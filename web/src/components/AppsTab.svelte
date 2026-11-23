<script>
    import { onMount } from 'svelte';
    import { Image, KeyRound, House, Activity, FileText, Cloud, RefreshCw, GitBranch, Music, Headphones, ChefHat, Rss, FileStack, Wrench, Box, Search, Loader2, ExternalLink, RotateCw, Trash2, Download } from 'lucide-svelte';
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
        const t = setInterval(() => visible() && loadInstalled(!busy), busy ? 3000 : 30000);
        return () => clearInterval(t);
    });
    let fast;
    $: { clearInterval(fast); if (busy) fast = setInterval(() => loadInstalled(false), 3000); }

    let q = '', cat = 'All';
    $: cats = ['All', ...new Set((catalog?.apps || []).map(a => a.category))];
    $: shown = (catalog?.apps || []).filter(a => (cat === 'All' || a.category === cat) && (!q || `${a.name} ${a.desc} ${a.category}`.toLowerCase().includes(q.toLowerCase())));
    $: projects = inst?.projects || [];
    $: where = (id) => projects.filter(p => p.project === id).map(p => p.machine);
    $: jobFor = (machine, project) => (inst?.jobs || []).filter(j => j.machine === machine && (j.project === project || j.app === project)).at(-1);
    $: updates = projects.reduce((a, p) => a + (p.updates ? 1 : 0), 0);
    const portOf = (p) => (p.containers.map(c => c.ports || '').join(',').match(/(?:0\.0\.0\.0|\[::\]):(\d+)->/) || [])[1];

    // ---- install ----
    let installing = null, form = {}, formErr = '';
    function openInstall(a) { installing = a; formErr = ''; form = { machine: catalog.machines[0], port: a.port }; }
    async function install() {
        formErr = '';
        const r = await fetch('/api/apps/install', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ app: installing.id, ...form }) }).then(r => r.json());
        if (r.status !== 'success') { formErr = r.message; return; }
        window.showToast?.(`Installing ${installing.name} in ${form.machine}; the first start downloads its images`);
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
</script>

<div class="ui-page">
    <div class="ui-head">
        <div><h1>Apps</h1><p>Install self-hosted apps into a machine with one click, and keep every Compose app up to date.</p></div>
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
            {#if !catalog.machines.length}<div class="ui-banner warn">No running machine has Docker. Start one (or install Docker in it) to install apps.</div>{/if}
            <div class="ui-cardgrid">
                {#each shown as a (a.id)}
                    {@const on = where(a.id)}
                    <section class="ui-card app">
                        <div class="ui-card-head">
                            <span class="ic"><svelte:component this={ICONS[a.icon] || Box} size={18} /></span>
                            <div class="tt"><h2 class="ui-card-title">{a.name}</h2><p class="ui-card-desc">{a.desc}</p></div>
                        </div>
                        <div class="ui-card-foot">
                            <span>{a.category} · port {a.port}</span>
                            {#if on.length}<span class="ui-btns"><StatusPill state="running" label="Installed in {on.join(', ')}" /></span>
                            {:else}<span class="ui-btns"><button class="ui-btn sm" disabled={!catalog.machines.length} on:click={() => openInstall(a)}>Install</button></span>{/if}
                        </div>
                    </section>
                {/each}
            </div>
        {/if}
    {:else}
        {#if !inst}
            <div class="ui-dim">Looking in the machines…</div>
        {:else}
            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">Compose apps</h2><p class="ui-card-desc">Every Compose project in {inst.machines.join(', ') || 'the running machines'}. {updates ? `${updates} ${updates === 1 ? 'has' : 'have'} a newer image.` : 'Their images are checked against the registry every 6 hours.'}</p></div></div>
                <div class="ui-tbl-wrap">
                    <table class="ui-tbl">
                        <thead><tr><th>App</th><th class="c-sm">Machine</th><th class="c-md">Containers</th><th>Status</th><th class="shrink"></th></tr></thead>
                        <tbody>
                            {#each projects as p (p.machine + p.project)}
                                {@const job = jobFor(p.machine, p.project)}
                                {@const port = portOf(p)}
                                <tr>
                                    <td><div class="nm">{p.project}</div><div class="sub ui-mono">{p.containers.map(c => c.image).join(' · ')}</div></td>
                                    <td class="c-sm">{p.machine}</td>
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
                                            {#if port}<a class="ui-btn sm icon" href="http://{p.machine}.orb.local:{port}" target="_blank" rel="noopener noreferrer" title="Open on :{port}" aria-label="Open {p.project}"><ExternalLink size={13} /></a>{:else}<span class="spacer"></span>{/if}
                                            {#if confirmRemove === p}
                                                <button class="ui-btn sm" on:click={() => confirmRemove = null}>Keep</button><button class="ui-btn sm danger" on:click={() => { act(p, 'remove'); confirmRemove = null; }}>Remove</button>
                                            {:else}<ActionMenu items={menu(p)} label="Actions for {p.project}" />{/if}
                                        </span>
                                    </td>
                                </tr>
                            {/each}
                            {#each (inst.jobs || []).filter(j => j.kind === 'install' && !projects.some(p => p.project === j.app && p.machine === j.machine)) as j (j.id)}
                                <tr>
                                    <td><div class="nm">{j.app}</div><div class="sub">New, port {j.port}</div></td>
                                    <td class="c-sm">{j.machine}</td>
                                    <td class="c-md ui-dim">—</td>
                                    <td>{#if j.state === 'running'}<StatusPill state="creating" label="Installing" /><div class="sub">Downloading its images…</div>{:else if j.state === 'failed'}<StatusPill state="error" label="Install failed" /><div class="sub err">{j.error}</div>{:else}<StatusPill state="running" label="Installed" />{/if}</td>
                                    <td></td>
                                </tr>
                            {/each}
                            {#if !projects.length && !(inst.jobs || []).length}<tr><td colspan="5" class="ui-dim">No Compose apps yet. Install one from the catalogue.</td></tr>{/if}
                        </tbody>
                    </table>
                </div>
                {#if confirmRemove}<div class="ui-card-foot"><span>Removing {confirmRemove.project} stops and deletes its containers. Its data volumes stay, so installing it again picks up where it left off.</span></div>{/if}
            </section>
        {/if}
    {/if}
</div>

<Modal open={!!installing} onClose={() => installing = null} width={460} title="Install {installing?.name}" description={installing?.desc}>
    {#if installing}
        <div class="f">
            <div class="ui-field">
                <span class="ui-label">Machine</span>
                <div class="ui-seg">{#each catalog.machines as m}<button type="button" class:on={form.machine === m} on:click={() => form.machine = m}>{m}</button>{/each}</div>
            </div>
            <div class="ui-field">
                <label for="ap-port">Web port</label>
                <input id="ap-port" class="ui-input mono port" type="number" min="1" max="65535" bind:value={form.port} />
                <span class="ui-hint">Opens at <span class="ui-mono">http://{form.machine}.orb.local:{form.port}</span>. Its data is kept in Docker volumes{form.machine === 'sietch' ? ', which the nightly backup includes' : ''}.</span>
            </div>
            {#if formErr}<p class="err">{formErr}</p>{/if}
        </div>
    {/if}
    <svelte:fragment slot="footer">
        <button class="ui-btn" on:click={() => installing = null}>Cancel</button>
        <button class="ui-btn primary" on:click={install}>Install</button>
    </svelte:fragment>
</Modal>

<style>
    .app .ui-card-head { justify-content: flex-start; gap: 14px; }
    .app { display: flex; flex-direction: column; }
    .app .ui-card-foot { margin-top: auto; }
    .ic { width: 38px; height: 38px; border-radius: 9px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--accent-soft); color: var(--accent); }
    .tt { min-width: 0; }
    .nm { font-weight: 600; }
    .sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; white-space: normal; }
    .sub.err, .err { color: var(--red); }
    .f { display: flex; flex-direction: column; gap: 16px; padding-top: 4px; }
    .port { width: 120px; }
    .spacer { width: 32px; }
    p.err { margin: 0; font-size: 13px; }
</style>
