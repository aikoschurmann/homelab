<script>
    import { onMount } from 'svelte';
    import { Plus, Search, Play, Square, RotateCw, Trash2, Settings2, Loader2, X, ExternalLink, Network, Layers, Server, LayoutGrid, List } from 'lucide-svelte';
    import { gbFromMib, fetchMachines, fetchHostVms, visible } from '../../lib/stores.js';
    import { vmRef, vmBase } from '../../lib/vmref.js';
    import { api, busy, machineAction, imageLabel, tsLabel, fmtBytes } from '../../lib/machines.js';
    import ResourceCard from '../ui/ResourceCard.svelte';
    import StatusPill from '../ui/StatusPill.svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';

    export let data;
    export let open = () => {};      // open(name, tab?)
    export let create = () => {};
    export let embedded = false;     // inside a host's OrbStack VM tab: no page title, actions in the toolbar
    export let onHost = null;        // another host's OrbStack (its id); null = Arrakis's

    $: base = vmBase(onHost);
    $: R = (m) => vmRef(onHost, m.name);
    const refresh = () => onHost ? fetchHostVms(onHost) : fetchMachines();

    const toast = (m) => window.showToast?.(m);

    $: host = data.host;
    $: pool = data.pool;
    $: list = data.machines || [];
    $: jobs = Object.entries(data.jobs || {});
    $: jobOf = Object.fromEntries(jobs);
    $: orphanJobs = jobs.filter(([n]) => !list.some(m => m.name === n));

    // ---- live usage (server samples every 5 s; this reads its cache) -------------------
    let usage = {};
    async function loadUsage() {
        try {
            const r = await fetch(`${base}/usage`).then(r => r.json());
            if (r.status === 'success') usage = r.data.machines;
        } catch (e) {}
    }
    onMount(() => {
        loadUsage();
        const t = setInterval(() => visible() && loadUsage(), 5000);
        return () => clearInterval(t);
    });
    const running = (m) => m.state === 'running';
    // reactive so rows and totals redraw when `usage` arrives
    $: u = (m) => running(m) ? usage[m.name] : null;
    // cores a machine may use, and how many it uses now
    $: allowCores = (m) => m.cpu || pool.cpu;
    $: coresUsed = (m) => u(m) ? (u(m).cpu / 100) * allowCores(m) : 0;

    $: runningList = list.filter(running);
    $: totalCores = runningList.reduce((a, m) => a + coresUsed(m), 0);
    $: totalMem = runningList.reduce((a, m) => a + (u(m)?.mem || 0), 0);
    $: poolMemBytes = pool.memory_mib * 2 ** 20;
    $: diskTotal = list.reduce((a, m) => a + parseSize(m.disk_usage), 0);
    function parseSize(s) {
        const x = (s || '').match(/([0-9.]+)\s*([KMGT]?)B/i);
        return x ? parseFloat(x[1]) * { '': 1, K: 1e3, M: 1e6, G: 1e9, T: 1e12 }[x[2].toUpperCase()] : 0;
    }
    const fmtDisk = (b) => b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : (b / 1e6).toFixed(0) + ' MB';
    // memory bar: one segment per machine, shaded apart
    const SHADES = [1, 0.7, 0.5, 0.35, 0.25];
    $: memSegs = runningList.map((m, i) => ({ name: m.name, bytes: u(m)?.mem || 0, shade: SHADES[i % SHADES.length] })).filter(s => s.bytes);
    $: cpuSegs = runningList.map((m, i) => ({ name: m.name, cores: coresUsed(m), shade: SHADES[i % SHADES.length] })).filter(s => s.cores > 0.001);
    const pct = (a, b) => b ? Math.min(100, (a / b) * 100) : 0;

    // ---- view: cards (default) or table, remembered per browser ------------------------
    let view = 'grid';
    try { view = localStorage.getItem('arrakis_machines_view') || 'grid'; } catch (e) {}
    function setView(v) { view = v; try { localStorage.setItem('arrakis_machines_view', v); } catch (e) {} }

    // ---- filter -----------------------------------------------------------------
    let q = '';
    let stateFilter = 'all';
    $: shown = list.filter(m =>
        (stateFilter === 'all' || (stateFilter === 'running') === running(m)) &&
        (!q || [m.name, m.ip, m.tailscale?.ip, m.image?.distro].some(v => v && v.toLowerCase().includes(q.toLowerCase()))));

    async function dismissJob(name) { await api(`${base}/jobs/${name}`, { method: 'DELETE' }); refresh(); }

    function menu(m) {
        return [
            { label: 'Open', icon: ExternalLink, onClick: () => open(m.name) },
            running(m) ? { label: 'Restart', icon: RotateCw, onClick: () => machineAction(R(m), 'restart') } : null,
            running(m) ? { label: 'Stop', icon: Square, onClick: () => machineAction(R(m), 'stop') } : { label: 'Start', icon: Play, onClick: () => machineAction(R(m), 'start') },
            { label: 'Workloads', icon: Layers, onClick: () => open(m.name, 'workloads') },
            { label: 'Networking', icon: Network, onClick: () => open(m.name, 'networking') },
            { label: 'Resource limits', icon: Settings2, onClick: () => open(m.name, 'settings') },
            { label: 'Delete…', icon: Trash2, danger: true, divider: true, onClick: () => open(m.name, 'settings') },
        ];
    }
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
    const runsText = (r) => [r.containers ? plural(r.containers, 'container') : null, r.services ? plural(r.services, 'service') : null].filter(Boolean).join(' · ') || 'nothing extra';
    const BUSY = { start: 'Starting', stop: 'Stopping', restart: 'Restarting', delete: 'Deleting', join: 'Joining', leave: 'Leaving', limits: 'Saving' };
</script>

<div class="ui-page" class:embedded>
    {#if !embedded}
    <div class="ui-head">
        <div>
            <h1>OrbStack VM</h1>
            <p>One Linux VM on Arrakis that runs these machines. They share its pool of CPU and memory.</p>
        </div>
        <div class="ui-head-actions">
            <button class="ui-btn primary" on:click={create}><Plus size={15} /> Create machine</button>
        </div>
    </div>
    {/if}

    <!-- usage summary -->
    <div class="summary">
        <div class="ui-stat">
            <span class="ui-stat-label">Machines</span>
            <span class="ui-stat-value">{list.length}</span>
            <span class="ui-stat-sub">{runningList.length} running · {list.length - runningList.length} stopped</span>
        </div>
        <div class="ui-stat">
            <span class="ui-stat-label">CPU in use</span>
            <span class="ui-stat-value">{pct(totalCores, pool.cpu).toFixed(1)}%<small>{totalCores.toFixed(2)} of {pool.cpu} pool cores</small></span>
            <div class="segbar" title={cpuSegs.map(s => `${s.name}: ${s.cores.toFixed(2)} cores`).join('\n')}>
                {#each cpuSegs as s}<i style="width: {pct(s.cores, pool.cpu)}%; background: var(--metric-cpu); opacity: {s.shade}"></i>{/each}
            </div>
            <span class="ui-stat-sub legend">{#each cpuSegs as s}<span><b style="background: var(--metric-cpu); opacity: {s.shade}"></b>{s.name} {s.cores.toFixed(2)}</span>{:else}idle{/each}</span>
        </div>
        <div class="ui-stat">
            <span class="ui-stat-label">Memory in use</span>
            <span class="ui-stat-value">{fmtBytes(totalMem)}<small>of {gbFromMib(pool.memory_mib)} pool</small></span>
            <div class="segbar" title={memSegs.map(s => `${s.name}: ${fmtBytes(s.bytes)}`).join('\n')}>
                {#each memSegs as s}<i style="width: {pct(s.bytes, poolMemBytes)}%; background: var(--metric-mem); opacity: {s.shade}"></i>{/each}
            </div>
            <span class="ui-stat-sub legend">{#each memSegs as s}<span><b style="background: var(--metric-mem); opacity: {s.shade}"></b>{s.name} {fmtBytes(s.bytes)}</span>{:else}—{/each}</span>
        </div>
        <div class="ui-stat">
            <span class="ui-stat-label">Disk</span>
            <span class="ui-stat-value">{diskTotal ? fmtDisk(diskTotal) : '—'}</span>
            <span class="ui-stat-sub">across all machines</span>
        </div>
    </div>

    <!-- machines table -->
    <div class="list-bar">
        <label class="ui-search"><Search size={14} /><input placeholder="Search name, IP or distro" bind:value={q} /></label>
        <div class="ui-seg">
            <button class:on={stateFilter === 'all'} on:click={() => stateFilter = 'all'}>All</button>
            <button class:on={stateFilter === 'running'} on:click={() => stateFilter = 'running'}>Running</button>
            <button class:on={stateFilter === 'stopped'} on:click={() => stateFilter = 'stopped'}>Stopped</button>
        </div>
        <span class="ui-count">{shown.length} {shown.length === 1 ? 'machine' : 'machines'}</span>
        {#if embedded}<button class="ui-btn primary" on:click={create}><Plus size={14} /> Create machine</button>{/if}
        <div class="ui-seg view" role="group" aria-label="View">
            <button class:on={view === 'grid'} on:click={() => setView('grid')} title="Cards" aria-label="Cards"><LayoutGrid size={14} /></button>
            <button class:on={view === 'table'} on:click={() => setView('table')} title="Table" aria-label="Table"><List size={14} /></button>
        </div>
    </div>

    {#if view === 'grid'}
    <div class="grid">
        {#each orphanJobs as [name, job] (name)}
            <div class="mcard pending">
                <div class="mc-head">
                    <span class="mc-icon"><Server size={18} /></span>
                    <div class="mc-title"><span class="mc-name plain">{name}</span><span class="sub">{job.state === 'creating' ? 'Downloading the image and setting it up…' : (job.message || 'unknown error')}</span></div>
                    <StatusPill state={job.state === 'creating' ? 'creating' : 'error'} label={job.state === 'creating' ? 'Creating' : 'Failed'} />
                    {#if job.state !== 'creating'}<button class="ui-btn sm icon" title="Dismiss" on:click={() => dismissJob(name)}><X size={14} /></button>{/if}
                </div>
            </div>
        {/each}
        {#each shown as m (m.name)}
            {@const b = $busy[R(m)]}
            {@const job = jobOf[m.name]}
            {@const s = u(m)}
            <ResourceCard name={m.name} tag={m.name === data.dashboard_vm ? 'Dashboard' : null} sub="{imageLabel(m.image)} · {m.image?.arch}" on={running(m)} off={!running(m)} on:open={() => open(m.name)}
                meters={[
                    { k: 'CPU', p: s ? s.cpu : 0, color: 'var(--metric-cpu)', v: s ? s.cpu.toFixed(1) + '%' : '—', of: m.cpu ? `of ${m.cpu} cores` : 'of pool' },
                    { k: 'Memory', p: s ? pct(s.mem, s.memLimit) : 0, color: 'var(--metric-mem)', v: s ? fmtBytes(s.mem) : '—', of: m.memory_mib ? `of ${gbFromMib(m.memory_mib)}` : 'of pool' },
                    { k: 'Disk', v: m.disk_usage || '—', of: 'used' },
                ]}
                chips={[
                    ...(s?.runs?.containers ? [{ label: plural(s.runs.containers, 'container'), onClick: () => open(m.name, 'workloads') }] : []),
                    ...(s?.runs?.services ? [{ label: plural(s.runs.services, 'service'), onClick: () => open(m.name, 'workloads') }] : []),
                ]}
                note={!running(m) ? 'Stopped' : s?.runs ? 'Nothing extra running' : ''}
                lan={running(m) ? m.ip : ''} ts={m.tailscale?.state === 'running' ? m.tailscale.ip : ''} tsTitle="Tailscale {m.tailscale?.dns || ''}">
                <svelte:fragment slot="status">
                    {#if b}<StatusPill state="starting" label={BUSY[b]} />
                    {:else if job?.state === 'creating'}<StatusPill state="creating" label={job.kind === 'tailscale' ? 'Joining Tailscale' : 'Creating'} />
                    {:else}<StatusPill state={m.state} />{/if}
                    <span on:click|stopPropagation on:keydown|stopPropagation role="presentation"><ActionMenu items={menu(m)} label="Actions for {m.name}" /></span>
                </svelte:fragment>
            </ResourceCard>
        {/each}
        {#if !shown.length && !orphanJobs.length}
            <div class="ui-card ui-empty">{#if list.length}No machines match.{:else}No machines yet. <button class="ui-link" on:click={create}>Create one</button>{/if}</div>
        {/if}
    </div>
    {:else}
    <section class="ui-card">
        <div class="ui-tbl-wrap">
            <table class="ui-tbl">
                <thead>
                    <tr><th>Name</th><th>Status</th><th class="c-sm">CPU</th><th class="c-sm">Memory</th><th class="c-md">Runs</th><th class="c-xl">Address</th><th class="c-xl">Tailscale</th><th class="c-lg">Disk</th><th class="shrink"></th></tr>
                </thead>
                <tbody>
                    {#each orphanJobs as [name, job] (name)}
                        <tr>
                            <td><span class="nm plain">{name}</span></td>
                            <td><StatusPill state={job.state === 'creating' ? 'creating' : 'error'} label={job.state === 'creating' ? 'Creating' : 'Failed'} /></td>
                            <td colspan="7" class="ui-dim wrap">{job.state === 'creating' ? 'Downloading the image and setting it up…' : (job.message || 'unknown error')}</td>
                            <td>{#if job.state === 'creating'}<Loader2 size={14} class="ui-spin" />{:else}<button class="ui-btn sm icon" title="Dismiss" on:click={() => dismissJob(name)}><X size={14} /></button>{/if}</td>
                        </tr>
                    {/each}
                    {#each shown as m (m.name)}
                        {@const b = $busy[R(m)]}
                        {@const job = jobOf[m.name]}
                        {@const s = u(m)}
                        <tr class="click" on:click={() => open(m.name)}>
                            <td>
                                <div class="nm-cell">
                                    <span class="nm">{m.name}</span>
                                    {#if m.name === data.dashboard_vm}<span class="ui-tag">Dashboard</span>{/if}
                                </div>
                                <div class="sub">{imageLabel(m.image)} · {m.image?.arch}</div>
                            </td>
                            <td>
                                {#if b}<StatusPill state="starting" label={BUSY[b]} />
                                {:else if job?.state === 'creating'}<StatusPill state="creating" label={job.kind === 'tailscale' ? 'Joining Tailscale' : 'Creating'} />
                                {:else}<StatusPill state={m.state} />{/if}
                            </td>
                            <td class="c-sm">
                                <div class="use">
                                    <span class="num">{s ? s.cpu.toFixed(1) + '%' : '—'}</span>
                                    <div class="mini"><i style="width: {s ? s.cpu : 0}%; background: var(--metric-cpu)"></i></div>
                                    <span class="sub">{m.cpu ? `of ${m.cpu} cores` : 'of pool'}</span>
                                </div>
                            </td>
                            <td class="c-sm">
                                <div class="use">
                                    <span class="num">{s ? fmtBytes(s.mem) : '—'}</span>
                                    <div class="mini"><i style="width: {s ? pct(s.mem, s.memLimit) : 0}%; background: var(--metric-mem)"></i></div>
                                    <span class="sub">{m.memory_mib ? `of ${gbFromMib(m.memory_mib)}` : 'of pool'}</span>
                                </div>
                            </td>
                            <td class="c-md">
                                {#if s?.runs}
                                    <button class="runs" on:click|stopPropagation={() => open(m.name, 'workloads')}>
                                        {runsText(s.runs)}
                                    </button>
                                {:else}<span class="ui-dim">—</span>{/if}
                            </td>
                            <td class="ui-mono c-xl">{running(m) ? (m.ip || '—') : '—'}</td>
                            <td class="c-xl">
                                {#if m.tailscale?.state === 'running'}<span class="ts"><i class="ok"></i><span class="ui-mono">{m.tailscale.ip}</span></span>
                                {:else}<span class="ui-dim">{running(m) ? tsLabel(m.tailscale) : '—'}</span>{/if}
                            </td>
                            <td class="ui-mono c-lg">{m.disk_usage || '—'}</td>
                            <td on:click|stopPropagation role="presentation"><ActionMenu items={menu(m)} label="Actions for {m.name}" /></td>
                        </tr>
                    {/each}
                </tbody>
            </table>
            {#if !shown.length && !orphanJobs.length}
                <div class="ui-empty">
                    {#if list.length}No machines match.{:else}No machines yet. <button class="ui-link" on:click={create}>Create one</button>{/if}
                </div>
            {/if}
        </div>
    </section>
    {/if}
</div>


<style>
    /* inside a tab the page wrapper must not add a second page's padding */
    .ui-page.embedded { padding: 0; max-width: none; margin: 0; }
    .summary { display: grid; grid-template-columns: 0.7fr 1fr 1fr 0.7fr; gap: 12px; }
    .segbar { display: flex; height: 6px; border-radius: 3px; background: var(--highlight-15); overflow: hidden; gap: 1px; }
    .segbar i { display: block; height: 100%; transition: width .3s ease; }
    .legend { display: flex; flex-wrap: wrap; gap: 2px 12px; }
    .legend span { display: inline-flex; align-items: center; gap: 5px; }
    .legend b { width: 8px; height: 8px; border-radius: 2px; }

    .list-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .list-bar .ui-count { margin-left: auto; font-size: 13px; color: var(--text-secondary); }
    .ui-seg.view button { padding: 0 9px; display: flex; align-items: center; }

    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 16px; }
    .mcard { container-type: inline-size; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; display: flex; flex-direction: column; cursor: pointer; transition: border-color .12s, box-shadow .12s; text-align: left; }
    .mcard:hover { border-color: var(--border-strong); box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06); }
    .mcard:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .mcard.pending { cursor: default; }
    .mc-head { display: flex; align-items: center; gap: 12px; padding: 16px 16px 14px 18px; }
    .mc-icon { width: 38px; height: 38px; border-radius: 9px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); }
    .mc-icon.on { background: var(--accent-soft); color: var(--accent); }
    .mc-title { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
    .mc-name { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: var(--accent); }
    .mc-name.plain { color: var(--text-primary); }
    .mcard:hover .mc-name:not(.plain) { text-decoration: underline; }
    .mc-meters { display: flex; flex-direction: column; gap: 10px; padding: 14px 18px; border-top: 1px solid var(--border); }
    .meter { display: grid; grid-template-columns: 64px 1fr 150px; align-items: center; gap: 12px; }
    .meter .k { font-size: 12.5px; color: var(--text-secondary); }
    .meter .v { font-size: 13px; font-weight: 500; color: var(--text-primary); font-variant-numeric: tabular-nums; white-space: nowrap; }
    .meter .v.wide { grid-column: 2 / -1; }
    .meter .v small { font-weight: 400; color: var(--text-secondary); margin-left: 5px; font-size: 12px; }
    .mc-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: nowrap; height: 46px; box-sizing: border-box; padding: 0 18px; overflow: hidden; border-top: 1px solid var(--border); background: var(--highlight-3); border-radius: 0 0 10px 10px; font-size: 12.5px; margin-top: auto; }
    .chips { display: flex; gap: 6px; flex-wrap: nowrap; align-items: center; min-width: 0; white-space: nowrap; }
    .chip { height: 24px; padding: 0 9px; border-radius: 12px; border: 1px solid var(--border); background: var(--surface); font-size: 12px; color: var(--text-primary); cursor: pointer; }
    .chip:hover { border-color: var(--accent); color: var(--accent); }
    .addr { display: flex; gap: 12px; align-items: center; color: var(--text-secondary); white-space: nowrap; flex-shrink: 0; }
    /* one footer height for every card: narrow cards drop addresses rather than wrap */
    @container (max-width: 520px) { .addr .lan { display: none; } }
    @container (max-width: 400px) { .addr { display: none; } }
    .addr .ui-mono { font-size: 12px; }
    .mcard.off .mc-meters { opacity: 0.55; }
    .nm-cell { display: flex; align-items: center; gap: 8px; }
    .nm { font-weight: 600; color: var(--accent); }
    .nm.plain { color: var(--text-primary); }
    tr.click:hover .nm { text-decoration: underline; }
    .sub { font-size: 12px; color: var(--text-secondary); }
    td > .sub { margin-top: 2px; }
    .wrap { white-space: normal; }
    .use { display: grid; grid-template-columns: auto 1fr; align-items: center; column-gap: 8px; row-gap: 3px; min-width: 120px; max-width: 170px; }
    .use .num { font-variant-numeric: tabular-nums; font-weight: 500; }
    .use .sub { grid-column: 1 / -1; }
    .mini { height: 4px; border-radius: 2px; background: var(--highlight-15); overflow: hidden; min-width: 40px; }
    .mini i { display: block; height: 100%; border-radius: 2px; transition: width .3s ease; }
    .runs { font-size: 13px; color: var(--text-primary); cursor: pointer; text-align: left; white-space: nowrap; }
    .runs:hover { color: var(--accent); text-decoration: underline; }
    .ts { display: inline-flex; align-items: center; gap: 6px; }
    .ts i.ok { width: 6px; height: 6px; border-radius: 50%; background: var(--green); }

    .pool-rows { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--radius-card, 8px); margin: 8px 0 12px; }
    .pool-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 16px; }
    .pool-row + .pool-row { border-top: 1px solid var(--border); }
    .ui-hint { margin: 0 0 6px; }

    @media (max-width: 1100px) {
        .summary { grid-template-columns: 1fr 1fr; }
    }
    @media (max-width: 640px) {
        .grid { grid-template-columns: 1fr; }
        .meter { grid-template-columns: 56px 1fr 120px; }
        .summary > :nth-child(2), .summary > :nth-child(3) { grid-column: 1 / -1; }
        .summary > :nth-child(2), .summary > :nth-child(3) { order: 1; }
        .ui-head-actions { width: 100%; }
        .ui-head-actions .ui-btn { flex: 1; }
    }
</style>
