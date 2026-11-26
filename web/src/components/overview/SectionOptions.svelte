<script>
    import { GripVertical } from 'lucide-svelte';
    import { sortable } from '../../lib/sortable.js';
    import Switch from '../ui/Switch.svelte';
    import { layout, SECTION_TILES, SHORTCUTS, COLS, toggleTile, setTileOrder, setTotalsCols, setShortcuts } from '../../lib/widgets.js';

    // What a section shows, and in which order: its tiles, how many per row, its shortcuts.
    // The same in the section's settings and in the Add gallery; changes apply right away.
    export let kind = null;

    $: hiddenTiles = new Set($layout.hidden_tiles);
    $: tileLabel = Object.fromEntries((SECTION_TILES[kind] || []).map(t => [t.id, t.label]));
    $: tiles = $layout.tile_order[kind] || [];
    $: picked = $layout.shortcuts;
    $: scRest = SHORTCUTS.filter(x => !picked.includes(x.id));
    const scLabel = Object.fromEntries(SHORTCUTS.map(x => [x.id, x.label]));
</script>

{#if SECTION_TILES[kind]}
    <div class="ui-field">
        <span class="ui-label">Tiles</span>
        <div class="list" use:sortable={{ onMove: (ids) => setTileOrder(kind, ids) }}>
            {#each tiles as t, i (t)}
                <div class="li" class:off={hiddenTiles.has(t)} data-id={t} data-n={i}>
                    <span class="gr" data-handle title="Drag to reorder"><GripVertical size={14} /></span>
                    <span class="nm" data-handle>{tileLabel[t]}</span>
                    <Switch checked={!hiddenTiles.has(t)} on:change={() => toggleTile(t)} label="Show {tileLabel[t]}" />
                </div>
            {/each}
        </div>
    </div>
{/if}
{#if kind === 'totals'}
    <div class="ui-field">
        <span class="ui-label">Tiles per row</span>
        <div class="ui-seg">{#each COLS as c}<button type="button" class:on={String($layout.totals_cols) === String(c)} on:click={() => setTotalsCols(c)}>{c}</button>{/each}</div>
    </div>
{/if}
{#if kind === 'shortcuts'}
    <div class="ui-field">
        <span class="ui-label">Pages</span>
        <div class="list">
            <div class="sub" use:sortable={{ onMove: (ids) => setShortcuts(ids) }}>
            {#each picked as k, i (k)}
                <div class="li" data-id={k} data-n={i}>
                    <span class="gr" data-handle title="Drag to reorder"><GripVertical size={14} /></span>
                    <span class="nm" data-handle>{scLabel[k]}</span>
                    <Switch checked on:change={() => setShortcuts(picked.filter(x => x !== k))} label="Show {scLabel[k]}" />
                </div>
            {/each}
            </div>
            {#each scRest as x (x.id)}
                <div class="li off"><span class="gr"></span><span class="nm">{x.label}</span><Switch checked={false} on:change={() => setShortcuts([...picked, x.id])} label="Show {x.label}" /></div>
            {/each}
        </div>
    </div>
{/if}

<style>
    .list { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: var(--surface); }
    .li { display: flex; align-items: center; gap: 10px; min-height: 42px; padding: 0 12px; font-size: 13.5px; color: var(--text-primary); }
    .li + .li { border-top: 1px solid var(--border); }
    .li .nm { flex: 1; min-width: 0; align-self: stretch; display: flex; align-items: center; cursor: grab; }
    .li.off .nm { color: var(--text-secondary); }
    .sub { display: flex; flex-direction: column; }
    .sub + .li, .sub .li + .li { border-top: 1px solid var(--border); }
    .sub:empty { display: none; }
    /* the grip: press anywhere on it and drag the row */
    .gr { width: 18px; margin-left: -4px; display: flex; align-items: center; justify-content: center; color: var(--text-secondary); opacity: .6; cursor: grab; touch-action: none; }
    .li:hover .gr { opacity: 1; }
</style>
