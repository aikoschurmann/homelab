<script>
    import { copyText } from '../../lib/clipboard.js';
    import { onMount } from 'svelte';
    import { Play, Square, RotateCw, Loader2, Cpu, Box, Copy, Check, FileText, Globe, Pin, PinOff, Link } from 'lucide-svelte';
    import { uptime, actions, serviceAction, BUSY_LABEL, fmtUptime, fmtMb, fmtPct } from '../../lib/services.js';
    import { visible } from '../../lib/stores.js';
    import StatusPill from '../ui/StatusPill.svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';
    import Tabs from '../ui/Tabs.svelte';
    import CopyText from '../ui/CopyText.svelte';
    import UptimeStrip from '../ui/UptimeStrip.svelte';
    import LiveChart from '../ui/LiveChart.svelte';
    import LogViewer from '../LogViewer.svelte';
    import { webLinks, linkOf, absUrl, setLink, editLink } from '../../lib/weblinks.js';

    export let svc;
    export let host = 'the Mac';      // where containers run
    export let tab = 'overview';
    export let setTab = () => {};
    export let now = Date.now();

    const TABS = [
        { id: 'overview', label: 'Overview' },
        { id: 'metrics', label: 'Metrics' },
        { id: 'logs', label: 'Logs' },
        { id: 'inspect', label: 'Inspect' },
    ];

    $: running = svc.status === 'running';
    $: a = $actions[svc.key];
    $: u = $uptime.services[svc.key];

    // ---- metrics from the dashboard's own service_metrics table (every ~10 s, 7 days) ----
    const RANGES = [{ id: 1, label: '1H' }, { id: 6, label: '6H' }, { id: 24, label: '24H' }, { id: 168, label: '7D' }];
    let range = 1;
    let pts = [];
    let loadingPts = true;
    async function loadMetrics() {
        try {
            const j = await fetch(`/api/services/metrics/${svc.kind}/${encodeURIComponent(svc.id)}?hours=${range}`).then(r => r.json());
            if (j.status === 'success') pts = j.data.points;
        } catch (e) {}
        loadingPts = false;
    }
    $: range, loadMetrics();
    onMount(() => {
        const t = setInterval(() => visible() && loadMetrics(), 15000);
        return () => clearInterval(t);
    });
    $: memPeak = pts.length ? Math.max(...pts.map(p => p.mem_max || p.mem)) : null;
    $: memAvg = pts.length ? pts.reduce((s, p) => s + p.mem, 0) / pts.length : null;
    $: cpuAvg = pts.length ? pts.reduce((s, p) => s + p.cpu, 0) / pts.length : null;
    $: cpuPeak = pts.length ? Math.max(...pts.map(p => p.cpu)) : null;
    // CPU axis: at least 1%, else the peak plus headroom, so small services stay readable
    const cpuMax = (v) => { const m = Math.max(1, v.max * 1.25); return m < 5 ? Math.ceil(m) : Math.ceil(m / 5) * 5; };
    const fmtAxisPct = (v) => (+v >= 10 || Number.isInteger(+v) ? (+v).toFixed(0) : (+v).toFixed(1)) + '%';
    // last ~15 min of points feed the overview sparkline
    $: recent = pts.filter(p => p.t * 1000 > now - 15 * 60 * 1000);

    let copied = false;
    async function copyJson() {
        try { await copyText(JSON.stringify(svc.raw, null, 2)); copied = true; setTimeout(() => copied = false, 1200); } catch (e) {}
    }

    $: menuItems = [
        running ? { label: 'Restart', icon: RotateCw, onClick: () => serviceAction(svc, 'restart') } : { label: 'Start', icon: Play, onClick: () => serviceAction(svc, 'start') },
        running ? { label: 'Stop', icon: Square, onClick: () => serviceAction(svc, 'stop') } : null,
        { label: 'View logs', icon: FileText, onClick: () => setTab('logs'), divider: true },
        { label: 'Copy JSON', icon: Copy, onClick: copyJson },
        webUrl ? { label: pinned ? 'Unpin from Overview' : 'Pin to Overview', icon: pinned ? PinOff : Pin, onClick: () => setLink(svc.key, { pinned: !pinned }), divider: true } : null,
        { label: webUrl ? 'Web UI address…' : 'Add web UI…', icon: Link, onClick: () => editLink(svc), divider: !webUrl },
    ];
    $: webUrl = absUrl(linkOf($webLinks, svc));
    $: pinned = !!$webLinks[svc.key]?.pinned;
    // docker lists every published port twice (0.0.0.0 and [::]); "any address" is the default, so drop it and dedupe
    const portList = (ports) => [...new Set(ports.split(', ').map(p => p.replace(/^(0\.0\.0\.0|\[::\]):/, '').replace('->', '→')))];
</script>

<div class="ui-page">
    <div class="ui-head">
        <div class="id">
            <span class="icon" class:on={running}>{#if svc.kind === 'daemon'}<Cpu size={20} />{:else}<Box size={20} />{/if}</span>
            <div>
                <h1>{svc.name}
                    {#if a?.state === 'running'}<StatusPill state="starting" label={BUSY_LABEL[a.act]} />
                    {:else if svc.health === 'unhealthy'}<StatusPill state="error" label="Unhealthy" />
                    {:else}<StatusPill state={running ? 'running' : 'stopped'} />{/if}
                </h1>
                <div class="ui-meta">
                    <span>{svc.kind === 'daemon' ? 'Daemon on the Mac' : `Container on ${host}`}</span>
                    {#if svc.image}<span class="ui-mono">{svc.image}</span>{/if}
                    {#if running && svc.startedAt}<span>Up {fmtUptime(now - svc.startedAt)}</span>{/if}
                </div>
            </div>
        </div>
        <div class="ui-head-actions">
            {#if webUrl}<a class="ui-btn" href={webUrl} target="_blank" rel="noopener noreferrer" title={webUrl}><Globe size={14} /> Open web UI</a>{/if}
            {#if running}
                <button class="ui-btn" disabled={!!a} on:click={() => serviceAction(svc, 'restart')}>{#if a?.state === 'running' && a.act === 'restart'}<Loader2 size={14} class="ui-spin" /> Restarting…{:else}<RotateCw size={14} /> Restart{/if}</button>
                <button class="ui-btn" disabled={!!a} on:click={() => serviceAction(svc, 'stop')}>{#if a?.state === 'running' && a.act === 'stop'}<Loader2 size={14} class="ui-spin" /> Stopping…{:else}<Square size={14} /> Stop{/if}</button>
            {:else}
                <button class="ui-btn primary" disabled={!!a} on:click={() => serviceAction(svc, 'start')}>{#if a?.state === 'running' && a.act === 'start'}<Loader2 size={14} class="ui-spin" /> Starting…{:else}<Play size={14} /> Start{/if}</button>
            {/if}
            <ActionMenu items={menuItems} label="More actions" />
        </div>
    </div>

    <Tabs tabs={TABS} active={tab} onSelect={setTab} />

    {#if tab === 'overview'}
        <div class="ui-stats">
            <div class="ui-stat">
                <span class="ui-stat-label">CPU</span>
                <span class="ui-stat-value">{running ? svc.cpu.toFixed(1) + '%' : '—'}</span>
                <div class="spark">{#if recent.length > 1}<LiveChart points={recent.map(p => [p.t * 1000, p.cpu])} windowMs={15 * 60 * 1000} height={36} bare />{/if}</div>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Memory</span>
                <span class="ui-stat-value">{running ? fmtMb(svc.mem_mb) : '—'}</span>
                <div class="spark">{#if recent.length > 1}<LiveChart points={recent.map(p => [p.t * 1000, p.mem])} windowMs={15 * 60 * 1000} height={36} color="var(--metric-mem)" bare />{/if}</div>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Uptime</span>
                <span class="ui-stat-value">{running && svc.startedAt ? fmtUptime(now - svc.startedAt) : '—'}</span>
                <span class="ui-stat-sub">{running && svc.startedAt ? 'since ' + new Date(svc.startedAt).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : 'not running'}</span>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Availability, 24 h</span>
                <span class="ui-stat-value">{fmtPct(u?.pct)}</span>
                <span class="ui-stat-sub">share of checks it was up</span>
            </div>
        </div>

        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Last 24 hours</h2><p class="ui-card-desc">Each segment is half an hour. Hover one for its state.</p></div></div>
            <div class="ui-card-body strip-body">
                <UptimeStrip slots={u?.slots || []} bucketSeconds={$uptime.bucket_seconds} height={10} />
                <div class="axis"><span>24 h ago</span><span>12 h ago</span><span>now</span></div>
            </div>
        </section>

        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Details</h2><p class="ui-card-desc">How this service runs.</p></div></div>
            <dl class="ui-kv" style="border-top: 1px solid var(--border)">
                <dt>ID</dt><dd><CopyText text={svc.id} /></dd>
                <dt>Type</dt><dd>{svc.kind === 'daemon' ? `Daemon on the Mac${svc.type ? ` (${svc.type})` : ''}` : `Docker container on ${host}`}</dd>
                {#if svc.image}<dt>Image</dt><dd><CopyText text={svc.image} /></dd>{/if}
                {#if svc.kind === 'container'}<dt>Ports</dt><dd class="ports">{#if svc.ports}{#each portList(svc.ports) as p}<code>{p}</code>{/each}{:else}<span class="ui-dim">None published</span>{/if}</dd>{/if}
                <dt>Web UI</dt><dd>{#if webUrl}<a class="ui-link" href={webUrl} target="_blank" rel="noopener noreferrer">{webUrl}</a>{:else}<span class="ui-dim">None</span>{/if} <button class="ui-btn sm" on:click={() => editLink(svc)}>{webUrl ? 'Edit' : 'Add'}</button></dd>
                {#if svc.health}<dt>Health check</dt><dd>{svc.health}</dd>{/if}
                {#if svc.pid}<dt>PID</dt><dd class="ui-mono">{svc.pid}</dd>{/if}
                {#if svc.cmd}<dt>Command</dt><dd class="ui-mono">{svc.cmd}</dd>{/if}
            </dl>
        </section>

    {:else if tab === 'metrics'}
        <div class="metrics-bar">
            <p class="ui-hint" style="margin: 0">Sampled about every 10 seconds; kept for 7 days.</p>
            <div class="ui-seg">{#each RANGES as r}<button class:on={range === r.id} on:click={() => range = r.id}>{r.label}</button>{/each}</div>
        </div>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">CPU</h2><p class="ui-card-desc">Average {cpuAvg != null ? cpuAvg.toFixed(1) + '%' : '—'} · peak {cpuPeak != null ? cpuPeak.toFixed(1) + '%' : '—'}</p></div>
                <span class="big">{running ? svc.cpu.toFixed(1) + '%' : '—'}</span></div>
            <div class="ui-card-body chart">
                {#if pts.length > 1}<LiveChart points={pts.map(p => [p.t * 1000, p.cpu])} windowMs={range * 3600000} max={cpuMax} unit="%" />
                {:else}<div class="ui-empty">{loadingPts ? 'Loading…' : 'No samples in this range.'}</div>{/if}
            </div>
        </section>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Memory</h2><p class="ui-card-desc">Average {fmtMb(memAvg)} · peak {fmtMb(memPeak)}</p></div>
                <span class="big">{running ? fmtMb(svc.mem_mb) : '—'}</span></div>
            <div class="ui-card-body chart">
                {#if pts.length > 1}<LiveChart points={pts.map(p => [p.t * 1000, p.mem])} windowMs={range * 3600000} color="var(--metric-mem)" unit=" MB" />
                {:else}<div class="ui-empty">{loadingPts ? 'Loading…' : 'No samples in this range.'}</div>{/if}
            </div>
        </section>

    {:else if tab === 'logs'}
        <section class="ui-card logs">
            <LogViewer kind={svc.kind} id={svc.id} />
        </section>

    {:else if tab === 'inspect'}
        <section class="ui-card">
            <div class="ui-card-head">
                <div><h2 class="ui-card-title">Raw data</h2><p class="ui-card-desc">What the dashboard backend reports for this service.</p></div>
                <button class="ui-btn sm" on:click={copyJson}>{#if copied}<Check size={13} /> Copied{:else}<Copy size={13} /> Copy{/if}</button>
            </div>
            <pre class="json">{JSON.stringify(svc.raw, null, 2)}</pre>
        </section>
    {/if}
</div>

<style>
    .id { display: flex; align-items: center; gap: 16px; min-width: 0; }
    .icon { width: 52px; height: 52px; border-radius: 12px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); border: 1px solid var(--border); }
    .icon.on { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
    .ui-head { padding: 4px 0 2px; }
    .ui-head h1 { line-height: 1.2; }
    .id .ui-meta { margin-top: 6px; }
    .spark { height: 36px; margin: 0 -4px -4px; }
    .strip-body { display: flex; flex-direction: column; gap: 8px; }
    .axis { display: flex; justify-content: space-between; font-size: 11.5px; color: var(--text-secondary); }
    .ports { gap: 6px; }
    .ports code { font-family: 'JetBrains Mono', monospace; font-size: 12px; padding: 2px 6px; border-radius: 4px; background: var(--highlight-10); }
    .metrics-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .big { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text-primary); white-space: nowrap; }
    .chart { padding-top: 8px; padding-bottom: 8px; }
    .logs { overflow: hidden; }
    .json { margin: 0; padding: 16px 20px; border-top: 1px solid var(--border); font-family: 'JetBrains Mono', monospace; font-size: 12.5px; line-height: 1.6; color: var(--text-primary); white-space: pre-wrap; overflow-wrap: anywhere; }
    /* phone: cards inset 14px, so this lines up with the card's header */
    @media (max-width: 768px) { .json { padding-left: 14px; padding-right: 14px; } }
</style>
