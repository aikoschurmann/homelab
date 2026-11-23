<script>
    import { copyText } from '../../lib/clipboard.js';
    import { Copy, Check } from 'lucide-svelte';
    // Monospace value with a copy button
    export let text = '';
    let done = false;
    async function copy() {
        try { await copyText(text); done = true; setTimeout(() => done = false, 1200); } catch (e) {}
    }
</script>

<span class="copy"><code>{text}</code><button on:click|stopPropagation={copy} aria-label="Copy" title="Copy">{#if done}<Check size={13} />{:else}<Copy size={13} />{/if}</button></span>

<style>
    .copy { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; }
    code { font-family: 'JetBrains Mono', monospace; font-size: 12.5px; overflow-wrap: anywhere; }
    button { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 4px; color: var(--text-secondary); cursor: pointer; flex-shrink: 0; }
    button:hover { background: var(--highlight-10); color: var(--text-primary); }
</style>
