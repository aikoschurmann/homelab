<script>
    import { onMount } from 'svelte';
    import { ChevronLeft, ChevronRight, ChevronDown, Check, Trash2, GripVertical, ChartLine, ChartBarStacked, Gauge } from 'lucide-svelte';
    import MetricCard from './MetricCard.svelte';
    import { layout, toggleJoin, joinKey, keepJoinsIf, baseOf, setCfg } from '../../lib/widgets.js';
    import { tick, beforeUpdate, afterUpdate } from 'svelte';
    import { mlayout, catalog, loadCatalog, removeCard, setCard, splitGauges, cellOf, gridLayout, pushLayout, swapLayout, setPositions, TYPES, SIZES, sizeName, widthsFor, heightsFor, WIDTH_NAMES, heightName, dimsOf, NET, RANGES, sizeFor, kindsFor } from '../../lib/metrics.js';

    // A run of metric widgets that sit next to each other among the Overview's sections
    // (each widget is its own item in the Overview's order, 'm:<id>'), laid out in one grid.
    // editing (the Overview's Customize): each widget is a row of the editor's drag list,
    // with its settings and tools in a bar on its top edge, as a section's are (no dialog).
    export let ids = [];                // the items of this run, in order: 'm:<id>' widgets and small sections ('avatar', 'text#k3x')
    export let sec = null;              // snippet drawing a section (the Overview's)
    export let tools = null;            // editing: snippet with a section's own settings for its bar
    export let onRemove = () => {};     // editing: take a section off the page
    export let nameOf = (t) => t;       // a section's or card's name (its bar's titles)
    export let editing = false;
    export let nOf = () => 0;           // editing: a widget's place in the editor's list
    export let total = 0;               // editing: how many items the list has
    export let arrange = () => {};      // editing: put the run's items in this order (tokens), after a move

    // a widget's settings, right in its bar (no dialog): kind, size, hosts, time range
    const KIND_ICON = { line: ChartLine, bars: ChartBarStacked, gauge: Gauge };
    $: metaOf = (c) => $catalog?.metrics.find(m => m.key === c.metric);
    $: availOf = (c) => metaOf(c)?.nodes || [];
    $: hname = (n) => $catalog?.names?.[n] || n;
    // one host only: a gauge, download & upload
    const single = (c) => c.type === 'gauge' || c.metric === NET;
    $: picked = (c) => { const a = availOf(c); if (single(c)) { const n = c.type === 'gauge' ? c.node : c.nodes[0]; return [a.includes(n) ? n : a[0]]; } return c.nodes.length ? c.nodes.filter(n => a.includes(n)) : a.slice(0, c.type === 'line' ? 3 : a.length); };
    function setKind(c, t) {
        if (t === c.type) return;
        const a = availOf(c);
        if (t === 'gauge') setCard(c.id, { type: t, width: 's', node: c.nodes[0] || a[0] || null, nodes: [] });
        else setCard(c.id, { type: t, width: sizeFor(t, c.type === 'gauge' ? 'm' : c.width), nodes: c.type === 'gauge' && c.node ? [c.node] : c.nodes, node: null });
    }
    function toggleHost(c, n) {
        if (c.type === 'gauge') return setCard(c.id, { node: n });
        if (single(c)) return setCard(c.id, { nodes: [n] });
        const cur = picked(c), a = availOf(c);
        let next = cur.includes(n) ? cur.filter(x => x !== n) : [...cur, n];
        if (!next.length) return;
        if (c.type === 'line') next = next.slice(-3);    // a graph: three hosts at most
        next = a.filter(x => next.includes(x));
        setCard(c.id, { nodes: next.length === a.length ? [] : next });
    }
    // size, hosts and time range: each a button in the bar opening a short list (on the page's
    // body, so no card covers it); the bar stays up while one is open
    let menu = null;
    function openMenu(e, c, kind) {
        if (menu?.id === c.id && menu.kind === kind) { menu = null; return; }
        const r = e.currentTarget.getBoundingClientRect();
        menu = { id: c.id, kind, top: r.bottom + 6, left: Math.max(8, Math.min(r.left, innerWidth - 208)) };
    }
    function portal(node) { document.body.appendChild(node); return { destroy() { node.remove(); } }; }
    $: mc = menu && cards.find(c => c.id === menu.id);
    $: hostsLabel = (c) => { const p = picked(c), a = availOf(c); return p.length === 1 ? hname(p[0]) : p.length === a.length ? 'All hosts' : `${p.length} hosts`; };
    const rangeLabel = (r) => RANGES.find(x => x[0] === r)?.[1] || r;
    // the bar sits on the widget's top edge from the side with more room, and wraps rather than
    // run past the grid
    $: barPos = (p) => {
        if (!p) return '';
        const u = cell.unit + gap, left = p.x + p.w / 2 < cell.n / 2;
        const room = left ? gw - p.x * u - 8 : (p.x + p.w) * u - gap - 8;
        return `${left ? 'left' : 'right'}: 8px; max-width: ${Math.max(120, room)}px; justify-content: flex-${left ? 'start' : 'end'}`;
    };

    onMount(() => {
        loadCatalog();
        const t = setInterval(() => loadCatalog(true), 60000);
        return () => clearInterval(t);
    });

    // a section on the grid looks like a widget to the layout: its size and cell are kept in its cfg
    const SEC_SIZE = { avatar: 's', text: 'm' };
    // host and machine cards: a width of their own, one row that grows to fit what they hold
    // (the rest of the sections, rack, totals and so on, the same way: Half if it was a half-width one)
    // Auto: cells per card so as many fit as can at 380px or more each
    $: fitCols = Math.ceil(cell.n / Math.max(1, Math.floor((gw + gap) / (380 + gap))));
    const cardKind = (t) => t.startsWith('h:') ? 'host' : t.startsWith('v:') ? 'machine' : null;
    // every item: a width (wk) and a height (hk: cells for a widget, avatar or text; 'auto' for cards
    // and sections, as tall as what they show)
    const secItem = (t, type, old, extra = {}) => { const g = $layout.cfg[t] || {}; return { id: t, section: true, type, pos: g.pos, fitCols, ...dimsOf(type, g.w, g.h, old), ...extra }; };
    // (cell named here so this runs after it: secItem reads it)
    $: cards = cell && ids.map(t => {
        if (t.startsWith('m:')) { const c = $mlayout.cards.find(c => c.id === t.slice(2)); return c && { ...c, ...dimsOf(c.type, c.w, c.h, c.width) }; }
        const g = $layout.cfg[t] || {};
        if (cardKind(t)) return secItem(t, cardKind(t), g.cell || 'auto', { auto: true });
        if (SEC_SIZE[baseOf(t)]) return secItem(t, baseOf(t), g.cell || SEC_SIZE[baseOf(t)]);
        // (the old all-hosts section is not a host card)
        return secItem(t, baseOf(t) === 'host' ? 'hostlist' : baseOf(t), g.cell || ($layout.widths[t] === 'half' ? 'half' : 'full'), { auto: true });
    }).filter(Boolean);
    const tokOf = (c) => c.section ? c.id : 'm:' + c.id;
    function setDim(c, patch) { if (c.section) setCfg(c.id, patch); else setCard(c.id, patch); }
    function remove(c) { if (c.section) onRemove(c.id); else removeCard(c.id); }
    $: $mlayout, splitGauges($catalog);
    // a grid of square cells: how many to a row and how big, from the grid's own width
    let gw = 1100, gridEl, gap = 16;
    $: gw, gridEl && (gap = parseFloat(getComputedStyle(gridEl).columnGap) || 0);
    $: cell = cellOf(gw, gap);
    // (a row past the last one, for the drag: a cell tall)
    $: rowH = cell.unit;
    // where each widget sits (cells): kept where it was put; while one is dragged, the others
    // moving out of its way (worked out from the layout as it was when the drag began)
    $: base = gridLayout(cards, cell.n);
    let preview = null, snap = null;
    $: at = preview || base;
    // a widget is at least its cells tall; a card or section as tall as what it shows (its row as
    // tall as the tallest in it, and everything in the row stretches to that)
    const place = (p, fit = false) => `grid-column: ${p.x + 1} / span ${p.w}; grid-row: ${p.y + 1} / span ${p.h}` + (fit ? '' : `; min-height: ${Math.round(cell.unit * p.h + gap * (p.h - 1))}px`);
    // called by the drag (lib/sortable.js): the widget is over cell (x, y); null: it left the grid
    function moveTo(mid, x, y, pcx) {
        if (mid == null) { preview = null; snap = null; rowCache = null; return; }
        if (!snap) snap = base;
        if (!snap[mid]) return;
        preview = pushLayout(snap, mid, x, y, cell.n, pcx);
    }
    // let go: every widget of this grid keeps its place (for this grid size), and the run takes
    // their reading order (what a narrower screen lays out)
    function commit() {
        if (preview) {
            const p = preview;
            const secs = new Set(cards.filter(c => c.section).map(c => c.id));
            setPositions(cell.n, Object.fromEntries(Object.entries(p).filter(([k]) => !secs.has(k))));
            for (const k of secs) if (p[k]) setCfg(k, { pos: { ...($layout.cfg[k]?.pos || {}), [cell.n]: { x: p[k].x, y: p[k].y } } });
            arrange(Object.entries(p).sort((a, b) => a[1].y - b[1].y || a[1].x - b[1].x).map(([id]) => secs.has(id) ? id : 'm:' + id));
            // a merge stays only between two widgets still touching on one row, as tall
            const touch = (a, b) => a && b && a.y === b.y && a.h === b.h && a.x + a.w === b.x;
            keepJoinsIf('metrics', (a, b) => !(a in p && b in p) || touch(p[a], p[b]) || touch(p[b], p[a]));
        }
        preview = null; snap = null; rowCache = null;
    }
    // the arrows on a widget: one cell left or right
    // the arrows: trade places with the item before / after it (reading order, across rows)
    function nudge(mid, d) { const p = swapLayout(base, mid, d, cell.n); if (p) { preview = p; commit(); } }
    $: readOrder = Object.entries(at).sort((a, b) => a[1].y - b[1].y || a[1].x - b[1].x).map(([k]) => k);
    // the row under a point (rows grow to fit a host card, so not all are one cell tall)
    // Measured once when a drag starts and kept until it ends: the preview reflows the rows (a
    // section's row is another height than a host cards' one), and measuring them again made the
    // target jump back and forth between rows.
    let rowCache = null;
    function rowAt(py) {
        const rows = rowCache ||= getComputedStyle(gridEl).gridTemplateRows.split(' ').map(parseFloat).filter(x => !isNaN(x));
        let y = gridEl.getBoundingClientRect().top;
        for (let i = 0; i < rows.length; i++) { if (py < y + rows[i] / 2 + gap / 2) return i; y += rows[i] + gap; }
        return rows.length + Math.max(0, Math.round((py - y) / (rowH + gap)));
    }
    $: if (gridEl) { gridEl.__moveTo = moveTo; gridEl.__commit = commit; gridEl.__rowAt = rowAt; }
    // while customizing, widgets that move glide to their new cell (as Apple's do)
    let before = null;
    beforeUpdate(() => { before = editing && gridEl ? new Map([...gridEl.children].filter(e => e.dataset.mid).map(e => [e, e.getBoundingClientRect()])) : null; });
    afterUpdate(() => {
        if (!before) return;
        for (const [e, r] of before) {
            if (!e.isConnected) continue;
            const b = e.getBoundingClientRect(), dx = r.left - b.left, dy = r.top - b.top;
            if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
            e.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: 200, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' });
        }
        before = null;
    });
    // which widgets sit right after the one before them on the same row, as tall: those can be
    // merged into one card (Customize toggles it). Read off the laid-out grid.
    let beside = {};
    async function measure() {
        await tick();
        if (!gridEl) return;
        const els = [...gridEl.querySelectorAll(':scope > [data-mid]')];
        const b = {};
        els.forEach((e, k) => {
            const p = els[k - 1];
            if (p && Math.abs(p.offsetTop - e.offsetTop) < 2 && Math.abs(p.offsetHeight - e.offsetHeight) < 2 && (d => d > -2 && d < gap + 2)(p.offsetLeft + p.offsetWidth + gap - e.offsetLeft)) b[e.dataset.mid] = true;   // (a merged one already reaches into the gap)
        });
        beside = b;
    }
    $: cards, cell, gap, at, measure();
    // merged with the one before / after it
    $: joins = $layout.tile_joins.metrics;
    const joinable = (k) => k > 0 && !cards[k].section && !cards[k - 1].section && beside[cards[k].id];
    $: jl = (k) => joinable(k) && joins.includes(joinKey(cards[k - 1].id, cards[k].id));
    $: jr = (k) => k < cards.length - 1 && jl(k + 1);
    $: labelOf = (c) => c.section ? nameOf(c.id) : c.title || $catalog?.metrics.find(m => m.key === c.metric)?.label || c.metric;
</script>

<div class="mgrid" class:canvas={editing} bind:clientWidth={gw} bind:this={gridEl} data-cells={cell.n} style="grid-template-columns: repeat({cell.n}, minmax(0, 1fr)); grid-auto-rows: auto">
    {#each cards as c, k (c.id)}
        {#if editing}
            {@const n = nOf(tokOf(c))}
            <div class="slot ed" class:fit={c.auto} class:held={menu?.id === c.id} class:tj-l={jl(k)} class:tj-r={jr(k)} style={at[c.id] ? place(at[c.id], c.auto) : ''} data-mid={c.id} data-span="{at[c.id]?.w} {at[c.id]?.h}" data-id={tokOf(c)} data-n={n} data-handle>
                <div class="ec" data-sort-root>{#if c.section}{@render sec?.(c.id, true)}{:else}<MetricCard card={c} range={$mlayout.range} cat={$catalog} ext={((jl(k) ? 1 : 0) + (jr(k) ? 1 : 0)) * gap / 2} />{/if}</div>
                <div class="tb" style={barPos(at[c.id])}>
                    <span class="grip" title="Drag to move {labelOf(c)}"><GripVertical size={14} /></span>
                    {#if c.section && tools}<i></i>{@render tools(c.id)}{/if}
                    {#if !c.section && kindsFor(metaOf(c)).length > 1}
                        <i></i><span class="grp" data-nodrag role="group" aria-label="Kind">{#each TYPES.filter(([t]) => kindsFor(metaOf(c)).includes(t)) as [t, l] (t)}<button type="button" class="ic" class:on={c.type === t} aria-pressed={c.type === t} title={l} on:click={() => setKind(c, t)}><svelte:component this={KIND_ICON[t]} size={14} /></button>{/each}</span>
                    {/if}
                    {#if widthsFor(c.type).length > 1}
                        <i></i><button type="button" class="dd" class:on={menu?.id === c.id && menu.kind === 'w'} data-nodrag title="Width" on:click|stopPropagation={(e) => openMenu(e, c, 'w')}>{WIDTH_NAMES[c.wk]}<ChevronDown size={12} /></button>
                    {/if}
                    {#if heightsFor(c.type, c.wk).length > 1}
                        <button type="button" class="dd" class:on={menu?.id === c.id && menu.kind === 'h'} data-nodrag title="Height" on:click|stopPropagation={(e) => openMenu(e, c, 'h')}>{heightName(c.hk)}<ChevronDown size={12} /></button>
                    {/if}
                    {#if !c.section && availOf(c).length > 1}
                        <i></i><button type="button" class="dd" class:on={menu?.id === c.id && menu.kind === 'hosts'} data-nodrag title="Hosts" on:click|stopPropagation={(e) => openMenu(e, c, 'hosts')}>{hostsLabel(c)}<ChevronDown size={12} /></button>
                    {/if}
                    {#if !c.section && c.type !== 'gauge'}
                        <i></i><button type="button" class="dd" class:on={menu?.id === c.id && menu.kind === 'range'} data-nodrag title="Time range" on:click|stopPropagation={(e) => openMenu(e, c, 'range')}>{rangeLabel(c.range || $mlayout.range)}<ChevronDown size={12} /></button>
                    {/if}
                    <i></i>
                    <span class="grp" data-nodrag>
                        {#if cards.length > 1}
                            <button class="ic" title="Move earlier" disabled={readOrder[0] === c.id} on:click={() => nudge(c.id, -1)}><ChevronLeft size={14} /></button>
                            <button class="ic" title="Move later" disabled={readOrder.at(-1) === c.id} on:click={() => nudge(c.id, 1)}><ChevronRight size={14} /></button>
                        {/if}
                        <button class="ic del" title="Remove {labelOf(c)}" on:click={() => remove(c)}><Trash2 size={13} /></button>
                    </span>
                </div>
                {#if joinable(k)}
                    <button type="button" class="tjb" data-nodrag title={jl(k) ? 'Split into two cards' : 'Merge into one card'} aria-label={jl(k) ? 'Split into two cards' : 'Merge into one card'} on:click|stopPropagation={() => toggleJoin('metrics', cards[k - 1].id, c.id)}></button>
                {/if}
            </div>
        {:else}
            <div class="slot" class:fit={c.auto} class:tj-l={jl(k)} class:tj-r={jr(k)} data-mid={c.id} style={at[c.id] ? place(at[c.id], c.auto) : ''}>{#if c.section}{@render sec?.(c.id, true)}{:else}<MetricCard card={c} range={$mlayout.range} cat={$catalog} ext={((jl(k) ? 1 : 0) + (jr(k) ? 1 : 0)) * gap / 2} editable />{/if}</div>
        {/if}
    {/each}
</div>

<svelte:window on:click={() => menu = null} on:scroll|capture={() => menu = null} on:resize={() => menu = null} on:keydown={(e) => e.key === 'Escape' && (menu = null)} />
{#if menu && mc}
    <div class="mmenu" use:portal style="top: {menu.top}px; left: {menu.left}px" role="menu" tabindex="-1" on:click|stopPropagation on:keydown={() => {}}>
        {#if menu.kind === 'w'}
            {#each widthsFor(mc.type) as z (z)}<button role="menuitemradio" aria-checked={mc.wk === z} on:click={() => { setDim(mc, { w: z, h: heightsFor(mc.type, z).includes(mc.hk) ? mc.hk : heightsFor(mc.type, z)[0] }); menu = null; }}><span>{WIDTH_NAMES[z]}</span>{#if mc.wk === z}<Check size={13} />{/if}</button>{/each}
        {:else if menu.kind === 'h'}
            {#each heightsFor(mc.type, mc.wk) as z (z)}<button role="menuitemradio" aria-checked={mc.hk === z} on:click={() => { setDim(mc, { h: z }); menu = null; }}><span>{heightName(z)}</span>{#if mc.hk === z}<Check size={13} />{/if}</button>{/each}
        {:else if menu.kind === 'range'}
            {#each RANGES as [r, l] (r)}<button role="menuitemradio" aria-checked={(mc.range || $mlayout.range) === r} on:click={() => { setCard(mc.id, { range: r }); menu = null; }}><span>{l}</span>{#if (mc.range || $mlayout.range) === r}<Check size={13} />{/if}</button>{/each}
        {:else}
            {#each availOf(mc) as h (h)}<button role={single(mc) ? 'menuitemradio' : 'menuitemcheckbox'} aria-checked={picked(mc).includes(h)} on:click={() => { toggleHost(mc, h); if (single(mc)) menu = null; }}><span>{hname(h)}</span>{#if picked(mc).includes(h)}<Check size={13} />{/if}</button>{/each}
            {#if mc.type === 'line' && !single(mc) && availOf(mc).length > 3}<small>Up to 3 hosts</small>{/if}
        {/if}
    </div>
{/if}


<style>
    /* square cells (columns and row height from the script); each widget spans 1×1, 2×1, 2×2
       or a whole row, and fills exactly that */
    .mgrid { --g: 16px; display: grid; gap: var(--g); align-items: stretch; }
    .slot { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
    .slot > :global(*) { flex: 1; min-height: 0; }
    /* a widget is exactly its cells (min-height from the script); a card or section (.fit) sets its
       row's height by what it shows, and everything in the row stretches to the tallest */
    .slot:not(.fit) { contain: size; }
    /* a row is as tall as its tallest item (a row of short sections stays short); everything in
       it fills that height, so the avatar or a text card beside a host card or the rack matches it */
    /* a section on the grid fills its cells exactly (the avatar's square, a text card) */
    .slot :global(.msr) { display: flex; flex-direction: column; min-height: 0; }
    .slot :global(.msr > *) { flex: 1; min-height: 0; }
    .slot :global(.sq) { width: auto; min-height: 0; }
    .slot :global(.note) { overflow: hidden; }
    .ed :global(.sq), .ed :global(.note) { border-color: transparent; }
    /* a host or machine card fills its cells; its parts keep their height, spread top to bottom */
    .slot :global(.emb), .slot :global(.ui-cardgrid) { display: flex; flex-direction: column; flex: 1; min-height: 0; gap: 0; }
    /* the cluster's tiles share the section's height (each row of tiles as tall) */
    .slot :global(#sec-totals) { flex: 1; display: flex; flex-direction: column; min-height: 0; }
    .slot :global(.ui-summary.cluster) { flex: 1; grid-auto-rows: 1fr; }
    .slot :global(.mcard) { flex: 1; justify-content: space-between; }
    /* host and machine cards on the Overview: no addresses, at any width */
    .slot :global(.mcard .addr) { display: none; }
    .ed :global(.mcard) { border-color: transparent; }
    /* merged with a neighbour: one card, a line between (the slot itself carries .tj-l/.tj-r;
       the card inside loses its corners and left border) */
    .slot:global(.tj-l) { border-left: none !important; }
    .slot:global(.tj-l) > :global(*) :global(.w), .slot:global(.tj-l) :global(.w), .slot:global(.tj-l) :global(.ui-stat.mb) { border-left: none; border-top-left-radius: 0; border-bottom-left-radius: 0; }
    .slot:global(.tj-r) :global(.w), .slot:global(.tj-r) :global(.ui-stat.mb) { border-top-right-radius: 0; border-bottom-right-radius: 0; }
    .slot:global(.tj-l) :global(.flush) { border-bottom-left-radius: 0; }
    .slot:global(.tj-r) :global(.flush) { border-bottom-right-radius: 0; }
    /* dragged (its copy, its place) and whatever it was merged with: cards of their own again */
    .slot:global(.sort-free) :global(.w), .slot:global(.sort-free) :global(.ui-stat.mb) { border-radius: var(--radius-card, 8px) !important; }
    :global(.sort-free) + .slot:global(.tj-l) :global(.w), :global(.sort-free) + .slot:global(.tj-l) :global(.ui-stat.mb) { border-top-left-radius: var(--radius-card, 8px); border-bottom-left-radius: var(--radius-card, 8px); }
    .slot:global(.tj-r):has(+ :global(.sort-free)) :global(.w), .slot:global(.tj-r):has(+ :global(.sort-free)) :global(.ui-stat.mb) { border-top-right-radius: var(--radius-card, 8px); border-bottom-right-radius: var(--radius-card, 8px); }
    /* the merge marker: slots have no border of their own */
    .mgrid :global(.tjb) { left: calc(-0.5 * var(--g)); }
    .mgrid :global(.tj-l > .tjb) { left: -0.5px; }

    /* ---- editing: the widgets as on the page, border dashed, tools in a bar on the corner ---- */
    .canvas { --g: 14px; }
    /* the same as a section being customized: a dashed outline around it as it is */
    .ed { position: relative; display: flex; border-radius: var(--radius-card, 8px); cursor: grab; touch-action: none; outline: 1px dashed var(--border-strong); outline-offset: 0; transition: outline-color .12s; }
    .ed:hover { outline-color: var(--text-secondary); }
    /* one line: the dashed outline sits where the card's own border is */
    .ed :global(.w), .ed :global(.ui-stat) { border-color: transparent; }
    .ed:global(.dragging) { cursor: grabbing; outline: 1px solid var(--accent); box-shadow: 0 14px 34px rgba(0, 0, 0, .35); }
    /* (the widget only drags; its own controls don't react) */
    .ec { flex: 1; min-width: 0; display: flex; flex-direction: column; pointer-events: none; position: relative; z-index: 0; }
    .ec > :global(*) { flex: 1; }
    /* its tools: the same bar as a section's, on the top edge, half in the gap above; shown
       while hovered or focused (always on touch) */
    .tb { position: absolute; top: 0; width: max-content; display: flex; align-items: center; flex-wrap: wrap; gap: 2px; padding: 2px; border-radius: 8px; background: var(--surface) linear-gradient(var(--highlight-10), var(--highlight-10)); border: 1px solid var(--border-strong); box-shadow: 0 4px 14px rgba(0, 0, 0, .35); z-index: 3; opacity: 0; transform: translateY(calc(-50% + 3px)); pointer-events: none; transition: opacity .12s, transform .12s; cursor: default; }
    .ed:hover .tb, .ed:focus-within .tb { opacity: 1; transform: translateY(-50%); pointer-events: auto; z-index: 4; }
    .ed:global(.dragging) .tb { opacity: 0; }
    @media (hover: none) { .tb { opacity: 1; transform: translateY(-50%); pointer-events: auto; } }
    .tb i { width: 1px; height: 14px; margin: 0 3px; background: var(--border-strong); }
    /* a group with nothing in it (web apps has no settings) leaves no empty gap between lines */
    .tb i + i { display: none; }
    .grp { display: flex; align-items: center; gap: 1px; }
    .grip { width: 20px; height: 24px; display: flex; align-items: center; justify-content: center; color: var(--text-secondary); cursor: grab; }
    .tb button { height: 24px; display: flex; align-items: center; justify-content: center; border-radius: 6px; color: var(--text-secondary); cursor: pointer; white-space: nowrap; }
    .tb button:hover:not(:disabled) { background: var(--highlight-10); color: var(--text-primary); }
    .tb button:disabled { opacity: .3; cursor: default; }
    .tb .ic { width: 26px; }
    .tb .ic.del:hover { color: var(--red); }
    /* a toggle: what's picked in plain text on a fill, the rest muted (as a section's) */
    .tb .ic.on { background: var(--highlight-15); color: var(--text-primary); }
    /* a section's own toggles (from the Overview's snippet) look like the rest of the bar */
    .tb :global(.grp) { display: flex; align-items: center; gap: 1px; }
    .tb :global(.tg) { height: 24px; padding: 0 8px; display: flex; align-items: center; border-radius: 6px; font-size: 12px; color: var(--text-secondary); cursor: pointer; white-space: nowrap; }
    .tb :global(.tg:hover) { background: var(--highlight-10); color: var(--text-primary); }
    .tb :global(.tg.on) { background: var(--highlight-15); color: var(--text-primary); font-weight: 500; }
    .tb { box-sizing: border-box; }
    .ed.held .tb { opacity: 1; transform: translateY(-50%); pointer-events: auto; z-index: 4; }
    .tb .dd { gap: 3px; padding: 0 5px 0 8px; font-size: 12px; color: var(--text-primary); }
    .tb .dd :global(svg) { color: var(--text-secondary); }
    .tb .dd.on { background: var(--highlight-10); }
    /* a narrow screen drags the widget anywhere on it: no grip */
    @media (max-width: 760px) { .grip, .grip + i { display: none; } }
    /* the list a bar button opens: as solid as the bar */
    .mmenu { position: fixed; z-index: 300; min-width: 150px; max-width: 200px; display: flex; flex-direction: column; padding: 3px; border-radius: 8px; background: var(--surface) linear-gradient(var(--highlight-10), var(--highlight-10)); border: 1px solid var(--border-strong); box-shadow: 0 12px 32px rgba(0, 0, 0, .6); }
    .mmenu button { display: flex; align-items: center; justify-content: space-between; gap: 10px; height: 28px; padding: 0 8px 0 10px; border-radius: 6px; font-size: 12.5px; color: var(--text-secondary); text-align: left; cursor: pointer; }
    .mmenu button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .mmenu button:hover { background: var(--highlight-10); color: var(--text-primary); }
    .mmenu button[aria-checked="true"] { color: var(--text-primary); font-weight: 500; }
    .mmenu small { padding: 4px 10px 3px; font-size: 11px; color: var(--text-secondary); }

    @media (max-width: 760px) {
        .mgrid { --g: 10px; }
    }
</style>
