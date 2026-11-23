<script>
    import { Minus, Plus } from 'lucide-svelte';
    export let value = 0;
    export let min = 0;
    export let max = 100;
    export let step = 1;
    export let unit = '';
    export let disabled = false;

    const clamp = (v) => Math.min(max, Math.max(min, Math.round(v / step) * step));
    const dec = () => value = clamp(value - step);
    const inc = () => value = clamp(value + step);
    const onInput = (e) => { const v = parseFloat(e.target.value); if (!isNaN(v)) value = clamp(v); };
    $: shown = Number.isInteger(step) ? value : String(+(+value).toFixed(2));
</script>

<div class="stepper" class:disabled>
    <button type="button" on:click={dec} disabled={disabled || value <= min} aria-label="Decrease"><Minus size={13} /></button>
    <input type="text" inputmode="decimal" value={shown} on:change={onInput} {disabled} aria-label="Value" />
    {#if unit}<span class="unit">{unit}</span>{/if}
    <button type="button" on:click={inc} disabled={disabled || value >= max} aria-label="Increase"><Plus size={13} /></button>
</div>

<style>
    .stepper { display: inline-flex; align-items: center; align-self: flex-start; height: 32px; border: 1px solid var(--border); border-radius: var(--radius-card, 8px); background: var(--bg); overflow: hidden; }
    .stepper.disabled { opacity: 0.5; }
    button { width: 30px; height: 100%; display: flex; align-items: center; justify-content: center; color: var(--text-secondary); cursor: pointer; }
    button:hover:not(:disabled) { background: var(--highlight-10); color: var(--text-primary); }
    button:disabled { opacity: 0.35; cursor: default; }
    input { width: 44px; height: 100%; border: none; border-left: 1px solid var(--border); background: transparent; text-align: right; font-family: 'JetBrains Mono', monospace; font-size: 13.5px; color: var(--text-primary); padding: 0 4px; }
    input:focus { outline: none; }
    .unit { min-width: 46px; box-sizing: border-box; font-size: 12px; color: var(--text-secondary); padding: 0 8px 0 2px; border-right: 1px solid var(--border); height: 100%; display: flex; align-items: center; }
    .stepper:not(:has(.unit)) input { border-right: 1px solid var(--border); padding-right: 8px; }
</style>
