<script>
    // A thin history strip: one series as a filled line on a fixed 0..max scale, so strips
    // side by side compare honestly (a quiet computer looks quiet, not stretched to fill).
    export let points = [];          // [[timestampMs, value], ...]
    export let max = 1;
    export let color = 'var(--metric-cpu)';
    export let windowMs = 10 * 60 * 1000;
    export let height = 28;

    const W = 200;
    $: end = points.length ? points[points.length - 1][0] : Date.now();
    $: x = (t) => Math.max(0, W - (end - t) / windowMs * W);
    $: y = (v) => height - 1 - Math.min(1, Math.max(0, v / (max || 1))) * (height - 2);
    $: shown = points.filter(p => p[0] >= end - windowMs);
    $: line = shown.map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
    $: area = shown.length ? `${x(shown[0][0]).toFixed(1)},${height} ${line} ${x(shown[shown.length - 1][0]).toFixed(1)},${height}` : '';
</script>

<svg viewBox="0 0 {W} {height}" preserveAspectRatio="none" style="height: {height}px" role="img" aria-label="history">
    <line x1="0" x2={W} y1={height - 0.5} y2={height - 0.5} stroke="var(--highlight-15)" stroke-width="1" vector-effect="non-scaling-stroke" />
    {#if shown.length > 1}
        <polygon points={area} fill={color} opacity="0.16" />
        <polyline points={line} fill="none" stroke={color} stroke-width="1.5" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
    {/if}
</svg>

<style>
    svg { display: block; width: 100%; }
</style>
