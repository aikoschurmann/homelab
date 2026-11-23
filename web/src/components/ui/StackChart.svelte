<script>
    // Several series over time: stacked bands (stacked = true) or separate 2px lines, an
    // optional dashed line at a capacity, crosshair tooltip listing every series and the total.
    // Series: [{ name, color, points: [[timestampMs, value], ...] }] sharing timestamps.
    import { onMount, onDestroy } from 'svelte';

    export let series = [];
    export let capacity = null;           // dashed line, e.g. the pool's total cores
    export let capacityLabel = '';
    export let height = 220;
    export let windowMs = 10 * 60 * 1000;
    export let format = (v) => v.toFixed(1);
    export let stacked = true;

    let el, chart, ro;
    const css = (v) => v.startsWith('var(') ? getComputedStyle(document.documentElement).getPropertyValue(v.slice(4, -1)).trim() : v;

    function render() {
        if (!chart) return;
        const all = series.flatMap(s => s.points);
        const now = all.length ? Math.max(...all.map(p => p[0])) : Date.now();
        const surface = css('var(--surface)'), txt = css('var(--text-secondary)'), grid = css('var(--highlight-15)');
        const top = stacked ? Math.max(capacity || 0, 0) : 0;
        chart.setOption({
            animation: false,
            grid: { left: 40, right: 12, top: 14, bottom: 24 },
            tooltip: {
                trigger: 'axis', backgroundColor: surface, borderColor: css('var(--border)'), textStyle: { color: css('var(--text-primary)'), fontSize: 12 },
                axisPointer: { type: 'line', lineStyle: { color: txt, width: 1 } },
                formatter: (items) => {
                    const t = new Date(items[0].value[0]).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                    const sum = items.reduce((a, i) => a + (i.value[1] || 0), 0);
                    const rows = [...items].reverse().map(i => `<div style="display:flex;gap:8px;align-items:center;justify-content:space-between"><span><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${i.color};margin-right:6px"></span>${i.seriesName}</span><b>${format(i.value[1] || 0)}</b></div>`).join('');
                    return `<div style="min-width:170px"><div style="color:${txt};margin-bottom:4px">${t}</div>${rows}<div style="display:flex;justify-content:space-between;border-top:1px solid ${grid};margin-top:4px;padding-top:4px"><span>Total</span><b>${format(sum)}${capacity ? ` of ${capacity}` : ''}</b></div></div>`;
                },
            },
            xAxis: { type: 'time', min: now - windowMs, max: now, splitNumber: 6, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
                axisLabel: { color: txt, fontSize: 11, hideOverlap: true, formatter: { hour: '{HH}:{mm}', minute: '{HH}:{mm}', second: '{HH}:{mm}:{ss}' } } },
            yAxis: { type: 'value', min: 0, max: top ? Math.ceil(top * 1.05) : null, minInterval: stacked ? null : 1, splitNumber: 4, axisLabel: { color: txt, fontSize: 11 }, splitLine: { lineStyle: { color: grid } } },
            series: series.map((s, i) => ({
                name: s.name, type: 'line', data: s.points, showSymbol: false, smooth: 0.15, itemStyle: { color: css(s.color) },
                // stacked: a 2px surface-coloured edge keeps neighbouring bands apart
                ...(stacked ? { stack: 'all', lineStyle: { width: 2, color: surface }, areaStyle: { color: css(s.color), opacity: 0.9 } }
                            : { lineStyle: { width: 2, color: css(s.color) } }),
                ...(i === series.length - 1 && capacity ? { markLine: { silent: true, symbol: 'none', lineStyle: { color: txt, type: 'dashed', width: 1 },
                    label: { formatter: capacityLabel || String(capacity), color: txt, fontSize: 11, position: 'insideEndTop' }, data: [{ yAxis: capacity }] } } : {}),
            })),
        }, true);
    }

    onMount(async () => {
        const echarts = (await import('../../lib/echarts.js')).default;
        chart = echarts.init(el, null, { renderer: 'canvas' });
        render();
        ro = new ResizeObserver(() => chart?.resize());
        ro.observe(el);
    });
    onDestroy(() => { ro?.disconnect(); chart?.dispose(); });

    $: series, capacity, windowMs, stacked, chart && render();
</script>

<div bind:this={el} style="height: {height}px; width: 100%;"></div>
