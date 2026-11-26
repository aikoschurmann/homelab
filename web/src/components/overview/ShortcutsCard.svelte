<script>
    import { onMount } from 'svelte';
    import { ArrowRight } from 'lucide-svelte';
    import { joinKey } from '../../lib/widgets.js';

    // The shortcuts picked under Customize: each page with one figure of what it holds.
    // Two tiles side by side on one line can be merged into one card, as the cluster's tiles can.
    export let items = [];      // [{ key, to, icon, k, v, s }]
    export let joins = [];      // neighbours that share one card ('a|b')
    export let onJoin = null;   // Customize: (a, b) merge or split two neighbours

    // which tiles sit right after the one before them on the same line (the grid wraps with the width)
    let el, beside = {};
    function measure() {
        if (!el) return;
        const els = [...el.querySelectorAll(':scope > [data-sc]')], b = {};
        els.forEach((e, i) => { if (i && Math.abs(els[i - 1].offsetTop - e.offsetTop) < 2) b[e.dataset.sc] = true; });
        if (Object.keys(b).join() !== Object.keys(beside).join()) beside = b;
    }
    onMount(() => { const ro = new ResizeObserver(measure); ro.observe(el); measure(); return () => ro.disconnect(); });
    $: items, queueMicrotask(measure);
    $: keys = items.map(c => c.key);
    $: jl = (i) => i > 0 && beside[keys[i]] && joins.includes(joinKey(keys[i - 1], keys[i]));
    $: jr = (i) => i < keys.length - 1 && jl(i + 1);
</script>

<div class="shortcuts" id="sec-databases" bind:this={el} style="--n: {Math.max(1, items.length)}">
    {#each items as c, i (c.key)}
        <a class="sc" class:tj-l={jl(i)} class:tj-r={jr(i)} href={c.to} data-sc={c.key}>
            {#if onJoin && i > 0 && beside[c.key]}
                <button type="button" class="tjb" data-nodrag title={jl(i) ? 'Split into two cards' : 'Merge into one card'} aria-label={jl(i) ? 'Split into two cards' : 'Merge into one card'} on:click|stopPropagation|preventDefault={() => onJoin(keys[i - 1], c.key)}></button>
            {/if}
            <span class="sc-ic"><svelte:component this={c.icon} size={16} /></span>
            <span class="sc-main"><span class="sc-k">{c.k}</span><span class="sc-v">{c.v} <small>{c.s}</small></span></span>
            <ArrowRight size={14} class="sc-go" />
        </a>
    {:else}<div class="ui-card ui-empty">No shortcuts picked. Add some under Customize.</div>{/each}
</div>

<style>
    /* as many across as fit (at least 220px each), never more than there are */
    /* beside something taller the tiles share its height rather than leave a gap under them */
    .shortcuts { --g: 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(max(220px, calc((100% - 36px) / min(var(--n), 4))), 1fr)); grid-auto-rows: 1fr; gap: var(--g); align-content: stretch; }
    .sc { position: relative; display: flex; align-items: center; gap: 12px; padding: 14px 16px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card, 8px); text-decoration: none; color: var(--text-primary); transition: border-color .12s, box-shadow .12s, background .12s; min-width: 0; }
    .sc:hover:not(:has(> .tjb:hover)) { border-color: var(--border-strong); box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05); }
    /* merged: no outline, the tile darkens instead (as the merged update/app/backup tiles do) */
    .sc.tj-l:hover:not(:has(> .tjb:hover)), .sc.tj-r:hover:not(:has(> .tjb:hover)) { border-color: var(--border); box-shadow: none; background: var(--highlight-3); }
    /* (Customize: the tiles themselves don't react, the merge handle between them does) */
    .sc > .tjb { pointer-events: auto; }
    .sc-ic { width: 36px; height: 36px; border-radius: 9px; background: var(--accent-soft); color: var(--accent); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .sc-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
    .sc-k { font-size: 12.5px; color: var(--text-secondary); }
    .sc-v { font-size: 17px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    /* the detail sits under the figure (it trailed off on one line in narrow tiles) */
    .sc-v small { display: block; margin-top: 1px; font-size: 12.5px; font-weight: 400; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .sc :global(.sc-go) { color: var(--text-secondary); flex-shrink: 0; transition: transform .12s; }
    .sc:hover:not(:has(> .tjb:hover)) :global(.sc-go) { color: var(--accent); transform: translateX(2px); }
    @media (max-width: 760px) {
        .shortcuts { grid-template-columns: 1fr; }
    }
</style>
