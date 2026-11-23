<script>
    import { THEMES, savedTheme, applyTheme } from '../lib/theme.js';
    import { onMount, tick, createEventDispatcher } from 'svelte';
    import { Search, Activity, Boxes, Box, Network, Database, Archive, Terminal, Eye, Settings, Plus, RotateCw, PackageCheck, HardDriveUpload, Gauge, RefreshCw, Server, Cpu, Monitor, Palette, Cloud, HeartPulse, ScrollText } from 'lucide-svelte';
    import { machines } from '../lib/stores.js';
    import { hosts } from '../lib/hosts.js';
    import { services } from '../lib/services.js';
    import { tailnet } from '../lib/tailscale.js';
    import { settingsIndex, openSetting } from '../lib/settingsIndex.js';

    const dispatch = createEventDispatcher();
    const toast = (m) => dispatch('toast', m);
    const go = (hash) => { location.hash = hash; };
    const post = (url) => fetch(url, { method: 'POST' }).then(r => r.json()).catch(() => ({ status: 'error' }));

    let open = false, query = '', selected = 0, inputEl, listEl;
    let confirming = null;      // id of a dangerous command waiting for a second Enter
    let databases = [];

    // ---- commands -----------------------------------------------------------------------
    const PAGES = [
        ['Overview', 'overview', Activity], ['Infrastructure', 'infra', Server], ['OrbStack VM', 'infra/arrakis/vm', Boxes], ['macOS apps', 'infra/arrakis/apps', Box],
        ['Tailscale', 'tailscale', Network], ['Cloudflare', 'cloudflare', Cloud], ['Uptime', 'tools/uptime', HeartPulse], ['Logs', 'logs', ScrollText], ['Databases', 'databases', Database], ['Backups', 'backups', Archive],
        ['Terminal', 'terminal', Terminal], ['API endpoints', 'endpoints', Eye], ['Settings', 'settings', Settings],
    ];
    // the Terminal page opens its "New session" dialog; it may not be mounted yet, so
    // leave a flag it reads on mount as well as an event for when it already is
    function newSession() {
        window.__arrakisNewSession = true;
        go('#terminal');
        window.dispatchEvent(new CustomEvent('arrakis:new-session'));
    }
    function nextTheme() {
        const i = THEMES.findIndex(t => t.id === savedTheme());
        const t = THEMES[(i + 1) % THEMES.length];
        applyTheme(t.id, true);
        toast(`Theme: ${t.label}`);
    }
    const ACTIONS = [
        { id: 'new-session', title: 'New terminal session', hint: '⌘T', icon: Plus, run: newSession },
        { id: 'new-machine', title: 'Create machine', icon: Plus, run: () => go('#infra/orbstack/new') },
        { id: 'add-host', title: 'Add host', icon: Plus, run: () => go('#infra/new') },
        { id: 'backup', title: 'Back up now', icon: HardDriveUpload, run: async () => { toast('Backup started'); const r = await post('/api/host/command/backup'); toast(r.status === 'success' ? 'Backup finished' : 'Backup failed'); } },
        { id: 'speedtest', title: 'Run speed test', icon: Gauge, run: () => { post('/api/network/speedtest'); toast('Speed test started; result in Network tools'); } },
        { id: 'theme', title: 'Next theme', icon: Palette, run: nextTheme },
        { id: 'refresh', title: 'Refresh data', icon: RefreshCw, run: () => { dispatch('refresh'); toast('Refreshing…'); } },
        { id: 'reboot-host', title: 'Reboot the Mac', icon: RotateCw, danger: true, run: async () => { const r = await post('/api/host/command/reboot'); toast(r.status === 'success' ? 'Mac reboot started' : 'Reboot failed: ' + (r.message || r.stderr || 'unknown error')); } },
        { id: 'reboot-vm', title: 'Reboot the dashboard VM', icon: RotateCw, danger: true, run: () => { post('/api/vm/command/reboot'); toast('VM reboot started'); } },
        { id: 'update', title: 'Update packages on the Mac and VM', icon: PackageCheck, danger: true, run: () => { post('/api/host/command/update'); post('/api/vm/command/update'); toast('Updates started'); } },
    ];

    $: items = [
        ...PAGES.map(([t, h, icon]) => ({ id: 'p-' + h, group: 'Go to', title: t, icon, run: () => go('#' + h) })),
        ...($hosts || []).map(h => ({ id: 'h-' + h.id, group: 'Hosts', title: h.name, sub: `${h.report?.os || 'host'} · ${h.online ? 'online' : 'offline'}`, icon: Server, run: () => go('#infra/' + h.id) })),
        ...($machines?.machines || []).map(m => ({ id: 'm-' + m.name, group: 'Machines', title: m.name, sub: `${m.image?.distro} ${m.image?.version} · ${m.state}`, icon: Server, run: () => go('#infra/vm-' + m.name) })),
        ...($services || []).map(s => ({ id: 's-' + s.key, group: 'Services', title: s.name, sub: `${s.host} · ${s.status}`, icon: s.kind === 'daemon' ? Cpu : Box, run: () => go('#infra/svc-' + encodeURIComponent(s.id)) })),
        ...($tailnet?.devices || []).filter(d => d.online && d.name !== 'device-of-shared-to-user').map(d => ({ id: 't-' + d.id, group: 'Tailscale devices', title: d.name, sub: `${d.ip} · ${d.os}`, icon: Monitor, run: () => go('#tailscale/' + d.name) })),
        ...databases.map(d => ({ id: 'd-' + d.id, group: 'Databases', title: d.name, sub: d.service, icon: Database, run: () => go('#databases/' + encodeURIComponent(d.id)) })),
        ...ACTIONS.map(a => ({ ...a, group: 'Actions' })),
        ...settingsIndex($machines?.machines, $hosts).map((e, i) => ({ id: 'set-' + i, group: 'Settings', title: e.title, sub: e.where, kw: e.kw, icon: Settings, run: () => openSetting(e) })),
    ];

    // every word must appear in the title, group or subtitle
    $: words = query.toLowerCase().split(/\s+/).filter(Boolean);
    $: shown = items.filter(i => words.every(w => `${i.title} ${i.group} ${i.sub || ''} ${i.kw || ''}`.toLowerCase().includes(w)))
        // without a query, keep the list short: pages and actions only
        .filter(i => words.length || ['Go to', 'Actions'].includes(i.group));
    $: if (selected >= shown.length) selected = Math.max(0, shown.length - 1);
    $: query, confirming = null;

    async function show() {
        open = true; query = ''; selected = 0; confirming = null;
        await tick(); inputEl?.focus();
        if (!databases.length) fetch('/api/databases').then(r => r.json()).then(j => { if (j.status === 'success') databases = j.data; }).catch(() => {});
    }
    const hide = () => { open = false; };

    function run(i) {
        const item = shown[i];
        if (!item) return;
        if (item.danger && confirming !== item.id) { confirming = item.id; selected = i; return; }
        hide();
        item.run();
    }

    // the selection, or if it was scrolled out of view, the first (dir 1) or last (dir -1) row on screen, so arrows
    // carry on from where you scrolled to instead of jumping back
    function fromView(dir) {
        const rows = [...(listEl?.querySelectorAll('.item') || [])];
        const box = listEl?.getBoundingClientRect();
        const seen = (el) => { const r = el.getBoundingClientRect(); return r.bottom > box.top && r.top < box.bottom; };
        if (!box || !rows[selected] || seen(rows[selected])) return selected;
        const vis = rows.map((el, i) => seen(el) ? i : -1).filter(i => i >= 0);
        return vis.length ? (dir > 0 ? vis[0] - 1 : vis[vis.length - 1] + 1) : selected;
    }
    async function scrollSel() { await tick(); listEl?.querySelector('.sel')?.scrollIntoView({ block: 'nearest' }); }

    function onKey(e) {
        if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'p')) { e.preventDefault(); open ? hide() : show(); return; }
        if ((e.metaKey || e.ctrlKey) && e.key === 't') { e.preventDefault(); hide(); newSession(); return; }
        if (!open) return;
        if (e.key === 'Escape') { e.preventDefault(); confirming ? confirming = null : hide(); }
        else if (e.key === 'ArrowDown') { e.preventDefault(); selected = Math.min(fromView(1) + 1, shown.length - 1); confirming = null; scrollSel(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); selected = Math.max(fromView(-1) - 1, 0); confirming = null; scrollSel(); }
        else if (e.key === 'Enter') { e.preventDefault(); run(selected); }
    }
    onMount(() => { window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); });
</script>

{#if open}
    <div class="backdrop" on:click|self={hide} role="presentation">
        <div class="palette" role="dialog" aria-label="Command palette">
            <label class="search">
                <Search size={17} />
                <input bind:this={inputEl} bind:value={query} placeholder="Search pages, machines, settings, or run an action…" autocomplete="off" spellcheck="false" />
            </label>
            <div class="list" bind:this={listEl}>
                {#each shown as item, i (item.id)}
                    {#if i === 0 || shown[i - 1].group !== item.group}<div class="group">{item.group}</div>{/if}
                    <button class="item" class:sel={i === selected} class:danger={item.danger} on:mousemove={() => { if (selected !== i) { selected = i; confirming = null; } }} on:click={() => run(i)}>
                        <span class="ic"><svelte:component this={item.icon} size={15} /></span>
                        <span class="t">{item.title}{#if item.sub}<small>{item.sub}</small>{/if}</span>
                        {#if confirming === item.id}<span class="confirm">Press Enter again to confirm</span>
                        {:else if item.hint}<kbd>{item.hint}</kbd>
                        {:else if i === selected}<span class="go">↵</span>{/if}
                    </button>
                {:else}
                    <div class="empty">Nothing matches “{query}”.</div>
                {/each}
            </div>
            <div class="foot"><span><kbd>↑</kbd><kbd>↓</kbd> to move</span><span><kbd>↵</kbd> to open</span><span><kbd>esc</kbd> to close</span></div>
        </div>
    </div>
{/if}

<style>
    .backdrop { overscroll-behavior: contain; position: fixed; inset: 0; z-index: 400; background: rgba(0, 0, 0, 0.5); backdrop-filter: blur(2px); -webkit-backdrop-filter: blur(2px); display: flex; justify-content: center; align-items: flex-start; padding: 14vh 16px 16px; box-sizing: border-box; animation: fade .12s ease-out; }
    @keyframes fade { from { opacity: 0; } }
    .palette { width: 620px; max-width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 24px 64px rgba(0, 0, 0, 0.5); display: flex; flex-direction: column; max-height: 62vh; overflow: hidden; animation: pop .14s ease-out; }
    @keyframes pop { from { opacity: 0; transform: translateY(-6px) scale(.98); } }
    .search { display: flex; align-items: center; gap: 12px; height: 54px; padding: 0 18px; flex-shrink: 0; border-bottom: 1px solid var(--border); color: var(--text-secondary); }
    .search input { flex: 1; min-width: 0; border: none; outline: none; background: transparent; font: inherit; font-size: 15px; color: var(--text-primary); }
    .search input::placeholder { color: var(--text-secondary); opacity: 0.8; }
    kbd { min-width: 18px; height: 20px; box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; font-family: inherit; font-size: 11px; font-weight: 500; padding: 0 5px; border-radius: 5px; border: 1px solid var(--border); background: var(--bg); color: var(--text-secondary); }
    .list { overflow-y: auto; overscroll-behavior: contain; padding: 4px 8px 8px; }
    /* group headings read like the sidebar's section labels */
    .group { font-size: 10.5px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-secondary); padding: 12px 10px 5px; }
    .item { display: flex; align-items: center; gap: 11px; width: 100%; min-height: 38px; padding: 5px 10px; border-radius: 7px; text-align: left; cursor: pointer; color: var(--text-primary); font-size: 13.5px; box-sizing: border-box; }
    .item.sel { background: var(--highlight-10); }
    .ic { width: 26px; height: 26px; border-radius: 6px; border: 1px solid var(--border); color: var(--text-secondary); display: flex; align-items: center; justify-content: center; flex-shrink: 0; box-sizing: border-box; transition: color .1s, border-color .1s; }
    .item.sel .ic { color: var(--accent); border-color: var(--accent); }
    .t { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 8px; overflow: hidden; white-space: nowrap; }
    .t small { font-size: 12px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; }
    .go { font-size: 13px; color: var(--text-secondary); padding-right: 2px; }
    .confirm { font-size: 12px; font-weight: 500; color: var(--text-primary); white-space: nowrap; }
    .empty { padding: 32px; text-align: center; color: var(--text-secondary); font-size: 13.5px; }
    .foot { display: flex; gap: 18px; padding: 10px 18px; flex-shrink: 0; border-top: 1px solid var(--border); font-size: 12px; color: var(--text-secondary); }
    .foot span { display: inline-flex; align-items: center; gap: 4px; }
    .foot span kbd + kbd { margin-left: -1px; }
    @media (max-width: 640px) { .backdrop { padding-top: 8vh; } .foot { display: none; } }
</style>
