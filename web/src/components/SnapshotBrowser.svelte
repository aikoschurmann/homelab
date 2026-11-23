<script>
    import { Folder, File, Download, X, Loader2, ChevronRight, RotateCcw, Copy } from 'lucide-svelte';
    import Modal from './ui/Modal.svelte';

    // The files inside one part of a backup snapshot: browse folders, download a file, and
    // restore what's selected (or the folder you're in) as a copy or back where it came from.
    export let ts;
    export let part;          // the archive's component name, e.g. vm_data
    export let label = part;
    export let when = '';     // the snapshot's date, for messages
    export let onClose = () => {};

    let path = '', data = null, error = '', loading = false;
    let selected = new Set();
    async function load(p = path) {
        loading = true; error = '';
        try {
            const j = await fetch(`/api/backups/${ts}/parts/${encodeURIComponent(part)}/files?path=${encodeURIComponent(p)}`).then(r => r.json());
            if (j.status === 'success') { data = j.data; path = j.data.path; selected = new Set(); }
            else error = j.message;
        } catch (e) { error = 'Could not read the archive'; }
        finally { loading = false; }
    }
    $: ts, part, (path = '', load(''));

    $: crumbs = path ? path.split('/') : [];
    const join = (name) => path ? `${path}/${name}` : name;
    const size = (b) => b == null ? '—' : b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : b < 1073741824 ? `${(b / 1048576).toFixed(1)} MB` : `${(b / 1073741824).toFixed(2)} GB`;
    const date = (t) => t ? new Date(t * 1000).toLocaleString([], { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
    function toggle(name) { selected.has(name) ? selected.delete(name) : selected.add(name); selected = selected; }
    $: entries = data?.entries || [];
    $: allOn = entries.length && entries.every(e => selected.has(e.name));
    $: chosen = selected.size ? [...selected].map(join) : [path];
    $: what = selected.size ? `${selected.size} selected` : path ? `“${crumbs.at(-1)}”` : 'everything';
    $: target = data?.target;
    $: home = (p) => p?.replace(/^\/Users\/[^/]+/, '~');

    // ---- restoring ----
    let confirm = null, job = null, poll;
    async function restore(mode) {
        confirm = null;
        try {
            const r = await fetch(`/api/backups/${ts}/restore`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ part, paths: chosen, mode }) }).then(r => r.json());
            if (r.status !== 'success') { window.showToast?.(r.message || 'Restore failed'); return; }
            job = r.data;
            clearInterval(poll);
            poll = setInterval(async () => {
                const j = await fetch(`/api/backups/restores/${job.id}`).then(r => r.json()).catch(() => null);
                if (j?.status === 'success') job = j.data;
                if (job.state !== 'running') clearInterval(poll);
            }, 1000);
        } catch (e) { window.showToast?.('Restore failed'); }
    }
</script>

<section class="ui-card">
    <div class="ui-card-head">
        <div>
            <h2 class="ui-card-title">Files in {label}</h2>
            <p class="ui-card-desc">{#if target?.where}Restoring puts files back in <span class="ui-mono">{home(target.root)}</span> on {target.where === 'mac' ? 'the Mac' : target.label}, or a copy goes to <span class="ui-mono">~/Homelab-Restores</span>.{:else if target}{target.why}{:else}&nbsp;{/if}</p>
        </div>
        <button class="ui-btn sm icon" on:click={onClose} title="Close" aria-label="Close"><X size={14} /></button>
    </div>

    <div class="ui-toolbar">
        <nav class="crumbs" aria-label="Folder">
            <button class="ui-link" on:click={() => load('')}>{label}</button>
            {#each crumbs as c, i}<ChevronRight size={13} class="sep" /><button class="ui-link" class:here={i === crumbs.length - 1} on:click={() => load(crumbs.slice(0, i + 1).join('/'))}>{c}</button>{/each}
        </nav>
        <span class="ui-btns end">
            <button class="ui-btn sm" disabled={!data || job?.state === 'running'} on:click={() => confirm = 'copy'}><Copy size={13} /> Restore a copy</button>
            {#if target?.where}<button class="ui-btn sm primary" disabled={!data || job?.state === 'running'} on:click={() => confirm = 'original'}><RotateCcw size={13} /> Restore {what}</button>{/if}
        </span>
    </div>

    {#if job}
        <div class="job" class:bad={job.state === 'failed'}>
            {#if job.state === 'running'}<Loader2 size={14} class="ui-spin" />{/if}
            <span>{job.log.join(' · ')}{#if job.state === 'done' && job.dest} <span class="ui-mono">{home(job.dest)}</span>{/if}</span>
            {#if job.state !== 'running'}<button class="ui-btn sm icon" on:click={() => job = null} aria-label="Dismiss"><X size={13} /></button>{/if}
        </div>
    {/if}

    {#if error}
        <div class="ui-empty">{error}</div>
    {:else if !data}
        <div class="ui-empty"><Loader2 size={14} class="ui-spin" /> Reading the archive…</div>
    {:else}
        <div class="ui-tbl-wrap" class:dim={loading}>
            <table class="ui-tbl">
                <thead><tr>
                    <th class="shrink"><input type="checkbox" checked={allOn} on:change={() => { selected = allOn ? new Set() : new Set(entries.map(e => e.name)); }} aria-label="Select all" /></th>
                    <th>Name</th><th class="c-sm">Size</th><th class="c-md">Modified</th><th class="shrink"></th>
                </tr></thead>
                <tbody>
                    {#each entries as e (e.name)}
                        <tr class:click={e.dir} on:click={() => e.dir && load(join(e.name))}>
                            <td><input type="checkbox" checked={selected.has(e.name)} on:click|stopPropagation on:change={() => toggle(e.name)} aria-label="Select {e.name}" /></td>
                            <td class="wrap"><span class="fn">{#if e.dir}<Folder size={14} class="fi" />{:else}<File size={14} class="fi" />{/if}<span class:nm={e.dir}>{e.name}</span></span></td>
                            <td class="c-sm num">{size(e.size)}</td>
                            <td class="c-md">{date(e.mtime)}</td>
                            <td>{#if !e.dir}<a on:click|stopPropagation class="ui-btn sm icon" href="/api/backups/{ts}/parts/{encodeURIComponent(part)}/download?path={encodeURIComponent(join(e.name))}" download title="Download" aria-label="Download {e.name}"><Download size={13} /></a>{/if}</td>
                        </tr>
                    {:else}<tr><td colspan="5" class="ui-dim">This folder is empty.</td></tr>{/each}
                </tbody>
            </table>
        </div>
    {/if}
</section>

<Modal open={!!confirm} onClose={() => confirm = null} width={480}
    title={confirm === 'copy' ? 'Restore a copy' : `Restore ${what}`}
    description={confirm === 'copy'
        ? `${what === 'everything' ? 'All of ' + label : what[0].toUpperCase() + what.slice(1)} from ${when} goes to ~/Homelab-Restores/${ts}/${part}. Nothing else is touched.`
        : `Files in ${home(target?.root)} on ${target?.where === 'mac' ? 'the Mac' : target?.label} are replaced with their versions from ${when}. Files added since then stay.`}>
    {#if confirm === 'original' && part === 'vm_data'}<p class="note">Containers that use a restored Docker volume are stopped first and started again afterwards.</p>{/if}
    <svelte:fragment slot="footer">
        <button class="ui-btn" on:click={() => confirm = null}>Cancel</button>
        <button class="ui-btn {confirm === 'original' ? 'danger' : 'primary'}" on:click={() => restore(confirm)}>{confirm === 'copy' ? 'Restore a copy' : 'Replace files'}</button>
    </svelte:fragment>
</Modal>

<style>
    .crumbs { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; min-width: 0; font-size: 13px; }
    .crumbs :global(.sep) { color: var(--text-secondary); }
    .crumbs .here { color: var(--text-primary); }
    .end { margin-left: auto; }
    .fn { display: inline-flex; align-items: center; gap: 8px; }
    .fn :global(.fi) { color: var(--text-secondary); flex-shrink: 0; }
    .nm { font-weight: 600; color: var(--accent); }
    tr.click:hover .nm { text-decoration: underline; }
    .num { font-variant-numeric: tabular-nums; }
    .dim { opacity: 0.5; }
    .job { display: flex; align-items: center; gap: 10px; padding: 10px 20px; border-bottom: 1px solid var(--border); font-size: 13px; background: var(--accent-soft); }
    .job.bad { background: rgba(184, 76, 62, 0.12); color: var(--red); }
    .job .ui-btn { margin-left: auto; }
    .note { margin: 0; font-size: 13px; color: var(--text-secondary); }
    input[type="checkbox"] { accent-color: var(--accent); cursor: pointer; }
</style>
