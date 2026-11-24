<script>
    import { onMount, tick } from 'svelte';
    import { SlidersHorizontal, ArrowLeft, RotateCcw, EyeOff, ArrowUp, ArrowDown, ChevronLeft, ChevronRight, Plus, X } from 'lucide-svelte';
    import { SN } from '../../lib/server.js';
    import { layout, sectionSizes, OVERVIEW_WIDGETS, SECTION_TILES, SHORTCUTS, COLS, toggleWidget, toggleHostCard, toggleTile, setTotalsCols, setWidgetOrder, setWidth, setShortcuts, resetLayout } from '../../lib/widgets.js';
    import { hosts, hostOrder, saveHostOrder, byOrder } from '../../lib/hosts.js';
    import { sortable } from '../../lib/sortable.js';
    import { crumbLabels } from '../../lib/stores.js';
    import { webLinks, pinnedLinks } from '../../lib/weblinks.js';
    import { services } from '../../lib/services.js';
    crumbLabels.update(c => ({ ...c, customize: 'Customize' }));

    // Customize the Overview at #overview/customize: a wireframe of the page (layout and names,
    // no figures) where sections are moved, hidden and brought back.
    // mode 'button': the Customize button in the Overview's header; 'editor': the page itself,
    // which the Overview shows in place of its sections at #overview/customize
    export let mode = 'button';
    const HASH = '#overview/customize';
    let canvas;
    const close = () => { location.hash = '#overview'; };

    const label = Object.fromEntries(OVERVIEW_WIDGETS.map(w => [w.id, w.label]));
    $: hidden = new Set($layout.hidden);
    $: hiddenHosts = new Set($layout.hidden_hosts);
    $: hiddenTiles = new Set($layout.hidden_tiles);
    $: hiddenCount = hidden.size + $layout.hidden_hosts.length + $layout.hidden_tiles.length;

    const shortOs = (o) => (o || '').replace(/ GNU\/Linux/, '').replace(/\s*\(.*\)$/, '');
    $: hostList = byOrder([{ id: 'arrakis', name: SN, os: 'macOS · this server' }, ...($hosts || []).map(h => ({ id: h.id, name: h.name, os: h.report ? shortOs(h.report.os) : 'agent not installed' }))], $hostOrder);
    const TILE_TITLE = { hosts: 'Hosts', cpu: 'CPU in use', mem: 'Memory in use', disk: 'Storage' };
    $: shownSections = $layout.order.filter(id => !hidden.has(id));
    $: shownHosts = hostList.filter(h => !hiddenHosts.has(h.id));
    // dragging in the canvas moves shown items; hidden ones keep their slot in the order
    const merge = (full, hide, now) => { let k = 0; return full.map(id => hide.has(id) ? id : now[k++]); };
    const moveShown = (ids) => setWidgetOrder(merge($layout.order, hidden, ids));

    // 'Fit screen' as the page does it: by the section's width (half: two per row, no Hosts)
    $: totHalf = $layout.widths.totals === 'half' && vw > 1000;
    $: totShown = SECTION_TILES.totals.filter(t => !hiddenTiles.has(t.id) && !(t.id === 'hosts' && $layout.totals_cols === 'auto' && totHalf));
    // 'auto' fits the screen: on a wide one that's every tile in one row, as drawn here
    $: perRow = Math.max(1, $layout.totals_cols === 'auto' ? Math.min(totHalf ? 2 : 4, totShown.length || 1) : Math.min(+$layout.totals_cols, totHalf ? 2 : 4, totShown.length || 1));
    // a half-width row fits two tiles at most
    $: colChoices = ['auto', ...COLS.filter(c => c !== 'auto' && +c <= Math.max(1, Math.min(totShown.length, totHalf ? 2 : 4)))];
    // the cluster tiles' height per row of tiles, from whichever setting was last seen on the page
    $: totRows = Math.max(1, Math.ceil(totShown.length / perRow));
    function totSize(sizes, mode) {
        const exact = sizes[`totals:${mode}:${totRows}`];
        if (exact) return exact;
        const k = Object.keys(sizes).find(x => x.startsWith(`totals:${mode}:`)) || Object.keys(sizes).find(x => x.startsWith('totals:') && x.split(':').length === 3);
        if (!k) return null;
        const r = +k.split(':')[2] || 1, m = sizes[k];
        return { w: m.w, h: (m.h + 12) / r * totRows - 12 };
    }
    $: spanOf = (i) => { const r = totShown.length % perRow; return r && i === totShown.length - 1 ? perRow - r + 1 : 1; };
    $: attShown = SECTION_TILES.attention.filter(t => !hiddenTiles.has(t.id));

    // move a shown section or host card one place; hidden ones keep their slot
    function step(list, id, d) { const o = [...list], i = o.indexOf(id), j = i + d; if (i < 0 || j < 0 || j >= o.length) return null; [o[i], o[j]] = [o[j], o[i]]; return o; }
    const moveSection = (id, d) => { const o = step(shownSections, id, d); if (o) moveShown(o); };
    const moveHost = (id, d) => { const o = step(shownHosts.map(h => h.id), id, d); if (o) saveHostOrder(merge(hostList.map(h => h.id), hiddenHosts, o)); };
    $: hiddenSections = $layout.order.filter(id => hidden.has(id));
    $: tileGhosts = (sec) => SECTION_TILES[sec].filter(t => hiddenTiles.has(t.id));
    $: hostGhosts = hostList.filter(h => hiddenHosts.has(h.id));
    // as on the page: consecutive half-width sections share two columns (one column when narrow)
    let vw = 1440;
    $: groups = (() => { const out = []; for (const id of shownSections) { const half = $layout.widths[id] === 'half' && vw > 1000, last = out.at(-1); if (half && last?.half) last.ids.push(id); else out.push({ key: id, half, ids: [id] }); } return out; })();
    // a section's preview is as tall as the section really is (measured on the Overview),
    // scaled by how much narrower the preview is; unmeasured ones keep their own height
    function fitHeight(node, size) {
        let sz = size;
        // the first child is the section's own card(s); "+ add" chips after it stay outside
        const set = () => { const c = node.firstElementChild; if (c?.classList.contains('scs')) return; if (c) c.style.minHeight = sz && sz.w ? Math.round(sz.h * node.clientWidth / sz.w) + 'px' : ''; };
        const ro = new ResizeObserver(set); ro.observe(node); set();
        return { update(n) { sz = n; set(); }, destroy() { ro.disconnect(); } };
    }
    // the pinned web apps, by name (as the page's chips)
    $: links = pinnedLinks($webLinks, $services).slice(0, 6);
    const scLabel = Object.fromEntries(SHORTCUTS.map(x => [x.id, x.label]));
    $: scLeft = SHORTCUTS.filter(x => !$layout.shortcuts.includes(x.id));
    const scMove = (k, d) => { const o = step($layout.shortcuts, k, d); if (o) setShortcuts(o); };
    const BAR = { cpu: 'var(--metric-cpu)', mem: 'var(--metric-mem)', disk: 'var(--text-secondary)', updates: 'var(--metric-net)', apps: 'var(--metric-disk)' };
</script>

<svelte:window bind:innerWidth={vw} on:keydown={e => mode === 'editor' && e.key === 'Escape' && close()} />

{#if mode === 'button'}
<button class="ui-btn" on:click={() => location.hash = HASH}>
    <SlidersHorizontal size={14} /> Customize{#if hiddenCount}<span class="cust-n">{hiddenCount} hidden</span>{/if}
</button>
{:else}
<div class="ui-page editor">
    <div class="ui-head">
        <div>
            <h1>Customize overview</h1>
            <p>Drag a section to move it, or use its arrows. Changes apply right away and are saved for every device.</p>
        </div>
        <div class="ui-head-actions">
            <button class="ui-btn" on:click={resetLayout}><RotateCcw size={14} /> Reset</button>
            <button class="ui-btn primary" on:click={close}>Done</button>
        </div>
    </div>

    <div class="eb">

        <!-- the wireframe: the page's layout, no data -->
        <div class="canvas" bind:this={canvas}>
            <div class="page">
                {#if hiddenSections.length}
                    <div class="tray"><span class="tray-k">Hidden sections</span>{#each hiddenSections as id (id)}<button class="ghost-chip" on:click={() => toggleWidget(id)}><Plus size={12} />{label[id]}</button>{/each}</div>
                {/if}
                {#snippet frameOf(id)}
                    {@const n = shownSections.indexOf(id)}
                        <div class="frame" class:half={$layout.widths[id] === 'half'} data-id={id} data-n={n} data-handle>
                            <div class="fh">
                                <span class="fn">{label[id]}</span>
                                <span class="ctl" data-nodrag>
                                    <span class="seg" title="Full width, or half so two sections share a row"><button class:on={$layout.widths[id] !== 'half'} on:click={() => setWidth(id, 'full')}>Full</button><button class:on={$layout.widths[id] === 'half'} on:click={() => setWidth(id, 'half')}>Half</button></span>
                                    {#if id === 'totals'}<span class="seg" title="How many tiles share a row. Fit screen: all in one row on a wide screen, fewer as it narrows."><span class="k">Tiles per row</span>{#each colChoices as c}<button class:on={c === 'auto' ? $layout.totals_cols === 'auto' : $layout.totals_cols !== 'auto' && perRow === +c} on:click={() => setTotalsCols(c)}>{c === 'auto' ? 'Fit screen' : c}</button>{/each}</span>{/if}
                                    <button class="cb" title="Move up" disabled={n === 0} on:click={() => moveSection(id, -1)}><ArrowUp size={13} /></button>
                                    <button class="cb" title="Move down" disabled={n === shownSections.length - 1} on:click={() => moveSection(id, 1)}><ArrowDown size={13} /></button>
                                    <button class="cb" title="Hide {label[id]}" on:click={() => toggleWidget(id)}><EyeOff size={13} /></button>
                                </span>
                            </div>
                            <div class="fc" use:fitHeight={id === 'totals' ? totSize($sectionSizes, $layout.widths.totals === 'half' && vw > 1000 ? 'half' : 'full') : ($sectionSizes[`${id}:${$layout.widths[id] === 'half' && vw > 1000 ? 'half' : 'full'}`] || $sectionSizes[`${id}:full`] || $sectionSizes[`${id}:half`])}>

                            {#if id === 'webapps'}
                                <div class="wf card row"><span class="tx t wa">Web apps</span>{#each links.length ? links : [{ name: 'App' }, { name: 'App' }] as l}<span class="pill"><b class="gl"></b><span class="tx">{l.name}</span></span>{/each}<span class="pill add"><Plus size={12} /></span></div>
                            {:else if id === 'attention'}
                                {#if attShown.length}
                                    <div class="wf card split">{#each attShown as t (t.id)}<div class="cell">
                                        <button class="hx" data-nodrag title="Hide {t.label}" on:click|stopPropagation={() => toggleTile(t.id)}><EyeOff size={12} /></button>
                                        <span class="tx">{t.label}</span><i class="num"></i>{#if t.id === 'backups'}<i class="days"></i>{:else}<i class="bar" style="--c: {BAR[t.id]}; --w: 70%"></i>{/if}</div>{/each}</div>
                                {:else}<div class="none">Every part is hidden</div>{/if}
                                {#if tileGhosts('attention').length}<div class="ghosts">{#each tileGhosts('attention') as t (t.id)}<button class="ghost-chip" on:click={() => toggleTile(t.id)}><Plus size={12} />{t.label}</button>{/each}</div>{/if}
                            {:else if id === 'totals'}
                                {#if totShown.length}
                                    <div class="tiles" style="grid-template-columns: repeat({perRow}, minmax(0, 1fr))">
                                        {#each totShown as t, i (t.id)}
                                            <div class="wf card tile" style="grid-column: span {spanOf(i)}">
                                                <button class="hx" data-nodrag title="Hide {t.label}" on:click|stopPropagation={() => toggleTile(t.id)}><EyeOff size={12} /></button>
                                                <span class="tx">{TILE_TITLE[t.id]}</span><i class="num"></i>{#if t.id !== 'hosts'}<i class="bar" style="--c: {BAR[t.id]}; --w: {t.id === 'cpu' ? 30 : t.id === 'mem' ? 60 : 45}%"></i><i class="ln w60"></i>{:else}<i class="ln w50"></i>{/if}
                                            </div>
                                        {/each}
                                    </div>
                                {:else}<div class="none">Every tile is hidden</div>{/if}
                                {#if tileGhosts('totals').length}<div class="ghosts">{#each tileGhosts('totals') as t (t.id)}<button class="ghost-chip" on:click={() => toggleTile(t.id)}><Plus size={12} />{t.label}</button>{/each}</div>{/if}
                            {:else if id === 'host'}
                                {#if shownHosts.length}
                                    <div class="hosts" data-nodrag use:sortable={{ onMove: (ids) => hostOrder.set(merge(hostList.map(h => h.id), hiddenHosts, ids)), onDrop: () => saveHostOrder($hostOrder) }}>
                                        {#each shownHosts as h, k (h.id)}
                                            <div class="wf card hc" data-id={h.id} data-n={k} data-handle>
                                                <span class="hh"><b class="ico"></b><span class="hl"><span class="tx t">{h.name}</span><span class="tx sub">{h.os}</span></span>
                                                    <b class="pillst"></b>
                                                    <span class="hctl" data-nodrag>
                                                        <button class="cb" title="Move earlier" disabled={k === 0} on:click|stopPropagation={() => moveHost(h.id, -1)}><ChevronLeft size={13} /></button>
                                                        <button class="cb" title="Move later" disabled={k === shownHosts.length - 1} on:click|stopPropagation={() => moveHost(h.id, 1)}><ChevronRight size={13} /></button>
                                                        <button class="cb" title="Hide {h.name}" on:click|stopPropagation={() => toggleHostCard(h.id)}><EyeOff size={12} /></button>
                                                    </span></span>
                                                <span class="mtr">{#each [['cpu', 'CPU', 30], ['mem', 'Memory', 55], ['disk', 'Storage', 40]] as [kk, l, w]}<span class="mr"><span class="tx k">{l}</span><i class="bar" style="--c: {BAR[kk]}; --w: {w}%"></i><i class="ln val"></i></span>{/each}</span>
                                                <span class="ft"><b class="chip2"></b><b class="chip2"></b><i class="ln ip"></i></span>
                                            </div>
                                        {/each}
                                    </div>
                                {:else}<div class="none">Every host card is hidden</div>{/if}
                                {#if hostGhosts.length}<div class="ghosts">{#each hostGhosts as h (h.id)}<button class="ghost-chip" on:click={() => toggleHostCard(h.id)}><Plus size={12} />{h.name}</button>{/each}</div>{/if}
                            {:else if id === 'tailscale'}
                                <div class="wf card ts">
                                    <span class="tx t">Tailscale</span>
                                    <span class="tsb"><span class="tx">Online</span><span class="tx">In use</span><span class="tx r">Traffic</span></span>
                                    <span class="two">{#each ['In use', 'Idle'] as c}<span class="col"><span class="tx t sm"><i class="dot" class:up={c === 'In use'}></i>{c}</span>{#each [0, 1, 2] as k}<span class="dev"><b class="ico sm"></b><span class="hl"><i class="ln w40"></i><i class="ln w60"></i></span></span>{/each}</span>{/each}</span>
                                </div>
                            {:else if id === 'shortcuts'}
                                <div class="scs" style="--n: {Math.max(1, $layout.shortcuts.length)}">
                                    {#each $layout.shortcuts as k, i (k)}
                                        <div class="wf card sc"><b class="ico acc"></b><span class="hl"><span class="tx">{scLabel[k]}</span><i class="num sm"></i></span>
                                            <span class="hctl" data-nodrag>
                                                <button class="cb" title="Move earlier" disabled={i === 0} on:click|stopPropagation={() => scMove(k, -1)}><ChevronLeft size={13} /></button>
                                                <button class="cb" title="Move later" disabled={i === $layout.shortcuts.length - 1} on:click|stopPropagation={() => scMove(k, 1)}><ChevronRight size={13} /></button>
                                                <button class="cb" title="Remove {scLabel[k]}" on:click|stopPropagation={() => setShortcuts($layout.shortcuts.filter(x => x !== k))}><X size={12} /></button>
                                            </span>
                                        </div>
                                    {/each}
                                </div>
                                {#if scLeft.length}
                                    <div class="ghosts" data-nodrag>
                                        <span class="gk">Add</span>{#each scLeft as x (x.id)}<button class="ghost-chip" on:click={() => setShortcuts([...$layout.shortcuts, x.id])}><Plus size={12} />{x.label}</button>{/each}
                                    </div>
                                {/if}
                            {:else if id === 'compute'}
                                <div class="wf card tbl"><span class="tx t">Compute</span><span class="tr th">{#each ['Pool', 'Cores busy', 'Last 10 min', 'Running'] as c}<span class="tx k">{c}</span>{/each}</span>{#each [0, 1] as k}<span class="tr"><i class="ln"></i><i class="ln"></i><i class="ln"></i><i class="ln"></i></span>{/each}</div>
                            {:else if id === 'api-latency'}
                                <div class="wf card lat">
                                    <span class="lhd"><span class="hl"><span class="tx t">API latency</span><i class="ln w40"></i></span><span class="tx k">Endpoints →</span></span>
                                    <span class="lat-b"><span class="hero"><span class="tx">Typical response</span><i class="num"></i><i class="ln w80"></i></span>
                                        <span class="plot"><span class="slow"><span class="tx k">Slow</span></span><span class="hist">{#each [2, 3, 5, 4, 6, 3, 2, 4, 5, 8, 12, 16, 13, 9, 6, 4, 3, 2, 1, 2, 1, 0, 1, 1] as h}<i style="height: {6 + h * 3}px"></i>{/each}</span><span class="typ"></span>
                                            <span class="axis">{#each ['0.1 ms', '1 ms', '10 ms', '100 ms', '1 s'] as t}<span class="tx k">{t}</span>{/each}</span></span></span>
                                    <span class="lslow"><span class="tx k">Slowest</span><b class="chip2 w"></b><b class="chip2 w"></b><b class="chip2 w"></b></span>
                                </div>
                            {:else if id === 'uptime'}
                                <div class="wf card ulist"><span class="lhd"><span class="hl"><span class="tx t">Uptime</span><i class="ln w30"></i></span><span class="tx k">Checks →</span></span>
                                    {#each ['Check one', 'Check two'] as k}<span class="urow"><span class="hl"><i class="ln w60 strong"></i><i class="ln w40"></i></span><span class="ustrip"></span><span class="ufig"><i class="num sm"></i><i class="ln"></i></span></span>{/each}
                                </div>
                            {:else if id === 'pihole'}
                                <div class="wf card pih"><span class="lhd"><span class="hl"><span class="tx t">Pi-hole</span><i class="ln w30"></i></span><span class="tx k">Pi-hole →</span></span><span class="pcells">{#each ['Queries today', 'Blocked', 'Blocklist', 'Clients'] as k}<span class="cell"><span class="tx">{k}</span><i class="num"></i></span>{/each}</span></div>
                            {:else if id === 'machines'}
                                <div class="hosts">{#each ['rasputin-vm', 'sietch'] as name}<div class="wf card hc"><span class="hh"><b class="ico"></b><span class="hl"><span class="tx t">{name}</span><span class="tx sub">machine</span></span></span><span class="mtr">{#each [['cpu', 'CPU', 20], ['mem', 'Memory', 45]] as [kk, l, w]}<span class="mr"><span class="tx k">{l}</span><i class="bar" style="--c: {BAR[kk]}; --w: {w}%"></i><i class="ln val"></i></span>{/each}</span><span class="ft"><b class="chip2"></b></span></div>{/each}</div>
                            {/if}
                        </div>
                        </div>
                {/snippet}
                <div class="stack" use:sortable={{ onMove: moveShown }}>
                    {#each groups as g (g.key)}
                        {#if g.half}
                            <div class="pair">{#each [g.ids.filter((_, i) => i % 2 === 0), g.ids.filter((_, i) => i % 2 === 1)] as col}<div class="col">{#each col as id (id)}{@render frameOf(id)}{/each}</div>{/each}</div>
                        {:else}{@render frameOf(g.ids[0])}{/if}
                    {/each}
                    {#if !shownSections.length}<div class="none big">Every section is hidden</div>{/if}
                </div>
            </div>
        </div>
    </div>
</div>
{/if}

<style>
    .cust-n { font-size: 12px; font-weight: 400; color: var(--text-secondary); margin-left: 2px; }

    /* full screen, above the app's chrome */
    .editor .ui-head p { margin: 4px 0 0; }
    
    /* canvas: the page's width, centred */
    .canvas { user-select: none; -webkit-user-select: none; }
    .page { max-width: 1180px; }
    .wf-head { display: flex; flex-direction: column; gap: 8px; margin-bottom: 22px; }
    .stack { display: flex; flex-direction: column; gap: 14px; }
    .frame { min-width: 0; }
    /* the preview fills the section's measured height */
    .fc { display: flex; flex-direction: column; min-width: 0; }
    /* a preview spreads its contents over the section's real height instead of leaving a gap */
    .fc > :global(:first-child) { box-sizing: border-box; }
    .fc > :global(.wf.card) { justify-content: space-between; }
    .fc > :global(.wf.card.row) { justify-content: flex-start; }
    .fc > :global(.tiles), .fc > :global(.hosts) { align-content: stretch; }
    .fc :global(.tile) { justify-content: space-evenly; }
    .fc :global(.hc) { display: flex; flex-direction: column; }
    .fc :global(.hc .mtr) { flex: 1; justify-content: space-evenly; }
    .fc :global(.split .cell) { justify-content: space-evenly; }
    .fc :global(.lat .lat-b), .fc :global(.ts .two), .fc :global(.pih .pcells) { flex: 1; }
    .fc :global(.lat .plot) { height: auto; min-height: 90px; }
    .fc :global(.ts .col), .fc :global(.pcells .cell) { justify-content: space-evenly; }
    .fc :global(.ulist), .fc :global(.tbl) { justify-content: space-evenly; }
    .pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; align-items: start; }
    .col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }

    /* each section is a frame; its name sits in a tab on the frame's own top edge */
    .frame { position: relative; padding: 0 14px 14px; border: 1px dashed var(--border-strong); border-radius: 12px; cursor: grab; touch-action: none; background: var(--bg); transition: border-color .12s; }
    /* the frame's own header: name left, its controls right, inside the outline */
    .fh { display: flex; align-items: center; gap: 8px; min-height: 40px; }
    .fn { font-size: 12px; font-weight: 500; color: var(--text-secondary); }
    .frame:hover .fn { color: var(--text-primary); }
    .frame:hover { border-color: var(--text-secondary); }
    .frame.sel { border: 1px solid var(--accent); background: var(--accent-soft); }
    .frame:global(.dragging) { cursor: grabbing; border-style: solid; border-color: var(--accent); box-shadow: 0 14px 34px rgba(0, 0, 0, .35); opacity: .72; }
    .tab { position: absolute; top: -10px; left: 14px; height: 20px; padding: 0 9px; display: inline-flex; align-items: center; border-radius: 10px; background: var(--bg); border: 1px solid var(--border-strong); font-size: 11px; font-weight: 500; color: var(--text-secondary); }
    .frame:hover .tab { color: var(--text-primary); border-color: var(--text-secondary); }
    /* a section's controls sit on its frame's top edge, opposite its name */
    .ctl { margin-left: auto; display: flex; align-items: center; gap: 4px; }
    .cb { width: 26px; height: 24px; display: flex; align-items: center; justify-content: center; border-radius: 7px; background: var(--bg); border: 1px solid var(--border-strong); color: var(--text-secondary); cursor: pointer; }
    .cb:hover:not(:disabled) { color: var(--text-primary); border-color: var(--text-secondary); }
    .cb:disabled { opacity: .35; cursor: default; }
    .seg { display: inline-flex; align-items: center; height: 24px; border-radius: 7px; background: var(--bg); border: 1px solid var(--border-strong); overflow: hidden; margin-right: 4px; }
    .seg .k { font-size: 11px; color: var(--text-secondary); padding: 0 8px; }
    .seg button { height: 100%; padding: 0 8px; font-size: 11px; color: var(--text-secondary); cursor: pointer; border-left: 1px solid var(--border); }
    .seg button.on { background: var(--highlight-15); color: var(--text-primary); }
    .hctl { margin-left: auto; display: flex; gap: 3px; opacity: 0; transition: opacity .12s; }
    .hctl .cb { width: 24px; height: 22px; background: var(--surface); }
    .hc:hover .hctl { opacity: 1; }
    .hc { cursor: grab; }
    .hc:global(.dragging) { border-color: var(--accent); box-shadow: 0 10px 26px rgba(0, 0, 0, .35); }
    /* what's hidden, one click to bring back */
    .tray { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 14px; padding: 10px 12px; border: 1px dashed var(--border-strong); border-radius: 10px; }
    .tray-k { font-size: 12px; color: var(--text-secondary); margin-right: 4px; }
    .ghosts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    /* a half-width frame draws its card the way the narrow card renders on the page */
    .frame.half .two { grid-template-columns: minmax(0, 1fr); gap: 12px; }
    .frame.half .two .col + .col { padding-top: 12px; border-top: 1px solid var(--border); }
    .frame.half .tsb { flex-wrap: wrap; row-gap: 8px; }
    .frame.half .tsb .r { flex-basis: 100%; margin-left: 0; }
    .pih { gap: 0; padding-bottom: 0; }
    .pcells { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 12px -16px 0; border-top: 1px solid var(--border); }
    .pcells .cell { gap: 8px; padding: 12px 16px; }
    .frame.half .pcells { grid-template-columns: 1fr 1fr; }
    .frame.half .pcells .cell:nth-child(3) { border-left: none; }
    .frame.half .pcells .cell:nth-child(n + 3) { border-top: 1px solid var(--border); }
    .frame.half .lat-b { grid-template-columns: minmax(0, 1fr); }
    .frame.half .hero { flex-direction: row; flex-wrap: wrap; justify-content: flex-start; align-items: center; gap: 6px 10px; }
    .frame.half .hero > .tx { flex-basis: 100%; }
    .frame.half .hero .num { width: 22%; }
    .frame.half .tr.th { display: none; }
    .frame.half .tbl .tr { grid-template-columns: 1fr 1fr; row-gap: 8px; }
    .frame.half .hero { border-right: none; border-bottom: 1px solid var(--border); }
    /* host and machine cards drawn like ResourceCard: header, meters, footer */
    .wf.card.hc { padding: 0; gap: 0; }
    .hc .hh { padding: 12px 14px; margin: 0; border-bottom: 1px solid var(--border); }
    .pillst { width: 52px; height: 18px; border-radius: 9px; background: var(--highlight-10); flex-shrink: 0; margin-left: auto; }
    .hc .mtr { display: flex; flex-direction: column; gap: 9px; padding: 12px 14px; }
    .hc .mr { display: grid; grid-template-columns: 52px minmax(0, 1fr) 64px; gap: 10px; align-items: center; }
    .hc .mr .val { width: 100%; }
    .hc .ft { display: flex; align-items: center; gap: 6px; padding: 9px 14px; border-top: 1px solid var(--border); margin-top: auto; }
    .chip2 { width: 64px; height: 20px; border-radius: 10px; border: 1px solid var(--border-strong); }
    .ft .ip { width: 80px; margin-left: auto; }
    .hc .hctl { margin-left: 6px; }
    /* the page's rule: as many across as fit, at most four, never more than there are */
    .lhd { display: flex; align-items: flex-start; gap: 10px; }
    .lhd .hl { gap: 6px; }
    .lat { gap: 0; padding-bottom: 0; }
    .lat .lat-b { margin: 12px -16px 0; }
    .lslow { display: flex; align-items: center; gap: 8px; margin: 0 -16px; padding: 10px 16px; border-top: 1px solid var(--border); }
    .chip2.w { width: 120px; height: 22px; border-radius: 11px; }
    .scs { display: grid; grid-template-columns: repeat(auto-fit, minmax(max(200px, calc((100% - 36px) / min(var(--n), 4))), 1fr)); gap: 12px; }
    .ico.acc { width: 36px; height: 36px; border-radius: 9px; background: var(--accent-soft); }
    .sc .hl { flex: 1; min-width: 0; }
    .arr { margin-left: auto; color: var(--text-secondary); font-size: 13px; }
    .sc .hctl { margin-left: 8px; }
    .sc .hctl { opacity: 0; }
    .sc:hover .hctl { opacity: 1; }
    .gk { font-size: 12px; color: var(--text-secondary); align-self: center; margin-right: 2px; }
    .ulist { gap: 0; }
    .ulist > .lhd { margin-bottom: 10px; }
    .urow { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) 56px; gap: 16px; align-items: center; padding: 10px 0; border-top: 1px solid var(--border); }
    /* one thin line, as the page's strip: no data yet, then the recent stretch up */
    .ustrip { display: block; height: 6px; border-radius: 3px; background: linear-gradient(90deg, var(--highlight-10) 75%, var(--green) 75%); opacity: .8; }
    .ufig { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; }
    .ufig .ln { width: 70%; }
    .pih .cell { gap: 8px; }
    .ghost-chip { display: inline-flex; align-items: center; gap: 4px; height: 26px; padding: 0 10px 0 7px; border-radius: 13px; border: 1px dashed var(--border-strong); font-size: 12px; color: var(--text-secondary); cursor: pointer; }
    .ghost-chip:hover { color: var(--text-primary); border-style: solid; border-color: var(--accent); }
    .frame.sel .tab { background: var(--accent); border-color: var(--accent); color: var(--bg); }

    /* wireframe parts: cards on the surface, grey lines for text, solid blocks for figures,
       theme-coloured bars where the page has bars */
    .wf.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
    .ln { display: block; height: 6px; border-radius: 3px; background: var(--highlight-10); }
    .ln.strong { background: var(--highlight-30); height: 8px; }
    .w10 { width: 10%; } .w15 { width: 15%; } .w20 { width: 20%; } .w30 { width: 30%; } .w40 { width: 40%; } .w50 { width: 50%; } .w60 { width: 60%; } .w70 { width: 70%; } .w80 { width: 80%; }
    .num { display: block; width: 34%; height: 14px; border-radius: 4px; background: var(--highlight-30); }
    .num.sm { width: 24%; height: 10px; }
    .bar { display: block; flex: none; width: 100%; height: 5px; border-radius: 3px; background: linear-gradient(90deg, var(--c) var(--w), var(--highlight-15) var(--w)); }
    .mr .bar { flex: 1; width: auto; }
    .days { display: block; height: 5px; background: repeating-linear-gradient(90deg, var(--accent) 0 calc(100% / 14 - 2px), transparent 0 calc(100% / 14)); border-radius: 2px; opacity: .8; }
    .wf.card.row { flex-direction: row; align-items: center; gap: 10px; }
    /* web app chips as on the page: globe, name, and the dashed add circle */
    .wa { margin-right: 8px; }
    .pill { display: inline-flex; align-items: center; gap: 7px; height: 30px; padding: 0 13px 0 9px; border-radius: 15px; border: 1px solid var(--border-strong); min-width: 0; flex: 0 1 auto; }
    .pill .tx { color: var(--text-primary); font-size: 12px; }
    .gl { width: 13px; height: 13px; border-radius: 50%; border: 1.5px solid var(--text-secondary); flex-shrink: 0; }
    .pill.add { width: 30px; padding: 0; justify-content: center; border-style: dashed; color: var(--text-secondary); flex: none; }
    .wf.card.split { flex-direction: row; padding: 0; gap: 0; }
    .cell { flex: 1; display: flex; flex-direction: column; gap: 8px; padding: 14px 16px; min-width: 0; }
    .cell + .cell { border-left: 1px solid var(--border); }
    .tiles { display: grid; gap: 12px; }
    /* same rule as the page's card grid, so the preview has as many cards per row */
    .hosts { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 12px; }
    .hh { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
    .ico { width: 28px; height: 28px; border-radius: 7px; background: var(--highlight-10); flex-shrink: 0; }
    .ico.sm { width: 18px; height: 18px; border-radius: 5px; }
    .hl { flex: 1; display: flex; flex-direction: column; gap: 5px; min-width: 0; }
    .mr { display: flex; align-items: center; gap: 12px; }
    .mr .ln { flex-shrink: 0; }
    .ts { gap: 12px; }
    .tsb { display: flex; gap: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
    .tsb .r { margin-left: auto; }
    .two { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .col { display: flex; flex-direction: column; gap: 9px; }
    .dev { display: flex; align-items: center; gap: 8px; }
    .duo { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .wf.card.sc { flex-direction: row; align-items: center; gap: 12px; }
    .wf.card.tbl { gap: 0; }
    .tbl > .ln { margin-bottom: 12px; }
    .tr { display: grid; grid-template-columns: 1.2fr 1fr 1.6fr 1fr; gap: 16px; padding: 10px 0; border-top: 1px solid var(--border); }
    .tr.th .ln { height: 4px; width: 50%; }
    .lat { gap: 12px; }
    .lat-b { display: grid; grid-template-columns: 180px minmax(0, 1fr); border-top: 1px solid var(--border); margin: 0 -16px -14px; }
    .hero { display: flex; flex-direction: column; justify-content: center; gap: 8px; padding: 16px; border-right: 1px solid var(--border); }
    .plot { position: relative; height: 90px; margin: 0 16px; }
    .slow { position: absolute; top: 10px; bottom: 10px; left: 75%; right: 0; border-radius: 6px; background: var(--highlight-3); }
    .hist { position: absolute; left: 0; right: 0; bottom: 18px; height: 64px; display: flex; align-items: flex-end; gap: 3px; }
    .hist i { flex: 1; border-radius: 2px 2px 0 0; background: var(--highlight-15); }
    .typ { position: absolute; left: 47%; top: 8px; bottom: 18px; width: 2px; border-radius: 1px; background: var(--accent); opacity: .8; }
    /* labels: names only (sections, tiles, hosts, columns), never figures */
    .tx { display: block; font-size: 11.5px; line-height: 1.2; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tx.t { font-size: 12.5px; font-weight: 600; color: var(--text-primary); }
    .tx.t.sm { font-size: 11.5px; display: flex; align-items: center; gap: 6px; }
    .tx.sub { font-size: 10.5px; }
    .tx.k { font-size: 10.5px; }
    .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--highlight-30); }
    .dot.up { background: var(--green); }
    .mr .tx.k { width: 52px; flex-shrink: 0; }
    .tr.th { align-items: center; }
    .slow .tx { position: absolute; top: 6px; right: 8px; }
    .axis { position: absolute; left: 0; right: 0; bottom: 0; display: flex; justify-content: space-between; }
    /* a tile's or host card's own hide button, on hover */
    .cell, .tile, .hc { position: relative; }
    .hx { position: absolute; top: 8px; right: 8px; width: 24px; height: 22px; border-radius: 6px; display: flex; align-items: center; justify-content: center; background: var(--surface); border: 1px solid var(--border-strong); color: var(--text-secondary); cursor: pointer; opacity: 0; transition: opacity .12s; z-index: 1; }
    .hx.in { position: static; margin-left: auto; }
    .cell:hover .hx, .tile:hover .hx, .hc:hover .hx { opacity: 1; }
    .hx:hover { color: var(--text-primary); border-color: var(--text-secondary); }
    .none { height: 44px; display: flex; align-items: center; justify-content: center; font-size: 12px; color: var(--text-secondary); }
    .none.big { height: 120px; border: 1px dashed var(--border-strong); border-radius: 12px; }

    /* narrower: the outline above, the wireframe below */
    @media (max-width: 900px) {
    }
    @media (max-width: 640px) {
        .hosts, .two { grid-template-columns: minmax(0, 1fr); }
        .urow { grid-template-columns: minmax(0, 1fr) 50px; } .ustrip { grid-column: 1 / -1; grid-row: 2; } .pih { flex-wrap: wrap; } .pih .cell { flex: 1 1 45%; }
        .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
        .tiles .tile { grid-column: auto !important; }
        .lat-b { grid-template-columns: minmax(0, 1fr); }
        .hero { border-right: none; border-bottom: 1px solid var(--border); }
        .hx, .hctl { opacity: 1; }
        .cell .tx, .tile .tx { padding-right: 28px; }
        .wf.card.row { overflow: hidden; }
        .seg .k { display: none; }
    }
</style>
