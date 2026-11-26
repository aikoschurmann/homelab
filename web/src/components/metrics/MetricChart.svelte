<script>
    import { onMount, onDestroy } from 'svelte';
    import { fmt } from '../../lib/metrics.js';
    // Line graph of one metric, one line per host: [{ name, color, points: [[ms, v]], neg? }]
    // A series with neg is drawn below zero (download under upload); zero then sits in the middle.
    export let series = [];
    export let unit = '';
    export let from = 0;
    export let to = 0;
    export let step = 60;          // seconds between points; a longer silence breaks the line
    export let height = 200;
    export let compact = false;
    export let bare = false;
    export let flush = false;      // edge to edge: the value labels sit inside the plot       // sparkline under a figure: no axes, grid or tooltip

    let el, chart, ro;
    // colour with alpha, for the area's fade (resolved token hex or rgb)
    function alpha(c, a) {
        const m = c.match(/^#([0-9a-f]{6})$/i);
        if (m) { const n = parseInt(m[1], 16); return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${a})`; }
        return c.replace(/^rgb\((.*)\)$/, `rgba($1, ${a})`);
    }
    const fade = (c, top, down) => ({ type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: down ? 1 : 0, color: alpha(c, top) }, { offset: down ? 0 : 1, color: alpha(c, 0) }] });
    const esc = (x) => String(x).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
    const css = (v) => v.startsWith('var(') ? getComputedStyle(document.documentElement).getPropertyValue(v.slice(4, -1)).trim() || v : v;

    function withGaps(pts) {
        // a silence counts from the series' own spacing (storage is sampled every 10 min)
        const d = pts.slice(1).map((p, i) => p[0] - pts[i][0]).sort((a, b) => a - b);
        const gap = Math.max(step * 1000, d[d.length >> 1] || 0) * 3;
        const out = [];
        for (let i = 0; i < pts.length; i++) {
            if (i && pts[i][0] - pts[i - 1][0] > gap) out.push([pts[i - 1][0] + gap / 3, null]);
            out.push(pts[i]);
        }
        // sparse series (storage): a point stands for its whole interval, so the line runs on to
        // the chart's edges when it began or last reported within one interval of them
        const iv = gap / 3;
        if (out.length && out[0][1] != null && out[0][0] - from > 0 && out[0][0] - from <= iv) out.unshift([from, out[0][1]]);
        const z = out[out.length - 1];
        if (z && z[1] != null && to - z[0] > 0 && to - z[0] <= iv) out.push([to, z[1]]);
        return out;
    }
    // even, round ticks: 4–5 steps of 1, 2, 2.5 or 5 × 10ⁿ
    function nice(lo, hi) {
        if (!(hi > lo)) hi = lo + 1;
        const rough = (hi - lo) / (compact ? 3 : 4), mag = 10 ** Math.floor(Math.log10(rough));
        const st = [1, 2, 2.5, 5, 10].map(m => m * mag).find(v => v >= rough);
        return { min: Math.floor(lo / st + 1e-9) * st, max: Math.ceil(hi / st - 1e-9) * st, interval: st };
    }
    $: mirror = series.some(s => s.neg);
    let barPeak = null;     // bars: the largest bucket total, for the axis
    function yRange() {
        const vals = series.flatMap(s => s.points.map(p => p[1])).filter(v => v != null && isFinite(v));
        if (mirror) {
            const r = nice(0, ((barPeak ?? Math.max(0, ...vals)) * 1.1) || 1);
            return { min: -r.max, max: r.max, interval: r.max / (compact ? 2 : 3) };
        }
        if (!vals.length) return unit === 'pct' ? { min: 0, max: 100, interval: 25 } : nice(0, 1);
        const lo = Math.min(...vals), hi = Math.max(...vals);
        // temperatures sit far from zero: frame the band they move in
        if (unit === 'c') return nice(Math.max(0, lo - 5), hi + 3);
        const r = nice(0, hi * 1.1 || 1);
        if (unit === 'pct' && r.max > 100) return { min: 0, max: 100, interval: 25 };
        return r;
    }

    function render() {
        if (!chart) return;
        const txt = css('var(--text-secondary)'), grid = css(compact ? 'var(--highlight-10)' : 'var(--highlight-15)');
        // fill under a lone line (or the two halves of one host's mirror); several would stack into a block
        const one = series.length === 1 || (mirror && series.length === 2);
        // upload and download: mirrored bars, a bucket each, up from and down from zero; with
        // several hosts each direction is a stack of the hosts' shares in their colours
        const bars = mirror;
        barPeak = null;
        const stacked = mirror && series.length > 2;
        if (bars) {
            const n = bare ? 48 : compact ? 60 : 90, w = (to - from) / n;
            const plotW = Math.max(60, chart.getWidth() - (bare ? 0 : 70));
            const bw = Math.max(1, Math.floor(plotW / n * 0.62));
            // every host on the same n buckets (stacks line up by position), null where it is silent
            const bucket = (pts) => {
                const sum = new Array(n).fill(0), cnt = new Array(n).fill(0);
                for (const [t, v] of pts) { if (v == null || t < from) continue; const k = Math.min(n - 1, Math.floor((t - from) / w)); sum[k] += v; cnt[k]++; }
                return sum.map((x, k) => [from + (k + 0.5) * w, cnt[k] ? x / cnt[k] : null]);
            };
            const bk = series.map(s => bucket(s.points));
            // the axis covers the largest stacked total either way
            const tot = { u: new Array(n).fill(0), d: new Array(n).fill(0) };
            series.forEach((s, i) => bk[i].forEach(([, v], k) => { if (v != null) tot[s.neg ? 'd' : 'u'][k] += v; }));
            barPeak = Math.max(...tot.u, ...tot.d);
            var mirrored = series.map((s, i) => {
                const c = css(s.color);
                return { type: 'bar', name: s.name, barWidth: bw, barGap: '-100%', animation: false,
                    stack: stacked ? (s.neg ? 'down' : 'up') : undefined,
                    data: bk[i].map(p => s.neg && p[1] != null ? [p[0], -p[1]] : p),
                    itemStyle: { color: alpha(c, stacked && s.neg ? 0.6 : 0.85), borderRadius: stacked ? 0 : s.neg ? [0, 0, 2, 2] : [2, 2, 0, 0] }, emphasis: { disabled: true } };
            });
        }
        const lines = bars ? mirrored : series.map(s => {
            const c = css(s.color);
            // a line needs two points; a lone one shows as a dot
            const lone = s.points.length < 2;
            const data = withGaps(s.points).map(p => s.neg && p[1] != null ? [p[0], -p[1]] : p);
            return { type: 'line', name: s.name, data, showSymbol: lone, symbol: 'circle', symbolSize: 5, connectNulls: false, smooth: 0.25,
                lineStyle: { width: 1.5, color: c }, itemStyle: { color: c },
                // a soft fade under a lone line; under several, a faint one each (stronger would stack into a block)
                areaStyle: { color: fade(c, one ? (mirror ? 0.32 : 0.22) : 0.08, s.neg) },
                emphasis: { disabled: true } };
        });
        // mirrored: a clear zero line, "↑ up" above it and "↓ down" below, at the left
        // mirrored: upload above, download below zero (no line drawn at zero)
        const zero = (lines) => lines;
        const span = to - from;
        const tooltip = { appendTo: 'body',     // (on the page's body: a card's edge can't cut it off)
               
                trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: txt, opacity: 0.45, type: [3, 3] } },
                backgroundColor: css('var(--surface)'), borderColor: css('var(--border)'), textStyle: { color: css('var(--text-primary)'), fontSize: 12 },
                formatter: (ps) => {
                    const t = new Date(ps[0]?.value?.[0] ?? ps[0]?.axisValue);
                    const when = span > 2 * 86400e3 ? t.toLocaleString([], { weekday: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    const rows = ps.filter(p => p.value?.[1] != null).sort((a, b) => mirror ? 0 : b.value[1] - a.value[1])
                        .map(p => `<div style="display:flex;gap:14px;justify-content:space-between;align-items:center"><span style="display:inline-flex;align-items:center;gap:6px"><i style="width:8px;height:8px;border-radius:2px;background:${p.color};display:inline-block"></i>${esc(p.seriesName)}</span><b style="font-weight:600">${fmt(Math.abs(p.value[1]), unit)}</b></div>`).join('');
                    return `<div style="font-size:11px;opacity:.7;margin-bottom:4px">${when}</div>${rows || '<span style="opacity:.7">no data</span>'}`;
                },
            };
        if (bare) {
            chart.setOption({
                animation: false, tooltip, grid: mirror ? { left: 0, right: 0, top: 8, bottom: 1 } : { left: 0, right: 0, top: 12, bottom: 10 },
                xAxis: { type: 'time', min: from, max: to, show: false },
                // lines over a scale from zero (temperatures: from near their lowest); edge to edge,
                // with room above and below so the top line clears the legend and one near zero the
                // card's edge
                yAxis: mirror
                    ? { type: 'value', show: false, min: (v) => -Math.max(-v.min, v.max, 1) * 1.15, max: (v) => Math.max(-v.min, v.max, 1) * 1.15 }
                    : { type: 'value', min: unit === 'c' ? (v) => Math.max(0, Math.floor((v.min - 5) / 10) * 10) : 0, max: unit === 'pct' ? (v) => (v.max > 50 ? 100 : undefined) : undefined,
                        splitNumber: 2, axisLine: { show: false }, axisTick: { show: false },
                        axisLabel: { show: false },
                        splitLine: { show: false } },
                series: zero(lines),
            }, true);
            return;
        }
        chart.setOption({
            animation: false, tooltip,
            grid: flush ? { left: 0, right: 0, top: 6, bottom: 22 } : compact ? { left: 4, right: 4, top: 10, bottom: 22, containLabel: true } : { left: 56, right: 14, top: 12, bottom: 24 },
            xAxis: { type: 'time', min: from, max: to, splitNumber: compact ? 3 : 6, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
                axisLabel: { color: txt, fontSize: compact ? 10 : 11, hideOverlap: true, ...(flush ? { showMinLabel: false, showMaxLabel: false } : {}), formatter: { year: '{yyyy}', month: '{MMM}', day: '{MMM} {d}', hour: '{HH}:{mm}', minute: '{HH}:{mm}', second: '{HH}:{mm}' } } },
            yAxis: { type: 'value', ...yRange(), axisLabel: { show: !flush, color: txt, fontSize: compact ? 10 : 11, formatter: (v) => mirror ? (v ? (v > 0 ? '↑ ' : '↓ ') + fmt(Math.abs(v), unit) : '0') : fmt(v, unit) }, splitLine: { show: !flush, lineStyle: { color: grid, type: [2, 4] } } },
            series: zero(lines),
        }, true);
    }

    onMount(async () => {
        const echarts = (await import('../../lib/echarts.js')).default;
        chart = echarts.init(el, null, { renderer: 'canvas' });
        render();
        ro = new ResizeObserver(() => { chart?.resize(); if (mirror) render(); });
        ro.observe(el);
    });
    onDestroy(() => { ro?.disconnect(); chart?.dispose(); });

    $: series, unit, from, to, compact, chart && render();
</script>

<!-- height 0: fill the parent (a stretched figure tile) -->
<div bind:this={el} style="height: {height ? height + 'px' : '100%'}; width: 100%;"></div>
