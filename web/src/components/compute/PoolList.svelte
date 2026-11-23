<script>
    // Compute: every pool as a card: how much of it is working now, and the last 10 minutes.
    import { onMount } from 'svelte';
    import { Plus, Cpu } from 'lucide-svelte';
    import { pools, poolState, poolStateLabel, updateReadings, poolNow, fmtRate } from '../../lib/compute.js';
    import { hostOrder, byOrder } from '../../lib/hosts.js';
    import { visible } from '../../lib/stores.js';
    import { href } from '../../lib/infra.js';
    import StatusPill from '../ui/StatusPill.svelte';
    import ResourceCard from '../ui/ResourceCard.svelte';

    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

    // each running pool's readings (from its watcher on Arrakis), last 10 minutes
    let readings = {};
    const load = async () => { readings = await updateReadings($pools, readings); };
    onMount(() => { load(); const t = setInterval(() => visible() && load(), 4000); return () => clearInterval(t); });
    $: $pools, load();
    const stats = (p) => poolNow(p, readings[p.name]);
    $: all = ($pools || []).map(p => ({ p, s: (readings, stats(p)) }));
    $: runningPools = all.filter(x => x.p.running).length;
    $: busyNow = all.reduce((a, x) => a + (x.s.fresh ? x.s.busy : 0), 0);
    $: coresNow = all.reduce((a, x) => a + (x.p.running ? x.s.cores : 0), 0);
    $: nodeCount = new Set(all.flatMap(x => Object.keys(x.p.nodes))).size;
    $: jobsRunning = all.reduce((a, x) => a + x.p.jobs.running, 0);
    $: jobsTotal = all.reduce((a, x) => a + x.p.jobs.total, 0);
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
        <div class="ui-stats">
            <div class="ui-stat"><span class="ui-stat-label">Pools</span><span class="ui-stat-value">{$pools.length}</span><span class="ui-stat-sub">{runningPools} running · {$pools.length - runningPools} stopped</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Cores busy</span><span class="ui-stat-value">{#if coresNow}{busyNow.toFixed(1)}<small>of {coresNow}</small>{:else}—{/if}</span><span class="ui-stat-sub">{coresNow ? 'across running pools' : 'no pool running'}</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Nodes</span><span class="ui-stat-value">{nodeCount}</span><span class="ui-stat-sub">computers in at least one pool</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Jobs</span><span class="ui-stat-value">{jobsRunning}<small>running</small></span><span class="ui-stat-sub">{plural(jobsTotal, 'job')} so far</span></div>
        </div>
        <div class="ui-cardgrid">
            {#each $pools as p (p.name)}
                {@const s = stats(p)}
                {@const nodes = byOrder(Object.keys(p.nodes).map(id => ({ id })), $hostOrder).map(x => x.id)}
                <ResourceCard name={p.name} sub="{nodes.join(' · ')}" icon={Cpu} on={p.running} off={!p.running} on:open={() => location.hash = href.pool(p.name)}
                    meters={[
                        { k: 'Cores', p: p.running && s.fresh && s.cores ? s.busy / s.cores * 100 : 0, color: 'var(--metric-cpu)', v: p.running && s.fresh ? s.busy.toFixed(1) : '—', of: s.cores ? `of ${s.cores} busy` : 'busy' },
                        { k: 'Tasks', v: p.running && s.fresh ? fmtRate(s.rate) : '—', of: `${s.unit || 'tasks'}/s` },
                        { k: 'Python', v: p.python, of: p.packages.length ? p.packages.slice(0, 2).join(', ') + (p.packages.length > 2 ? '…' : '') : '' },
                    ]}
                    chips={[{ label: p.jobs.running ? plural(p.jobs.running, 'job') + ' running' : plural(p.jobs.total, 'job'), onClick: () => location.hash = href.pool(p.name, 'jobs') }]}>
                    <svelte:fragment slot="status"><StatusPill state={poolState(p)} label={poolStateLabel(p)} /></svelte:fragment>
                </ResourceCard>
            {/each}
        </div>
    {/if}
</div>

