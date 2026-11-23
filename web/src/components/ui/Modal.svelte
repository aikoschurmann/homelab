<script>
    import { X } from 'lucide-svelte';
    import { fade, scale } from 'svelte/transition';
    // Dialog with a title, a body slot and a "footer" slot
    export let open = false;
    export let title = '';
    export let description = '';
    export let width = 480;
    export let onClose = () => { open = false; };
</script>

<svelte:window on:keydown={e => open && e.key === 'Escape' && onClose()} />

{#if open}
    <div class="backdrop" transition:fade={{ duration: 120 }} on:click|self={onClose} role="presentation">
        <div class="dialog" style="width: {width}px" role="dialog" aria-modal="true" aria-label={title} transition:scale={{ duration: 140, start: 0.97 }}>
            <div class="head">
                <div>
                    <h2>{title}</h2>
                    {#if description}<p>{description}</p>{/if}
                </div>
                <button class="x" on:click={onClose} aria-label="Close"><X size={16} /></button>
            </div>
            <div class="body"><slot /></div>
            {#if $$slots.footer}<div class="foot"><slot name="footer" /></div>{/if}
        </div>
    </div>
{/if}

<style>
    .backdrop { position: fixed; inset: 0; z-index: 300; background: rgba(15, 17, 20, 0.45); display: flex; align-items: flex-start; justify-content: center; padding: 12vh 16px 16px; box-sizing: border-box; }
    .dialog { max-width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; box-shadow: 0 24px 60px rgba(0, 0, 0, 0.22); display: flex; flex-direction: column; max-height: 76vh; }
    .head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 18px 20px 14px; }
    h2 { margin: 0; font-size: 16px; font-weight: 600; color: var(--text-primary); }
    p { margin: 4px 0 0; font-size: 13px; color: var(--text-secondary); line-height: 1.5; }
    .x { display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 6px; color: var(--text-secondary); cursor: pointer; flex-shrink: 0; }
    .x:hover { background: var(--highlight-10); color: var(--text-primary); }
    .body { padding: 4px 20px 18px; overflow-y: auto; }
    .foot { display: flex; align-items: center; justify-content: flex-end; gap: 8px; padding: 12px 20px; border-top: 1px solid var(--border); background: var(--highlight-3); border-radius: 0 0 10px 10px; }
</style>
