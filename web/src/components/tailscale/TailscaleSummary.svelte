<script>
    import { SN } from '../../lib/server.js';
    // The four tiles over every Tailscale tab (same layout as the Infrastructure page's).
    import { Info } from 'lucide-svelte';
    import { infoPop } from '../../lib/infoPop.js';
    import { isShared, displayName, fmtBytes, fmtDate } from '../../lib/tailscale.js';
    import CopyText from '../ui/CopyText.svelte';

    export let net;
    export let now = Date.now();

    // Arrakis is the server everything here is seen from, so it gets a tile, not a card
    $: server = net.devices.find(d => d.self) || net.self;
    $: peers = net.devices.filter(d => !d.self);
    $: online = peers.filter(d => d.online);
    $: active = online.filter(d => d.state === 'active').length;
    // only devices in use have a path; an idle one has no open session to be direct or relayed
    $: direct = online.filter(d => d.connection === 'direct').length;
    $: relayed = online.filter(d => d.connection === 'relay').length;
    $: rx = peers.reduce((a, d) => a + d.rx_bytes, 0);
    $: tx = peers.reduce((a, d) => a + d.tx_bytes, 0);
    $: keyDays = server.key_expiry ? Math.round((new Date(server.key_expiry) - now) / 86400000) : null;
    const total = (d) => d.rx_bytes + d.tx_bytes;
    const nameOf = (d) => isShared(d) ? (d.user || 'Shared user') : displayName(d);
    // each bar gets one theme colour of its own, one shade per part
    const ONLINE = 'var(--metric-cpu)', CONN = 'var(--metric-mem)', NET = 'var(--metric-net)';
    const SEG = [1, 0.7, 0.5];
    // traffic split by device, busiest first, the rest lumped together
    $: busiest = peers.filter(total).sort((a, b) => total(b) - total(a));
    $: trafficSegs = [...busiest.slice(0, 3).map((d, i) => ({ name: nameOf(d), bytes: total(d), shade: SEG[i] })), ...(busiest.length > 3 ? [{ name: 'others', bytes: busiest.slice(3).reduce((a, d) => a + total(d), 0), shade: 0.3 }] : [])];
</script>

<div class="ui-summary">
    <div class="ui-stat">
        <span class="ui-stat-label">Online</span>
        <span class="ui-stat-value">{online.length}<small>of {peers.length}</small></span>
        <div class="ui-segbar"><i style="width: {active / Math.max(1, peers.length) * 100}%; background: {ONLINE}"></i><i style="width: {(online.length - active) / Math.max(1, peers.length) * 100}%; background: {ONLINE}; opacity: 0.4"></i></div>
        <span class="ui-stat-sub ui-legend"><span><b style="background: {ONLINE}"></b>{active} in use</span><span><b style="background: {ONLINE}; opacity: 0.4"></b>{online.length - active} idle</span></span>
    </div>
    <div class="ui-stat">
        <span class="ui-stat-label" title="Counted since Tailscale last started on {SN}">Traffic</span>
        <span class="ui-stat-value">{fmtBytes(rx + tx)}<small>↓{fmtBytes(rx)} ↑{fmtBytes(tx)}</small></span>
        <div class="ui-segbar">{#each trafficSegs as x}<i style="width: {x.bytes / Math.max(1, rx + tx) * 100}%; background: {NET}; opacity: {x.shade}"></i>{/each}</div>
        <span class="ui-stat-sub ui-legend">{#each trafficSegs as x}<span><b style="background: {NET}; opacity: {x.shade}"></b>{x.name} {fmtBytes(x.bytes)}</span>{:else}Since Tailscale started{/each}</span>
    </div>
    <div class="ui-stat">
        <span class="ui-stat-label">Connections
            <button type="button" class="info" use:infoPop aria-label="About connections"><Info size={12} /><span class="info-pop" role="tooltip"><b>Direct</b>: {SN} and the device talk peer to peer, the fastest path.<br /><b>Relayed</b>: traffic goes through a Tailscale relay server because no direct path was found. It works, just slower.</span></button>
        </span>
        <span class="ui-stat-value">{direct}<small>direct · {relayed} relayed</small></span>
        <div class="ui-segbar"><i style="width: {direct / Math.max(1, active) * 100}%; background: {CONN}"></i><i style="width: {relayed / Math.max(1, active) * 100}%; background: {CONN}; opacity: 0.4"></i></div>
        <span class="ui-stat-sub">of the {active} {active === 1 ? 'device' : 'devices'} in use{#if server.relay}{' · '}nearest relay {server.relay}{/if}</span>
    </div>
    <div class="ui-stat">
        <span class="ui-stat-label">{SN}</span>
        <span class="ui-stat-value ip"><CopyText text={server.ip} /></span>
        <span class="ui-stat-sub" title={fmtDate(server.key_expiry)}>Key {server.key_expiry ? (keyDays > 0 ? `expires in ${keyDays} days` : 'expired') : 'never expires'}{server.exit_node_option ? ' · exit node' : ''}</span>
    </div>
</div>


<style>
    .ip :global(code) { font-size: 17px; white-space: nowrap; }
    @media (max-width: 560px) { .ip :global(code) { font-size: 14px; } }
    /* the traffic split wraps under the total instead of running out of the tile */
    .ui-summary .ui-stat-value { white-space: normal; }
    .ui-summary .ui-stat-value small { white-space: nowrap; }
    .info { position: relative; display: inline-flex; vertical-align: -1px; margin-left: 3px; color: var(--text-secondary); opacity: 0.6; cursor: help; }
    .info:hover, .info:focus-visible { opacity: 1; }
    .info-pop { position: absolute; left: calc(-10px + var(--dx, 0px)); max-width: calc(100vw - 24px); top: calc(100% + 8px); width: 280px; padding: 8px 10px; border-radius: 6px; background: var(--text-primary); color: var(--surface); font-size: 12px; font-weight: 400; line-height: 1.45; text-align: left; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18); display: none; z-index: 5; }
    .info:hover .info-pop, .info:focus-visible .info-pop, :global(.info.open) .info-pop { display: block; animation: info-in .15s ease; }
    @keyframes info-in { from { opacity: 0; transform: translateY(-4px); } }
</style>
