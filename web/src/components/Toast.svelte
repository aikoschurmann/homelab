<script>
    export let message = '';
    // keep the last text while the toast slides away, so it doesn't empty mid-fade
    let text = '';
    $: if (message) text = message;
</script>

<div class="toast" class:show={!!message} role="status" aria-live="polite">{text}</div>

<style>
    .toast { position: fixed; left: 50%; bottom: 24px; z-index: 500; max-width: min(480px, calc(100vw - 32px)); padding: 10px 16px; border-radius: var(--radius-card, 8px); background: var(--text-primary); color: var(--surface); font-size: 13.5px; font-weight: 500; line-height: 1.4; box-shadow: 0 8px 28px rgba(0, 0, 0, 0.22); box-sizing: border-box; pointer-events: none; opacity: 0; transform: translate(-50%, 12px) scale(0.98); transition: opacity 180ms ease, transform 260ms cubic-bezier(0.22, 1, 0.36, 1); }
    .toast.show { opacity: 1; transform: translate(-50%, 0); }
</style>
