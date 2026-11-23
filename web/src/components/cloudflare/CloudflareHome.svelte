<script>
    import { Search, Globe, ExternalLink, Copy, Cable, Info, Trash2, Cloud, CloudOff } from 'lucide-svelte';
    import { copyText } from '../../lib/clipboard.js';
    import { infoPop } from '../../lib/infoPop.js';
    import { ago, fmtDate } from '../../lib/tailscale.js';
    import { machineHref, colos, upSince, STATUS, KEEP, isActive, tunnelKey, fetchCloudflare } from '../../lib/cloudflare.js';
    import Tabs from '../ui/Tabs.svelte';
    import StatusPill from '../ui/StatusPill.svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';
    import Modal from '../ui/Modal.svelte';

    export let cf;
    export let view = 'tunnels';        // from the route: tunnels | dns
    export let filter = 'all';          // tunnels: all | active | inactive | deleted
    export let onNavigate = () => {};
    export let now = Date.now();

    $: z = cf.zone;
    $: live = cf.tunnels.filter(KEEP.all);
    $: records = cf.records;
    $: active = live.filter(isActive).length;
    $: conns = live.reduce((a, t) => a + t.connections.length, 0);
    $: edges = [...new Set(live.flatMap(colos))].sort();
    $: proxied = records.filter(r => r.proxied).length;
    $: byType = Object.entries(records.reduce((a, r) => (a[r.type] = (a[r.type] || 0) + 1, a), {})).sort((a, b) => b[1] - a[1]);
    $: dashZone = `https://dash.cloudflare.com/${z.account_id}/${z.name}`;
    const dashTunnels = (acct) => `https://one.dash.cloudflare.com/${acct}/networks/tunnels`;

    // ---- tunnels -----------------------------------------------------------------------
    const FILTERS = [
        { id: 'all', label: 'All' },
        { id: 'active', label: 'Active' },
        { id: 'inactive', label: 'Inactive' },
        { id: 'deleted', label: 'Deleted' },
    ];
    $: counts = Object.fromEntries(FILTERS.map(f => [f.id, cf.tunnels.filter(KEEP[f.id]).length]));
    $: shown = cf.tunnels.filter(KEEP[filter] || KEEP.all);
    const setFilter = (f) => onNavigate('Cloudflare', f === 'all' ? null : 'f-' + f);
    const statusOf = (t) => t.deleted ? { state: 'stopped', label: 'Deleted' } : STATUS[t.status] || { state: '', label: t.status };

    // ---- DNS -----------------------------------------------------------------------------
    let q = '';
    let type = 'all';
    $: types = ['all', ...byType.map(([t]) => t)];
    $: shownRecords = records.filter(r => (type === 'all' || r.type === type) &&
        (!q || [r.name, r.content, r.comment, r.tunnel].some(v => v && v.toLowerCase().includes(q.toLowerCase()))));
    const ttl = (s) => !s || s === 1 ? 'Auto' : s % 3600 === 0 ? `${s / 3600} h` : s % 60 === 0 ? `${s / 60} min` : `${s} s`;

    // ---- actions -----------------------------------------------------------------------
    const copy = (t) => copyText(t).then(() => window.showToast?.('Copied ' + t), () => {});
    const open = (t) => onNavigate('Cloudflare', tunnelKey(t));
    let doomed = null, deleting = false, delErr = '';
    async function del() {
        deleting = true; delErr = '';
        try {
            const j = await fetch(`/api/cloudflare/tunnels/${doomed.id}`, { method: 'DELETE' }).then(r => r.json());
            if (j.status !== 'success') { delErr = j.message; deleting = false; return; }
            window.showToast?.(`Deleted ${doomed.name}`);
            doomed = null;
            await fetchCloudflare();
        } catch (e) { delErr = 'Could not reach the backend'; }
        deleting = false;
    }
    $: doomedDns = doomed ? records.filter(r => r.tunnel === doomed.name).map(r => r.name) : [];
    function menu(t) {
        return [
            { label: 'Open', icon: ExternalLink, onClick: () => open(t) },
            t.hostname && !t.deleted ? { label: 'Copy hostname', icon: Copy, onClick: () => copy(t.hostname), divider: true } : null,
            { label: 'Copy tunnel ID', icon: Copy, onClick: () => copy(t.id), divider: !t.hostname || t.deleted },
            { label: 'Cloudflare dashboard', icon: ExternalLink, divider: true, onClick: () => window.open(dashTunnels(z.account_id), '_blank', 'noopener') },
            // a shared machine's tunnel goes away by stopping the share, which also cleans up the machine
            t.deleted ? null : t.machine
                ? { label: 'Stop sharing to delete…', icon: Trash2, danger: true, divider: true, onClick: () => location.hash = machineHref(t) }
                : { label: 'Delete tunnel…', icon: Trash2, danger: true, divider: true, onClick: () => { delErr = ''; doomed = t; } },
        ];
    }
</script>

<div class="ui-page">
    <div class="ui-head">
        <div>
            <h1>Cloudflare</h1>
            <div class="ui-meta"><span>Zone <b class="ui-mono">{z.name}</b></span></div>
        </div>
        <div class="ui-head-actions">
            <a class="ui-btn" href={view === 'dns' ? dashZone + '/dns/records' : dashTunnels(z.account_id)} target="_blank" rel="noopener">Cloudflare dashboard <ExternalLink size={13} /></a>
        </div>
    </div>

    <!-- the zone: everything below lives under it -->
    <section class="ui-card hub">
        <div class="hub-id">
            <span class="hub-ic"><Globe size={18} /></span>
            <div>
                <div class="hub-name">{z.name} {#if z.paused}<StatusPill state="stopped" label="Paused" />{:else if z.status === 'active'}<StatusPill state="running" label="Active" />{:else}<StatusPill state="waiting" label={z.status} />{/if}</div>
                <div class="hub-sub">Shared machines are reached at <span class="ui-mono">&lt;machine&gt;.{z.name}</span>.</div>
            </div>
        </div>
        <dl class="hub-facts">
            <div><dt>Plan</dt><dd>{z.plan || '—'}</dd></div>
            <div><dt>Nameservers</dt><dd class="ns">{#each z.name_servers as n}<span class="ui-mono">{n}</span>{/each}</dd></div>
            <div><dt>Added</dt><dd>{fmtDate(z.created)}</dd></div>
        </dl>
    </section>

    <div class="summary">
        <div class="ui-stat">
            <span class="ui-stat-label">Tunnels</span>
            <span class="ui-stat-value">{active}<small>of {live.length} active</small></span>
            <div class="ui-segbar"><i style="width: {active / Math.max(1, live.length) * 100}%; background: var(--green)"></i><i style="width: {(live.length - active) / Math.max(1, live.length) * 100}%; background: var(--green); opacity: 0.4"></i></div>
            <span class="ui-stat-sub">{live.length - active} inactive · {counts.deleted} recently deleted</span>
        </div>
        <div class="ui-stat">
            <span class="ui-stat-label">Connections
                <button type="button" class="info" use:infoPop aria-label="About connections"><Info size={12} /><span class="info-pop" role="tooltip">Each machine's <b>cloudflared</b> keeps several connections open to nearby Cloudflare data centres, so a share survives one of them going away.</span></button>
            </span>
            <span class="ui-stat-value">{conns}<small>open</small></span>
            <span class="ui-stat-sub">via {edges.length ? edges.join(', ') : '—'}</span>
        </div>
        <div class="ui-stat">
            <span class="ui-stat-label">DNS records</span>
            <span class="ui-stat-value">{records.length}<small>{proxied} proxied</small></span>
            <span class="ui-stat-sub">{byType.map(([t, n]) => `${n} ${t}`).join(' · ') || '—'}</span>
        </div>
    </div>

    <Tabs tabs={[{ id: 'tunnels', label: 'Tunnels' }, { id: 'dns', label: 'DNS records' }]} active={view} onSelect={(id) => onNavigate('Cloudflare', id === 'tunnels' ? null : id)} />

    {#if view === 'dns'}
        <div class="ui-listbar">
            <label class="ui-search"><Search size={14} /><input placeholder="Search name, content or comment" bind:value={q} /></label>
            <div class="ui-seg">
                {#each types as t}<button class:on={type === t} on:click={() => type = t}>{t === 'all' ? 'All' : t} <span class="n">{t === 'all' ? records.length : records.filter(r => r.type === t).length}</span></button>{/each}
            </div>
            <span class="ui-count">{shownRecords.length} {shownRecords.length === 1 ? 'record' : 'records'}</span>
        </div>
        <section class="ui-card">
            <div class="ui-tbl-wrap">
                <table class="ui-tbl dns">
                    <colgroup><col class="w-ty" /><col class="w-nm" /><col /><col class="w-px" /><col class="w-ttl" /></colgroup>
                    <thead><tr><th>Type</th><th>Name</th><th>Content</th><th>Proxy</th><th>TTL</th></tr></thead>
                    <tbody>
                        {#each shownRecords as r (r.id)}
                            <tr title={r.comment || null}>
                                <td class="ty">{r.type}</td>
                                <td class="rn">{r.name}</td>
                                <td class="ct">
                                    {#if r.tunnel}
                                        <button class="tun-link" on:click={() => onNavigate('Cloudflare', r.tunnel)}><Cable size={13} />{r.tunnel}</button>
                                    {:else if r.dangling}
                                        <span class="val">{r.content}</span><span class="ui-tag">No such tunnel</span>
                                    {:else}
                                        <span class="val">{r.content}</span>
                                    {/if}
                                </td>
                                <td>{#if r.proxied}<span class="px on"><Cloud size={14} />Proxied</span>{:else}<span class="px"><CloudOff size={14} />DNS only</span>{/if}</td>
                                <td class="ttl">{ttl(r.ttl)}</td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
                {#if !shownRecords.length}<div class="ui-empty">No records match.</div>{/if}
            </div>
        </section>
    {:else}
        <div class="ui-listbar">
            <div class="ui-seg">
                {#each FILTERS as f}<button class:on={filter === f.id} on:click={() => setFilter(f.id)}>{f.label} <span class="n">{counts[f.id]}</span></button>{/each}
            </div>
            <span class="ui-count">{shown.length} {shown.length === 1 ? 'tunnel' : 'tunnels'}</span>
        </div>
        <section class="ui-card">
            <div class="ui-tbl-wrap">
                <table class="ui-tbl tun">
                    <colgroup><col /><col class="w-st" /><col class="w-cn" /><col class="w-act" /></colgroup>
                    <thead><tr><th>Tunnel</th><th>Status</th><th>Connections</th><th class="shrink"></th></tr></thead>
                    <tbody>
                        {#each shown as t (t.id)}
                            {@const st = statusOf(t)}
                            <tr class="click" class:off={!isActive(t)} on:click={() => open(t)}>
                                <td>
                                    <div class="dev">
                                        <span class="ic" class:on={isActive(t)}><Cable size={15} /></span>
                                        <span class="dev-main">
                                            <span class="nm"><span class="nm-t">{t.name}</span></span>
                                            <small>{#if t.deleted}Created {fmtDate(t.created)}{:else if t.hostname}<span class="ui-mono">{t.hostname}</span>{:else}Not made by the dashboard{/if}{#if t.machine}{' · '}<a class="mlink" href={machineHref(t)} on:click|stopPropagation>{t.machine} machine</a>{/if}</small>
                                        </span>
                                    </div>
                                </td>
                                <td><span class="stp"><StatusPill state={st.state} label={st.label} />
                                    {#if t.deleted}<small>{ago(t.deleted_at, now)}</small>
                                    {:else if t.connections.length && upSince(t)}<small>up {ago(upSince(t), now).replace(' ago', '')}</small>
                                    {:else if t.inactive_at}<small>since {ago(t.inactive_at, now)}</small>{/if}</span></td>
                                <td>{#if t.connections.length}<span class="stp"><b>{t.connections.length}</b><small>{colos(t).join(', ')}</small></span>{:else}<span class="ui-dim">—</span>{/if}</td>
                                <td on:click|stopPropagation role="presentation"><ActionMenu items={menu(t)} label="Actions for {t.name}" /></td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
                {#if !shown.length}<div class="ui-empty">{filter === 'all' ? 'No tunnels yet. Share a machine from its Sharing tab to make one.' : `No ${filter} tunnels.`}</div>{/if}
            </div>
        </section>
    {/if}
</div>

<Modal open={!!doomed} title="Delete {doomed?.name}?" onClose={() => !deleting && (doomed = null)}>
    <p class="mtext">The tunnel is removed from Cloudflare and anything still connected to it is cut off.{#if doomedDns.length} These DNS records point at it and are deleted too: <b class="ui-mono">{doomedDns.join(', ')}</b>.{/if}</p>
    {#if delErr}<p class="mtext err">{delErr}</p>{/if}
    <svelte:fragment slot="footer">
        <button class="ui-btn" on:click={() => doomed = null} disabled={deleting}>Cancel</button>
        <button class="ui-btn danger" on:click={del} disabled={deleting}>{deleting ? 'Deleting…' : 'Delete tunnel'}</button>
    </svelte:fragment>
</Modal>

<style>
    .hub { display: grid; grid-template-columns: minmax(240px, 1fr) 2fr; align-items: stretch; }
    .hub-id { display: flex; align-items: center; gap: 14px; padding: 18px 20px; border-right: 1px solid var(--border); }
    /* same tinted icon as the host and machine cards */
    .hub-ic { width: 38px; height: 38px; border-radius: 9px; background: var(--accent-soft); color: var(--accent); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .hub-name { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; color: var(--text-primary); }
    .hub-sub { font-size: 12.5px; color: var(--text-secondary); margin-top: 3px; line-height: 1.4; }
    .hub-facts { display: grid; grid-template-columns: auto auto auto; margin: 0; }
    .hub-facts > div { padding: 16px 20px; min-width: 0; display: flex; flex-direction: column; justify-content: center; gap: 4px; }
    .hub-facts > div + div { border-left: 1px solid var(--border); }
    .hub-facts dt { font-size: 12px; color: var(--text-secondary); }
    .hub-facts dd { margin: 0; font-size: 13.5px; color: var(--text-primary); min-width: 0; }
    .ns { display: flex; flex-direction: column; gap: 2px; }
    .ns .ui-mono { font-size: 12.5px; }

    .summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .info { position: relative; display: inline-flex; vertical-align: -1px; margin-left: 3px; color: var(--text-secondary); opacity: 0.6; cursor: help; }
    .info:hover, .info:focus-visible { opacity: 1; }
    .info-pop { position: absolute; left: calc(-10px + var(--dx, 0px)); max-width: calc(100vw - 24px); top: calc(100% + 8px); width: 280px; padding: 8px 10px; border-radius: 6px; background: var(--text-primary); color: var(--surface); font-size: 12px; font-weight: 400; line-height: 1.45; text-align: left; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18); display: none; z-index: 5; }
    .info:hover .info-pop, .info:focus-visible .info-pop, :global(.info.open) .info-pop { display: block; }

    /* tunnels */
    .tun, .dns { table-layout: fixed; }
    .tun td, .dns td { overflow: hidden; text-overflow: ellipsis; }
    .tun td:last-child { overflow: visible; }
    .w-st { width: 150px; } .w-cn { width: 200px; } .w-act { width: 52px; }
    .dev { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .ic { width: 32px; height: 32px; border-radius: var(--radius-card, 8px); flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); }
    .ic.on { background: var(--accent-soft); color: var(--accent); }
    .dev-main { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .dev-main small { font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .dev-main small .ui-mono { font-size: 11.5px; }
    .nm { display: flex; align-items: center; gap: 8px; font-weight: 600; color: var(--accent); min-width: 0; }
    .nm-t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    tr.click:hover .nm-t { text-decoration: underline; }
    tr.off .nm { color: var(--text-primary); }
    tr.off .ic { opacity: 0.7; }
    .mlink { color: var(--accent); text-decoration: none; font-weight: 500; }
    .mlink:hover { text-decoration: underline; }
    .stp { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; min-width: 0; }
    .stp b { font-weight: 500; font-variant-numeric: tabular-nums; }
    .stp small { font-size: 11.5px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }

    /* DNS: one line per record, plain text; only the record's value is monospace */
    .w-ty { width: 84px; } .w-nm { width: 32%; } .w-px { width: 120px; } .w-ttl { width: 72px; }
    .dns td { padding-top: 11px; padding-bottom: 11px; white-space: nowrap; }
    .dns tbody tr:hover td { background: var(--highlight-3); }
    .ty { font-weight: 600; font-size: 12.5px; color: var(--text-secondary); }
    .rn { font-weight: 500; }
    .ct { color: var(--text-secondary); }
    .ct .val { font-family: var(--font-mono, ui-monospace, monospace); font-size: 12.5px; }
    .ct :global(.ui-tag) { margin-left: 8px; }
    .tun-link { display: inline-flex; align-items: center; gap: 6px; color: var(--accent); font-size: 13px; font-weight: 500; cursor: pointer; }
    .tun-link:hover { text-decoration: underline; }
    .px { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-secondary); }
    .px.on { color: var(--amber); }
    .ttl { color: var(--text-secondary); font-size: 12.5px; }

    .mtext { margin: 0; font-size: 13.5px; line-height: 1.5; color: var(--text-secondary); }
    .mtext b { color: var(--text-primary); font-weight: 500; }
    .mtext.err { margin-top: 10px; color: var(--red); }

    @media (max-width: 1100px) {
        .hub { grid-template-columns: 1fr; }
        .hub-id { border-right: none; border-bottom: 1px solid var(--border); padding: 14px 20px; }
        .w-ttl { width: 0; } .dns th:nth-child(5), .dns td:nth-child(5) { padding: 0; font-size: 0; }
    }
    @media (max-width: 760px) {
        .summary { grid-template-columns: 1fr 1fr; }
        .summary > :last-child { grid-column: 1 / -1; }
        .w-st { width: 110px; } .w-cn { width: 120px; } .w-act { width: 44px; }
        .w-ty { width: 64px; } .w-nm { width: 40%; } .w-px { width: 40px; }
        .px { font-size: 0; gap: 0; }
        .dns th:nth-child(4) { font-size: 0; padding: 0; }
    }
    @media (max-width: 560px) {
        .hub-facts { grid-template-columns: 1fr; }
        .hub-facts > div { flex-direction: row; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px; }
        .hub-facts > div + div { border-left: none; border-top: 1px solid var(--border); }
        .ns { align-items: flex-end; }
        .ic { display: none; }
        .w-cn { width: 0; } .tun th:nth-child(3), .tun td:nth-child(3) { padding: 0; font-size: 0; }
        .tun td:nth-child(3) * { display: none; }
    }
</style>
