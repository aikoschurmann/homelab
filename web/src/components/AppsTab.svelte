<script>
    import { onMount } from 'svelte';
    import { Image, KeyRound, House, Activity, FileText, Cloud, RefreshCw, GitBranch, Music, Headphones, ChefHat, Rss, FileStack, Wrench, Box, Search, ExternalLink, RotateCw, Trash2, Download, Apple, Server, Laptop, Loader2 } from 'lucide-svelte';
    import { visible } from '../lib/stores.js';
    import Tabs from './ui/Tabs.svelte';
    import Modal from './ui/Modal.svelte';
    import ActionMenu from './ui/ActionMenu.svelte';
    import StatusPill from './ui/StatusPill.svelte';

    // Routes: #apps (catalogue), #apps/installed
    export let section = null;
    export let onNavigate = () => {};
    $: tab = section === 'installed' ? 'installed' : 'catalog';

    const ICONS = { image: Image, 'key-round': KeyRound, house: House, activity: Activity, 'file-text': FileText, cloud: Cloud, 'refresh-cw': RefreshCw,
                    'git-branch': GitBranch, music: Music, headphones: Headphones, 'chef-hat': ChefHat, rss: Rss, 'file-stack': FileStack, wrench: Wrench };

    let catalog = null, inst = null, error = '';
    async function loadCatalog() {
        try { const j = await fetch('/api/apps/catalog').then(r => r.json()); if (j.status === 'success') catalog = j.data; else error = j.message; } catch (e) { error = 'Could not load'; }
    }
    async function loadInstalled(check = true) {
        try { const j = await fetch(`/api/apps/installed?check=${check ? 1 : 0}`).then(r => r.json()); if (j.status === 'success') inst = j.data; } catch (e) {}
    }
    $: busy = (inst?.jobs || []).some(j => j.state === 'running');
    onMount(() => {
        loadCatalog(); loadInstalled();
        const t = setInterval(() => visible() && !busy && loadInstalled(), 30000);
        return () => clearInterval(t);
    });
    let fast;
    $: { clearInterval(fast); if (busy) fast = setInterval(() => loadInstalled(false), 3000); }

    $: targets = catalog?.targets || [];
    const tName = (id) => targets.find(t => t.id === id)?.name || id;
    let q = '', cat = 'All';
    $: cats = ['All', ...new Set((catalog?.apps || []).map(a => a.category))];
    $: shown = (catalog?.apps || []).filter(a => (cat === 'All' || a.category === cat) && (!q || `${a.name} ${a.desc} ${a.category}`.toLowerCase().includes(q.toLowerCase())));
    $: projects = inst?.projects || [];
    $: where = (id) => projects.filter(p => p.project === id).map(p => tName(p.machine));
    $: installingNow = (id) => (inst?.jobs || []).some(j => j.kind === 'install' && j.app === id && j.state === 'running');
    $: jobFor = (machine, project) => (inst?.jobs || []).filter(j => j.machine === machine && (j.project === project || j.app === project)).at(-1);
    $: updates = projects.filter(p => p.updates).length;
    const portOf = (p) => (p.containers.map(c => c.ports || '').join(',').match(/(?:0\.0\.0\.0|\[::\]):(\d+)->/) || [])[1];
    const openUrl = (machine, port) => machine === 'mac' ? `http://${location.hostname}:${port}`
        : machine.startsWith('host:') ? `http://${targets.find(t => t.id === machine)?.addr || machine.slice(5)}:${port}` : `http://${machine}.orb.local:${port}`;

    // ---- install ----
    let installing = null, form = {}, formErr = '';
    function openInstall(a) {
        installing = a; formErr = '';
        form = { machine: (targets.find(t => t.docker && t.kind === 'machine') || targets[0])?.id, port: a.port };
    }
    async function install() {
        formErr = '';
        const r = await fetch('/api/apps/install', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ app: installing.id, ...form }) }).then(r => r.json());
        if (r.status !== 'success') { formErr = r.message; return; }
        window.showToast?.(`Installing ${installing.name} on ${tName(form.machine)}`);
        installing = null;
        onNavigate('Apps', 'installed');
        loadInstalled(false);
    }
    async function act(p, action) {
        const r = await fetch(`/api/apps/${p.machine}/${p.project}/${action}`, { method: 'POST' }).then(r => r.json());
        if (r.status !== 'success') window.showToast?.(r.message || 'Failed');
        loadInstalled(false);
    }
    let confirmRemove = null;
    const menu = (p) => [
        { label: 'Update', icon: Download, onClick: () => act(p, 'update') },
        { label: 'Restart', icon: RotateCw, onClick: () => act(p, 'restart') },
        { label: 'Remove…', icon: Trash2, danger: true, divider: true, onClick: () => confirmRemove = p },
    ];
    $: chosen = targets.find(t => t.id === form.machine);
</script>

<div class="ui-page">
    <div class="ui-head">
        <div><h1>Apps</h1><p>Install self-hosted apps on this Mac's Docker or in a machine, and keep every Compose app up to date.</p></div>
    </div>

    <Tabs tabs={[{ id: 'catalog', label: 'Catalogue' }, { id: 'installed', label: `Installed${projects.length ? ` (${projects.length})` : ''}` }]} active={tab} onSelect={(id) => onNavigate('Apps', id === 'catalog' ? null : id)} />

    {#if tab === 'catalog'}
        {#if !catalog}
            <div class="ui-dim">{error || 'Loading…'}</div>
        {:else}
            <div class="ui-listbar">
                <label class="ui-search"><Search size={14} /><input placeholder="Search apps" bind:value={q} /></label>
                <div class="ui-seg">{#each cats as c}<button class:on={cat === c} on:click={() => cat = c}>{c}</button>{/each}</div>
                <span class="ui-count">{shown.length} {shown.length === 1 ? 'app' : 'apps'}</span>
            </div>
            <section class="ui-card">
                <div class="ui-tbl-wrap">
                    <table class="ui-tbl">
                        <thead><tr><th>App</th><th class="c-sm">Category</th><th class="c-md">Port</th><th class="act"></th></tr></thead>
                        <tbody>
                            {#each shown as a (a.id)}
                                {@const on = where(a.id)}
                                <tr>
                                    <td class="wrap"><div class="row"><span class="ic"><svelte:component this={ICONS[a.icon] || Box} size={15} /></span><span class="tx"><b>{a.name}</b><small>{a.desc}</small></span></div></td>
                                    <td class="c-sm">{a.category}</td>
                                    <td class="c-md ui-mono">{a.port}</td>
                                    <!-- fixed-width column and button, so "Installing" never widens it -->
                                    <td class="act">
                                        {#if installingNow(a.id)}<button class="ui-btn sm inb" disabled><Loader2 size={13} class="ui-spin" /> Installing</button>
                                        {:else if on.length}<span class="ui-dim on" title="On {on.join(', ')}">On {on.join(', ')}</span>
                                        {:else}<button class="ui-btn sm inb" disabled={!targets.length} on:click={() => openInstall(a)}>Install</button>{/if}
                                    </td>
                                </tr>
                            {:else}<tr><td colspan="4" class="ui-dim">No apps match.</td></tr>{/each}
                        </tbody>
                    </table>
                </div>
            </section>
        {/if}
    {:else}
        {#if !inst}
            <div class="ui-dim">Looking for Compose apps…</div>
        {:else}
            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">Compose apps</h2><p class="ui-card-desc">Every Compose project on {inst.machines.map(tName).join(', ') || 'the running machines'}. {updates ? `${updates} ${updates === 1 ? 'has' : 'have'} a newer image.` : 'Images are checked against their registry every 6 hours.'}</p></div></div>
                <div class="ui-tbl-wrap">
                    <table class="ui-tbl">
                        <thead><tr><th>App</th><th class="c-sm">Runs on</th><th class="c-md">Containers</th><th>Status</th><th class="shrink"></th></tr></thead>
                        <tbody>
                            {#each projects as p (p.machine + p.project)}
                                {@const job = jobFor(p.machine, p.project)}
                                {@const port = portOf(p)}
                                <tr>
                                    <td class="wrap"><div class="row"><span class="ic"><svelte:component this={ICONS[catalog?.apps.find(a => a.id === p.project)?.icon] || Box} size={15} /></span><span class="tx"><b>{p.project}</b><small class="ui-mono">{p.containers.map(c => c.image).join(' · ')}</small></span></div></td>
                                    <td class="c-sm">{tName(p.machine)}</td>
                                    <td class="c-md">{p.running} of {p.containers.length} running</td>
                                    <td>
                                        {#if job?.state === 'running'}<StatusPill state="starting" label={{ update: 'Updating', restart: 'Restarting', remove: 'Removing', install: 'Installing' }[job.kind]} />
                                        {:else if job?.state === 'failed'}<StatusPill state="error" label="Failed" /><div class="sub err">{job.error}</div>
                                        {:else if p.updates}<button class="ui-link" on:click={() => act(p, 'update')}>Update available</button>
                                        {:else if p.running < p.containers.length}<StatusPill state="stopped" label="Not all running" />
                                        {:else}<StatusPill state="running" label="Up to date" />{/if}
                                    </td>
                                    <td>
                                        <span class="ui-btns">
                                            {#if confirmRemove === p}
                                                <button class="ui-btn sm" on:click={() => confirmRemove = null}>Keep</button><button class="ui-btn sm danger" on:click={() => { act(p, 'remove'); confirmRemove = null; }}>Remove</button>
                                            {:else}
                                                {#if port}<a class="ui-btn sm icon" href={openUrl(p.machine, port)} target="_blank" rel="noopener noreferrer" title="Open on :{port}" aria-label="Open {p.project}"><ExternalLink size={13} /></a>{:else}<span class="spacer"></span>{/if}
                                                <ActionMenu items={menu(p)} label="Actions for {p.project}" />
                                            {/if}
                                        </span>
                                    </td>
                                </tr>
                            {/each}
                            {#each (inst.jobs || []).filter(j => j.kind === 'install' && !projects.some(p => p.project === j.app && p.machine === j.machine)) as j (j.id)}
                                <tr>
                                    <td class="wrap"><div class="row"><span class="ic"><Box size={15} /></span><span class="tx"><b>{j.name}</b><small>Port {j.port}</small></span></div></td>
                                    <td class="c-sm">{tName(j.machine)}</td>
                                    <td class="c-md ui-dim">—</td>
                                    <td>{#if j.state === 'running'}<StatusPill state="creating" label={j.step || 'Installing'} />{:else if j.state === 'failed'}<StatusPill state="error" label="Install failed" /><div class="sub err">{j.error}</div>{:else}<StatusPill state="running" label="Installed" />{/if}</td>
                                    <td></td>
                                </tr>
                            {/each}
                            {#if !projects.length && !(inst.jobs || []).length}<tr><td colspan="5" class="ui-dim">No Compose apps yet. Install one from the catalogue.</td></tr>{/if}
                        </tbody>
                    </table>
                </div>
                {#if confirmRemove}<div class="ui-card-foot"><span>Removing {confirmRemove.project} deletes its containers. Its data volumes stay, so installing it again picks up where it left off.</span></div>{/if}
            </section>
        {/if}
    {/if}
</div>

<Modal open={!!installing} onClose={() => installing = null} width={520} title="Install {installing?.name || ''}" description={installing?.desc}>
    {#if installing}
        <div class="f">
            <div class="ui-field">
                <span class="ui-label">Where</span>
                <div class="options">
                    {#each targets as t (t.id)}
                        <button type="button" class="option" class:on={form.machine === t.id} disabled={t.kind === 'host' && !t.docker} on:click={() => form.machine = t.id}>
                            <span class="radio"></span>
                            <span class="o-icon">{#if t.kind === 'mac'}<Apple size={16} />{:else if t.kind === 'host'}<Laptop size={16} />{:else}<Server size={16} />{/if}</span>
                            <span class="o-text"><b>{t.name}</b><small>{t.kind === 'mac' ? 'This Mac, in OrbStack’s Docker' : t.kind === 'host' ? (t.docker ? 'Other computer · through its agent' : `Other computer · ${t.why}`) : t.docker ? 'OrbStack machine · Docker ready' : 'OrbStack machine · installs Docker first'}</small></span>
                        </button>
                    {/each}
                </div>
            </div>
            <div class="ui-field">
                <label for="ap-port">Web port</label>
                <div class="portrow">
                    <input id="ap-port" class="ui-input mono port" type="number" min="1" max="65535" bind:value={form.port} />
                    <span class="ui-hint ui-mono">{openUrl(form.machine || '', form.port).replace('http://', '')}</span>
                </div>
            </div>
            {#if chosen?.id === 'sietch'}<p class="ui-hint">Its data goes in Docker volumes, which sietch’s nightly backup includes.</p>{/if}
            {#if formErr}<p class="err">{formErr}</p>{/if}
        </div>
    {/if}
    <svelte:fragment slot="footer">
        <button class="ui-btn" on:click={() => installing = null}>Cancel</button>
        <button class="ui-btn primary" disabled={!form.machine} on:click={install}>Install</button>
    </svelte:fragment>
</Modal>

<style>
    .row { display: flex; align-items: center; gap: 12px; }
    .ic { width: 30px; height: 30px; border-radius: var(--radius-card, 8px); flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); }
    .tx { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .tx b { font-weight: 600; }
    .tx small { font-size: 12px; color: var(--text-secondary); }
    .sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; white-space: normal; }
    .sub.err, .err { color: var(--red); }
    .spacer { width: 32px; }
    .act { width: 150px; min-width: 150px; max-width: 150px; text-align: right; }
    .inb { width: 104px; justify-content: center; }
    /* same box as the Install button, so its text lines up with the button labels */
    .on { display: inline-block; width: 104px; vertical-align: middle; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .f { display: flex; flex-direction: column; gap: 16px; padding-top: 4px; }
    .options { display: flex; flex-direction: column; gap: 8px; }
    .option { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-card, 8px); background: var(--surface); cursor: pointer; text-align: left; font: inherit; color: inherit; transition: border-color .12s, background .12s; }
    .option:hover:not(:disabled) { border-color: var(--border-strong); }
    .option:disabled { opacity: 0.5; cursor: default; }
    .option.on { border-color: var(--accent); background: var(--accent-soft); box-shadow: inset 0 0 0 1px var(--accent); }
    .radio { width: 16px; height: 16px; border-radius: 50%; border: 1.5px solid var(--border-strong); flex-shrink: 0; box-sizing: border-box; }
    .option.on .radio { border: 5px solid var(--accent-fill); }
    .o-icon { width: 32px; height: 32px; border-radius: 7px; background: var(--highlight-10); color: var(--text-secondary); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .option.on .o-icon { background: var(--surface); color: var(--accent); }
    .o-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .o-text b { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
    .o-text small { font-size: 12px; color: var(--text-secondary); }
    .portrow { display: flex; align-items: center; gap: 12px; }
    .port { width: 110px; }
    p.err, p.ui-hint { margin: 0; font-size: 13px; }
    @media (max-width: 640px) {
        /* the name and text get the width: no icon, two-line descriptions, one-line image list */
        .ic { display: none; }
        td.wrap { width: 100%; max-width: 0; }
        .tx small { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: normal; }
        .tx small.ui-mono { display: block; white-space: nowrap; text-overflow: ellipsis; }
        .act { width: 92px; min-width: 92px; max-width: 92px; }
        .inb, .on { width: 84px; }
    }
</style>
