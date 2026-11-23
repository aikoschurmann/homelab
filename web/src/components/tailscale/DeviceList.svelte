<script>
    import { copyText } from '../../lib/clipboard.js';
    import { Search, ExternalLink, Copy, Activity, Server, ChevronDown, ArrowDown, ArrowUp, LayoutGrid, List } from 'lucide-svelte';
    import ResourceCard from '../ui/ResourceCard.svelte';
    import { machines } from '../../lib/stores.js';
    import { hosts, arrakisModel, hostIcon } from '../../lib/hosts.js';
    import { isShared, isTagged, displayName, ownerOf, deviceId, fmtBytes, ago, fmtDate, KEEP, clusterOf, deviceIcon } from '../../lib/tailscale.js';
    import StatusPill from '../ui/StatusPill.svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';

    export let net;
    export let open = () => {};
    export let now = Date.now();

    $: me = net.self.user;
    $: peers = net.devices.filter(d => !d.self);
    // which devices are hosts or machines of the cluster, for their icon and a link to their page
    $: cl = Object.fromEntries(net.devices.map(d => [d.id, clusterOf(d, $hosts, $machines?.machines, $arrakisModel)]));

    export let filter = 'all';        // from the route
    export let setFilter = () => {};
    let q = '';
    let showOffline = false;
    const FILTERS = [
        { id: 'all', label: 'All' },
        { id: 'online', label: 'Online' },
        { id: 'mine', label: 'My devices' },
        { id: 'tagged', label: 'Tagged' },
        { id: 'shared', label: 'Shared' },
    ];
    // online first (active, then idle, busiest first), offline by most recently seen
    const rank = (d) => (d.online ? 0 : 10) + (d.state === 'active' ? 0 : 1);
    $: matched = peers
        .filter(d => KEEP[filter](d) && (!q || [d.name, d.ip, d.os, d.user, d.dns].some(v => v && v.toLowerCase().includes(q.toLowerCase()))))
        .sort((a, b) => rank(a) - rank(b) || (b.rx_bytes + b.tx_bytes) - (a.rx_bytes + a.tx_bytes) || new Date(b.last_seen || 0) - new Date(a.last_seen || 0));
    // offline devices fold away unless asked for, or a search is narrowing the list
    $: offlineCount = matched.filter(d => !d.online).length;
    $: shown = showOffline || q ? matched : matched.filter(d => d.online);
    $: counts = Object.fromEntries(FILTERS.map(f => [f.id, peers.filter(KEEP[f.id]).length]));

    // view: table (default) or cards, remembered per browser
    let view = 'grid';
    try { view = localStorage.getItem('arrakis_tailscale_view') || 'grid'; } catch (e) {}
    function setView(v) { view = v; try { localStorage.setItem('arrakis_tailscale_view', v); } catch (e) {} }
    $: iconOf = (d) => deviceIcon(d, cl[d.id]);
    const total = (d) => d.rx_bytes + d.tx_bytes;
    // the LAN address a direct path uses, when it is one (public and IPv6 endpoints are left out)
    const lanOf = (d) => { const a = d.connection === 'direct' && (d.endpoint || '').replace(/:\d+$/, ''); return /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(a || '') ? a : ''; };
    // traffic bars are each device's share of the busiest one
    $: tmax = Math.max(1, ...peers.map(total));
    $: pathLabel = (d) => d.connection === 'direct' ? 'Direct' : d.connection === 'relay' ? 'Relayed' + (d.relay ? ' · ' + d.relay : '') : '';
    $: subOf = (d) => [cl[d.id] ? (cl[d.id].kind === 'host' ? 'Host' : 'Machine') : '', isShared(d) ? 'their device' : d.os, ownerOf(d, me) !== 'You' && !isShared(d) ? ownerOf(d, me) : ''].filter(Boolean).join(' · ') || '—';
    const NET = 'var(--metric-net)';
    const onKey = (e, d) => { if (e.key === 'Enter' && e.target === e.currentTarget) open(deviceId(d)); };
    const nameOf = (d) => isShared(d) ? (d.user || 'Shared user') : displayName(d);
    const copy = (t) => copyText(t).then(() => window.showToast?.('Copied ' + t), () => {});
    function menu(d) {
        return [
            { label: 'Open', icon: ExternalLink, onClick: () => open(deviceId(d)) },
            d.online ? { label: 'Ping from Arrakis', icon: Activity, onClick: () => open(deviceId(d), 'ping') } : null,
            { label: 'Copy IP', icon: Copy, onClick: () => copy(d.ip), divider: true },
            d.dns && !isShared(d) ? { label: 'Copy DNS name', icon: Copy, onClick: () => copy(d.dns) } : null,
            { label: 'Tailscale admin', icon: ExternalLink, divider: true, onClick: () => window.open(`https://login.tailscale.com/admin/machines/${d.ip}`, '_blank', 'noopener') },
        ];
    }
</script>

<div class="ts-sub">
    <div class="ui-listbar">
        <label class="ui-search"><Search size={14} /><input placeholder="Search name, IP, OS or owner" bind:value={q} /></label>
        <div class="ui-seg">
            {#each FILTERS as f}<button class:on={filter === f.id} on:click={() => setFilter(f.id)}>{f.label} <span class="n">{counts[f.id]}</span></button>{/each}
        </div>
        <span class="ui-count">{shown.length} {shown.length === 1 ? 'device' : 'devices'}</span>
        <div class="ui-seg view" role="group" aria-label="View">
            <button class:on={view === 'grid'} on:click={() => setView('grid')} title="Cards" aria-label="Cards"><LayoutGrid size={14} /></button>
            <button class:on={view === 'table'} on:click={() => setView('table')} title="Table" aria-label="Table"><List size={14} /></button>
        </div>
    </div>

    {#if view === 'grid'}
    <!-- one host-style card per device -->
    <div class="ui-cardgrid">
        {#each shown as d (d.id)}
            {@const c = cl[d.id]}
            <ResourceCard name={nameOf(d)} tag={isShared(d) ? 'Shared' : null} sub={subOf(d)} icon={iconOf(d)} on={d.online} off={!d.online} on:open={() => open(deviceId(d))}
                meters={total(d) ? [
                    { k: 'Received', p: d.rx_bytes / tmax * 100, color: NET, v: fmtBytes(d.rx_bytes) },
                    { k: 'Sent', p: d.tx_bytes / tmax * 100, color: NET, v: fmtBytes(d.tx_bytes) },
                    { k: 'Path', v: pathLabel(d) || 'No open session' },
                ] : d.online ? [
                    { k: 'Traffic', v: 'None since Tailscale started' },
                    { k: 'Path', v: 'No open session' },
                    { k: 'Owner', v: ownerOf(d, me) },
                ] : [
                    { k: 'Last seen', v: d.last_seen ? ago(d.last_seen, now) : '—' },
                    { k: 'Owner', v: ownerOf(d, me) },
                ]}
                chips={[
                    ...(c ? [{ label: c.kind === 'host' ? 'Host page' : 'Machine page', onClick: () => location.hash = c.href }] : []),
                    ...(d.online ? [{ label: 'Ping', onClick: () => open(deviceId(d), 'ping') }] : []),
                ]}
                note={d.online ? '' : 'Offline'}
                lan={lanOf(d)}
                ts={d.ip} tsTitle="Tailscale IP">
                <svelte:fragment slot="status">
                    {#if d.state === 'active'}<StatusPill state="running" label="In use" />{:else if d.state === 'idle'}<StatusPill state="" label="Idle" />{:else}<StatusPill state="stopped" label="Offline" />{/if}
                </svelte:fragment>
            </ResourceCard>
        {/each}
        {#if !matched.length}<div class="ui-card ui-empty">No devices match.</div>{/if}
    </div>
    {#if offlineCount && !q}
        <button class="more-btn boxed" on:click={() => showOffline = !showOffline}>
            {showOffline ? 'Hide' : 'Show'} {offlineCount} offline {offlineCount === 1 ? 'device' : 'devices'}
            <span class="mchev" class:open={showOffline}><ChevronDown size={14} /></span>
        </button>
    {/if}
    {:else}
    <!-- table: address and owner under the name, the path under the status -->
    <section class="ui-card">
        <div class="ui-tbl-wrap">
            <table class="ui-tbl slim">
                <colgroup><col /><col class="w-st" /><col class="w-tr" /><col class="w-act" /></colgroup>
                <thead><tr><th>Device</th><th>Status</th><th>Traffic</th><th class="shrink"></th></tr></thead>
                <tbody>
                    {#each shown as d (d.id)}
                        {@const c = cl[d.id]}
                        <tr class="click" class:off={!d.online} on:click={() => open(deviceId(d))}>
                            <td>
                                <div class="dev">
                                    <span class="ic" class:on={d.online}><svelte:component this={iconOf(d)} size={15} /></span>
                                    <span class="dev-main">
                                        <span class="nm"><span class="nm-t">{nameOf(d)}</span>{#if isShared(d)}<span class="ui-tag">Shared</span>{/if}</span>
                                        <small><span class="ui-mono">{d.ip}</span> · {subOf(d)}{#if c}{' · '}<a class="mlink" href={c.href} on:click|stopPropagation>{c.kind === 'host' ? 'host page' : c.name + ' machine'}</a>{/if}</small>
                                    </span>
                                </div>
                            </td>
                            <td>
                                <!-- status with the connection path under it -->
                                <span class="stp">
                                    {#if d.state === 'active'}<span class="st on">In use</span>
                                    {:else if d.state === 'idle'}<span class="st">Idle</span>
                                    {:else}<span class="ui-dim">{d.last_seen ? 'Seen ' + ago(d.last_seen, now) : 'Offline'}</span>{/if}
                                    {#if d.online && pathLabel(d)}<small class="pth" class:relay={d.connection === 'relay'}>{pathLabel(d)}</small>{/if}
                                </span>
                            </td>
                            <td>
                                {#if total(d)}<span class="tr2" title="{fmtBytes(d.rx_bytes)} received · {fmtBytes(d.tx_bytes)} sent"><b>{fmtBytes(total(d))}</b><small><ArrowDown size={10} />{fmtBytes(d.rx_bytes)} <ArrowUp size={10} />{fmtBytes(d.tx_bytes)}</small></span>{:else}<span class="ui-dim">—</span>{/if}
                            </td>
                            <td on:click|stopPropagation role="presentation"><ActionMenu items={menu(d)} label="Actions for {nameOf(d)}" /></td>
                        </tr>
                    {/each}
                </tbody>
            </table>
            {#if !matched.length}<div class="ui-empty">No devices match.</div>{/if}
        </div>
        {#if offlineCount && !q}
            <button class="more-btn" on:click={() => showOffline = !showOffline}>
                {showOffline ? 'Hide' : 'Show'} {offlineCount} offline {offlineCount === 1 ? 'device' : 'devices'}
                <span class="mchev" class:open={showOffline}><ChevronDown size={14} /></span>
            </button>
        {/if}
    </section>
    {/if}
</div>

<style>

    /* show / hide offline: chevron points down to expand, up to collapse */
    .more-btn { display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%; padding: 12px 20px; border-top: 1px solid var(--border); font-size: 13px; font-weight: 500; color: var(--text-secondary); cursor: pointer; transition: color .12s, background-color .12s; }
    .more-btn:hover { color: var(--text-primary); background: var(--highlight-3); }
    .more-btn.boxed { border: 1px dashed var(--border-strong); border-radius: var(--radius-card, 8px); padding: 11px 20px; }
    .mchev { display: flex; transition: transform .2s cubic-bezier(0.22, 1, 0.36, 1); }
    .mchev.open { transform: rotate(180deg); }

    /* traffic as a total with the split underneath */
    .tr2 { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .tr2 b { font-size: 13.5px; font-weight: 500; color: var(--text-primary); }
    .tr2 small { display: inline-flex; align-items: center; gap: 3px; font-size: 11.5px; color: var(--text-secondary); }
    .tr2 small :global(svg) { opacity: 0.7; }
    .tr2 small :global(svg:nth-of-type(2)) { margin-left: 5px; }

    /* table */
    .slim .dev-main small .ui-mono { font-size: 11.5px; }
    /* fixed widths, so showing the offline rows doesn't reflow the columns */
    .slim { table-layout: fixed; }
    .w-st { width: 150px; } .w-tr { width: 170px; } .w-act { width: 52px; }
    .slim td { overflow: hidden; text-overflow: ellipsis; }
    .slim .dev, .slim .dev-main { min-width: 0; }
    .slim .dev-main small { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .slim .nm { min-width: 0; }
    .slim .nm-t { max-width: none; white-space: nowrap; }
    .slim td:last-child { overflow: visible; }
    .st { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary); white-space: nowrap; }
    .st::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
    .st.on { color: var(--green); }
    .stp { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .pth { font-size: 11.5px; color: var(--text-secondary); padding-left: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .pth.relay { color: var(--amber); }


    .n { font-size: 11.5px; color: var(--text-secondary); margin-left: 3px; font-variant-numeric: tabular-nums; }
    .ui-seg button.on .n { color: var(--accent); }
    .dev { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .ic { width: 32px; height: 32px; border-radius: var(--radius-card, 8px); flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); }
    .ic.on { background: var(--accent-soft); color: var(--accent); }
    .dev-main { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .nm { display: flex; align-items: center; gap: 8px; font-weight: 600; color: var(--accent); min-width: 0; }
    .nm-t { overflow: hidden; text-overflow: ellipsis; max-width: 260px; }
    /* a long name (a shared user's email) truncates; the Shared tag never wraps */
    .nm-t { white-space: nowrap; min-width: 0; }
    .nm :global(.ui-tag) { flex-shrink: 0; white-space: nowrap; }
    tr.click:hover .nm-t { text-decoration: underline; }
    .dev-main small { font-size: 12px; color: var(--text-secondary); }
    .mlink { color: inherit; text-decoration: underline; text-decoration-color: var(--border-strong); text-underline-offset: 2px; }
    .mlink:hover { color: var(--accent); }
    tr.off .nm { color: var(--text-primary); }
    tr.off td { color: var(--text-secondary); }
    tr.off .ic { opacity: 0.7; }

    @media (max-width: 760px) {
        .w-st { width: 120px; } .w-tr { width: 84px; } .w-act { width: 44px; }
        .tr2 small { display: none; }
    }
    /* phone: each row is the name with traffic beside it, status and path underneath */
    @media (max-width: 560px) {
        .slim, .slim tbody { display: block; }
        .slim thead, .slim colgroup { display: none; }
        .slim tr { display: grid; grid-template-columns: minmax(0, 1fr) auto 32px; grid-template-areas: "dev tr act" "st st act"; align-items: center; gap: 4px 12px; padding: 12px 6px 12px 14px; border-bottom: 1px solid var(--border); }
        .slim tr:last-child { border-bottom: none; }
        .slim td, .slim tbody tr:first-child td { display: block; padding: 0 !important; border: none; background: none !important; }
        .slim td:nth-child(1) { grid-area: dev; }
        .slim td:nth-child(2) { grid-area: st; }
        .slim td:nth-child(3) { grid-area: tr; }
        .slim td:nth-child(4) { grid-area: act; }
        .slim tr.off td:nth-child(3) { display: none; }
        .slim .stp { flex-direction: row; align-items: center; gap: 8px; }
        .slim .pth { padding-left: 0; }
        .slim .pth::before { content: '·'; margin-right: 8px; color: var(--text-secondary); }
        .slim tr.click:hover { background: var(--highlight-3); }
        .slim .st, .slim td:nth-child(2) .ui-dim { font-size: 12px; }
    }
    @media (max-width: 640px) {
        .ic { display: none; }
        .nm-t { max-width: 170px; }
        }
</style>
