<script>
    import { parts } from '../../lib/metrics.js';
    // A thin full ring filled clockwise from the top to value / max, the figure inside
    export let value = null;
    export let max = 100;
    export let unit = '';
    export let color = 'var(--accent)';
    export let size = 88;
    export let label = '';

    const R = 45, C = 2 * Math.PI * R;
    // a small value still shows as a short arc, not a dot
    $: frac = value == null ? 0 : Math.max(value > 0 ? 0.035 : 0, Math.min(1, value / max));
    $: [n, u] = parts(value, unit);
</script>

<div class="g">
    <div class="ring" style="width: {size}px; height: {size}px">
        <svg viewBox="0 0 100 100" width={size} height={size} aria-label="{label} {n}{u}">
            <circle class="track" cx="50" cy="50" r={R} />
            {#if frac > 0}<circle class="val" cx="50" cy="50" r={R} stroke={color} stroke-dasharray="{C * frac} {C}" />{/if}
        </svg>
        <span class="v" style="font-size: {Math.max(14, Math.round(size * 0.24))}px">{n}<small>{u}</small></span>
    </div>
    {#if label}<span class="l" style="max-width: {size + 24}px">{label}</span>{/if}
</div>

<style>
    .g { display: flex; flex-direction: column; align-items: center; gap: 8px; flex-shrink: 0; min-width: 0; }
    .ring { position: relative; }
    svg { display: block; transform: rotate(-90deg); }
    circle { fill: none; stroke-width: 9; stroke-linecap: round; }
    .track { stroke: var(--highlight-15); }
    .val { transition: stroke-dasharray .5s cubic-bezier(0.22, 1, 0.36, 1); }
    .v { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; letter-spacing: -0.03em; }
    .v small { font-size: 0.45em; font-weight: 500; color: var(--text-secondary); margin-left: 1px; letter-spacing: 0; align-self: center; }
    .l { font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
