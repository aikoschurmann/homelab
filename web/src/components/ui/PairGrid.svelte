<script>
    // Label/value pairs in two halves where each line holds one pair from each side,
    // so both sides share the line's height and the rules line up.
    // rows: [[left, right], ...]; a cell is { k, v, copy?, mono?, bad?, title?, action?: { label, onClick } } or null
    // heads: optional [leftTitle, rightTitle] above each half
    import CopyText from './CopyText.svelte';
    export let rows = [];
    export let heads = [];
</script>

<div class="pg wide">
    {#if heads.length}
        <div class="pg-r pg-h">{#each heads as h}<div class="half">{h}</div>{/each}</div>
    {/if}
    {#each rows as pair}
        <!-- a line with only one pair spans the full width instead of leaving half of it blank -->
        {@const lone = pair.filter(Boolean).length === 1}
        <div class="pg-r" class:lone>
            {#each lone ? pair.filter(Boolean) : pair as c}
                <div class="half" class:empty={!c}>
                    {#if c}
                        <span class="pg-k">{c.k}</span>
                        <span class="pg-v" class:ui-mono={c.mono} class:bad={c.bad} title={c.title || null}>
                            {#if c.action}<button class="ui-link" on:click={c.action.onClick}>{c.action.label}</button>
                            {:else if c.copy && c.v && c.v !== '—'}<CopyText text={c.v} />
                            {:else}{c.v ?? '—'}{/if}
                        </span>
                    {/if}
                </div>
            {/each}
        </div>
    {/each}
</div>

<!-- phone: each half as its own list, under its heading -->
<div class="pg narrow">
    {#each [0, 1] as side}
        {#if heads[side]}<div class="n-h">{heads[side]}</div>{/if}
        {#each rows.map(p => p[side]).filter(Boolean) as c}
            <div class="half">
                <span class="pg-k">{c.k}</span>
                <span class="pg-v" class:ui-mono={c.mono} class:bad={c.bad} title={c.title || null}>
                    {#if c.action}<button class="ui-link" on:click={c.action.onClick}>{c.action.label}</button>
                    {:else if c.copy && c.v && c.v !== '—'}<CopyText text={c.v} />
                    {:else}{c.v ?? '—'}{/if}
                </span>
            </div>
        {/each}
    {/each}
</div>

<style>
    .pg { border-top: 1px solid var(--border); }
    .pg-r { display: grid; grid-template-columns: 1fr 1fr; border-bottom: 1px solid var(--border); }
    .pg-r:last-child { border-bottom: none; }
    .pg-r.lone { grid-template-columns: 1fr; }
    .half { display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: 0 16px; align-items: center; min-height: 52px; padding: 8px 24px; box-sizing: border-box; font-size: 13.5px; }
    .half + .half { border-left: 1px solid var(--border); }
    .pg-h .half { display: block; min-height: 0; padding: 12px 24px 10px; font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-secondary); padding-top: 14px; }
    .pg-h { border-bottom-color: var(--border); }
    .pg-k { color: var(--text-secondary); }
    .pg-v { color: var(--text-primary); min-width: 0; overflow-wrap: anywhere; line-height: 1.45; }
    .pg-v.ui-mono { font-size: 12.5px; }
    .pg-v.bad { color: var(--red); font-weight: 500; }
    @media (max-width: 1100px) { .half { grid-template-columns: 120px minmax(0, 1fr); padding: 8px 20px; } }
    .narrow { display: none; }
    .n-h { padding: 12px 14px 8px; font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-secondary); border-bottom: 1px solid var(--border); }
    .narrow .half + .n-h { border-top: 1px solid var(--border); }
    @media (max-width: 760px) {
        .wide { display: none; }
        .narrow { display: block; }
        .narrow .half { grid-template-columns: 110px minmax(0, 1fr); padding: 10px 14px; min-height: 44px; border-bottom: 1px solid var(--border); }
        .narrow .half:last-child { border-bottom: none; }
        .narrow .half + .half { border-left: none; }
    }
</style>
