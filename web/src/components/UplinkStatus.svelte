<script>
    import { onMount } from 'svelte';
    import { uplink, uplinkState } from '../lib/stores.js';

    // compact (top bar): just the dot while live, the age or state otherwise. Full: dot, label, transport and age.
    export let compact = false;

    let now = Date.now();
    onMount(() => {
        const t = setInterval(() => now = Date.now(), 1000);
        return () => clearInterval(t);
    });

    $: state = uplinkState($uplink, now);
    $: age = $uplink.lastFetchAt ? Math.max(0, Math.round((now - $uplink.lastFetchAt) / 1000)) : null;
    $: ageText = age == null ? '' : age < 60 ? `${age}s` : age < 3600 ? `${Math.floor(age / 60)}m` : `${Math.floor(age / 3600)}h`;
    $: label = { connecting: 'Connecting', live: 'Live', stale: 'Stale', down: 'Reconnecting' }[state];
    $: title = state === 'live' ? `Receiving updates over ${$uplink.method}; last one ${ageText} ago`
        : state === 'stale' ? `No update for ${ageText}; the backend may be busy or asleep`
        : state === 'down' ? 'Lost the connection to the backend; retrying'
        : 'Waiting for the first update from the backend';
</script>

<div class="uplink {state} {compact ? 'compact' : ''}" {title} role="status" aria-live="polite">
    <span class="dot"></span>
    {#if compact}
        <!-- a green dot says enough while live; words only when something is off -->
        {#if state === 'stale'}<span class="age">{ageText}</span>{:else if state !== 'live'}<span class="age">{label}</span>{/if}
    {:else}
        <span class="label">{label}</span>
        {#if state === 'live' || state === 'stale'}
            <span class="meta">{$uplink.method} · {ageText} ago</span>
        {/if}
    {/if}
</div>

<style>
    .uplink { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-secondary); padding: 6px 8px; border-radius: var(--radius-card, 8px); white-space: nowrap; min-width: 0; }
    .label { font-weight: 600; color: var(--text-primary); }
    .meta { font-family: 'JetBrains Mono', monospace; font-size: 11px; margin-left: auto; font-variant-numeric: tabular-nums; }
    .age { font-family: 'JetBrains Mono', monospace; font-size: 11px; font-variant-numeric: tabular-nums; }
    .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--text-secondary); opacity: 0.5; }
    .live .dot { background: var(--green); opacity: 1; box-shadow: 0 0 0 3px rgba(63, 125, 92, 0.18); }
    .stale .dot { background: var(--yellow); opacity: 1; box-shadow: 0 0 0 3px rgba(201, 147, 46, 0.18); }
    .down .dot { background: var(--red); opacity: 1; box-shadow: 0 0 0 3px rgba(184, 76, 62, 0.18); animation: pulse 1.2s ease-in-out infinite; }
    .connecting .dot { animation: pulse 1.2s ease-in-out infinite; }
    .stale .label { color: var(--yellow); }
    .down .label { color: var(--red); }
    .compact { padding: 0; gap: 6px; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
    @media (prefers-reduced-motion: reduce) { .dot { animation: none !important; } }
</style>
