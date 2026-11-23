<script>
    // running | stopped | starting | creating | error | anything else (neutral)
    export let state = '';
    export let label = null;
    const TONE = { running: 'ok', connected: 'ok', stopped: 'off', starting: 'busy', stopping: 'busy', creating: 'busy', joining: 'busy', error: 'bad', failed: 'bad', offline: 'bad', waiting: 'busy' };
    $: tone = TONE[state] || 'off';
    $: text = label ?? (state ? state[0].toUpperCase() + state.slice(1) : '—');
</script>

<span class="pill {tone}"><i></i>{text}</span>

<style>
    .pill { display: inline-flex; align-items: center; gap: 6px; height: 22px; padding: 0 8px; border-radius: 11px; font-size: 12px; font-weight: 500; white-space: nowrap; background: var(--highlight-10); color: var(--text-secondary); }
    i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
    .ok { background: rgba(63, 125, 92, 0.12); color: var(--green); }
    .bad { background: rgba(184, 76, 62, 0.12); color: var(--red); }
    .busy { background: rgba(201, 147, 46, 0.14); color: var(--amber); }
    .busy i { animation: pulse 1.2s ease-in-out infinite; }
    @keyframes pulse { 50% { opacity: 0.3; } }
</style>
