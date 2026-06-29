<script>
  import * as Plot from '@observablehq/plot';
  import * as d3 from 'd3';

  let { snapshots = [], topN = 10, highlightManager = null } = $props();

  const TEAM_COLORS = {
    'Algeria':            '#006233',
    'Argentina':          '#74ACDF',
    'Australia':          '#FFD700',
    'Austria':            '#ED2939',
    'Belgium':            '#EF3340',
    'Bosnia-Herzegovina': '#1A4FA0',
    'Brazil':             '#FFCC00',
    'Canada':             '#FF0000',
    'Cape Verde Islands': '#003893',
    'Colombia':           '#FDD116',
    'Congo DR':           '#007FFF',
    'Croatia':            '#D4021D',
    'Curaçao':            '#009FE3',
    'Czechia':            '#D7141A',
    'Ecuador':            '#FFD100',
    'Egypt':              '#C8102E',
    'England':            '#CF0A2C',
    'France':             '#0055A4',
    'Germany':            '#3C3C3C',
    'Ghana':              '#FCD116',
    'Haiti':              '#00209F',
    'Iran':               '#239F40',
    'Iraq':               '#CE1126',
    'Ivory Coast':        '#F77F00',
    'Japan':              '#BC002D',
    'Jordan':             '#007A3D',
    'Mexico':             '#006847',
    'Morocco':            '#C1272D',
    'Netherlands':        '#FF6600',
    'New Zealand':        '#808080',
    'Norway':             '#EF2B2D',
    'Panama':             '#DA121A',
    'Paraguay':           '#D52B1E',
    'Portugal':           '#006600',
    'Qatar':              '#8D1B3D',
    'Saudi Arabia':       '#165C38',
    'Scotland':           '#003F87',
    'Senegal':            '#00853F',
    'South Africa':       '#007A4D',
    'South Korea':        '#CD2E3A',
    'Spain':              '#AA151B',
    'Sweden':             '#006AA7',
    'Switzerland':        '#EE0000',
    'Tunisia':            '#E70013',
    'Turkey':             '#E30A17',
    'United States':      '#002868',
    'Uruguay':            '#5EB6E4',
    'Uzbekistan':         '#1EB53A',
  };

  let container = $state(null);

  // Collapse snapshots that share the same round into one, keeping the latest
  // per round. This means the chart has one x-position per match day rather
  // than one per calendar date (since a round can span multiple days).
  const roundSnapshots = $derived.by(() => {
    const seen = new Map();
    for (const snap of snapshots) {
      const key = snap.round ?? snap.ts?.slice(0, 10) ?? '';
      seen.set(key, snap);
    }
    return [...seen.values()];
  });

  const plotData = $derived.by(() => {
    if (!roundSnapshots.length) return [];

    // gsTracked enforces topN throughout the whole chart.
    // We anchor on the last group-stage snapshot so the visible teams are
    // consistent whether or not a knockout snapshot exists yet.
    const lastGsSnap = [...roundSnapshots].reverse().find(s => s.round?.startsWith('MD'));
    const gsTracked = lastGsSnap
      ? new Set(lastGsSnap.teams.slice(0, topN).map(t => t.name))
      : new Set(roundSnapshots[roundSnapshots.length - 1].teams.slice(0, topN).map(t => t.name));

    return roundSnapshots.flatMap((snap, i) => {
      const isKnockout = !snap.round?.startsWith('MD');
      const shown = snap.teams.filter(t => {
        if (!gsTracked.has(t.name)) return false;
        if (!isKnockout) return true;  // GS snapshots: status backfill is unreliable, always show
        if ((t.status ?? 'in') !== 'out') return true;  // alive — show
        // Eliminated: show only at the round they exited, not after.
        return t.stage != null && t.stage === snap.stage;
      });
      // Re-rank 1..N within shown teams so there are no rank gaps.
      return shown.map((t, idx) => ({
        x: i,
        rank: idx + 1,
        team: t.name,
        label: `${t.flag} ${t.name}`,
        manager: t.manager,
      }));
    });
  });

  const numTeams = $derived([...new Set(plotData.map(d => d.team))].length);
  const chartHeight = $derived(Math.max(560, numTeams * 56));

  const teamColor = $derived.by(() => {
    const map = {};
    for (const d of plotData) map[d.team] = TEAM_COLORS[d.team] ?? '#888888';
    return map;
  });

  // When a manager is selected, dim teams that don't belong to them
  const highlightedTeams = $derived(
    highlightManager
      ? new Set(plotData.filter(d => d.manager === highlightManager).map(d => d.team))
      : null
  );

  const effectiveColor = $derived.by(() => {
    if (!highlightedTeams) return teamColor;
    const map = {};
    for (const [team, color] of Object.entries(teamColor)) {
      map[team] = highlightedTeams.has(team) ? color : '#333340';
    }
    return map;
  });

  const xLabels = $derived(roundSnapshots.map(snap => snap.round ?? snap.ts?.slice(0, 10) ?? ''));

  function halo({ stroke = 'currentColor', strokeWidth = 3 } = {}) {
    return (index, scales, values, dimensions, context, next) => {
      const g = next(index, scales, values, dimensions, context);
      for (const path of [...g.childNodes]) {
        const clone = path.cloneNode(true);
        clone.setAttribute('stroke', stroke);
        clone.setAttribute('stroke-width', strokeWidth);
        path.parentNode.insertBefore(clone, path);
      }
      return g;
    };
  }

  function renderChart() {
    if (!container || !plotData.length) return;

    const teams = [...new Set(plotData.map(d => d.team))];
    const colors = teams.map(t => effectiveColor[t]);
    const [xmin, xmax] = d3.extent(plotData, d => d.x);
    const rank = Plot.stackY2({ x: 'x', z: 'team', order: 'rank' });
    const w = container.offsetWidth || 1000;

    const chart = Plot.plot({
      width: w,
      height: chartHeight,
      marginLeft: 110,
      marginRight: 130,
      style: {
        background: 'transparent',
        color: 'var(--txt-2)',
        fontFamily: 'var(--mono)',
        fontSize: '10px',
      },
      x: {
        label: null,
        grid: true,
        ticks: roundSnapshots.map((_, i) => i),
        tickFormat: i => xLabels[i] ?? '',
        tickRotate: -30,
      },
      y: { axis: null, inset: 40, reverse: true },
      color: { domain: teams, range: colors },
      marks: [
        Plot.lineY(plotData, {
          ...rank,
          stroke: 'team',
          strokeWidth: 26,
          curve: 'bump-x',
          sort: { color: 'y', reduce: 'first' },
          render: halo({ stroke: 'var(--bg)', strokeWidth: 33 }),
        }),
        Plot.text(plotData, {
          ...rank,
          text: 'rank',
          fill: '#000',
          stroke: 'team',
          strokeWidth: 6,
          paintOrder: 'stroke',
          fontSize: 11,
          fontWeight: 'bold',
          fontFamily: 'var(--mono)',
        }),
        Plot.text(plotData, {
          ...rank,
          filter: d => d.x >= xmax,
          text: 'label',
          dx: 22,
          textAnchor: 'start',
          fill: 'white',
          fontSize: 10,
          fontFamily: 'var(--mono)',
        }),
        Plot.text(plotData, {
          ...rank,
          filter: d => d.x <= xmin,
          text: 'label',
          dx: -22,
          textAnchor: 'end',
          fill: 'white',
          fontSize: 10,
          fontFamily: 'var(--mono)',
        }),
      ],
    });

    chart.querySelectorAll('[aria-label="x-axis tick"] text').forEach(el => {
      el.style.fill = 'var(--txt-3)';
    });

    container.innerHTML = '';
    container.appendChild(chart);
  }

  $effect(() => {
    renderChart();
    const ro = new ResizeObserver(() => renderChart());
    ro.observe(container);
    return () => ro.disconnect();
  });
</script>

<div bind:this={container} class="bump-wrap"></div>

<style>
  .bump-wrap { width: 100%; }
  .bump-wrap :global(figure) { margin: 0; padding: 0; }
  .bump-wrap :global(svg) { width: 100%; height: auto; overflow: visible; }
  .bump-wrap :global(text) { font-family: var(--mono) !important; }
  .bump-wrap :global([aria-label$="tick"] text) { fill: var(--txt-3) !important; }
  .bump-wrap :global(line[stroke="#e5e5e5"]),
  .bump-wrap :global(line[stroke="#ccc"]) { stroke: var(--line, #2a2a30) !important; }
</style>
