<script>
    // Compute: every pool as a card: how much of it is working now, and the last 10 minutes.
    import { onMount } from 'svelte';
    import { Plus, Cpu } from 'lucide-svelte';
    import { pools, poolState, poolStateLabel, updateReadings, poolNow, fmtRate, SLOTS } from '../../lib/compute.js';
    import { hostOrder, byOrder } from '../../lib/hosts.js';
    import { visible } from '../../lib/stores.js';
    import { href } from '../../lib/infra.js';
    import StatusPill from '../ui/StatusPill.svelte';
    import Strip from '../ui/Strip.svelte';

    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

    // each running pool's readings (from its watcher on Arrakis), last 10 minutes
    let readings = {};
    const load = async () => { readings = await updateReadings($pools, readings); };
    onMount(() => { load(); const t = setInterval(() => visible() && load(), 4000); return () => clearInterval(t); });
    $: $pools, load();
    const stats = (p) => poolNow(p, readings[p.name]);
</script>

<div class="ui-page">
    <div class="ui-head">
        <div><h1>Compute</h1><p>Pools of nodes that work as one big machine: a job's work spreads over every core of every node in its pool.</p></div>
        <div class="ui-head-actions"><a class="ui-btn primary" href={href.newPool}><Plus size={15} /> New pool</a></div>
    </div>

    {#if !$pools}
        <div class="ui-dim">Loading…</div>
    {:else if !$pools.length}
        <div class="ui-card ui-empty">No pools yet. <a class="ui-link" href={href.newPool}>Make one</a> from the nodes in the cluster.</div>
    {:else}
        <div class="grid">
            {#each $pools as p (p.name)}
                {@const s = stats(p)}
                {@const nodes = byOrder(Object.keys(p.nodes).map(id => ({ id })), $hostOrder).map(x => x.id)}
                <a class="pc" class:off={!p.running} href={href.pool(p.name)}>
                    <div class="head">
                        <span class="ic"><Cpu size={18} /></span>
                        <div class="tt"><b>{p.name}</b><small class="nodes">{#each nodes as id, i}<span><i style="background: {SLOTS[i % SLOTS.length]}"></i>{id}</span>{/each}</small></div>
                        <StatusPill state={poolState(p)} label={poolStateLabel(p)} />
                    </div>
                    <div class="main">
                        {#if p.running}
                            <div class="fig"><b>{s.fresh ? s.busy.toFixed(1) : '—'}</b><span>of {s.cores} cores busy</span></div>
                            <Strip points={s.pts} max={s.cores || 1} windowMs={s.win} height={40} />
                        {:else}
                            <div class="fig idle"><span>Stopped · {s.cores ? `${s.cores} cores` : 'its cores'} when it runs</span></div>
                            <Strip points={[]} height={40} />
                        {/if}
                    </div>
                    <div class="foot">
                        <span>{p.running && s.fresh ? `${fmtRate(s.rate)} ${s.unit || 'tasks'}/s` : '—'}</span>
                        <span>{p.jobs.running ? plural(p.jobs.running, 'job') + ' running' : plural(p.jobs.total, 'job') + ' so far'}</span>
                        <span class="py">Python {p.python}{p.packages.length ? ' · ' + p.packages.slice(0, 2).join(', ') + (p.packages.length > 2 ? '…' : '') : ''}</span>
                    </div>
                </a>
            {/each}
        </div>
    {/if}
</div>

<style>
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 16px; }
    .pc { display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; color: var(--text-primary); text-decoration: none; transition: border-color .15s; }
    .pc:hover { border-color: var(--border-strong); }
    .head { display: flex; align-items: center; gap: 12px; padding: 16px 18px 4px; }
    .ic { width: 38px; height: 38px; border-radius: 9px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--accent-soft); color: var(--accent); }
    .off .ic { background: var(--highlight-10); color: var(--text-secondary); }
    .tt { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
    .tt b { font-size: 15px; font-weight: 600; }
    .tt small { font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .main { padding: 14px 18px 16px; display: flex; flex-direction: column; gap: 10px; }
    .fig { display: flex; align-items: baseline; gap: 6px; font-variant-numeric: tabular-nums; }
    .fig b { font-size: 26px; font-weight: 600; letter-spacing: -0.01em; }
    .fig span { font-size: 13px; color: var(--text-secondary); }
    .fig.idle { min-height: 33px; align-items: center; }
    .foot { display: flex; align-items: center; gap: 16px; min-height: 44px; padding: 0 18px; margin-top: auto; border-top: 1px solid var(--border); background: var(--highlight-3); border-radius: 0 0 10px 10px; font-size: 12.5px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
    .foot span { white-space: nowrap; }
    .py { margin-left: auto; overflow: hidden; text-overflow: ellipsis; }
    .nodes { display: flex; gap: 10px; overflow: hidden; }
    .nodes span { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
    .nodes i { width: 8px; height: 8px; border-radius: 2px; }
</style>
