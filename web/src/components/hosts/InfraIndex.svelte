<script>
    import { sortable } from '../../lib/sortable.js';
    import { joinKey } from '../../lib/widgets.js';
    import { SN } from '../../lib/server.js';
    // #infra: every host, laid out like the OrbStack VM page — summary tiles split by
    // host, a toolbar, then one ResourceCard per host (or the folder tree as a table).
    import { Plus, Search, LayoutGrid, List, Laptop, Server } from 'lucide-svelte';
    import { stats, machines, machineUsage } from '../../lib/stores.js';
    import { services } from '../../lib/services.js';
    import { hosts, fmtGb, fmtDisk, hostState, hostStateLabel, hostIcon, arrakisModel, hostOrder, byOrder } from '../../lib/hosts.js';
    import { href } from '../../lib/infra.js';
    import { disks, storageTotals } from '../../lib/storage.js';
    import ResourceCard from '../ui/ResourceCard.svelte';
    import StatusPill from '../ui/StatusPill.svelte';
    import ClusterCard from './ClusterCard.svelte';

    export let arrakis = {};
    export let vm = {};
    // on the Overview: just the cluster tiles and host cards, no title or toolbar
    export let embedded = false;
    // the Overview shows the totals and the cards as separate sections, and can hide single cards
    export let summary = true;
    export let cards = true;
    export let hiddenIds = [];
    export let only = null;       // just these hosts' cards, in this order (the Overview places each card on its own)
    // the Overview's Customize: tiles to leave out, and how many per row ('auto' or '1'–'4')
    export let hideTiles = [];
    export let order = ['hosts', 'cpu', 'mem', 'disk'];   // the tiles' order, from Customize
    export let cols = '4';
    export let most = 4;          // out: how many tiles fit across at this width
    export let joins = [];        // pairs of neighbouring tiles that share one card ('a|b')
    export let onJoin = null;     // Customize: (a, b) merge or split two neighbours
    export let onSort = null;     // Customize: the tiles can be dragged into another order (ids)
    export let rows = 1;          // out: how many rows of tiles (the Overview records height per row)

    $: hd = $stats?.host?.details || {};
    $: machineList = $machines?.machines || [];
    $: runningMachines = machineList.filter(m => m.state === 'running').length;
    $: vmContainers = machineList.reduce((a, m) => a + ($machineUsage[m.name]?.runs?.containers_running || 0), 0);
    $: appCount = ($services || []).filter(s => s.host === 'Mac' && !/orbstack/i.test(s.name || '') && s.status === 'running').length;

    const pct = (a, b) => b ? Math.min(100, Math.max(0, (a / b) * 100)) : 0;
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
    const shortOs = (os) => (os || '').replace(/ LTS$/, '').replace(/ \(.*\)$/, '');
    const ago = (t) => { const s = Math.max(0, Date.now() / 1000 - t); return s < 90 ? `${Math.round(s)}s ago` : s < 5400 ? `${Math.round(s / 60)}m ago` : s < 129600 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`; };
    const SHADES = [1, 0.7, 0.5, 0.35, 0.25];

    // one shape for every host: Arrakis from the dashboard's own stats, the rest from their agent
    // external drives on Arrakis: their mounted volumes
    $: ext = storageTotals($disks).external;
    $: list = byOrder([
        {
            id: 'arrakis', name: SN, tag: 'This server', online: true, icon: hostIcon($arrakisModel, 'macOS'), state: 'running', stateLabel: 'Online',
            sub: `${shortOs(arrakis.os || 'macOS')} · ${arrakis.cores || '—'} cores · ${arrakis.mem ? arrakis.mem.total.toFixed(0) + ' GB' : '—'}`,
            cores: arrakis.cores || 0, cpu: isFinite(arrakis.cpu) ? arrakis.cpu : null,
            mem: arrakis.mem ? arrakis.mem.used * 2 ** 30 : null, memTotal: arrakis.mem ? arrakis.mem.total * 2 ** 30 : 0,
            // internal disk plus any external drives on Arrakis
            disk: arrakis.disk ? arrakis.disk.used * 1e9 + ext.used : null, diskTotal: arrakis.disk ? arrakis.disk.total * 1e9 + ext.size : 0,
            lan: hd['Local IP'] || '', ts: hd['Tailscale IP'] || '',
            chips: [
                { label: vm.running ? plural(runningMachines, 'machine') : 'VM stopped', to: '#infra/arrakis/vm' },
                ...(vmContainers ? [{ label: plural(vmContainers, 'container'), to: '#infra/arrakis/vm' }] : []),
                ...(appCount ? [{ label: plural(appCount, 'app'), to: '#infra/arrakis/apps' }] : []),
            ],
            search: 'arrakis macos mac server',
        },
        ...($hosts || []).map(h => {
            const r = h.report || {}, n = (r.containers || []).filter(c => c.status === 'running').length;
            // machines from its managed OrbStack, else its last inventory; a Mac's apps (OrbStack is the VM)
            const ms = h.vms?.machines, mCount = ms ? ms.filter(m => m.state === 'running').length : h.caps?.machines;
            const apps = (r.apps || []).filter(a => !/orbstack/i.test(a.name)).length;
            // a Linux host's own services (not the standard system ones, nor this dashboard's agent)
            const svcs = (r.workloads?.services || []).filter(u => !u.base && u.unit !== 'arrakis-agent').length;
            return {
                id: h.id, name: h.name, online: h.online, icon: hostIcon(r.model, r.os), state: hostState(h), stateLabel: hostStateLabel(h),
                sub: h.report ? [shortOs(r.os), r.cores ? `${r.cores} cores` : '', r.mem_total ? fmtGb(r.mem_total) : ''].filter(Boolean).join(' · ') : 'Agent not installed yet',
                cores: r.cores || 0, cpu: h.online ? r.cpu_pct : null,
                mem: h.online ? r.mem_used : null, memTotal: r.mem_total || 0,
                disk: r.disk_used ?? null, diskTotal: r.disk_total || 0,
                lan: '', ts: r.ip || '',
                chips: h.online ? [
                    ...((h.caps?.orbstack === 'stopped' && !ms) || mCount ? [{ label: h.caps?.orbstack === 'stopped' && !ms ? 'VM stopped' : plural(mCount || 0, 'machine'), to: `${href.host(h.id)}/vm` }] : []),
                    ...(n ? [{ label: plural(n, 'container'), to: href.host(h.id) }] : []),
                    ...(apps ? [{ label: plural(apps, 'app'), to: `${href.host(h.id)}/apps` }] : []),
                    ...(svcs ? [{ label: plural(svcs, 'service'), to: `${href.host(h.id)}/workloads` }] : []),
                ] : [],
                note: !h.online ? (h.last_seen ? `Offline · last report ${ago(h.last_seen)}` : 'Run the install command on it') : '',
                search: [h.name, r.os, r.ip, r.hostname].filter(Boolean).join(' ').toLowerCase(),
            };
        }),
    ], $hostOrder);

    // ---- summary: totals of the hosts that are online, split by host ---------------------
    $: live = list.filter(h => h.online);
    $: totCores = live.reduce((a, h) => a + h.cores, 0);
    // biggest first, as many hosts as fit the tile's legend in two lines; the rest share one
    // "N others" part (the bar's tooltip still lists every host). Label widths are estimated
    // in the legend's own font.
    let ctx, legendFont = '';
    const textW = (t) => {
        if (!ctx) ctx = document.createElement('canvas').getContext('2d');
        ctx.font = legendFont || '12px Inter, sans-serif';
        return Math.ceil(ctx.measureText(t).width) + 13;   // + swatch and its gap
    };
    function lines(labels, w) {
        let n = 1, x = 0;
        for (const l of labels) { const lw = textW(l); if (x && x + 12 + lw > w) { n++; x = lw; } else x += (x ? 12 : 0) + lw; }
        return n;
    }
    function top(list, key, label, w) {
        const all = list.filter(x => x[key] > (key === 'cores' ? 0.005 : 0)).sort((a, b) => b[key] - a[key]);
        const build = (k) => {
            const parts = all.slice(0, k).map((x, i) => ({ ...x, shade: SHADES[Math.min(i, 3)] }));
            const rest = all.slice(k);
            if (rest.length) parts.push({ name: `${rest.length} others`, [key]: rest.reduce((a, x) => a + x[key], 0), shade: 0.25 });
            return parts;
        };
        let k = all.length;
        while (k > 1 && (!w || lines(build(k).map(label), w) > 2)) { if (!w && k <= 3) break; k--; }
        return { all, parts: build(k) };
    }
    let cpuW = 0, memW = 0, diskW = 0, legendEl;
    $: if (legendEl && cpuW) legendFont = getComputedStyle(legendEl).font;
    $: cpu = top(live.map(h => ({ name: h.name, cores: (h.cpu || 0) / 100 * h.cores })), 'cores', s => `${s.name} ${s.cores < 0.1 ? '<0.1' : s.cores.toFixed(1)} cores`, cpuW);
    $: usedCores = cpu.all.reduce((a, s) => a + s.cores, 0);
    $: totMem = live.reduce((a, h) => a + h.memTotal, 0);
    $: memory = top(live.map(h => ({ name: h.name, bytes: h.mem || 0 })), 'bytes', s => `${s.name} ${fmtGb(s.bytes)}`, memW);
    $: usedMem = memory.all.reduce((a, s) => a + s.bytes, 0);
    $: totDisk = live.reduce((a, h) => a + h.diskTotal, 0);
    $: usedDisk = live.reduce((a, h) => a + (h.disk || 0), 0);
    $: storage = top(live.map(h => ({ name: h.name, bytes: h.disk || 0 })), 'bytes', s => `${s.name} ${fmtDisk(s.bytes)}`, diskW);

    // ---- tile layout: per row from the setting (or the screen in auto); a short last row
    // stretches its last tile, so three tiles at two per row read as 2 + 1 ----------------
    // measured on the tiles' own row, so a half-width section lays out by its own width
    let cw = 1300;
    $: tiles = order.filter(t => !hideTiles.includes(t));
    // the number chosen, but never squeezing a tile below about 240px (4 across from about 1000px)
    $: most = Math.max(1, Math.floor((cw + 12) / 252));
    $: rows = Math.max(1, Math.ceil(tiles.length / perRow));
    $: perRow = Math.max(1, Math.min(tiles.length, Math.min(+cols || 4, most)));
    $: gridCols = perRow === tiles.length && perRow > 1 ? tiles.map(t => t === 'hosts' ? 'minmax(0, 0.6fr)' : 'minmax(0, 1fr)').join(' ') : `repeat(${perRow}, minmax(0, 1fr))`;
    // merged with the tile before / after it: only on the same row
    $: jl = (t) => { const i = tiles.indexOf(t); return i > 0 && i % perRow !== 0 && joins.includes(joinKey(tiles[i - 1], t)); };
    $: jr = (t) => { const i = tiles.indexOf(t); return i < tiles.length - 1 && (i + 1) % perRow !== 0 && joins.includes(joinKey(t, tiles[i + 1])); };
    $: spanOf = (t) => { const rest = tiles.length % perRow; return rest && tiles.indexOf(t) === tiles.length - 1 ? perRow - rest + 1 : 1; };

    // ---- toolbar -----------------------------------------------------------------------------
    let q = '', filter = 'all';
    let view = 'grid';
    try { view = localStorage.getItem('arrakis_infra_view') || 'grid'; } catch (e) {}
    function setView(v) { view = v; try { localStorage.setItem('arrakis_infra_view', v); } catch (e) {} }
    $: shown = list.filter(h => (filter === 'all' || (filter === 'online') === h.online) && (!q || h.search.includes(q.toLowerCase()) || h.name.toLowerCase().includes(q.toLowerCase())));
    const go = (to) => location.hash = to;
</script>

<div class:ui-page={!embedded} class:emb={embedded}>
    {#if !embedded}
    <div class="ui-head">
        <div>
            <h1>Infrastructure</h1>
            <p>Every computer in the cluster. Open one to see what runs on it.</p>
        </div>
        <div class="ui-head-actions">
            <a class="ui-btn primary" href={href.newHost}><Plus size={15} /> Add host</a>
        </div>
    </div>

    {/if}

    <!-- Customize: on the gap (or line) before a tile, merge it with the one before or split them -->
    {#snippet joinBtn(t)}
        {#if onJoin && tiles.indexOf(t) % perRow !== 0}
            {@const prev = tiles[tiles.indexOf(t) - 1]}
            <button type="button" class="tjb" data-nodrag title={jl(t) ? 'Split into two cards' : 'Merge into one card'} aria-label={jl(t) ? 'Split into two cards' : 'Merge into one card'} on:click|stopPropagation={() => onJoin(prev, t)}></button>
        {/if}
    {/snippet}
    {#if summary}
    {#if tiles.length}
    <div class="ui-summary cluster" class:tsort={onSort} style="grid-template-columns: {gridCols}" bind:clientWidth={cw} use:sortable={{ onMove: (ids) => onSort?.(ids) }}>
        {#each tiles as t (t)}
        {#if t === 'hosts'}
        <div class="ui-stat" class:tj-l={jl('hosts')} class:tj-r={jr('hosts')} style="grid-column: span {spanOf('hosts')}" data-id="hosts" data-n={tiles.indexOf('hosts')} data-handle={onSort ? '' : null}>
            {@render joinBtn('hosts')}
            <span class="ui-stat-label">Hosts</span>
            <span class="ui-stat-value">{list.length}</span>
            <span class="ui-stat-sub">{live.length} online · {list.length - live.length} offline</span>
        </div>
        {:else if t === 'cpu'}
        <div class="ui-stat" class:tj-l={jl('cpu')} class:tj-r={jr('cpu')} style="grid-column: span {spanOf('cpu')}" data-id="cpu" data-n={tiles.indexOf('cpu')} data-handle={onSort ? '' : null}>
            {@render joinBtn('cpu')}
            <span class="ui-stat-label">CPU in use</span>
            <span class="ui-stat-value">{pct(usedCores, totCores).toFixed(1)}%<small>{usedCores.toFixed(2)} of {totCores} cores</small></span>
            <div class="ui-segbar" title={cpu.all.map(s => `${s.name}: ${s.cores.toFixed(2)} cores`).join('\n')}>
                {#each cpu.parts as s}<i style="width: {pct(s.cores, totCores)}%; background: var(--metric-cpu); opacity: {s.shade}"></i>{/each}
            </div>
            <span class="ui-stat-sub ui-legend" bind:clientWidth={cpuW} bind:this={legendEl}>{#each cpu.parts as s}<span><b style="background: var(--metric-cpu); opacity: {s.shade}"></b>{s.name} {s.cores < 0.1 ? "<0.1" : s.cores.toFixed(1)} cores</span>{:else}idle{/each}</span>
        </div>
        {:else if t === 'mem'}
        <div class="ui-stat" class:tj-l={jl('mem')} class:tj-r={jr('mem')} style="grid-column: span {spanOf('mem')}" data-id="mem" data-n={tiles.indexOf('mem')} data-handle={onSort ? '' : null}>
            {@render joinBtn('mem')}
            <span class="ui-stat-label">Memory in use</span>
            <span class="ui-stat-value">{fmtGb(usedMem)}<small>of {fmtGb(totMem)}</small></span>
            <div class="ui-segbar" title={memory.all.map(s => `${s.name}: ${fmtGb(s.bytes)}`).join('\n')}>
                {#each memory.parts as s}<i style="width: {pct(s.bytes, totMem)}%; background: var(--metric-mem); opacity: {s.shade}"></i>{/each}
            </div>
            <span class="ui-stat-sub ui-legend" bind:clientWidth={memW}>{#each memory.parts as s}<span><b style="background: var(--metric-mem); opacity: {s.shade}"></b>{s.name} {fmtGb(s.bytes)}</span>{:else}—{/each}</span>
        </div>
        {:else if t === 'disk'}
        <div class="ui-stat" class:tj-l={jl('disk')} class:tj-r={jr('disk')} style="grid-column: span {spanOf('disk')}" data-id="disk" data-n={tiles.indexOf('disk')} data-handle={onSort ? '' : null}>
            {@render joinBtn('disk')}
            <span class="ui-stat-label">Storage</span>
            <span class="ui-stat-value">{fmtDisk(usedDisk)}<small>of {fmtDisk(totDisk)}</small></span>
            <div class="ui-segbar" title={storage.all.map(x => `${x.name}: ${fmtDisk(x.bytes)} used`).join('\n')}>
                {#each storage.parts as x}<i style="width: {pct(x.bytes, totDisk)}%; background: var(--text-secondary); opacity: {x.shade}"></i>{/each}
            </div>
            <span class="ui-stat-sub ui-legend" bind:clientWidth={diskW}>{#each storage.parts as x}<span><b style="background: var(--text-secondary); opacity: {x.shade}"></b>{x.name} {fmtDisk(x.bytes)}</span>{/each}</span>
        </div>
        {/if}
        {/each}
    </div>
    {/if}
    {/if}

    {#if !embedded}
    <div class="ui-listbar">
        <label class="ui-search"><Search size={14} /><input placeholder="Search name, OS or IP" bind:value={q} /></label>
        <div class="ui-seg">
            <button class:on={filter === 'all'} on:click={() => filter = 'all'}>All <span class="n">{list.length}</span></button>
            <button class:on={filter === 'online'} on:click={() => filter = 'online'}>Online <span class="n">{list.filter(h => h.online).length}</span></button>
            <button class:on={filter === 'offline'} on:click={() => filter = 'offline'}>Offline <span class="n">{list.filter(h => !h.online).length}</span></button>
        </div>
        <span class="ui-count">{plural(shown.length, 'host')}</span>
        <div class="ui-seg view" role="group" aria-label="View">
            <button class:on={view === 'grid'} on:click={() => setView('grid')} title="Cards" aria-label="Cards"><LayoutGrid size={14} /></button>
            <button class:on={view === 'table'} on:click={() => setView('table')} title="Tree" aria-label="Tree"><List size={14} /></button>
        </div>
    </div>

    {/if}

    {#if embedded && !cards}
    {:else if view === 'grid' || embedded}
        <div class="ui-cardgrid">
            {#each only ? only.map(id => list.find(h => h.id === id)).filter(Boolean) : shown.filter(h => !hiddenIds.includes(h.id)) as h (h.id)}
                <ResourceCard name={h.name} tag={h.tag} sub={h.sub} icon={h.icon} on={h.online} off={!h.online} on:open={() => go(href.host(h.id))}
                    meters={[
                        { k: 'CPU', p: h.cpu ?? 0, color: 'var(--metric-cpu)', v: h.cpu != null ? h.cpu.toFixed(1) + '%' : '—', of: h.cores ? `of ${h.cores} cores` : '' },
                        { k: 'Memory', p: h.mem != null ? pct(h.mem, h.memTotal) : 0, color: 'var(--metric-mem)', v: h.mem != null ? fmtGb(h.mem) : '—', of: h.memTotal ? `of ${fmtGb(h.memTotal)}` : '' },
                        { k: 'Storage', p: h.disk != null ? pct(h.disk, h.diskTotal) : 0, color: 'var(--text-secondary)', v: h.disk != null ? fmtDisk(h.disk) : '—', of: h.diskTotal ? `of ${fmtDisk(h.diskTotal)}` : '' },
                    ]}
                    chips={h.chips.map(c => ({ label: c.label, onClick: () => go(c.to) }))}
                    note={h.note || ''} lan={h.lan} ts={h.ts} tsTitle="Tailscale">
                    <svelte:fragment slot="status"><StatusPill state={h.state} label={h.stateLabel} /></svelte:fragment>
                </ResourceCard>
            {/each}
            {#if !shown.length}<div class="ui-card ui-empty">No hosts match.</div>{/if}
        </div>
    {:else}
        <ClusterCard {arrakis} {vm} bare />
    {/if}
</div>

<style>
    .emb { display: flex; flex-direction: column; gap: 16px; }
    /* the columns and spans come from the script (tile layout); phones only tighten the gap */
    .ui-summary.cluster > * { order: 0; }
    /* Customize: the tiles themselves can be dragged (the section around them can't be clicked into) */
    .tsort { pointer-events: auto; }
    .cluster { --g: 12px; gap: var(--g); }
    @media (max-width: 760px) { .cluster { --g: 8px; } }
</style>
