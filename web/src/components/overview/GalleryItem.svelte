<script>
    import { ChartSpline, Gauge as GaugeIcon, ChartBar } from 'lucide-svelte';
    import MetricCard from '../metrics/MetricCard.svelte';
    import { SECTION_TILES, SHORTCUTS, COLS, AVATAR_LOOKS, layout, toggleTile, setTotalsCols, setShortcuts } from '../../lib/widgets.js';
    import { catalog, mlayout, kindsFor, SIZES, sizeOf, NET } from '../../lib/metrics.js';

    // One thing the Add gallery offers, as it will be on the page (dashed, as while customizing)
    // with its tools on its top edge, the same as a placed one's. Pressed and moved: dragged onto
    // the page; pressed and let go: added at the end.
    export let item;                  // { type: 'section' | 'host' | 'machine' | 'metric', id, label, desc, meta?, list? }
    export let preview = null;        // snippet: an item ('tailscale', 'h:<id>', 'v:<name>') as on the page
    export let pageW = 1100;
    export let fitS = 1;
    export let realW = () => 0;
    export let press = () => {};
    export let placed = 0;            // how many of it are on the page
    export let onDrag = () => {};     // (spec, event, element) a drag onto the page has begun
    export let onPick = () => {};     // (spec) add it at the end
    export let minH = 0;              // cards: as tall as the tallest beside it (as in a row on the page)
    export let onH = () => {};        // (px) its own height, unstretched

    const KIND = { line: 'Graph', bars: 'Bars', gauge: 'Gauge' };
    const KIND_ICON = { line: ChartSpline, bars: ChartBar, gauge: GaugeIcon };

    // a section: what it shows (shared with the one on the page) and its width
    let secWidth = 'full';
    let look = 'visor';   // the avatar: which character
    $: tileName = Object.fromEntries((SECTION_TILES[item.id] || []).map(t => [t.id, t.label]));
    $: tiles = item.type === 'section' && SECTION_TILES[item.id] ? ($layout.tile_order[item.id] || []) : [];
    $: picked = $layout.shortcuts;
    const toggleShortcut = (id) => setShortcuts(picked.includes(id) ? picked.filter(x => x !== id) : [...picked, id]);

    // a host's or a machine's card: which one
    let cardId = null;
    $: list = item.list || [];
    $: if (list.length && !list.some(x => x.id === cardId)) cardId = list[0].id;

    // a metric: its kind, of which hosts, its size
    // which metric: one widget for all of them, the metric picked on its bar
    let mkey = item.metrics?.[0]?.key, kind = 'line', host = '', vi = 0, seen = null;
    $: meta = item.metrics ? item.metrics.find(m => m.key === mkey) || item.metrics[0] : item.meta;
    // a kind of widget (graph, gauge, bars, network) keeps its kind; only the metric changes
    $: if (meta && meta.key !== seen) { seen = meta.key; kind = item.kind || 'line'; host = ''; }
    $: names = $catalog?.names || {};
    $: if (meta && host && !meta.nodes.includes(host)) host = '';
    // download & upload: one host's, never all of them at once
    // (a gauge too: one ring, one host)
    $: oneHost = meta?.key === NET || item.kind === 'gauge';
    $: if (oneHost && !host && meta.nodes.length) host = meta.nodes[0];
    $: kinds = item.kind ? [item.kind] : meta ? kindsFor(meta).filter(k => k !== 'bars' || (meta.nodes.length > 1 && !host)) : [];
    $: if (meta && !kinds.includes(kind)) kind = kinds[0];
    $: hostsOf = host ? [host] : meta?.nodes || [];
    $: sizes = SIZES[kind] || [];
    $: if (vi >= sizes.length) vi = 0;

    $: spec = item.type === 'section' ? { kind: 'section', id: item.id, width: secWidth, ...(item.id === 'avatar' ? { cfg: { look } } : {}) }
        : item.type === 'host' || item.type === 'machine' ? { kind: item.type, id: cardId }
        : !meta ? null
        : (() => {
            const c = { type: kind, metric: meta.key, width: sizes[vi]?.[0], nodes: host ? [host] : [], node: null, title: '', range: null };
            // a gauge is one host's ring: from every host, one each
            return kind === 'gauge' ? { kind: 'metric', card: { ...c, node: hostsOf[0] }, each: hostsOf } : { kind: 'metric', card: c };
        })();
    $: what = item.type === 'section' ? item.id : item.type === 'host' ? 'h:' + cardId : item.type === 'machine' ? 'v:' + cardId : null;

    let lastH = 0;
    function scaled(node, p) {
        let o = p;
        const inner = node.firstElementChild;
        const set = () => {
            inner.style.width = o.w + 'px';
            inner.style.height = o.h ? o.h + 'px' : '';
            const card = inner.querySelector('.mcard');
            if (card) card.style.minHeight = '';
            const nat = inner.offsetHeight;
            if (nat !== lastH) { lastH = nat; onH(nat); }
            // a card stretched to the tallest beside it: the card itself grows by the difference
            if (card && o.mh > nat) { card.style.boxSizing = 'border-box'; card.style.minHeight = card.offsetHeight + o.mh - nat + 'px'; }
            inner.style.transform = `scale(${o.s})`;
            node.style.width = o.w * o.s + 'px';
            node.style.height = inner.offsetHeight * o.s + 'px';
        };
        const ro = new ResizeObserver(set); ro.observe(inner); set();
        return { update(n) { o = n; set(); }, destroy() { ro.disconnect(); } };
    }

    // tiles inside it are reordered as on the page (sortable, from the section itself); one pulled
    // well out of it hands over to a drag of the whole thing onto the page (sortable's __begin)
    function handover(node) { node.__begin = (row, x0, y0, e) => onDrag(spec, e, row); }
    function down(e) {
        if (e.button > 0 || e.target.closest('button, select, [data-nodrag]')) return;
        if (e.target.closest('.tsort [data-handle]')) {
            // on a tile: let go without moving adds it; moved, it's the tile's own drag
            const sx = e.clientX, sy = e.clientY;
            const mv = (m) => { if (Math.hypot(m.clientX - sx, m.clientY - sy) > 6) off(); };
            const upH = () => { off(); onPick(spec); };
            const off = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', upH); };
            window.addEventListener('pointermove', mv); window.addEventListener('pointerup', upH);
            return;
        }
        press(e, spec, e.currentTarget);
    }
</script>

{#if spec && (item.type === 'section' || item.type === 'metric' || cardId)}
<div class="it" data-label={item.label} class:full={item.type === 'section' && secWidth === 'full'}>
    <!-- (a metric widget carries its own name: no label over it) -->
    {#if item.type !== 'metric'}<div class="lb"><b>{item.label}</b>{#if item.desc}<span>{item.desc}</span>{/if}</div>{/if}
    <div class="ver" data-sort-root use:handover>
        <div class="ui-tools tb" class:left={item.type === 'metric' || secWidth === 'half' || item.id === 'avatar'}>
            {#if item.type === 'section'}
                {#if tiles.length}
                    <span class="grp" role="group" aria-label="Tiles shown">{#each tiles as t (t)}<button type="button" class:on={!$layout.hidden_tiles.includes(t)} aria-pressed={!$layout.hidden_tiles.includes(t)} title="{$layout.hidden_tiles.includes(t) ? 'Show' : 'Hide'} {tileName[t]}" on:click={() => toggleTile(t)}>{tileName[t]}</button>{/each}</span><i></i>
                {/if}
                {#if item.id === 'totals'}
                    <span class="grp" role="group" aria-label="Tiles per row" title="Tiles per row">{#each COLS as c}<button type="button" class:on={String($layout.totals_cols) === String(c)} on:click={() => setTotalsCols(c)}>{c}</button>{/each}</span><i></i>
                {/if}
                {#if item.id === 'shortcuts'}
                    <span class="grp" role="group" aria-label="Pages shown">{#each SHORTCUTS as x (x.id)}<button type="button" class:on={picked.includes(x.id)} aria-pressed={picked.includes(x.id)} title="{picked.includes(x.id) ? 'Hide' : 'Show'} {x.label}" on:click={() => toggleShortcut(x.id)}>{x.label}</button>{/each}</span><i></i>
                {/if}
                {#if item.id === 'avatar'}
                <span class="grp" role="group" aria-label="Look">{#each AVATAR_LOOKS as [k, l]}<button type="button" class:on={look === k} on:click={() => look = k}>{l}</button>{/each}</span>
                {:else}
                <span class="grp" role="group" aria-label="Width"><button type="button" class:on={secWidth === 'full'} on:click={() => secWidth = 'full'}>Full</button><button type="button" class:on={secWidth === 'half'} on:click={() => secWidth = 'half'}>Half</button></span>
                {/if}
            {:else if item.type === 'metric'}
                <!-- compact, so it fits on the widget: the metric, hosts and size as menus, the kind as icons -->
                {#if item.metrics?.length > 1}<select class="mk" bind:value={mkey} aria-label="Metric" title="Metric">{#each item.metrics as m (m.key)}<option value={m.key}>{m.label}</option>{/each}</select>{/if}
                {#if kinds.length > 1}{#if item.metrics?.length > 1}<i></i>{/if}<span class="grp" role="group" aria-label="Kind">{#each kinds as k}<button type="button" class="ic" class:on={kind === k} title={KIND[k]} aria-label={KIND[k]} on:click={() => kind = k}><svelte:component this={KIND_ICON[k]} size={13} /></button>{/each}</span>{/if}
                <!-- (bars: one bar of every host, no host to pick) -->
                {#if meta.nodes.length > 1 && kind !== 'bars'}
                    {#if kinds.length > 1 || item.metrics?.length > 1}<i></i>{/if}
                    <select bind:value={host} aria-label="Hosts" title="Hosts">{#if !oneHost}<option value="">{kind === 'line' && meta.nodes.length > 3 ? 'Top 3' : 'All'}</option>{/if}{#each meta.nodes as n (n)}<option value={n}>{names[n] || n}</option>{/each}</select>
                {/if}
                {#if sizes.length > 1}{#if item.metrics?.length > 1 || kinds.length > 1 || (meta.nodes.length > 1 && kind !== 'bars')}<i></i>{/if}<select bind:value={vi} aria-label="Size" title="Size">{#each sizes as [, l], k}<option value={k}>{l}</option>{/each}</select>{/if}
            {:else}
                <span class="grp">{#each list as x (x.id)}<button type="button" class:on={cardId === x.id} on:click={() => cardId = x.id}>{x.name}</button>{/each}</span>
            {/if}
        </div>
        {#key JSON.stringify(spec)}
            <div class="pv" data-id="gal" data-handle use:scaled={{ w: realW(spec), h: spec.kind === 'metric' ? sizeOf(spec.card, pageW).h : 0, mh: minH, s: fitS }} role="button" tabindex="-1" title="Drag onto the page, or click to add at the end" on:pointerdown={down}>
                <div class="pin">
                    {#if spec.kind === 'metric'}<MetricCard card={{ id: 'gal-' + meta.key, ...spec.card }} range={$mlayout.range} cat={$catalog} />
                    {:else if preview}{@render preview(what, false, spec.cfg || null)}{/if}
                </div>
            </div>
        {/key}
    </div>
    {#if placed && (tiles.length || item.id === 'shortcuts')}<p class="oh">What it shows changes the one on the page too.</p>{/if}
</div>
{/if}

<style>
    .it { display: flex; flex-direction: column; min-width: 0; }
    .it.full { flex-basis: 100%; }
    .lb { display: flex; align-items: baseline; gap: 8px; min-width: 0; margin-bottom: 12px; font-size: 13px; white-space: nowrap; }
    .lb b { font-weight: 600; color: var(--text-primary); }
    .lb span { color: var(--text-secondary); font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; }
    .ver { position: relative; align-self: flex-start; }
    /* its tools on its top edge, half above it, while hovered: as a placed one's (always on touch) */
    .tb { position: absolute; top: 0; right: 12px; max-width: calc(100% - 24px); z-index: 3; transform: translateY(calc(-50% + 3px)); box-shadow: 0 4px 14px rgba(0, 0, 0, .35); justify-content: flex-end; opacity: 0; pointer-events: none; transition: opacity .12s, transform .12s; }
    .ver:hover .tb, .ver:focus-within .tb { opacity: 1; transform: translateY(-50%); pointer-events: auto; }
    @media (hover: none) { .tb { opacity: 1; transform: translateY(-50%); pointer-events: auto; } }
    .tb.left { right: auto; left: 12px; justify-content: flex-start; }
    .tb :global(.grp) { flex-wrap: wrap; }
    .tb .ic { padding: 0; width: 22px; justify-content: center; }
    /* (a widget's tools sit closer to its corner, as on a placed one) */
    .tb.left { left: 0; }
    .it:has(.tb.left) .tb { max-width: 100%; flex-wrap: nowrap; }
    .tb.left :global(.grp) { flex-wrap: nowrap; }
    .tb > :global(i) { margin: 0 2px; }
    .tb select { height: 24px; padding: 0 15px 0 6px; border: none; border-radius: 6px; font: inherit; font-size: 12px; color: var(--text-primary); cursor: pointer; appearance: none; -webkit-appearance: none;
        background: transparent url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%23999' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E") no-repeat right 4px center; max-width: 120px; text-overflow: ellipsis; field-sizing: content; }
    .tb select:hover { background-color: var(--highlight-10); }
    .tb select.mk { font-weight: 500; max-width: 140px; }
    .tb select option { background: var(--surface); color: var(--text-primary); }
    .pv { position: relative; border-radius: var(--radius-card, 8px); outline: 1px dashed var(--border-strong); cursor: grab; touch-action: none; transition: outline-color .12s, box-shadow .12s; }
    .pv:hover { outline-color: var(--text-secondary); }
    .pv:active { cursor: grabbing; }
    .pin { position: absolute; top: 0; left: 0; transform-origin: top left; pointer-events: none; display: flex; flex-direction: column; }
    .pin > :global(*) { flex: 1; }
    /* (its tiles take the pointer, to be reordered, as on the page) */
    .pin :global(.tsort) { pointer-events: auto; }
    /* (a widget: one line, the dashed outline where its own border is, as when placed) */
    .pin :global(.w), .pin :global(.ui-stat.mb) { border-color: transparent; }
    .oh { margin: 8px 0 0; font-size: 12px; color: var(--text-secondary); }
</style>
