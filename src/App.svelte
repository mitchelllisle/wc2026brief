<script>
  import { onMount } from 'svelte';

  let data = $state(null);
  let loading = $state(true);
  let error = $state(false);

  onMount(async () => {
    try {
      const res = await fetch(ENDPOINT);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
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

  const ENDPOINT = `${import.meta.env.BASE_URL}data/stats.json`;
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

  let ranked = $derived(data ? [...data.leaderboard] : []);
  let leaderName = $derived(ranked[0]?.name);
  let tabName = $derived(ranked.at(-1)?.name);
  let stamp = $derived(data ? formatStamp(data.generated_at) : '');
  let totalAlive = $derived(ranked.reduce((s, p) => s + p.teams_remaining, 0));
  let totalOut = $derived(ranked.reduce((s, p) => s + p.eliminated, 0));
  let projectedLeader = $derived(data?.projections?.managers?.[0] ?? null);
  let projectedTeam = $derived(data?.projections?.teams?.[0] ?? null);
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
    <div class="np-sub">FIFA World Cup 2026 · United States · Canada · Mexico</div>
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
        <h1 class="headline">{leaderName} stays <em>untouchable</em> as {tabName} eyes the Secretary role</h1>
        <p class="deck">{#if projectedLeader}{projectedLeader.name} now leads the title race at {formatProbability(projectedLeader.title_probability)}, with {projectedTeam?.flag ?? ''} {projectedTeam?.name ?? 'nobody yet'} the likeliest squad pick to carry someone deep.{:else}{ranked[0]?.teams_remaining} still alive and not a soul laying a glove on him — meanwhile the wooden spoon, and a 12-month stint as group Secretary handling plans and bookings, has {tabName}&apos;s name all over it.{/if}</p>
        <div class="report-cols">
          {#each data.summary as p}
            <p>{@html renderPara(p)}</p>
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
          <th class="l">#</th><th class="l">Manager</th>
          <th class="hide-sm">Survival</th><th>Alive</th><th class="hide-sm">Risk</th><th>Out</th><th class="hide-sm">W·D·L</th>
        </tr>
      </thead>
      <tbody>
        {#each ranked as p, i}
          {@const isLeader = p.name === leaderName}
          {@const isTab = p.name === tabName}
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
            <td class="hide-sm">
              <div class="pips">
                {#each pipOrder(data.squads[p.name] ?? []) as t}
                  <span
                    class="p {t.last_result === 'W' ? 'win' : t.last_result === 'D' ? 'draw' : t.last_result === 'L' ? 'loss' : 'none'}"
                    data-tip="{t.name} · {t.last_result ?? 'No result'}"
                    title="{t.name} · {t.last_result ?? 'No result'}"
                  ></span>
                {/each}
              </div>
            </td>
            <td class="num"><span class="v in">{p.teams_remaining}</span></td>
            <td class="num hide-sm"><span class="v risk">{p.at_risk}</span></td>
            <td class="num"><span class="v out">{p.eliminated}</span></td>
            <td class="num hide-sm"><span class="wdl"><b class="w">{p.record.w}</b>·<b>{p.record.d}</b>·<b class="l">{p.record.l}</b></span></td>
          </tr>
        {/each}
      </tbody>
    </table>

    {#if data.projections}
      <div class="sec"><span class="num">02</span><h2>Prediction Market</h2><span class="meta">Odds update with every result</span></div>
      <section class="projection-grid">
        {#each data.projections.managers as manager}
          <article class="projection-card" class:leader={manager.name === projectedLeader?.name}>
            <div class="projection-head">
              <span class="projection-name">{manager.name}</span>
              {#if manager.name === projectedLeader?.name}
                <span class="pill g">Favourite</span>
              {/if}
            </div>
            <div class="projection-odds">{formatProbability(manager.title_probability)}</div>
            <div class="projection-meta">
              <span>Expected next round</span>
              <strong>{manager.expected_teams_next_stage.toFixed(2)} teams</strong>
            </div>
            <div class="projection-meta">
              <span>Best shot</span>
              <strong>{manager.favourite_team ?? '--'}</strong>
            </div>
          </article>
        {/each}
      </section>

      <div class="projection-table-wrap">
        <table class="table projection-table">
          <thead>
            <tr>
              <th class="l">Team</th><th class="l">Manager</th><th>Next stage</th><th>Title odds</th>
            </tr>
          </thead>
          <tbody>
            {#each data.projections.teams.slice(0, 8) as team}
              <tr>
                <td class="c-name">
                  <div class="nm"><span>{team.flag}</span>{team.name}</div>
                  <div class="sub">{team.status === 'out' ? 'Eliminated' : team.status === 'at_risk' ? 'On the ropes' : 'Alive'}</div>
                </td>
                <td class="c-name">{team.manager}</td>
                <td class="num"><span class="v {normalizeStatus(team.status)}">{formatProbability(team.next_stage_probability)}</span></td>
                <td class="num"><span class="v in">{formatProbability(team.title_probability)}</span></td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}

    <div class="sec"><span class="num">03</span><h2>The Squads</h2><span class="meta">12 teams drafted each</span></div>
    <section class="squads">
      {#each ranked as p, i}
        <article class="sq" class:leader={p.name === leaderName}>
          <div class="sqh">
            <span class="idx">{String(i + 1).padStart(2, '0')}</span>
            <span class="nm">{p.name}</span>
            <span class="av">{p.teams_remaining}<small>/{p.teams_total}</small></span>
          </div>
          {#each data.squads[p.name] ?? [] as t}
            {@const status = normalizeStatus(t.status)}
            <div class="tm {status}">
              <span class="fl">{t.flag}</span>
              <span class="nm">{t.name}</span>
              <span class="rr {t.last_result ?? 'none'}">{t.last_result ?? '–'}</span>
              <span class="sd {status}"></span>
            </div>
          {/each}
        </article>
      {/each}
    </section>

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
