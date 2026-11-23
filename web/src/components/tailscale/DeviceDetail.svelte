<script>
    import { SN } from '../../lib/server.js';
    import { ExternalLink, Activity, Loader2 } from 'lucide-svelte';
    import { machines } from '../../lib/stores.js';
    import { hosts, arrakisModel } from '../../lib/hosts.js';
    import { isShared, displayName, ownerOf, fmtBytes, ago, fmtDate, clusterOf, deviceIcon } from '../../lib/tailscale.js';
    import StatusPill from '../ui/StatusPill.svelte';
    import CopyText from '../ui/CopyText.svelte';

    export let d;
    export let me;
    export let now = Date.now();
    export let autoPing = false;

    $: c = clusterOf(d, $hosts, $machines?.machines, $arrakisModel);
    $: m = c?.m;
    $: expiresInDays = d.key_expiry ? Math.round((new Date(d.key_expiry) - now) / 86400000) : null;
    $: sshUser = m?.username || 'root';

    // ---- ping ----------------------------------------------------------------------------
    let ping = null, pinging = false, pingErr = '';
    async function runPing() {
        pinging = true; pingErr = '';
        try {
            const j = await fetch(`/api/tailscale/ping/${d.ip}`, { method: 'POST' }).then(r => r.json());
            if (j.status === 'success') ping = j.data; else { ping = null; pingErr = j.message; }
        } catch (e) { pingErr = 'Could not reach the backend'; }
        pinging = false;
    }
    let pinged = false;
    $: if (autoPing && !pinged && d.online && !d.self) { pinged = true; runPing(); }
</script>

<div class="ui-page">
    <div class="ui-head">
        <div class="id">
            <span class="icon" class:on={d.online}><svelte:component this={deviceIcon(d, c)} size={20} /></span>
            <div>
                <h1>{displayName(d)}
                    {#if d.self}<StatusPill state="running" label="Online" />
                    {:else if d.state === 'active'}<StatusPill state="running" label="In use" />
                    {:else if d.state === 'idle'}<StatusPill state="" label="Idle" />
                    {:else}<StatusPill state="stopped" label="Offline" />{/if}
                    {#if d.self}<span class="ui-tag">This server</span>{/if}
                </h1>
                <div class="ui-meta">
                    <span><b class="ui-mono">{d.ip}</b></span>
                    <span>{isShared(d) ? `Shared with ${d.user}` : d.os || 'unknown OS'}</span>
                    {#if c}<span><a class="ui-link" href={c.href}>{c.kind === 'host' ? 'Host page' : `${c.name} machine on ${SN}`}</a></span>{/if}
                    <span>Added {fmtDate(d.created)}</span>
                </div>
            </div>
        </div>
        <div class="ui-head-actions">
            {#if d.online && !d.self}<button class="ui-btn" disabled={pinging} on:click={runPing}>{#if pinging}<Loader2 size={14} class="ui-spin" />{:else}<Activity size={14} />{/if} Ping</button>{/if}
            <a class="ui-btn" href="https://login.tailscale.com/admin/machines/{d.ip}" target="_blank" rel="noopener">Admin console <ExternalLink size={13} /></a>
        </div>
    </div>

    {#if ping || pingErr}
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Ping</h2>
                <p class="ui-card-desc">{#if pingErr}{pingErr}{:else}{ping.path === 'direct' ? 'Reached directly, peer to peer.' : `Relayed through ${ping.via}: no direct path between the two yet.`}{/if}</p></div>
                {#if ping}<span class="big">{ping.best_ms} ms</span>{/if}</div>
            {#if ping}
                <div class="pongs" style="border-top: 1px solid var(--border)">
                    {#each ping.pongs as p, i}<span class="pong"><b>#{i + 1}</b> {p.ms} ms <small>via {p.via.startsWith('DERP') ? p.via : 'direct'}</small></span>{/each}
                </div>
            {/if}
        </section>
    {/if}

    <!-- connection and traffic are measured from Arrakis, so the server's own page leaves them out -->
    <section class="ui-card">
        <dl class="facts">
            {#if !d.self}
            <div><dt>Connection</dt><dd>{d.connection === 'direct' ? 'Direct, peer to peer' : d.connection === 'relay' ? `Relayed through ${d.relay || 'DERP'}` : d.online ? 'Idle, no open session' : 'Not connected'}</dd></div>
            <div><dt title="Counted since Tailscale last started on {SN}">Traffic with {SN}</dt><dd>{#if d.rx_bytes + d.tx_bytes}{fmtBytes(d.rx_bytes + d.tx_bytes)} <span class="ui-dim">{fmtBytes(d.rx_bytes)} from it · {fmtBytes(d.tx_bytes)} to it</span>{:else}—{/if}</dd></div>
            <div><dt>{d.online ? 'Last handshake' : 'Last seen'}</dt><dd>{d.online ? (d.last_handshake ? ago(d.last_handshake, now) : '—') : (d.last_seen ? ago(d.last_seen, now) : '—')}</dd></div>
            {/if}
            <div><dt>Owner</dt><dd>{ownerOf(d, me)}</dd></div>
            <div><dt>Key expires</dt><dd title={d.key_expiry ? fmtDate(d.key_expiry) : 'Tagged device or key expiry off'}>{d.key_expiry ? (expiresInDays > 0 ? `in ${expiresInDays} days` : 'expired') : 'Never'}{#if d.key_expiry}<span class="ui-dim">{fmtDate(d.key_expiry)}</span>{/if}</dd></div>
            <div><dt>Exit node</dt><dd>{d.exit_node ? `In use by ${SN}` : d.exit_node_option ? 'Offered' : 'No'}</dd></div>
        </dl>
    </section>

    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Addresses</h2><p class="ui-card-desc">How to reach it from any device on the tailnet.</p></div></div>
        <dl class="ui-kv" style="border-top: 1px solid var(--border)">
            <dt>IPv4</dt><dd><CopyText text={d.ip} /></dd>
            {#if d.ipv6}<dt>IPv6</dt><dd><CopyText text={d.ipv6} /></dd>{/if}
            {#if d.dns && !isShared(d)}<dt>MagicDNS</dt><dd><CopyText text={d.dns} /></dd>{/if}
            {#if !d.self && !isShared(d) && ['linux', 'macOS'].includes(d.os)}<dt>SSH</dt><dd><CopyText text="ssh {sshUser}@{d.name}" /></dd>{/if}
            {#if d.tags?.length}<dt>Tags</dt><dd>{d.tags.join(', ')}</dd>{/if}
            {#if d.connection === 'direct' && d.endpoint}<dt>Direct endpoint</dt><dd class="ui-mono">{d.endpoint}</dd>{/if}
        </dl>
    </section>
</div>

<style>
    /* same header and facts grid as a Cloudflare tunnel's page */
    .id { display: flex; align-items: center; gap: 14px; min-width: 0; }
    .icon { width: 44px; height: 44px; border-radius: 10px; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); flex-shrink: 0; }
    .icon.on { background: var(--accent-soft); color: var(--accent); }
    .facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0; }
    .facts > div { padding: 14px 20px; display: flex; flex-direction: column; gap: 4px; min-width: 0; border-top: 1px solid var(--border); }
    .facts > div:nth-child(-n + 3) { border-top: none; }
    .facts > div:not(:nth-child(3n + 1)) { border-left: 1px solid var(--border); }
    .facts dt { font-size: 12px; color: var(--text-secondary); }
    .facts dd { margin: 0; font-size: 13.5px; color: var(--text-primary); min-height: 24px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
    .facts dd .ui-dim { font-size: 12.5px; }
    .ui-kv dd.ui-mono { word-break: break-all; }
    .big { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .pongs { display: flex; flex-wrap: wrap; gap: 8px 20px; padding: 12px 20px; font-size: 13px; }
    .pong b { color: var(--text-secondary); font-weight: 500; margin-right: 4px; }
    .pong small { color: var(--text-secondary); margin-left: 4px; }
    @media (max-width: 900px) {
        .facts { grid-template-columns: 1fr 1fr; }
        .facts > div { border-left: none !important; border-top: 1px solid var(--border) !important; }
        .facts > div:nth-child(-n + 2) { border-top: none !important; }
        .facts > div:nth-child(even) { border-left: 1px solid var(--border) !important; }
    }
    @media (max-width: 560px) {
        .facts { grid-template-columns: 1fr; }
        .facts > div { flex-direction: row; justify-content: space-between; align-items: center; padding: 10px 14px; border-left: none !important; }
        .facts > div:nth-child(2) { border-top: 1px solid var(--border) !important; }
        .facts dd { justify-content: flex-end; text-align: right; }
    }
    /* phone: cards inset 14px, so this lines up with the card's header */
    @media (max-width: 768px) { .pongs { padding-left: 14px; padding-right: 14px; } }
</style>
