<script>
    import { onMount } from 'svelte';
    import { Cable, ExternalLink } from 'lucide-svelte';
    import { ago, fmtDate } from '../../lib/tailscale.js';
    import { machineHref, colos, upSince, STATUS } from '../../lib/cloudflare.js';
    import StatusPill from '../ui/StatusPill.svelte';
    import CopyText from '../ui/CopyText.svelte';

    export let t;
    export let zone;
    export let records = [];
    export let now = Date.now();

    $: st = t.deleted ? { state: 'stopped', label: 'Deleted' } : STATUS[t.status] || { state: '', label: t.status };
    $: dns = records.filter(r => r.tunnel === t.name);
    $: versions = [...new Set(t.connections.map(c => c.version).filter(Boolean))];
    $: origins = [...new Set(t.connections.map(c => c.origin_ip).filter(Boolean))];
    $: conns = [...t.connections].sort((a, b) => (a.colo || '').localeCompare(b.colo || '') || (a.opened_at || '').localeCompare(b.opened_at || ''));

    // ingress rules live with Cloudflare for remotely managed tunnels
    let ingress = null, ingressErr = '';
    onMount(async () => {
        if (!t.remote || t.deleted) return;
        try {
            const j = await fetch(`/api/cloudflare/tunnels/${t.id}/config`).then(r => r.json());
            if (j.status === 'success') ingress = j.data.ingress; else ingressErr = j.message;
        } catch (e) { ingressErr = 'Could not reach the backend'; }
    });
</script>

<div class="ui-page">
    <div class="ui-head">
        <div class="id">
            <span class="icon" class:on={t.status === 'healthy'}><Cable size={20} /></span>
            <div>
                <h1>{t.name} <StatusPill state={st.state} label={st.label} /></h1>
                <div class="ui-meta">
                    {#if t.hostname}<span><b class="ui-mono">{t.hostname}</b></span>{/if}
                    {#if t.machine}<span><a class="ui-link" href={machineHref(t)}>{t.machine} machine</a>{#if t.host} on {t.host}{/if}</span>{/if}
                    <span>Created {fmtDate(t.created)}</span>
                    {#if t.deleted}<span>Deleted {ago(t.deleted_at, now)}</span>{/if}
                </div>
            </div>
        </div>
        <div class="ui-head-actions">
            <a class="ui-btn" href="https://one.dash.cloudflare.com/{zone.account_id}/networks/tunnels" target="_blank" rel="noopener">Cloudflare dashboard <ExternalLink size={13} /></a>
        </div>
    </div>

    <section class="ui-card">
        <dl class="facts">
            <div><dt>Tunnel ID</dt><dd><CopyText text={t.id} /></dd></div>
            <div><dt>Connector up</dt><dd>{t.deleted ? '—' : upSince(t) ? ago(upSince(t), now).replace(' ago', '') : t.inactive_at ? 'Down since ' + ago(t.inactive_at, now) : '—'}</dd></div>
            <div><dt>cloudflared</dt><dd>{versions.join(', ') || '—'}</dd></div>
            <div><dt>Connects from</dt><dd>{#if origins.length}{#each origins as ip}<span class="ui-mono">{ip}</span>{/each}{:else}—{/if}</dd></div>
            <div><dt>Managed</dt><dd>{t.deleted ? '—' : t.remote ? 'By Cloudflare (token)' : 'Locally (config file)'}</dd></div>
            {#if t.machine}<div><dt>People with access</dt><dd>{t.people} {t.people === 1 ? 'key' : 'keys'}</dd></div>{/if}
        </dl>
    </section>

    <section class="ui-card">
        <div class="ui-card-head">
            <div>
                <h2 class="ui-card-title">Connections</h2>
                <p class="ui-card-desc">Open links from the connector to Cloudflare's edge{#if conns.length}, through {colos(t).join(', ')}{/if}.</p>
            </div>
        </div>
        <div class="ui-tbl-wrap">
            <table class="ui-tbl">
                <thead><tr><th>Data centre</th><th>Opened</th><th>Version</th><th>Connection ID</th></tr></thead>
                <tbody>
                    {#each conns as c (c.id)}
                        <tr>
                            <td><span class="ui-mono">{(c.colo || '—').toUpperCase()}</span>{#if c.pending_reconnect} <span class="ui-dim">reconnecting</span>{/if}</td>
                            <td title={c.opened_at}>{ago(c.opened_at, now)}</td>
                            <td>{c.version || '—'}</td>
                            <td><span class="ui-mono ui-dim">{c.id?.slice(0, 8)}</span></td>
                        </tr>
                    {/each}
                </tbody>
            </table>
            {#if !conns.length}<div class="ui-empty">{#if t.deleted}The tunnel is deleted; Cloudflare keeps listing it for a while.{:else}No connector is running.{/if}{#if t.machine && !t.deleted} It runs inside {t.machine}, so start the machine.{/if}</div>{/if}
        </div>
    </section>

    <div class="two">
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Routes</h2><p class="ui-card-desc">Which hostname goes to which service in the machine. Checked top to bottom.</p></div></div>
            <div class="ui-tbl-wrap">
                {#if t.deleted}
                    <div class="ui-empty">Removed with the tunnel.</div>
                {:else if !t.remote}
                    <div class="ui-empty">Set in the connector's own config file.</div>
                {:else if ingressErr}
                    <div class="ui-empty">{ingressErr}</div>
                {:else if !ingress}
                    <div class="ui-empty">Loading…</div>
                {:else}
                    <table class="ui-tbl">
                        <thead><tr><th>Hostname</th><th>Service</th></tr></thead>
                        <tbody>
                            {#each ingress as r}
                                <tr><td>{#if r.hostname}<span class="ui-mono">{r.hostname}{r.path}</span>{:else}<span class="ui-dim">Anything else</span>{/if}</td><td><span class="ui-mono">{r.service}</span></td></tr>
                            {/each}
                        </tbody>
                    </table>
                {/if}
            </div>
        </section>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">DNS records</h2><p class="ui-card-desc">Names in {zone.name} that point at this tunnel.</p></div></div>
            <div class="ui-tbl-wrap">
                <table class="ui-tbl">
                    <thead><tr><th>Name</th><th>Type</th><th>Proxy</th></tr></thead>
                    <tbody>
                        {#each dns as r (r.id)}
                            <tr><td><span class="ui-mono">{r.name}</span></td><td>{r.type}</td><td>{r.proxied ? 'Proxied' : 'DNS only'}</td></tr>
                        {/each}
                    </tbody>
                </table>
                {#if !dns.length}<div class="ui-empty">No DNS record points here, so nothing reaches it.</div>{/if}
            </div>
        </section>
    </div>
</div>

<style>
    .id { display: flex; align-items: center; gap: 14px; }
    .icon { width: 44px; height: 44px; border-radius: 10px; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); flex-shrink: 0; }
    .icon.on { background: var(--accent-soft); color: var(--accent); }
    .facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0; }
    .facts > div { padding: 14px 20px; display: flex; flex-direction: column; gap: 4px; min-width: 0; border-top: 1px solid var(--border); }
    .facts > div:nth-child(-n + 3) { border-top: none; }
    .facts > div:not(:nth-child(3n + 1)) { border-left: 1px solid var(--border); }
    .facts dt { font-size: 12px; color: var(--text-secondary); }
    .facts dd { margin: 0; font-size: 13.5px; color: var(--text-primary); min-height: 24px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
    .two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
    .two .ui-card-head { min-height: 82px; box-sizing: border-box; }
    @media (max-width: 900px) {
        .two { grid-template-columns: 1fr; }
        .two .ui-card-head { min-height: 0; }
        .facts { grid-template-columns: 1fr 1fr; }
        .facts > div { border-left: none !important; border-top: 1px solid var(--border) !important; }
        .facts > div:nth-child(-n + 2) { border-top: none !important; }
        .facts > div:nth-child(even) { border-left: 1px solid var(--border) !important; }
    }
    @media (max-width: 560px) {
        .facts { grid-template-columns: 1fr; }
        .facts > div { flex-direction: row; justify-content: space-between; align-items: center; padding: 10px 14px; border-left: none !important; }
        .facts > div:nth-child(2) { border-top: 1px solid var(--border) !important; }
        .facts dd { justify-content: flex-end; }
    }
</style>
