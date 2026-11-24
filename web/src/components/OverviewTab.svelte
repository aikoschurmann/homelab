<script>
    import { SN } from '../lib/server.js';
    import { infoPop } from '../lib/infoPop.js';
    import { onMount } from 'svelte';
    import { Database, Terminal, ArrowRight, Archive, SlidersHorizontal, Check, Info, PackageCheck, Store, ScrollText, Network, Cloud, ShieldCheck, Eye } from 'lucide-svelte';
    import { layout, hiddenWidgets, fetchLayout, measureSection } from '../lib/widgets.js';
    import CustomizeMenu from './overview/CustomizeMenu.svelte';
    // #overview/customize shows the layout editor in place of the page
    let customizing = typeof location !== 'undefined' && location.hash === '#overview/customize';
    onMount(() => { const f = () => customizing = location.hash === '#overview/customize'; window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f); });
    import { endpoints, fetchEndpoints, machines, fetchMachines, machineUsage, fetchMachineUsage, gbFromMib, visible } from '../lib/stores.js';
    import { services, fetchServices, fmtMb } from '../lib/services.js';
    import { fmtBytes, imageLabel } from '../lib/machines.js';
    import InfraIndex from './hosts/InfraIndex.svelte';
    import WebAppsCard from './WebAppsCard.svelte';
    import { fetchDisks } from '../lib/storage.js';
    import { updates } from '../lib/updates.js';
    import { hosts, fetchHosts } from '../lib/hosts.js';
    import { fetchTailnet } from '../lib/tailscale.js';
    import TailscaleCard from './overview/TailscaleCard.svelte';
    import ComputeCard from './overview/ComputeCard.svelte';
    import UptimeCard from './overview/UptimeCard.svelte';
    import PiholeCard from './overview/PiholeCard.svelte';
    import MachinesCard from './overview/MachinesCard.svelte';
    import { tailnet } from '../lib/tailscale.js';
    import { cloudflare, isActive } from '../lib/cloudflare.js';
    import LiveChart from './ui/LiveChart.svelte';
    import AttentionRow from './overview/AttentionRow.svelte';

    export let stats;
    export let tmux;

    // reactive, so ticking a card in Customize redraws the page
    $: show = (id) => !$hiddenWidgets.has(id);

    // ---- host -------------------------------------------------------------------------
    $: hd = stats?.host?.details || {};
    const ratio = (s) => { const m = (s || '').match(/([0-9.]+)\s*[A-Za-z]*\s*\/\s*([0-9.]+)/); return m ? { used: +m[1], total: +m[2] } : null; };
    $: mem = ratio(hd['Memory']);
    $: disk = ratio(hd['Disk Space']);
    $: cpuNow = parseFloat(hd['CPU Usage']);
    $: upSince = (hd['Uptime'] || '').startsWith('T:') ? parseInt(hd['Uptime'].slice(2)) * 1000 : null;
    // same numbers as the Updates page: every computer, not just this server's Homebrew
    $: updTargets = ($updates?.targets || []).filter(t => t.packages?.length);
    $: pendingUpdates = updTargets.reduce((a, t) => a + t.packages.length, 0);
    $: pool = $machines?.pool;
    $: poolPct = pool && mem ? Math.min(100, (pool.memory_mib / 1024) / mem.total * 100) : 0;
    $: machineList = $machines?.machines || [];
    const pct = (a, b) => b ? Math.min(100, (a / b) * 100) : 0;

    let now = Date.now();
    function fmtSince(ms) {
        if (!ms) return '—';
        const s = Math.floor((now - ms) / 1000), d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
        return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
    }

    // ---- usage chart --------------------------------------------------------------------
    const RANGES = [
        { label: '5M', hours: 5 / 60, refresh: 5 },
        { label: '1H', hours: 1, refresh: 30 },
        { label: '24H', hours: 24, refresh: 60 },
        { label: '7D', hours: 168, refresh: 300 },
        { label: '30D', hours: 720, refresh: 300 },
    ];
    let range = RANGES[0];
    let metric = 'cpu';
    let hist = [];
    let histAt = 0, histSeq = 0;
    // which host the chart shows: Arrakis (its own long history) or one reporting through the agent (last hour)
    let chartHost = 'arrakis';
    $: remoteHost = chartHost === 'arrakis' ? null : ($hosts || []).find(h => h.id === chartHost);
    $: ranges = remoteHost ? RANGES.slice(0, 2) : RANGES;
    $: metrics = remoteHost ? METRICS.filter(m => m.id !== 'net') : METRICS;
    async function fetchHistory() {
        const seq = ++histSeq, r = range, host = chartHost;
        try {
            if (host === 'arrakis') {
                const j = await fetch(`/api/history?hours=${r.hours}`).then(r => r.json());
                if (seq === histSeq && j.status === 'success') { hist = j.data.host || []; histAt = Date.now(); }
            } else {
                const j = await fetch(`/api/hosts/${encodeURIComponent(host)}/history`).then(r => r.json());
                const since = Date.now() / 1000 - r.hours * 3600;
                if (seq === histSeq && j.status === 'success') {
                    hist = j.data.filter(p => p.t >= since).map(p => ({ ts: p.t, cpu: p.cpu, mem: p.mem != null ? p.mem / 2 ** 30 : null }));
                    histAt = Date.now();
                }
            }
        } catch (e) {}
    }
    function setHost(id) {
        chartHost = id;
        if (id !== 'arrakis') { if (range.hours > 1) range = RANGES[1]; if (metric === 'net') metric = 'cpu'; }
        hist = []; fetchHistory();
    }
    function setRange(r) { range = r; fetchHistory(); }

    const METRICS = [
        { id: 'cpu', label: 'CPU', color: 'var(--metric-cpu)' },
        { id: 'mem', label: 'Memory', color: 'var(--metric-mem)' },
        { id: 'net', label: 'Network', color: 'var(--metric-net)' },
    ];
    const fmt = (k, v) => v == null || !isFinite(v) ? '—' : k === 'cpu' ? v.toFixed(1) + '%' : k === 'mem' ? v.toFixed(2) + ' GB' : (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2)) + ' Mbps';
    // Axis per metric, with evenly spaced ticks. CPU tops out at 25, 50 or 100%; memory
    // frames where it actually sits in whole GB; network rounds up to 1, 2 or 5 × 10ⁿ Mbps.
    function axisFor(k, pts, memTotal) {
        const vals = pts.map(p => p[1]).filter(v => v != null);
        const hi = vals.length ? Math.max(...vals) : 0, lo = vals.length ? Math.min(...vals) : 0;
        if (k === 'cpu') {
            const max = [25, 50, 100].find(t => t >= hi * 1.1) ?? 100;
            return { min: 0, max, interval: max / (max === 100 ? 4 : 5) };
        }
        if (k === 'mem') {
            let max = Math.min(Math.ceil(hi + 0.5), memTotal ? Math.ceil(memTotal) : Infinity);
            let min = Math.max(0, Math.floor(lo - 0.5));
            const step = max - min > 6 ? 2 : 1;
            min = Math.floor(min / step) * step;
            max = min + Math.ceil((max - min) / step) * step;
            return { min, max, interval: step };
        }
        const need = Math.max(hi * 1.15, 1), p = 10 ** Math.floor(Math.log10(need));
        const lead = [1, 2, 5, 10].find(m => m * p >= need);
        const max = lead * p;
        return { min: 0, max, interval: max / (lead === 5 ? 5 : 4) };
    }
    const trim = (v) => +(+v).toFixed(2);
    // units in the labels on wide screens; on a phone they sit once above the chart
    $: axisFmt = (k) => (v) => phone ? String(trim(v)) : k === 'cpu' ? `${trim(v)}%` : k === 'mem' ? `${trim(v)} GB` : `${trim(v)} Mbps`;
    const UNIT = { cpu: '%', mem: 'GB', net: 'Mbps' };
    let phone = false;
    onMount(() => {
        const mq = window.matchMedia('(max-width: 640px)');
        phone = mq.matches;
        const on = (e) => phone = e.matches;
        mq.addEventListener('change', on);
        return () => mq.removeEventListener('change', on);
    });
    $: live = remoteHost ? {
        cpu: remoteHost.report?.cpu_pct, mem: remoteHost.report ? remoteHost.report.mem_used / 2 ** 30 : null, net: null,
    } : {
        cpu: stats?.history?.cpu?.at(-1) ?? hist.at(-1)?.cpu,
        mem: mem?.used ?? hist.at(-1)?.mem,
        net: stats?.history?.net?.at(-1) ?? hist.at(-1)?.net,
    };
    function sum(k) {
        const v = hist.map(p => p[k]).filter(x => x != null);
        return v.length ? { avg: v.reduce((a, b) => a + b, 0) / v.length, peak: Math.max(...v) } : null;
    }
    $: sums = hist && { cpu: sum('cpu'), mem: sum('mem'), net: sum('net') };
    $: chartPts = hist.map(p => [p.ts * 1000, p[metric]]);
    $: memTotalGb = remoteHost ? (remoteHost.report?.mem_total || 0) / 2 ** 30 : mem?.total;
    $: axis = axisFor(metric, chartPts, memTotalGb);
    $: cur = METRICS.find(m => m.id === metric);

    // ---- services -----------------------------------------------------------------------
    $: svcList = $services || [];
    // cluster figures for the page's subtitle
    $: onlineHosts = 1 + ($hosts || []).filter(h => h.online).length;
    $: runningContainers = machineList.reduce((a, m) => a + ($machineUsage[m.name]?.runs?.containers_running || 0), 0)
        + ($hosts || []).reduce((a, h) => a + (h.online ? (h.report?.containers || []).filter(c => c.status === 'running').length : 0), 0);
    const hostName = (h) => h === 'Mac' ? SN : h;
    // OrbStack's VM process holds the machines' memory: it is shown as the machines,
    // so it would be counted twice as a service
    const isVmEngine = (s) => /orbstack/i.test(s.name || '');
    $: vmEngine = svcList.find(s => isVmEngine(s) && s.status === 'running');
    $: vmGb = vmEngine ? (vmEngine.mem_mb || 0) / 1024 : 0;
    $: ownGb = mem ? Math.max(0, mem.used - vmGb) : 0;
    $: cores = +hd['CPU Cores'] || pool?.cpu || 0;
    // ps reports per-core percent; the Mac's figure is of all cores, so the VM's is put on the same scale
    $: vmCpu = vmEngine && cores ? (+vmEngine.cpu || 0) / cores : 0;
    $: byHost = (() => {
        const m = new Map();
        for (const s of svcList) {
            const h = m.get(s.host) || { host: s.host, total: 0, up: 0, mem: 0 };
            h.total++; if (s.status === 'running') { h.up++; if (!isVmEngine(s)) h.mem += s.mem_mb || 0; }
            m.set(s.host, h);
        }
        return [...m.values()];
    })();
    $: topSvc = svcList.filter(s => s.status === 'running' && !isVmEngine(s)).sort((a, b) => (b.mem_mb || 0) - (a.mem_mb || 0)).slice(0, 3);
    // topology: Arrakis's own services, then each machine's, busiest first
    const byMem = (a, b) => (b.status === 'running') - (a.status === 'running') || (b.mem_mb || 0) - (a.mem_mb || 0);
    $: macSvc = svcList.filter(s => s.host === 'Mac' && !isVmEngine(s)).sort(byMem);
    const shortImage = (img) => img.replace(/^(lscr\.io|ghcr\.io|docker\.io|quay\.io)\//, '').replace(/:latest$/, '');
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
    const fmtDur = (sec) => { const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60); return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`; };

    // ---- tailscale, databases, tmux, endpoints ------------------------------------------
    $: peers = stats?.connections?.tailscale || [];

    function ago(iso) {
        if (!iso) return 'offline';
        const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
        return s < 3600 ? `${Math.max(1, Math.round(s / 60))}m ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`;
    }
    let dbList = [];
    async function fetchDatabases() {
        try { const j = await fetch('/api/databases').then(r => r.json()); if (j.status === 'success') dbList = j.data; } catch (e) {}
    }
    const size = (b) => { if (!b) return '0 B'; const i = Math.floor(Math.log(b) / Math.log(1024)); return +(b / 1024 ** i).toFixed(1) + ' ' + ['B', 'KB', 'MB', 'GB', 'TB'][i]; };
    $: sessions = tmux?.sessions || [];
    // ---- api latency: reads only; actions (create a machine, restart a service) take seconds by design
    $: reads = $endpoints.filter(e => e.latency != null && e.method === 'GET');
    $: readMs = reads.map(e => e.latency).sort((a, b) => a - b);
    $: medianMs = readMs.length ? readMs[readMs.length >> 1] : null;
    $: p95Ms = readMs.length ? readMs[Math.min(readMs.length - 1, Math.floor(readMs.length * 0.95))] : null;
    $: slowest = [...reads].sort((a, b) => b.latency - a.latency).slice(0, 3);
    const short = (p) => p.replace(/^\/api\//, '/').replace(/\/\{.*?\}/g, '/*');

    // Histogram on a log axis, 0.1 ms to 1 s: six bars a decade, each as tall as the number of
    // endpoints that answer in that range (too many endpoints now for one dot each)
    const LAT_AXIS = 24, LAT_TOP = 30, BAR_H = 80, PER_DEC = 8, NBINS = 4 * PER_DEC, DECADES = [0.1, 1, 10, 100, 1000];
    // anything faster than 0.1 ms sits in the first bar, so that tick says so
    const tickLabel = (d) => d >= 1000 ? '1 s' : d === 0.1 ? '≤0.1 ms' : `${d} ms`;
    let latW = 600, hoverPath = null, latCardW = 1200, hoverBin = -1;
    $: lx = (ms) => 12 + (Math.log10(Math.min(1000, Math.max(0.1, ms))) + 1) / 4 * (latW - 24);
    const binOf = (ms) => Math.max(0, Math.min(NBINS - 1, Math.floor((Math.log10(Math.max(0.1, ms)) + 1) * PER_DEC)));
    $: bins = (() => {
        const out = Array.from({ length: NBINS }, (_, i) => ({ i, lo: 10 ** (i / PER_DEC - 1), hi: 10 ** ((i + 1) / PER_DEC - 1), eps: [] }));
        for (const e of reads) out[binOf(e.latency)].eps.push(e);
        for (const b of out) b.eps.sort((x, y) => y.latency - x.latency);
        return out;
    })();
    $: binMax = Math.max(1, ...bins.map(b => b.eps.length));
    const latH = LAT_TOP + BAR_H + LAT_AXIS;
    // a slowest chip lights up the bar its endpoint is in
    $: litBin = hoverBin >= 0 ? hoverBin : hoverPath ? binOf(reads.find(e => e.path === hoverPath)?.latency ?? 0) : -1;
    $: tipBin = hoverBin >= 0 ? bins[hoverBin] : null;
    // the popup stays while the pointer moves from the bar into it, so its endpoints can be picked
    let tipTimer, pinBin = -1;
    // a click pins the popup (hover only previews), so its endpoints can be picked
    const unpin = () => { if (pinBin >= 0) { pinBin = -1; hoverBin = -1; } };
    const leaveBin = () => { clearTimeout(tipTimer); tipTimer = setTimeout(() => hoverBin = -1, 220); };
    const binRange = (b) => `${fmtMs(b.lo)}–${fmtMs(b.hi)}`;
    const openEp = (id) => location.hash = id ? `#endpoints/${id}/history` : '#endpoints';
    let backup = null;
    async function fetchBackup() {
        try { const j = await fetch('/api/backups/details').then(r => r.json()); if (j.status === 'success') backup = j.data; } catch (e) {}
    }
    const agoTs = (t) => { const s = Math.max(0, now / 1000 - t); return s < 3600 ? `${Math.round(s / 60)}m ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`; };
    const inTs = (t) => { const s = Math.max(0, t - now / 1000); return s < 3600 ? `in ${Math.round(s / 60)}m` : s < 86400 ? `in ${Math.round(s / 3600)}h` : `in ${Math.round(s / 86400)}d`; };
    // narrower than two columns: every section full width, in order
    let vw = 1440, totRows = 1;
    $: narrow = vw <= 1000;
    // the shown sections in order, consecutive half-width ones grouped into pairs of columns
    $: groups = (() => {
        const out = [];
        for (const id of $layout.order.filter(show)) {
            const half = $layout.widths[id] === 'half', last = out.at(-1);
            if (half && narrow) { out.push({ key: id, half: false, ids: [id] }); continue; }
            if (half && last?.half) last.ids.push(id);
            else out.push({ key: id, half, ids: [id] });
        }
        return out;
    })();
    // the shortcuts picked under Customize: each page with one figure of what it holds
    $: SC = {
        databases: { to: '#databases', icon: Database, k: 'Databases', v: String(dbList.length), s: size(dbList.reduce((a, d) => a + (d.size_bytes || 0), 0)) },
        terminal: { to: '#terminal', icon: Terminal, k: 'Terminal', v: String(sessions.length), s: sessions.length === 1 ? 'tmux session' : 'tmux sessions' },
        backups: { to: '#backups', icon: Archive, k: 'Backups', v: backup?.last_success ? agoTs(backup.last_success) : '—', s: backup?.next_run ? 'next ' + inTs(backup.next_run) : '' },
        updates: { to: '#updates', icon: PackageCheck, k: 'Updates', v: String(pendingUpdates), s: pendingUpdates ? `on ${updTargets.length} ${updTargets.length === 1 ? 'computer' : 'computers'}` : 'all up to date' },
        apps: { to: '#apps/installed', icon: Store, k: 'Apps', v: '', s: 'installed and catalogue' },
        logs: { to: '#logs', icon: ScrollText, k: 'Logs', v: '', s: 'search every log' },
        tailscale: { to: '#tailscale', icon: Network, k: 'Tailscale', v: String(($tailnet?.devices || []).filter(d => d.online && !d.self).length), s: 'devices online' },
        cloudflare: { to: '#cloudflare', icon: Cloud, k: 'Cloudflare', v: String(($cloudflare?.tunnels || []).filter(isActive).length), s: 'tunnels up' },
        pihole: { to: '#tools/pihole', icon: ShieldCheck, k: 'Pi-hole', v: '', s: 'queries and blocking' },
        endpoints: { to: '#endpoints', icon: Eye, k: 'API endpoints', v: String($endpoints.length), s: 'routes' },
    };
    const fmtMs = (ms) => (ms < 10 ? ms.toFixed(1) : Math.round(ms)) + ' ms';

    onMount(() => {
        fetchLayout(); fetchHistory(); fetchDatabases(); fetchBackup(); fetchTailnet(); fetchEndpoints(); fetchMachines(); fetchMachineUsage(); fetchServices(); fetchHosts(); fetchDisks();
        const tick = setInterval(() => now = Date.now(), 1000);
        const poll = setInterval(() => {
            if (!visible()) return;
            if (Date.now() - histAt >= range.refresh * 1000) fetchHistory();
            fetchMachineUsage(); fetchHosts();
        }, 5000);
        const slow = setInterval(() => { if (visible()) { fetchEndpoints(); fetchDatabases(); fetchBackup(); fetchTailnet(); fetchServices(); fetchMachines(); fetchDisks(); } }, 30000);
        return () => { clearInterval(tick); clearInterval(poll); clearInterval(slow); };
    });
</script>

<svelte:window bind:innerWidth={vw} on:click={(e) => !e.target.closest?.(".lat-tip, .hit") && unpin()} on:keydown={e => e.key === 'Escape' && unpin()} />
{#if customizing}
<CustomizeMenu mode="editor" />
{:else}
<div class="ui-page">
    <div class="ui-head">
        <div>
            <h1>Overview</h1>
            <div class="ui-meta">
                <span><b>{onlineHosts}</b> of {plural(1 + ($hosts || []).length, 'host')} online</span>
                <span><b>{machineList.filter(m => m.state === 'running').length}</b> {machineList.filter(m => m.state === 'running').length === 1 ? 'machine' : 'machines'} running</span>
                <span><b>{runningContainers}</b> {runningContainers === 1 ? 'container' : 'containers'}</span>
                {#if pendingUpdates && !show('attention')}<a class="up-link" href="#updates">{plural(pendingUpdates, 'update')} on {updTargets.length === 1 ? updTargets[0].name : plural(updTargets.length, 'computer')}</a>{/if}
            </div>
        </div>
        <div class="ui-head-actions">
            <CustomizeMenu mode="button" data={{ arrakis: { cpu: live.cpu ?? cpuNow, mem, disk, cores }, pendingUpdates, updTargets, backupAgo: backup?.last_success ? agoTs(backup.last_success) : null, dbCount: dbList.length, sessions: sessions.length, medianMs }} />
        </div>
    </div>

    <!-- the sections, in the order and with the cards picked under Customize -->
    {#snippet section(id)}
    <div class="msr" use:measureSection={`${id}:${$layout.widths[id] === 'half' && !narrow ? 'half' : 'full'}${id === 'totals' ? ':' + totRows : ''}`}>
    {#if id === 'webapps'}<WebAppsCard />
    {:else if id === 'attention'}<AttentionRow {now} {pendingUpdates} {updTargets} {backup} hide={$layout.hidden_tiles} />
    {:else if id === 'totals'}
    <!-- the cluster's totals split per host, as on the Infrastructure page -->
    <div id="sec-totals"><InfraIndex embedded cards={false} bind:rows={totRows} hideTiles={$layout.hidden_tiles} cols={$layout.totals_cols}
            arrakis={{ cpu: live.cpu, mem, disk, cores, os: 'macOS', up: upSince ? (now - upSince) / 1000 : null }}
            vm={{ running: !!vmEngine, cpu: vmCpu, memGb: vmGb, limitGb: pool ? pool.memory_mib / 1024 : null, up: vmEngine?.uptime_seconds }} /></div>
    {:else if id === 'host'}
    <div id="sec-host"><InfraIndex embedded summary={false} hiddenIds={$layout.hidden_hosts}
            arrakis={{ cpu: live.cpu, mem, disk, cores, os: 'macOS', up: upSince ? (now - upSince) / 1000 : null }}
            vm={{ running: !!vmEngine, cpu: vmCpu, memGb: vmGb, limitGb: pool ? pool.memory_mib / 1024 : null, up: vmEngine?.uptime_seconds }} /></div>
    {:else if id === 'tailscale'}<TailscaleCard {peers} />
    {:else if id === 'shortcuts'}
    <div class="shortcuts" id="sec-databases" style="--n: {Math.max(1, $layout.shortcuts.length)}">
        {#each $layout.shortcuts as k (k)}
            {@const c = SC[k]}
            <a class="sc" href={c.to}>
                <span class="sc-ic"><svelte:component this={c.icon} size={16} /></span>
                <span class="sc-main"><span class="sc-k">{c.k}</span><span class="sc-v">{c.v} <small>{#if c.v && c.s}<i class="sep">· </i>{/if}{c.s}</small></span></span>
                <ArrowRight size={14} class="sc-go" />
            </a>
        {:else}<div class="ui-card ui-empty">No shortcuts picked. Add some under Customize.</div>{/each}
    </div>
    {:else if id === 'compute'}<ComputeCard />
    {:else if id === 'uptime'}<UptimeCard />
    {:else if id === 'pihole'}<PiholeCard />
    {:else if id === 'machines'}<MachinesCard />
    {:else if id === 'api-latency'}
    <section class="ui-card" class:latn={latCardW < 760} id="sec-api-latency" bind:clientWidth={latCardW}>
        <div class="ui-card-head">
            <div><h2 class="ui-card-title">API latency <button type="button" class="info" use:infoPop aria-label="Reads only. Actions such as creating a machine take seconds by design and are left out."><Info size={13} /><span class="info-pop" role="tooltip">Reads only. Actions such as creating a machine take seconds by design and are left out.</span></button></h2><p class="ui-card-desc">How quickly the backend answers this dashboard.</p></div>
            <a class="ui-link more" href="#endpoints">Endpoints <ArrowRight size={13} /></a>
        </div>
        <div class="lat" style="border-top: 1px solid var(--border)">
            <div class="lat-hero">
                <span class="lat-k">Typical response</span>
                <span class="lat-v">{medianMs != null ? fmtMs(medianMs) : '—'}</span>
                <span class="lat-s">{#if p95Ms != null}95% of {reads.length} endpoints answer in under {fmtMs(p95Ms)}{:else}No measurements yet{/if}</span>
            </div>
            <div class="lat-plot"><div class="lat-area" bind:clientWidth={latW}>
                <svg width={latW} height={latH} role="img" aria-label="How many endpoints answer in each response-time range, log scale from 0.1 ms to 1 s">
                    <rect class="slow-band" x={lx(100)} y={LAT_TOP - 8} width={lx(1000) - lx(100) + 4} height={BAR_H + 8} rx="6" />
                    <text class="band-lbl" x={lx(1000) - 4} y={LAT_TOP + 6} text-anchor="end">Slow</text>
                    <line class="base" x1="8" x2={latW - 8} y1={LAT_TOP + BAR_H + 0.5} y2={LAT_TOP + BAR_H + 0.5} />
                    {#each DECADES as d}
                        <line class="tk" x1={lx(d)} x2={lx(d)} y1={LAT_TOP + BAR_H} y2={LAT_TOP + BAR_H + 4} />
                        <text class="tick" x={lx(d)} y={latH - 5} text-anchor={d === 0.1 ? 'start' : d === 1000 ? 'end' : 'middle'}>{tickLabel(d)}</text>
                    {/each}
                    {#each bins as b (b.i)}
                        {#if b.eps.length}
                            {@const h = Math.max(4, b.eps.length / binMax * BAR_H)}
                            {@const x = lx(b.lo) + 1.5}
                            {@const w = Math.max(2, lx(b.hi) - lx(b.lo) - 3)}
                            <path class="bar" class:hl={litBin === b.i} class:dim={litBin >= 0 && litBin !== b.i}
                                d="M{x},{LAT_TOP + BAR_H} v{-(h - 2)} q0,-2 2,-2 h{Math.max(0, w - 4)} q2,0 2,2 v{h - 2} z" />
                            <rect class="hit" x={x - 1} y={LAT_TOP + BAR_H - Math.max(h, 14)} width={w + 2} height={Math.max(h, 14)} role="presentation" on:mouseenter={() => { if (pinBin < 0) { clearTimeout(tipTimer); hoverBin = b.eps.length ? b.i : -1; } }} on:mouseleave={() => pinBin < 0 && leaveBin()} on:click|stopPropagation={() => { pinBin = b.eps.length && pinBin !== b.i ? b.i : -1; hoverBin = pinBin; }} />
                            <text class="cnt" x={x + w / 2} y={LAT_TOP + BAR_H - h - 5} text-anchor="middle">{b.eps.length}</text>
                        {/if}
                    {/each}
                    {#if medianMs != null}
                        <line class="med" x1={lx(medianMs)} x2={lx(medianMs)} y1="14" y2={LAT_TOP + BAR_H} />
                        <text class="med-lbl" x={lx(medianMs)} y="10" text-anchor="middle">typical</text>
                    {/if}
                </svg>
                {#if tipBin}
                    {@const cx = (lx(tipBin.lo) + lx(tipBin.hi)) / 2}
                    {@const left = Math.min(Math.max(cx, 120), latW - 120)}
                    <!-- svelte-ignore a11y_no_static_element_interactions -->
                    <div class="lat-tip pick" style="left: {left}px; top: {LAT_TOP + BAR_H - Math.max(4, tipBin.eps.length / binMax * BAR_H)}px; --arrow: {cx - left}px" on:mouseenter={() => clearTimeout(tipTimer)} on:mouseleave={() => pinBin < 0 && leaveBin()} on:click|stopPropagation>
                        <div class="tip-row"><b>{tipBin.eps.length} {tipBin.eps.length === 1 ? 'endpoint' : 'endpoints'}</b><span class="tip-r">{binRange(tipBin)}</span></div>
                        {#if pinBin < 0}<div class="tip-hint">Click to see them</div>{/if}
                        {#if pinBin >= 0}<div class="tip-list">{#each tipBin.eps as e (e.path)}<a class="tip-row tip-a" href={e.id ? `#endpoints/${e.id}/history` : '#endpoints'}><span class="tip-p">{short(e.path)}</span><span>{fmtMs(e.latency)}</span></a>{/each}</div>{/if}
                    </div>
                {/if}
            </div></div>
        </div>
        {#if slowest.length}
            <div class="lat-slow">
                <span class="lat-slow-k">Slowest</span>
                {#each slowest as e, i (e.path)}
                    <a class="lat-chip" class:on={hoverPath === e.path} href={e.id ? `#endpoints/${e.id}/history` : '#endpoints'} on:mouseenter={() => hoverPath = e.path} on:mouseleave={() => hoverPath = null}>
                        <span class="rk">{i + 1}</span><span class="p">{short(e.path)}</span><b>{fmtMs(e.latency)}</b>
                    </a>
                {/each}
            </div>
        {/if}
    </section>
    {/if}
    </div>
    {/snippet}

    <!-- full-width sections one per row; a run of half-width ones as two columns that stack
         independently (first, third… left; second, fourth… right), so a short one leaves no hole -->
    <div class="secs">
    {#each groups as g (g.key)}
        {#if g.half}
            <div class="pair">
                {#each [g.ids.filter((_, i) => i % 2 === 0), g.ids.filter((_, i) => i % 2 === 1)] as col}
                    <div class="col">{#each col as id (id)}{@render section(id)}{/each}</div>
                {/each}
            </div>
        {:else}{@render section(g.ids[0])}{/if}
    {/each}
    </div>
</div>

{/if}
<style>
    /* usage */
    .mtabs { display: flex; align-items: stretch; border-bottom: 1px solid var(--border); border-top: 1px solid var(--border); }
    .mtab { flex: 1; display: flex; flex-direction: column; gap: 4px; padding: 16px 20px 14px; text-align: left; cursor: pointer; border-right: 1px solid var(--border); position: relative; min-width: 0; }
    .mtab:hover { background: var(--highlight-3); }
    .mtab.on { background: var(--surface); }
    .mtab.on::after { content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px; background: var(--accent); }
    .mtab:first-child { border-radius: 0; }
    .mt-label { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--text-secondary); font-weight: 500; }
    .mt-label i { width: 8px; height: 8px; border-radius: 2px; }
    .mtab.on .mt-label { color: var(--text-primary); }
    .mt-value { font-size: 24px; font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; letter-spacing: -0.01em; white-space: nowrap; }
    .mt-value small { font-size: 13px; font-weight: 400; color: var(--text-secondary); margin-left: 5px; }
    .mt-sub { font-size: 12px; color: var(--text-secondary); line-height: 1.4; }
    .mt-range { display: flex; align-items: center; padding: 0 16px; }
    .chart { padding: 12px 16px 8px; position: relative; }
    .unit { position: absolute; top: 4px; left: 14px; font-size: 10.5px; color: var(--text-secondary); }

    .row { display: grid; gap: 16px; align-items: stretch; }
    .row > .ui-card { display: flex; flex-direction: column; }
    .more { font-size: 13px; white-space: nowrap; margin-top: 2px; }

    .tp-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--highlight-30); flex-shrink: 0; }
    .tp-dot.tp-up { background: var(--green); }

    /* tailscale summary */
    .ts-row { grid-template-columns: 2fr 1fr; }

    /* sections: full width, or two half-width ones side by side (one column on narrower screens) */
    .msr { display: flex; flex-direction: column; min-width: 0; }
    .secs { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
    .pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; align-items: start; }
    .col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }


    /* shortcuts */
    /* as many across as fit (at least 220px each), never more than there are */
    .shortcuts { display: grid; grid-template-columns: repeat(auto-fit, minmax(max(220px, calc((100% - 36px) / min(var(--n), 4))), 1fr)); gap: 12px; align-content: start; }
    .ts-row .shortcuts { grid-auto-rows: 1fr; }
    .ts-row.single { grid-template-columns: 1fr; }
    .ts-row.single .shortcuts { grid-template-columns: repeat(2, 1fr); }
    .sc { display: flex; align-items: center; gap: 12px; padding: 14px 16px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card, 8px); text-decoration: none; color: var(--text-primary); transition: border-color .12s, box-shadow .12s; min-width: 0; }
    .sc:hover { border-color: var(--border-strong); box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05); }
    .sc-ic { width: 36px; height: 36px; border-radius: 9px; background: var(--accent-soft); color: var(--accent); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .sc-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
    .sc-k { font-size: 12.5px; color: var(--text-secondary); }
    .sc-v { font-size: 17px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .sc-v small { font-size: 12.5px; font-weight: 400; color: var(--text-secondary); }
    .sc :global(.sc-go) { color: var(--text-secondary); flex-shrink: 0; transition: transform .12s; }
    .sc:hover :global(.sc-go) { color: var(--accent); transform: translateX(2px); }


    /* api latency */
    .lat { display: grid; grid-template-columns: 220px minmax(0, 1fr); }
    .lat-hero { display: flex; flex-direction: column; justify-content: center; gap: 4px; padding: 20px; border-right: 1px solid var(--border); }
    .lat-k { font-size: 12.5px; color: var(--text-secondary); font-weight: 500; }
    .lat-v { font-size: 32px; font-weight: 600; letter-spacing: -0.02em; color: var(--text-primary); font-variant-numeric: tabular-nums; line-height: 1.1; }
    .lat-s { font-size: 12.5px; color: var(--text-secondary); line-height: 1.45; }
    .info { position: relative; display: inline-flex; vertical-align: -1px; margin-left: 4px; color: var(--text-secondary); opacity: 0.6; cursor: help; }
    .info:hover, .info:focus-visible { opacity: 1; }
    .info-pop { position: absolute; left: calc(-10px + var(--dx, 0px)); max-width: calc(100vw - 24px); top: calc(100% + 8px); width: 280px; text-align: left; padding: 8px 10px; border-radius: 6px; background: var(--text-primary); color: var(--surface); font-size: 12px; font-weight: 400; line-height: 1.45; letter-spacing: 0; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18); display: none; z-index: 5; }
    .info:hover .info-pop, .info:focus-visible .info-pop, :global(.info.open) .info-pop { display: block; animation: info-in .15s ease; }
    @keyframes info-in { from { opacity: 0; transform: translateY(-4px); } }
    .lat-plot { position: relative; padding: 16px 20px 12px; min-width: 0; align-self: center; }
    .lat-area { position: relative; }
    .lat-plot svg { display: block; overflow: visible; }
    .slow-band { fill: var(--highlight-3); }
    .base { stroke: var(--border); stroke-width: 1; }
    .tk { stroke: var(--border); stroke-width: 1; }
    .cnt { font-size: 10.5px; fill: var(--text-secondary); font-variant-numeric: tabular-nums; opacity: 0; transition: opacity .15s; }
    .lat-area:hover .cnt { opacity: 1; }
    .band-lbl { font-size: 11px; font-weight: 500; fill: var(--text-secondary); }
    .grid { stroke: var(--highlight-20); stroke-width: 1; stroke-dasharray: 2 3; }
    .tick { font-size: 11px; fill: var(--text-secondary); font-variant-numeric: tabular-nums; }
    .dot { fill: var(--accent); stroke: var(--surface); stroke-width: 2; opacity: 0.85; transition: r .15s ease, opacity .15s ease, cx .6s cubic-bezier(0.22, 1, 0.36, 1), cy .6s cubic-bezier(0.22, 1, 0.36, 1); animation: dot-in .5s cubic-bezier(0.22, 1, 0.36, 1) backwards; animation-delay: calc(var(--i) * 18ms); }
    @keyframes dot-in { from { opacity: 0; transform: translateY(6px); } }
    .med { stroke: var(--accent); stroke-width: 1.5; pointer-events: none; }
    .med-lbl { font-size: 10.5px; font-weight: 600; fill: var(--accent); letter-spacing: 0.02em; pointer-events: none; }
    .bar { fill: var(--text-secondary); opacity: 0.32; transition: opacity .15s ease, fill .15s ease; }
    .bar.hl { opacity: 0.75; }
    .bar.dim { opacity: 0.18; }
    .tip-r { opacity: 0.7; font-variant-numeric: tabular-nums; }
    /* the bar's popup can be entered: every endpoint in the range, each opening its history */
    .lat-tip.pick { pointer-events: auto; padding: 8px 6px 6px; min-width: 240px; }
    .lat-tip.pick > .tip-row { padding: 0 6px 4px; }
    .lat-tip.pick::before { content: ''; position: absolute; left: 0; right: 0; bottom: -14px; height: 14px; }
    .tip-list { display: flex; flex-direction: column; max-height: 180px; overflow-y: auto; }
    .tip-hint { padding: 0 6px 2px; font-size: 11px; opacity: 0.6; }
    .lat-tip.pick:not(:has(.tip-list)) { min-width: 0; }
    .tip-a { padding: 4px 6px; border-radius: 4px; color: inherit; text-decoration: none; }
    .tip-a:hover { background: color-mix(in srgb, var(--surface) 18%, transparent); }
    .hit { fill: transparent; cursor: pointer; }
    .lat-tip { position: absolute; transform: translate(-50%, calc(-100% - 12px)); display: flex; flex-direction: column; gap: 6px; padding: 8px 10px; border-radius: 6px; background: var(--text-primary); color: var(--surface); font-size: 12px; white-space: nowrap; pointer-events: none; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18); z-index: 2; }
    .lat-tip::after { content: ''; position: absolute; left: calc(50% + var(--arrow, 0px)); bottom: -4px; width: 8px; height: 8px; background: inherit; transform: translateX(-50%) rotate(45deg); border-radius: 1px; }
    .tip-row { display: flex; gap: 14px; align-items: baseline; justify-content: space-between; }
    .tip-p { font-family: 'JetBrains Mono', monospace; }
    .lat-tip b { font-weight: 600; font-variant-numeric: tabular-nums; }
    .tip-hist { display: flex; align-items: flex-end; gap: 3px; height: 18px; }
    .tip-hist i { width: 6px; border-radius: 1.5px; background: currentColor; opacity: 0.55; }
    .tip-hist i:last-of-type { opacity: 1; }
    .tip-hist small { margin-left: 6px; align-self: center; font-size: 10.5px; opacity: 0.65; }
    .lat-slow { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 12px 20px 14px; border-top: 1px solid var(--border); }
    .lat-slow-k { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-right: 4px; }
    .lat-chip { display: inline-flex; align-items: center; gap: 8px; height: 28px; padding: 0 12px; border: 1px solid var(--border); border-radius: 14px; text-decoration: none; color: var(--text-primary); font-size: 12.5px; min-width: 0; max-width: 100%; box-sizing: border-box; }
    .lat-chip:hover, .lat-chip.on { border-color: var(--accent); background: var(--accent-soft); }
    .lat-chip .p { font-family: 'JetBrains Mono', monospace; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .lat-chip b { font-weight: 600; font-variant-numeric: tabular-nums; flex-shrink: 0; }
    .rk { width: 16px; height: 16px; margin-left: -6px; border-radius: 50%; background: var(--highlight-10); color: var(--text-secondary); font-size: 10.5px; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
    /* narrow card (half width): the figure as one line on top, the plot across, the
       slowest as a short list instead of chips */
    .latn .lat { grid-template-columns: minmax(0, 1fr); }
    .latn .lat-hero { flex-direction: row; flex-wrap: wrap; justify-content: flex-start; align-items: baseline; column-gap: 10px; row-gap: 2px; padding: 14px 20px; border-right: none; border-bottom: 1px solid var(--border); }
    .latn .lat-k { flex-basis: 100%; }
    .latn .lat-v { font-size: 24px; }
    .latn .lat-plot { padding: 12px 16px 8px; }
    .latn .lat-slow { display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px; padding: 10px 12px 12px; }
    .latn .lat-slow-k { padding: 0 8px 4px; }
    .latn .lat-chip { height: 30px; border: none; border-radius: 6px; padding: 0 8px; }
    .latn .lat-chip b { margin-left: auto; }
    .lat-chip.on .rk, .lat-chip:hover .rk { background: var(--accent); color: var(--surface); }


    /* three narrow tiles: the detail drops under the figure instead of trailing off */
    @media (min-width: 761px) and (max-width: 1100px) {
        .sc-v small { display: block; margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .sc-v .sep { display: none; }
    }
    /* laptop widths: the metric tabs get narrow, so the value drops its "of 16 GB" and shrinks a step */
    @media (max-width: 1200px) {
        .mt-value { font-size: 20px; }
        .mt-value small { display: none; }
        .mtab { padding: 14px 16px 12px; }
    }
    @media (max-width: 1000px) {
        .mtabs { flex-wrap: wrap; }
        .mt-range { flex-basis: 100%; padding: 10px 16px; border-top: 1px solid var(--border); }
        .mt-range .ui-seg { width: 100%; }
        .mt-range .ui-seg button { flex: 1; }
    }
    @media (max-width: 1100px) {
        .ts-row { grid-template-columns: 1fr; }
    }
    @media (max-width: 760px) {
        .ui-card-head { flex-wrap: wrap; }
        .mtabs { flex-wrap: wrap; }
        .mtab { flex: 1 1 33%; padding: 12px 14px; }
        .mt-value { font-size: 18px; }
        .mt-value small { display: none; }
        .mt-sub { display: none; }
        .mt-range { flex-basis: 100%; padding: 10px 14px; border-top: 1px solid var(--border); }
        .mt-range .ui-seg { width: 100%; }
        .mt-range .ui-seg button { flex: 1; }
        .chart { padding: 14px 8px 4px; }
        .shortcuts, .ts-row.single .shortcuts { grid-template-columns: 1fr; }
        .lat { grid-template-columns: 1fr; }
        .lat-hero { border-right: none; border-bottom: 1px solid var(--border); padding: 16px 14px; }
        .lat-v { font-size: 26px; }
        .lat-plot { padding: 12px 14px 6px; }
        .lat-slow { padding: 12px 14px; }
        .lat-slow-k { flex-basis: 100%; }
    }
    .up-link { color: inherit; text-decoration: none; }
    .up-link:hover { color: var(--accent); text-decoration: underline; }
</style>
