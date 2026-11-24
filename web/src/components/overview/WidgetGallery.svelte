<script>
    import { X, Search } from 'lucide-svelte';
    import { fade, scale } from 'svelte/transition';
    import GalleryItem from './GalleryItem.svelte';
    import { SN } from '../../lib/server.js';
    import { OVERVIEW_WIDGETS, baseOf } from '../../lib/widgets.js';
    import { hosts, hostOrder, byOrder } from '../../lib/hosts.js';
    import { machines } from '../../lib/stores.js';
    import { catalog, loadCatalog, widthOf, kindsFor, NET } from '../../lib/metrics.js';

    // Add to the Overview: everything that can go on it (sections, a host's card, a machine's
    // card, every metric), each drawn as it will be on the page with its tools on its edge.
    // Drag one onto the page, or click it to add it at the end. Anything can be added again.
    export let open = false;
    export let preview = null;          // snippet: an item ('tailscale', 'h:<id>', 'v:<name>') as on the page
    export let pageW = 1100;            // the page's width, so versions are drawn at their true size
    export let onPage = [];             // what is on the page now (its items)
    export let dragging = false;        // a version is being dragged onto the page: step aside
    export let onPick = () => {};       // (spec) a click: add at the end
    export let onDrag = () => {};       // (spec, event, element) a drag has begun

    $: if (open) loadCatalog();
    const DESC = {
        webapps: 'Your pinned web apps, one click away.',
        attention: 'Package updates, apps and the last backup.',
        totals: 'CPU, memory and storage of all hosts together.',
        host: 'One host: its CPU, memory and storage.',
        machine: 'One OrbStack machine: its CPU and memory.',
        tailscale: 'Devices on your tailnet and their traffic.',
        shortcuts: 'Links to pages, each with one figure.',
        compute: 'Compute pools and how busy they are.',
        'api-latency': 'How quickly the backend answers.',
        uptime: 'Your uptime checks at a glance.',
        pihole: 'Queries and blocking today.',
        rack: 'Every host and machine as a unit in a rack, with live lights.',
        text: 'A title and some lines of your own.',
        avatar: 'A little companion whose mood follows the cluster.',
    };
    // everything that can be added, one after another (no list to pick from: each is shown, each
    // with its own tools), found by name
    $: metrics = ($catalog?.metrics || []).filter(m => m.nodes.length);
    $: hostList = byOrder([{ id: 'arrakis', name: SN }, ...($hosts || []).map(h => ({ id: h.id, name: h.name }))], $hostOrder);
    $: machineList = ($machines?.machines || []).map(m => ({ id: m.name, name: m.name }));
    let q = '';
    $: match = (it) => !q.trim() || (it.label + ' ' + (it.desc || '') + ' ' + (it.search || '')).toLowerCase().includes(q.trim().toLowerCase());
    $: groups = [
        { name: 'Sections', items: OVERVIEW_WIDGETS.map(w => ({ type: 'section', id: w.id, label: w.label, desc: DESC[w.id] })) },
        { name: 'Cards', items: [
            { type: 'host', id: 'host', label: 'Host card', desc: DESC.host, list: hostList },
            ...(machineList.length ? [{ type: 'machine', id: 'machine', label: 'Machine card', desc: DESC.machine, list: machineList }] : []),
        ] },
        // one widget for every metric: which one is picked on its bar
        // a widget for each kind (graph, gauge, bars, and download & upload of its own), the
        // metric picked on its bar from those that kind suits
        { name: 'Metrics', items: [
            // in pairs, a row each: the graphs (one host's network, and any metric), then bars and gauge
            { kind: 'line', label: 'Graph', of: metrics.filter(m => m.key !== NET && kindsFor(m).includes('line')) },
            { kind: 'line', label: 'Network', id: 'net', desc: 'Download and upload', of: metrics.filter(m => m.key === NET) },
            { kind: 'bars', label: 'Bars', row: true, of: metrics.filter(m => m.key !== NET && m.nodes.length > 1 && kindsFor(m).includes('bars')) },
            { kind: 'gauge', label: 'Gauge', of: metrics.filter(m => kindsFor(m).includes('gauge')) },
        ].filter(x => x.of.length).map(x => ({ type: 'metric', id: 'm-' + (x.id || x.kind), label: x.label, desc: x.desc, kind: x.kind, row: x.row, metrics: x.of, search: x.of.map(m => m.label).join(' ') })) },
    ].map(g => ({ ...g, items: g.items.filter(match) })).filter(g => g.items.length);
    // how many of a section are on the page already
    $: count = (id) => onPage.filter(t => !/^[mhv]:/.test(t) && baseOf(t) === id).length;

    // the cards side by side as tall as each other, as in a row on the page
    let cardHs = {};
    $: cardH = Math.max(0, ...Object.values(cardHs));
    // drawn at their width on the page, all scaled alike when the page is wider than this pane
    let paneW = 800, innerW = 1440;
    $: fitS = Math.min(1, (paneW - 56) / Math.max(1, pageW));
    // a card: as wide as in a row of cards (.ui-cardgrid: as many of at least 380px as fit, 16px apart)
    $: cardN = innerW <= 640 ? 1 : Math.max(1, Math.floor((pageW + 16) / 396));
    $: cardW = (pageW - 16 * (cardN - 1)) / cardN;
    $: realW = (spec) => spec.kind === 'host' || spec.kind === 'machine' ? cardW : spec.kind === 'section' ? (spec.id === 'avatar' ? 136 : spec.width === 'half' ? (pageW - 16) / 2 : pageW) : widthOf(spec.card, pageW);

    // press and move: a drag onto the page; press and let go: add at the end
    function press(e, spec, el) {
        if (e.button > 0) return;
        const sx = e.clientX, sy = e.clientY;
        const mv = (m) => { if (Math.hypot(m.clientX - sx, m.clientY - sy) > 6) { off(); onDrag(spec, m, el); } };
        const upH = () => { off(); onPick(spec); };
        const off = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', upH); };
        window.addEventListener('pointermove', mv);
        window.addEventListener('pointerup', upH);
    }
</script>

<svelte:window bind:innerWidth={innerW} on:keydown={e => open && !dragging && e.key === 'Escape' && (open = false)} />

{#if open}
    <div class="backdrop" class:away={dragging} transition:fade={{ duration: 120 }} on:click|self={() => open = false} role="presentation">
        <div class="gal" style="width: min({pageW + 58}px, 100%)" role="dialog" aria-modal="true" aria-label="Add to the overview" transition:scale={{ duration: 140, start: 0.97 }}>
            <header class="hd">
                <h2>Add to the overview</h2>
                <label class="search"><Search size={14} /><input placeholder="Search" bind:value={q} /></label>
                <button class="x" on:click={() => open = false} aria-label="Close"><X size={16} /></button>
            </header>
            <div class="pane" bind:clientWidth={paneW}>
                {#each groups as g (g.name)}
                    <h3>{g.name}</h3>
                    <!-- cards and metrics: spaced as on the page's grids, so they sit side by side as they will there -->
                    <div class="items" class:mx={g.name === 'Metrics'} style={g.name !== 'Sections' ? `column-gap: ${16 * fitS}px` : ''}>
                        {#each g.items as it (it.id)}{#if it.row && !q.trim()}<i class="brk"></i>{/if}<GalleryItem item={it} {preview} {pageW} {fitS} {realW} {press} {onDrag} {onPick} placed={it.type === 'section' ? count(it.id) : 0}
                            minH={g.name === 'Cards' ? cardH : 0} onH={(h) => { if (g.name === 'Cards' && cardHs[it.id] !== h) cardHs = { ...cardHs, [it.id]: h }; }} />{/each}
                    </div>
                {:else}<p class="note">Nothing called “{q}”.</p>{/each}
            </div>
            <footer class="ft">Drag one onto the page, or click it to add it at the end.</footer>
        </div>
    </div>
{/if}

<style>
    .backdrop { position: fixed; inset: 0; z-index: 500; display: flex; align-items: center; justify-content: center; padding: 24px; background: rgba(0, 0, 0, .55); transition: opacity .15s; }
    /* while one is dragged onto the page, the gallery steps aside */
    .backdrop.away { opacity: 0; pointer-events: none; }
    .gal { display: flex; flex-direction: column; height: min(860px, 100%); border-radius: 12px; overflow: hidden; background: var(--bg); border: 1px solid var(--border-strong); box-shadow: 0 30px 80px rgba(0, 0, 0, .5); }
    .hd { display: flex; align-items: center; gap: 16px; padding: 14px 16px 14px 28px; background: var(--surface); border-bottom: 1px solid var(--border); }
    .hd h2 { margin: 0; font-size: 16px; font-weight: 600; color: var(--text-primary); white-space: nowrap; }
    .search { display: flex; align-items: center; gap: 8px; margin-left: auto; width: 260px; min-width: 0; height: 32px; padding: 0 10px; border-radius: 6px; background: var(--bg); border: 1px solid var(--border); color: var(--text-secondary); }
    .search:focus-within { border-color: var(--accent); }
    .search input { flex: 1; min-width: 0; background: none; border: none; outline: none; font-size: 13px; color: var(--text-primary); }
    .x { width: 30px; height: 30px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 8px; color: var(--text-secondary); cursor: pointer; }
    .x:hover { background: var(--highlight-10); color: var(--text-primary); }
    /* the page's own background, so each looks as it will on it */
    .pane { flex: 1; min-height: 0; overflow-y: auto; padding: 4px 28px 32px; }
    .pane h3 { margin: 28px 0 16px; font-size: 11px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: var(--text-secondary); }
    .items { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 32px 24px; }
    /* (row gap: room for the next row's tools, half above it) */
    .items.mx { row-gap: 16px; }
    /* (a new row: the next pair starts on its own line) */
    .brk { flex-basis: 100%; height: 0; }
    .note { margin: 28px 0 0; font-size: 13px; color: var(--text-secondary); }
    .ft { padding: 10px 28px; font-size: 12px; color: var(--text-secondary); background: var(--surface); border-top: 1px solid var(--border); }

    @media (max-width: 760px) {
        .backdrop { padding: 0; align-items: flex-end; }
        .gal { height: 92vh; border-radius: 12px 12px 0 0; }
        .hd { padding: 12px 12px 12px 16px; gap: 10px; }
        .hd h2 { display: none; }
        .search { margin-left: 0; flex: 1; width: auto; }
        .pane { padding: 4px 16px 24px; }
        .ft { display: none; }
    }
</style>
