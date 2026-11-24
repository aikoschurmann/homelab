<script>
    import { onMount } from 'svelte';
    import { ArrowRight } from 'lucide-svelte';
    import { visible } from '../../lib/stores.js';
    import UptimeStrip from '../ui/UptimeStrip.svelte';

    // The uptime checks from Network tools: one row each, its strip and how it's doing now
    let data = null;
    async function load() { try { const j = await fetch('/api/uptime').then(r => r.json()); if (j.status === 'success') data = j.data; } catch (e) {} }
    onMount(() => { load(); const t = setInterval(() => visible() && load(), 60000); return () => clearInterval(t); });
    $: checks = data?.checks || [];
    $: down = checks.filter(c => c.status === 'down').length;
    const fms = (v) => v == null ? '—' : v < 1000 ? Math.round(v) + ' ms' : (v / 1000).toFixed(1) + ' s';
</script>

<section class="ui-card" id="sec-uptime">
    <div class="ui-card-head">
        <div><h2 class="ui-card-title">Uptime</h2><p class="ui-card-desc">{!data ? 'Loading…' : !checks.length ? 'No checks yet.' : down ? `${down} of ${checks.length} down right now.` : `All ${checks.length} up.`}</p></div>
        <a class="ui-link more" href="#tools/uptime">Checks <ArrowRight size={13} /></a>
    </div>
    {#if checks.length}
        <div class="rows">
            {#each checks as c (c.id)}
                <a class="row" href="#tools/uptime">
                    <span class="nm"><b>{c.name}</b><small>{c.url.replace(/^https?:\/\//, '')}</small></span>
                    <span class="st">{#if c.history}<UptimeStrip slots={c.history.slots} bucketSeconds={data.bucket_seconds} />{/if}</span>
                    <span class="fig" class:bad={c.status === 'down'}>{c.status === 'down' ? 'Down' : c.history?.pct != null ? c.history.pct.toFixed(c.history.pct >= 99.95 ? 0 : 1) + '%' : '—'}<small>{fms(c.last?.ms)}</small></span>
                </a>
            {/each}
        </div>
    {/if}
</section>

<style>
    .more { font-size: 13px; display: inline-flex; align-items: center; gap: 3px; white-space: nowrap; margin-top: 2px; }
    .rows { border-top: 1px solid var(--border); }
    .row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) 86px; gap: 16px; align-items: center; padding: 11px 20px; text-decoration: none; color: inherit; }
    .row + .row { border-top: 1px solid var(--border); }
    .row:hover { background: var(--highlight-3); }
    .nm { display: flex; flex-direction: column; min-width: 0; }
    .nm b { font-size: 13.5px; font-weight: 500; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .nm small { font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .st { min-width: 0; }
    .fig { display: flex; flex-direction: column; align-items: flex-end; font-size: 13.5px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text-primary); }
    .fig small { font-size: 12px; font-weight: 400; color: var(--text-secondary); }
    .fig.bad { color: var(--red); }
    @media (max-width: 640px) { .row { grid-template-columns: minmax(0, 1fr) 70px; padding: 10px 14px; } .st { grid-column: 1 / -1; grid-row: 2; } }
</style>
