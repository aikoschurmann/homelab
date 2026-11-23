<script>
    import { onMount, onDestroy } from 'svelte';
    // Small area chart over [timestampMs, value] points
    export let points = [];
    export let color = 'var(--metric-cpu)';
    export let max = null;      // number, or (extent) => number
    export let format = (v) => String(v);
    export let height = 180;
    export let windowMs = 10 * 60 * 1000;
    export let bare = false;   // sparkline: no axes, grid or tooltip
    export let min = 0;        // number, or (extent) => number
    export let interval = null; // tick spacing; when null and min/max are numbers, a quarter of the range
    export let compact = false; // small screens: tighter margins, smaller labels
    export let unit = null;     // when set, axis labels are the tick value (trimmed) + unit
    export let dots = false;    // sparse data: points instead of a filled line   // fixed time window, so the line grows in from the right

    let el, chart, echarts, ro;
    const css = (v) => v.startsWith('var(') ? getComputedStyle(document.documentElement).getPropertyValue(v.slice(4, -1)).trim() : v;

    // A stretch with no samples (Mac asleep, backend down) breaks the line instead of
    // being drawn straight across
    function withGaps(pts) {
        if (pts.length < 3) return pts;
        const steps = pts.slice(1).map((p, i) => p[0] - pts[i][0]).sort((a, b) => a - b);
        const step = steps[steps.length >> 1];
        const out = [pts[0]];
        for (let i = 1; i < pts.length; i++) {
            if (pts[i][0] - pts[i - 1][0] > step * 3) out.push([pts[i - 1][0] + step, null]);
            out.push(pts[i]);
        }
        return out;
    }

    // Even, round ticks: 4–5 steps of 1, 2, 2.5 or 5 × 10ⁿ covering lo..hi
    function nice(lo, hi) {
        if (!(hi > lo)) hi = lo + 1;
        const rough = (hi - lo) / 4, mag = 10 ** Math.floor(Math.log10(rough));
        const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(v => v >= rough);
        return { min: Math.floor(lo / step + 1e-9) * step, max: Math.ceil(hi / step - 1e-9) * step, interval: step };
    }
    // the y range: explicit min/max/interval as given; otherwise round ticks around the data
    function yAxisRange() {
        if (interval != null && typeof min === 'number' && typeof max === 'number') return { min, max, interval };
        const vals = points.map(p => p[1]).filter(v => v != null && isFinite(v));
        const dMin = vals.length ? Math.min(...vals) : 0, dMax = vals.length ? Math.max(...vals) : 1;
        const lo = typeof min === 'number' ? min : typeof min === 'function' ? min({ min: dMin, max: dMax }) : dMin;
        const hi = typeof max === 'number' ? max : typeof max === 'function' ? max({ min: dMin, max: dMax }) : dMax * 1.1;
        return nice(lo, hi);
    }

    function render() {
        if (!chart) return;
        const data = withGaps(points);
        const now = points.length ? points[points.length - 1][0] : Date.now();
        // the window starts at the first sample when that is close to the window start,
        // so a full window fills edge to edge; a short history still grows in from the right
        let start = now - windowMs;
        if (points.length && points[0][0] - start < windowMs * 0.1) start = Math.max(start, points[0][0]);
        const range = yAxisRange();
        const decimals = Math.max(0, -Math.floor(Math.log10(range.interval) + 1e-9) + (String(range.interval).includes('.25') ? 1 : 0));
        const label = unit != null ? (v) => `${+(+v).toFixed(decimals)}${unit}` : format;
        const c = css(color), grid = css('var(--highlight-15)'), txt = css('var(--text-secondary)');
        if (bare) {
            chart.setOption({
                animation: false,
                grid: { left: 0, right: 0, top: 2, bottom: 0 },
                xAxis: { type: 'time', min: start, max: now, show: false },
                // scaled to the data so a quiet series still shows its shape
                yAxis: { type: 'value', show: false, min: (v) => Math.max(0, v.min - (v.max - v.min || v.max || 1) * 0.3), max: (v) => v.max + (v.max - v.min || v.max || 1) * 0.3 },
                series: [{ type: 'line', data, showSymbol: false, connectNulls: false, smooth: 0.2, lineStyle: { width: 1.4, color: c }, areaStyle: { color: c, opacity: 0.1 } }],
            }, true);
            return;
        }
        chart.setOption({
            animation: false,
            grid: compact ? { left: 34, right: 8, top: 10, bottom: 22 } : { left: 52, right: 12, top: 12, bottom: 24 },
            tooltip: { trigger: 'axis', valueFormatter: format, backgroundColor: css('var(--surface)'), borderColor: css('var(--border)'), textStyle: { color: css('var(--text-primary)'), fontSize: 12 } },
            xAxis: { type: 'time', min: start, max: now, minInterval: 60 * 1000, splitNumber: 6, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { color: txt, fontSize: compact ? 10 : 11, hideOverlap: true, formatter: { year: '{yyyy}', month: '{MMM}', day: '{MMM} {d}', hour: '{HH}:{mm}', minute: '{HH}:{mm}', second: '{HH}:{mm}:{ss}' } } },
            yAxis: { type: 'value', ...range, axisLabel: { color: txt, fontSize: compact ? 10 : 11, formatter: label }, splitLine: { lineStyle: { color: grid } } },
            series: [dots
                ? { type: 'scatter', data: points, symbolSize: 5, itemStyle: { color: c, opacity: 0.8 } }
                : { type: 'line', data, showSymbol: false, connectNulls: false, smooth: 0.2, lineStyle: { width: 1.6, color: c }, areaStyle: { color: c, opacity: 0.12 } }],
        }, true);
    }

    onMount(async () => {
        echarts = (await import('../../lib/echarts.js')).default;
        chart = echarts.init(el, null, { renderer: 'canvas' });
        render();
        ro = new ResizeObserver(() => chart?.resize());
        ro.observe(el);
    });
    onDestroy(() => { ro?.disconnect(); chart?.dispose(); });

    $: points, max, min, interval, compact, unit, chart && render();
</script>

<div bind:this={el} style="height: {height}px; width: 100%;"></div>
