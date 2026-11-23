<script>
    import { href } from '../../lib/infra.js';
    import { Search, Play, Square, RotateCw, ExternalLink, FileText, Activity, Cpu, Box, Loader2, Globe, Pin, PinOff, Link } from 'lucide-svelte';
    import { uptime, actions, serviceAction, BUSY_LABEL, fmtUptime, fmtMb, fmtPct } from '../../lib/services.js';
    import StatusPill from '../ui/StatusPill.svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';
    import UptimeStrip from '../ui/UptimeStrip.svelte';
    import { machines } from '../../lib/stores.js';
    import WebLinkButton from '../ui/WebLinkButton.svelte';
    import { webLinks, linkOf, absUrl, setLink, editLink } from '../../lib/weblinks.js';

    export let list = [];
    export let open = () => {};      // open(id, tab?)
    export let now = Date.now();

    export let host = null;          // lower-case host name from the route, or null for all
    export let setHost = () => {};
    export let title = 'Services';
    export let desc = null;
    let q = '';
    $: hostFilter = host || 'all';
    // where each service runs: daemons on the Mac, containers on the dashboard machine
    $: vm = $machines?.dashboard_vm || 'vm';
    const hostOf = (s) => s.host.toLowerCase();
    $: hosts = [...new Set(list.map(s => s.host))].map(h => ({ id: h.toLowerCase(), label: h }));
    $: shown = list.filter(s =>
        (hostFilter === 'all' || hostOf(s) === hostFilter) &&
        (!q || [s.name, s.id, s.image].some(v => v && v.toLowerCase().includes(q.toLowerCase()))));

    $: runningCount = list.filter(s => s.status === 'running').length;
    $: totalMem = list.reduce((a, s) => a + (s.status === 'running' ? s.mem_mb || 0 : 0), 0);
    $: daemons = list.filter(s => s.kind === 'daemon');
    $: containers = list.filter(s => s.kind === 'container');
    $: up = (s) => $uptime.services[s.key];
    $: pcts = list.map(s => up(s)?.pct).filter(p => p != null);
    $: avail = pcts.length ? pcts.reduce((a, b) => a + b, 0) / pcts.length : null;
    // biggest memory users, for the memory tile
    $: topMem = [...list].filter(s => s.status === 'running' && s.mem_mb).sort((a, b) => b.mem_mb - a.mem_mb).slice(0, 3);

    // web UI entries: open, pin to the Overview, set the address
    function webItems(s) {
        const url = linkOf($webLinks, s), pinned = !!$webLinks[s.key]?.pinned;
        return [
            url ? { label: 'Open web UI', icon: Globe, onClick: () => window.open(absUrl(url), '_blank', 'noopener,noreferrer'), divider: true } : null,
            url ? { label: pinned ? 'Unpin from Overview' : 'Pin to Overview', icon: pinned ? PinOff : Pin, onClick: () => setLink(s.key, { pinned: !pinned }) } : null,
            { label: url ? 'Web UI address…' : 'Add web UI…', icon: Link, onClick: () => editLink(s), divider: !url },
        ];
    }
    function menu(s) {
        const running = s.status === 'running';
        return [
            { label: 'Open', icon: ExternalLink, onClick: () => open(s.id) },
            running ? { label: 'Restart', icon: RotateCw, onClick: () => serviceAction(s, 'restart') } : null,
            running ? { label: 'Stop', icon: Square, onClick: () => serviceAction(s, 'stop') } : { label: 'Start', icon: Play, onClick: () => serviceAction(s, 'start') },
            { label: 'Metrics', icon: Activity, onClick: () => open(s.id, 'metrics'), divider: true },
            { label: 'Logs', icon: FileText, onClick: () => open(s.id, 'logs') },
        ];
    }
</script>

<div class="ui-page">
    <div class="ui-head">
        <div>
            <h1>{title}</h1>
            <p>{desc || `Daemons on the Mac and Docker containers on ${$machines?.dashboard_vm || 'the dashboard machine'}.`}</p>
        </div>
    </div>

    <div class="summary">
        <div class="ui-stat">
            <span class="ui-stat-label">Running</span>
            <span class="ui-stat-value">{runningCount}<small>of {list.length}</small></span>
            <span class="ui-stat-sub">{daemons.length} daemons · {containers.length} containers</span>
        </div>
        <div class="ui-stat">
            <span class="ui-stat-label">Memory in use</span>
            <span class="ui-stat-value">{fmtMb(totalMem)}</span>
            <span class="ui-stat-sub">{topMem.map(s => `${s.name} ${fmtMb(s.mem_mb)}`).join(' · ') || '—'}</span>
        </div>
        <div class="ui-stat">
            <span class="ui-stat-label">Availability, 24 h</span>
            <span class="ui-stat-value">{fmtPct(avail)}</span>
            <span class="ui-stat-sub">average across all services</span>
        </div>
    </div>

    <div class="ui-listbar">
        <label class="ui-search"><Search size={14} /><input placeholder="Search name or image" bind:value={q} /></label>
        {#if hosts.length > 1}<div class="ui-seg">
            <button class:on={hostFilter === 'all'} on:click={() => setHost(null)}>All hosts</button>
            {#each hosts as h}<button class:on={hostFilter === h.id} on:click={() => setHost(h.id)}>{h.label}</button>{/each}
        </div>{/if}
        <span class="ui-count">{shown.length} {shown.length === 1 ? 'service' : 'services'}</span>
    </div>

    <section class="ui-card">
        <div class="ui-tbl-wrap">
            <table class="ui-tbl">
                <thead>
                    <tr><th>Name</th><th class="c-lg">Runs on</th><th>Status</th><th class="c-sm">CPU</th><th class="c-sm">Memory</th><th class="c-md">Uptime</th><th class="avail c-md">Last 24 hours</th><th class="shrink"></th></tr>
                </thead>
                <tbody>
                    {#each shown as s (s.key)}
                        {@const a = $actions[s.key]}
                        {@const u = up(s)}
                        <tr class="click" on:click={() => open(s.id)}>
                            <td>
                                <div class="nm-cell">
                                    <span class="ic {s.kind}">{#if s.kind === 'daemon'}<Cpu size={14} />{:else}<Box size={14} />{/if}</span>
                                    <div class="nm-text">
                                        <span class="nm">{s.name}</span>
                                        <span class="sub">{s.kind === 'daemon' ? `Daemon${s.type ? ' · ' + s.type : ''}` : (s.image || 'container')}</span>
                                    </div>
                                </div>
                            </td>
                            <td class="c-lg">
                                {#if s.kind === 'daemon'}<span class="host">Mac</span>
                                {:else}<a class="host link" href={href.machine(s.host, 'workloads')} on:click|stopPropagation>{s.host}</a>{/if}
                            </td>
                            <td>
                                {#if a?.state === 'running'}<StatusPill state="starting" label={BUSY_LABEL[a.act]} />
                                {:else if a?.state === 'error'}<StatusPill state="error" label="Failed" />
                                {:else if s.health === 'unhealthy'}<StatusPill state="error" label="Unhealthy" />
                                {:else}<StatusPill state={s.status === 'running' ? 'running' : 'stopped'} />{/if}
                            </td>
                            <td class="num c-sm">{s.status === 'running' ? s.cpu.toFixed(1) + '%' : '—'}</td>
                            <td class="num c-sm">{s.status === 'running' ? fmtMb(s.mem_mb) : '—'}</td>
                            <td class="num c-md">{s.startedAt ? fmtUptime(now - s.startedAt) : '—'}</td>
                            <td class="c-md">
                                <div class="avail-cell">
                                    <UptimeStrip slots={u?.slots || []} bucketSeconds={$uptime.bucket_seconds} />
                                    <span class="pct" class:meh={u?.pct != null && u.pct < 99}>{fmtPct(u?.pct)}</span>
                                </div>
                            </td>
                            <td on:click|stopPropagation role="presentation">
                                {#if a?.state === 'running'}<span class="spin"><Loader2 size={15} class="ui-spin" /></span>
                                {:else}<div class="acts"><WebLinkButton svc={s} /><ActionMenu items={menu(s, $webLinks)} label="Actions for {s.name}" /></div>{/if}
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
            {#if !shown.length}<div class="ui-empty">{list.length ? 'No services match.' : 'No services found.'}</div>{/if}
        </div>
    </section>
</div>

<style>
    .summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
    .nm-cell { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .ic { width: 30px; height: 30px; border-radius: 7px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; background: var(--highlight-10); color: var(--text-secondary); }
    .nm-text { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .nm { font-weight: 600; color: var(--accent); }
    tr.click:hover .nm { text-decoration: underline; }
    .sub { font-size: 12px; color: var(--text-secondary); max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
    .host { font-size: 13px; color: var(--text-primary); text-decoration: none; }
    .host.link:hover { color: var(--accent); text-decoration: underline; }
    .num { font-variant-numeric: tabular-nums; }
    th.avail { width: 26%; }
    .avail-cell { min-width: 140px; }
    .avail-cell { display: flex; align-items: center; gap: 10px; min-width: 160px; }
    .pct { font-size: 12.5px; color: var(--text-secondary); font-variant-numeric: tabular-nums; width: 52px; text-align: right; flex-shrink: 0; }
    .pct.meh { color: var(--amber); }
    .acts { display: flex; align-items: center; justify-content: flex-end; gap: 2px; }
    .spin { display: inline-flex; width: 32px; justify-content: center; color: var(--text-secondary); }
    @media (max-width: 640px) {
        .ic { display: none; }
        .sub { max-width: 150px; }
        .nm-text { max-width: 170px; }
        .summary { grid-template-columns: 1fr 1fr; }
        .summary > :first-child { grid-column: 1 / -1; }
    }
</style>
