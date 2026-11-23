<script>
    import { onMount, tick } from 'svelte';
    // Underlined tab bar; `tabs` is [{ id, label }]. The underline slides to the active tab.
    export let tabs = [];
    export let active;
    export let onSelect = () => {};

    let bar;
    let ink = '';
    let ready = false;
    async function place() {
        await tick();
        const el = bar?.querySelector('[aria-selected="true"]');
        if (!el) { ink = 'opacity: 0'; return; }
        ink = `transform: translateX(${el.offsetLeft + 8}px); width: ${el.offsetWidth - 16}px`;
        // on narrow screens the bar scrolls; keep the open tab visible
        if (el.offsetLeft < bar.scrollLeft || el.offsetLeft + el.offsetWidth > bar.scrollLeft + bar.clientWidth)
            bar.scrollTo({ left: el.offsetLeft - 24, behavior: ready ? 'smooth' : 'auto' });
        edges();
    }
    // fade whichever side has more tabs out of view
    let fadeL = false, fadeR = false;
    function edges() {
        if (!bar) return;
        fadeL = bar.scrollLeft > 2;
        fadeR = bar.scrollLeft + bar.clientWidth < bar.scrollWidth - 2;
    }
    $: active, tabs, place();
    onMount(() => {
        // web fonts change tab widths after first paint; the bar follows without animating in
        const ro = new ResizeObserver(place);
        ro.observe(bar);
        requestAnimationFrame(() => ready = true);
        return () => ro.disconnect();
    });
</script>

<div class="tabs" class:fade-l={fadeL} class:fade-r={fadeR} role="tablist" bind:this={bar} on:scroll={edges}>
    {#each tabs as t}
        <button role="tab" aria-selected={active === t.id} class:on={active === t.id} on:click={() => onSelect(t.id)}>{t.label}</button>
    {/each}
    <span class="ink" class:ready style={ink}></span>
</div>

<style>
    .tabs { position: relative; display: flex; gap: 4px; border-bottom: 1px solid var(--border); overflow-x: auto; scrollbar-width: none; }
    button { position: relative; padding: 10px 12px; font-size: 14px; font-weight: 500; color: var(--text-secondary); cursor: pointer; white-space: nowrap; border-radius: 6px 6px 0 0; }
    button:hover { color: var(--text-primary); background: var(--highlight-5); }
    button.on { color: var(--accent); }
    .ink { position: absolute; left: 0; bottom: 0; height: 2px; border-radius: 2px 2px 0 0; background: var(--accent); pointer-events: none; }
    .tabs.fade-r { -webkit-mask-image: linear-gradient(to right, #000 calc(100% - 36px), transparent); mask-image: linear-gradient(to right, #000 calc(100% - 36px), transparent); }
    .tabs.fade-l { -webkit-mask-image: linear-gradient(to left, #000 calc(100% - 36px), transparent); mask-image: linear-gradient(to left, #000 calc(100% - 36px), transparent); }
    .tabs.fade-l.fade-r { -webkit-mask-image: linear-gradient(to right, transparent, #000 36px, #000 calc(100% - 36px), transparent); mask-image: linear-gradient(to right, transparent, #000 36px, #000 calc(100% - 36px), transparent); }
    @media (max-width: 640px) { button { padding: 10px 9px; font-size: 13.5px; } .tabs { gap: 0; } }
    .ink.ready { transition: transform 260ms cubic-bezier(0.22, 1, 0.36, 1), width 260ms cubic-bezier(0.22, 1, 0.36, 1); }
</style>
