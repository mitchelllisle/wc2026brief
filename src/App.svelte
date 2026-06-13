<script>
  import { onMount } from 'svelte';

  let data = $state(null);
  let loading = $state(true);
  let error = $state(false);

  onMount(async () => {
    try {
      const res = await fetch(`${import.meta.env.BASE_URL}data/stats.json`);
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
</script>

<div class="wrap">
  <header class="masthead">
    <div class="trophy">🏆</div>
    <h1><span class="tag">[JOINT]</span> Sweep</h1>
    <div class="sub">FIFA World Cup 2026 · Last squad standing · Loser cops it</div>
    <div class="stamp">
      {#if loading}
        Loading…
      {:else if error}
        Stats unavailable — check back soon
      {:else}
        Report generated: {formatStamp(data.generated_at)}
      {/if}
    </div>
  </header>

  {#if data}
    <h2>📋 Summary</h2>
    <div class="summary">
      {#each data.summary as para}
        <p>{@html renderPara(para)}</p>
      {/each}
    </div>

    <h2>💀 Danger Rankings</h2>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Participant</th>
          <th>Teams remaining</th>
          <th>Eliminated</th>
          <th>At risk</th>
          <th>Record (W-D-L)</th>
        </tr>
      </thead>
      <tbody>
        {#each data.leaderboard as p, i}
          {@const last = i === data.leaderboard.length - 1}
          {@const pct = p.teams_total > 0 ? Math.round(p.teams_remaining / p.teams_total * 100) : 0}
          <tr class:lb-danger={last}>
            <td class="pos">{last ? '💀' : i + 1}</td>
            <td class="name">{p.name}</td>
            <td>
              <div class="bar"><div class="bar-fill" style="width:{pct}%"></div></div>
              <span class="bar-label">{p.teams_remaining} / {p.teams_total}</span>
            </td>
            <td>{p.eliminated}</td>
            <td>{p.at_risk}</td>
            <td class="record">{p.record.w}W-{p.record.d}D-{p.record.l}L</td>
          </tr>
        {/each}
      </tbody>
    </table>

    <h2>👥 Squads</h2>
    <div class="squad-grid">
      {#each data.leaderboard as p}
        {@const teams = data.squads[p.name] ?? []}
        {@const alive = teams.filter(t => t.status !== 'out').length}
        <section class="squad">
          <header class="squad-head">
            <h3>{p.name}</h3>
            <span class="alive">{alive}/{teams.length} alive</span>
          </header>
          <ul class="teams">
            {#each teams as t}
              <li class="st-{t.status}">
                <span class="flag">{t.flag}</span>
                <span class="team">{t.name}</span>
                <span class="res {t.last_result ? t.last_result.toLowerCase() : 'none'}">
                  {t.last_result ?? '–'}
                </span>
                <span class="st-dot"></span>
              </li>
            {/each}
          </ul>
        </section>
      {/each}
    </div>

    <div class="legend">
      <div class="legend-rag">
        <span><span class="dot g"></span> In</span>
        <span><span class="dot a"></span> At Risk</span>
        <span><span class="dot r"></span> Out</span>
      </div>
      <div class="legend-note">W/D/L indicates most recent game result only.</div>
    </div>
  {/if}

  <footer>
    [JOINT] Sweep - FIFA World Cup 2026
  </footer>
</div>
