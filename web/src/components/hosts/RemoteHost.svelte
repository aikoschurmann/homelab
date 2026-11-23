<script>
    import { SN } from '../../lib/server.js';
    import { openShell } from '../../lib/terminal.js';
    import OrbStackSettings from '../machines/OrbStackSettings.svelte';
    // Another host's page, shaped like Arrakis's and a machine's: icon header, then tabs.
    // Overview (sparkline tiles, what uses it, health, details) · Workloads · OrbStack VM and
    // Storage (when its agent reports them) · Metrics · Settings.
    import { onMount } from 'svelte';
    import { ChevronRight, Trash2, Terminal, Power, Download, Play, Square, RotateCw, LayoutGrid, List, Search, AppWindow, SquareTerminal } from 'lucide-svelte';
    import { visible, gbFromMib } from '../../lib/stores.js';
    import { imageLabel } from '../../lib/machines.js';
    import { tailnet, fetchTailnet } from '../../lib/tailscale.js';
    import { removeHost, installCommand, hostState, hostStateLabel, fmtGb, fmtDisk, hostIcon, canAct, queueAction, fetchActions, actionLabel, hostStorage, hostMachines, INVENTORY_FROM, orbManaged, setOrbManage } from '../../lib/hosts.js';
    import { href } from '../../lib/infra.js';
    import { vmRef } from '../../lib/vmref.js';
    import MachineList from '../machines/MachineList.svelte';
    import HardwareCard from './HardwareCard.svelte';
    import { fmtMb } from '../../lib/services.js';
    import StatusPill from '../ui/StatusPill.svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';
    import Tabs from '../ui/Tabs.svelte';
    import CopyText from '../ui/CopyText.svelte';
    import LiveChart from '../ui/LiveChart.svelte';
    import { bucketed } from '../../lib/spark.js';
    import PairGrid from '../ui/PairGrid.svelte';
    import MachineWorkloads from '../machines/MachineWorkloads.svelte';
    import UptimeStrip from '../ui/UptimeStrip.svelte';
    import Modal from '../ui/Modal.svelte';
    import ResourceCard from '../ui/ResourceCard.svelte';
    import StorageView from './StorageView.svelte';

    export let h;                     // the host, from the hosts store
    export let tab = 'overview';
    export let setTab = () => {};
    export let removed = () => {};

    $: r = h.report || {};
    $: mac = /macos/i.test(r.os || '');
    $: w = r.workloads;
    $: TABS = [
        { id: 'overview', label: 'Overview' },
        (h.caps?.orbstack || managed) && { id: 'vm', label: `OrbStack VM${h.vms?.machines ? ` (${h.vms.machines.length})` : h.caps?.machines != null ? ` (${h.caps.machines})` : ''}` },
        mac ? { id: 'apps', label: macApps ? `Apps (${macApps.length})` : 'Apps' }
            : { id: 'workloads', label: w ? `Workloads (${(w.docker || []).length + w.services.filter(u => !u.base).length})` : 'Workloads' },
        h.caps?.storage != null && { id: 'storage', label: `Storage (${h.caps.storage})` },
        { id: 'metrics', label: 'Metrics' },
        { id: 'settings', label: 'Settings' },
    ].filter(Boolean);
    const toast = (m) => window.showToast?.(m);
    const shortOs = (os) => (os || '').replace(/ GNU\/Linux/, '').replace(/ \(.*\)$/, '').replace(/ LTS$/, '');
    const pct = (a, b) => b ? Math.min(100, Math.max(0, (a / b) * 100)) : 0;
    const plural = (n, x) => `${n} ${x}${n === 1 ? '' : 's'}`;
    const fmtUp = (s) => { if (!s) return '—'; const d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? `${d}d ${hh}h` : hh ? `${hh}h ${m}m` : `${m}m`; };
    const ago = (t) => { const s = Math.max(0, Date.now() / 1000 - t); return s < 90 ? `${Math.round(s)} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`; };

    // ---- history: the last hour at 5 s; longer spans from metrics.db on Arrakis ------------
    const RANGES = [{ id: '1h', label: '1H', hours: 1 }, { id: '24h', label: '24H', hours: 24 }, { id: '7d', label: '7D', hours: 168 }, { id: '30d', label: '30D', hours: 720 }];
    let range = RANGES[0], hist = [];
    $: hours = tab === 'metrics' ? range.hours : 1;
    async function loadHistory() {
        const want = hours;
        try { const j = await fetch(`/api/hosts/${encodeURIComponent(h.id)}/history?hours=${want}`).then(r => r.json()); if (j.status === 'success' && want === hours) hist = j.data; } catch (e) {}
    }
    $: hours, loadHistory();

    // disk, every 5 minutes on Arrakis (the 1H view shows the last day: it barely moves)
    let disk = [];
    async function loadDisk() {
        const want = Math.max(24, range.hours);
        try { const j = await fetch(`/api/hosts/${encodeURIComponent(h.id)}/disk?hours=${want}`).then(r => r.json()); if (j.status === 'success' && want === Math.max(24, range.hours)) disk = j.data; } catch (e) {}
    }
    $: if (tab === 'metrics') range, loadDisk();
    $: diskPts = disk.map(p => [p.ts * 1000, p.used / 1e9]);
    // a line needs a couple of hours of 5-minute samples to read as one
    $: diskReady = diskPts.length > 1 && diskPts.at(-1)[0] - diskPts[0][0] >= 2 * 3600000;
    $: diskMax = r.disk_total ? Math.ceil(r.disk_total / 1e9) : null;

    // ---- health: when the agent reported, and Arrakis's own checks of its open ports ------
    let presence = null, checks = null;
    async function loadHealth() {
        const id = encodeURIComponent(h.id);
        try {
            const [p, c] = await Promise.all([fetch(`/api/hosts/${id}/presence`).then(r => r.json()), fetch(`/api/hosts/${id}/checks`).then(r => r.json())]);
            if (p.status === 'success') presence = p.data;
            if (c.status === 'success') checks = c.data;
        } catch (e) {}
    }
    $: checkRows = (checks?.checks || []).map(c => ({ ...c, up: checks.ports?.[c.port] }));
    const checkName = (c) => c.port === 53 ? 'DNS' : c.port === 22 ? 'SSH' : c.detail.startsWith('HTTP') ? 'Web' : c.detail === 'VNC server' ? 'VNC' : 'Port';
    const ms = (v) => v == null ? '' : v < 10 ? v.toFixed(1) + ' ms' : Math.round(v) + ' ms';
    $: pts = hist.filter(p => p.cpu != null);
    $: win = pts.length > 1 ? Math.min(3600000, Math.max(5 * 60000, (pts.at(-1).t - pts[0].t) * 1000)) : 3600000;
    $: cpuPts = pts.map(p => [p.t * 1000, p.cpu]);
    $: memPts = hist.filter(p => p.mem != null).map(p => [p.t * 1000, p.mem / 2 ** 30]);
    $: memMax = r.mem_total ? Math.ceil(r.mem_total / 2 ** 30) : null;

    // ---- drives and OrbStack machines: the inventory its agent sends every minute ----------
    let drives = null, vms = null;
    async function loadInv() {
        const id = h.id;
        const [d, m] = await Promise.all([hostStorage(id), hostMachines(id)]);
        if (id === h.id) { drives = d; vms = m; }
    }
    $: h.id, reload, loadInv();
    $: inv5 = +(r.agent || 0) >= INVENTORY_FROM;
    // the dashboard manages this host's OrbStack like Arrakis's (its owner switched it on)
    $: managed = orbManaged(h);
    const RPC_FROM = 6;
    let manageBusy = false, confirmManage = false;
    async function toggleManage(on) {
        manageBusy = true; confirmManage = false;
        try { await setOrbManage(h.id, on); toast(on ? `The dashboard now manages OrbStack on ${h.name}` : `Stopped managing OrbStack on ${h.name}`); } catch (e) { toast(e.message); }
        manageBusy = false;
    }
    const goTo = (to) => location.hash = to;
    let view = 'grid';
    try { view = localStorage.getItem('arrakis_host_view') || 'grid'; } catch (e) {}
    function setView(v) { view = v; try { localStorage.setItem('arrakis_host_view', v); } catch (e) {} }
    $: vmList = h.vms?.machines || vms?.machines || [];
    $: vmRunning = vmList.filter(m => m.state === 'running').length;
    const limitCpu = (m) => m.cpu ? `${m.cpu} cores` : 'Shared';
    const limitMem = (m) => m.memory_mib ? gbFromMib(m.memory_mib) : 'Shared';
    $: vmMenu = (m) => !(actOk && inv5) ? [] : m.state === 'running'
        ? [{ label: 'Restart', icon: RotateCw, onClick: () => act('vm-restart', m.name) }, { label: 'Stop…', icon: Square, danger: true, onClick: () => act('vm-stop', m.name) }]
        : [{ label: 'Start', icon: Play, onClick: () => act('vm-start', m.name) }];

    // ---- install / remove -------------------------------------------------------------------
    let cmd = null, confirmRemove = false;
    async function remove() {
        try { await removeHost(h.id); toast(`${h.name} removed`); removed(); } catch (e) { toast(e.message); }
    }
    onMount(() => {
        fetchTailnet(); installCommand(h.id).then(c => cmd = c);
        loadHealth(); loadActs();
        const t = setInterval(() => visible() && (hours === 1 || Date.now() % 60000 < 5000) && loadHistory(), 5000);
        const t2 = setInterval(() => visible() && tab === 'overview' && loadHealth(), 30000);
        const t3 = setInterval(() => visible() && (tab === 'vm' || tab === 'storage') && loadInv(), 15000);
        return () => { clearInterval(t); clearInterval(t2); clearInterval(t3); };
    });

    // ---- what uses it: containers, its own services, the system, free (as on Arrakis) -----
    const list = (xs, n) => xs.length ? xs.slice(0, n).join(', ') + (xs.length > n ? ` +${xs.length - n}` : '') : '';
    const gb = (v) => v.toFixed(1) + ' GB';
    const sum = (xs, f) => xs.reduce((a, x) => a + (+f(x) || 0), 0);
    $: cores = r.cores || 0;
    $: totalGb = (r.mem_total || 0) / 2 ** 30;
    $: usedGb = (r.mem_used || 0) / 2 ** 30;
    $: running = (r.containers || []).filter(c => c.status === 'running');
    $: apps = (w?.services || []).filter(u => !u.base);
    $: measured = apps.some(u => u.mem_mb != null);       // agent 4 measures each service
    $: ctrGb = sum(running, c => c.mem_mb) / 1024;
    $: appGb = sum(apps, u => u.mem_mb) / 1024;
    $: ctrCpu = cores ? sum(running, c => c.cpu) / cores : 0;
    $: appCpu = cores ? sum(apps, u => u.cpu) / cores : 0;
    // a Mac: its apps (agent 7), as on Arrakis's Apps tab. OrbStack itself is the VM, shown
    // apart (its helpers run the machines), as on Arrakis
    $: macApps = r.apps ? r.apps.filter(a => !/orbstack/i.test(a.name)) : null;
    $: orb = (r.apps || []).find(a => /orbstack/i.test(a.name));
    $: macCpu = cores ? sum(macApps || [], a => a.cpu) / cores : 0;
    $: macGb = sum(macApps || [], a => a.mem_mb) / 1024;
    $: vmCpu = orb && cores ? orb.cpu / cores : 0;
    $: vmGb = orb ? orb.mem_mb / 1024 : 0;
    let aq = '';
    $: shownApps = (macApps || []).filter(a => !aq || `${a.name} ${a.ports.join(' ')}`.toLowerCase().includes(aq.toLowerCase()));
    const portsText = (a) => a.ports.length ? a.ports.slice(0, 3).map(p => ':' + p).join(' ') + (a.ports.length > 3 ? ` +${a.ports.length - 3}` : '') : '';
    const appSub = (a) => [a.type === 'app' ? 'app' : 'program', a.processes > 1 ? `${a.processes} processes` : '', portsText(a)].filter(Boolean).join(' · ');
    $: layers = mac && w ? [
        (orb || h.caps?.orbstack) && { id: 'vm', name: 'OrbStack VM', sub: `${vmList.filter(m => m.state === 'running').length} of ${plural(vmList.length, 'machine')} running`, cpu: orb ? vmCpu : null, mem: orb ? vmGb : null, shade: 1, tab: 'vm' },
        { id: 'apps', name: 'Apps on macOS', sub: macApps ? list(macApps.map(a => a.name), 4) || 'none running' : 'update the agent to list them', cpu: macApps ? macCpu : null, mem: macApps ? macGb : null, shade: 0.6, tab: 'apps' },
        { id: 'sys', name: 'macOS and the rest', sub: 'the system and untracked apps', cpu: r.cpu_pct != null ? Math.max(0, r.cpu_pct - macCpu - vmCpu) : null, mem: Math.max(0, usedGb - macGb - vmGb), shade: 0.3 },
        { id: 'free', name: 'Free', sub: 'available memory', cpu: null, mem: Math.max(0, totalGb - usedGb), shade: 0 },
    ] : w ? [
        w.docker != null && { id: 'ctr', name: 'Containers', sub: w.docker.length ? `${running.length} of ${plural(w.docker.length, 'container')} running · ${list(running.map(c => c.name), 3) || 'none running'}` : 'none', cpu: ctrCpu, mem: ctrGb, shade: 1, tab: 'workloads' },
        { id: 'svc', name: 'Services', sub: list(apps.map(u => u.unit), 5) || 'only the standard system ones', cpu: measured ? appCpu : null, mem: measured ? appGb : null, shade: 0.6, tab: 'workloads' },
        { id: 'sys', name: `${(r.os || 'Linux').split(' ')[0]} and the rest`, sub: measured ? 'the system and everything else' : 'the system and services (update the agent to split them out)', cpu: r.cpu_pct != null ? Math.max(0, r.cpu_pct - ctrCpu - (measured ? appCpu : 0)) : null, mem: Math.max(0, usedGb - ctrGb - (measured ? appGb : 0)), shade: 0.3 },
        { id: 'free', name: 'Free', sub: 'available memory', cpu: null, mem: Math.max(0, totalGb - usedGb), shade: 0 },
    ].filter(Boolean) : [];

    // ---- details: the system on the left, how to reach it on the right -------------------
    $: dev = ($tailnet?.devices || []).find(d => d.ip === r.ip);
    $: detailRows = [
        [{ k: 'Model', v: [r.model, r.arch].filter(Boolean).join(', ') || '—' }, { k: 'Tailscale', v: r.ip || '—', copy: !!r.ip }],
        [{ k: 'Cores', v: r.cores ? String(r.cores) : '—' }, { k: 'MagicDNS', v: dev?.dns || dev?.name || '—', copy: !!(dev?.dns || dev?.name) }],
        [{ k: 'Memory', v: fmtGb(r.mem_total) }, { k: 'Shell', v: r.ip ? `ssh ${r.ip}` : '—', copy: !!r.ip }],
        [{ k: 'Disk', v: fmtDisk(r.disk_total) }, { k: 'Agent', v: h.last_seen ? `version ${r.agent || '?'} · reports every 5 s` : 'not reporting yet' }],
        [{ k: 'Operating system', v: r.os || '—' }, { k: 'Hostname', v: r.hostname || '—', mono: true }],
        [{ k: 'Kernel', v: r.kernel || '—', mono: true }, { k: 'Added', v: new Date(h.added * 1000).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' }) }],
    ];

    // ---- actions: queued on Arrakis, the agent runs them within ~5 s ----------------------
    $: actOk = canAct(h) && h.online;
    let acts = [], reload = 0, ask = null, busy = false;
    async function loadActs() { acts = await fetchActions(h.id); }
    const RISKY = { 'service-stop': 'stop', 'container-stop': 'stop', 'vm-stop': 'stop', reboot: 'reboot' };
    function act(verb, target = '') {
        if (RISKY[verb]) ask = { verb, target };
        else send(verb, target);
    }
    async function send(verb, target) {
        ask = null;
        let a;
        try { a = await queueAction(h.id, verb, target); } catch (e) { toast(e.message); return; }
        busy = true; toast(`${actionLabel(a)}: sent to ${h.name}`);
        await loadActs();
        // follow it until the agent answers (or the queue gives up on it)
        for (let i = 0; i < 45; i++) {
            await new Promise(res => setTimeout(res, 2000));
            await loadActs();
            const x = acts.find(y => y.id === a.id);
            if (x && !['queued', 'sent'].includes(x.state)) {
                toast(x.state === 'done' ? `${actionLabel(x)}: done` : `${actionLabel(x)}: ${x.output?.split('\n')[0] || x.state}`);
                reload++;
                break;
            }
        }
        busy = false;
    }
    const stateLabel = { queued: 'Waiting for the agent', sent: 'Running', done: 'Done', failed: 'Failed', expired: 'Not picked up', unknown: 'No answer' };
    const statePill = { queued: 'waiting', sent: 'starting', done: 'running', failed: 'error', expired: 'stopped', unknown: 'stopped' };

    async function wakeUp() {
        const r = await fetch(`/api/hosts/${encodeURIComponent(h.id)}/wake`, { method: 'POST' }).then(r => r.json()).catch(() => null);
        toast(r?.status === 'success' ? `Wake-up sent to ${h.name} (${r.data.mac})` : r?.message || 'Could not send the wake-up');
    }
    $: menuItems = [
        !h.online && h.mac && { label: 'Wake up', icon: Power, onClick: wakeUp },
        actOk && { label: 'Update agent', icon: Download, onClick: () => act('update-agent') },
        actOk && { label: 'Reboot…', icon: Power, danger: true, onClick: () => act('reboot') },
        { label: 'Agent install command', icon: Terminal, onClick: () => setTab('settings') },
        { label: 'Remove host…', icon: Trash2, danger: true, divider: true, onClick: () => { setTab('settings'); confirmRemove = true; } },
    ];
</script>

<div class="ui-page">
    <div class="ui-head">
        <div class="id">
            <span class="icon" class:on={h.online}><svelte:component this={hostIcon(r.model, r.os)} size={22} /></span>
            <div>
                <h1>{h.name} <StatusPill state={hostState(h)} label={hostStateLabel(h)} /></h1>
                <div class="ui-meta">
                    {#if r.os}<span>{[r.model?.replace(/ Rev [\d.]+$/, ''), shortOs(r.os), `${r.cores} cores`, fmtGb(r.mem_total)].filter(Boolean).join(' · ')}</span>{/if}
                    {#if r.ip}<span>Tailscale <b class="ui-mono">{r.ip}</b></span>{/if}
                    {#if h.online && r.uptime_secs}<span>Up {fmtUp(r.uptime_secs)}</span>{/if}
                    {#if h.last_seen && !h.online}<span>Last report {ago(h.last_seen)}</span>{/if}
                    {#if r.agent}<span>Agent {r.agent}{+r.agent < (h.agent_latest || 0) ? `, ${h.agent_latest} available` : ''}</span>{/if}
                </div>
            </div>
        </div>
        <div class="ui-head-actions">
            {#if h.online}<button class="ui-btn" on:click={() => openShell(h.id)} title="A tmux session named shell on this host, over SSH"><SquareTerminal size={14} /> Shell</button>{/if}
            <ActionMenu items={menuItems} label="More actions" />
        </div>
    </div>

    <Tabs tabs={TABS} active={tab} onSelect={setTab} />

    {#if !h.last_seen}
        <div class="ui-banner warn">No report yet. Run the install command on {h.name}: it's under <button class="ui-link" on:click={() => setTab('settings')}>Settings</button>.</div>
    {:else if !h.online}
        <div class="ui-banner warn">{h.name} stopped reporting {ago(h.last_seen)}. It may be asleep, off, or off the tailnet. Figures are from its last report.</div>
    {/if}

    {#if tab === 'overview' && h.report}
        <div class="ui-stats">
            <div class="ui-stat">
                <span class="ui-stat-label">CPU</span>
                <span class="ui-stat-value">{r.cpu_pct != null ? r.cpu_pct.toFixed(1) + '%' : '—'}<small>of {r.cores} cores</small></span>
                <div class="spark">{#if cpuPts.length > 1}<LiveChart points={bucketed(cpuPts)} windowMs={win} height={36} bare />{/if}</div>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Memory</span>
                <span class="ui-stat-value">{fmtGb(r.mem_used)}<small>of {fmtGb(r.mem_total)}</small></span>
                <div class="spark">{#if memPts.length > 1}<LiveChart points={bucketed(memPts)} windowMs={win} height={36} color="var(--metric-mem)" min={0} max={memMax} bare />{/if}</div>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Storage</span>
                <span class="ui-stat-value">{fmtDisk(r.disk_used)}<small>of {fmtDisk(r.disk_total)}</small></span>
                <div class="ui-meter"><i style="width: {pct(r.disk_used, r.disk_total)}%; background: var(--text-secondary)"></i></div>
                <span class="ui-stat-sub">{r.disk_total ? fmtDisk(r.disk_total - r.disk_used) + ' free' : ''}</span>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Uptime</span>
                <span class="ui-stat-value">{fmtUp(r.uptime_secs)}</span>
                <span class="ui-stat-sub">{r.uptime_secs ? 'since ' + new Date(Date.now() - r.uptime_secs * 1000).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''}</span>
            </div>
        </div>

        <!-- one table: what on it uses the CPU and memory -->
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">What uses {h.name}</h2><p class="ui-card-desc">{w ? `As its agent measured it ${ago(w.at)}.` : 'Its agent sends this every 30 seconds.'}</p></div></div>
            {#if w}
                <div class="use-bar">
                    <div class="ui-segbar tall" title="Memory">
                        {#each layers.filter(l => l.mem != null && l.id !== 'free') as l}<i style="width: {pct(l.mem, totalGb)}%; background: var(--metric-mem); opacity: {l.shade}"></i>{/each}
                    </div>
                    <span class="ub-k">{gb(usedGb)} of {totalGb.toFixed(1)} GB memory in use</span>
                </div>
                <div class="lt" role="table">
                    <div class="lt-r lt-h" role="row"><span></span><span>Part</span><span>CPU</span><span>Memory</span><span></span></div>
                    {#each layers as l (l.id)}
                        <svelte:element this={l.tab ? 'button' : 'div'} class="lt-r" class:link={l.tab} role="row" on:click={() => l.tab && setTab(l.tab)}>
                            <span class="sw" class:free={l.id === 'free'} style={l.id === 'free' ? '' : `background: var(--metric-mem); opacity: ${l.shade}`}></span>
                            <span class="lt-n"><b>{l.name}</b><small>{l.sub}</small></span>
                            <span class="lt-v">{l.cpu != null ? l.cpu.toFixed(1) + '%' : l.id === 'free' ? '' : '—'}</span>
                            <span class="lt-v">{l.mem != null ? gb(l.mem) : '—'}</span>
                            <span class="lt-go">{#if l.tab}<ChevronRight size={15} />{/if}</span>
                        </svelte:element>
                    {/each}
                </div>
            {/if}
        </section>

        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Health</h2><p class="ui-card-desc">Its reports, and its open ports checked from {SN} every {checks?.every || 30} s. Last 24 hours.</p></div></div>
            <div class="hl">
                <div class="hl-r">
                    <span class="dot" class:bad={!h.online}></span>
                    <span class="hl-n"><b>Agent reports</b><small>{h.online ? 'every 5 s' : `none since ${ago(h.last_seen)}`}</small></span>
                    <span class="hl-s">{#if presence?.slots?.length}<UptimeStrip slots={presence.slots} bucketSeconds={presence.bucket_seconds} />{/if}</span>
                    <span class="hl-p">{presence?.pct != null ? presence.pct + '%' : '—'}</span>
                </div>
                {#each checkRows as c (c.port)}
                    <div class="hl-r">
                        <span class="dot" class:bad={!c.ok}></span>
                        <span class="hl-n"><b>{checkName(c)} <span class="ui-mono ui-dim">:{c.port}</span></b><small class:err={!c.ok}>{c.process} · {c.detail}{c.ok && c.ms != null ? ' · ' + ms(c.ms) : ''}</small></span>
                        <span class="hl-s">{#if c.up}<UptimeStrip slots={c.up.slots} bucketSeconds={checks.bucket_seconds} />{/if}</span>
                        <span class="hl-p">{c.up?.pct != null ? c.up.pct + '%' : '—'}</span>
                    </div>
                {:else}
                    <div class="ui-empty">{!checks || (h.online && !w) || (h.online && checks.checks.length === 0 && w?.listening?.length) ? 'Checking its ports…' : 'No open ports to check.'}</div>
                {/each}
            </div>
        </section>

        <HardwareCard hid={h.id} name={h.name} agentOld={+(r.agent || 0) < 14} />

        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Details</h2><p class="ui-card-desc">The hardware, and how to reach it.</p></div></div>
            <PairGrid rows={detailRows} heads={['Hardware', 'Network']} />
        </section>

    {:else if tab === 'apps'}
        {#if macApps}
            <div class="ui-listbar">
                <label class="ui-search"><Search size={14} /><input placeholder="Search apps" bind:value={aq} /></label>
                <span class="ui-count" title="Apps and programs running on {h.name}, outside OrbStack. macOS's own processes are left out.">{plural(shownApps.length, 'app')}{w ? ` · seen ${ago(w.at)}` : ''}</span>
                <div class="ui-seg view" role="group" aria-label="View">
                    <button class:on={view === 'grid'} on:click={() => setView('grid')} title="Cards" aria-label="Cards"><LayoutGrid size={14} /></button>
                    <button class:on={view === 'table'} on:click={() => setView('table')} title="Table" aria-label="Table"><List size={14} /></button>
                </div>
            </div>
            {#if view === 'grid'}
                <div class="ui-cardgrid">
                    {#each shownApps as a (a.id)}
                        <ResourceCard plain name={a.name} sub={appSub(a)} icon={AppWindow} on
                            meters={[
                                { k: 'CPU', p: cores ? a.cpu / cores : 0, color: 'var(--metric-cpu)', v: cores ? (a.cpu / cores).toFixed(1) + '%' : '—', of: `of ${cores} cores` },
                                { k: 'Memory', p: pct(a.mem_mb / 1024, totalGb), color: 'var(--metric-mem)', v: fmtMb(a.mem_mb), of: `of ${totalGb.toFixed(0)} GB` },
                                { k: 'Up', v: fmtUp(a.uptime_seconds), of: 'since start' },
                            ]}
                            foot={false}>
                            <svelte:fragment slot="status"><StatusPill state="running" /></svelte:fragment>
                        </ResourceCard>
                    {:else}<div class="ui-card ui-empty">No apps match.</div>{/each}
                </div>
            {:else}
                <section class="ui-card"><div class="ui-tbl-wrap"><table class="ui-tbl">
                    <thead><tr><th>Name</th><th class="c-sm">CPU</th><th class="c-sm">Memory</th><th class="c-md">Ports</th><th class="c-md">Up</th></tr></thead>
                    <tbody>
                        {#each shownApps as a (a.id)}
                            <tr>
                                <td><div class="nm-cell"><b>{a.name}</b></div><div class="ui-dim sub">{a.type === 'app' ? 'app' : 'program'}{a.processes > 1 ? ` · ${a.processes} processes` : ''}</div></td>
                                <td class="c-sm">{cores ? (a.cpu / cores).toFixed(1) + '%' : '—'}</td>
                                <td class="c-sm">{fmtMb(a.mem_mb)}</td>
                                <td class="c-md ui-mono">{a.ports.length ? a.ports.join(', ') : '—'}</td>
                                <td class="c-md">{fmtUp(a.uptime_seconds)}</td>
                            </tr>
                        {:else}<tr><td colspan="5" class="ui-dim">No apps match.</td></tr>{/each}
                    </tbody>
                </table></div></section>
            {/if}
        {:else}
            <div class="ui-card ui-empty">{h.online ? `Waiting for ${h.name}'s app list (every 30 seconds). If this stays empty, use Update agent in the ⋯ menu.` : 'Shown while the host reports.'}</div>
        {/if}

    {:else if tab === 'workloads'}
        {#if w}
            {#if h.online && !canAct(h)}<p class="ui-hint" style="margin: 0">To restart or stop things from here, update {h.name}'s agent: run the install command from <button class="ui-link" on:click={() => setTab('settings')}>Settings</button> again.</p>{/if}
            <MachineWorkloads name={h.name} url="/api/hosts/{encodeURIComponent(h.id)}/workloads" running={h.online} act={actOk ? act : null} {reload} />
            {#if acts.length}
                <section class="ui-card">
                    <div class="ui-card-head"><div><h2 class="ui-card-title">Recent actions</h2><p class="ui-card-desc">Since the dashboard last started. {h.name}'s agent runs them on its next report.</p></div></div>
                    <div class="ui-tbl-wrap">
                        <table class="ui-tbl">
                            <thead><tr><th>Action</th><th>State</th><th class="c-md">Output</th><th>When</th></tr></thead>
                            <tbody>
                                {#each acts as a (a.id)}
                                    <tr>
                                        <td><b>{actionLabel(a)}</b></td>
                                        <td><StatusPill state={statePill[a.state]} label={stateLabel[a.state]} /></td>
                                        <td class="ui-mono ui-dim c-md out" title={a.output}>{a.output || '—'}</td>
                                        <td class="ui-dim">{ago(a.at)}</td>
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                    </div>
                </section>
            {/if}
        {:else}
            <div class="ui-card ui-empty">{h.online ? 'Waiting for the first workloads report (every 30 seconds). If this stays empty, update the agent from Settings.' : 'Shown while the host reports.'}</div>
        {/if}

    {:else if tab === 'vm' && managed}
        {#if h.vms?.error}
            <div class="ui-banner warn">{h.vms.error}</div>
        {:else if h.vms}
            <MachineList data={h.vms} embedded onHost={h.id} open={(n, t = null) => goTo(href.machine(vmRef(h.id, n), t))} create={() => goTo(href.newMachineOn(h.id))} />
        {:else}<div class="ui-dim">Reading machines…</div>{/if}

    {:else if tab === 'vm'}
        {#if h.orb_manage && !h.rpc}<div class="ui-banner warn">Managing OrbStack is switched on, but {h.name} isn't connected{+(r.agent || 0) < RPC_FROM ? ': its agent needs updating (⋯ → Update agent)' : ' right now'}. Showing what it last reported.</div>
        {:else if !h.orb_manage}<p class="ui-hint" style="margin: 0">To create, share and fully manage machines here, switch on managing OrbStack in <button class="ui-link" on:click={() => setTab('settings')}>Settings</button>.</p>{/if}
        {#if vms?.orbstack === 'stopped'}
            <div class="ui-card ui-empty">OrbStack is installed on {h.name} but isn't running. Open it there and its machines show up here within a minute.</div>
        {:else if vms}
            <div class="ui-listbar">
                <span class="ui-count" title="{h.name}'s agent reports every minute and right after you start or stop one.">{vmRunning} of {plural(vmList.length, 'machine')} running{vms.pool ? ` · VM pool ${vms.pool.cpu} cores, ${gbFromMib(vms.pool.memory_mib)}` : ''}{vms.at ? ` · seen ${ago(vms.at)}` : ''}</span>
                <div class="ui-seg view" role="group" aria-label="View">
                    <button class:on={view === 'grid'} on:click={() => setView('grid')} title="Cards" aria-label="Cards"><LayoutGrid size={14} /></button>
                    <button class:on={view === 'table'} on:click={() => setView('table')} title="Table" aria-label="Table"><List size={14} /></button>
                </div>
            </div>
            {#if h.online && !inv5}<p class="ui-hint" style="margin: 0">To start or stop machines from here, use Update agent in the ⋯ menu.</p>{/if}
            {#if view === 'grid'}
                <div class="ui-cardgrid">
                    {#each vmList as m (m.name)}
                        {@const on = m.state === 'running'}
                        <ResourceCard plain name={m.name} sub="{imageLabel(m.image)} · {m.image?.arch || ''}" {on} off={!on}
                            meters={[
                                { k: 'CPU', v: limitCpu(m), of: m.cpu ? 'limit' : `pool of ${vms.pool?.cpu}` },
                                { k: 'Memory', v: limitMem(m), of: m.memory_mib ? 'limit' : `pool of ${gbFromMib(vms.pool?.memory_mib || 0)}` },
                                { k: 'User', v: m.username || '—', of: '' },
                            ]}
                            foot={false}>
                            <svelte:fragment slot="status">
                                <StatusPill state={m.state} />
                                {#if vmMenu(m).length}<ActionMenu items={vmMenu(m)} label="Actions for {m.name}" />{/if}
                            </svelte:fragment>
                        </ResourceCard>
                    {:else}<div class="ui-card ui-empty">No machines in OrbStack on {h.name}.</div>{/each}
                </div>
            {:else}
                <section class="ui-card"><div class="ui-tbl-wrap"><table class="ui-tbl">
                    <thead><tr><th>Name</th><th>Status</th><th class="c-sm">CPU</th><th class="c-sm">Memory</th><th class="c-md">User</th><th class="shrink"></th></tr></thead>
                    <tbody>
                        {#each vmList as m (m.name)}
                            <tr>
                                <td><div class="nm-cell"><b>{m.name}</b></div><div class="ui-dim sub">{imageLabel(m.image)} · {m.image?.arch || ''}</div></td>
                                <td><StatusPill state={m.state} /></td>
                                <td class="c-sm">{limitCpu(m)}</td>
                                <td class="c-sm">{limitMem(m)}</td>
                                <td class="c-md ui-mono">{m.username || '—'}</td>
                                <td>{#if vmMenu(m).length}<ActionMenu items={vmMenu(m)} label="Actions for {m.name}" />{/if}</td>
                            </tr>
                        {:else}<tr><td colspan="6" class="ui-dim">No machines in OrbStack on {h.name}.</td></tr>{/each}
                    </tbody>
                </table></div></section>
            {/if}
        {:else}<div class="ui-dim">Reading machines…</div>{/if}

    {:else if tab === 'storage'}
        {#if drives}
            <StorageView disks={drives} host={h.name}
                onEject={actOk && inv5 && mac ? (d) => act('disk-eject', d.id) : null}
                onMount={actOk && inv5 && mac ? (v) => act('volume-mount', v.id) : null}
                hint="{h.name}'s agent reports its drives every minute{mac ? '. Eject a drive here before unplugging it' : ''}." />
        {:else}<div class="ui-card ui-empty">{h.online ? 'Waiting for the first drive report (every minute).' : 'Shown while the host reports.'}</div>{/if}

    {:else if tab === 'metrics'}
        <div class="ctl">
            <p class="ui-hint" style="margin: 0">{range.hours === 1 ? 'Every 5 seconds' : range.hours === 24 ? '5-minute averages' : range.hours === 168 ? 'Hourly averages' : '3-hour averages'} · {h.name} as a whole, as its agent reports it.</p>
            <div class="ui-seg">{#each RANGES as x}<button class:on={range === x} on:click={() => range = x}>{x.label}</button>{/each}</div>
        </div>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">CPU</h2><p class="ui-card-desc">Percent of all {r.cores} cores</p></div><span class="big">{r.cpu_pct != null ? r.cpu_pct.toFixed(1) + '%' : '—'}</span></div>
            <div class="ui-card-body chart">{#if cpuPts.length > 1}<LiveChart points={cpuPts} windowMs={range.hours * 3600000} color="var(--metric-cpu)" min={0} max={100} interval={25} format={(v) => v + '%'} height={200} />{:else}<div class="ui-empty">Collecting samples…</div>{/if}</div>
        </section>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Memory</h2><p class="ui-card-desc">Used, of {fmtGb(r.mem_total)}</p></div><span class="big">{fmtGb(r.mem_used)}</span></div>
            <div class="ui-card-body chart">{#if memPts.length > 1}<LiveChart points={memPts} windowMs={range.hours * 3600000} color="var(--metric-mem)" min={0} max={memMax} interval={memMax ? memMax / 4 : null} format={(v) => +v.toFixed(1) + ' GB'} height={200} />{:else}<div class="ui-empty">Collecting samples…</div>{/if}</div>
        </section>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Disk</h2><p class="ui-card-desc">Used, of {fmtDisk(r.disk_total)} · sampled every 5 minutes{range.hours === 1 ? ', last 24 hours' : ''}</p></div><span class="big">{fmtDisk(r.disk_used)}</span></div>
            <div class="ui-card-body chart">{#if diskReady}<LiveChart points={diskPts} windowMs={Math.max(24, range.hours) * 3600000} color="var(--text-secondary)" min={0} max={diskMax} interval={diskMax ? diskMax / 4 : null} format={(v) => Math.round(v) + ' GB'} height={160} />{:else}<div class="ui-empty">Collecting samples (one every 5 minutes)…</div>{/if}</div>
        </section>

    {:else if tab === 'settings'}
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Agent</h2><p class="ui-card-desc">What {h.name} runs to report in and to carry out what you ask from here.</p></div></div>
            <div class="rows">
                <div class="ui-form-row">
                    <div><div class="ui-label">Version</div><div class="ui-hint">{!r.agent ? 'Not reporting yet' : +r.agent < (h.agent_latest || 0) ? `Version ${h.agent_latest} is available` : 'Up to date'}</div></div>
                    <div class="agent-v">
                        <span class="ui-mono">{r.agent || '—'}</span>
                        {#if r.agent && +r.agent < (h.agent_latest || 0)}
                            {#if actOk}<button class="ui-btn sm" disabled={busy} on:click={() => act('update-agent')}>Update to {h.agent_latest}</button>
                            {:else}<span class="ui-dim">run the install command below</span>{/if}
                        {/if}
                    </div>
                </div>
                <div class="ui-form-row">
                    <div><div class="ui-label">Runs as</div><div class="ui-hint">Root can reboot the computer and read every folder for backups</div></div>
                    <span>{r.root == null ? '—' : +r.root ? 'root' : 'your user'}</span>
                </div>
                {#if r.fda != null}
                    <div class="ui-form-row">
                        <div><div class="ui-label">Full Disk Access</div><div class="ui-hint">{r.fda ? 'Can read every folder you pick for backups' : 'System Settings → Privacy & Security → Full Disk Access → Arrakis Agent'}</div></div>
                        <span class:bad={!r.fda}>{r.fda ? 'Allowed' : 'Not allowed'}</span>
                    </div>
                {/if}
                <div class="ui-form-row">
                    <div><div class="ui-label">Reports</div><div class="ui-hint">Usage every 5 s, apps and services every 30 s, drives every minute</div></div>
                    <span>{h.online ? 'Now' : h.last_seen ? `Last ${ago(h.last_seen)}` : 'Not yet'}</span>
                </div>
                <div class="ui-form-row">
                    <div><div class="ui-label">Install or update</div><div class="ui-hint">On {h.name}, in a terminal</div></div>
                    {#if cmd}<div class="cmd"><Terminal size={14} /><CopyText text={cmd.command} /></div>{:else}<span class="ui-dim">…</span>{/if}
                </div>
                <div class="ui-form-row">
                    <div><div class="ui-label">Uninstall</div><div class="ui-hint">Stops the agent and deletes it</div></div>
                    {#if cmd}<div class="cmd"><Terminal size={14} /><CopyText text={cmd.uninstall} /></div>{/if}
                </div>
            </div>
        </section>
        {#if h.orb_manage && h.vms}
            <OrbStackSettings data={h.vms} onHost={h.id} hostName={h.name}>
                <svelte:fragment slot="manage"><div class="ui-form-row">
                    <div><div class="ui-label">Managed by the dashboard</div>
                        <div class="ui-hint">{#if h.orb_manage}{h.rpc ? `On · connected to ${h.name}` : +(r.agent || 0) < RPC_FROM ? `On · waiting for agent ${RPC_FROM} (⋯ → Update agent)` : `On · ${h.name} isn't connected right now`}{:else}Off · only shows what the agent reports{/if}</div></div>
                    {#if h.orb_manage}
                        <button class="ui-btn sm" disabled={manageBusy} on:click={() => toggleManage(false)}>Turn off</button>
                    {:else if confirmManage}
                        <div class="ui-btns"><button class="ui-btn sm" on:click={() => confirmManage = false}>Cancel</button><button class="ui-btn sm primary" disabled={manageBusy} on:click={() => toggleManage(true)}>Turn on</button></div>
                    {:else}
                        <button class="ui-btn sm" on:click={() => confirmManage = true}>Turn on…</button>
                    {/if}
                </div>
                {#if confirmManage}<p class="ui-hint warn-note">This lets the dashboard run any <span class="ui-mono">orb</span> command on {h.name}, including commands inside its machines. OrbStack machines can reach the Mac they run on, so whoever can use this dashboard can, in effect, act on {h.name} as you. The agent runs nothing but <span class="ui-mono">orb</span>.</p>{/if}</svelte:fragment>
            </OrbStackSettings>
        {:else if h.caps?.orbstack || h.orb_manage}
            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">OrbStack</h2><p class="ui-card-desc">Let the dashboard manage {h.name}'s OrbStack like {SN}'s: create, limit and share machines, and change its pool and switches.</p></div></div>
                <div class="rows"><div class="ui-form-row">
                    <div><div class="ui-label">Managed by the dashboard</div>
                        <div class="ui-hint">{#if h.orb_manage}{h.rpc ? `On · connected to ${h.name}` : +(r.agent || 0) < RPC_FROM ? `On · waiting for agent ${RPC_FROM} (⋯ → Update agent)` : `On · ${h.name} isn't connected right now`}{:else}Off · only shows what the agent reports{/if}</div></div>
                    {#if h.orb_manage}
                        <button class="ui-btn sm" disabled={manageBusy} on:click={() => toggleManage(false)}>Turn off</button>
                    {:else if confirmManage}
                        <div class="ui-btns"><button class="ui-btn sm" on:click={() => confirmManage = false}>Cancel</button><button class="ui-btn sm primary" disabled={manageBusy} on:click={() => toggleManage(true)}>Turn on</button></div>
                    {:else}
                        <button class="ui-btn sm" on:click={() => confirmManage = true}>Turn on…</button>
                    {/if}
                </div>
                {#if confirmManage}<p class="ui-hint warn-note">This lets the dashboard run any <span class="ui-mono">orb</span> command on {h.name}, including commands inside its machines. OrbStack machines can reach the Mac they run on, so whoever can use this dashboard can, in effect, act on {h.name} as you. The agent runs nothing but <span class="ui-mono">orb</span>.</p>{/if}</div>
            </section>
        {/if}
        <section class="ui-card danger">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Remove host</h2><p class="ui-card-desc">Takes {h.name} off the dashboard and revokes its token, so its agent's reports are refused. Uninstall the agent on the host as well.</p></div></div>
            <div class="ui-card-foot">
                {#if confirmRemove}
                    <div class="ui-btns"><button class="ui-btn" on:click={() => confirmRemove = false}>Cancel</button><button class="ui-btn danger" on:click={remove}><Trash2 size={14} /> Remove {h.name}</button></div>
                {:else}
                    <button class="ui-btn danger-outline" on:click={() => confirmRemove = true}><Trash2 size={14} /> Remove host…</button>
                {/if}
            </div>
        </section>
    {/if}
</div>

<Modal open={!!ask} onClose={() => ask = null} width={420}
    title={ask?.verb === 'reboot' ? `Reboot ${h.name}?` : `Stop ${ask?.target}?`}
    description={ask?.verb === 'reboot' ? `It drops off the dashboard until it's back up, usually in a minute or two.` : `It stays stopped until you start it again${ask?.verb === 'service-stop' ? ' or the host reboots' : ''}.`}>
    <svelte:fragment slot="footer">
        <div class="ui-btns">
            <button class="ui-btn" on:click={() => ask = null}>Cancel</button>
            <button class="ui-btn danger" disabled={busy} on:click={() => send(ask.verb, ask.target)}>{#if ask?.verb === 'reboot'}<Power size={14} /> Reboot{:else}Stop{/if}</button>
        </div>
    </svelte:fragment>
</Modal>

<style>
    /* header, as on a machine's page */
    .id { display: flex; align-items: center; gap: 16px; min-width: 0; }
    .ui-head { padding: 4px 0 2px; }
    .ui-head h1 { line-height: 1.2; }
    .icon { width: 52px; height: 52px; border-radius: 12px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); border: 1px solid var(--border); }
    .icon.on { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
    .id .ui-meta { margin-top: 6px; }
    .agent-v { display: flex; align-items: center; gap: 12px; }
    .spark { height: 36px; margin: 2px -4px -4px; }
    .ctl { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .big { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text-primary); white-space: nowrap; }
    .chart { padding-top: 8px; padding-bottom: 8px; }
    /* what uses it: the same table as Arrakis's */
    .use-bar { display: flex; align-items: center; gap: 16px; padding: 16px 20px; border-top: 1px solid var(--border); }
    .use-bar .ui-segbar { flex: 1; }
    .ui-segbar.tall { height: 10px; border-radius: 5px; }
    .ub-k { font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; }
    .lt { border-top: 1px solid var(--border); }
    .lt-r { display: grid; grid-template-columns: 10px minmax(0, 1fr) 90px 150px 16px; gap: 0 16px; align-items: center; width: 100%; padding: 12px 20px; border-bottom: 1px solid var(--border); text-align: left; font-size: 13px; color: var(--text-primary); box-sizing: border-box; }
    .lt-r:last-child { border-bottom: none; }
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
    .lt-go { display: flex; color: var(--text-secondary); }
    .cmd { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; border-radius: var(--radius-card, 8px); background: var(--highlight-5); border: 1px solid var(--border); color: var(--text-secondary); min-width: 0; max-width: 100%; box-sizing: border-box; }
    .cmd :global(svg) { flex-shrink: 0; margin-top: 4px; }
    .cmd :global(.copy) { align-items: flex-start; }
    .cmd :global(code) { color: var(--text-primary); line-height: 1.6; }
    .lbl { font-size: 13.5px; font-weight: 500; }
    .ui-form-row .ui-hint { margin: 2px 0 0; }
    /* health rows: name, then a 24 h strip and its pass rate */
    .hl { border-top: 1px solid var(--border); }
    .hl-r { display: grid; grid-template-columns: 8px minmax(0, 1.1fr) minmax(80px, 1fr) 56px; gap: 0 14px; align-items: center; padding: 11px 20px; border-bottom: 1px solid var(--border); font-size: 13px; }
    .hl-r:last-child { border-bottom: none; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); }
    .dot.bad { background: var(--red); }
    .hl-n { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .hl-n b { font-weight: 600; }
    .hl-n small { font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .hl-n small.err { color: var(--red); }
    .hl-p { text-align: right; font-variant-numeric: tabular-nums; color: var(--text-secondary); font-size: 12px; }
    .sub { font-size: 12px; margin-top: 2px; }
    .warn-note { margin: 0; padding: 0 20px 16px; color: var(--text-secondary); }
    .out { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    /* phone: cards inset 14px, so this lines up with the card's header */
    @media (max-width: 768px) {
        .lt-r { grid-template-columns: 10px minmax(0, 1fr) 54px 76px 14px; gap: 0 10px; padding: 11px 14px; }
        .use-bar { padding: 14px; flex-wrap: wrap; }
        .ub-k { white-space: normal; }
        .hl-r { padding-left: 14px; padding-right: 14px; }
        .hl-r { grid-template-columns: 8px minmax(0, 1fr) 48px; }
        .hl-s { grid-column: 2 / 4; grid-row: 2; margin-top: 6px; }
    }
    .rows { border-top: 1px solid var(--border); }
</style>
