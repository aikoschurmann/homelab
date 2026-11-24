<script>
    import { SN } from '../../lib/server.js';
    // Make a pool or change one: which nodes, how to reach them, what to install.
    import { onMount } from 'svelte';
    import { Check, X, Loader2, Server, Box } from 'lucide-svelte';
    import { candidates, sshCheck, createPool, savePool } from '../../lib/compute.js';
    import { hostIcon, arrakisModel, hosts } from '../../lib/hosts.js';

    export let pool = null;               // an existing pool to edit; null = a new one
    export let saved = () => {};          // saved(pool)
    export let cancel = null;

    let cands = [], loading = true, error = '', saving = false;
    let name = pool?.name || '';
    let python = pool?.python || '3.13';
    let packages = (pool?.packages || []).join('\n');
    let scheduler = pool?.scheduler || 'arrakis';
    let jobsOn = pool?.jobs_on || 'arrakis';
    // per node: { on, ssh, tags (text), procs }
    let rows = {};
    let checks = {};                      // id -> { busy, ok, message }

    onMount(async () => {
        cands = await candidates();
        for (const c of cands) {
            const n = pool?.nodes?.[c.id];
            rows[c.id] = { on: pool ? !!n : !c.vm && (c.id === 'arrakis' || c.online), ssh: n?.ssh || c.ssh, tags: (n?.tags || []).join(', '), procs: n?.procs || '' };
        }
        // each VM right under the node it runs on
        const vms = cands.filter(c => c.vm);
        cands = cands.filter(c => !c.vm).flatMap(h => [h, ...vms.filter(v => v.parent === h.id)]).concat(vms.filter(v => !cands.some(h => h.id === v.parent)));
        // nodes in the pool that are no longer hosts of the cluster stay listed
        for (const [id, n] of Object.entries(pool?.nodes || {})) {
            if (!rows[id]) { cands = [...cands, { id, name: id, ssh: n.ssh, online: false, vm: !!n.vm }]; rows[id] = { on: true, ssh: n.ssh, tags: (n.tags || []).join(', '), procs: n.procs || '' }; }
        }
        rows = rows; loading = false;
    });

    $: picked = cands.filter(c => rows[c.id]?.on);
    // the coordinator: any picked node or VM, or Arrakis without doing work itself
    $: coords = [...(picked.some(c => c.id === 'arrakis') ? [] : [{ id: 'arrakis', name: `${SN} (coordinates only)` }]), ...picked];
    $: if (!loading && !coords.some(c => c.id === scheduler)) scheduler = 'arrakis';
    $: if (!loading && jobsOn !== 'arrakis' && !picked.some(c => c.id === jobsOn)) jobsOn = 'arrakis';   // not before the list is read
    $: totalCores = picked.reduce((a, c) => a + (c.cores || 0), 0);
    $: nameOk = !!pool || /^[a-z0-9][a-z0-9-]{0,30}$/.test(name);

    // a host and its VMs share the same cores: the pool uses one or the other
    function exclusive(c) {
        if (!rows[c.id].on) return;
        for (const o of cands) {
            if (c.vm ? o.id === c.parent : o.parent === c.id) rows[o.id].on = false;
        }
        rows = rows;
    }
    const sharesWith = (c) => c.vm ? cands.find(o => o.id === c.parent) : null;

    async function check(c) {
        checks[c.id] = { busy: true };
        checks[c.id] = await sshCheck(rows[c.id].ssh.trim(), c.vm ? c.parent : null, via(c));
    }
    // a VM on another host is reached through that host (its OrbStack), with the host's login
    const via = (c) => c.vm && c.parent !== 'arrakis' ? (rows[c.parent]?.ssh || cands.find(h => h.id === c.parent)?.ssh || '').trim() || undefined : undefined;
    const icon = (c) => c.vm ? Box : c.id === 'arrakis' ? hostIcon($arrakisModel, 'macOS') : hostIcon(($hosts || []).find(h => h.id === c.id)?.report?.model, c.os) || Server;

    async function submit() {
        error = ''; saving = true;
        const def = {
            name, python, scheduler, jobs_on: jobsOn,
            packages: packages.split(/[\n,]+/).map(s => s.trim()).filter(Boolean),
            nodes: Object.fromEntries(picked.map(c => [c.id, {
                ssh: rows[c.id].ssh.trim(),
                tags: rows[c.id].tags.split(/[\s,]+/).map(t => t.trim().toLowerCase()).filter(Boolean),
                procs: rows[c.id].procs ? +rows[c.id].procs : null,
                vm: !!c.vm,
                host: c.vm ? c.parent : undefined,
                via: via(c),
            }])),
        };
        try { saved(pool ? await savePool(pool.name, def) : await createPool(def)); }
        catch (e) { error = e.message; }
        saving = false;
    }
</script>

<form class="pf" on:submit|preventDefault={submit}>
    {#if !pool}
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Name</h2><p class="ui-card-desc">Also its folder, <span class="ui-mono">~/pools/{name || 'name'}</span>, where its scripts live.</p></div></div>
            <div class="ui-card-body"><input class="ui-input ui-mono name" bind:value={name} placeholder="crunch" maxlength="31" autocomplete="off" spellcheck="false" />
                {#if name && !nameOk}<p class="err">Lowercase letters, digits and dashes, starting with a letter or digit.</p>{/if}</div>
        </section>
    {/if}

    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Nodes</h2><p class="ui-card-desc">Every core of the ones you pick works for the pool: whole machines or the VMs on them (pick only VMs for an identical environment everywhere). {SN} reaches each over SSH with its own key, so each needs an SSH login that works without a password.</p></div>
            <span class="tot">{picked.length} picked{totalCores ? ` · ${totalCores} cores` : ''}</span></div>
        {#if loading}<div class="ui-card-body ui-dim">Reading the cluster…</div>
        {:else}
            <div class="ui-tbl-wrap"><table class="ui-tbl nodes">
                <thead><tr><th class="shrink"></th><th>Node</th><th>Login</th><th class="c-sm">Processes</th></tr></thead>
                <tbody>
                    {#each cands as c (c.id)}
                        {@const ck = checks[c.id]}
                        <tr class:off={!rows[c.id].on} class:vm={c.vm}>
                            <td><input type="checkbox" bind:checked={rows[c.id].on} aria-label="Use {c.name}" title={c.vm ? `Shares ${sharesWith(c)?.name || "its host"}'s cores: picking it takes ${sharesWith(c)?.name || "the host"} out` : null} on:change={() => exclusive(c)} /></td>
                            <td><div class="cm"><span class="ic"><svelte:component this={icon(c)} size={15} /></span><div><b>{c.name}</b><div class="ui-dim sub">{[c.vm ? 'VM' : '', c.os, c.cores ? `${c.cores} ${c.cores === 1 ? 'core' : 'cores'}` : '', c.vm && !c.tailnet ? `${SN} only` : '', c.online ? '' : (c.vm ? 'stopped' : 'offline')].filter(Boolean).join(' · ')}</div></div></div></td>
                            <td>
                                <div class="ssh">
                                    <input class="ui-input ui-mono sm" bind:value={rows[c.id].ssh} disabled={!rows[c.id].on} spellcheck="false" on:input={() => delete checks[c.id]} />
                                    <button type="button" class="ui-btn sm chk" class:ok={ck && !ck.busy && ck.ok} class:bad={ck && !ck.busy && !ck.ok} title={ck && !ck.busy ? ck.message : `Try logging in from ${SN}`} disabled={!rows[c.id].on || ck?.busy} on:click={() => check(c)}>
                                        {#if ck?.busy}<Loader2 size={13} class="ui-spin" />{:else if ck?.ok}<Check size={13} />{:else if ck}<X size={13} />{/if}Check</button>
                                </div>
                            </td>
                            <td class="c-sm"><input class="ui-input sm num" type="number" min="1" max="256" bind:value={rows[c.id].procs} disabled={!rows[c.id].on} placeholder="all" /></td>
                        </tr>
                    {/each}
                </tbody>
            </table></div>
            <p class="ui-hint note">Processes: one per core unless you set fewer, which gives each more memory.</p>
        {/if}
    </section>

    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Software</h2><p class="ui-card-desc">Installed the same way on every node, and on {SN} for the job itself. Setup commands (clone a repo, install tools) go under <span class="ui-mono">setup:</span> in the pool's <span class="ui-mono">pool.yaml</span>.</p></div></div>
        <div class="ui-form-row">
            <div><div class="ui-label">Python packages</div><div class="ui-hint">One per line, like pip: <span class="ui-mono">numpy</span>, <span class="ui-mono">pandas&gt;=2</span></div></div>
            <textarea class="ui-input ui-mono pk" rows="3" bind:value={packages} placeholder="numpy" spellcheck="false"></textarea>
        </div>
        <div class="ui-form-row">
            <div><div class="ui-label">Python</div><div class="ui-hint">The same version runs everywhere</div></div>
            <select class="ui-input sel" bind:value={python}>{#each ['3.11', '3.12', '3.13'] as v}<option value={v}>{v}</option>{/each}</select>
        </div>
        <div class="ui-form-row">
            <div><div class="ui-label">Coordinator</div><div class="ui-hint">Hands out the work; pick one that stays on</div></div>
            <select class="ui-input sel" bind:value={scheduler}>{#each coords as c}<option value={c.id}>{c.name}</option>{/each}</select>
        </div>
        <div class="ui-form-row">
            <div><div class="ui-label">Jobs run on</div><div class="ui-hint">{SN}, or a node: then the job script has the pool's whole environment, setup included (files it writes stay there)</div></div>
            <select class="ui-input sel" bind:value={jobsOn}><option value="arrakis">{SN}</option>{#each picked.filter(c => c.id !== 'arrakis') as c}<option value={c.id}>{c.name}</option>{/each}</select>
        </div>
    </section>

    {#if error}<div class="ui-banner warn">{error}</div>{/if}
    <div class="ui-btns end">
        {#if cancel}<button type="button" class="ui-btn" on:click={cancel}>Cancel</button>{/if}
        <button class="ui-btn primary" disabled={saving || !picked.length || !nameOk || (!pool && !name)}>{#if saving}<Loader2 size={14} class="ui-spin" />{/if}{pool ? 'Save changes' : 'Create pool'}</button>
    </div>
</form>

<style>
    .pf { display: flex; flex-direction: column; gap: 16px; }
    input[type=checkbox] { accent-color: var(--accent); width: 15px; height: 15px; cursor: pointer; }
    .name { max-width: 320px; }
    .err { margin: 6px 0 0; font-size: 12.5px; color: var(--red); }
    .tot { font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; }
    tr.off .ssh, tr.off .c-sm { opacity: 0.6; }
    .cm { display: flex; align-items: center; gap: 10px; }
    .ic { width: 28px; height: 28px; border-radius: 7px; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); flex-shrink: 0; }
    .sub { font-size: 12px; margin-top: 1px; }
    .ssh { display: flex; gap: 6px; align-items: center; min-width: 220px; }
    .ssh .ui-input { flex: 1; min-width: 0; }
    .ui-input.sm { height: 30px; font-size: 12.5px; padding: 0 8px; }
    .num { width: 72px; }
    .chk.ok { color: var(--green); }
    .chk.bad { color: var(--red); }
    .note { margin: 0; padding: 12px 20px 16px; }
    .pk { width: 100%; max-width: 360px; resize: vertical; font-size: 13px; padding: 8px 10px; }
    .sel { width: 220px; }
    tr.vm .cm { padding-left: 22px; }
    .end { justify-content: flex-end; }
    /* phone: each node is the name with its login (and processes) on a line under it, instead
       of a table wider than the screen */
    @media (max-width: 640px) {
        .pf .ui-card-head { flex-wrap: wrap; }
        .nodes thead { display: none; }
        .nodes tbody tr { display: grid; grid-template-columns: auto 1fr auto; column-gap: 12px; padding: 12px 14px; border-bottom: 1px solid var(--border); }
        .nodes tbody tr:last-child { border-bottom: none; }
        .nodes tbody td, .nodes tbody tr:first-child td { padding: 0; border: none; }
        .nodes td:nth-child(1) { grid-row: span 2; padding-top: 6px; }
        .nodes td:nth-child(2) { grid-column: 2 / -1; }
        .nodes td:nth-child(3) { grid-column: 2; padding-top: 8px; }
        .nodes td.c-sm { display: block; grid-column: 3; padding-top: 8px; }
        .ssh { min-width: 0; }
        .num { width: 64px; }
        tr.vm .cm { padding-left: 0; }
    }
</style>
