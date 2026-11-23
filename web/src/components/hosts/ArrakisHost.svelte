<script>
    import { SN } from '../../lib/server.js';
    import { openShell } from '../../lib/terminal.js';
    // Arrakis's page, shaped like a machine's: icon header, then tabs.
    // Overview (usage, where the memory goes, details) · Machines (in the OrbStack VM)
    // · Apps (on macOS itself) · Metrics (history charts).
    import { onMount } from 'svelte';
    import WebLinkButton from '../ui/WebLinkButton.svelte';
    import { Search, Layers, AppWindow, Plus, LayoutGrid, List, Laptop, Terminal, ArrowRight, ChevronRight, HardDrive, Lock, SquareTerminal } from 'lucide-svelte';
    import { disks, disksError, fetchDisks, ejectDisk, mountVolume, unmountVolume, storageTotals } from '../../lib/storage.js';
    import { fmtDisk } from '../../lib/hosts.js';
    import { stats, machines, machineUsage, gbFromMib, visible } from '../../lib/stores.js';
    import { services, fmtMb } from '../../lib/services.js';
    import { imageLabel, fmtBytes } from '../../lib/machines.js';
    import { href } from '../../lib/infra.js';
    import { hostIcon, arrakisModel } from '../../lib/hosts.js';
    import ResourceCard from '../ui/ResourceCard.svelte';
    import StatusPill from '../ui/StatusPill.svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';
    import Tabs from '../ui/Tabs.svelte';
    import CopyText from '../ui/CopyText.svelte';
    import LiveChart from '../ui/LiveChart.svelte';
    import PairGrid from '../ui/PairGrid.svelte';
    import MachineList from '../machines/MachineList.svelte';
    import StorageView from './StorageView.svelte';
    import OrbStackSettings from '../machines/OrbStackSettings.svelte';

    export let arrakis = {};
    export let vm = {};
    export let tab = 'overview';
    export let setTab = () => {};

    $: hd = $stats?.host?.details || {};
    $: machineList = $machines?.machines || [];
    $: runningMachines = machineList.filter(m => m.state === 'running').length;
    $: vmContainers = machineList.reduce((a, m) => a + ($machineUsage[m.name]?.runs?.containers_running || 0), 0);
    $: apps = ($services || []).filter(s => s.host === 'Mac' && !/orbstack/i.test(s.name || ''))
        .sort((a, b) => (b.status === 'running') - (a.status === 'running') || (b.mem_mb || 0) - (a.mem_mb || 0));
    $: TABS = [
        { id: 'overview', label: 'Overview' },
        { id: 'vm', label: `OrbStack VM (${machineList.length})` },
        { id: 'apps', label: `Apps (${apps.length})` },
        { id: 'storage', label: `Storage${$disks ? ` (${$disks.length})` : ''}` },
        { id: 'metrics', label: 'Metrics' },
        { id: 'settings', label: 'Settings' },
    ];

    const pct = (a, b) => b ? Math.min(100, Math.max(0, (a / b) * 100)) : 0;
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
    const fmtUp = (s) => { if (!s) return '—'; const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`; };
    const gb = (v) => v.toFixed(1) + ' GB';

    $: cores = arrakis.cores || 0;
    $: cpuNow = isFinite(arrakis.cpu) ? arrakis.cpu : 0;
    $: totalMem = arrakis.mem?.total || 0;
    // where the memory goes: the VM (all the machines), the tracked apps, the rest of macOS, free
    $: vmGb = vm.running ? vm.memGb : 0;
    $: appGb = apps.reduce((a, s) => a + (s.status === 'running' ? (s.mem_mb || 0) / 1024 : 0), 0);
    $: otherGb = Math.max(0, (arrakis.mem?.used || 0) - vmGb - appGb);
    $: freeGb = Math.max(0, totalMem - vmGb - appGb - otherGb);
    // the parts of Arrakis: CPU as a share of all cores, memory in GB
    $: appCpu = cores ? apps.reduce((a, s) => a + (s.status === 'running' ? +s.cpu || 0 : 0), 0) / cores : 0;
    $: vmCpuAll = vm.running ? vm.cpu : 0;
    $: layers = [
        { id: 'vm', name: 'OrbStack VM', sub: `${runningMachines} of ${plural(machineList.length, 'machine')} running${vmContainers ? ' · ' + plural(vmContainers, 'container') : ''}`, cpu: vmCpuAll, mem: vmGb, of: vm.limitGb ? `of ${vm.limitGb.toFixed(0)} GB` : '', shade: 1, tab: 'vm' },
        { id: 'apps', name: 'Apps on macOS', sub: apps.filter(s => s.status === 'running').map(s => s.name).join(', ') || 'none running', cpu: appCpu, mem: appGb, shade: 0.6, tab: 'apps' },
        { id: 'macos', name: 'macOS and the rest', sub: 'the system and untracked apps', cpu: Math.max(0, cpuNow - vmCpuAll - appCpu), mem: otherGb, shade: 0.3 },
        { id: 'free', name: 'Free', sub: 'available memory', cpu: null, mem: freeGb, shade: 0 },
    ];
    $: detailRows = [
        [{ k: 'Model', v: $arrakisModel ? `${$arrakisModel}, Apple silicon` : 'Apple silicon' }, { k: 'LAN', v: hd['Local IP'] || '—', copy: true }],
        [{ k: 'Cores', v: String(cores) }, { k: 'Tailscale', v: hd['Tailscale IP'] || '—', copy: true }],
        [{ k: 'Memory', v: `${totalMem.toFixed(0)} GB` }, { k: 'Dashboard', v: hd['Tailscale IP'] ? `http://${hd['Tailscale IP']}:5050` : '—', copy: true }],
        [{ k: 'Disk', v: arrakis.disk ? `${arrakis.disk.total.toFixed(0)} GB, shared with the VM` : '—' }, { k: 'Shell', action: { label: 'Open a terminal', onClick: () => go('#terminal') } }],
    ];
    $: memSegs = [
        { name: 'OrbStack VM', v: vmGb, shade: 1, note: vm.limitGb ? `can grow to ${vm.limitGb.toFixed(0)} GB` : '' },
        { name: 'Apps', v: appGb, shade: 0.6 },
        { name: 'macOS and the rest', v: otherGb, shade: 0.3 },
    ];

    // ---- machines / apps tabs: search, state, cards or table (remembered) -----------------
    let q = '', state = 'all';
    let view = 'grid';
    try { view = localStorage.getItem('arrakis_host_view') || 'grid'; } catch (e) {}
    function setView(v) { view = v; try { localStorage.setItem('arrakis_host_view', v); } catch (e) {} }
    $: if (tab) { q = ''; state = 'all'; }
    $: match = (s, running) => (state === 'all' || (state === 'running') === running) && (!q || s.toLowerCase().includes(q.toLowerCase()));
    $: shownApps = apps.filter(s => match(`${s.name} ${s.type || ''}`, s.status === 'running'));
    $: u = (m) => m.state === 'running' ? $machineUsage[m.name] : null;
    const runsText = (r) => [r.containers ? plural(r.containers, 'container') : null, r.services ? plural(r.services, 'service') : null].filter(Boolean).join(' · ') || 'nothing extra';
    const go = (to) => location.hash = to;

    // ---- metrics tab ----------------------------------------------------------------------
    const RANGES = [{ id: '1h', label: '1H', hours: 1 }, { id: '24h', label: '24H', hours: 24 }, { id: '7d', label: '7D', hours: 168 }, { id: '30d', label: '30D', hours: 720 }];
    let range = RANGES[0], hist = [];
    let spark = [];
    async function loadHistory() {
        try {
            if (tab === 'metrics') { const j = await fetch(`/api/history?hours=${range.hours}`).then(r => r.json()); if (j.status === 'success') hist = j.data.host || []; }
            if (tab === 'overview') { const j = await fetch('/api/history?hours=1').then(r => r.json()); if (j.status === 'success') spark = j.data.host || []; }
        } catch (e) {}
    }
    $: if ((tab === 'metrics' && range) || tab === 'overview') loadHistory();
    $: sparkCpu = spark.filter(p => p.cpu != null).map(p => [p.ts * 1000, p.cpu]);
    $: sparkMem = spark.filter(p => p.mem != null).map(p => [p.ts * 1000, p.mem]);
    $: cpuPts = hist.map(p => [p.ts * 1000, p.cpu]);
    $: memPts = hist.map(p => [p.ts * 1000, p.mem]);
    // the internal disk, every 5 minutes (the 1H view shows the last day: it barely moves)
    let disk = [];
    async function loadDisk() {
        const want = Math.max(24, range.hours);
        try { const j = await fetch(`/api/hosts/arrakis/disk?hours=${want}`).then(r => r.json()); if (j.status === 'success' && want === Math.max(24, range.hours)) disk = j.data; } catch (e) {}
    }
    $: if (tab === 'metrics') range, loadDisk();
    $: diskPts = disk.map(p => [p.ts * 1000, p.used / 1e9]);
    $: diskMax = arrakis.disk ? Math.ceil(arrakis.disk.total) : null;
    $: diskReady = diskPts.length > 1 && diskPts.at(-1)[0] - diskPts[0][0] >= 2 * 3600000;
    // ---- storage: every drive on Arrakis --------------------------------------------------
    $: st = storageTotals($disks);
    // the Overview's storage tile: the internal disk plus every external drive, as one figure
    $: diskAll = { used: (arrakis.disk ? arrakis.disk.used * 1e9 : 0) + st.external.used, size: (arrakis.disk ? arrakis.disk.total * 1e9 : 0) + st.external.size };

    onMount(() => {
        fetchDisks();
        const ds = setInterval(() => visible() && fetchDisks(), 15000);
        const t = setInterval(() => visible() && loadHistory(), 30000);
        return () => { clearInterval(t); clearInterval(ds); };
    });

    $: menuItems = [
        { label: 'Open a terminal', icon: Terminal, onClick: () => go('#terminal') },
        { label: 'OrbStack VM and pool', icon: Layers, onClick: () => setTab('vm') },
    ];
</script>

<div class="ui-page">
    <div class="ui-head">
        <div class="id">
            <span class="icon on"><svelte:component this={hostIcon($arrakisModel, 'macOS')} size={22} /></span>
            <div>
                <h1>{SN} <StatusPill state="running" label="Online" /><span class="ui-tag">This server</span></h1>
                <div class="ui-meta">
                    <span>{$arrakisModel || 'Mac'} · macOS · {cores} cores · {totalMem.toFixed(0)} GB</span>
                    {#if hd['Local IP']}<span>LAN <b class="ui-mono">{hd['Local IP']}</b></span>{/if}
                    {#if hd['Tailscale IP']}<span>Tailscale <b class="ui-mono">{hd['Tailscale IP']}</b></span>{/if}
                    <span>Up {fmtUp(arrakis.up)}</span>
                </div>
            </div>
        </div>
        <div class="ui-head-actions">
            <button class="ui-btn" on:click={() => openShell('mac')} title="A tmux session named shell on the Mac"><SquareTerminal size={14} /> Shell</button>
            <a class="ui-btn primary" href={href.newMachine}><Plus size={15} /> Create machine</a>
            <ActionMenu items={menuItems} label="More actions" />
        </div>
    </div>

    <Tabs tabs={TABS} active={tab} onSelect={setTab} />

    {#if tab === 'overview'}
        <div class="ui-stats">
            <div class="ui-stat">
                <span class="ui-stat-label">CPU</span>
                <span class="ui-stat-value">{cpuNow.toFixed(1)}%<small>of {cores} cores</small></span>
                <div class="spark">{#if sparkCpu.length > 1}<LiveChart points={sparkCpu} windowMs={3600000} height={36} bare />{/if}</div>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Memory</span>
                <span class="ui-stat-value">{arrakis.mem ? gb(arrakis.mem.used) : '—'}<small>of {totalMem.toFixed(0)} GB</small></span>
                <div class="spark">{#if sparkMem.length > 1}<LiveChart points={sparkMem} windowMs={3600000} height={36} color="var(--metric-mem)" min={0} max={totalMem || null} bare />{/if}</div>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Storage</span>
                <span class="ui-stat-value">{fmtDisk(diskAll.used)}<small>of {fmtDisk(diskAll.size)}</small></span>
                <div class="ui-meter"><i style="width: {pct(diskAll.used, diskAll.size)}%; background: var(--text-secondary)"></i></div>
                <span class="ui-stat-sub">{fmtDisk(diskAll.size - diskAll.used)} free{#if st.external.count}&nbsp;on {st.external.count + 1} drives · <button class="ui-link" on:click={() => setTab('storage')}>Storage</button>{/if}</span>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Uptime</span>
                <span class="ui-stat-value">{fmtUp(arrakis.up)}</span>
                <span class="ui-stat-sub">{arrakis.up ? 'since ' + new Date(Date.now() - arrakis.up * 1000).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''}</span>
            </div>
        </div>

        <!-- one table: what on Arrakis uses the CPU and memory -->
        <section class="ui-card">
            <div class="ui-card-head">
                <div><h2 class="ui-card-title">What uses {SN}</h2><p class="ui-card-desc">The machines run inside the OrbStack VM; apps run on macOS itself.</p></div>
            </div>
            <div class="use-bar">
                <div class="ui-segbar tall" title="Memory">
                    {#each layers.filter(l => l.mem != null) as l}<i style="width: {pct(l.mem, totalMem)}%; background: var(--metric-mem); opacity: {l.shade}"></i>{/each}
                </div>
                <span class="ub-k">{arrakis.mem ? gb(arrakis.mem.used) : '—'} of {totalMem.toFixed(0)} GB memory in use</span>
            </div>
            <div class="lt" role="table">
                <div class="lt-r lt-h" role="row"><span></span><span>Part</span><span>CPU</span><span>Memory</span><span></span></div>
                {#each layers as l (l.id)}
                    <svelte:element this={l.tab ? 'button' : 'div'} class="lt-r" class:link={l.tab} role="row" on:click={() => l.tab && setTab(l.tab)}>
                        <span class="sw" class:free={l.id === 'free'} style={l.id === 'free' ? '' : `background: var(--metric-mem); opacity: ${l.shade}`}></span>
                        <span class="lt-n"><b>{l.name}</b><small>{l.sub}</small></span>
                        <span class="lt-v">{l.cpu != null ? l.cpu.toFixed(1) + '%' : ''}</span>
                        <span class="lt-v">{gb(l.mem)}{#if l.of}<small>{l.of}</small>{/if}</span>
                        <span class="lt-go">{#if l.tab}<ChevronRight size={15} />{/if}</span>
                    </svelte:element>
                {/each}
            </div>
        </section>

        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Details</h2><p class="ui-card-desc">The hardware, and how to reach it.</p></div></div>
            <PairGrid rows={detailRows} heads={["Hardware", "Network"]} />
        </section>

    {:else if tab === 'vm'}
        {#if $machines}
            <MachineList data={$machines} embedded open={(n, t = null) => go(href.machine(n, t))} create={() => go(href.newMachine)} />
        {:else}<div class="ui-dim">Loading machines…</div>{/if}

    {:else if tab === 'apps'}
        <div class="ui-listbar">
            <label class="ui-search"><Search size={14} /><input placeholder="Search apps" bind:value={q} /></label>
            <div class="ui-seg">
                <button class:on={state === 'all'} on:click={() => state = 'all'}>All</button>
                <button class:on={state === 'running'} on:click={() => state = 'running'}>Running</button>
                <button class:on={state === 'stopped'} on:click={() => state = 'stopped'}>Stopped</button>
            </div>
            <span class="ui-count">{plural(shownApps.length, 'app')}</span>
            <div class="ui-seg view" role="group" aria-label="View">
                <button class:on={view === 'grid'} on:click={() => setView('grid')} title="Cards" aria-label="Cards"><LayoutGrid size={14} /></button>
                <button class:on={view === 'table'} on:click={() => setView('table')} title="Table" aria-label="Table"><List size={14} /></button>
            </div>
        </div>

            <p class="ui-hint lead">Apps and daemons on macOS itself, outside the VM.</p>
            {#if view === 'grid'}
                <div class="ui-cardgrid">
                    {#each shownApps as s (s.key)}
                        {@const run = s.status === 'running'}
                        <ResourceCard name={s.name} sub={s.type || 'app'} icon={AppWindow} on={run} off={!run} on:open={() => go(href.service(s.id))}
                            meters={[
                                { k: 'CPU', p: run && cores ? (+s.cpu || 0) / cores : 0, color: 'var(--metric-cpu)', v: run && cores ? ((+s.cpu || 0) / cores).toFixed(1) + '%' : '—', of: `of ${cores} cores` },
                                { k: 'Memory', p: run ? pct((s.mem_mb || 0) / 1024, totalMem) : 0, color: 'var(--metric-mem)', v: run ? fmtMb(s.mem_mb) : '—', of: `of ${totalMem.toFixed(0)} GB` },
                                { k: 'Up', v: run ? fmtUp(s.uptime_seconds) : '—', of: run ? 'since start' : '' },
                            ]}
                            note={run ? 'Running' : 'Not running'}>
                            <svelte:fragment slot="status"><WebLinkButton svc={s} /></svelte:fragment>
                        </ResourceCard>
                    {:else}<div class="ui-card ui-empty">No apps match.</div>{/each}
                </div>
            {:else}
                <section class="ui-card"><div class="ui-tbl-wrap"><table class="ui-tbl">
                    <thead><tr><th>Name</th><th>Status</th><th class="c-sm">CPU</th><th class="c-sm">Memory</th><th class="c-md">Up</th><th class="shrink"></th></tr></thead>
                    <tbody>
                        {#each shownApps as s (s.key)}
                            {@const run = s.status === 'running'}
                            <tr class="click" on:click={() => go(href.service(s.id))}>
                                <td><div class="nm-cell"><span class="nm">{s.name}</span></div><div class="sub">{s.type || 'app'}</div></td>
                                <td><StatusPill state={run ? 'running' : 'stopped'} /></td>
                                <td class="c-sm"><div class="use"><span class="num">{run && cores ? ((+s.cpu || 0) / cores).toFixed(1) + '%' : '—'}</span><div class="mini"><i style="width: {run && cores ? (+s.cpu || 0) / cores : 0}%; background: var(--metric-cpu)"></i></div><span class="sub">of {cores} cores</span></div></td>
                                <td class="c-sm"><div class="use"><span class="num">{run ? fmtMb(s.mem_mb) : '—'}</span><div class="mini"><i style="width: {run ? pct((s.mem_mb || 0) / 1024, totalMem) : 0}%; background: var(--metric-mem)"></i></div><span class="sub">of {totalMem.toFixed(0)} GB</span></div></td>
                                <td class="c-md">{run ? fmtUp(s.uptime_seconds) : '—'}</td>
                                <td><WebLinkButton svc={s} /></td>
                            </tr>
                        {:else}<tr><td colspan="6" class="ui-dim">No apps match.</td></tr>{/each}
                    </tbody>
                </table></div></section>
            {/if}

    {:else if tab === 'storage'}
        {#if $disks}
            <StorageView disks={$disks} onEject={ejectDisk} onMount={mountVolume} hint="Drives plugged into {SN} show up here within 15 seconds. Eject a drive here before unplugging it." />
        {:else if $disksError}
            <div class="ui-banner warn">{$disksError}</div>
        {:else}<div class="ui-dim">Reading drives…</div>{/if}

    {:else if tab === 'metrics'}
        <div class="ctl">
            <p class="ui-hint" style="margin: 0">{range.hours === 1 ? '1-minute averages' : range.hours === 24 ? '5-minute averages' : range.hours === 168 ? 'Hourly averages' : '3-hour averages'} · {SN} as a whole, the VM and macOS together.</p>
            <div class="ui-seg">{#each RANGES as r}<button class:on={range === r} on:click={() => range = r}>{r.label}</button>{/each}</div>
        </div>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">CPU</h2><p class="ui-card-desc">Percent of all {cores} cores</p></div><span class="big">{cpuNow.toFixed(1)}%</span></div>
            <div class="ui-card-body chart">{#if cpuPts.length > 1}<LiveChart points={cpuPts} windowMs={range.hours * 3600000} color="var(--metric-cpu)" min={0} max={100} interval={25} format={(v) => v + '%'} height={200} />{:else}<div class="ui-empty">Loading…</div>{/if}</div>
        </section>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Memory</h2><p class="ui-card-desc">Used, of {totalMem.toFixed(0)} GB</p></div><span class="big">{arrakis.mem ? gb(arrakis.mem.used) : '—'}</span></div>
            <div class="ui-card-body chart">{#if memPts.length > 1}<LiveChart points={memPts} windowMs={range.hours * 3600000} color="var(--metric-mem)" min={0} max={Math.ceil(totalMem) || 16} interval={4} format={(v) => v + ' GB'} height={200} />{:else}<div class="ui-empty">Loading…</div>{/if}</div>
        </section>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Disk</h2><p class="ui-card-desc">Internal disk used, of {arrakis.disk ? arrakis.disk.total.toFixed(0) + ' GB' : '—'} · sampled every 5 minutes{range.hours === 1 ? ', last 24 hours' : ''} · drives on <button class="ui-link" on:click={() => setTab('storage')}>Storage</button></p></div><span class="big">{arrakis.disk ? arrakis.disk.used.toFixed(0) + ' GB' : '—'}</span></div>
            <div class="ui-card-body chart">{#if diskReady}<LiveChart points={diskPts} windowMs={Math.max(24, range.hours) * 3600000} color="var(--text-secondary)" min={0} max={diskMax} interval={diskMax ? diskMax / 4 : null} format={(v) => Math.round(v) + ' GB'} height={160} />{:else}<div class="ui-empty">Collecting samples (one every 5 minutes)…</div>{/if}</div>
        </section>
    {:else if tab === 'settings'}
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">This server</h2><p class="ui-card-desc">{SN} runs the dashboard itself, so it reports without an agent.</p></div></div>
            <div class="rows">
                <div class="ui-form-row">
                    <div><div class="ui-label">Dashboard address</div><div class="ui-hint">Over Tailscale, from your own devices</div></div>
                    {#if hd['Tailscale IP']}<CopyText text={`http://${hd['Tailscale IP']}:5050`} />{:else}<span class="ui-dim">—</span>{/if}
                </div>
                <div class="ui-form-row">
                    <div><div class="ui-label">Agent</div><div class="ui-hint">What other computers install to report in</div></div>
                    <span class="ui-dim">Not needed on this server</span>
                </div>
            </div>
        </section>
        {#if $machines}
            <OrbStackSettings data={$machines} hostName={SN}>
                <div class="ui-form-row" slot="manage">
                    <div><div class="ui-label">Managed by the dashboard</div><div class="ui-hint">Create, limit and share machines from here</div></div>
                    <span class="ui-dim">Always: this is the server</span>
                </div>
            </OrbStackSettings>
        {:else}<div class="ui-card ui-empty">Loading…</div>{/if}
    {/if}
</div>

<style>
    /* header, as on a machine's page */
    .id { display: flex; align-items: center; gap: 16px; min-width: 0; }
    .ui-head { padding: 4px 0 2px; }
    .ui-head h1 { line-height: 1.2; }
    .icon { width: 52px; height: 52px; border-radius: 12px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); border: 1px solid var(--border); }
    .icon.on { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
    .id .ui-meta { margin-top: 6px; }
    h1 .ui-tag { font-size: 12px; font-weight: 500; }
    a.ui-btn { text-decoration: none; }
    .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
    .big { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text-primary); white-space: nowrap; }
    .chart { padding-top: 8px; padding-bottom: 8px; }
    .ctl { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .ui-stat-sub .ui-link { font-size: 12px; }

    /* overview */
    .spark { height: 36px; margin: 2px -4px -4px; }
    .use-bar { display: flex; align-items: center; gap: 16px; padding: 16px 20px; border-top: 1px solid var(--border); }
    .use-bar .ui-segbar { flex: 1; }
    .ui-segbar.tall { height: 10px; border-radius: 5px; }
    .ub-k { font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; }
    .lt { border-top: 1px solid var(--border); }
    .lt-r { display: grid; grid-template-columns: 10px minmax(0, 1fr) 90px 150px 16px; gap: 0 16px; align-items: center; width: 100%; padding: 12px 20px; border-bottom: 1px solid var(--border); text-align: left; font-size: 13px; color: var(--text-primary); box-sizing: border-box; }
    .lt-r:last-child { border-bottom: none; }
    /* same look as .ui-tbl: quiet labels, every column left-aligned, one rule weight */
    .lt-h { padding-top: 14px; padding-bottom: 10px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); background: none; border-bottom-color: var(--border); }
    .lt-r.link { cursor: pointer; }
    .lt-r.link:hover { background: var(--highlight-3); }
    .lt-r.link:hover b, .lt-r.link:hover .lt-go { color: var(--accent); }
    .sw { width: 10px; height: 10px; border-radius: 3px; }
    .sw.free { background: var(--highlight-15); border: 1px solid var(--border-strong); box-sizing: border-box; }
    .lt-n { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .lt-n b { font-weight: 600; }
    .lt-n small { font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .lt-v { font-weight: 500; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .lt-v small { margin-left: 4px; font-weight: 400; font-size: 12px; color: var(--text-secondary); }
    .lt-go { display: flex; color: var(--text-secondary); }

    @media (max-width: 760px) {
        .lt-r { grid-template-columns: 10px minmax(0, 1fr) 54px 76px 14px; gap: 0 10px; padding: 11px 14px; }
        .lt-v small { display: none; }
        .use-bar { padding: 14px; flex-wrap: wrap; }
        .ub-k { white-space: normal; }
    }
    .lead { margin: 0; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

    /* machine and app tables, as on the OrbStack VM page */
    .nm-cell { display: flex; align-items: center; gap: 8px; }
    .nm { font-weight: 600; color: var(--accent); }
    tr.click:hover .nm { text-decoration: underline; }
    .sub { font-size: 12px; color: var(--text-secondary); }
    td > .sub { margin-top: 2px; }
    .use { display: grid; grid-template-columns: auto 1fr; align-items: center; column-gap: 8px; row-gap: 3px; min-width: 120px; max-width: 170px; }
    .use .num { font-variant-numeric: tabular-nums; font-weight: 500; }
    .use .sub { grid-column: 1 / -1; }
    .mini { height: 4px; border-radius: 2px; background: var(--highlight-15); overflow: hidden; min-width: 40px; }
    .mini i { display: block; height: 100%; border-radius: 2px; transition: width .3s ease; }
    .runs { font-size: 13px; color: var(--text-primary); cursor: pointer; text-align: left; white-space: nowrap; }
    .runs:hover { color: var(--accent); text-decoration: underline; }
    @media (max-width: 1000px) { .cols { grid-template-columns: 1fr; } }
    .rows { border-top: 1px solid var(--border); }
</style>
