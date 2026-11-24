<script>
    import { onMount } from 'svelte';
    import { ChevronLeft, ChevronRight, ChevronDown, Check, Trash2, GripVertical, ChartLine, ChartBarStacked, Gauge } from 'lucide-svelte';
    import MetricCard from './MetricCard.svelte';
    import { layout, toggleJoin, joinKey, keepJoinsIf } from '../../lib/widgets.js';
    import { tick, beforeUpdate, afterUpdate } from 'svelte';
    import { mlayout, catalog, loadCatalog, removeCard, setCard, splitGauges, cellOf, gridLayout, pushLayout, setPositions, TYPES, SIZES, SIZE_NAMES, NET, RANGES, sizeFor, kindsFor } from '../../lib/metrics.js';

    // A run of metric widgets that sit next to each other among the Overview's sections
    // (each widget is its own item in the Overview's order, 'm:<id>'), laid out in one grid.
    // editing (the Overview's Customize): each widget is a row of the editor's drag list,
    // with its settings and tools in a bar on its top edge, as a section's are (no dialog).
    export let ids = [];                // the widgets of this run, in order
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

    $: cards = ids.map(i => $mlayout.cards.find(c => c.id === i)).filter(Boolean);
    $: $mlayout, splitGauges($catalog);
    // a grid of square cells: how many to a row and how big, from the grid's own width
    let gw = 1100, gridEl, gap = 16;
    $: gw, gridEl && (gap = parseFloat(getComputedStyle(gridEl).columnGap) || 0);
    $: cell = cellOf(gw, gap);
    // where each widget sits (cells): kept where it was put; while one is dragged, the others
    // moving out of its way (worked out from the layout as it was when the drag began)
    $: base = gridLayout(cards, cell.n);
    let preview = null, snap = null;
    $: at = preview || base;
    const place = (p) => `grid-column: ${p.x + 1} / span ${p.w}; grid-row: ${p.y + 1} / span ${p.h}`;
    // called by the drag (lib/sortable.js): the widget is over cell (x, y); null: it left the grid
    function moveTo(mid, x, y) {
        if (mid == null) { preview = null; snap = null; return; }
        if (!snap) snap = base;
        if (!snap[mid]) return;
        preview = pushLayout(snap, mid, x, y, cell.n);
    }
    // let go: every widget of this grid keeps its place (for this grid size), and the run takes
    // their reading order (what a narrower screen lays out)
    function commit() {
        if (preview) {
            const p = preview;
            setPositions(cell.n, p);
            arrange(Object.entries(p).sort((a, b) => a[1].y - b[1].y || a[1].x - b[1].x).map(([id]) => 'm:' + id));
            // a merge stays only between two widgets still touching on one row, as tall
            const touch = (a, b) => a && b && a.y === b.y && a.h === b.h && a.x + a.w === b.x;
            keepJoinsIf('metrics', (a, b) => !(a in p && b in p) || touch(p[a], p[b]) || touch(p[b], p[a]));
        }
        preview = null; snap = null;
    }
    // the arrows on a widget: one cell left or right
    function nudge(mid, d) { snap = base; const p = base[mid]; moveTo(mid, p.x + d * p.w, p.y); commit(); }
    $: if (gridEl) { gridEl.__moveTo = moveTo; gridEl.__commit = commit; }
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
    $: jl = (k) => k > 0 && beside[cards[k].id] && joins.includes(joinKey(cards[k - 1].id, cards[k].id));
    $: jr = (k) => k < cards.length - 1 && jl(k + 1);
    $: labelOf = (c) => c.title || $catalog?.metrics.find(m => m.key === c.metric)?.label || c.metric;
</script>

<div class="mgrid" class:canvas={editing} bind:clientWidth={gw} bind:this={gridEl} data-cells={cell.n} style="grid-template-columns: repeat({cell.n}, minmax(0, 1fr)); grid-auto-rows: {cell.unit}px">
    {#each cards as c, k (c.id)}
        {#if editing}
            {@const n = nOf('m:' + c.id)}
            <div class="slot ed" class:held={menu?.id === c.id} class:tj-l={jl(k)} class:tj-r={jr(k)} style={at[c.id] ? place(at[c.id]) : ''} data-mid={c.id} data-span="{at[c.id]?.w} {at[c.id]?.h}" data-id={'m:' + c.id} data-n={n} data-handle>
                <div class="ec"><MetricCard card={c} range={$mlayout.range} cat={$catalog} ext={((jl(k) ? 1 : 0) + (jr(k) ? 1 : 0)) * gap / 2} /></div>
                <div class="tb" style={barPos(at[c.id])}>
                    <span class="grip" title="Drag to move {labelOf(c)}"><GripVertical size={14} /></span>
                    {#if kindsFor(metaOf(c)).length > 1}
                        <i></i><span class="grp" data-nodrag role="group" aria-label="Kind">{#each TYPES.filter(([t]) => kindsFor(metaOf(c)).includes(t)) as [t, l] (t)}<button type="button" class="ic" class:on={c.type === t} aria-pressed={c.type === t} title={l} on:click={() => setKind(c, t)}><svelte:component this={KIND_ICON[t]} size={14} /></button>{/each}</span>
                    {/if}
                    {#if (SIZES[c.type] || []).length > 1}
                        <i></i><button type="button" class="dd" class:on={menu?.id === c.id && menu.kind === 'size'} data-nodrag title="Size" on:click|stopPropagation={(e) => openMenu(e, c, 'size')}>{SIZE_NAMES[sizeFor(c.type, c.width)]}<ChevronDown size={12} /></button>
                    {/if}
                    {#if availOf(c).length > 1}
                        <i></i><button type="button" class="dd" class:on={menu?.id === c.id && menu.kind === 'hosts'} data-nodrag title="Hosts" on:click|stopPropagation={(e) => openMenu(e, c, 'hosts')}>{hostsLabel(c)}<ChevronDown size={12} /></button>
                    {/if}
                    {#if c.type !== 'gauge'}
                        <i></i><button type="button" class="dd" class:on={menu?.id === c.id && menu.kind === 'range'} data-nodrag title="Time range" on:click|stopPropagation={(e) => openMenu(e, c, 'range')}>{rangeLabel(c.range || $mlayout.range)}<ChevronDown size={12} /></button>
                    {/if}
                    <i></i>
                    <span class="grp" data-nodrag>
                        {#if c.type !== 'gauge' && at[c.id] && at[c.id].w < cell.n}
                            <button class="ic" title="Move left" disabled={!at[c.id]?.x} on:click={() => nudge(c.id, -1)}><ChevronLeft size={14} /></button>
                            <button class="ic" title="Move right" disabled={at[c.id] && at[c.id].x + at[c.id].w >= cell.n} on:click={() => nudge(c.id, 1)}><ChevronRight size={14} /></button>
                        {/if}
                        <button class="ic del" title="Remove {labelOf(c)}" on:click={() => removeCard(c.id)}><Trash2 size={13} /></button>
                    </span>
                </div>
                {#if k > 0 && beside[c.id]}
                    <button type="button" class="tjb" data-nodrag title={jl(k) ? 'Split into two cards' : 'Merge into one card'} aria-label={jl(k) ? 'Split into two cards' : 'Merge into one card'} on:click|stopPropagation={() => toggleJoin('metrics', cards[k - 1].id, c.id)}></button>
                {/if}
            </div>
        {:else}
            <div class="slot" class:tj-l={jl(k)} class:tj-r={jr(k)} data-mid={c.id} style={at[c.id] ? place(at[c.id]) : ''}><MetricCard card={c} range={$mlayout.range} cat={$catalog} ext={((jl(k) ? 1 : 0) + (jr(k) ? 1 : 0)) * gap / 2} editable /></div>
        {/if}
    {/each}
</div>

<svelte:window on:click={() => menu = null} on:scroll|capture={() => menu = null} on:resize={() => menu = null} on:keydown={(e) => e.key === 'Escape' && (menu = null)} />
{#if menu && mc}
    <div class="mmenu" use:portal style="top: {menu.top}px; left: {menu.left}px" role="menu" tabindex="-1" on:click|stopPropagation on:keydown={() => {}}>
        {#if menu.kind === 'size'}
            {#each SIZES[mc.type] as [z, l] (z)}<button role="menuitemradio" aria-checked={sizeFor(mc.type, mc.width) === z} on:click={() => { setCard(mc.id, { width: z }); menu = null; }}><span>{l}</span>{#if sizeFor(mc.type, mc.width) === z}<Check size={13} />{/if}</button>{/each}
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
    .grp { display: flex; align-items: center; gap: 1px; }
    .grip { width: 20px; height: 24px; display: flex; align-items: center; justify-content: center; color: var(--text-secondary); cursor: grab; }
    .tb button { height: 24px; display: flex; align-items: center; justify-content: center; border-radius: 6px; color: var(--text-secondary); cursor: pointer; white-space: nowrap; }
    .tb button:hover:not(:disabled) { background: var(--highlight-10); color: var(--text-primary); }
    .tb button:disabled { opacity: .3; cursor: default; }
    .tb .ic { width: 26px; }
    .tb .ic.del:hover { color: var(--red); }
    /* a toggle: what's picked in plain text on a fill, the rest muted (as a section's) */
    .tb .ic.on { background: var(--highlight-15); color: var(--text-primary); }
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
