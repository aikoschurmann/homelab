<script>
    // The card the Machines page uses for a machine, shared so the Overview's Mac and
    // machine cards look the same. Meters: { k, v, of, p, color } or { k, v, of, segs: [{ p, color, opacity }] };
    // without p or segs the value spans the bar's column. Chips: { label, onClick }.
    import { createEventDispatcher } from 'svelte';
    import { Server } from 'lucide-svelte';

    export let name;
    export let sub = '';
    export let tag = null;
    export let on = true;         // tinted icon
    export let off = false;       // dimmed meters (stopped)
    export let plain = false;     // not a link
    export let icon = Server;
    export let meters = [];
    export let chips = [];
    export let note = '';         // dim text in the footer when there are no chips
    export let lan = '';
    export let ts = '';
    export let tsTitle = '';
    export let foot = true;
    export let selected = false;  // picked (e.g. where Network tools run checks)

    const dispatch = createEventDispatcher();
    const open = () => !plain && dispatch('open');
</script>

<div class="mcard" class:off class:plain class:sel={selected} on:click={open} on:keydown={e => e.key === 'Enter' && open()} role={plain ? null : 'link'} tabindex={plain ? null : 0}>
    <div class="mc-head">
        <span class="mc-icon" class:on><svelte:component this={icon} size={18} /></span>
        <div class="mc-title">
            <span class="mc-name" class:plain><span class="mc-name-t">{name}</span>{#if tag}<span class="ui-tag">{tag}</span>{/if}</span>
            {#if sub}<span class="sub">{sub}</span>{/if}
        </div>
        <slot name="status" />
    </div>

    {#if meters.length}
    <div class="mc-meters">
        {#each meters as m}
            <div class="meter">
                <span class="k">{m.k}</span>
                {#if m.segs}
                    <div class="ui-meter segs" title={m.title || null}>{#each m.segs as s}<i style="width: {s.p}%; background: {s.color}; opacity: {s.opacity ?? 1}"></i>{/each}</div>
                {:else if m.p != null}
                    <div class="ui-meter"><i style="width: {m.p}%; background: {m.color}"></i></div>
                {/if}
                <span class="v" class:wide={m.p == null && !m.segs}>{m.v}{#if m.of}<small>{m.of}</small>{/if}</span>
            </div>
        {/each}
    </div>
    {/if}

    {#if foot}
        <div class="mc-foot">
            <span class="chips">
                {#each chips as c}<button class="chip" on:click|stopPropagation={c.onClick}>{c.label}</button>{/each}
                {#if !chips.length && note}<span class="ui-dim">{note}</span>{/if}
            </span>
            <span class="addr">
                {#if lan}<span class="ui-mono lan">{lan}</span>{/if}
                {#if ts}<span class="ts" title={tsTitle || null}><i class="ok"></i><span class="ui-mono">{ts}</span></span>{/if}
            </span>
        </div>
    {/if}
</div>

<style>
    .mcard { container-type: inline-size; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card, 8px); display: flex; flex-direction: column; cursor: pointer; transition: border-color .12s, box-shadow .12s; text-align: left; min-width: 0; }
    .mcard:hover { border-color: var(--border-strong); box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06); }
    .mcard:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .mcard.sel, .mcard.sel:hover { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
    .mcard.plain { cursor: default; }
    .mcard.plain:hover { border-color: var(--border); box-shadow: none; }
    .mc-head { display: flex; align-items: center; gap: 12px; padding: 16px 16px 14px 18px; }
    .mc-icon { width: 38px; height: 38px; border-radius: 9px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); }
    .mc-icon.on { background: var(--accent-soft); color: var(--accent); }
    .mc-title { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
    .mc-name { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: var(--accent); min-width: 0; }
    .mc-name-t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    .mc-name :global(.ui-tag) { flex-shrink: 0; }
    .mc-head > :global(:last-child:not(.mc-title)) { flex-shrink: 0; }
    .mc-name.plain { color: var(--text-primary); }
    .mcard:hover .mc-name:not(.plain) .mc-name-t { text-decoration: underline; }
    .sub { font-size: 12px; color: var(--text-secondary); overflow-wrap: anywhere; }
    .mc-meters { display: flex; flex-direction: column; gap: 10px; padding: 14px 18px; border-top: 1px solid var(--border); }
    .meter { display: grid; grid-template-columns: 64px 1fr 150px; align-items: center; gap: 12px; }
    .meter .k { font-size: 12.5px; color: var(--text-secondary); }
    .meter .v { font-size: 13px; font-weight: 500; color: var(--text-primary); font-variant-numeric: tabular-nums; white-space: nowrap; }
    .meter .v.wide { grid-column: 2 / -1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
    .meter .v small { font-weight: 400; color: var(--text-secondary); margin-left: 5px; font-size: 12px; }
    .ui-meter.segs { display: flex; }
    .ui-meter.segs i { border-radius: 0; }
    .mc-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: nowrap; height: 46px; box-sizing: border-box; padding: 0 18px; overflow: hidden; border-top: 1px solid var(--border); background: var(--highlight-3); border-radius: 0 0 var(--radius-card, 8px) var(--radius-card, 8px); font-size: 12.5px; margin-top: auto; }
    .chips { display: flex; gap: 6px; flex-wrap: nowrap; align-items: center; min-width: 0; white-space: nowrap; }
    .chip { height: 24px; padding: 0 9px; border-radius: 12px; border: 1px solid var(--border); background: var(--surface); font-size: 12px; color: var(--text-primary); cursor: pointer; }
    .chip:hover { border-color: var(--accent); color: var(--accent); }
    .addr { display: flex; gap: 12px; align-items: center; color: var(--text-secondary); white-space: nowrap; flex-shrink: 0; }
    /* one footer height for every card: narrow cards drop addresses rather than wrap */
    @container (max-width: 520px) { .addr .lan { display: none; } }
    @container (max-width: 400px) { .addr { display: none; } }
    .addr .ui-mono { font-size: 12px; }
    .mcard.off .mc-meters { opacity: 0.55; }
    .ts { display: inline-flex; align-items: center; gap: 6px; }
    .ts i.ok { width: 6px; height: 6px; border-radius: 50%; background: var(--green); }
    /* narrow cards: the value column gives up width before the bar disappears */
    @container (max-width: 380px) { .meter { grid-template-columns: 60px 1fr 104px; gap: 10px; } }
    @media (max-width: 640px) {
        .meter { grid-template-columns: 56px 1fr 120px; }
    }
</style>
