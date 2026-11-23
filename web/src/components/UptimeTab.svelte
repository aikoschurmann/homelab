<script>
    import { onMount } from 'svelte';
    import { Plus, Globe, Loader2, RotateCw, Pencil, Trash2, Search } from 'lucide-svelte';
    import { visible } from '../lib/stores.js';
    import { SN } from '../lib/server.js';
    import StatusPill from './ui/StatusPill.svelte';
    import UptimeStrip from './ui/UptimeStrip.svelte';
    import ActionMenu from './ui/ActionMenu.svelte';
    import Modal from './ui/Modal.svelte';

    // Websites and services fetched on a schedule from this server, with HTTPS certificate expiry.
    // A tab of Network tools (embedded): no page header, Add check sits in the list bar.
    export let embedded = false;
    let data = null, error = '';
    async function load() {
        try {
            const j = await fetch('/api/uptime').then(r => r.json());
            if (j.status === 'success') { data = j.data; error = ''; } else error = j.message;
        } catch (e) { error = 'Could not load the checks'; }
    }
    onMount(() => { load(); const t = setInterval(() => visible() && load(), 15000); return () => clearInterval(t); });

    $: checks = data?.checks || [];
    let q = '', filter = 'all';
    const isDown = (c) => c.status === 'down' || c.status === 'flaky';
    $: shown = checks.filter(c => (filter === 'all' || (filter === 'down') === isDown(c)) &&
        (!q || `${c.name} ${c.url}`.toLowerCase().includes(q.toLowerCase())));
    $: upCount = checks.filter(c => c.status === 'up').length;
    $: downCount = checks.filter(isDown).length;
    $: pcts = checks.map(c => c.history?.pct).filter(v => v != null);
    $: avgPct = pcts.length ? pcts.reduce((a, b) => a + b, 0) / pcts.length : null;
    $: medians = checks.map(c => c.history?.median_ms).filter(v => v != null).sort((a, b) => a - b);
    $: midMs = medians.length ? medians[Math.floor(medians.length / 2)] : null;
    $: certs = checks.filter(c => c.cert?.expires).map(c => ({ c, days: (c.cert.expires * 1000 - Date.now()) / 864e5 })).sort((a, b) => a.days - b.days);
    $: soonest = certs[0];

    const ms = (v) => v == null ? '—' : v < 10 ? v.toFixed(1) + ' ms' : Math.round(v) + ' ms';
    const days = (d) => d < 0 ? 'expired' : d < 1 ? 'today' : `${Math.floor(d)} day${Math.floor(d) === 1 ? '' : 's'}`;
    const pill = (c) => ({ up: ['running', 'Up'], down: ['error', 'Down'], flaky: ['waiting', 'Failing'], pending: ['starting', 'Checking'] })[c.status] || ['stopped', '—'];
    const host = (u) => { try { return new URL(u).host; } catch (e) { return u; } };
    const EVERY = [[30, '30 s'], [60, '1 min'], [300, '5 min']];
    const everyLabel = (s) => (EVERY.find(([v]) => v === s) || [, s + ' s'])[1];

    // ---- add / edit ----
    let open = false, editing = null, form = {}, saving = false, formErr = '';
    function edit(c = null) {
        editing = c; formErr = '';
        form = c ? { name: c.name, url: c.url, every: c.every, expect: c.expect || '' } : { name: '', url: '', every: 60, expect: '' };
        open = true;
    }
    async function save() {
        saving = true; formErr = '';
        try {
            const r = await fetch(editing ? `/api/uptime/${editing.id}` : '/api/uptime', {
                method: editing ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) }).then(r => r.json());
            if (r.status !== 'success') { formErr = r.message || 'Could not save'; return; }
            open = false;
            window.showToast?.(editing ? 'Check saved' : 'Check added');
            await load();
        } catch (e) { formErr = 'Could not save'; }
        finally { saving = false; }
    }
    let running = {};
    async function runNow(c) {
        running = { ...running, [c.id]: true };
        try { await fetch(`/api/uptime/${c.id}/run`, { method: 'POST' }); await load(); }
        finally { running = { ...running, [c.id]: false }; }
    }
    let confirmDel = null;
    async function del(c) {
        await fetch(`/api/uptime/${c.id}`, { method: 'DELETE' });
        confirmDel = null; open = false;
        window.showToast?.(`${c.name} removed`);
        load();
    }
    const menu = (c) => [
        { label: 'Check now', icon: RotateCw, onClick: () => runNow(c) },
        { label: 'Edit', icon: Pencil, onClick: () => edit(c) },
        { label: 'Remove…', icon: Trash2, danger: true, divider: true, onClick: () => confirmDel = c },
    ];
</script>

<div class:ui-page={!embedded} class:inner={embedded}>
    {#if !embedded}
    <div class="ui-head">
        <div><h1>Uptime</h1><p>Websites and services checked from {SN} on a schedule, with HTTPS certificate expiry.</p></div>
        <div class="ui-head-actions"><button class="ui-btn primary" on:click={() => edit()}><Plus size={15} /> Add check</button></div>
    </div>
    {/if}

    {#if !data}
        <div class="ui-dim">{error || 'Loading…'}</div>
    {:else if !checks.length}
        <section class="ui-card empty">
            <span class="empty-ic"><Globe size={22} /></span>
            <h2>No checks yet</h2>
            <p>Add a website or a service's address. The dashboard fetches it every minute, keeps 24 hours of history, warns {data.cert_warn_days} days before an HTTPS certificate expires, and sends an alert when it goes down.</p>
            <button class="ui-btn primary" on:click={() => edit()}><Plus size={15} /> Add check</button>
        </section>
    {:else}
        <div class="ui-stats">
            <div class="ui-stat"><span class="ui-stat-label">Checks</span><span class="ui-stat-value">{checks.length}</span><span class="ui-stat-sub">{upCount} up · {downCount} down</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Uptime</span><span class="ui-stat-value">{avgPct != null ? avgPct.toFixed(2) + '%' : '—'}</span><span class="ui-stat-sub">average, last 24 hours</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Response</span><span class="ui-stat-value">{ms(midMs)}</span><span class="ui-stat-sub">median across checks</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Certificates</span><span class="ui-stat-value">{soonest ? days(soonest.days) : '—'}</span><span class="ui-stat-sub">{soonest ? `until ${host(soonest.c.url)} expires` : 'no HTTPS checks yet'}</span></div>
        </div>

        <div class="ui-listbar">
            <label class="ui-search"><Search size={14} /><input placeholder="Search name or address" bind:value={q} /></label>
            <div class="ui-seg">
                <button class:on={filter === 'all'} on:click={() => filter = 'all'}>All <span class="n">{checks.length}</span></button>
                <button class:on={filter === 'up'} on:click={() => filter = 'up'}>Up <span class="n">{checks.length - downCount}</span></button>
                <button class:on={filter === 'down'} on:click={() => filter = 'down'}>Down <span class="n">{downCount}</span></button>
            </div>
            <span class="ui-count">{shown.length} {shown.length === 1 ? 'check' : 'checks'}</span>
            {#if embedded}<button class="ui-btn primary" on:click={() => edit()}><Plus size={14} /> Add check</button>{/if}
        </div>

        <section class="ui-card">
            <div class="ui-tbl-wrap">
                <table class="ui-tbl">
                    <thead><tr><th>Check</th><th>Status</th><th class="c-md strip-h">Last 24 hours</th><th class="c-sm">Uptime</th><th class="c-sm">Response</th><th class="c-lg">Certificate</th><th class="shrink"></th></tr></thead>
                    <tbody>
                        {#each shown as c (c.id)}
                            {@const [st, lbl] = pill(c)}
                            {@const cd = c.cert?.expires ? (c.cert.expires * 1000 - Date.now()) / 864e5 : null}
                            <tr class="click" on:click={() => edit(c)}>
                                <td class="wrap">
                                    <div class="nm">{c.name}</div>
                                    <div class="sub"><a class="ui-mono url" href={c.url} target="_blank" rel="noopener noreferrer" on:click|stopPropagation>{c.url}</a> · every {everyLabel(c.every)}</div>
                                    {#if c.last && !c.last.ok && c.last.error}<div class="sub err">{c.last.error}</div>{/if}
                                </td>
                                <td>{#if running[c.id]}<StatusPill state="starting" label="Checking" />{:else}<StatusPill state={st} label={lbl} />{/if}</td>
                                <td class="c-md">{#if c.history}<div class="strip"><UptimeStrip slots={c.history.slots} bucketSeconds={data.bucket_seconds} /></div>{:else}<span class="ui-dim">—</span>{/if}</td>
                                <td class="c-sm num">{c.history?.pct != null ? c.history.pct + '%' : '—'}</td>
                                <td class="c-sm num">{c.last?.ok ? ms(c.last.ms) : '—'}{#if c.last?.code}<div class="sub">HTTP {c.last.code}</div>{/if}</td>
                                <td class="c-lg">
                                    {#if c.cert?.error}<span class="err">Invalid</span><div class="sub" title={c.cert.error}>{c.cert.error.slice(0, 40)}</div>
                                    {:else if cd != null}<span class:warn={cd < data.cert_warn_days}>{days(cd)}</span><div class="sub">{c.cert.issuer || ''}</div>
                                    {:else}<span class="ui-dim">{c.url.startsWith('https') ? '—' : 'No HTTPS'}</span>{/if}
                                </td>
                                <td>
                                    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                                    <span on:click|stopPropagation>
                                    {#if confirmDel?.id === c.id}
                                        <span class="ui-btns"><button class="ui-btn sm" on:click={() => confirmDel = null}>Keep</button><button class="ui-btn sm danger" on:click={() => del(c)}>Remove</button></span>
                                    {:else}<ActionMenu items={menu(c)} label="Actions for {c.name}" />{/if}
                                    </span>
                                </td>
                            </tr>
                        {:else}<tr><td colspan="7" class="ui-dim">No checks match.</td></tr>{/each}
                    </tbody>
                </table>
            </div>
        </section>
    {/if}
</div>

<Modal bind:open title={editing ? 'Edit check' : 'Add check'} description="Fetched from {SN}; up when it answers below HTTP 400. A public address goes out through the internet, so the check fails when people outside can't reach it." width={480}>
    <form class="f" on:submit|preventDefault={save}>
        <div class="ui-field">
            <label for="up-url">Address</label>
            <input id="up-url" class="ui-input mono" class:bad={formErr} placeholder="https://example.com" spellcheck="false" autocapitalize="off" bind:value={form.url} />
        </div>
        <div class="ui-field">
            <label for="up-name">Name</label>
            <input id="up-name" class="ui-input" placeholder={host(form.url || '') || 'My website'} bind:value={form.name} />
        </div>
        <div class="ui-field">
            <span class="ui-label">Every</span>
            <div class="ui-seg">{#each EVERY as [v, l]}<button type="button" class:on={form.every === v} on:click={() => form.every = v}>{l}</button>{/each}</div>
        </div>
        <div class="ui-field">
            <label for="up-expect">Page must contain <span class="ui-dim opt">(optional)</span></label>
            <input id="up-expect" class="ui-input" placeholder="e.g. Sign in" bind:value={form.expect} />
            <span class="ui-hint">Catches an error page that still answers 200.</span>
        </div>
        {#if formErr}<p class="err">{formErr}</p>{/if}
        <button type="submit" hidden aria-label="Save"></button>
    </form>
    <svelte:fragment slot="footer">
        {#if editing}<button class="ui-btn danger-outline" style="margin-right: auto" on:click={() => del(editing)}>Remove</button>{/if}
        <button class="ui-btn" on:click={() => open = false}>Cancel</button>
        <button class="ui-btn primary" disabled={saving || !form.url?.trim()} on:click={save}>{#if saving}<Loader2 size={13} class="ui-spin" />{/if}{editing ? 'Save' : 'Add check'}</button>
    </svelte:fragment>
</Modal>

<style>
    .inner { display: flex; flex-direction: column; gap: 20px; }
    .nm { font-weight: 600; color: var(--accent); }
    tr.click:hover .nm { text-decoration: underline; }
    .sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
    .sub.err, .err { color: var(--red); }
    .warn { color: var(--amber); font-weight: 600; }
    .url { color: var(--text-secondary); text-decoration: none; font-size: 12px; }
    .url:hover { color: var(--accent); }
    .num { font-variant-numeric: tabular-nums; }
    .strip { width: 180px; }
    .empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 10px; padding: 40px 24px; }
    .empty h2 { margin: 0; font-size: 16px; }
    .empty p { margin: 0 0 6px; max-width: 520px; font-size: 13.5px; color: var(--text-secondary); line-height: 1.5; }
    .empty-ic { width: 44px; height: 44px; border-radius: 10px; display: flex; align-items: center; justify-content: center; background: var(--accent-soft); color: var(--accent); }
    .f { display: flex; flex-direction: column; gap: 16px; padding-top: 4px; }
    .opt { font-weight: 400; }
    p.err { margin: 0; font-size: 13px; }
</style>
