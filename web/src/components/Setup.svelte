<script>
    // First run: a few steps that set up this server. Shown instead of the app until
    // /api/server says setup_done. Name/port/machine are saved at the end; the look, a new
    // machine and the Tailscale key take effect as soon as they're chosen.
    // On a server that's already set up, /?setup is a preview: every step can be walked
    // through, nothing is saved or created, and the look goes back to what it was on exit.
    import { onMount, tick } from 'svelte';
    import { Check, Loader2, Server as ServerIcon, ExternalLink, ArrowLeft, ArrowRight, Box, Plus, RefreshCw } from 'lucide-svelte';
    import { server, saveServer } from '../lib/server.js';
    import { savedTheme, applyTheme, applyAppearance, savedAppearance } from '../lib/theme.js';
    import AppearancePicker from './ui/AppearancePicker.svelte';

    applyTheme(savedTheme());
    applyAppearance(savedAppearance());

    const preview = server.setup_done;
    const before = { theme: savedTheme(), look: savedAppearance() };
    function restoreLook() {
        applyTheme(before.theme);
        applyAppearance(before.look, true);
    }
    function exitPreview() {
        restoreLook();
        location.href = '/';
    }

    const STEPS = [
        { id: 'name', label: 'Name' },
        { id: 'look', label: 'Look' },
        { id: 'machines', label: 'Machines' },
        { id: 'tailscale', label: 'Tailscale' },
        { id: 'done', label: 'Done' },
    ];
    let step = 0;
    let reached = 0;                  // furthest step seen; the progress bar can jump back to it
    let titleEl;
    $: cur = STEPS[step].id;
    $: if (step > reached) reached = step;
    async function go(i) {
        step = Math.max(0, Math.min(i, STEPS.length - 1));
        await tick();
        titleEl?.focus({ preventScroll: true });
        window.scrollTo({ top: 0 });
    }
    const next = () => { if (canNext) { error = ''; go(step + 1); } };
    const back = () => go(step - 1);
    const goTo = (id) => go(STEPS.findIndex(s => s.id === id));

    // ---- name ---------------------------------------------------------------------------
    let name = server.name;
    let port = server.port;
    let showPort = Number(server.port) !== Number(server.port_active);
    $: nameOk = name.trim().length > 0 && name.trim().length <= 40 && !/[<>"/\\]/.test(name);
    $: portOk = Number(port) >= 1024 && Number(port) <= 65535;
    // a port something else already listens on would restart the dashboard into nothing
    let portFree = true, portChecking = false, portTimer;
    $: checkPort(port);
    function checkPort(p) {
        clearTimeout(portTimer);
        portFree = true;
        if (!(Number(p) >= 1024 && Number(p) <= 65535) || Number(p) === Number(server.port_active)) { portChecking = false; return; }
        portChecking = true;
        portTimer = setTimeout(async () => {
            try {
                const j = await fetch(`/api/server/port?port=${Number(p)}`).then(r => r.json());
                if (Number(p) === Number(port)) portFree = j.data?.free !== false;
            } catch {}
            if (Number(p) === Number(port)) portChecking = false;
        }, 350);
    }

    // ---- what's installed: re-read after the user installs something in another window ----
    let rechecking = '';
    async function recheck(what) {
        rechecking = what;
        try {
            const j = await fetch('/api/server', { cache: 'no-store' }).then(r => r.json());
            if (j.status === 'success') {
                server.features = j.data.features;
                server.machines = j.data.machines;
                server.machine_info = j.data.machine_info;
                features = server.features;
                machines = server.machines || [];
                machineInfo = server.machine_info || [];
                if (!vm && machines.length) vm = machines[0];
            }
            if (what === 'tailscale') { ts = null; await loadTs(); }
        } catch {}
        rechecking = '';
    }
    let features = server.features;

    // ---- machines -----------------------------------------------------------------------
    let machines = server.machines || [];
    let machineInfo = server.machine_info || [];
    $: infoOf = (n) => machineInfo.find(m => m.name === n);
    let vm = server.vm_name && machines.includes(server.vm_name) ? server.vm_name : (machines[0] || '');
    let creatingNew = false;          // the create form, when machines already exist
    let images = null;
    let form = { name: 'main', distro: 'ubuntu', version: '', arch: 'arm64' };
    let job = null;                   // {state, message} while a machine is being created
    $: distroDef = images?.distros.find(d => d.distro === form.distro);
    $: if (distroDef && !distroDef.versions.some(v => v.id === form.version)) form.version = distroDef.default || distroDef.versions[0]?.id || '';
    $: fname = form.name.trim();
    $: versionLabel = distroDef?.versions.find(v => v.id === form.version)?.label || form.version;
    $: nameErr = !fname ? '' : !/^[a-z0-9][a-z0-9-]{0,62}$/.test(fname) ? 'Lowercase letters, digits and dashes' : machines.includes(fname) ? 'That name is taken' : '';
    const PRETTY = { alma: 'AlmaLinux', alpine: 'Alpine', arch: 'Arch Linux', centos: 'CentOS Stream', debian: 'Debian', devuan: 'Devuan', fedora: 'Fedora', gentoo: 'Gentoo', kali: 'Kali', nixos: 'NixOS', openeuler: 'openEuler', opensuse: 'openSUSE', oracle: 'Oracle Linux', rocky: 'Rocky Linux', ubuntu: 'Ubuntu', void: 'Void' };
    const pretty = (d) => PRETTY[d] || d;

    async function loadImages() {
        if (images || !features.orbstack) return;
        try {
            const j = await fetch('/api/vms/images').then(r => r.json());
            if (j.status === 'success') { images = j.data; form.arch = images.arches?.[0] || 'arm64'; }
        } catch {}
    }
    $: if (cur === 'machines') loadImages();

    async function createMachine() {
        job = { state: 'creating', message: '' };
        const nm = fname;
        try {
            const r = await fetch('/api/vms', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: nm, distro: form.distro, version: form.version, arch: form.arch, cpu: 0, memory_mib: 0, tailscale: false }) }).then(r => r.json());
            if (r.status !== 'success') { job = { state: 'error', message: r.message }; return; }
        } catch (e) { job = { state: 'error', message: e.message }; return; }
        // orb create takes a minute or two; GET /api/vms reports the job until the machine exists
        for (;;) {
            await new Promise(r => setTimeout(r, 2500));
            try {
                const d = (await fetch('/api/vms').then(r => r.json())).data;
                const j = d.jobs?.[nm];
                if (j?.state === 'error') { job = { state: 'error', message: j.message }; return; }
                if (d.machines?.some(m => m.name === nm)) {
                    machines = d.machines.map(m => m.name);
                    machineInfo = [...machineInfo.filter(m => m.name !== nm), { name: nm, state: 'running', distro: form.distro, version: form.version }];
                    break;
                }
            } catch {}
        }
        vm = nm;
        job = null;
        creatingNew = false;
    }

    // ---- tailscale ----------------------------------------------------------------------
    let ts = null, tsKey = null, tsInput = '', tsSaving = false, tsErr = '';
    async function loadTs() {
        if (ts || !features.tailscale) return;
        try { ts = (await fetch('/api/tailscale').then(r => r.json())).data; } catch { ts = {}; }
        try { tsKey = (await fetch('/api/vms/tailscale/key').then(r => r.json())).data; } catch {}
    }
    $: if (cur === 'tailscale') loadTs();
    // logging in happens in the Tailscale app: keep checking while this step waits for it
    let tsPoll;
    $: {
        clearInterval(tsPoll);
        if (cur === 'tailscale' && features.tailscale && ts && ts.backend_state !== 'Running')
            tsPoll = setInterval(async () => {
                try { const d = (await fetch('/api/tailscale').then(r => r.json())).data; if (d) ts = d; } catch {}
            }, 4000);
    }
    $: tsAddr = ts?.backend_state === 'Running' ? `http://${ts.self?.dns || ts.self?.ip}:${port}` : '';
    async function saveTsKey() {
        tsSaving = true; tsErr = '';
        try {
            const j = await fetch('/api/vms/tailscale/key', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ auth_key: tsInput.trim() }) }).then(r => r.json());
            if (j.status === 'success') { tsInput = ''; tsKey = (await fetch('/api/vms/tailscale/key').then(r => r.json())).data; }
            else tsErr = j.message;
        } catch (e) { tsErr = e.message; }
        tsSaving = false;
    }

    // ---- finish -------------------------------------------------------------------------
    // `hash` opens a page of the dashboard right after (the "Next" shortcuts on the last step)
    let saving = false, error = '', restarting = false, restartNeeded = false;
    async function finish(hash = '') {
        if (preview) { restoreLook(); location.href = '/' + hash; return; }
        saving = true; error = '';
        try {
            const d = await saveServer({ name: name.trim(), port: Number(port), vm_name: vm || '', setup_done: true });
            const target = `${location.protocol}//${location.hostname}:${d.port}/`;
            if (d.restarting) {
                restarting = true;
                // wait for the restarted server (possibly on its new port), then open it
                await new Promise(r => setTimeout(r, 2500));
                for (let i = 0; i < 60; i++) {
                    try { await fetch(target + 'api/server', { mode: 'no-cors', cache: 'no-store' }); break; } catch {}
                    await new Promise(r => setTimeout(r, 1000));
                }
                location.href = target + hash;
            } else if (d.restart_needed) {
                restartNeeded = true;
            } else {
                location.href = '/' + hash;      // drops ?setup, if it was opened that way
            }
        } catch (e) { error = e.message; goTo(/port/i.test(e.message) ? 'name' : 'done'); }
        saving = false;
    }

    const NEXT_UP = [
        { hash: '#hosts', what: 'Add your other computers', where: 'Hosts → Add host' },
        { hash: '#settings/alerts', what: 'Get alerts on Discord or ntfy', where: 'Settings → Alerts' },
        { hash: '#backups/coverage', what: 'Choose what the nightly backup keeps', where: 'Backups' },
    ];

    $: canNext = cur === 'name' ? nameOk && portOk && portFree && !portChecking : cur === 'machines' ? !job : true;
    onMount(() => {
        document.title = (preview ? 'Setup preview · ' : 'Set up · ') + server.name;
        // leaving the preview any other way (closing the tab, back button) also undoes the look
        if (!preview) return () => clearInterval(tsPoll);
        addEventListener('pagehide', restoreLook);
        return () => { removeEventListener('pagehide', restoreLook); clearInterval(tsPoll); };
    });
</script>

<div class="setup">
    <div class="wrap">
        <div class="brand">
            <span class="ic"><ServerIcon size={18} /></span>
            <div><b>{preview ? 'Setup preview' : 'Set up this server'}</b><span class="ui-dim">{preview ? 'Click through freely. Nothing here is saved or created.' : `Step ${step + 1} of ${STEPS.length}`}</span></div>
            {#if preview}<button type="button" class="ui-btn sm exit" on:click={exitPreview}>Exit preview</button>{/if}
        </div>

        <ol class="progress" aria-label="Steps">
            {#each STEPS as s, i}
                <li class:on={i === step} class:done={i !== step && i <= reached}>
                    <button type="button" disabled={i > reached || (i > step && !canNext)} aria-current={i === step ? 'step' : undefined} on:click={() => go(i)}>
                        <span class="num">{#if i !== step && i <= reached}<Check size={12} strokeWidth={3} />{:else}{i + 1}{/if}</span><span class="lbl">{s.label}</span>
                    </button>
                </li>
            {/each}
        </ol>

        <section class="ui-card">
            {#if cur === 'name'}
                <div class="ui-card-head"><div><h1 class="ui-card-title" tabindex="-1" bind:this={titleEl}>Name this server</h1><p class="ui-card-desc">The dashboard runs on this computer and watches it, its machines and the computers you add later. This is what it's called everywhere.</p></div></div>
                <form class="ui-card-body body" on:submit|preventDefault={next}>
                    <label class="field"><span class="ui-label">Name</span>
                        <!-- svelte-ignore a11y-autofocus -->
                        <input class="ui-input big" class:bad={!nameOk && name} bind:value={name} maxlength="40" placeholder="e.g. Arrakis" autofocus />
                        {#if name && !nameOk}<span class="err">Up to 40 characters, without &lt; &gt; " / \</span>
                        {:else if server.hostname && name.trim() !== server.hostname.split('.')[0]}<span class="ui-hint">This computer's network name is <span class="ui-mono">{server.hostname.split('.')[0]}</span>; that stays as it is.</span>{/if}
                    </label>
                    {#if showPort}
                        <label class="field"><span class="ui-label">Port</span>
                            <input class="ui-input port" class:bad={!portOk || !portFree} type="number" min="1024" max="65535" bind:value={port} />
                            {#if !portOk}<span class="err">Between 1024 and 65535</span>
                            {:else if portChecking}<span class="ui-hint ic-hint"><Loader2 size={12} class="ui-spin" /> Checking…</span>
                            {:else if !portFree}<span class="err">Something else on this computer is using port {port}.</span>
                            {:else if Number(port) !== Number(server.port_active)}<span class="ui-hint ic-hint ok-line"><Check size={12} /> Free. The dashboard moves to it when you finish.</span>
                            {:else}<span class="ui-hint">The port the dashboard is on now.</span>{/if}
                        </label>
                    {:else}
                        <p class="ui-hint">Served on port {port}. <button type="button" class="ui-link" on:click={() => showPort = true}>Change port</button></p>
                    {/if}
                    <button type="submit" hidden aria-label="Continue"></button>
                </form>

            {:else if cur === 'look'}
                <div class="ui-card-head"><div><h1 class="ui-card-title" tabindex="-1" bind:this={titleEl}>Pick a look</h1><p class="ui-card-desc">Applies right away and is saved in this browser. Settings → General has the same choices.</p></div></div>
                <AppearancePicker />

            {:else if cur === 'machines'}
                <div class="ui-card-head"><div><h1 class="ui-card-title" tabindex="-1" bind:this={titleEl}>Main machine</h1><p class="ui-card-desc">An OrbStack machine is a small Linux computer on this Mac. The dashboard tracks the containers in your main one and backs them up each night.</p></div></div>
                <div class="ui-card-body body">
                    {#if !features.orbstack}
                        <div class="empty">
                            <Box size={22} />
                            <div><b>OrbStack isn't installed</b><p class="ui-dim">Without it the dashboard still watches this computer, its apps and other hosts. Install it now and check again, or later and pick a main machine under Settings.</p></div>
                            <span class="ui-btns">
                                <a class="ui-btn sm" href="https://orbstack.dev/download" target="_blank" rel="noreferrer">Get OrbStack <ExternalLink size={13} /></a>
                                <button type="button" class="ui-btn sm" disabled={!!rechecking} on:click={() => recheck('orbstack')}><RefreshCw size={13} class={rechecking ? 'ui-spin' : ''} /> Check again</button>
                            </span>
                        </div>
                    {:else if job}
                        <div class="empty">
                            {#if job.state === 'error'}
                                <Box size={22} />
                                <div><b>Couldn't create {fname}</b><p class="err">{job.message || 'orb create failed'}</p></div>
                                <button type="button" class="ui-btn sm" on:click={() => job = null}>Try again</button>
                            {:else}
                                <Loader2 size={20} class="ui-spin" />
                                <div><b>Creating {fname}…</b><p class="ui-dim">{pretty(form.distro)} {versionLabel}. This takes a minute or two; it becomes the main machine when it's ready.</p></div>
                            {/if}
                        </div>
                    {:else if machines.length && !creatingNew}
                        <div class="choices" role="radiogroup">
                            {#each machines as m}
                                <label class="choice" class:on={vm === m}>
                                    <input type="radio" bind:group={vm} value={m} />
                                    <span class="mi"><Box size={15} /></span><b>{m}</b>
                                    {#if m === server.vm_name}<span class="ui-tag">Current</span>{/if}
                                    {#if infoOf(m)}<span class="ui-dim meta">{pretty(infoOf(m).distro)} {infoOf(m).version}{#if infoOf(m).state && infoOf(m).state !== 'running'} · {infoOf(m).state}{/if}</span>{/if}
                                    {#if vm === m}<Check size={15} class="tick" />{/if}
                                </label>
                            {/each}
                            <label class="choice" class:on={!vm}>
                                <input type="radio" bind:group={vm} value="" />
                                <span class="mi"></span><span class="ui-dim">None for now</span>
                                {#if !vm}<Check size={15} class="tick" />{/if}
                            </label>
                        </div>
                        <button type="button" class="ui-link add" on:click={() => creatingNew = true}><Plus size={13} /> Create a new machine</button>
                    {:else}
                        {#if !machines.length}<p class="lead">You don't have any machines yet. Create one now, or skip and do it later from the OrbStack VM page.</p>{/if}
                        <div class="create">
                            <label class="field"><span class="ui-label">Name</span>
                                <input class="ui-input mono" class:bad={nameErr} bind:value={form.name} maxlength="63" />
                                {#if nameErr}<span class="err">{nameErr}</span>{/if}
                            </label>
                            <label class="field"><span class="ui-label">Linux</span>
                                {#if images}
                                    <select class="ui-select" bind:value={form.distro}>{#each images.distros as d}<option value={d.distro}>{pretty(d.distro)}</option>{/each}</select>
                                {:else}<span class="ui-dim"><Loader2 size={13} class="ui-spin" /> Loading…</span>{/if}
                            </label>
                            {#if distroDef}
                                <label class="field"><span class="ui-label">Version</span>
                                    <select class="ui-select" bind:value={form.version}>{#each distroDef.versions as v}<option value={v.id}>{v.label}</option>{/each}</select>
                                </label>
                            {/if}
                        </div>
                        <div class="create-actions">
                            <button type="button" class="ui-btn primary" disabled={preview || !fname || nameErr || !images} on:click={createMachine}>Create machine</button>
                            {#if creatingNew}<button type="button" class="ui-btn" on:click={() => creatingNew = false}>Cancel</button>{/if}
                            <span class="ui-hint">{preview ? 'Not created in the preview.' : "Shares this Mac's CPU and memory; set limits later."}</span>
                        </div>
                    {/if}
                </div>

            {:else if cur === 'tailscale'}
                <div class="ui-card-head"><div><h1 class="ui-card-title" tabindex="-1" bind:this={titleEl}>Tailscale <span class="ui-dim opt">· optional</span></h1><p class="ui-card-desc">Your private network. It lets your phone and laptop open this dashboard from anywhere, and other computers report in to it.</p></div></div>
                <div class="ui-card-body body">
                    {#if !features.tailscale}
                        <div class="empty">
                            <ServerIcon size={22} />
                            <div><b>Tailscale isn't installed</b><p class="ui-dim">Until it is, the dashboard only opens on this computer. You can skip this and set it up any time.</p></div>
                            <span class="ui-btns">
                                <a class="ui-btn sm" href="https://tailscale.com/download" target="_blank" rel="noreferrer">Get Tailscale <ExternalLink size={13} /></a>
                                <button type="button" class="ui-btn sm" disabled={!!rechecking} on:click={() => recheck('tailscale')}><RefreshCw size={13} class={rechecking ? 'ui-spin' : ''} /> Check again</button>
                            </span>
                        </div>
                    {:else if !ts}
                        <p class="ui-dim"><Loader2 size={13} class="ui-spin" /> Checking Tailscale…</p>
                    {:else if ts.backend_state === 'Running'}
                        <div class="status ok"><Check size={15} /><div><b>Connected as {ts.self?.name}</b><span class="ui-dim">Open the dashboard from your devices at <a class="ui-link ui-mono" href={tsAddr} target="_blank" rel="noreferrer">{tsAddr}</a></span></div></div>
                    {:else}
                        <div class="status"><Loader2 size={15} class="ui-spin" /><div><b>Waiting for Tailscale to connect</b><span class="ui-dim">Open the Tailscale app and log in. This updates by itself once it's connected.</span></div></div>
                    {/if}

                    {#if features.tailscale && features.orbstack}
                        <div class="keyrow">
                            <div><div class="ui-label">Auth key for new machines <span class="ui-dim">· optional</span></div>
                                <div class="ui-hint">Lets machines join the tailnet from the dashboard. Make a reusable one at <a class="ui-link" href="https://login.tailscale.com/admin/settings/keys" target="_blank" rel="noreferrer">Tailscale → Settings → Keys</a>.</div></div>
                            {#if tsKey?.set}
                                <p class="ok-line"><Check size={14} /> Saved (…{tsKey.hint})</p>
                            {:else}
                                <div class="inline">
                                    <input class="ui-input mono" type="password" placeholder="tskey-auth-…" autocomplete="off" bind:value={tsInput} />
                                    <button type="button" class="ui-btn" disabled={preview || tsSaving || !tsInput.trim().startsWith('tskey-')} on:click={saveTsKey}>{tsSaving ? 'Saving…' : 'Save'}</button>
                                </div>
                                {#if tsErr}<span class="err">{tsErr}</span>{/if}
                            {/if}
                        </div>
                    {/if}
                </div>

            {:else}
                <div class="ui-card-head"><div><h1 class="ui-card-title" tabindex="-1" bind:this={titleEl}>Ready</h1><p class="ui-card-desc">{preview ? "This is where a new server's setup ends. Nothing was saved." : 'Everything here can be changed later under Settings.'}</p></div></div>
                {#if restarting}
                    <div class="ui-card-body body"><p class="wait"><Loader2 size={14} class="ui-spin" /> Restarting the dashboard{Number(port) !== Number(server.port_active) ? ` on port ${port}` : ''}…</p></div>
                {:else if restartNeeded}
                    <div class="ui-card-body body"><div class="ui-banner">Saved. Restart the dashboard (<span class="ui-mono">./run.sh</span>) for the new port or machine to apply.</div></div>
                {:else}
                    <dl class="summary">
                        <div><dt>Name</dt><dd>{name.trim()}</dd><button type="button" class="ui-link" on:click={() => goTo('name')}>Change</button></div>
                        <div><dt>Address</dt><dd class="ui-mono">http://{location.hostname}:{port}{#if tsAddr}<br />{tsAddr}{/if}</dd><button type="button" class="ui-link" on:click={() => { showPort = true; goTo('name'); }}>Change</button></div>
                        <div><dt>Look</dt><dd>Saved in this browser</dd><button type="button" class="ui-link" on:click={() => goTo('look')}>Change</button></div>
                        <div><dt>Main machine</dt><dd>{vm || (features.orbstack ? 'None yet' : 'No OrbStack')}</dd><button type="button" class="ui-link" on:click={() => goTo('machines')}>Change</button></div>
                        <div><dt>Tailscale</dt><dd>{!features.tailscale ? 'Not installed' : ts?.backend_state === 'Running' ? `Connected as ${ts.self?.name}` : ts ? 'Not connected' : 'Installed'}</dd><button type="button" class="ui-link" on:click={() => goTo('tailscale')}>Change</button></div>
                        <div><dt>Settings folder</dt><dd class="ui-mono">{server.home}</dd><span></span></div>
                    </dl>
                    <div class="ui-card-body next-up">
                        <span class="ui-label">Then, from the dashboard</span>
                        <div class="choices">
                            {#each NEXT_UP as n}
                                <button type="button" class="choice" disabled={saving} on:click={() => finish(n.hash)}>
                                    <span>{n.what}</span><span class="ui-dim where">{n.where}</span><ArrowRight size={14} class="tick" />
                                </button>
                            {/each}
                        </div>
                    </div>
                {/if}
            {/if}

            {#if !restarting && !restartNeeded}
                <div class="ui-card-foot">
                    {#if step > 0}<button type="button" class="ui-btn" on:click={back}><ArrowLeft size={14} /> Back</button>{:else}<span></span>{/if}
                    {#if error}<span class="err">{error}</span>{/if}
                    <span class="ui-btns">
                        {#if cur === 'done' && preview}
                            <button type="button" class="ui-btn primary" on:click={exitPreview}>Exit preview</button>
                        {:else if cur === 'done'}
                            <button type="button" class="ui-btn primary" disabled={saving} on:click={() => finish()}>{#if saving}<Loader2 size={14} class="ui-spin" /> Saving…{:else}Open the dashboard{/if}</button>
                        {:else}
                            {#if (cur === 'machines' && features.orbstack && !machines.length) || (cur === 'tailscale' && features.tailscale && ts && ts.backend_state !== 'Running')}
                                <button type="button" class="ui-btn" disabled={!!job} on:click={next}>Skip for now</button>
                            {:else}
                                <button type="button" class="ui-btn primary" disabled={!canNext} on:click={next}>Continue</button>
                            {/if}
                        {/if}
                    </span>
                </div>
            {/if}
        </section>
    </div>
</div>

<style>
    .setup { min-height: 100vh; display: flex; justify-content: center; padding: 56px 16px 32px; box-sizing: border-box; background: var(--bg); }
    .wrap { width: 100%; max-width: 760px; display: flex; flex-direction: column; gap: 20px; }
    .brand { display: flex; align-items: center; gap: 12px; }
    .brand div { display: flex; flex-direction: column; gap: 1px; font-size: 13px; }
    .brand b { font-size: 15px; font-weight: 600; color: var(--text-primary); }
    .brand .exit { margin-left: auto; }
    .ic { width: 38px; height: 38px; border-radius: 8px; display: grid; place-items: center; background: var(--highlight-3); border: 1px solid var(--border); color: var(--text-secondary); flex: none; }

    /* steps, numbered like Add host */
    .progress { list-style: none; margin: 0; padding: 0; display: flex; gap: 4px; }
    .progress li { flex: 1; min-width: 0; }
    .progress button { width: 100%; display: flex; align-items: center; gap: 8px; padding: 8px 4px 10px; background: none; border: none; border-bottom: 2px solid var(--border); color: var(--text-secondary); font: inherit; font-size: 13px; cursor: pointer; text-align: left; }
    .progress button:disabled { cursor: default; opacity: 0.6; }
    .progress li.on button { border-bottom-color: var(--accent); color: var(--text-primary); font-weight: 500; }
    .progress li.done button { border-bottom-color: var(--green); }
    .num { width: 22px; height: 22px; border-radius: 50%; flex: none; display: flex; align-items: center; justify-content: center; font-size: 11.5px; font-weight: 600; background: var(--highlight-10); color: var(--text-secondary); }
    .progress li.on .num { background: var(--accent); color: var(--surface); }
    .progress li.done .num { background: var(--green); color: var(--surface); }
    .lbl { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    .ui-card-title { font-size: 17px; outline: none; }
    .opt { font-size: 13px; font-weight: 400; }
    /* long steps (Look) keep Back / Continue in reach */
    .ui-card-foot { position: sticky; bottom: 0; z-index: 1; background: var(--surface); box-shadow: inset 0 9999px 0 var(--highlight-3); }
    .ic-hint { display: inline-flex; align-items: center; gap: 5px; }
    .meta { font-size: 12.5px; margin-left: 4px; }
    .empty .ui-btns { display: flex; gap: 6px; flex-wrap: wrap; }
    .body { border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 16px; }
    .field { display: flex; flex-direction: column; gap: 6px; max-width: 420px; }
    .big { height: 40px; font-size: 15px; }
    .port { max-width: 120px; }
    .err { color: var(--red); font-size: 12.5px; }
    .lead { margin: 0; font-size: 13.5px; color: var(--text-secondary); }

    .empty { display: grid; grid-template-columns: 22px 1fr auto; gap: 14px; align-items: start; color: var(--text-secondary); }
    .empty b { color: var(--text-primary); font-size: 14px; font-weight: 600; }
    .empty p { margin: 3px 0 0; font-size: 13px; }
    .empty .ui-btn { display: inline-flex; gap: 6px; align-items: center; }

    .choices { display: grid; gap: 8px; }
    .choice { position: relative; display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-card, 8px); cursor: pointer; font-size: 13.5px; }
    .choice:hover { border-color: var(--border-strong); }
    .choice.on { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
    .choice input { position: absolute; opacity: 0; pointer-events: none; }
    .choice b { font-weight: 500; color: var(--text-primary); }
    .mi { width: 15px; display: flex; color: var(--text-secondary); }
    .choice :global(.tick) { margin-left: auto; color: var(--accent); }
    .add { display: inline-flex; align-items: center; gap: 5px; align-self: flex-start; }

    .create { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .create .field { max-width: none; }
    .create-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

    .status { display: flex; gap: 10px; align-items: flex-start; font-size: 13px; color: var(--text-secondary); }
    .status div { display: flex; flex-direction: column; gap: 2px; min-width: 0; overflow-wrap: anywhere; }
    .status b { color: var(--text-primary); font-weight: 600; font-size: 14px; }
    .status.ok > :global(svg) { color: var(--green); margin-top: 2px; flex: none; }
    .keyrow { display: flex; flex-direction: column; gap: 8px; padding-top: 16px; border-top: 1px solid var(--border); }
    .inline { display: flex; gap: 8px; max-width: 460px; }
    .inline .ui-input { flex: 1; min-width: 0; }
    .ok-line { margin: 0; display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--green); }
    .wait { margin: 0; display: flex; align-items: center; gap: 8px; font-size: 13.5px; }

    .summary { margin: 0; border-top: 1px solid var(--border); }
    .summary div { display: grid; grid-template-columns: 160px 1fr auto; gap: 16px; align-items: baseline; padding: 11px 20px; border-bottom: 1px solid var(--border); font-size: 13.5px; }
    .summary dt { color: var(--text-secondary); }
    .summary dd { margin: 0; color: var(--text-primary); min-width: 0; overflow-wrap: anywhere; line-height: 1.6; }
    .summary .ui-link { font-size: 12.5px; }
    .next-up { display: flex; flex-direction: column; gap: 8px; }
    .next-up .choice { width: 100%; background: none; font: inherit; font-size: 13.5px; color: var(--text-primary); text-align: left; }
    .next-up .where { font-size: 12.5px; }
    .next-up .choice:hover :global(.tick) { transform: translateX(2px); }

    @media (max-width: 640px) {
        .setup { padding-top: 24px; }
        .lbl { display: none; }
        .progress li.on .lbl { display: inline; }
        .create { grid-template-columns: 1fr; }
        .empty { grid-template-columns: 22px 1fr; }
        .empty .ui-btn { grid-column: 2; justify-self: start; }
        .summary div { grid-template-columns: 1fr auto; gap: 2px 12px; }
        .summary dt { grid-column: 1; }
        .summary dd { grid-column: 1; grid-row: 2; }
        .summary .ui-link { grid-column: 2; grid-row: 1 / span 2; align-self: center; }
        .next-up .where { display: none; }
    }
</style>
