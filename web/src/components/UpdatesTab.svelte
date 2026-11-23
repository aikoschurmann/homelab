<script>
    import { onMount } from 'svelte';
    import { RotateCw, Loader2, ChevronDown, ChevronRight } from 'lucide-svelte';
    import { visible } from '../lib/stores.js';
    import { SN } from '../lib/server.js';
    import StatusPill from './ui/StatusPill.svelte';

    // Outdated packages on this server (Homebrew), its OrbStack machines and the other hosts,
    // with an update button per computer and per package.
    let data = null, error = '';
    async function load() {
        try {
            const j = await fetch('/api/updates').then(r => r.json());
            if (j.status === 'success') { data = j.data; error = ''; } else error = j.message;
        } catch (e) { error = 'Could not load updates'; }
    }
    onMount(() => { load(); const t = setInterval(() => visible() && load(), 4000); return () => clearInterval(t); });

    const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }).then(r => r.json());
    async function checkNow() { await post('/api/updates/check'); load(); }
    async function apply(t, packages = []) {
        const r = await post(`/api/updates/${encodeURIComponent(t.id)}/apply`, { packages });
        if (r.status !== 'success') { window.showToast?.(r.message || 'Could not start the update'); return; }
        window.showToast?.(t.kind === 'host' ? `Asked ${t.name} to update; it reports back when done` : `Updating ${packages.length ? packages.join(', ') : 'everything'} on ${t.name}`);
        load();
    }

    $: targets = data?.targets || [];
    $: jobOf = (t) => (data?.jobs || []).filter(j => j.target === t.id).at(-1);
    $: pending = targets.reduce((a, t) => a + (t.packages?.length || 0), 0);
    $: upToDate = targets.filter(t => t.manager && !t.packages?.length).length;
    $: lastChecked = Math.max(0, ...targets.map(t => t.checked || 0));
    const ago = (s) => { if (!s) return 'not yet'; const d = Date.now() / 1000 - s; return d < 90 ? 'just now' : d < 5400 ? `${Math.round(d / 60)} min ago` : `${Math.round(d / 3600)} h ago`; };
    const MGR = { brew: 'Homebrew', apt: 'apt', apk: 'apk', dnf: 'dnf', pacman: 'pacman' };
    const KIND = { mac: 'This server', machine: 'OrbStack machine', host: 'Other computer' };
    const blocked = (t) => t.kind === 'host' && (!t.online ? `${t.name} is offline` : +(t.agent || 0) < 16 ? 'Update its agent first (⋯ → Update agent on its page)' : t.manager !== 'brew' && t.root === false ? 'Its agent isn’t running as root, so it can’t install packages' : null);
    let open = {};

</script>

<div class="ui-page">
    <div class="ui-head">
        <div><h1>Updates</h1><p>Outdated packages on {SN}, its machines and your other computers, looked up every 30 minutes.</p></div>
        <div class="ui-head-actions"><button class="ui-btn" disabled={data?.checking} on:click={checkNow}>{#if data?.checking}<Loader2 size={14} class="ui-spin" /> Checking…{:else}<RotateCw size={14} /> Check now{/if}</button></div>
    </div>

    {#if !data}
        <div class="ui-dim">{error || 'Loading…'}</div>
    {:else}
        <div class="ui-stats">
            <div class="ui-stat"><span class="ui-stat-label">Pending</span><span class="ui-stat-value">{pending}<small>{pending === 1 ? 'package' : 'packages'}</small></span><span class="ui-stat-sub">across {targets.filter(t => t.packages?.length).length} {targets.filter(t => t.packages?.length).length === 1 ? 'computer' : 'computers'}</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Up to date</span><span class="ui-stat-value">{upToDate}<small>of {targets.length}</small></span><span class="ui-stat-sub">computers</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Last looked</span><span class="ui-stat-value">{ago(lastChecked || null)}</span><span class="ui-stat-sub">every 30 minutes</span></div>
        </div>

        <section class="ui-card">
            <div class="ui-tbl-wrap">
                <table class="ui-tbl">
                    <thead><tr><th>Computer</th><th class="c-sm">Packages</th><th>Status</th><th class="c-md">Looked</th><th class="shrink"></th></tr></thead>
                    <tbody>
                        {#each targets as t (t.id)}
                            {@const job = jobOf(t)}
                            {@const why = blocked(t)}
                            {@const n = t.packages?.length || 0}
                            <tr class:click={n} on:click={() => n && (open = { ...open, [t.id]: !open[t.id] })}>
                                <td>
                                    <div class="nm-cell">{#if n}<span class="chev">{#if open[t.id]}<ChevronDown size={14} />{:else}<ChevronRight size={14} />{/if}</span>{/if}<b>{t.name}</b></div>
                                    <div class="sub">{KIND[t.kind]}</div>
                                </td>
                                <td class="c-sm">{t.manager ? MGR[t.manager] || t.manager : '—'}</td>
                                <td>
                                    {#if job?.state === 'running' || t.checking}<StatusPill state="starting" label={job?.state === 'running' ? 'Updating' : 'Checking'} />
                                    {:else if job?.state === 'failed'}<StatusPill state="error" label="Update failed" />{#if job.error}<div class="sub err">{job.error}</div>{/if}
                                    {:else if t.error}<span class="ui-dim">{t.error}</span>
                                    {:else if !t.manager}<span class="ui-dim">{t.kind === 'host' ? (+(t.agent || 0) < 16 ? 'Its agent doesn’t report updates yet' : 'No package manager found') : 'Not looked yet'}</span>
                                    {:else if n}<b>{n} {n === 1 ? 'update' : 'updates'}</b>
                                    {:else}<StatusPill state="running" label="Up to date" />{/if}
                                </td>
                                <td class="c-md ui-dim">{ago(t.checked)}</td>
                                <td>
                                    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                                    <span on:click|stopPropagation>
                                        {#if n}<button class="ui-btn sm" disabled={job?.state === 'running' || !!why} title={why || null} on:click={() => apply(t)}>Update all</button>{/if}
                                    </span>
                                </td>
                            </tr>
                            {#if n && open[t.id]}
                                {#each t.packages as p (p.name)}
                                    <tr class="pkg">
                                        <td class="ui-mono">{p.name}{#if p.cask}<span class="ui-tag">app</span>{/if}</td>
                                        <td class="c-sm ui-mono ui-dim">{p.current || '—'}</td>
                                        <td class="ui-mono">→ {p.latest || '?'}</td>
                                        <td class="c-md"></td>
                                        <td>{#if t.kind !== 'host' && job?.state !== 'running'}<button class="ui-link" on:click={() => apply(t, [p.name])}>Update</button>{/if}</td>
                                    </tr>
                                {/each}
                                {#if why}<tr class="pkg"><td colspan="5" class="ui-dim">{why}</td></tr>{/if}
                            {/if}
                        {/each}
                    </tbody>
                </table>
            </div>
        </section>
    {/if}
</div>

<style>
    .nm-cell { display: flex; align-items: center; gap: 6px; }
    .chev { display: inline-flex; color: var(--text-secondary); margin-left: -4px; }
    .sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
    .sub.err { color: var(--red); white-space: normal; }
    tr.pkg td { background: var(--highlight-3); font-size: 12.5px; padding-top: 8px; padding-bottom: 8px; }
    tr.pkg td:first-child { padding-left: 44px; }
    .ui-tag { margin-left: 8px; }
</style>
