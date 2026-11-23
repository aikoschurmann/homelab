<script>
    // The Overview's compute card: each pool on one row: how much of it is working, the last
    // 10 minutes, its throughput, and what is running on it now.
    import { onMount } from 'svelte';
    import { ArrowRight, Cpu, Plus } from 'lucide-svelte';
    import { pools, fetchPools, updateReadings, poolNow, fmtRate, poolStateLabel } from '../../lib/compute.js';
    import { visible } from '../../lib/stores.js';
    import { href } from '../../lib/infra.js';
    import Strip from '../ui/Strip.svelte';

    let readings = {};
    const load = async () => { readings = await updateReadings($pools, readings); };
    onMount(() => {
        fetchPools().then(load);
        const t = setInterval(() => { if (visible()) { fetchPools(); load(); } }, 5000);
        return () => clearInterval(t);
    });

    const dur = (t) => { const s = Math.max(0, Math.round(Date.now() / 1000 - t)); return s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor(s % 3600 / 60)} min`; };
    const go = (to) => location.hash = to;
    $: running = ($pools || []).filter(p => p.running);
    $: busyAll = running.reduce((a, p) => a + poolNow(p, readings[p.name]).busy, 0);
    $: coresAll = running.reduce((a, p) => a + poolNow(p, readings[p.name]).cores, 0);
</script>

<section class="ui-card" id="sec-compute">
    <div class="ui-card-head">
        <div><h2 class="ui-card-title">Compute</h2>
            <p class="ui-card-desc">{#if !$pools}Loading…{:else if running.length}{busyAll.toFixed(1)} of {coresAll} cores busy across {running.length === 1 ? 'one running pool' : `${running.length} running pools`}.{:else if $pools.length}No pool is running.{:else}Pools of nodes that work as one machine.{/if}</p></div>
        <a class="ui-link more" href={href.pools}>{$pools?.length ? 'All pools' : 'Compute'} <ArrowRight size={13} /></a>
    </div>

    {#if $pools && !$pools.length}
        <a class="empty" href={href.newPool}><Plus size={14} /> Make a pool from the cluster's nodes</a>
    {:else if $pools}
        <div class="rows">
            <div class="row head" aria-hidden="true"><span>Pool</span><span>Cores busy</span><span>Last {Math.max(1, Math.round(Math.max(...($pools || []).map(p => poolNow(p, readings[p.name]).win), 60000) / 60000))} min</span><span>Per second</span><span>Running</span><span></span></div>
            {#each $pools as p (p.name)}
                {@const s = poolNow(p, readings[p.name])}
                {@const job = (p.running_jobs || [])[0]}
                <button class="row" on:click={() => go(href.pool(p.name))}>
                    <span class="nm">
                        <span class="ic" class:on={p.running}><Cpu size={15} /></span>
                        <span class="nm-t"><b>{p.name}</b><small>{Object.keys(p.nodes).length} nodes</small></span>
                    </span>
                    <span class="fig">{#if s.fresh}<b>{s.busy.toFixed(1)}</b><small>of {s.cores} cores</small>{:else}<small>{poolStateLabel(p)}</small>{/if}</span>
                    <span class="strip"><Strip points={s.pts} max={s.cores || 1} windowMs={s.win} height={30} /></span>
                    <span class="rate">{#if s.fresh}<b>{fmtRate(s.rate)}</b><small class="unit">{s.unit || 'tasks'}</small>{:else}<small>—</small>{/if}</span>
                    <span class="job">{#if job}<span class="ui-mono">{job.script}{job.args.length ? ' ' + job.args.join(' ') : ''}</span><small>{dur(job.started)}</small>{:else if p.running}<small>No job running</small>{/if}</span>
                    <ArrowRight size={14} class="go" />
                </button>
            {/each}
        </div>
    {/if}
</section>

<style>
    .more { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; white-space: nowrap; }
    .rows { border-top: 1px solid var(--border); }
    .row { display: grid; grid-template-columns: minmax(150px, 1.1fr) 130px minmax(120px, 1.5fr) 80px minmax(150px, 1.3fr) 16px; gap: 0 18px; align-items: center; width: 100%; padding: 12px 20px; border-bottom: 1px solid var(--border); text-align: left; color: var(--text-primary); font-size: 13px; cursor: pointer; box-sizing: border-box; }
    .row:last-child { border-bottom: none; border-radius: 0 0 var(--radius-card, 8px) var(--radius-card, 8px); }
    .row:not(.head):hover { background: var(--highlight-3); }
    .row:hover :global(.go) { color: var(--accent); }
    :global(.row .go) { color: var(--text-secondary); justify-self: end; }
    .row.head { cursor: default; padding-top: 12px; padding-bottom: 10px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); }
    .nm { display: flex; align-items: center; gap: 10px; min-width: 0; }
    .ic { width: 30px; height: 30px; border-radius: var(--radius-card, 8px); flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); }
    .ic.on { background: var(--accent-soft); color: var(--accent); }
    .nm-t { display: flex; flex-direction: column; min-width: 0; }
    .nm-t b { font-weight: 600; }
    .nm-t small, .fig small, .rate small, .job small { font-size: 12px; color: var(--text-secondary); }
    .fig, .rate { display: flex; align-items: baseline; gap: 5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .fig b, .rate b { font-size: 16px; font-weight: 600; }
    .strip { min-width: 0; }
    .job { display: flex; align-items: center; gap: 8px; min-width: 0; white-space: nowrap; }
    .job .ui-mono { font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; }
    .empty { display: flex; align-items: center; gap: 8px; padding: 16px 20px; border-top: 1px solid var(--border); font-size: 13px; color: var(--text-secondary); }
    .empty:hover { color: var(--accent); }
    /* phone: no column headers; each pool is a small block: name, the two figures, the
       strip across, then what's running */
    @media (max-width: 760px) {
        .row.head { display: none; }
        .row { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 16px; grid-template-areas: "nm nm go" "fig rate rate" "strip strip strip" "job job job"; gap: 10px 12px; padding: 14px; }
        .nm { grid-area: nm; }
        .fig { grid-area: fig; }
        .rate { grid-area: rate; justify-self: end; }
        .strip { grid-area: strip; }
        .job { grid-area: job; }
        .job:empty { display: none; }
        :global(.row .go) { grid-area: go; }
    }
</style>
