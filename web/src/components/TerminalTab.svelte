<script>
    import { onMount } from 'svelte';
    import { Terminal, Plus, ExternalLink, Pencil, X, Loader2, Download, Columns2, Rows2, Maximize2, Minimize2, Send, Play, Bookmark, Trash2, Laptop, Server, Box, RotateCw, ArrowLeft, Square, Copy } from 'lucide-svelte';
    import { machines, visible } from '../lib/stores.js';
    import { hosts, hostIcon, arrakisModel } from '../lib/hosts.js';
    import { act, sendLine, sessionUrl, presets, fetchPresets, savePresets } from '../lib/terminal.js';
    import ActionMenu from './ui/ActionMenu.svelte';
    import ResourceCard from './ui/ResourceCard.svelte';
    import Modal from './ui/Modal.svelte';
    import Switch from './ui/Switch.svelte';
    import Tabs from './ui/Tabs.svelte';

    // Routes: #terminal (sessions), #terminal/<where>:<name>, where = "mac", a machine name or a host id
    export let sessions = [];
    export let section = null;
    export let onNavigate = () => {};
    export let refresh = () => {};

    const toast = (m) => window.showToast?.(m);
    $: vm = $machines?.dashboard_vm || 'the VM';
    // "casaos:work" -> where "casaos", short "work"; "vm:" is an old alias for the dashboard machine
    $: where = (s) => { const w = s.where || s.name.split(':')[0]; return w === 'vm' ? vm : w; };
    const short = (s) => s.name.split(':').slice(1).join(':');
    const place = (w) => w === 'mac' ? 'the Mac' : w;
    $: running = ($machines?.machines || []).filter(m => m.state === 'running').map(m => m.name);
    $: remotes = ($hosts || []).filter(h => h.online && !running.includes(h.id)).map(h => h.id);
    // other hosts are reached over SSH from the Mac
    $: targets = ['mac', ...running, ...remotes];
    const label = (s) => { const n = short(s); return n.startsWith('cmd_') ? n.slice(4) : n; };
    const openUrl = (s) => `/terminal?session=${encodeURIComponent(s.name)}`;
    const tilde = (p) => (p || '').replace(/^\/(Users|home)\/[^/]+/, '~').replace(/^\/root(?=\/|$)/, '~');
    // the folder, unless it's just home
    const folder = (p) => { const t = tilde(p); return t === '~' ? '' : t; };

    let now = Date.now();
    onMount(() => {
        const t = setInterval(() => now = Date.now(), 1000);
        // ⌘T / the command palette ask for a new session
        const openNew = () => { window.__arrakisNewSession = false; if (!section) newOpen = true; };
        if (window.__arrakisNewSession) openNew();
        window.addEventListener('arrakis:new-session', openNew);
        fetchPresets();
        return () => { clearInterval(t); window.removeEventListener('arrakis:new-session', openNew); };
    });
    function since(epoch) {
        if (!epoch) return '—';
        const s = Math.max(0, Math.floor(now / 1000 - epoch)), d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
        return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
    }
    function ago(epoch) {
        if (!epoch) return '';
        const s = Math.max(0, Math.floor(now / 1000 - epoch));
        return s < 60 ? 'just now' : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : `${Math.floor(s / 86400)}d ago`;
    }

    $: isSess = !!section && section.includes(':');
    $: session = isSess && sessions.find(s => s.name === section);
    // a session that was only just started (a Shell button, a saved command) isn't in the
    // polled list yet: ask for the list again for a few seconds before calling it ended
    let missing = null, missingAt = 0;
    $: if (isSess && !session && missing !== section) { missing = section; missingAt = Date.now(); refresh(); }
    $: if (session) missing = null;
    $: waiting = isSess && !session && now - missingAt < 6000;
    onMount(() => { const t = setInterval(() => isSess && !session && now - missingAt < 6000 && refresh(), 1500); return () => clearInterval(t); });
    $: onMac = sessions.filter(s => where(s) === 'mac').length;
    $: machineCount = new Set(sessions.map(where).filter(w => w !== 'mac')).size;
    $: attached = sessions.filter(s => s.attached).length;

    // sessions grouped by where they run: the Mac, then machines, then other hosts
    const rank = (w) => w === 'mac' ? 0 : running.includes(w) ? 1 : 2;
    $: groups = [...new Set(sessions.map(where))]
        .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
        .map(w => ({ where: w, kind: rank(w), list: sessions.filter(s => where(s) === w).sort((a, b) => short(a).localeCompare(short(b))) }));
    const groupIcon = (k) => k === 0 ? Laptop : k === 1 ? Box : Server;
    const groupKind = (k) => k === 0 ? 'This Mac' : k === 1 ? 'OrbStack machine' : 'Host over SSH';

    // ---- new session --------------------------------------------------------------------
    let newOpen = false, creating = false, saveIt = false;
    let form = { name: '', target: 'mac', command: '', cwd: '' };
    $: nameOk = /^[a-zA-Z0-9_-]+$/.test(form.name.trim());
    $: taken = sessions.some(s => s.name === `${form.target}:${form.name.trim()}`);
    function newOn(w) { form = { name: '', target: w, command: '', cwd: '' }; saveIt = false; newOpen = true; }
    async function create() {
        creating = true;
        try {
            const j = await fetch('/api/tmux/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.name.trim(), target: form.target, command: form.command.trim() || undefined, cwd: form.cwd.trim() || undefined }) }).then(r => r.json());
            if (j.status === 'success') {
                if (saveIt) await savePresets([...$presets, { label: form.name.trim(), name: form.name.trim(), target: form.target, command: form.command.trim(), cwd: form.cwd.trim() }]);
                toast(j.message ? `${j.message}; session ${form.name.trim()} started` : `Session ${form.name.trim()} started`);
                newOpen = false; form = { name: '', target: form.target, command: '', cwd: '' };
                refresh(); setTimeout(() => onNavigate('Terminal', j.session), 600);
            }
            else toast(j.message || 'Could not start the session');
        } catch (e) { toast('Could not start the session'); }
        creating = false;
    }

    // ---- saved commands -------------------------------------------------------------------
    let launching = null;
    async function runPreset(p) {
        // the window has to be opened inside the click, or the browser blocks it
        const w = p.open_window ? window.open('about:blank', '_blank') : null;
        launching = p.id;
        try {
            const j = await fetch(`/api/tmux/presets/${p.id}/run`, { method: 'POST' }).then(r => r.json());
            if (j.status === 'success') {
                if (j.message) toast(j.message);
                else if (j.restarted) toast(`Restarted ${p.label}`);
                if (w) w.location = `/terminal?session=${encodeURIComponent(j.session)}`;
                else onNavigate('Terminal', j.session);
                refresh(); fetchPresets();
            } else { w?.close(); toast(j.message || 'Could not start it'); }
        } catch (e) { w?.close(); toast('Could not start it'); }
        launching = null;
    }
    // reactive, so the cards notice when the session list arrives or changes
    $: liveNames = new Set(sessions.map(s => s.name));
    $: isLive = (p) => liveNames.has(`${p.target}:${p.name}`);
    const slug = (t) => (t || '').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
    // the saved-commands editor: a copy of the picked one (or a new one) until it's saved
    let editing = null, editIsNew = false, nameTouched = false, editOrig = '', editOrigLabel = '';
    const BLANK = { id: null, label: '', name: '', target: 'mac', command: '', cwd: '', notes: '', mode: 'reuse', open_window: false };
    function editPreset(p, stay = false) {
        editing = p ? { ...p } : { ...BLANK };
        editOrig = JSON.stringify(editing);
        editOrigLabel = editing.label || editing.name;
        confirmDel = null;
        editIsNew = !p; nameTouched = !!p;
        if (!stay && section !== 'saved') onNavigate('Terminal', 'saved');
    }
    $: tab = section === 'saved' ? 'saved' : 'sessions';
    $: if (tab !== 'saved' && editing) editing = null;
    $: dirty = !!editing && JSON.stringify(editing) !== editOrig;
    $: editOk = !!editing && /^[a-zA-Z0-9_-]+$/.test((editing.name || '').trim());
    async function saveEdit() {
        const e = { ...editing, name: editing.name.trim(), label: editing.label.trim() || editing.name.trim() };
        const list = editIsNew ? [...$presets, e] : $presets.map(p => p.id === e.id ? e : p);
        if (await savePresets(list)) {
            toast(editIsNew ? `Saved ${e.label}` : 'Changes saved');
            editing = null;
        }
    }
    let confirmDel = null;
    async function removePreset(p) { confirmDel = null; if (await savePresets($presets.filter(x => x.id !== p.id))) toast(`Deleted ${p.label}`); }
    // a copy opens as a new, unsaved one with a free session name
    function duplicate(p) {
        let i = 2;
        while ($presets.some(x => x.name === `${p.name}-${i}`)) i++;
        editPreset(null);
        editing = { ...p, id: null, label: `${p.label} copy`, name: `${p.name}-${i}` };
        nameTouched = true;
    }
    const pmenu = (p, i) => [
        { label: 'Edit', icon: Pencil, onClick: () => editPreset(p) },
        { label: 'Duplicate', icon: Copy, onClick: () => duplicate(p) },
        { label: 'Delete…', icon: Trash2, danger: true, divider: true, onClick: () => confirmDel = p.id },
    ].filter(Boolean);
    // stop ends its tmux session; restart ends it and starts it again
    let confirmStop = null;
    const endSession = (p) => fetch(sessionUrl(`${p.target}:${p.name}`), { method: 'DELETE' });
    async function stopPreset(p) {
        confirmStop = null;
        try { await endSession(p); toast(`Stopped ${p.label}`); } catch (e) { toast('Could not stop it'); }
        refresh();
    }
    async function restartPreset(p) {
        launching = p.id;
        try { await endSession(p); } catch (e) {}
        await runPreset(p);
    }
    // the card's icon is where it runs, as in the sidebar: the Mac, a machine, another host
    const hostOf = (t) => ($hosts || []).find(h => h.id === t)?.report;
    const whereIcon = (t) => t === 'mac' ? hostIcon($arrakisModel, 'macOS')
        : ($machines?.machines || []).some(m => m.name === t) ? Box
        : hostIcon(hostOf(t)?.model, hostOf(t)?.os);
    const offline = (t) => t !== 'mac' && !targets.includes(t);

    // ---- rename / kill ------------------------------------------------------------------
    // by name: the poller replaces the session objects on every refresh
    let renaming = null, newName = '', confirmKill = null;
    function startRename(s) { renaming = s; newName = short(s); }
    async function rename() {
        const s = renaming; renaming = null;
        try {
            const j = await fetch(sessionUrl(s.name), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_name: newName.trim() }) }).then(r => r.json());
            if (j.status === 'success') { toast('Renamed'); refresh(); if (section === s.name) onNavigate('Terminal', `${where(s)}:${newName.trim()}`); }
            else toast(j.message || 'Rename failed');
        } catch (e) { toast('Rename failed'); }
    }
    async function kill(s) {
        confirmKill = null;
        try { await fetch(sessionUrl(s.name), { method: 'DELETE' }); toast(`Session ${label(s)} ended`); }
        catch (e) { toast('Could not end the session'); }
        refresh();
        if (section === s.name) onNavigate('Terminal', null);
    }
    const menu = (s) => [
        { label: 'Details', icon: Terminal, onClick: () => onNavigate('Terminal', s.name) },
        { label: 'Download scrollback', icon: Download, onClick: () => window.location.href = sessionUrl(s.name, '/scrollback') },
        { label: 'Rename', icon: Pencil, onClick: () => startRename(s) },
        { label: 'End session…', icon: X, danger: true, divider: true, onClick: () => confirmKill = s.name },
    ];

    // ---- windows and panes of the open session ------------------------------------------------
    let windows = [], winFor = null;
    async function loadWindows() {
        if (!session) return;
        const name = session.name;
        try { const j = await fetch(sessionUrl(name, '/windows')).then(r => r.json()); if (j.status === 'success' && section === name) windows = j.windows; } catch (e) {}
    }
    $: if (session && session.name !== winFor) { winFor = session.name; windows = []; loadWindows(); }
    onMount(() => { const t = setInterval(() => session && visible() && loadWindows(), 2000); return () => clearInterval(t); });
    $: activeWin = windows.find(w => w.active);
    $: paneCount = windows.reduce((a, w) => a + w.panes.length, 0) || session?.windows || 0;
    async function doAct(body) {
        const j = await act(session.name, body);
        if (j.status !== 'success') toast(j.message || 'tmux said no');
        await loadWindows();
    }
    let renamingWin = null, winName = '';
    function startWinRename(w) { renamingWin = w.index; winName = w.name; }
    async function finishWinRename() {
        const idx = renamingWin; renamingWin = null;
        if (winName.trim()) await doAct({ action: 'rename', window: idx, name: winName.trim() });
    }
    const focusEl = (n) => { n.focus(); n.select(); };

    // ---- the send line -----------------------------------------------------------------------
    let line = '', sending = false;
    async function send() {
        if (!line.trim() || sending) return;
        sending = true;
        const j = await sendLine(session.name, line);
        if (j.status === 'success') line = ''; else toast(j.message || 'Could not send');
        sending = false;
    }
</script>

{#if session}
    <div class="ui-page">
        <div class="ui-head">
            <div class="id">
                <span class="icon"><Terminal size={22} /></span>
                <div>
                    <h1>{label(session)}</h1>
                    <div class="ui-meta"><span>tmux on {place(where(session))}</span>{#if folder(session.path)}<span class="ui-mono">{folder(session.path)}</span>{/if}</div>
                </div>
            </div>
            <div class="ui-head-actions">
                <a class="ui-btn primary" href={openUrl(session)} target="_blank"><ExternalLink size={14} /> Open terminal</a>
                <a class="ui-btn" href={sessionUrl(session.name, '/scrollback')} title="The whole history of the active pane, as a text file"><Download size={14} /> Scrollback</a>
                {#if confirmKill === session.name}
                    <button class="ui-btn" on:click={() => confirmKill = null}>Keep</button>
                    <button class="ui-btn danger" on:click={() => kill(session)}>End session</button>
                {:else}
                    <ActionMenu items={[{ label: 'Rename', icon: Pencil, onClick: () => startRename(session) }, { label: 'End session…', icon: X, danger: true, divider: true, onClick: () => confirmKill = session.name }]} label="More actions" />
                {/if}
            </div>
        </div>

        <div class="summary four">
            <div class="ui-stat"><span class="ui-stat-label">Running</span><span class="ui-stat-value small">{session.command || '—'}</span><span class="ui-stat-sub">in the active pane</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Windows</span><span class="ui-stat-value">{session.windows}</span><span class="ui-stat-sub">{paneCount} {paneCount === 1 ? 'pane' : 'panes'} in all</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Last output</span><span class="ui-stat-value small">{session.activity ? ago(session.activity) : '—'}</span><span class="ui-stat-sub">{session.attached ? 'open in a terminal now' : 'not open anywhere'}</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Running for</span><span class="ui-stat-value small">{since(session.created)}</span><span class="ui-stat-sub">started {new Date(session.created * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span></div>
        </div>

        <section class="ui-card">
            <div class="ui-card-head grp">
                <div><h2 class="ui-card-title">Windows</h2><p class="ui-card-desc">The shown window is what an open terminal displays. Double-click a name to rename it.</p></div>
                <button class="ui-btn sm" on:click={() => doAct({ action: 'new' })}><Plus size={13} /> New window</button>
            </div>
            <div class="ui-tbl-wrap">
                <table class="ui-tbl">
                    <colgroup><col /><col /><col class="w-act" /></colgroup>
                    <thead><tr><th>Window</th><th>Panes</th><th></th></tr></thead>
                    <tbody>
                        {#each windows as w (w.index)}
                            <tr>
                                <td>
                                    <div class="sn"><span class="ic">{w.index}</span>
                                        <span class="sx">
                                            {#if renamingWin === w.index}
                                                <input class="ui-input mono win-in" bind:value={winName} use:focusEl on:blur={finishWinRename}
                                                    on:keydown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') { winName = ''; e.currentTarget.blur(); } }} />
                                            {:else}<span class="nm plain" on:dblclick={() => startWinRename(w)} role="button" tabindex="-1">{w.name}</span>{/if}
                                            <small>{w.active ? 'Shown' : 'In the background'}{w.zoomed ? ' · one pane zoomed' : ''}</small>
                                        </span>
                                    </div>
                                </td>
                                <td>
                                    <div class="panes">
                                        {#each w.panes as p (p.index)}
                                            {#if w.panes.length > 1}
                                                <span class="ui-tag pane" class:on={p.active}>
                                                    <button on:click={() => doAct({ action: 'pane', window: w.index, pane: p.index })} title="Make this the active pane">{p.command}</button>
                                                    <button class="px" on:click={() => doAct({ action: 'kill-pane', window: w.index, pane: p.index })} aria-label="Close pane {p.index}"><X size={11} /></button>
                                                </span>
                                            {:else}<span class="ui-mono">{p.command}</span>{/if}
                                        {/each}
                                    </div>
                                </td>
                                <td>
                                    <span class="ui-btns">
                                        {#if !w.active}<button class="ui-btn sm" on:click={() => doAct({ action: 'select', window: w.index })}>Show</button>{/if}
                                        <ActionMenu label="Actions for window {w.name}" items={[
                                            { label: 'Split right', icon: Columns2, onClick: () => doAct({ action: 'split', window: w.index, dir: 'right' }) },
                                            { label: 'Split down', icon: Rows2, onClick: () => doAct({ action: 'split', window: w.index, dir: 'down' }) },
                                            w.panes.length > 1 ? { label: w.zoomed ? 'Show all panes' : 'Zoom the active pane', icon: w.zoomed ? Minimize2 : Maximize2, onClick: () => doAct({ action: 'zoom', window: w.index }) } : null,
                                            { label: 'Rename', icon: Pencil, onClick: () => startWinRename(w) },
                                            windows.length > 1 ? { label: 'Close window', icon: X, danger: true, divider: true, onClick: () => doAct({ action: 'close', window: w.index }) } : null,
                                        ].filter(Boolean)} />
                                    </span>
                                </td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </div>
        </section>

        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Send a command</h2><p class="ui-card-desc">Types a line into the active pane and presses Enter, without opening the terminal.</p></div></div>
            <form class="sendbar" on:submit|preventDefault={send}>
                <input class="ui-input mono" bind:value={line} placeholder="git pull" autocomplete="off" spellcheck="false" />
                <button class="ui-btn" type="submit" disabled={!line.trim() || sending}><Send size={13} /> Send</button>
            </form>
        </section>
    </div>

{:else if isSess && waiting}
    <div class="ui-page"><div class="ui-head"><div><h1>{section.split(':').slice(1).join(':')}</h1><p><Loader2 size={13} class="ui-spin" /> Opening the session…</p></div></div></div>

{:else if isSess}
    <div class="ui-page"><div class="ui-head"><div><h1>{section.split(':').slice(1).join(':')}</h1><p>This session has ended or its machine is stopped. <button class="ui-link" on:click={() => onNavigate('Terminal', null)}>All sessions</button></p></div></div></div>

{:else}
    <div class="ui-page">
        <div class="ui-head">
            <div><h1>Terminal</h1><p>tmux sessions on the Mac, your machines and your other hosts. They keep running when you close the browser.</p></div>
            <div class="ui-head-actions">
                <button class="ui-btn primary" on:click={() => newOn(form.target)}><Plus size={15} /> New session</button>
            </div>
        </div>

        <div class="summary">
            <div class="ui-stat"><span class="ui-stat-label">Sessions</span><span class="ui-stat-value">{sessions.length}</span><span class="ui-stat-sub">{onMac} on the Mac · {sessions.length - onMac} on {machineCount} {machineCount === 1 ? 'machine' : 'machines'}</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Attached</span><span class="ui-stat-value">{attached}</span><span class="ui-stat-sub">open in a terminal right now</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Shortcut</span><span class="ui-stat-value small">⌘ T</span><span class="ui-stat-sub">new session from anywhere in the dashboard</span></div>
        </div>

        <Tabs tabs={[{ id: 'sessions', label: 'Sessions' }, { id: 'saved', label: 'Saved commands' }]} active={tab} onSelect={(t) => onNavigate('Terminal', t === 'sessions' ? null : t)} />

        {#if tab === 'sessions'}
        <!-- saved commands: one click starts the session (or opens it if it's running) -->
        <div class="quick">
            {#each $presets as p (p.id)}
                {@const live = isLive(p)}
                <button class="ui-btn quick-btn" on:click={() => runPreset(p)} disabled={launching === p.id || (p.target !== 'mac' && !targets.includes(p.target))}
                    title="{p.command || 'A shell'}{p.cwd ? ' in ' + p.cwd : ''}{live ? (p.mode === 'restart' ? ' (running; starts it again)' : ' (running; opens it)') : ''}">
                    {#if launching === p.id}<Loader2 size={13} class="ui-spin" />{:else if live && p.mode !== 'restart'}<ExternalLink size={13} />{:else if live}<RotateCw size={13} />{:else}<Play size={13} />{/if}
                    {p.label}{#if p.target !== 'mac'}<span class="q-where">{p.target}</span>{/if}
                </button>
            {/each}
            {#if $presets.length}
                <button class="ui-btn quick-edit" on:click={() => onNavigate('Terminal', 'saved')} title="Edit saved commands" aria-label="Edit saved commands"><Pencil size={13} /></button>
            {:else}
                <button class="ui-btn quick-add" on:click={() => editPreset(null)}><Bookmark size={13} /> Save a command for one-click start</button>
            {/if}
        </div>

        {#each groups as g (g.where)}
            <section class="ui-card">
                <div class="ui-card-head grp">
                    <div><h2 class="ui-card-title">{g.where === 'mac' ? 'The Mac' : g.where}</h2><p class="ui-card-desc">{g.kind === 0 ? '' : groupKind(g.kind) + ' · '}{g.list.length} {g.list.length === 1 ? 'session' : 'sessions'}</p></div>
                </div>
                <div class="ui-tbl-wrap">
                    <table class="ui-tbl">
                        <colgroup><col /><col class="w-on" /><col class="w-n" /><col class="w-on" /><col class="w-act" /></colgroup>
                        <thead><tr><th>Session</th><th class="c-sm">Running</th><th class="c-sm">Windows</th><th class="c-sm">Last output</th><th></th></tr></thead>
                        <tbody>
                            {#each g.list as s (s.name)}
                                <tr class="click" on:click={() => onNavigate('Terminal', s.name)}>
                                    <td><div class="sn"><span class="ic"><Terminal size={14} /></span><span class="sx"><span class="nm">{label(s)}</span>{#if folder(s.path)}<small class="ui-mono">{folder(s.path)}</small>{/if}</span></div></td>
                                    <td class="c-sm ui-mono">{s.command || '—'}</td>
                                    <td class="c-sm num">{s.windows}</td>
                                    <td class="c-sm num">{s.activity ? ago(s.activity) : '—'}</td>
                                    <td on:click|stopPropagation role="presentation">
                                        {#if confirmKill === s.name}
                                            <span class="ui-btns"><button class="ui-btn sm" on:click={() => confirmKill = null}>Keep</button><button class="ui-btn sm danger" on:click={() => kill(s)}>End</button></span>
                                        {:else}
                                            <span class="ui-btns"><a class="ui-btn sm" href={openUrl(s)} target="_blank">Open</a><ActionMenu items={menu(s)} label="Actions for {label(s)}" /></span>
                                        {/if}
                                    </td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </section>
        {:else}
            <section class="ui-card empty">
                <span class="empty-ic"><Terminal size={22} /></span>
                <h2>No sessions running</h2>
                <p>Start a shell on the Mac, one of your machines or another host. It keeps running in tmux after you close the tab, and you can come back to it from here.</p>
                <button class="ui-btn primary" on:click={() => newOn('mac')}><Plus size={15} /> New session</button>
            </section>
        {/each}
        {:else}
            {#if $presets.length}
                <div class="pbar"><span class="ui-dim">{$presets.length} saved · also one click away on Sessions</span><button class="ui-btn sm" on:click={() => editPreset(null)}><Plus size={13} /> New saved command</button></div>
                <!-- one card per command, the same card as the hosts; open one to edit it -->
                <div class="ui-cardgrid">
                    {#each $presets as p, i (p.id)}
                        {@const live = isLive(p)}
                        <ResourceCard name={p.label} icon={whereIcon(p.target)} on={live} off={offline(p.target)} on:open={() => editPreset(p)}
                            sub="{place(p.target) === 'the Mac' ? 'The Mac' : p.target}{offline(p.target) ? ' · offline' : ''}"
                            meters={[
                                { k: 'Command', v: p.command || 'A shell' },
                                { k: 'Folder', v: p.cwd || '~' },
                            ]}
                            note={live ? 'Running now' : p.last_run ? `Last run ${ago(p.last_run)}` : 'Never run'}
                            lan={p.name}>
                            <svelte:fragment slot="status">
                                <span class="acts" on:click|stopPropagation on:keydown|stopPropagation role="presentation">
                                    {#if confirmDel === p.id || confirmStop === p.id}
                                        <button class="ui-btn sm" on:click={() => { confirmDel = null; confirmStop = null; }}>Keep</button>
                                        {#if confirmDel === p.id}<button class="ui-btn sm danger" on:click={() => removePreset(p)}>Delete</button>
                                        {:else}<button class="ui-btn sm danger" on:click={() => stopPreset(p)}>Stop</button>{/if}
                                    {:else}
                                        {#if launching === p.id}
                                            <span class="ib"><Loader2 size={15} class="ui-spin" /></span>
                                        {:else if live}
                                            <a class="ib" href={openUrl({ name: `${p.target}:${p.name}` })} target="_blank" title="Open" aria-label="Open {p.label}"><ExternalLink size={15} /></a>
                                            <button class="ib" on:click={() => restartPreset(p)} title="Restart" aria-label="Restart {p.label}"><RotateCw size={15} /></button>
                                            <button class="ib" on:click={() => confirmStop = p.id} title="Stop" aria-label="Stop {p.label}"><Square size={14} /></button>
                                        {:else}
                                            <button class="ib" on:click={() => runPreset(p)} disabled={offline(p.target)} title={offline(p.target) ? `${p.target} is offline` : 'Start'} aria-label="Start {p.label}"><Play size={15} /></button>
                                        {/if}
                                        <ActionMenu items={pmenu(p, i)} label="Actions for {p.label}" />
                                    {/if}
                                </span>
                            </svelte:fragment>
                        </ResourceCard>
                    {/each}
                </div>
            {:else}
                <section class="ui-card empty">
                    <span class="empty-ic"><Bookmark size={22} /></span>
                    <h2>No saved commands</h2>
                    <p>Save a session you start often, like a dev server or <span class="ui-mono">htop</span> on a machine. It gets a one-click button on the Sessions tab.</p>
                    <button class="ui-btn primary" on:click={() => editPreset(null)}><Plus size={15} /> New saved command</button>
                </section>
            {/if}
        {/if}
    </div>
{/if}

<Modal bind:open={newOpen} title="New session" description="A tmux session that keeps running in the background." width={500}>
    <div class="fields">
        <div class="ui-field">
            <label for="t-name">Name</label>
            <input id="t-name" class="ui-input mono" placeholder="work" autocomplete="off" bind:value={form.name} class:bad={form.name && (!nameOk || taken)} />
            <span class="ui-hint">{form.name && !nameOk ? 'Letters, digits, dashes and underscores only' : taken ? 'A session with this name is running there' : ' '}</span>
        </div>
        <div class="ui-field">
            <span class="ui-label">Runs on</span>
            <div class="ui-seg targets">{#each targets as t}<button class:on={form.target === t} on:click={() => form.target = t}>{t === 'mac' ? 'The Mac' : t}</button>{/each}</div>
            {#if form.target !== 'mac'}<span class="ui-hint">If tmux isn't installed on {form.target}, it's installed first.</span>{/if}
        </div>
        <div class="ui-field">
            <label for="t-cwd">Starting folder <span class="opt">optional</span></label>
            <input id="t-cwd" class="ui-input mono" placeholder="~/projects/app" autocomplete="off" bind:value={form.cwd} />
            <span class="ui-hint">On {place(form.target)}; empty starts in the home folder. New windows open where you are.</span>
        </div>
        <div class="ui-field">
            <label for="t-cmd">Command <span class="opt">optional</span></label>
            <input id="t-cmd" class="ui-input mono" placeholder="htop" autocomplete="off" bind:value={form.command} />
            <span class="ui-hint">Runs instead of a shell; the session ends when it exits.</span>
        </div>
        <Switch bind:checked={saveIt}>Also add it to saved commands</Switch>
    </div>
    <svelte:fragment slot="footer">
        <button class="ui-btn" on:click={() => newOpen = false}>Cancel</button>
        <button class="ui-btn primary" disabled={creating || !nameOk || taken} on:click={create}>{#if creating}<Loader2 size={14} class="ui-spin" />{/if} Start session</button>
    </svelte:fragment>
</Modal>
<!-- a saved command, new or edited: the same dialog as New session, plus what its button does -->
<Modal open={!!editing} title={editIsNew ? 'New saved command' : `Edit ${editOrigLabel}`} description="A one-click start for a session you use often." width={500} onClose={() => editing = null}>
    {#if editing}
        <div class="fields">
            <div class="ui-field">
                <label for="p-label">Name</label>
                <input id="p-label" class="ui-input" placeholder="Dev server" autocomplete="off" bind:value={editing.label} on:input={() => { if (!nameTouched) editing.name = slug(editing.label); }} />
            </div>
            <div class="ui-field">
                <span class="ui-label">Runs on</span>
                <div class="ui-seg targets">{#each [...new Set([...targets, editing.target])] as t}<button class:on={editing.target === t} on:click={() => editing.target = t}>{t === 'mac' ? 'The Mac' : t}{offline(t) ? ' (offline)' : ''}</button>{/each}</div>
            </div>
            <div class="ui-field">
                <label for="p-cmd">Command <span class="opt">optional</span></label>
                <input id="p-cmd" class="ui-input mono" placeholder="npm run dev" autocomplete="off" spellcheck="false" bind:value={editing.command} />
                <span class="ui-hint">Empty starts a shell. The session ends when the command exits.</span>
            </div>
            <div class="ui-field">
                <label for="p-cwd">Starting folder <span class="opt">optional</span></label>
                <input id="p-cwd" class="ui-input mono" placeholder="~/projects/app" autocomplete="off" spellcheck="false" bind:value={editing.cwd} />
            </div>
            <div class="pair">
                <div class="ui-field">
                    <label for="p-name">tmux session</label>
                    <input id="p-name" class="ui-input mono" class:bad={editing.name && !editOk} placeholder="dev" autocomplete="off" spellcheck="false" bind:value={editing.name} on:input={() => nameTouched = true} />
                </div>
                <div class="ui-field">
                    <span class="ui-label">If it's running</span>
                    <div class="ui-seg"><button class:on={editing.mode === 'reuse'} on:click={() => editing.mode = 'reuse'}>Open it</button><button class:on={editing.mode === 'restart'} on:click={() => editing.mode = 'restart'}>Restart</button></div>
                </div>
            </div>
            {#if editing.name && !editOk}<span class="ui-hint bad-t">Session names use letters, digits, dashes and underscores.</span>{/if}
            <Switch bind:checked={editing.open_window}>Open the terminal in a new window after starting</Switch>
        </div>
    {/if}
    <svelte:fragment slot="footer">
        {#if editing && !editIsNew}
            {#if confirmDel === editing.id}
                <button class="ui-btn danger" on:click={() => { const p = $presets.find(x => x.id === editing.id); editing = null; removePreset(p); }}>Delete it</button>
            {:else}
                <button class="ui-btn danger-outline" on:click={() => confirmDel = editing.id}><Trash2 size={13} /> Delete</button>
            {/if}
            <span class="grow"></span>
        {/if}
        <button class="ui-btn" on:click={() => editing = null}>Cancel</button>
        <button class="ui-btn primary" disabled={!editOk || (!editIsNew && !dirty)} on:click={saveEdit}>{editIsNew ? 'Save' : 'Save changes'}</button>
    </svelte:fragment>
</Modal>


<Modal open={!!renaming} title="Rename session" width={420} onClose={() => renaming = null}>
    <div class="ui-field">
        <label for="t-rn">New name</label>
        <input id="t-rn" class="ui-input mono" bind:value={newName} on:keydown={e => e.key === 'Enter' && /^[a-zA-Z0-9_-]+$/.test(newName.trim()) && rename()} />
    </div>
    <svelte:fragment slot="footer">
        <button class="ui-btn" on:click={() => renaming = null}>Cancel</button>
        <button class="ui-btn primary" disabled={!/^[a-zA-Z0-9_-]+$/.test(newName.trim())} on:click={rename}>Rename</button>
    </svelte:fragment>
</Modal>

<style>
    .summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
    .summary.four { grid-template-columns: repeat(4, 1fr); }
    .ui-stat-value.small { font-size: 18px; font-family: 'JetBrains Mono', monospace; }
    .id { display: flex; align-items: center; gap: 16px; min-width: 0; }
    .icon { width: 52px; height: 52px; border-radius: 12px; display: flex; align-items: center; justify-content: center; background: var(--accent-soft); color: var(--accent); flex-shrink: 0; }
    .ui-head h1 { line-height: 1.2; }
    .id .ui-meta { margin-top: 6px; }
    .grp { align-items: center; }
    /* name cell: icon tile, name, a line under it (as on Databases) */
    .sn { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .sx { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .sx small { font-size: 11.5px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ic { width: 30px; height: 30px; border-radius: 7px; background: var(--accent-soft); color: var(--accent); display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-family: 'JetBrains Mono', monospace; font-size: 12.5px; font-weight: 600; }
    .nm { font-weight: 600; color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .nm.plain { color: var(--text-primary); }
    tr.click:hover .nm { text-decoration: underline; }
    .num { font-variant-numeric: tabular-nums; }
    .w-on { width: 150px; } .w-n { width: 100px; } .w-act { width: 1%; }
    .win-in { height: 28px; width: 200px; }
    .panes { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
    .pane { display: inline-flex; align-items: center; gap: 2px; padding: 0 2px 0 0; }
    .pane > button:first-child { padding: 0 2px 0 6px; color: inherit; cursor: pointer; font: inherit; }
    .pane.on { color: var(--accent); background: var(--accent-soft); }
    .px { display: flex; padding: 2px; border-radius: 3px; color: inherit; opacity: .5; cursor: pointer; }
    .px:hover { opacity: 1; background: var(--highlight-15); }
    /* ---- saved commands: a row of launch buttons ---- */
    .quick { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
    .quick-btn { gap: 7px; }
    .q-where { font-size: 11.5px; color: var(--text-secondary); font-weight: 400; margin-left: 2px; }
    .quick-add { color: var(--text-secondary); border-style: dashed; }
    .quick-edit { padding: 0 9px; color: var(--text-secondary); }

    /* actions in a saved command's card head: drawn like the ⋯ button next to them */
    .pbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 13px; }
    .acts { display: flex; align-items: center; gap: 2px; }
    .ib { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 6px; color: var(--text-secondary); cursor: pointer; }
    .ib:hover:not(:disabled) { background: var(--highlight-10); color: var(--text-primary); }
    .ib:disabled { opacity: .35; cursor: default; }
    .sendbar { display: flex; gap: 8px; padding: 0 20px 18px; }
    .sendbar .ui-input { flex: 1; min-width: 0; }

    .empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 10px; padding: 56px 24px; }
    .empty-ic { width: 52px; height: 52px; border-radius: 14px; background: var(--accent-soft); color: var(--accent); display: flex; align-items: center; justify-content: center; margin-bottom: 4px; }
    .empty h2 { margin: 0; font-size: 16px; font-weight: 600; }
    .empty p { margin: 0 0 8px; max-width: 440px; font-size: 13.5px; color: var(--text-secondary); line-height: 1.5; }
    .fields { display: flex; flex-direction: column; gap: 16px; padding-top: 8px; }
    .targets { flex-wrap: wrap; height: auto; }
    .targets button { height: 32px; }
    .pair { display: grid; grid-template-columns: 1fr auto; gap: 14px; align-items: start; }
    .bad-t { color: var(--red); margin-top: -8px; }
    .grow { flex: 1; }
    .opt { font-weight: 400; color: var(--text-secondary); font-size: 12px; margin-left: 4px; }

    @media (max-width: 900px) { .summary.four { grid-template-columns: 1fr 1fr; } }
    @media (max-width: 768px) {
        .summary { grid-template-columns: 1fr; }
        .sendbar { padding: 0 14px 14px; }
    }
    @media (max-width: 640px) { .ic { display: none; } }
</style>
