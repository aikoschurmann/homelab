<script>
    import { SN } from '../../lib/server.js';
    // One pool, shaped like a machine's page: icon header, then tabs.
    // Overview (start/stop, live totals, each node) · Jobs (run a script, follow it)
    // · Files (the pool folder's scripts) · Settings (nodes, software, delete).
    import { onMount, tick } from 'svelte';
    import { Cpu, Play, Square, RotateCw, Trash2, Plus, Save, FileCode, Loader2, Terminal, Search, ArrowLeft } from 'lucide-svelte';
    import { getPool, poolMetrics, poolOp, listJobs, jobOutput, jobLast, runJob, stopJob, deleteJob, listFiles, readFile, writeFile, removeFile, deletePool, poolState, poolStateLabel, JOB_PILL, JOB_LABEL, fetchPools, workUnit, amount, unitLabel } from '../../lib/compute.js';
    import { visible } from '../../lib/stores.js';
    import { href } from '../../lib/infra.js';
    import { hostOrder, byOrder } from '../../lib/hosts.js';
    import Strip from '../ui/Strip.svelte';
    import StackChart from '../ui/StackChart.svelte';
    import LiveChart from '../ui/LiveChart.svelte';
    import StatusPill from '../ui/StatusPill.svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';
    import Tabs from '../ui/Tabs.svelte';
    import CopyText from '../ui/CopyText.svelte';
    import PoolForm from './PoolForm.svelte';
    import CodeEditor from '../ui/CodeEditor.svelte';
    import Modal from '../ui/Modal.svelte';

    export let name;
    export let tab = 'overview';
    export let setTab = () => {};

    const toast = (m) => window.showToast?.(m);
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
    const gb = (b) => b == null ? '—' : (b / 2 ** 30).toFixed(1) + ' GB';
    const ago = (t) => { const s = Math.max(0, Date.now() / 1000 - t); return s < 90 ? `${Math.round(s)} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`; };
    const dur = (a, b) => { const s = Math.max(0, Math.round((b || Date.now() / 1000) - a)); return s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${Math.floor(s / 3600)} h ${Math.floor(s % 3600 / 60)} min`; };

    let p = null, missing = false;
    async function load() {
        const x = await getPool(name);
        if (x) { p = x; missing = false; } else missing = true;
    }
    // ---- readings: every 2 s from the pool's watcher on Arrakis (the last 30 minutes) -------
    // { t, nodes: { id: { cores, busy (cores in use), done (tasks finished since the last
    //   reading), queued, mem, limit } } }
    let readings = [], watching = false, fetching = false;
    async function loadMetrics() {
        if (fetching) return;              // two overlapping reads would add every reading twice
        fetching = true;
        try {
            const since = readings.length ? readings[readings.length - 1].t : 0;
            const d = await poolMetrics(name, since);
            if (!d) return;
            watching = d.watching;
            const fresh = d.points.filter(r => !readings.length || r.t > readings[readings.length - 1].t);
            if (fresh.length) readings = [...readings, ...fresh].slice(-900);
        } finally { fetching = false; }
    }
    // nodes in the sidebar's order, each with a fixed colour (categorical slots, validated)
    const SLOTS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
    $: order = byOrder(nodeIds.map(id => ({ id })), $hostOrder).map(x => x.id);
    $: colour = Object.fromEntries(order.map((id, i) => [id, SLOTS[i % SLOTS.length]]));
    $: now = readings[readings.length - 1];
    $: fresh = !!(p?.running && !busy && now && Date.now() / 1000 - now.t < 10);
    $: cur = fresh ? now.nodes : {};
    $: coresTot = Object.values(cur).reduce((a, n) => a + n.cores, 0) || p?.counts?.cores || 0;
    $: busyNow = Object.values(cur).reduce((a, n) => a + n.busy, 0);
    $: queuedNow = Object.values(cur).reduce((a, n) => a + n.queued, 0);
    // throughput per second over the last ~10 s (per node and in total): in the job's own unit
    // when it counts its work (pool.count), else tasks finished
    $: unit = workUnit(readings);
    $: Unit = unitLabel(unit);
    function rate(id = null, span = 10) {
        const pts = readings.filter(r => r.t > (now?.t || 0) - span);
        if (pts.length < 2) return 0;
        const done = pts.slice(1).reduce((a, r) => a + (id ? amount(r.nodes[id], unit) : Object.values(r.nodes).reduce((x, n) => x + amount(n, unit), 0)), 0);
        return done / (pts[pts.length - 1].t - pts[0].t);
    }
    const fmt = (v) => v < 10 ? v.toFixed(1) : Math.round(v).toLocaleString();
    $: rateNow = (readings, unit, rate());
    let span = 10;                                   // minutes on the graphs (at most)
    // the graphs span what there is: from 1 minute up to the chosen 10 or 30, so a short
    // history fills the width instead of sitting in a corner
    $: winMs = readings.length ? Math.min(span * 60000, Math.max(60000, (readings[readings.length - 1].t - readings[0].t) * 1000)) : span * 60000;
    $: capMax = fresh && coresTot ? coresTot : readings.reduce((m, r) => Math.max(m, Object.values(r.nodes).reduce((a, n) => a + n.cores, 0)), coresTot || 0);   // see poolNow
    $: totalPts = readings.map(r => [r.t * 1000, Object.values(r.nodes).reduce((a, n) => a + n.busy, 0)]);
    $: nodeCap = Object.fromEntries(order.map(id => [id, (fresh && cur[id]?.cores) || readings.reduce((m, r) => Math.max(m, r.nodes[id]?.cores || 0), 0) || 1]));
    $: nodePts = Object.fromEntries(order.map(id => [id, readings.map(r => [r.t * 1000, r.nodes[id]?.busy ?? 0])]));
    // throughput on each node (each reading's count over its interval)
    $: rateSeries = order.map(id => ({ name: id, color: colour[id],
        points: smooth(readings.slice(1).map((r, i) => [r.t * 1000, amount(r.nodes[id], unit) / Math.max(0.5, r.t - readings[i].t)])) }));
    const smooth = (pts, k = 3) => pts.map((p, i) => [p[0], pts.slice(Math.max(0, i - k + 1), i + 1).reduce((a, q) => a + q[1], 0) / Math.min(k, i + 1)]);
    $: TABS = [
        { id: 'overview', label: 'Overview' },
        { id: 'jobs', label: p?.jobs?.total ? `Jobs (${p.jobs.total})` : 'Jobs' },
        { id: 'files', label: 'Files' },
        { id: 'settings', label: 'Settings' },
    ];
    $: busy = p?.op?.state === 'running';
    $: nodeIds = p ? Object.keys(p.nodes) : [];

    async function op(kind) {
        if (await poolOp(name, kind)) { await load(); toast(kind === 'up' ? `Starting ${name}…` : `Stopping ${name}…`); }
    }

    // ---- jobs -----------------------------------------------------------------------------
    let jobs = [], sel = null, out = '', outOffset = 0, outEl, follow = true, script = '', args = '', starting = false, showAll = false;
    async function loadJobs() {
        const was = jobs.find(j => j.id === sel)?.state;
        jobs = await listJobs(name);
        if (was === 'running' && jobs.find(j => j.id === sel)?.state !== 'running') loadOut();
    }
    // a run has a page of its own (#infra/pool-<name>/job-<id>), under the Jobs tab
    $: jobId = tab && tab.startsWith('job-') ? +tab.slice(4) : null;
    $: if (jobId && jobId !== sel) pick(jobId);
    $: activeTab = jobId ? 'jobs' : filePath ? 'files' : tab;
    const openJob = (id) => setTab('job-' + id);
    // the list: search and state, like the other lists
    let jq = '', jstate = 'all';
    const JFILTERS = [['all', 'All'], ['running', 'Running'], ['done', 'Done'], ['failed', 'Failed']];
    const jmatch = (j, st) => st === 'all' || (st === 'failed' ? ['failed', 'stopped', 'unknown'].includes(j.state) : j.state === st);
    // jstate and jq are passed in so the list recomputes the moment either changes
    $: shownJobs = jobs.filter(j => jmatch(j, jstate) && (!jq || `${j.script} ${j.args.join(' ')}`.toLowerCase().includes(jq.toLowerCase())));
    let runDlg = false;
    async function pick(id) { sel = id; out = ''; outOffset = 0; follow = true; await loadOut(); }
    $: job = jobs.find(j => j.id === sel);
    async function loadOut() {
        if (!sel) return;
        const id = sel;
        const d = await jobOutput(name, id, outOffset);
        if (!d || id !== sel) return;
        if (d.output) { out = (out + d.output).slice(-400_000); outOffset = d.offset; }
        const i = jobs.findIndex(j => j.id === id);
        const ended = i >= 0 && jobs[i].state === 'running' && d.state !== 'running';
        if (i >= 0 && jobs[i].state !== d.state) { jobs[i] = { ...jobs[i], ...d, output: undefined }; jobs = jobs; }
        if (ended) return loadOut();
        if (follow) { await tick(); outEl && (outEl.scrollTop = outEl.scrollHeight); }
    }
    // the overview's "running now": each running job's latest line of output
    $: runningJobs = jobs.filter(j => j.state === 'running');
    let lastLine = {};
    async function loadLast() {
        for (const j of runningJobs) { const l = await jobLast(name, j.id); lastLine = { ...lastLine, [j.id]: l }; }
    }
    let confirmStop = false;
    async function stopPool() { confirmStop = false; await op('down'); }
    async function start() {
        starting = true;
        const j = await runJob(name, script, args);
        starting = false;
        if (j) { runDlg = false; await loadJobs(); openJob(j.id); }
    }

    // ---- files ----------------------------------------------------------------------------
    let files = [], open = null, text = '', orig = '', newName = '', adding = false, saving = false, confirmDel = false;
    $: pyFiles = files.filter(f => f.path.endsWith('.py'));
    $: if (!script && pyFiles.length) script = (pyFiles.find(f => f.path === 'job.py') || pyFiles[0]).path;
    async function loadFiles() { files = (await listFiles(name)).filter(f => f.path !== 'pool.json'); }
    // a file has a page of its own (#infra/pool-<name>/file-<path>), under the Files tab;
    // leaving a file with unsaved changes saves it, so nothing is lost by clicking away
    $: filePath = tab && tab.startsWith('file-') ? decodeURIComponent(tab.slice(5)) : null;
    $: if (filePath !== open) switchTo(filePath);
    const fileTab = (path) => 'file-' + encodeURIComponent(path);
    async function switchTo(path) {
        if (dirty && open) await save();
        confirmDel = false;
        if (!path) { open = null; text = orig = ''; return; }
        open = path;
        const t = await readFile(name, path);
        if (t != null && open === path) text = orig = t;
    }
    $: dirty = open && text !== orig;
    async function save() {
        saving = true;
        if (await writeFile(name, open, text)) {
            orig = text; toast(open === 'pool.yaml' ? (p?.running ? 'Saved. Restart the pool to apply it' : 'Saved') : `${open} saved`); loadFiles();
            if (open === 'pool.yaml') p = { ...p, ...(await getPool(name)) };
        }
        saving = false;
    }
    async function create() {
        const path = newName.trim().replace(/^\/+/, '');
        if (!path) return;
        const fresh = path.endsWith('.py') ? 'import pool\n\n\nif __name__ == "__main__":\n    print(pool.cpus(), "cores")\n' : '';
        if (await writeFile(name, path, fresh)) { adding = false; newName = ''; await loadFiles(); setTab(fileTab(path)); }
    }
    async function del() {
        confirmDel = false;
        if (await removeFile(name, open)) { toast(`${open} deleted`); text = orig = ''; open = null; await loadFiles(); setTab('files'); }
    }
    async function runOpen() {
        if (dirty) await save();
        const j = await runJob(name, open, '');
        if (j) { await loadJobs(); openJob(j.id); }
    }

    // ---- settings ---------------------------------------------------------------------------
    let confirmDelete = false;
    async function removePool() {
        try { const r = await deletePool(name); toast(`${name} deleted; its folder moved to ${r.moved_to.replace(/^\/Users\/[^/]+/, '~')}`); location.hash = href.pools; }
        catch (e) { toast(e.message); }
    }

    onMount(() => {
        load().then(() => p?.running && loadMetrics()); loadJobs(); loadFiles();
        const t1 = setInterval(() => visible() && load(), 3000);
        const t2 = setInterval(() => visible() && tab === 'overview' && p?.running && loadMetrics(), 2000);
        const t3 = setInterval(() => { if (!visible()) return; if (jobId && job?.state === 'running') loadOut(); }, 1500);
        const t4 = setInterval(() => visible() && (tab === 'jobs' || jobId || tab === 'overview') && loadJobs(), 4000);
        const t5 = setInterval(() => visible() && tab === 'overview' && runningJobs.length && loadLast(), 2000);
        return () => [t1, t2, t3, t4, t5].forEach(clearInterval);
    });
    // a start or stop just finished: refresh the live view and the sidebar
    let wasBusy = false;
    $: { if (wasBusy && !busy) { loadMetrics(); fetchPools(); } wasBusy = busy; }
    $: if (tab === 'files' || filePath) loadFiles();

    $: menuItems = p ? [
        p.running && { label: 'Restart and apply changes', icon: RotateCw, onClick: () => op('up') },
        p.running && { label: 'Stop', icon: Square, onClick: () => op('down') },
        { label: 'Delete pool…', icon: Trash2, danger: true, divider: true, onClick: () => { setTab('settings'); confirmDelete = true; } },
    ].filter(Boolean) : [];
</script>

<div class="ui-page">
    {#if missing}
        <div class="ui-head"><div><h1>{name}</h1><p>No pool by this name. <a class="ui-link" href={href.pools}>All pools</a></p></div></div>
    {:else if !p}
        <div class="ui-dim">Loading…</div>
    {:else}
        <div class="ui-head">
            <div class="id">
                <span class="icon" class:on={p.running}><Cpu size={22} /></span>
                <div>
                    <h1>{p.name} <StatusPill state={poolState(p)} label={poolStateLabel(p)} /></h1>
                    <div class="ui-meta">
                        <span>{plural(nodeIds.length, 'node')}{p.counts ? ` · ${p.counts.cores} cores` : ''}</span>
                        <span>Coordinator <b>{p.scheduler}</b></span>
                        <span>Python {p.python}{p.packages.length ? ' · ' + p.packages.join(', ') : ''}{p.setup ? ' · setup script' : ''}</span>
                    </div>
                </div>
            </div>
            <div class="ui-head-actions">
                {#if !p.running}<button class="ui-btn primary" disabled={busy} on:click={() => op('up')}>{#if busy}<Loader2 size={14} class="ui-spin" />{:else}<Play size={14} />{/if} Start</button>
                {:else}
                    {#if confirmStop}<button class="ui-btn" on:click={() => confirmStop = false}>Cancel</button><button class="ui-btn danger" disabled={busy} on:click={stopPool}><Square size={14} /> Stop {p.name}{runningJobs.length ? ' and its job' : ''}</button>
                    {:else}<button class="ui-btn" disabled={busy} on:click={() => confirmStop = true}><Square size={14} /> Stop</button>
                    <button class="ui-btn primary" on:click={() => runDlg = true}><Play size={14} /> Run a job</button>{/if}
                {/if}
                <ActionMenu items={menuItems} label="More actions" />
            </div>
        </div>

        <Tabs tabs={TABS} active={activeTab} onSelect={setTab} />

        {#if p.op && (p.op.state === 'running' || (p.op.state === 'error' && Date.now() / 1000 - p.op.ended < 600) || (p.op.ended && Date.now() / 1000 - p.op.ended < 6))}
            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">{p.op.kind === 'up' ? 'Starting' : 'Stopping'} {p.name}</h2>
                    <p class="ui-card-desc">{p.op.state === 'running' ? 'Installing what is missing, syncing the folder and starting the workers. The first start of a node takes a minute or two.' : p.op.state === 'done' ? `Finished ${ago(p.op.ended)}.` : 'It failed; the output says where.'}</p></div>
                    <StatusPill state={p.op.state === 'running' ? 'starting' : p.op.state === 'done' ? 'running' : 'error'} label={p.op.state === 'running' ? 'Working' : p.op.state === 'done' ? 'Done' : 'Failed'} /></div>
                <pre class="log small">{(p.op.log || []).join('\n') || '…'}</pre>
            </section>
        {/if}

        {#if tab === 'overview'}
            {#each runningJobs as j (j.id)}
                <section class="ui-card">
                    <div class="ui-card-head">
                        <div><h2 class="ui-card-title run-title"><span class="pulse"></span><span class="ui-mono">{j.script}{j.args.length ? ' ' + j.args.join(' ') : ''}</span></h2>
                            <p class="ui-card-desc">Running for {dur(j.started)} · started {new Date(j.started * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p></div>
                        <div class="ui-btns">
                            <button class="ui-btn sm" on:click={() => openJob(j.id)}>Full output</button>
                            <button class="ui-btn sm danger-outline" on:click={() => stopJob(name, j.id).then(loadJobs)}><Square size={13} /> Stop</button>
                        </div>
                    </div>
                    <div class="tail">
                        {#each (lastLine[j.id]?.length ? lastLine[j.id] : ['Getting the pool ready…']) as l, i (i)}
                            <div class:now={i === (lastLine[j.id]?.length || 1) - 1}>{l}</div>
                        {/each}
                    </div>
                </section>
            {/each}
            <div class="ui-stats">
                <div class="ui-stat"><span class="ui-stat-label">Compute in use</span><span class="ui-stat-value">{fresh ? busyNow.toFixed(1) : '—'}<small>of {coresTot || '—'} cores</small></span>
                    <div class="ui-meter"><i style="width: {coresTot ? Math.min(100, busyNow / coresTot * 100) : 0}%; background: var(--metric-cpu)"></i></div></div>
                <div class="ui-stat"><span class="ui-stat-label">{unit ? Unit : 'Tasks finished'}</span><span class="ui-stat-value">{fresh ? fmt(rateNow) : '—'}<small>per second</small></span><span class="ui-stat-sub">over the last 10 s</span></div>
                <div class="ui-stat"><span class="ui-stat-label">Queued</span><span class="ui-stat-value">{fresh ? queuedNow : '—'}<small>tasks</small></span><span class="ui-stat-sub">running or waiting for a core</span></div>
                <div class="ui-stat"><span class="ui-stat-label">Jobs</span><span class="ui-stat-value">{p.jobs.running}<small>running</small></span><span class="ui-stat-sub">{p.jobs.total} so far · <button class="ui-link" on:click={() => setTab('jobs')}>Jobs</button></span></div>
            </div>

            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">Compute in use</h2><p class="ui-card-desc">Cores busy across the pool; the top of the chart is all {capMax}. Each node's share is under Nodes.</p></div>
                    <div class="ui-seg">{#each [10, 30] as m}<button class:on={span === m} on:click={() => span = m}>{m} min</button>{/each}</div></div>
                {#if readings.length > 1}
                    <div class="chart"><LiveChart points={totalPts} windowMs={winMs} color="var(--metric-cpu)" min={0} max={capMax} interval={capMax / 4} unit=" cores" format={(v) => (+v).toFixed(1) + ' cores'} height={200} /></div>
                {:else}
                    <div class="ui-empty">{busy ? (p.op?.kind === 'up' ? 'Starting the pool…' : 'Stopping the pool…') : p.running ? (watching ? 'Collecting the first readings…' : 'Connecting to the pool…') : 'Start the pool to see it work.'}</div>
                {/if}
            </section>

            {#if readings.length > 2}
                <section class="ui-card">
                    <div class="ui-card-head"><div><h2 class="ui-card-title">{unit ? Unit : 'Tasks finished'} per second</h2><p class="ui-card-desc">On each node: its real throughput. Steady is good; dips mean its cores were waiting for work.</p></div>
                        <span class="big">{fresh ? fmt(rateNow) : '—'}<small>/s in all</small></span></div>
                    <div class="legend">
                        {#each order as id (id)}
                            <span class="lg"><i style="background: {colour[id]}"></i><b>{id}</b><span class="ui-dim">{cur[id] ? fmt(rate(id)) + '/s' : p.running ? 'not connected' : 'stopped'}</span></span>
                        {/each}
                    </div>
                    <div class="chart"><StackChart series={rateSeries} stacked={false} windowMs={winMs} height={200} format={(v) => fmt(v) + (unit ? ` ${unit}/s` : '/s')} /></div>
                </section>
            {/if}

            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">Nodes</h2><p class="ui-card-desc">{p.running ? 'Right now, as the coordinator sees them.' : 'Start the pool to put them to work.'}</p></div></div>
                <div class="ui-tbl-wrap"><table class="ui-tbl">
                    <thead><tr><th>Node</th><th>Cores busy</th><th class="c-md hist">Last {Math.max(1, Math.round(winMs / 60000))} min</th><th class="c-sm">{Unit}/s</th><th class="c-sm">Queued</th><th class="c-md">Memory</th></tr></thead>
                    <tbody>
                        {#each order as id (id)}
                            {@const n = cur[id]}
                            <tr>
                                <td><span class="cm"><i style="background: {colour[id]}"></i><span><b>{id}</b><div class="ui-dim sub ui-mono">{p.nodes[id].ssh}</div></span></span></td>
                                <td>{#if n}<div class="busy"><div class="bar"><i style="width: {Math.min(100, n.busy / n.cores * 100)}%; background: {colour[id]}"></i></div><span>{n.busy.toFixed(1)} <span class="ui-dim">of {n.cores}</span></span></div>
                                    {:else}<StatusPill state={busy ? 'starting' : p.running ? 'error' : 'stopped'} label={busy ? 'Restarting' : p.running ? (fresh ? 'Not connected' : 'Checking…') : 'Stopped'} />{/if}</td>
                                <td class="c-md hist"><Strip points={nodePts[id] || []} max={nodeCap[id]} color={colour[id]} windowMs={winMs} /></td>
                                <td class="c-sm">{n ? fmt(rate(id)) : '—'}</td>
                                <td class="c-sm">{n ? n.queued : '—'}</td>
                                <td class="c-md">{n ? `${gb(n.mem)} of ${gb(n.limit)}` : '—'}</td>
                            </tr>
                        {/each}
                    </tbody>
                </table></div>
            </section>

            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">Using it</h2><p class="ui-card-desc">Write a script under <button class="ui-link" on:click={() => setTab('files')}>Files</button> (start from <span class="ui-mono">job.py</span>) and run it under <button class="ui-link" on:click={() => setTab('jobs')}>Jobs</button>. In it, <span class="ui-mono">import pool</span> and <span class="ui-mono">pool.map(fn, items)</span> spreads the calls over every core. From a terminal on {SN}:</p></div></div>
                <div class="ui-card-body"><div class="cmd"><Terminal size={14} /><CopyText text="cd ~/pools/{p.name} && ~/pool/pool.py run job.py" /></div></div>
            </section>

        {:else if tab === 'jobs'}
            <div class="ui-listbar">
                <label class="ui-search"><Search size={14} /><input placeholder="Search runs" bind:value={jq} /></label>
                <div class="ui-seg">{#each JFILTERS as [k, l]}<button class:on={jstate === k} on:click={() => jstate = k}>{l}</button>{/each}</div>
                <span class="ui-count">{plural(shownJobs.length, 'run')}</span>
            </div>
            {#if jobs.length}
                <section class="ui-card"><div class="ui-tbl-wrap"><table class="ui-tbl">
                    <thead><tr><th>Script</th><th>State</th><th class="c-md">Started</th><th class="c-sm">Took</th><th class="c-sm">Exit</th></tr></thead>
                    <tbody>
                        {#each shownJobs as j (j.id)}
                            <tr class="click" on:click={() => openJob(j.id)}>
                                <td><b class="ui-mono">{j.script}</b>{#if j.args.length}<span class="ui-mono ui-dim argv">{j.args.join(' ')}</span>{/if}</td>
                                <td><StatusPill state={JOB_PILL[j.state]} label={JOB_LABEL[j.state]} /></td>
                                <td class="c-md">{new Date(j.started * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}<span class="ui-dim"> · {ago(j.started)}</span></td>
                                <td class="c-sm">{dur(j.started, j.ended)}</td>
                                <td class="c-sm ui-mono">{j.rc ?? '—'}</td>
                            </tr>
                        {:else}<tr><td colspan="5" class="ui-dim">No runs match.</td></tr>{/each}
                    </tbody>
                </table></div></section>
            {:else}<div class="ui-card ui-empty">No runs yet. <button class="ui-link" on:click={() => runDlg = true}>Run a job</button> to start one.</div>{/if}

        {:else if jobId}
            <button class="back" on:click={() => setTab('jobs')}><ArrowLeft size={14} /> All runs</button>
            {#if job}
                <section class="ui-card">
                    <div class="ui-card-head">
                        <div><h2 class="ui-card-title run-title">{#if job.state === 'running'}<span class="pulse"></span>{/if}<span class="ui-mono">{job.script}{job.args.length ? ' ' + job.args.join(' ') : ''}</span> <StatusPill state={JOB_PILL[job.state]} label={JOB_LABEL[job.state]} /></h2>
                            <p class="ui-card-desc">Started {new Date(job.started * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' })} · {job.state === 'running' ? 'running for ' + dur(job.started) : `took ${dur(job.started, job.ended)}`}{job.rc != null ? ` · exit code ${job.rc}` : ''}</p></div>
                        <div class="ui-btns">
                            {#if job.state === 'running'}<button class="ui-btn sm danger-outline" on:click={() => stopJob(name, job.id).then(loadJobs)}><Square size={13} /> Stop</button>
                            {:else}
                                <button class="ui-btn sm" on:click={() => { script = job.script; args = job.args.join(' '); start(); }}><RotateCw size={13} /> Run again</button>
                                <button class="ui-btn sm danger-outline" on:click={async () => { await deleteJob(name, job.id); sel = null; await loadJobs(); setTab('jobs'); }} aria-label="Delete this run"><Trash2 size={13} /></button>
                            {/if}
                        </div>
                    </div>
                    <pre class="log full" bind:this={outEl} on:scroll={() => outEl && (follow = outEl.scrollTop + outEl.clientHeight >= outEl.scrollHeight - 30)}>{out || (job.state === 'running' ? 'Getting the pool ready: syncing the folder to every node and starting workers where something changed. Your script\'s output appears here as it prints.' : '(no output)')}</pre>
                </section>
            {:else}<div class="ui-card ui-empty">{jobs.length ? 'This run was deleted.' : 'Loading…'}</div>{/if}

        {:else if tab === 'files'}
            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">Files</h2><p class="ui-card-desc"><span class="ui-mono">~/pools/{p.name}</span> · synced to every node when a job starts.</p></div>
                    <button class="ui-btn sm" on:click={() => adding = !adding}><Plus size={13} /> New file</button></div>
                {#if adding}<form class="nf" on:submit|preventDefault={create}><input class="ui-input sm ui-mono" bind:value={newName} placeholder="analysis.py" spellcheck="false" /><button class="ui-btn sm primary">Create</button><button type="button" class="ui-btn sm" on:click={() => adding = false}>Cancel</button></form>{/if}
                <div class="ui-tbl-wrap"><table class="ui-tbl">
                    <thead><tr><th>Name</th><th class="c-sm">Size</th><th class="c-md">Changed</th></tr></thead>
                    <tbody>
                        {#each files as f (f.path)}
                            <tr class:click={f.text} class:dim={!f.text} on:click={() => f.text && setTab(fileTab(f.path))}>
                                <td><span class="fname"><FileCode size={14} /><span class="ui-mono">{f.path}</span>{#if f.path === 'pool.yaml'}<span class="ui-dim gen">definition</span>{/if}</span></td>
                                <td class="c-sm ui-dim">{f.size < 1024 ? f.size + ' B' : (f.size / 1024).toFixed(1) + ' KB'}</td>
                                <td class="c-md ui-dim">{ago(f.modified)}</td>
                            </tr>
                        {:else}<tr><td colspan="3" class="ui-dim">Empty folder.</td></tr>{/each}
                    </tbody>
                </table></div>
            </section>

        {:else if filePath}
            <button class="back" on:click={() => setTab('files')}><ArrowLeft size={14} /> All files</button>
            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title ui-mono">{filePath}{dirty ? ' •' : ''}</h2><p class="ui-card-desc">{filePath === 'pool.yaml' && !dirty ? "The pool's definition, the same as Settings. Saving checks it first." : dirty ? 'Unsaved changes · ⌘S saves (leaving the file saves it too)' : 'Saved · synced to every node when a job starts'}</p></div>
                    <div class="ui-btns">
                        {#if filePath.endsWith('.py')}<button class="ui-btn sm" on:click={runOpen}><Play size={13} /> Run</button>{/if}
                        <button class="ui-btn sm primary" disabled={!dirty || saving} on:click={save}><Save size={13} /> Save</button>
                        {#if filePath !== 'pool.yaml'}
                            {#if confirmDel}<button class="ui-btn sm" on:click={() => confirmDel = false}>Cancel</button><button class="ui-btn sm danger" on:click={del}><Trash2 size={13} /> Delete</button>
                            {:else}<button class="ui-btn sm danger-outline" on:click={() => confirmDel = true} aria-label="Delete {filePath}"><Trash2 size={13} /></button>{/if}
                        {/if}
                    </div></div>
                <div class="code full">{#key open}{#if open === filePath}<CodeEditor bind:value={text} path={open} onSave={() => dirty && save()} />{/if}{/key}</div>
            </section>

        {:else if tab === 'settings'}
            {#key p.name}<PoolForm pool={p} saved={(x) => { p = { ...p, ...x }; toast(p.running ? 'Saved. Restart the pool to apply it (⋯ → Restart and apply changes)' : 'Saved'); }} />{/key}
            <section class="ui-card danger">
                <div class="ui-card-head"><div><h2 class="ui-card-title">Delete pool</h2><p class="ui-card-desc">Removes it from the dashboard. Its folder, with your scripts and job history, moves to <span class="ui-mono">~/pools/.trash</span>, so nothing is lost. {p.running ? 'Stop it first.' : ''}</p></div></div>
                <div class="ui-card-foot">
                    {#if confirmDelete}<div class="ui-btns"><button class="ui-btn" on:click={() => confirmDelete = false}>Cancel</button><button class="ui-btn danger" disabled={p.running} on:click={removePool}><Trash2 size={14} /> Delete {p.name}</button></div>
                    {:else}<button class="ui-btn danger-outline" on:click={() => confirmDelete = true}><Trash2 size={14} /> Delete pool…</button>{/if}
                </div>
            </section>
        {/if}
    {/if}
</div>

<Modal open={runDlg} onClose={() => runDlg = false} width={480} title="Run a job" description="Runs a script from the pool's folder on every node in {name}.">
    <form class="dlg" id="run-form" on:submit|preventDefault={() => script && start()}>
        <label>Script
            <select class="ui-input" bind:value={script}>{#each pyFiles as f}<option value={f.path}>{f.path}</option>{:else}<option value="">No .py files yet</option>{/each}</select>
        </label>
        <label>Arguments <span class="ui-dim">(optional)</span>
            <input class="ui-input ui-mono" bind:value={args} placeholder="e.g. 60" spellcheck="false" />
        </label>
        <p class="ui-hint">{p?.running ? 'The pool is running, so it starts right away.' : 'The pool starts first; that takes about 20 seconds.'} Write or change scripts under <button type="button" class="ui-link" on:click={() => { runDlg = false; setTab('files'); }}>Files</button>.</p>
    </form>
    <svelte:fragment slot="footer">
        <div class="ui-btns"><button class="ui-btn" on:click={() => runDlg = false}>Cancel</button><button class="ui-btn primary" type="submit" form="run-form" disabled={!script || starting}>{#if starting}<Loader2 size={14} class="ui-spin" />{:else}<Play size={14} />{/if} Run</button></div>
    </svelte:fragment>
</Modal>

<style>
    .id { display: flex; align-items: center; gap: 16px; min-width: 0; }
    .ui-head { padding: 4px 0 2px; }
    .ui-head h1 { line-height: 1.2; }
    .icon { width: 52px; height: 52px; border-radius: 12px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); border: 1px solid var(--border); }
    .icon.on { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
    .id .ui-meta { margin-top: 6px; }
    .sub { font-size: 12px; margin-top: 2px; }
    .chart { padding: 4px 16px 12px; }
    .run-title { display: flex; align-items: center; gap: 10px; }
    .argv { margin-left: 8px; }
    .back { display: inline-flex; align-items: center; gap: 6px; align-self: flex-start; font-size: 13px; color: var(--text-secondary); cursor: pointer; padding: 2px 0; }
    .back:hover { color: var(--text-primary); }
    .log.full { max-height: none; height: calc(100vh - 360px); min-height: 360px; }
    .dlg { display: flex; flex-direction: column; gap: 12px; }
    .dlg label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 500; }
    .dlg .ui-hint { margin: 0; }
    .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--green); flex-shrink: 0; animation: pulse 1.6s ease-in-out infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
    .tail { padding: 12px 20px 14px; border-top: 1px solid var(--border); background: var(--highlight-3); border-radius: 0 0 10px 10px; font: 12.5px/1.65 'JetBrains Mono', monospace; color: var(--text-secondary); }
    .tail div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tail .now { color: var(--text-primary); }
    .big { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text-primary); white-space: nowrap; }
    .big small { font-size: 13px; font-weight: 500; color: var(--text-secondary); margin-left: 2px; }
    .legend { display: flex; flex-wrap: wrap; gap: 6px 20px; padding: 0 20px 4px; font-size: 12.5px; }
    .lg { display: inline-flex; align-items: center; gap: 7px; }
    .lg i, .cm i { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
    .lg b { font-weight: 600; color: var(--text-primary); }
    .cm { display: inline-flex; align-items: center; gap: 10px; }
    .hist { width: 26%; min-width: 160px; }
    .busy { display: flex; align-items: center; gap: 10px; min-width: 150px; font-variant-numeric: tabular-nums; }
    .busy .bar { flex: 1; max-width: 120px; height: 8px; border-radius: 4px; background: var(--highlight-15); overflow: hidden; }
    .busy .bar i { display: block; height: 100%; border-radius: 4px; transition: width .4s ease; }
    .pad { margin: 0; padding: 0 20px 16px; }
    .log { margin: 0; padding: 14px 20px; border-top: 1px solid var(--border); background: var(--highlight-3); font: 12.5px/1.55 'JetBrains Mono', monospace; color: var(--text-primary); white-space: pre-wrap; word-break: break-word; max-height: 520px; overflow: auto; border-radius: 0 0 10px 10px; }
    .log.small { max-height: 220px; }
    .cmd { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; border-radius: var(--radius-card, 8px); background: var(--highlight-5); border: 1px solid var(--border); color: var(--text-secondary); }
    .cmd :global(svg) { flex-shrink: 0; margin-top: 4px; }
    .runbar { display: flex; gap: 8px; padding: 16px 20px 10px; flex-wrap: wrap; }
    .runbar select { width: 220px; }
    .args { flex: 1; min-width: 160px; }
    tr.sel td { background: var(--accent-soft); }
    tr.dim td { opacity: 0.5; }
    .more { padding: 10px 20px 14px; border-top: 1px solid var(--border); font-size: 13px; }
    .fname { display: inline-flex; align-items: center; gap: 8px; color: var(--text-secondary); }
    .fname .ui-mono { color: var(--text-primary); font-size: 12.5px; }
    .gen { font-size: 11.5px; }
    .nf { display: flex; gap: 6px; padding: 0 20px 14px; max-width: 520px; }
    .nf .ui-input { flex: 1; min-width: 0; height: 30px; font-size: 12.5px; padding: 0 8px; }
    .code.full { height: calc(100vh - 330px); min-height: 380px; resize: none; }
    .code { height: 560px; border-top: 1px solid var(--border); background: var(--highlight-3); border-radius: 0 0 10px 10px; overflow: hidden; resize: vertical; }

</style>
