<script>
    export let checked = false;
    export let disabled = false;
    export let label = '';
</script>

<label class="sw-row" class:disabled>
    <span class="sw" class:on={checked}><input type="checkbox" bind:checked {disabled} on:change aria-label={label || null} /><i></i></span>
    <slot />
</label>

<style>
    .sw-row { display: inline-flex; align-items: center; gap: 10px; font-size: 13.5px; color: var(--text-primary); cursor: pointer; }
    .sw-row.disabled { cursor: default; color: var(--text-secondary); opacity: .6; }
    .sw { position: relative; width: 36px; height: 20px; flex-shrink: 0; }
    .sw input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: inherit; }
    .sw i { position: absolute; inset: 0; border-radius: 10px; background: var(--highlight-30); transition: background .15s; pointer-events: none; }
    .sw i::after { content: ''; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.25); transition: transform .15s; }
    .sw.on i { background: var(--accent-fill); }
    .sw.on i::after { transform: translateX(16px); }
</style>
