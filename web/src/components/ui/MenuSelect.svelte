<script>
    // A toolbar picker for one choice: a ui-btn that opens the same menu as Network tools' "From".
    // options: [{ value, label, hint? }]; onChange(value)
    import { onMount } from 'svelte';
    import { ChevronDown, Check } from 'lucide-svelte';

    export let options = [];
    export let value = null;
    export let onChange = () => {};
    export let label = '';          // shown before the chosen option's name, e.g. "Group:"
    export let heading = '';        // small grey line at the top of the menu
    export let align = 'right';     // which edge of the button the menu lines up with

    let open = false, el;
    $: current = options.find(o => o.value === value) || options[0];
    function pick(v) { open = false; if (v !== value) onChange(v); }
    onMount(() => {
        const away = (e) => { if (open && el && !el.contains(e.target)) open = false; };
        const esc = (e) => { if (open && e.key === 'Escape') open = false; };
        document.addEventListener('click', away, true);
        document.addEventListener('keydown', esc);
        return () => { document.removeEventListener('click', away, true); document.removeEventListener('keydown', esc); };
    });
</script>

<div class="ms" bind:this={el}>
    <button type="button" class="ui-btn" aria-haspopup="menu" aria-expanded={open} on:click={() => open = !open}>
        {#if label}<span class="ms-lbl">{label}</span>{/if}<span class="ms-cur">{current?.label ?? ''}</span><ChevronDown size={14} />
    </button>
    {#if open}
        <div class="ms-menu" class:left={align === 'left'} role="menu">
            {#if heading}<div class="ms-head">{heading}</div>{/if}
            {#each options as o (o.value)}
                <button type="button" class="ms-item" role="menuitemradio" aria-checked={o.value === value} on:click={() => pick(o.value)}>
                    <span class="ms-tick">{#if o.value === value}<Check size={14} />{/if}</span>
                    <span class="ms-txt">{o.label}</span>
                    {#if o.hint != null}<span class="ms-hint">{o.hint}</span>{/if}
                </button>
            {/each}
        </div>
    {/if}
</div>

<style>
    .ms { position: relative; min-width: 0; }
    .ms .ui-btn { max-width: 100%; }
    .ms-lbl { color: var(--text-secondary); margin-right: -2px; }
    .ms-cur { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ms-menu { position: absolute; right: 0; top: calc(100% + 6px); z-index: 60; min-width: 220px; max-width: min(320px, calc(100vw - 32px)); max-height: min(420px, 60vh); overflow-y: auto; padding: 6px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card, 8px); box-shadow: 0 10px 28px rgba(0, 0, 0, 0.14); box-sizing: border-box; }
    .ms-menu.left { left: 0; right: auto; }
    .ms-head { font-size: 12px; font-weight: 600; color: var(--text-secondary); padding: 6px 8px; }
    .ms-item { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 8px; border-radius: 5px; font-size: 13.5px; color: var(--text-primary); text-align: left; cursor: pointer; }
    .ms-item:hover { background: var(--highlight-10); }
    .ms-tick { width: 14px; display: flex; flex-shrink: 0; color: var(--accent); }
    .ms-txt { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ms-hint { margin-left: auto; padding-left: 12px; font-size: 12px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
</style>
