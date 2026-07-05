<script>
  import { onMount } from 'svelte';
  import BumpChart from './BumpChart.svelte';
  import KnockoutBracket from './KnockoutBracket.svelte';
  import { runBracket, computeTeamDepths } from './simulation.js';

  let data = $state(null);
  let history = $state(null);
  let loading = $state(true);
  let error = $state(false);
  let showTableModal = $state(false);
  let showAllChart = $state(false);
  let selectedManager = $state(null);

  const MANAGER_COLORS = {
    'Mitchell': '#6d12e6',
    'Kerrod':   '#9fe635',
    'Jay':      '#fb9a3c',
    'Ryan':     '#14c46b',
  };

  onMount(async () => {
    try {
      const [statsRes, historyRes] = await Promise.all([
        fetch(ENDPOINT),
        fetch(HISTORY_ENDPOINT).catch(() => null),
      ]);
      if (!statsRes.ok) throw new Error(`HTTP ${statsRes.status}`);
      data = await statsRes.json();
      if (historyRes?.ok) history = await historyRes.json();
    } catch (e) {
      console.error('Failed to load stats:', e);
      error = true;
    } finally {
      loading = false;
    }
  });

  function formatStamp(iso) {
    return new Date(iso).toLocaleString('en-AU', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Australia/Sydney',
    }) + ' AEST';
  }

  // HTML-escape then convert **bold** markers to <strong>
  function renderPara(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  }

  // HTML-escape then convert *italic* markers to <em>
  function renderHeadline(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\*(.*?)\*/g, '<em>$1</em>');
  }

  // Replace {leader}/{tab} tokens with live-computed names before rendering
  function injectHeadlineTokens(text, leader, tab) {
    return text.replace(/\{leader\}/g, leader ?? '').replace(/\{tab\}/g, tab ?? '');
  }

  const ENDPOINT = `${import.meta.env.BASE_URL}data/stats.json`;
  const HISTORY_ENDPOINT = `${import.meta.env.BASE_URL}data/history.json`;
  const LOGO_SRC = `${import.meta.env.BASE_URL}fifa-logo.svg`;
  const ORDER = { in: 0, at_risk: 1, risk: 1, out: 2 };
  const DAYS_TO_FINAL = 33;
  const FINAL_VENUE = 'MetLife Stadium';
  const MANAGER_ORDER = ['Mitchell', 'Kerrod', 'Jay', 'Ryan'];

  function normalizeStatus(status) {
    return status === 'risk' ? 'at_risk' : status;
  }

  function managerRagClass(teamsRemaining) {
    if (typeof teamsRemaining !== 'number') return '';
    if (teamsRemaining >= 9) return 'rag-in';
    if (teamsRemaining >= 6) return 'rag-risk';
    return 'rag-out';
  }

  function formatProbability(value) {
    return typeof value === 'number' ? `${value.toFixed(1)}%` : '--';
  }

  function managerTeams(name) {
    return [...(data?.projections?.teams ?? [])]
      .filter(t => t.manager === name)
      .sort((a, b) => b.title_probability - a.title_probability);
  }

  const pipOrder = (squad) => [...squad].sort((a, b) => {
    const aStatus = normalizeStatus(a.status);
    const bStatus = normalizeStatus(b.status);
    return ORDER[aStatus] - ORDER[bStatus];
  });

  function fallbackCode(teamName) {
    const compact = teamName.toUpperCase().replace(/[^A-Z]/g, '');
    return (compact.slice(0, 3) || 'TBD').padEnd(3, 'X');
  }

  function ownerFromResult(code, flag, squads) {
    if (!squads) return '';

    const ownersByFlag = new Map();
    const ownersByCode = new Map();

    for (const [owner, teams] of Object.entries(squads)) {
      for (const team of teams ?? []) {
        if (team?.flag) {
          const f = ownersByFlag.get(team.flag) ?? new Set();
          f.add(owner);
          ownersByFlag.set(team.flag, f);
        }
        if (team?.name) {
          const c = fallbackCode(team.name);
          const cs = ownersByCode.get(c) ?? new Set();
          cs.add(owner);
          ownersByCode.set(c, cs);
        }
      }
    }

    const byFlag = ownersByFlag.get(flag);
    if (byFlag?.size === 1) return [...byFlag][0];

    const byCode = ownersByCode.get(code);
    if (byCode?.size === 1) return [...byCode][0];

    return '';
  }

  const homeWin = (g) => g.hs > g.as;
  const awayWin = (g) => g.as > g.hs;

  let managerTitleMap = $derived(
    new Map(data?.projections?.managers?.map(m => [m.name, m.title_probability]) ?? [])
  );
  let managerDeltaMap = $derived(
    new Map(data?.projections?.managers?.map(m => [m.name, m.delta]) ?? [])
  );
  function titleDelta(name) {
    const d = managerDeltaMap.get(name);
    return (d == null || d === 0) ? null : d;
  }

  // ── Bracket-simulation stage bonus ───────────────────────────────────────
  // Runs the same strength-based knockout simulation as KnockoutBracket.svelte
  // and assigns each team a depth (0 = exits R32 … 5 = champion).
  // A manager's stage score = Σ (depth × team_strength) across their teams,
  // rewarding both advancing further AND having multiple teams in late rounds.
  // Weight 0.5 blends the bonus into the base title_probability without
  // overwhelming the underlying team-quality signal.
  const STAGE_WEIGHT = 0.5;

  let bracketSim = $derived.by(() => {
    const teams = data?.projections?.teams;
    if (!teams?.length) return null;
    return runBracket(teams);
  });

  let teamDepths = $derived(
    bracketSim ? computeTeamDepths(bracketSim) : new Map()
  );

  // Per-manager sum of (predicted_round_depth × team_title_probability)
  let managerStageScoreMap = $derived.by(() => {
    const map = new Map();
    for (const t of (data?.projections?.teams ?? [])) {
      if (!t.manager) continue;
      const depth = teamDepths.get(t.name) ?? 0;
      map.set(t.manager, (map.get(t.manager) ?? 0) + depth * t.title_probability);
    }
    return map;
  });

  // Outlook column: top 1–2 teams per manager by predicted bracket depth,
  // filtered to QF or deeper (depth ≥ 2); falls back to the single best team
  // if none reach the quarters. Explains why the stage bonus moves the ranking.
  const STAGE_LABELS  = ['R32', 'Last 16', 'QF', 'Semi-final', 'Finalist', 'Champion'];
  const STAGE_CLASSES = ['ol-dim', 'ol-dim', 'ol-mid', 'ol-sf', 'ol-final', 'ol-champ'];
  function stageLabel(depth)      { return STAGE_LABELS[depth]  ?? '--'; }
  function stageDepthClass(depth) { return STAGE_CLASSES[depth] ?? 'ol-dim'; }

  let managerOutlookMap = $derived.by(() => {
    const map = new Map();
    for (const t of (data?.projections?.teams ?? [])) {
      if (!t.manager) continue;
      const depth = teamDepths.get(t.name) ?? 0;
      const arr = map.get(t.manager) ?? [];
      arr.push({ name: t.name, flag: t.flag ?? '', depth, prob: t.title_probability });
      map.set(t.manager, arr);
    }
    const result = new Map();
    for (const [mgr, teams] of map) {
      teams.sort((a, b) => b.depth - a.depth || b.prob - a.prob);
      const notable = teams.filter(t => t.depth >= 2); // QF or deeper
      result.set(mgr, notable.length > 0 ? notable.slice(0, 2) : teams.slice(0, 1));
    }
    return result;
  });

  // Adjusted strength = base title_probability + 0.5 × stage bonus
  // (base scores remain unchanged; this is additive on top)
  let managerAdjustedStrengthMap = $derived(
    new Map(
      [...managerTitleMap.entries()].map(([name, tp]) => [
        name,
        +(tp + (managerStageScoreMap.get(name) ?? 0) * STAGE_WEIGHT).toFixed(1),
      ])
    )
  );

  let ranked = $derived(
    data ? [...data.leaderboard].sort((a, b) =>
      (managerAdjustedStrengthMap.get(b.name) ?? 0) - (managerAdjustedStrengthMap.get(a.name) ?? 0)
    ) : []
  );
  let leaderName = $derived(ranked[0]?.name);
  let tabName = $derived(ranked.at(-1)?.name);
  let stamp = $derived(data ? formatStamp(data.generated_at) : '');
  let totalAlive = $derived(ranked.reduce((s, p) => s + p.teams_remaining, 0));
  let totalOut = $derived(ranked.reduce((s, p) => s + p.eliminated, 0));
  let projectedLeader = $derived(data?.projections?.managers?.find(m => m.name === ranked[0]?.name) ?? null);
  let projectedTeam = $derived(
    projectedLeader?.favourite_team
      ? (data?.projections?.teams?.find(t => t.name === projectedLeader.favourite_team) ?? null)
      : null
  );
  let projectionDeck = $derived(
    projectedLeader
      ? `${projectedLeader.name} leads on title strength with ${projectedTeam?.flag ?? ''} ${projectedTeam?.name ?? 'nobody yet'} his highest-rated individual pick.`
      : `${ranked[0]?.teams_remaining} still alive and not a soul laying a glove on him — meanwhile the wooden spoon, and a 12-month stint as group Secretary handling plans and bookings, has ${tabName}'s name all over it.`
  );
  let teamFlagMap = $derived(
    new Map(data?.projections?.teams?.map(t => [t.name, t.flag]) ?? [])
  );
  let teamStrengthMap = $derived(
    new Map(data?.projections?.teams?.map(t => [t.name, t.title_probability]) ?? [])
  );
  let teamFormMap = $derived.by(() => {
    const map = new Map();
    for (const teams of Object.values(data?.squads ?? {})) {
      for (const t of teams) {
        map.set(t.name, (t.form ?? []).map(e => typeof e === 'string' ? { result: e } : e));
      }
    }
    return map;
  });
  let teamDeltaMap = $derived(
    new Map(data?.projections?.teams?.map(t => [t.name, t.delta]) ?? [])
  );
  function teamStrengthDelta(name) {
    const d = teamDeltaMap.get(name);
    return (d == null || d === 0) ? null : d;
  }


  function injectFlags(text) {
    if (teamFlagMap.size === 0) return text;
    const names = [...teamFlagMap.keys()].sort((a, b) => b.length - a.length);
    let result = text;
    for (const name of names) {
      const flag = teamFlagMap.get(name);
      const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      result = result.replace(
        new RegExp(`(?<!\\p{L})${escaped}(?!\\p{L})`, 'gu'),
        `${flag} ${name}`
      );
    }
    return result;
  }
</script>

<div class="ribbon"><i class="v"></i><i class="m"></i><i class="r"></i><i class="l"></i><i class="g"></i></div>
<div class="crawl" aria-label="Recent full-time results ticker">
  <div class="crawl-tag"><span class="dot"></span> Full-Time</div>
  <div class="crawl-track">
    {#if data?.recent_results}
      {#each [...data.recent_results, ...data.recent_results] as g}
          {@const hOwner = ownerFromResult(g.h_code, g.h_flag, data.squads)}
          {@const aOwner = ownerFromResult(g.a_code, g.a_flag, data.squads)}
        <span class="gm">
          <span class="grp">{g.group}</span>
            <span class="side" class:win={homeWin(g)}><span class="fl">{g.h_flag}</span>{g.h_code}{#if hOwner}<span class="own">({hOwner})</span>{/if}</span>
          <span class="sc">{g.hs}–{g.as}</span>
            <span class="side" class:win={awayWin(g)}>{g.a_code}{#if aOwner}<span class="own">({aOwner})</span>{/if}<span class="fl">{g.a_flag}</span></span>
          <span class="ft">FT</span>
        </span>
      {/each}
    {/if}
  </div>
</div>

<div class="wrap">
  <header class="nameplate">
    <div class="np-top">
      <span>Vol. I · No. 3 — Group Stage</span>
      {#if loading}
        <span class="mid">● Updating…</span>
      {:else if error}
        <span class="mid">● Feed unavailable</span>
      {:else}
        <span class="mid">● Updated {stamp}</span>
      {/if}
      <span>Last team standing wins</span>
    </div>
    <div class="np-title">
      <div class="brand-logo" aria-hidden="true">
        <img src={LOGO_SRC} alt="FIFA World Cup 2026 logo" />
      </div>
      <h1>The [Joint] <b>Sweep</b> Desk</h1>
    </div>
    <div class="np-sub">FIFA World Cup 2026 · 🇺🇸 United States · 🇨🇦 Canada · 🇲🇽 Mexico</div>
  </header>

  {#if error}
    <section class="lede">
      <div class="lede-main">
        <div class="kicker-row">
          <span class="kick">Feed Status</span>
          <span class="byline">The Sweep Desk</span>
        </div>
        <h1 class="headline">Stats unavailable right now.</h1>
        <p class="deck">Couldn&apos;t load the latest sweep file. Check the data source and refresh.</p>
      </div>
      <aside class="lede-side">
        <div class="side-label">At a glance</div>
        <div class="glance">
          <div class="gl"><div class="lab">Teams alive<small>of 48 drafted</small></div><div class="val g">--</div></div>
          <div class="gl"><div class="lab">Eliminated<small>copped it</small></div><div class="val r">--</div></div>
          <div class="gl"><div class="lab">Final<small>{FINAL_VENUE}</small></div><div class="val">{DAYS_TO_FINAL}<small>days</small></div></div>
          {#each MANAGER_ORDER as manager}
            <div class="gl"><div class="lab">{manager}<small>teams left</small></div><div class="val">--</div></div>
          {/each}
        </div>
      </aside>
    </section>
  {:else if data}
    <section class="lede">
      <div class="lede-main">
        <div class="kicker-row">
          <span class="kick">Match Report</span>
          <span class="byline">The Sweep Desk · Auto Anchor · {stamp}</span>
        </div>
        <h1 class="headline">{@html data.headline ? renderHeadline(injectHeadlineTokens(data.headline, leaderName, tabName)) : `${leaderName} leads as ${tabName} eyes the Secretary role`}</h1>
        <p class="deck">{projectionDeck}</p>
        <div class="report-cols">
          {#each data.summary as p}
            <p>{@html renderPara(injectFlags(p))}</p>
          {/each}
        </div>
      </div>
      <aside class="lede-side">
        <div class="side-label">At a glance</div>
        <div class="glance">
          <div class="gl"><div class="lab">Teams alive<small>of 48 drafted</small></div><div class="val g">{totalAlive}</div></div>
          <div class="gl"><div class="lab">Eliminated<small>copped it</small></div><div class="val r">{totalOut}</div></div>
          <div class="gl"><div class="lab">Final<small>{FINAL_VENUE}</small></div><div class="val">{DAYS_TO_FINAL}<small>days</small></div></div>
          {#each MANAGER_ORDER as manager}
            {@const p = ranked.find((x) => x.name.toLowerCase() === manager.toLowerCase())}
            <div class="gl"><div class="lab">{p?.name ?? manager}<small>teams left</small></div><div class="val {managerRagClass(p?.teams_remaining)}">{p?.teams_remaining ?? '--'}</div></div>
          {/each}
        </div>
      </aside>
    </section>

    <div class="sec"><span class="num">01</span><h2>Danger Rankings</h2><span class="meta">First out becomes Secretary for 12 months</span></div>
    <table class="table">
      <thead>
        <tr>
          <th class="l">#</th><th class="l">Manager</th><th>Strength <span class="tooltip-wrap th-tip"><span class="info-icon">ⓘ</span><div class="tooltip-box"><p class="tooltip-title">What is Strength?</p><p class="tooltip-desc" style="margin-bottom:0">A composite index, not a probability. Base score = sum of each team's strength (form + FIFA rank, normalised to 100). A stage bonus is added: each team earns its strength score × predicted knockout rounds survived — so teams projected deep in the bracket count more, and having multiple teams in late rounds compounds the advantage.</p></div></span></th>
          <th class="hide-sm">Survival</th><th class="c-outlook-hd hide-sm">Outlook</th><th>Alive</th><th>Out</th><th class="hide-sm">W·D·L</th>
        </tr>
      </thead>
      <tbody>
        {#each ranked as p, i}
          {@const isLeader = p.name === leaderName}
          {@const isTab = p.name === tabName}
          {@const strDelta = titleDelta(p.name)}
          <tr class:leader={isLeader} class:tab={isTab}>
            <td class="c-rank"><span class="n">{i + 1}</span></td>
            <td class="c-name">
              <div class="nm">
                {p.name}
                {#if isLeader}<span class="pill g">Leader</span>
                {:else if isTab}<span class="pill r">Secretary duty</span>{/if}
              </div>
              <div class="sub">{p.teams_remaining} of {p.teams_total} surviving</div>
            </td>
            <td class="c-str">
              <span class="str-val {strDelta !== null ? (strDelta > 0 ? 'up' : 'dn') : ''}">{managerAdjustedStrengthMap.get(p.name) ?? '--'}</span>
              {#if strDelta !== null}
                <span class="str-chg {strDelta > 0 ? 'up' : 'dn'}" title="Change in base score (excludes stage bonus)">{strDelta > 0 ? '▲' : '▼'} {Math.abs(strDelta)} <span class="str-chg-lbl">base</span></span>
              {/if}
            </td>
            <td class="hide-sm">
              <div class="pip-count">{p.teams_remaining}/{p.teams_total}</div>
              <div class="pips">
                {#each pipOrder(data.squads[p.name] ?? []) as t}
                  {@const teamStatus = normalizeStatus(t.status)}
                  <span
                    class="p {teamStatus === 'out' ? 'out' : 'in'}"
                    data-tip="{t.name} · {teamStatus === 'out' ? 'Eliminated' : 'Alive'}"
                    title="{t.name} · {teamStatus === 'out' ? 'Eliminated' : 'Alive'}"
                  ></span>
                {/each}
              </div>
            </td>
            <td class="c-outlook hide-sm">
              {#each managerOutlookMap.get(p.name) ?? [] as pick}
                <div class="ol-row" title="{pick.name}: predicted {stageLabel(pick.depth)}" aria-label="{pick.name}: predicted {stageLabel(pick.depth)}">
                  <span class="ol-flag" aria-hidden="true">{pick.flag}</span>
                  <span class="ol-stage {stageDepthClass(pick.depth)}">{stageLabel(pick.depth)}</span>
                </div>
              {/each}
            </td>
            <td class="num"><span class="v in">{p.teams_remaining}</span></td>
            <td class="num"><span class="v out">{p.eliminated}</span></td>
            <td class="num hide-sm"><span class="wdl"><b class="w">{p.record.w}</b>·<b>{p.record.d}</b>·<b class="l">{p.record.l}</b></span></td>
          </tr>
        {/each}
      </tbody>
    </table>

    <div class="sec"><span class="num">02</span><h2>The Squads</h2><span class="meta">12 teams drafted each</span></div>
    <section class="squads">
      {#each ranked as p, i}
        {@const squadTeams = [...(data.squads[p.name] ?? [])].sort((a, b) => (teamStrengthMap.get(b.name) ?? 0) - (teamStrengthMap.get(a.name) ?? 0))}
        <article class="sq" class:leader={p.name === leaderName}>
          <div class="sqh">
            <span class="idx">{String(i + 1).padStart(2, '0')}</span>
            <span class="nm">{p.name}</span>
            <span class="av">{p.teams_remaining}<small>/{p.teams_total}</small></span>
          </div>
          <table class="sq-tbl">
            <thead>
              <tr>
                <th colspan="2" class="l">Team</th>
                <th>Str</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {#each squadTeams as t}
                {@const status = normalizeStatus(t.status)}
                {@const strength = teamStrengthMap.get(t.name)}
                {@const tsDelta = teamStrengthDelta(t.name)}
                <tr class={status}>
                  <td class="sq-fl">{t.flag}</td>
                  <td class="sq-nm">{t.name}</td>
                  <td class="sq-ts">
                    <span class="ts">{strength != null ? strength.toFixed(1) : '–'}</span>
                    {#if tsDelta !== null}
                      <span class="ts-delta {tsDelta > 0 ? 'up' : 'dn'}">{tsDelta > 0 ? '▲' : '▼'} {Math.abs(tsDelta)}</span>
                    {/if}
                  </td>
                  <td class="sq-st">{status === 'out' ? 'Out' : status === 'at_risk' ? 'At risk' : 'Alive'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </article>
      {/each}
    </section>

    {#if data.projections}
      <div class="sec">
        <span class="num">03</span>
        <h2>Title Race</h2>
        <span class="meta">Powered by live FIFA rankings · updates with every result</span>
      </div>

      <!-- Manager projection cards — click to highlight that manager's teams in the chart -->
      <section class="projection-grid">
        {#each data.projections.managers as manager}
          {@const isSelected = selectedManager === manager.name}
          {@const selColor = MANAGER_COLORS[manager.name]}
          <article
            class="projection-card"
            class:leader={manager.name === projectedLeader?.name}
            class:mgr-selected={isSelected}
            style:--mgr-color={selColor}
            onclick={() => selectedManager = isSelected ? null : manager.name}
            role="button"
            tabindex="0"
            onkeydown={e => e.key === 'Enter' && (selectedManager = isSelected ? null : manager.name)}
            aria-pressed={isSelected}
          >
            <div class="projection-head">
              <span class="projection-name">{manager.name}</span>
              <div class="projection-head-right">
                {#if manager.name === projectedLeader?.name}
                  <span class="pill g">Favourite</span>
                {/if}
                <span class="tooltip-wrap">
                  <span class="info-icon">ⓘ</span>
                  <div class="tooltip-box">
                    <p class="tooltip-title">What is title strength?</p>
                    <p class="tooltip-desc">A composite index, not a probability. Each team is scored on three signals — stage reached, current form (W/D/L, goal diff), and FIFA world ranking — then all 48 scores are normalised to sum to 100. A manager's total is the sum of their teams' scores. Higher means stronger title credentials relative to the field, not a percentage chance of winning.</p>
                    <table class="tooltip-table">
                      <tbody>
                        {#each managerTeams(manager.name) as team}
                          <tr class="tooltip-row {normalizeStatus(team.status)}">
                            <td class="tooltip-team">{team.flag} {team.name}{#if team.fifa_rank}<span class="tooltip-rank"> #{team.fifa_rank}</span>{/if}</td>
                            <td class="tooltip-prob">{team.title_probability.toFixed(1)}</td>
                          </tr>
                        {/each}
                      </tbody>
                    </table>
                  </div>
                </span>
              </div>
            </div>
            <div class="best-shot">
              {#if manager.favourite_team}
                {@const bestTeam = managerTeams(manager.name).find(t => t.name === manager.favourite_team)}
                <div class="bs-flag">{teamFlagMap.get(manager.favourite_team) ?? ''}</div>
                <div class="bs-name">
                  {manager.favourite_team}
                  {#if bestTeam}<span class="bs-score">{bestTeam.title_probability.toFixed(1)}</span>{/if}
                </div>
              {:else}
                <div class="bs-name">—</div>
              {/if}
            </div>
            <div class="bs-label">Best shot</div>
          </article>
        {/each}
      </section>

      <!-- Team bump chart (replaces the teams table inline) -->
      {#if history?.snapshots?.length > 0}
        {@const totalTeams = history.snapshots[history.snapshots.length - 1]?.teams?.length ?? 0}
        <div class="bump-section">
          <BumpChart snapshots={history.snapshots} topN={showAllChart ? totalTeams : 10} highlightManager={selectedManager} />
          <div class="bump-footer">
            <button class="show-table-link" onclick={() => showAllChart = !showAllChart}>
              {showAllChart ? 'Show top 10' : `Show all ${totalTeams} teams`}
            </button>
            <button class="show-table-link" onclick={() => showTableModal = true}>
              View full team rankings
            </button>
          </div>
        </div>
      {:else}
        <!-- Fallback: inline teams table if no history loaded -->
        <div class="projection-table-wrap">
          <table class="table projection-table">
            <thead>
              <tr>
                <th class="l">Team</th><th class="hide-sm">FIFA</th><th class="l">Manager</th><th class="hide-sm">Form</th><th>Title Strength</th><th class="hide-sm">Status</th>
              </tr>
            </thead>
            <tbody>
              {#each data.projections.teams.slice(0, 10) as team}
                <tr>
                  <td class="c-name"><div class="nm"><span>{team.flag}</span>{team.name}</div></td>
                  <td class="num hide-sm">{#if team.fifa_rank}<span class="fifa-rank">#{team.fifa_rank}</span>{:else}<span class="fifa-rank unranked">--</span>{/if}</td>
                  <td class="c-name">{team.manager}</td>
                  <td class="num hide-sm"><span class="frm">{#each (teamFormMap.get(team.name) ?? []).slice(-5) as entry}<span class="fr {entry.result}" data-tip={entry.opponent ? `${entry.opponent} ${entry.score}` : undefined}></span>{/each}</span></td>
                  <td class="num"><span class="v {normalizeStatus(team.status)}">{formatProbability(team.title_probability)}</span></td>
                  <td class="num hide-sm"><span class="v {normalizeStatus(team.status)}">{team.status === 'out' ? 'Out' : team.status === 'at_risk' ? 'At risk' : 'Alive'}</span></td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}

    <div class="sec"><span class="num">04</span><h2>Knockout Predictor</h2><span class="meta">Strength-based · FIFA rank tiebreaker</span></div>
    <KnockoutBracket teams={data.projections.teams} managerColors={MANAGER_COLORS} />

    {/if}

    <!-- Team rankings modal -->
    {#if showTableModal}
      <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
      <div class="modal-overlay" onclick={() => showTableModal = false} role="presentation">
        <div class="modal-box" onclick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Team Rankings">
          <div class="modal-head">
            <h3>Team Rankings</h3>
            <button class="modal-close" onclick={() => showTableModal = false} aria-label="Close">✕</button>
          </div>
          {#if data?.projections?.teams}
            <table class="table modal-table">
              <thead>
                <tr>
                  <th class="l">Team</th><th class="hide-sm">FIFA</th><th class="l">Manager</th><th class="hide-sm">Form</th><th>Title Strength</th><th class="hide-sm">Status</th>
                </tr>
              </thead>
              <tbody>
                {#each data.projections.teams as team}
                  <tr>
                    <td class="c-name">
                      <div class="nm"><span>{team.flag}</span>{team.name}</div>
                    </td>
                    <td class="num hide-sm">
                      {#if team.fifa_rank}
                        <span class="fifa-rank">#{team.fifa_rank}</span>
                      {:else}
                        <span class="fifa-rank unranked">--</span>
                      {/if}
                    </td>
                    <td class="c-name">{team.manager}</td>
                    <td class="num hide-sm">
                      <span class="frm">
                        {#each (teamFormMap.get(team.name) ?? []).slice(-5) as entry}
                          <span class="fr {entry.result}" data-tip={entry.opponent ? `${entry.opponent} ${entry.score}` : undefined}></span>
                        {/each}
                      </span>
                    </td>
                    <td class="num">
                      <div class="adv-cell">
                        <span class="v {normalizeStatus(team.status)}">{formatProbability(team.title_probability)}</span>
                        {#if team.status !== 'out' && team.title_breakdown}
                          {@const b = team.title_breakdown}
                          <span class="tooltip-wrap">
                            <span class="info-icon">ⓘ</span>
                            <div class="tooltip-box adv-tooltip-box">
                              <p class="tooltip-title">Title Strength — how it's calculated</p>
                              <p class="tooltip-desc">A composite index of each team's tournament winning potential. All 48 teams are scored and normalised to sum to 100 — higher means more likely to win.</p>
                              <p class="tooltip-section">Components <span class="tooltip-section-note">(each scored 0–1)</span></p>
                              <table class="tooltip-table">
                                <tbody>
                                  <tr class="tooltip-row"><td class="tooltip-team">Form <span class="tooltip-dim">points ÷ 24 + goals/game × 2% · {Math.round(b.form_weight * 100)}% weight</span></td><td class="tooltip-prob">{b.form_score}</td></tr>
                                  <tr class="tooltip-row"><td class="tooltip-team">Stage <span class="tooltip-dim">{b.stage_label} · 30% weight</span></td><td class="tooltip-prob">{b.stage_score}</td></tr>
                                  <tr class="tooltip-row"><td class="tooltip-team">Rank <span class="tooltip-dim">FIFA #{team.fifa_rank ?? '—'} · {Math.round(b.rank_weight * 100)}% weight</span></td><td class="tooltip-prob">{b.rank_score}</td></tr>
                                </tbody>
                              </table>
                              <div class="tooltip-result">
                                <span>Title Strength <span class="tooltip-dim" style="font-weight:normal">(normalised)</span></span>
                                <strong>{team.title_probability}%</strong>
                              </div>
                            </div>
                          </span>
                        {/if}
                      </div>
                    </td>
                    <td class="num hide-sm"><span class="v {normalizeStatus(team.status)}">{team.status === 'out' ? 'Out' : team.status === 'at_risk' ? 'At risk' : 'Alive'}</span></td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        </div>
      </div>
    {/if}
    <div class="ribbon ribbon-foot"><i class="v"></i><i class="m"></i><i class="r"></i><i class="l"></i><i class="g"></i></div>
    <div class="footrow">
      <div class="legend">
        <span class="li"><span class="sd in"></span> In</span>
        <span class="li"><span class="sd at_risk"></span> At risk</span>
        <span class="li"><span class="sd out"></span> Out</span>
      </div>
      <span>[Joint] Sweep · First manager eliminated becomes Secretary for 12 months (organising plans and bookings)</span>
    </div>
  {/if}
</div>
