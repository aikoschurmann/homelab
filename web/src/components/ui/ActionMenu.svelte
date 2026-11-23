<script>
    import { MoreHorizontal } from 'lucide-svelte';
    // ⋯ button with a dropdown; items: [{ label, icon?, onClick, danger?, disabled?, divider? }]
    export let items = [];
    export let label = 'Actions';
    export let align = 'right';
    let open = false;
    let el, btn;
    // The menu is fixed-positioned so cards and scrolling tables can't clip it
    let pos = '';
    function toggle() {
        open = !open;
        if (!open) return;
        const r = btn.getBoundingClientRect();
        const below = window.innerHeight - r.bottom > 260;
        const v = below ? `top: ${r.bottom + 4}px;` : `bottom: ${window.innerHeight - r.top + 4}px;`;
        const h = align === 'right' ? `right: ${window.innerWidth - r.right}px;` : `left: ${r.left}px;`;
        pos = v + h;
    }
    const onDoc = (e) => { if (open && el && !el.contains(e.target)) open = false; };
    const pick = (it) => { if (it.disabled) return; open = false; it.onClick?.(); };
</script>

<svelte:window on:click={onDoc} on:keydown={e => e.key === 'Escape' && (open = false)} on:resize={() => open = false} on:scroll|capture={() => open = false} />

<div class="wrap" bind:this={el} on:click|stopPropagation role="presentation">
    <button bind:this={btn} class="trigger" class:on={open} aria-label={label} aria-haspopup="menu" aria-expanded={open} on:click={toggle}>
        <slot name="trigger"><MoreHorizontal size={16} /></slot>
    </button>
    {#if open}
        <div class="menu" role="menu" style={pos}>
            {#each items.filter(Boolean) as it}
                {#if it.divider}<div class="div"></div>{/if}
                <button role="menuitem" class:danger={it.danger} disabled={it.disabled} on:click={() => pick(it)}>
                    {#if it.icon}<svelte:component this={it.icon} size={14} />{/if}{it.label}
                </button>
            {/each}
        </div>
    {/if}
</div>

<style>
    .wrap { position: relative; display: inline-flex; }
    .trigger { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-width: 32px; height: 32px; padding: 0 8px; border-radius: 6px; color: var(--text-secondary); cursor: pointer; box-sizing: border-box; }
    .trigger:hover, .trigger.on { background: var(--highlight-10); color: var(--text-primary); }
    .menu { position: fixed; z-index: 200; min-width: 180px; padding: 4px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card, 8px); box-shadow: 0 10px 28px rgba(0, 0, 0, 0.14); }
    .menu button { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border-radius: 5px; font-size: 13.5px; color: var(--text-primary); text-align: left; cursor: pointer; white-space: nowrap; }
    .menu button:hover:not(:disabled) { background: var(--highlight-10); }
    .menu button:disabled { opacity: 0.4; cursor: default; }
    .menu button.danger { color: var(--red); }
    .div { height: 1px; margin: 4px 0; background: var(--border); }
</style>
