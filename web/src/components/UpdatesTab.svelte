<script>
    import { onMount } from 'svelte';
    import { RotateCw, Loader2, ChevronRight, ChevronLeft, Search } from 'lucide-svelte';
    import { visible, crumbLabels } from '../lib/stores.js';
    import { updates, fetchUpdates } from '../lib/updates.js';
    import { SN } from '../lib/server.js';

    // Outdated packages on this server (Homebrew), its OrbStack machines and the other hosts.
    // The main page lists the computers; #updates/<id> is one computer's package list.
    export let section = null;
    export let onNavigate = () => {};
    const go = (id) => onNavigate('Updates', id || null);

    let error = '';
    $: data = $updates;
    async function load() {
        try { await fetchUpdates(); error = ''; } catch (e) { error = e.message || 'Could not load updates'; }
    }
    onMount(() => { load(); const t = setInterval(() => visible() && load(), 4000); return () => clearInterval(t); });

    const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }).then(r => r.json());
    async function checkNow() { await post('/api/updates/check', section ? { target: section } : {}); load(); }
    async function apply(t, packages = []) {
        const r = await post(`/api/updates/${encodeURIComponent(t.id)}/apply`, { packages });
        if (r.status !== 'success') { window.showToast?.(r.message || 'Could not start the update'); return; }
        window.showToast?.(t.kind === 'host' ? `Asked ${t.name} to update ${packages.length ? packages.join(', ') : 'everything'}; it reports back when done` : `Updating ${packages.length ? packages.join(', ') : 'everything'} on ${t.name}`);
        load();
    }

    $: targets = data?.targets || [];
    // the top bar names the open computer, not its id
    $: if (targets.length) crumbLabels.update(c => ({ ...c, ...Object.fromEntries(targets.map(x => [x.id, x.name])) }));
    $: jobOf = (t) => (data?.jobs || []).filter(j => j.target === t.id).at(-1);
    $: outdated = targets.filter(t => t.packages?.length);
    $: pending = outdated.reduce((a, t) => a + t.packages.length, 0);
    $: upToDate = targets.filter(t => t.manager && !t.packages?.length && !t.error).length;
    $: lastChecked = Math.max(0, ...targets.map(t => t.checked || 0));
    const ago = (s) => { if (!s) return 'not yet'; const d = Date.now() / 1000 - s; return d < 90 ? 'just now' : d < 5400 ? `${Math.round(d / 60)} min ago` : `${Math.round(d / 3600)} h ago`; };
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
    const MGR = { brew: 'Homebrew', apt: 'apt', apk: 'apk', dnf: 'dnf', pacman: 'pacman' };
    const KIND = { mac: 'This server', machine: 'OrbStack machine', host: 'Other computer' };
    const blocked = (t) => t.kind === 'host' && (!t.online ? `${t.name} is offline` : +(t.agent || 0) < 16 ? 'Update its agent first (⋯ → Update agent on its page)' : t.manager !== 'brew' && t.root === false ? 'Its agent isn’t running as root, so it can’t install packages' : null);
    // one package at a time on another computer needs agent 18
    const onePkg = (t) => t.kind !== 'host' || +(t.agent || 0) >= 18 ? null : 'Updating one package needs a newer agent (⋯ → Update agent on its page)';
    // what the list's Updates column says (plain text; red only for failures)
    function state(t) {
        const job = jobOf(t), n = t.packages?.length || 0;
        if (job?.state === 'running') return { text: 'Updating…', busy: true };
        if (t.checking) return { text: 'Checking…', busy: true };
        if (job?.state === 'failed') return { text: 'Update failed', bad: true };
        if (t.error) return { text: t.error, dim: true };
        if (!t.manager) return { text: t.kind === 'host' ? (+(t.agent || 0) < 16 ? 'Its agent doesn’t report updates yet' : 'No package manager found') : 'Not looked yet', dim: true };
        if (n) return { text: plural(n, 'update'), strong: true };
        return { text: 'Up to date', dim: true };
    }

    $: t = section ? targets.find(x => x.id === section) : null;
    let q = '';
    let qFor = section; $: if (section !== qFor) { qFor = section; q = ''; }
    $: shown = (t?.packages || []).filter(p => !q || p.name.toLowerCase().includes(q.toLowerCase()));
</script>

<div class="ui-page">
    {#if section}
        {#if !data}
            <div class="ui-dim">{error || 'Loading…'}</div>
        {:else if !t}
            <div class="ui-head"><div><h1>{section}</h1><p>No computer with this id. <button class="ui-link" on:click={() => go(null)}>All computers</button></p></div></div>
        {:else}
            {@const job = jobOf(t)}
            {@const why = blocked(t)}
            {@const n = t.packages?.length || 0}
            <div class="ui-head">
                <div>
                    <button class="ui-back" on:click={() => go(null)}><ChevronLeft size={14} /> All computers</button>
                    <h1>{t.name}</h1>
                    <div class="ui-meta">
                        <span>{KIND[t.kind]}</span>
                        {#if t.manager}<span>{MGR[t.manager] || t.manager}</span>{/if}
                        <span>Looked {ago(t.checked)}</span>
                        {#if job?.state === 'failed'}<span class="bad" title={job.output || null}>Update failed{job.error ? `: ${job.error}` : ''}</span>{/if}
                    </div>
                </div>
                <div class="ui-head-actions">
                    {#if t.kind !== 'host'}<button class="ui-btn" disabled={t.checking || data.checking} on:click={checkNow}>{#if t.checking}<Loader2 size={14} class="ui-spin" /> Checking…{:else}<RotateCw size={14} /> Check now{/if}</button>{/if}
                    {#if n}<button class="ui-btn primary allb" disabled={job?.state === 'running' || !!why} title={why || null} on:click={() => apply(t)}>{#if job?.state === 'running'}<Loader2 size={14} class="ui-spin" /> Updating…{:else}Update all{/if}</button>{/if}
                </div>
            </div>

            <section class="ui-card">
                {#if n}
                    <div class="ui-toolbar">
                        <label class="ui-search"><Search size={14} /><input placeholder="Filter packages" bind:value={q} /></label>
                        <span class="ui-count">{q ? `${shown.length} of ${n}` : plural(n, 'package')}{why ? ` · ${why}` : ''}</span>
                    </div>
                    <div class="ui-tbl-wrap">
                        <table class="ui-tbl pk">
                            <colgroup><col /><col class="w-v inst" /><col class="w-v" /><col class="w-a" /></colgroup>
                            <thead><tr><th>Package</th><th class="inst">Installed</th><th>Latest</th><th></th></tr></thead>
                            <tbody>
                                {#each shown as p (p.name)}
                                    <tr>
                                        <td class="trunc" title={p.name}><span class="ui-mono">{p.name}</span>{#if p.cask}<span class="dim"> · app</span>{/if}<div class="sub ui-mono now trunc">{p.current || '—'}</div></td>
                                        <td class="ui-mono dim trunc inst" title={p.current || null}>{p.current || '—'}</td>
                                        <td class="ui-mono trunc" title={p.latest || null}>{p.latest || '?'}</td>
                                        <td class="r">
                                            <!-- same button in every state, so rows never change size -->
                                            <button class="ui-btn sm pkb" disabled={job?.state === 'running' || !!why || !!onePkg(t)} title={why || onePkg(t)} on:click={() => apply(t, [p.name])}>{#if job?.state === 'running' && (!job.packages?.length || job.packages.includes(p.name))}<Loader2 size={13} class="ui-spin" /> Updating{:else}Update{/if}</button>
                                        </td>
                                    </tr>
                                {:else}
                                    <tr><td colspan="4" class="ui-dim">No package matches “{q}”.</td></tr>
                                {/each}
                            </tbody>
                        </table>
                    </div>
                {:else}
                    <div class="ui-empty">{state(t).text === 'Up to date' ? 'Everything is up to date.' : state(t).text}</div>
                {/if}
            </section>
        {/if}
    {:else}
        <div class="ui-head">
            <div><h1>Updates</h1><p>Outdated packages on {SN}, its machines and your other computers, looked up every 30 minutes.</p></div>
            <div class="ui-head-actions"><button class="ui-btn" disabled={data?.checking} on:click={checkNow}>{#if data?.checking}<Loader2 size={14} class="ui-spin" /> Checking…{:else}<RotateCw size={14} /> Check now{/if}</button></div>
        </div>

        {#if !data}
            <div class="ui-dim">{error || 'Loading…'}</div>
        {:else}
            <div class="ui-stats">
                <div class="ui-stat"><span class="ui-stat-label">Updates</span><span class="ui-stat-value">{pending}</span><span class="ui-stat-sub">{outdated.length ? `on ${outdated.map(x => x.name).join(', ')}` : 'nothing to install'}</span></div>
                <div class="ui-stat"><span class="ui-stat-label">Up to date</span><span class="ui-stat-value">{upToDate}<small>of {targets.length}</small></span><span class="ui-stat-sub">computers</span></div>
                <div class="ui-stat"><span class="ui-stat-label">Last looked</span><span class="ui-stat-value">{ago(lastChecked || null)}</span><span class="ui-stat-sub">next in about {Math.max(1, Math.round((lastChecked + 1800 - Date.now() / 1000) / 60))} min</span></div>
            </div>

            <section class="ui-card">
                <div class="ui-tbl-wrap">
                    <table class="ui-tbl cm">
                        <colgroup><col /><col class="w-u" /><col class="w-l lk" /><col class="w-c" /></colgroup>
                        <thead><tr><th>Computer</th><th>Updates</th><th class="lk">Looked</th><th></th></tr></thead>
                        <tbody>
                            {#each targets as x (x.id)}
                                {@const s = state(x)}
                                <tr class="click" on:click={() => go(x.id)}>
                                    <td><div class="strong">{x.name}</div><div class="sub">{KIND[x.kind]}{x.manager ? ` · ${MGR[x.manager] || x.manager}` : ''}</div></td>
                                    <td class:strong={s.strong} class:dim={s.dim} class:bad={s.bad}>{#if s.busy}<Loader2 size={13} class="ui-spin" /> {/if}{s.text}</td>
                                    <td class="lk dim">{ago(x.checked)}</td>
                                    <td class="r dim"><ChevronRight size={15} /></td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </section>
        {/if}
    {/if}
</div>

<style>
    .ui-head h1 { line-height: 1.2; }
    .sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
    .strong { font-weight: 600; color: var(--text-primary); }
    .dim { color: var(--text-secondary); }
    .bad { color: var(--red); }
    .r { text-align: right; }
    table.pk td.trunc, .trunc { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; word-break: normal; }
    .now { display: none; }
    table.cm, table.pk { table-layout: fixed; width: 100%; }
    .w-u { width: 34%; } .w-l { width: 120px; } .w-c { width: 40px; }
    .w-v { width: 22%; } .w-a { width: 120px; }
    td :global(.ui-spin) { vertical-align: -2px; }
    /* fixed widths: "Updating…" with its spinner takes the same room as the idle label */
    .pkb { width: 100px; justify-content: center; }
    .allb { width: 124px; justify-content: center; }
    @media (max-width: 640px) {
        /* Looked goes (column too, so the cells don't shift), and its width goes to the name */
        .lk { display: none; }
        .w-u { width: 36%; } .w-v { width: 30%; } .w-a { width: 116px; }
        table.cm td:first-child { overflow-wrap: normal; }
        .inst { display: none; }
        .now { display: block; }
    }
</style>
