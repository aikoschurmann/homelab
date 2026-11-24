<script>
    import { SN } from '../lib/server.js';
    import { onMount } from 'svelte';
    import { Archive, Trash2, Plus, Download, FolderOpen, Loader2, ExternalLink, Settings2, X, FolderSearch } from 'lucide-svelte';
    import { visible } from '../lib/stores.js';
    import { backups, fetchBackups, snapLabel } from '../lib/backups.js';
    import Tabs from './ui/Tabs.svelte';
    import ActionMenu from './ui/ActionMenu.svelte';
    import Modal from './ui/Modal.svelte';
    import SnapshotBrowser from './SnapshotBrowser.svelte';

    // Routes: #backups (snapshots), #backups/coverage, #backups/runs, #backups/<timestamp>.
    // What and when to back up is in Settings → Backups. Parts and their names come from
    // the backend, so whatever backup.sh saves shows up here as it is.
    export let section = null;
    export let onNavigate = () => {};

    const toast = (m) => window.showToast?.(m);
    const go = (s = null) => onNavigate('Backups', s);
    const PAGES = ['coverage', 'runs'];

    let config = null, bsaved = null, runs = null, coverage = null;
    async function load() {
        try {
            const [c, st, r, cv] = await Promise.all([
                fetch('/api/backups/config').then(r => r.json()),
                fetch('/api/backups/settings').then(r => r.json()),
                fetch('/api/backups/runs').then(r => r.json()),
                fetch('/api/backups/coverage').then(r => r.json()),
                fetchBackups(),
            ]);
            if (st.status === 'success') bsaved = st.data;
            if (c.status === 'success') config = c.data;
            if (r.status === 'success') runs = r.data;
            if (cv.status === 'success') coverage = cv.data;
        } catch (e) {}
    }
    onMount(() => {
        load();
        const t = setInterval(() => visible() && load(), 15000);
        return () => clearInterval(t);
    });

    $: details = $backups;
    $: snaps = details?.snapshots || [];
    $: if (section === 'schedule' || section === 'contents') onNavigate('Settings', 'backups');
    $: tab = PAGES.includes(section) ? section : 'snapshots';
    $: snap = section && !PAGES.includes(section) ? snaps.find(s => s.timestamp === section) : null;
    $: lastRun = runs?.[0];
    let browsing = null;          // the part whose files are open below the parts list
    $: if (!snap) browsing = null;

    // ---- formatting ----------------------------------------------------------------------
    function fmtSize(b) {
        if (!b) return '0 B';
        const u = ['B', 'KB', 'MB', 'GB', 'TB'];
        let i = Math.min(4, Math.floor(Math.log(b) / Math.log(1024)));
        // stays in MB up to a full GB (1017 MB, not 0.99 GB), so snapshots of about the same size share a unit
        const v = b / 1024 ** i;
        return v.toFixed(i >= 3 ? 2 : i && v < 1000 ? 1 : 0) + ' ' + u[i];
    }
    const fmtDate = snapLabel;
    const tsSec = (ts) => ts ? new Date(ts.replace(/_(\d\d)-(\d\d)-(\d\d)$/, 'T$1:$2:$3')).getTime() / 1000 : null;
    function rel(sec) {
        const d = sec - Date.now() / 1000, a = Math.abs(d);
        const n = a < 3600 ? Math.max(1, Math.round(a / 60)) : a < 86400 ? Math.round(a / 3600) : Math.round(a / 86400);
        const v = a < 3600 ? `${n} min` : a < 86400 ? `${n} h` : `${n} ${n === 1 ? 'day' : 'days'}`;
        return d < 0 ? `${v} ago` : `in ${v}`;
    }
    const took = (s) => s == null ? '—' : s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
    const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    const pad = (n) => String(n).padStart(2, '0');
    function describe(c) {
        if (!c) return '—';
        if (c.frequency === 'hourly') return `Every ${c.hour} ${c.hour === 1 ? 'hour' : 'hours'}`;
        const at = `${pad(c.hour)}:${pad(c.minute)}`;
        return c.frequency === 'weekly' ? `${DAYS[c.day % 7]}s at ${at}` : `Daily at ${at}`;
    }
    const home = (p) => (p || '').replace(/^\/Users\/[^/]+/, '~');
    $: deltaOf = (i) => i + 1 < snaps.length ? snaps[i].size_bytes - snaps[i + 1].size_bytes : null;
    const signed = (b) => (b >= 0 ? '+' : '−') + fmtSize(Math.abs(b));
    const failedParts = (s) => s.files.filter(f => !f.size_bytes).map(f => f.label);

    // coverage: one line per computer or machine
    $: covered = coverage ? coverage.groups.filter(g => g.items.some(i => i.on && i.last)) : [];
    const savedOf = (g) => g.items.filter(i => i.on && i.last);
    const lastOf = (g) => savedOf(g).map(i => i.last).sort().pop();
    const KIND = { mac: 'The Mac', machine: `Machine on ${SN}`, host: 'Computer' };

    // ---- actions ------------------------------------------------------------------------
    let triggering = false;
    async function backupNow() {
        triggering = true;
        toast('Backup started');
        try {
            const r = await (await fetch('/api/host/command/backup', { method: 'POST' })).json();
            toast(r.status === 'success' ? 'Backup finished' : 'Backup finished with errors: ' + (r.message || 'see Runs'));
        }
        catch (e) { toast('Backup request failed'); }
        triggering = false;
        load();
    }
    let confirmDelete = null;
    async function del(ts) {
        confirmDelete = null;
        try {
            const r = await fetch(`/api/backups/${ts}`, { method: 'DELETE' }).then(r => r.json());
            toast(r.status === 'success' ? `Deleted snapshot ${ts}` : (r.message || 'Delete failed'));
            if (r.status === 'success' && section === ts) go(null);
        } catch (e) { toast('Delete failed'); }
        load();
    }
    async function reveal(ts) {
        try {
            const r = await fetch(`/api/backups/${ts}/reveal`, { method: 'POST' }).then(r => r.json());
            toast(r.status === 'success' ? 'Opened in Finder on the Mac' : (r.message || 'Could not open Finder'));
        } catch (e) { toast('Could not open Finder'); }
    }
    const menu = (s) => [
        { label: 'Open', icon: ExternalLink, onClick: () => go(s.timestamp) },
        { label: 'Show in Finder', icon: FolderOpen, onClick: () => reveal(s.timestamp) },
        { label: 'Delete…', icon: Trash2, danger: true, divider: true, onClick: () => confirmDelete = s.timestamp },
    ];
    let openRun = null;

    // ---- which folders of a machine to back up ------------------------------------------------
    let editing = null;   // the machine's coverage group
    let choice = { containers: false, folders: [] }, offered = [], offerErr = '', offering = false, newPath = '', savingM = false, saveErr = '';
    let measuring = false;
    async function editMachine(g) {
        editing = g; saveErr = ''; offerErr = ''; newPath = ''; measuring = false;
        choice = { containers: !!g.containers_on, folders: [...(g.folders || [])] };
        offered = []; offering = true;
        const url = g.kind === 'host' ? `/api/backups/hosts/${encodeURIComponent(g.id)}/folders` : `/api/backups/machines/${encodeURIComponent(g.name)}/folders`;
        try {
            const j = await fetch(url).then(r => r.json());
            if (j.status !== 'success') offerErr = `${j.message} You can still type a path.`;
            else if (j.data.running === false) offerErr = `${g.name} isn't running, so its folders can't be listed. You can still type a path.`;
            // Containers already covers the Docker volumes in the dashboard machine
            else {
                offered = j.data.folders.filter(f => !(g.containers && f.path === '/var/lib/docker/volumes'));
                measuring = !!j.data.measuring;
                if (measuring) followSizes(g, url);
            }
        } catch (e) { offerErr = 'Could not reach the backend'; }
        offering = false;
    }
    // a computer measures its folders after listing them; fill the sizes in as they come
    async function followSizes(g, url) {
        while (measuring && editing === g) {
            await new Promise(r => setTimeout(r, 3000));
            if (editing !== g) break;
            try {
                const j = await fetch(url).then(r => r.json());
                if (j.status === 'success') { offered = j.data.folders; measuring = !!j.data.measuring; }
            } catch (e) { break; }
        }
    }
    // what the dialog lists: the offered folders, plus any chosen or typed one that isn't among them
    $: rows = [...offered, ...choice.folders.filter(f => !offered.some(o => o.path === f)).map(path => ({ path, bytes: null }))];
    const toggle = (p) => choice = { ...choice, folders: choice.folders.includes(p) ? choice.folders.filter(x => x !== p) : [...choice.folders, p] };
    function addPath() {
        const p = newPath.trim().replace(/\/+$/, '');
        if (!p.startsWith('/') || p === '/') { saveErr = 'Type a full path, like /home/me/data'; return; }
        saveErr = ''; newPath = '';
        if (!choice.folders.includes(p)) choice = { ...choice, folders: [...choice.folders, p] };
    }
    async function saveMachine() {
        savingM = true; saveErr = '';
        const body = {};
        if (editing.kind === 'host') {
            const others = (bsaved?.hosts || []).filter(x => x.id !== editing.id);
            body.hosts = [...others, ...(choice.folders.length ? [{ id: editing.id, folders: choice.folders }] : [])];
        } else {
            const others = (bsaved?.machines || []).filter(m => m.name !== editing.name);
            body.machines = [...others, ...(choice.folders.length ? [{ name: editing.name, folders: choice.folders }] : [])];
        }
        if (editing.containers) body.parts = { ...bsaved.parts, vm_data: choice.containers };
        try {
            const j = await fetch('/api/backups/settings', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json());
            if (j.status !== 'success') saveErr = j.message;
            else { toast(`Saved. ${editing.name} is backed up from the next run.`); editing = null; load(); }
        } catch (e) { saveErr = 'Could not reach the backend'; }
        savingM = false;
    }
</script>

<div class="ui-page">
    {#if section && !PAGES.includes(section)}
        {#if !details}
            <div class="ui-dim">Loading…</div>
        {:else if !snap}
            <div class="ui-head"><div><h1>{section}</h1><p>No snapshot with this name. <button class="ui-link" on:click={() => go(null)}>All snapshots</button></p></div></div>
        {:else}
            <div class="ui-head">
                <div class="id">
                    <span class="icon"><Archive size={20} /></span>
                    <div>
                        <h1>{fmtDate(snap.created)}</h1>
                        <div class="ui-meta">
                            <span>{rel(snap.created)}</span><span>{fmtSize(snap.size_bytes)}</span>
                            {#if snap.incomplete}<span class="bad">{failedParts(snap).join(', ')} failed</span>{/if}
                        </div>
                    </div>
                </div>
                <div class="ui-head-actions">
                    <button class="ui-btn" on:click={() => reveal(snap.timestamp)}><FolderOpen size={14} /> Show in Finder</button>
                    {#if confirmDelete === snap.timestamp}
                        <button class="ui-btn" on:click={() => confirmDelete = null}>Keep</button>
                        <button class="ui-btn danger" on:click={() => del(snap.timestamp)}>Delete snapshot</button>
                    {:else}
                        <button class="ui-btn danger-outline" on:click={() => confirmDelete = snap.timestamp}><Trash2 size={14} /> Delete</button>
                    {/if}
                </div>
            </div>
            <section class="ui-card">
                <div class="ui-tbl-wrap">
                    <table class="ui-tbl">
                        <thead><tr><th>Part</th><th class="c-md">File</th><th class="r">Size</th><th class="shrink"></th></tr></thead>
                        <tbody>
                            {#each snap.files as f (f.name)}
                                <tr>
                                    <td class="strong">{f.label}</td>
                                    <td class="c-md ui-mono dim trunc" title={f.name}>{f.name}</td>
                                    <td class="r num">{#if f.size_bytes}{fmtSize(f.size_bytes)}{:else}<span class="bad">failed</span>{/if}</td>
                                    <td>{#if f.size_bytes}<span class="ui-btns"><button class="ui-btn sm" class:on={browsing?.name === f.name} on:click={() => browsing = browsing?.name === f.name ? null : f}><FolderSearch size={13} /> Browse</button><a class="ui-btn sm" href="/api/backups/file/{f.name}" download><Download size={13} /> Download</a></span>{/if}</td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </section>
            {#if browsing}
                {#key browsing.name}<SnapshotBrowser ts={snap.timestamp} part={browsing.component} label={browsing.label} when={fmtDate(snap.created)} onClose={() => browsing = null} />{/key}
            {/if}
        {/if}
    {:else}
        <div class="ui-head">
            <div>
                <h1>Backups</h1>
                <div class="ui-meta">
                    <span>{describe(config)}</span>
                    <span>keeps the last {config?.retention ?? '—'}</span>
                    <span>in <b class="ui-mono">{home(bsaved?.dest || '~/Homelab-Backups/archive')}</b></span>
                </div>
            </div>
            <div class="ui-head-actions">
                <button class="ui-btn" on:click={() => onNavigate('Settings', 'backups')}><Settings2 size={14} /> Settings</button>
                <button class="ui-btn primary" disabled={triggering || details?.running} on:click={backupNow}>
                    {#if triggering || details?.running}<Loader2 size={14} class="ui-spin" /> Backing up…{:else}<Plus size={15} /> Back up now{/if}
                </button>
            </div>
        </div>

        <div class="summary">
            <div class="ui-stat">
                <span class="ui-stat-label">Last backup</span>
                <span class="ui-stat-value">{details?.last_success ? rel(details.last_success) : '—'}</span>
                <span class="ui-stat-sub">{#if lastRun}{lastRun.state === 'failed' ? 'Had problems' : lastRun.state === 'running' ? 'Running' : 'Went fine'}{lastRun.seconds != null ? `, took ${took(lastRun.seconds)}` : ''}{:else}None yet{/if}</span>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Next backup</span>
                <span class="ui-stat-value">{details?.running ? 'Running now' : details?.next_run ? rel(details.next_run) : '—'}</span>
                <span class="ui-stat-sub">{describe(config)}</span>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Stored</span>
                <span class="ui-stat-value">{details ? fmtSize(details.total_bytes) : '—'}</span>
                <span class="ui-stat-sub">{snaps.length} {snaps.length === 1 ? 'snapshot' : 'snapshots'}</span>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Covered</span>
                <span class="ui-stat-value">{coverage ? covered.length : '—'}<small>of {coverage?.groups.length ?? '—'}</small></span>
                <span class="ui-stat-sub">computers and machines</span>
            </div>
        </div>

        <Tabs tabs={[{ id: 'snapshots', label: 'Snapshots' }, { id: 'coverage', label: "What's covered" }, { id: 'runs', label: 'Runs' }]} active={tab} onSelect={(t) => go(t === 'snapshots' ? null : t)} />

        {#if tab === 'snapshots'}
            <section class="ui-card">
                <div class="ui-tbl-wrap">
                    <table class="ui-tbl list snaps">
                        <colgroup><col class="w-when" /><col class="ct" /><col class="w-size" /><col class="w-act" /></colgroup>
                        <thead><tr><th>Snapshot</th><th class="ct">Contents</th><th class="r">Size</th><th></th></tr></thead>
                        <tbody>
                            {#each snaps as s, i (s.timestamp)}
                                <tr class="click" on:click={() => go(s.timestamp)}>
                                    <td><span class="strong">{fmtDate(s.created)}</span><small>{rel(s.created)}</small></td>
                                    <td class="wrap ct">
                                        <span class="parts">{#each s.files as f, j}{#if j}<span class="sep">·</span>{' '}{/if}<span class:bad={!f.size_bytes}>{f.label} <span class="dim">{f.size_bytes ? fmtSize(f.size_bytes) : 'failed'}</span></span>{/each}</span>
                                    </td>
                                    <td class="r num"><span class="strong">{fmtSize(s.size_bytes)}</span>{#if deltaOf(i) != null}<small>{signed(deltaOf(i))}</small>{/if}</td>
                                    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
                                    <td on:click|stopPropagation>
                                        {#if confirmDelete === s.timestamp}
                                            <span class="ui-btns"><button class="ui-btn sm" on:click={() => confirmDelete = null}>Keep</button><button class="ui-btn sm danger" on:click={() => del(s.timestamp)}>Delete</button></span>
                                        {:else}<ActionMenu items={menu(s)} label="Actions for {s.timestamp}" />{/if}
                                    </td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                    {#if !details}<div class="ui-empty">Loading…</div>{:else if !snaps.length}<div class="ui-empty">No backups yet. <button class="ui-link" on:click={backupNow}>Back up now</button></div>{/if}
                </div>
            </section>

        {:else if tab === 'coverage'}
            <section class="ui-card">
                <div class="ui-tbl-wrap">
                    <table class="ui-tbl list cov">
                        <colgroup><col class="w-who" /><col /><col class="w-last" /></colgroup>
                        <thead><tr><th>Computer or machine</th><th>What's saved</th><th class="r">Last saved</th></tr></thead>
                        <tbody>
                            {#each coverage?.groups || [] as g (g.id)}
                                {@const saved = savedOf(g)}
                                {@const act = g.kind === 'mac' ? () => onNavigate('Settings', 'backups') : g.editable ? () => editMachine(g) : null}
                                <tr class:click={!!act} on:click={() => act?.()}>
                                    <td><span class="strong">{g.name}</span><small>{KIND[g.kind]}</small></td>
                                    <td class="wrap">
                                        {#if saved.length}
                                            <span class="parts">{#each saved as it, j}{#if j}<span class="sep">·</span>{' '}{/if}<span title={it.what + (it.excluded?.length ? '. Leaves out ' + it.excluded.join(' and ') : '')}>{it.name}</span>{/each}</span>
                                        {:else if g.kind === 'host' && !g.editable}<span class="dim">Nothing. Its agent needs updating first</span>
                                        {:else if g.folders?.length}<span class="dim">{g.folders.join(' · ')}, from the next run</span>
                                        {:else}<span class="dim">Nothing</span>{/if}
                                    </td>
                                    <td class="r">{#if saved.length}{rel(tsSec(lastOf(g)))}{:else}<span class="dim">—</span>{/if}</td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                    {#if !coverage}<div class="ui-empty">Loading…</div>{/if}
                </div>
                {#if coverage}
                    <div class="ui-card-foot">
                        <span>Second copy: {#if !coverage.copy_to}off, snapshots only live on the Mac's own disk{:else if !coverage.copy}{home(coverage.copy_to)}, not made yet{:else if coverage.copy.ok}{home(coverage.copy_to)}, {rel(tsSec(coverage.copy.at))}{:else}<span class="bad">{home(coverage.copy_to)} failed: {coverage.copy.why}</span>{/if}</span>
                        <span>Click a row to change what's saved</span>
                    </div>
                {/if}
            </section>

        {:else}
            <section class="ui-card">
                <div class="ui-tbl-wrap">
                    <table class="ui-tbl list runs">
                        <colgroup><col class="w-when" /><col class="w-how" /><col class="w-took" /><col /><col class="w-log" /></colgroup>
                        <thead><tr><th>Started</th><th>How</th><th class="r">Took</th><th>Result</th><th></th></tr></thead>
                        <tbody>
                            {#each runs || [] as r (r.timestamp)}
                                <tr class="click" on:click={() => openRun = openRun === r.timestamp ? null : r.timestamp}>
                                    <td><span class="strong">{fmtDate(r.started)}</span><small>{rel(r.started)}{#if r.seconds}<span class="tk">{' · ' + took(r.seconds)}</span>{/if}</small></td>
                                    <td class="dim">{r.manual ? 'Back up now' : 'Scheduled'}</td>
                                    <td class="r num">{took(r.seconds)}</td>
                                    <td class="wrap">{#if r.state === 'running'}Running…{:else if r.state === 'failed'}<span class="bad">{r.problems[0] || 'Didn’t finish'}{r.problems.length > 1 ? ` (+${r.problems.length - 1} more)` : ''}</span>{:else}<span class="dim">OK</span>{/if}</td>
                                    <td class="r"><span class="loglink">{openRun === r.timestamp ? 'Hide log' : 'Log'}</span></td>
                                </tr>
                                {#if openRun === r.timestamp}
                                    <tr class="logrow"><td colspan="5"><pre>{r.log ? r.log.join('\n') : 'Started with Back up now; its output isn’t kept.'}</pre></td></tr>
                                {/if}
                            {/each}
                        </tbody>
                    </table>
                    {#if !runs}<div class="ui-empty">Loading…</div>{:else if !runs.length}<div class="ui-empty">No runs yet.</div>{/if}
                </div>
            </section>
        {/if}
    {/if}
</div>

<Modal open={!!editing} title="Back up {editing?.name}" description="Pick what on {editing?.kind === 'host' ? 'this computer' : 'the machine'} to save. It goes into every backup from the next run on, kept like the rest." width={520} onClose={() => !savingM && (editing = null)}>
    {#if editing}
        <div class="pick">
            {#if editing.containers}
                <label class="prow"><input type="checkbox" bind:checked={choice.containers} /><span class="pp">Containers<small>Compose stacks and every Docker volume</small></span></label>
            {/if}
            {#if offering}<div class="dim pad"><Loader2 size={13} class="ui-spin" /> Looking inside {editing.name}…</div>{/if}
            {#if offerErr}<div class="dim pad">{offerErr}</div>{/if}
            {#if editing.mac && editing.fda === false}<div class="dim pad">Without Full Disk Access, macOS keeps the agent out of Documents, Desktop and Downloads. Allow it under System Settings → Privacy & Security → Full Disk Access → Arrakis Agent.</div>{/if}
            {#each rows as f (f.path)}
                <label class="prow"><input type="checkbox" checked={choice.folders.includes(f.path)} on:change={() => toggle(f.path)} /><span class="pp ui-mono" title={f.path}>{f.path.replace(/^\/(Users|home)\/[^/]+(?=\/|$)/, '~')}</span><span class="dim num">{f.bytes == null ? (measuring ? 'measuring…' : '') : f.bytes ? fmtSize(f.bytes) : 'empty'}</span></label>
            {/each}
            <form class="padd" on:submit|preventDefault={addPath}>
                <input class="ui-input" placeholder="Another folder, e.g. /home/me/data" bind:value={newPath} />
                <button class="ui-btn sm" type="submit" disabled={!newPath.trim()}>Add</button>
            </form>
            {#if saveErr}<div class="bad">{saveErr}</div>{/if}
        </div>
    {/if}
    <svelte:fragment slot="footer">
        <button class="ui-btn" on:click={() => editing = null} disabled={savingM}>Cancel</button>
        <button class="ui-btn primary" on:click={saveMachine} disabled={savingM}>{savingM ? 'Saving…' : 'Save'}</button>
    </svelte:fragment>
</Modal>

<style>
    .summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .id { display: flex; align-items: center; gap: 16px; }
    .icon { width: 52px; height: 52px; border-radius: 12px; display: flex; align-items: center; justify-content: center; background: var(--accent-soft); color: var(--accent); flex-shrink: 0; }
    .ui-head h1 { line-height: 1.2; }
    .id .ui-meta { margin-top: 6px; }
    .strong { font-weight: 500; color: var(--text-primary); }
    .dim { color: var(--text-secondary); }
    .bad { color: var(--red); }
    .num { font-variant-numeric: tabular-nums; white-space: nowrap; }
    .r, th.r { text-align: right; }

    /* the three lists: a main line with a grey line under it */
    .list { table-layout: fixed; }
    .list td { vertical-align: top; overflow: hidden; text-overflow: ellipsis; }
    .list td small { display: block; margin-top: 2px; font-size: 12px; color: var(--text-secondary); }
    .list td.wrap { white-space: normal; }
    tr.click:hover .strong { text-decoration: underline; text-decoration-color: var(--border-strong); text-underline-offset: 3px; }
    .sep { margin: 0 4px 0 8px; color: var(--text-secondary); opacity: 0.6; }

    .w-when { width: 210px; } .w-size { width: 120px; } .w-act { width: 60px; }
    .w-who { width: 240px; } .w-last { width: 130px; }
    .w-how { width: 140px; } .w-took { width: 90px; } .w-log { width: 90px; }
    .list td:last-child { overflow: visible; }

    .pick { display: flex; flex-direction: column; gap: 2px; }
    .prow { display: flex; align-items: center; gap: 10px; padding: 8px 4px; border-bottom: 1px solid var(--border); cursor: pointer; font-size: 13.5px; }
    .prow input { accent-color: var(--accent); }
    .pp { flex: 1; min-width: 0; display: flex; flex-direction: column; color: var(--text-primary); }
    .pp small { font-size: 12px; color: var(--text-secondary); font-family: inherit; }
    .pad { padding: 8px 4px; font-size: 13px; display: flex; align-items: center; gap: 6px; }
    .padd { display: flex; gap: 8px; margin-top: 10px; }
    .padd .ui-input { flex: 1; }
    .pick .bad { font-size: 13px; margin-top: 6px; }
    .loglink { font-size: 12.5px; color: var(--text-secondary); }
    tr.click:hover .loglink { color: var(--text-primary); }
    .logrow td { padding: 0 20px 14px !important; background: none !important; }
    .logrow pre { margin: 0; padding-left: 12px; border-left: 2px solid var(--border-strong); font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.6; color: var(--text-secondary); white-space: pre-wrap; }

    @media (max-width: 1100px) { .summary { grid-template-columns: 1fr 1fr; } }
    @media (max-width: 760px) {
        .w-when { width: 140px; } .w-who { width: 130px; } .w-last { width: 90px; } .w-size { width: 90px; } .w-act { width: 44px; }
        .w-how { width: 0; } .runs th:nth-child(2), .runs td:nth-child(2) { padding: 0; font-size: 0; }
        .w-log { width: 64px; }
        .list th { white-space: normal; }
    }
    @media (max-width: 560px) { .summary { grid-template-columns: 1fr; } }
    /* phone: what's inside is on the snapshot's own page; the list keeps date and size */
    @media (max-width: 640px) { table.snaps .ct { display: none; } table.snaps .w-when { width: auto; } }
    /* phone runs: the date on one line, how long it took on the grey line under it */
    .runs .tk { display: none; }
    @media (max-width: 640px) {
        .runs .w-when { width: auto; } .runs td:first-child { white-space: nowrap; }
        .runs .w-took { width: 0; } .runs th:nth-child(3), .runs td:nth-child(3) { padding: 0; font-size: 0; }
        .runs .tk { display: inline; }
        .runs col:nth-child(4) { width: 72px; }
    }
</style>
