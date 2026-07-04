<script>
  import { R32 } from './simulation.js';

  let { teams = [], managerColors = {}, actualResults = new Map() } = $props();

  // Fast name-keyed lookup (reactive so downstream $derived re-run if prop changes)
  const T = $derived(new Map(teams.map(t => [t.name, t])));

  // Pick winner: higher strength wins; lower FIFA rank (= better) breaks exact ties
  function pick(a, b) {
    const sa = T.get(a)?.title_probability ?? 0;
    const sb = T.get(b)?.title_probability ?? 0;
    if (sa !== sb) return sa > sb ? a : b;
    return (T.get(a)?.fifa_rank ?? 999) <= (T.get(b)?.fifa_rank ?? 999) ? a : b;
  }


  function sim(pairs) {
    return pairs.map(([a, b]) => ({ a, b, w: pick(a, b) }));
  }
  function adv(res) {
    const p = [];
    for (let i = 0; i < res.length; i += 2) p.push([res[i].w, res[i + 1].w]);
    return sim(p);
  }

  const r32   = $derived(sim(R32));
  const r16   = $derived(adv(r32));
  const qf    = $derived(adv(r16));
  const sf    = $derived(adv(qf));
  const fin   = $derived(adv(sf));
  const champ = $derived(fin[0].w);

  // Helpers
  function flag(n)  { return T.get(n)?.flag ?? '🏳️'; }
  function str(n)   { return (T.get(n)?.title_probability ?? 0).toFixed(1); }
  function rank(n)  { return T.get(n)?.fifa_rank ?? null; }
  function mgrOf(n) { return T.get(n)?.manager ?? null; }
  function mc(n)    { const m = mgrOf(n); return m ? (managerColors[m] ?? null) : null; }
  function delta(n) { return T.get(n)?.delta ?? null; }
  function actualW(a, b) { return actualResults.get([a, b].sort().join('|')) ?? null; }

  // Group array into consecutive pairs
  function pair(arr) {
    const out = [];
    for (let i = 0; i < arr.length; i += 2) out.push(arr.slice(i, i + 2));
    return out;
  }

  // Which managers have teams competing in a given round's matches (both sides of each matchup)
  function managersIn(matches) {
    const s = new Set();
    for (const m of matches) {
      const ma = mgrOf(m.a); if (ma) s.add(ma);
      const mb = mgrOf(m.b); if (mb) s.add(mb);
    }
    return s;
  }

  // Consistent manager display order
  const MGR_ORDER = ['Mitchell', 'Kerrod', 'Jay', 'Ryan'];
  const MGR_INITIAL = { Mitchell: 'M', Kerrod: 'K', Jay: 'J', Ryan: 'R' };

  const placings = $derived.by(() => {
    const depthKeys = ['r32', 'r16', 'qf', 'sf', 'fin'];
    const roundsMap = { r32, r16, qf, sf, fin };
    const best = {};
    for (let i = 0; i < depthKeys.length; i++) {
      for (const m of roundsMap[depthKeys[i]]) {
        for (const team of [m.a, m.b]) {
          const mgr = mgrOf(team);
          if (!mgr) continue;
          if (!best[mgr] || i > best[mgr].idx) best[mgr] = { idx: i, teams: [team] };
          else if (i === best[mgr].idx && !best[mgr].teams.includes(team)) best[mgr].teams.push(team);
        }
      }
    }
    const cm = mgrOf(champ);
    if (cm) best[cm] = { idx: 6, teams: [champ] };
    const MEDALS = ['🥇', '🥈', '🥉', '💀'];
    return Object.entries(best)
      .sort(([,a],[,b]) => b.idx - a.idx)
      .map(([mgr, { teams }], i) => {
        const rep = teams.reduce((b, t) => {
          const sb = T.get(b)?.title_probability ?? 0;
          const st = T.get(t)?.title_probability ?? 0;
          if (st !== sb) return st > sb ? t : b;
          return (T.get(t)?.fifa_rank ?? 999) <= (T.get(b)?.fifa_rank ?? 999) ? t : b;
        });
        return { mgr, team: rep, color: managerColors[mgr] ?? null, medal: MEDALS[i] ?? '💀' };
      });
  });
  const finMgrs    = $derived(managersIn(fin));

  const roundData = $derived([
    { id: 'r32', label: 'R32', segs: pair(r32), mgrs: managersIn(r32) },
    { id: 'r16', label: 'R16', segs: pair(r16), mgrs: managersIn(r16) },
    { id: 'qf',  label: 'QF',  segs: pair(qf),  mgrs: managersIn(qf)  },
    { id: 'sf',  label: 'SF',  segs: pair(sf),  mgrs: managersIn(sf)  },
  ]);

  // ── Predicted standings sentence ──────────────────────────
  const summaryLine = $derived(() => {
    // For each manager, find their deepest round as a COMPETITOR (both sides of matchups)
    const depthKeys = ['r32', 'r16', 'qf', 'sf', 'fin'];
    const roundsMap = { r32, r16, qf, sf, fin };

    const best = {}; // mgr → { idx: number, key: string, teams: string[] }

    for (let i = 0; i < depthKeys.length; i++) {
      const key = depthKeys[i];
      const teamsHere = roundsMap[key].flatMap(m => [m.a, m.b]);
      for (const team of teamsHere) {
        const mgr = mgrOf(team);
        if (!mgr) continue;
        if (!best[mgr] || i > best[mgr].idx) {
          best[mgr] = { idx: i, key, teams: [team] };
        } else if (i === best[mgr].idx && !best[mgr].teams.includes(team)) {
          best[mgr].teams.push(team);
        }
      }
    }

    // Champion overrides everything
    const cm = mgrOf(champ);
    if (cm) best[cm] = { idx: 6, key: 'win', teams: [champ] };

    const depthVal = { r32:1, r16:2, qf:3, sf:4, fin:5, win:6 };
    const rndLabel = { r32:'R32', r16:'R16', qf:'quarter-finals', sf:'semi-finals', fin:'the final', win:'the final' };

    const sorted = Object.entries(best)
      .sort(([,a],[,b]) => depthVal[b.key] - depthVal[a.key])
      .map(([mgr, info]) => ({ mgr, key: info.key, teams: info.teams }));

    if (sorted.length < 4) return '';

    const [p1, p2, p3, p4] = sorted;

    const tf = (t) => t.map(n => `${flag(n)} ${n}`).join(' and ');
    const plural = (t) => t.length > 1 ? 'exit' : 'exits';

    return `${p1.mgr} wins it all with ${tf(p1.teams)}`
      + `; ${p2.mgr} finishes runner-up — ${tf(p2.teams)} ${plural(p2.teams)} in ${rndLabel[p2.key]}`
      + `; ${p3.mgr} goes out in the ${rndLabel[p3.key]} (${tf(p3.teams)})`
      + `; ${p4.mgr} finishes last — ${tf(p4.teams)} ${plural(p4.teams)} in the ${rndLabel[p4.key]}.`;
  });
</script>

<div class="bkt-scroll">
  <!-- Champion + summary sits above the bracket -->
  <div class="champ-strip">
    <div class="champ-cards">
      {#each placings as p, i}
        <div class="champ-card" style:--cc={p.color ?? 'var(--txt-3)'} style:opacity={['1','0.88','0.72','0.52'][i]}>
          <span class="champ-flag">{flag(p.team)}</span>
          <div class="champ-info">
            <span class="champ-name">{p.team}</span>
            <span class="champ-mgr" style:color={p.color}>{p.mgr}</span>
          </div>
          {#if rank(p.team)}
            <span class="champ-rank">#{rank(p.team)}</span>
          {/if}
          <span class="champ-trophy">{p.medal}</span>
        </div>
      {/each}
    </div>
    <p class="champ-summary">{summaryLine()}</p>
    <p class="champ-note">Predicted by strength score · ties broken by FIFA ranking</p>
  </div>

  <div class="bkt-body">

    {#each roundData as rnd}
      <div class="bkt-col bkt-{rnd.id}">
        <div class="rnd-hdr">
          <div class="rnd-lbl">{rnd.label}</div>
          <div class="rnd-mgrs">
            {#each MGR_ORDER as mgr}
              {@const active = rnd.mgrs.has(mgr)}
              <span
                class="rnd-dot"
                class:rnd-dot-out={!active}
                style:color={active ? (managerColors[mgr] ?? 'var(--txt-3)') : undefined}
                title={mgr}
              >{MGR_INITIAL[mgr]}</span>
            {/each}
          </div>
        </div>
        <div class="bkt-ms">
          {#each rnd.segs as seg}
            <div class="bkt-seg">
              {#each seg as m}
                <div class="bkt-m">
                  {@render trow(m.a, m.w === m.a, actualW(m.a, m.b))}
                  {@render trow(m.b, m.w === m.b, actualW(m.a, m.b))}
                </div>
              {/each}
            </div>
          {/each}
        </div>
      </div>
    {/each}

    <!-- Final column -->
    <div class="bkt-col bkt-fin">
      <div class="rnd-hdr">
        <div class="rnd-lbl">Final</div>
        <div class="rnd-mgrs">
          {#each MGR_ORDER as mgr}
            {@const active = finMgrs.has(mgr)}
            <span
              class="rnd-dot"
              class:rnd-dot-out={!active}
              style:color={active ? (managerColors[mgr] ?? 'var(--txt-3)') : undefined}
              title={mgr}
            >{MGR_INITIAL[mgr]}</span>
          {/each}
        </div>
      </div>
      <div class="bkt-ms bkt-fin-ms">
        {#each fin as m}
          <div class="bkt-m bkt-fin-m">
            {@render trow(m.a, m.w === m.a, actualW(m.a, m.b))}
            {@render trow(m.b, m.w === m.b, actualW(m.a, m.b))}
          </div>
        {/each}
      </div>
    </div>

  </div><!-- /bkt-body -->
</div><!-- /bkt-scroll -->

{#snippet trow(name, isWin, aw)}
  {@const col = mc(name)}
  {@const d = delta(name)}
  {@const isActualWin  = aw !== null && aw === name}
  {@const isActualLose = aw !== null && aw !== name}
  <div class="bkt-t"
       class:win={isWin}
       class:lose={!isWin}
       class:actual-win={isActualWin}
       class:actual-lose={isActualLose}
       style:--mc={col ?? 'transparent'}>
    <span class="bkt-fl">{flag(name)}</span>
    <span class="bkt-nm">{name}</span>
    <span class="bkt-sc">{str(name)}</span>
    {#if d !== null && d !== 0}
      <span class="bkt-dl" class:up={d > 0} class:dn={d < 0}>{d > 0 ? '▲' : '▼'}</span>
    {/if}
    {#if isActualWin && !isWin}
      <span class="bkt-verdict bkt-upset" title="Upset — won against prediction" aria-label="Upset: won against prediction">⚡</span>
    {:else if isActualLose && isWin}
      <span class="bkt-verdict bkt-wrong" title="Predicted winner — actually lost" aria-label="Wrong prediction: predicted winner actually lost">✗</span>
    {:else if isActualWin && isWin}
      <span class="bkt-verdict bkt-correct" title="Prediction correct" aria-label="Prediction correct">✓</span>
    {/if}
  </div>
{/snippet}

<style>
  /* ── Scroll shell ──────────────────────────────────────── */
  .bkt-scroll {
    overflow-x: auto;
    margin-top: 24px;
    -webkit-overflow-scrolling: touch;
  }

  /* ── Bracket row of columns ────────────────────────────── */
  .bkt-body {
    display: flex;
    align-items: stretch;
    gap: 28px;
    min-width: 999px;
    padding-bottom: 2px;
  }

  /* ── One round column ──────────────────────────────────── */
  .bkt-col {
    flex: 1;
    min-width: 150px;
    display: flex;
    flex-direction: column;
    overflow: visible;
  }

  /* ── Round header: label + manager dots ─────────────────── */
  .rnd-hdr {
    flex-shrink: 0;
    margin-bottom: 6px;
    border-bottom: 1px solid var(--line-soft);
    padding-bottom: 6px;
  }

  .rnd-lbl {
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--txt-3);
    text-align: center;
    margin-bottom: 5px;
  }

  .rnd-mgrs {
    display: flex;
    gap: 4px;
    justify-content: center;
    align-items: center;
  }

  .rnd-dot {
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 900;
    flex-shrink: 0;
    line-height: 1;
    letter-spacing: 0;
  }

  .rnd-dot-out {
    color: var(--txt-3) !important;
    opacity: 0.25;
  }

  /* ── Match container ────────────────────────────────────── */
  .bkt-ms {
    flex: 1;
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: visible;
  }

  /* ── Segment: two matches → one next-round match ──────── */
  .bkt-seg {
    flex: 1;
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: visible;
  }

  /* ── Individual match ──────────────────────────────────── */
  .bkt-m {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    position: relative;
    overflow: visible;
    gap: 2px;
    padding: 3px 0;
  }

  /* Final: auto-height, vertically centred */
  .bkt-fin-ms { justify-content: center; }
  .bkt-fin-m  { flex: none; }

  /* ── Team row ──────────────────────────────────────────── */
  .bkt-t {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 4px 6px 4px 7px;
    min-height: 26px;
    font-size: 12px;
    white-space: nowrap;
    border-left: 3px solid var(--mc);
    border-radius: 0 2px 2px 0;
    transition: opacity 0.12s;
    background: var(--bg-2);
  }
  .bkt-t.win {
    background: var(--paper);
    font-weight: 700;
    color: var(--txt);
  }
  .bkt-t.lose { opacity: 0.38; }

  .bkt-fl { font-size: 13px; flex-shrink: 0; line-height: 1; }

  .bkt-nm {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    letter-spacing: -0.01em;
    line-height: 1.2;
  }

  .bkt-sc {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--txt-3);
    font-weight: 700;
    flex-shrink: 0;
    letter-spacing: 0.02em;
  }
  .bkt-t.win .bkt-sc { color: var(--accent); }

  .bkt-dl {
    font-family: var(--mono);
    font-size: 8px;
    font-weight: 700;
    flex-shrink: 0;
    line-height: 1;
  }
  .bkt-dl.up { color: var(--in); }
  .bkt-dl.dn { color: var(--out); }

  /* ── Actual result verdict icons ───────────────────────── */
  .bkt-verdict {
    font-family: var(--mono);
    font-size: 9px;
    font-weight: 900;
    flex-shrink: 0;
    line-height: 1;
    margin-left: 1px;
  }
  .bkt-correct { color: var(--in); }
  .bkt-wrong   { color: var(--out); }
  .bkt-upset   { color: #f9a825; }

  /* Predicted winner who actually lost — muted error tint */
  .bkt-t.win.actual-lose {
    background: color-mix(in srgb, var(--out) 10%, var(--bg-2));
    border-left-color: var(--out);
    color: color-mix(in srgb, var(--out) 60%, var(--txt));
  }
  .bkt-t.win.actual-lose .bkt-sc { color: var(--out); }

  /* Predicted loser who actually won — show as real winner */
  .bkt-t.lose.actual-win {
    opacity: 1;
    background: color-mix(in srgb, var(--in) 10%, var(--bg-2));
    border-left-color: var(--in);
    font-weight: 700;
    color: var(--txt);
  }
  .bkt-t.lose.actual-win .bkt-sc { color: var(--in); }

  /* Correctly predicted winner */
  .bkt-t.win.actual-win {
    border-left-color: var(--in);
  }
  .bkt-t.win.actual-win .bkt-sc { color: var(--in); }

  /* ── Bracket connector lines ───────────────────────────── */
  /*
   * Gap between columns = 28px; half = 14px.
   * A) bkt-m::after     – horizontal arm from match card 0→14px right
   * B) bkt-seg::before  – vertical bar at +14px, 25%→75% of seg height
   * C) bkt-seg::after   – horizontal arm 14→28px (reaching next col)
   */

  /* A) Right arm */
  .bkt-col:not(.bkt-fin) .bkt-m::after {
    content: '';
    position: absolute;
    right: -14px;
    top: 50%;
    width: 14px;
    height: 0;
    border-top: 1px solid var(--line);
    pointer-events: none;
  }

  /* B) Vertical bar */
  .bkt-col:not(.bkt-fin) .bkt-seg::before {
    content: '';
    position: absolute;
    right: -14px;
    top: 25%;
    height: 50%;
    width: 0;
    border-right: 1px solid var(--line);
    pointer-events: none;
  }

  /* C) Left half of gap → next column */
  .bkt-col:not(.bkt-fin) .bkt-seg::after {
    content: '';
    position: absolute;
    right: -28px;
    top: 50%;
    width: 14px;
    height: 0;
    border-top: 1px solid var(--line);
    pointer-events: none;
  }

  /* ── Champion strip ────────────────────────────────────── */
  .champ-strip {
    margin-bottom: 20px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--line-soft);
  }

  .champ-cards {
    display: flex;
    gap: 12px;
    flex-wrap: nowrap;
    width: 100%;
  }

  .champ-card {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 16px 14px 18px;
    background: color-mix(in srgb, var(--cc) 8%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--cc) 35%, var(--line));
    border-left: 4px solid var(--cc);
    border-radius: 6px;
    overflow: hidden;
  }


  .champ-flag { font-size: 40px; line-height: 1; flex-shrink: 0; }

  .champ-info {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .champ-name {
    font-size: 20px;
    font-weight: 900;
    letter-spacing: -0.03em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .champ-mgr {
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }

  .champ-rank {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--txt-3);
    font-weight: 700;
    margin-left: auto;
    flex-shrink: 0;
    align-self: center;
    white-space: nowrap;
  }

  .champ-trophy { font-size: 28px; flex-shrink: 0; }

  .champ-summary {
    font-size: 13.5px;
    color: var(--txt-2);
    line-height: 1.6;
    max-width: 68ch;
    text-align: center;
    text-wrap: pretty;
  }

  .champ-note {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--txt-3);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    text-align: center;
  }
</style>
