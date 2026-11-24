<script>
    import { onMount } from 'svelte';
    import { ArrowRight } from 'lucide-svelte';
    import { visible } from '../../lib/stores.js';

    // Pi-hole at a glance: today's queries, how many it blocked, the blocklist, and whether
    // blocking is on. The Pi-hole page has the details and the pause button.
    let d = null, err = '', w = 800;
    async function load() {
        try { const j = await fetch('/api/pihole').then(r => r.json()); if (j.status === 'success' || j.found != null) { d = j.data || j; err = ''; } else err = j.message || 'Pi-hole not found'; } catch (e) { err = 'Could not reach Pi-hole'; }
    }
    onMount(() => { load(); const t = setInterval(() => visible() && load(), 60000); return () => clearInterval(t); });
    const n = (v) => v == null ? '—' : v >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : v >= 1e4 ? Math.round(v / 1000) + 'k' : v.toLocaleString();
    $: off = d && d.blocking && d.blocking !== 'enabled';
</script>

<section class="ui-card pi" id="sec-pihole" bind:clientWidth={w}>
    <div class="ui-card-head">
        <div><h2 class="ui-card-title">Pi-hole</h2><p class="ui-card-desc" class:bad={off}>{err || (!d ? 'Loading…' : off ? 'Blocking is off' : `Blocking on ${d.target}`)}</p></div>
        <a class="ui-link more" href="#tools/pihole">Pi-hole <ArrowRight size={13} /></a>
    </div>
    {#if d?.found}
        <div class="cells" class:two={w < 560}>
            <a class="cell" href="#tools/pihole"><span class="k">Queries today</span><span class="v">{n(d.queries)}</span></a>
            <a class="cell" href="#tools/pihole"><span class="k">Blocked</span><span class="v">{d.percent != null ? d.percent.toFixed(1) + '%' : '—'}<small>{n(d.blocked)}</small></span></a>
            <a class="cell" href="#tools/pihole"><span class="k">Blocklist</span><span class="v">{n(d.gravity)}<small>domains</small></span></a>
            <a class="cell" href="#tools/pihole"><span class="k">Clients</span><span class="v">{d.clients ?? '—'}</span></a>
        </div>
    {/if}
</section>

<style>
    .more { font-size: 13px; display: inline-flex; align-items: center; gap: 3px; white-space: nowrap; margin-top: 2px; }
    .bad { color: var(--red) !important; }
    .cells { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-top: 1px solid var(--border); }
    .cell { display: flex; flex-direction: column; gap: 4px; padding: 14px 20px; text-decoration: none; color: inherit; min-width: 0; }
    .cell + .cell { border-left: 1px solid var(--border); }
    .cell:hover { background: var(--highlight-3); }
    .k { font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .v { font-size: 20px; font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; white-space: nowrap; }
    .v small { font-size: 12.5px; font-weight: 400; color: var(--text-secondary); margin-left: 5px; }
    /* narrow (half width or phone): two by two, by the card's own width */
    .cells.two { grid-template-columns: 1fr 1fr; }
    .cells.two .cell:nth-child(3) { border-left: none; }
    .cells.two .cell:nth-child(n + 3) { border-top: 1px solid var(--border); }
</style>
