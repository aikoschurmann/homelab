<script>
    import { onDestroy } from 'svelte';
    import MetricChart from './MetricChart.svelte';
    import Gauge from './Gauge.svelte';
    import { ChevronDown } from 'lucide-svelte';
    import { fetchSeries, setCard, hostColor, metricColor, additive, fmt, parts, scaleMax, small, RANGES, NET } from '../../lib/metrics.js';

    // One widget on the Metrics page: a quiet label, then the figure or the plot.
    // Kinds: number, gauge (one host's ring), line graph, bars (one bar split by host, as on
    // the Overview). "Download & upload" draws upload above zero and download below.
    export let card;
    export let range = '24h';      // the default; a widget can have its own
    export let ext = 0;            // px it reaches into the gap (merged with the widget before it): not its own width
    export let editable = false;   // its time range can be changed from its header
    export let cat = null;

    $: meta = cat?.metrics.find(m => m.key === card.metric);
    $: names = cat?.names || {};
    $: avail = meta?.nodes || [];
    // a small gauge is one host's ring; wider gauges and the other kinds show every host picked
    $: sq = small(card);
    $: nodes = sq ? [card.node && avail.includes(card.node) ? card.node : avail[0]].filter(Boolean) : (card.nodes.length ? card.nodes.filter(n => avail.includes(n)) : avail);
    $: title = card.title || meta?.label || card.metric;
    $: rng = card.range || range;
    $: rangeLabel = RANGES.find(r => r[0] === rng)?.[1] || rng;
    const pickRange = (r) => setCard(card.id, { range: r });
    let rOpen = false, rBtn, rPos = '';
    // on the page's body, so no card painted after this one can cover it
    function portal(node) { document.body.appendChild(node); return { destroy() { node.remove(); } }; }
    function toggleRange() {
        rOpen = !rOpen;
        if (!rOpen) return;
        const b = rBtn.getBoundingClientRect();
        rPos = `top: ${b.bottom + 6}px; right: ${Math.max(8, window.innerWidth - b.right - 6)}px`;
    }
    $: net = card.metric === NET;

    let data = null, loading = true, timer;
    async function load() {
        if (!nodes.length) { data = null; loading = false; return; }
        data = await fetchSeries(card.metric, nodes, rng);
        loading = false;
    }
    $: card.metric, nodes.join(','), rng, cat && (loading = true, load());
    timer = setInterval(() => cat && load(), 60000);
    onDestroy(() => clearInterval(timer));

    $: unit = data?.unit || meta?.unit;
    $: allSeries = (data?.series || []).map(s => ({ node: s.node, name: names[s.node] || s.node, color: hostColor(s.node, cat), points: s.points, last: s.last, max: s.max, up: s.up }));
    // a graph of every host: the three busiest now (more lines and legend entries are a tangle),
    // kept in their usual order
    const MAXL = 3;
    $: top = card.type === 'line' && !card.nodes.length && allSeries.length > MAXL
        ? new Set([...allSeries].sort((a, b) => (b.last?.v ?? -Infinity) - (a.last?.v ?? -Infinity)).slice(0, MAXL).map(s => s.node)) : null;
    $: series = top ? allSeries.filter(s => top.has(s.node)) : allSeries;
    $: has = series.some(s => s.points.length || s.last || s.up?.points.length || s.up?.last);
    $: firstT = Math.min(...series.flatMap(s => [s.points, s.up?.points || []]).filter(p => p.length).map(p => p[0][0]));
    $: since = data && isFinite(firstT) && firstT - data.from > (data.to - data.from) * 0.15
        ? new Date(firstT).toLocaleString([], (data.to - firstT) > 20 * 3600e3 ? { weekday: 'short', hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit' }) : null;
    $: when = since ? `since ${since}` : rangeLabel;

    // one host's value now, average and peak (number, gauge)
    $: one = series[0];
    const avgOf = (pts) => { const v = (pts || []).map(p => p[1]).filter(v => v != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
    $: avg = avgOf(one?.points);
    $: [nv, nu] = parts(one?.last?.v ?? null, unit);
    $: [uv, uu] = parts(one?.up?.last?.v ?? null, unit);
    $: wifi = card.metric.startsWith('wifi') && one ? cat?.wifi?.[one.node] : null;

    // line graphs of several hosts: tabs to look at one (remembered per widget in this browser)
    // each host's tab switches its line on or off; at least one stays on
    const HK = () => 'metric_hidden_' + card.id;
    let hidden = [], hseen = null;
    $: if (card.id !== hseen) { hseen = card.id; try { hidden = JSON.parse(localStorage.getItem(HK()) || '[]'); if (!Array.isArray(hidden)) hidden = []; } catch (e) { hidden = []; } }
    function toggle(n) {
        const h = hidden.includes(n) ? hidden.filter(x => x !== n) : [...hidden, n];
        if (!series.some(s => !h.includes(s.node))) return;
        hidden = h;
        try { h.length ? localStorage.setItem(HK(), JSON.stringify(h)) : localStorage.removeItem(HK()); } catch (e) {}
    }
    $: tabs = card.type === 'line' && series.length > 1;
    // the All tab: the hosts' total (amounts that add up) or their average (%, °C)
    $: pv = (v) => parts(v ?? null, unit);
    const sumOf = (ss, up) => { const v = ss.map(s => (up ? s.up : s)?.last?.v).filter(v => v != null); return v.length ? v.reduce((a, b) => a + b, 0) : null; };
    $: allVal = (() => { const v = series.map(s => s.last?.v).filter(v => v != null); if (!v.length) return null; const t = v.reduce((a, b) => a + b, 0); return additive(unit) ? t : t / v.length; })();
    // download and upload in one tab: ↓ figure, ↑ figure
    const esc = (x) => String(x).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
    $: two = (d, u) => { const [a, au] = parts(d ?? null, unit), [b, bu] = parts(u ?? null, unit); return `<i>↓</i>${esc(a)}<small>${esc(au)}</small><i class="u">↑</i>${esc(b)}<small>${esc(bu)}</small>`; };
    $: shown = tabs && series.some(s => !hidden.includes(s.node)) ? series.filter(s => !hidden.includes(s.node)) : series;

    // mirrored network: upload above zero, download below. One host: the two in two colours;
    // several: each host's colour both ways
    const DOWN = 'var(--metric-cpu)', UP = 'var(--metric-net)';
    $: lines = net
        ? shown.flatMap(s => [
            { name: shown.length > 1 ? `${s.name} ↑` : 'Upload', color: shown.length > 1 ? s.color : UP, points: s.up?.points || [] },
            { name: shown.length > 1 ? `${s.name} ↓` : 'Download', color: shown.length > 1 ? s.color : DOWN, points: s.points, neg: true },
        ])
        : shown;

    // gauge: as large as the tile allows
    let tw = 300, th = 180;
    // gauge: a small square tile, the ring filling what the title and host name leave
    // the ring fits the square cell: its width (less what it reaches into a merged gap) and its
    // height less the caption under it
    $: gsize = Math.max(48, Math.min(160, tw - ext - 28, th - 66));
    $: full = scaleMax(unit) ?? 1;

    // bars: one bar split by host, biggest first, parts in shades of the metric's colour.
    // Amounts that add up (memory, storage, traffic) show the total; % and °C the average.
    const SHADES = [1, 0.7, 0.5, 0.35, 0.25];
    $: live = series.filter(s => s.last?.v != null).sort((a, b) => b.last.v - a.last.v).map((s, i) => ({ ...s, shade: SHADES[Math.min(i, SHADES.length - 1)] }));
    $: sum = live.reduce((a, s) => a + s.last.v, 0);
    $: adds = additive(unit);
    $: barVal = adds ? sum : (live.length ? sum / live.length : null);
    $: [bv, bu] = parts(barVal, unit);
    // over the range: the hosts' total (or average) through time, each host's latest value carried
    // forward, so its average and peak are of the whole, not each host's added up
    $: barStats = (() => {
        if (card.type !== 'bars' || !live.length) return null;
        // one host: its own average and peak
        if (live.length === 1) { const a = avgOf(live[0].points); return a == null ? null : { avg: a, peak: live[0].max ?? a }; }
        const ev = live.flatMap((s, i) => (s.points || []).filter(p => p[1] != null).map(p => [p[0], i, p[1]])).sort((a, b) => a[0] - b[0]);
        const last = new Array(live.length).fill(null), agg = [];
        for (let k = 0; k < ev.length; k++) {
            last[ev[k][1]] = ev[k][2];
            if (k + 1 < ev.length && ev[k + 1][0] === ev[k][0]) continue;
            if (last.some(v => v == null)) continue;      // (from when every host has reported)
            const t = last.reduce((a, b) => a + b, 0);
            agg.push(adds ? t : t / last.length);
        }
        if (!agg.length) return null;
        return { avg: agg.reduce((a, b) => a + b, 0) / agg.length, peak: Math.max(...agg) };
    })();
    // a share of the bar: of the total, or (averaged kinds) of the hosts' full scale
    $: share = (v) => adds ? (sum ? v / sum * 100 : 0) : v / ((scaleMax(unit) || 100) * Math.max(1, live.length)) * 100;
    $: mc = metricColor(card.metric);

    const EMPTY = {
        net_rx: 'Agents send this from version 19.', net_tx: 'Agents send this from version 19.', net: 'Agents send this from version 19.',
        wifi_signal: 'Only hosts on Wi-Fi.', wifi_rate: 'Only hosts on Wi-Fi.',
        temp_cpu: 'Hosts with readable sensors.', temp_ssd: 'Hosts with readable sensors.',
    };
</script>

<svelte:window on:click={() => rOpen = false} on:scroll|capture={() => rOpen = false} on:resize={() => rOpen = false} on:keydown={(e) => e.key === 'Escape' && (rOpen = false)} />

{#if card.type === 'bars'}
<!-- bars: the Overview's own cluster tile (ui-stat), one bar split by host, its legend under it -->
<!-- laid out as a one-host graph: title and range, the big figure, what it is with its average
     and peak, then (where the graph would be) one bar split by host and its legend -->
<div class="ui-stat mb">
    <div class="hd"><span class="t">{title}</span><span class="m">{rangeLabel}</span></div>
    {#if !has}
        <div class="empty"><span>{loading ? 'Loading…' : 'No data yet'}</span>{#if !loading && EMPTY[card.metric]}<small>{EMPTY[card.metric]}</small>{/if}</div>
    {:else}
        <div class="big">{bv}<small>{bu}</small></div>
        <div class="sub">{#if live.length > 1}{adds ? `total of ${live.length} hosts` : `average of ${live.length} hosts`}{:else}{live[0]?.name}{/if}{#if barStats}{' · '}avg {fmt(barStats.avg, unit)} · peak {fmt(barStats.peak, unit)}{/if}</div>
        <div class="bb">
            <div class="ui-segbar" title={live.map(s => `${s.name}: ${fmt(s.last.v, unit)}`).join('\n')}>
                {#each live as s (s.node)}<i style="width: {Math.min(100, share(s.last.v))}%; background: {mc}; opacity: {s.shade}"></i>{/each}
            </div>
            <span class="ui-stat-sub ui-legend">{#each live.slice(0, 3) as s (s.node)}<span><b style="background: {mc}; opacity: {s.shade}"></b>{s.name} {fmt(s.last.v, unit)}</span>{/each}{#if live.length > 3}<span>+{live.length - 3} more</span>{/if}</span>
        </div>
    {/if}
</div>
{:else}
<div class="w k-{card.type}" class:sq bind:clientWidth={tw} bind:clientHeight={th}>
    {#if !sq}
    <div class="hd">
        <span class="t">{title}</span>
        <span class="m">{#if card.type === 'line'}
            <!-- its time range, picked right here -->
            {#if editable}
                <button class="rb" class:on={rOpen} bind:this={rBtn} title="Time range" on:click|stopPropagation={toggleRange}>{rangeLabel}<ChevronDown size={12} /></button>
                {#if rOpen}
                    <!-- one compact row of ranges, fixed so the card can't clip it -->
                    <span class="rpick" use:portal style={rPos} role="menu" tabindex="-1" on:click|stopPropagation on:keydown={() => {}}>{#each RANGES as [r, l]}<button role="menuitemradio" aria-checked={r === rng} class:on={r === rng} on:click={() => { rOpen = false; pickRange(r); }}>{l}</button>{/each}</span>
                {/if}
            {:else}{rangeLabel}{/if}
        {:else if card.type === 'gauge'}{:else if series.length === 1}{one.name}{:else if card.type === 'bars' && live.length > 1}{live.length} hosts{/if}</span>
    </div>
    {/if}

    {#if !has}
        {#if sq}<div class="gcap"><b>{title}</b></div>{/if}
        <div class="empty"><span>{loading ? 'Loading…' : 'No data yet'}</span>{#if !loading && EMPTY[card.metric]}<small>{EMPTY[card.metric]}</small>{/if}</div>

    {:else if card.type === 'gauge' && !sq}
        <!-- wider: each host's own ring, side by side -->
        <div class="rings">{#each series as s (s.node)}<div class="r1"><Gauge value={s.last?.v ?? null} max={full} {unit} color={s.color} size={104} /><span class="gcap"><b>{s.name}</b></span></div>{/each}</div>

    {:else if card.type === 'gauge'}
        <div class="gauge" title={avg != null ? `avg ${fmt(avg, unit)} · peak ${fmt(one.max, unit)}` : ''}><Gauge value={one?.last?.v ?? null} max={full} {unit} color={one?.color} size={gsize} /></div>
        <div class="gcap"><b>{title}</b><span>{one?.name}{#if wifi?.ssid}{' · ' + wifi.ssid}{/if}</span></div>

    {:else}
        <!-- a graph: one host shows its figure over the history; several get a tab each to switch them on and off -->
        {#if tabs}
            <div class="tabs">
                {#each series as s (s.node)}
                    <button class:on={!hidden.includes(s.node)} aria-pressed={!hidden.includes(s.node)} title="{hidden.includes(s.node) ? 'Show' : 'Hide'} {s.name}" on:click={() => toggle(s.node)}>
                        <span class="pl"><b style="background: {s.color}"></b>{s.name}</span>
                        {#if net}<span class="tv">{@html two(s.last?.v, s.up?.last?.v)}</span>
                        {:else}<span class="tv">{pv(s.last?.v)[0]}<small>{pv(s.last?.v)[1]}</small></span>{/if}
                    </button>
                {/each}
            </div>
            {#if net && shown.length === 1}<div class="lg key"><span><b style="background: {UP}"></b>Upload</span><span><b style="background: {DOWN}"></b>Download</span></div>{/if}
        {:else if net}
            <div class="pair">
                <div><span class="pl"><b style="background: {DOWN}"></b>Download</span><span class="big md">{nv}<small>{nu}</small></span></div>
                <div><span class="pl"><b style="background: {UP}"></b>Upload</span><span class="big md">{uv}<small>{uu}</small></span></div>
            </div>
        {:else}
            <div class="big">{nv}<small>{nu}</small></div>
            <div class="sub">{one.name}{#if wifi?.ssid}{' · ' + wifi.ssid}{/if}{#if avg != null}{' · '}avg {fmt(avg, unit)} · peak {fmt(one.max, unit)}{/if}</div>
        {/if}
        <div class="flush" class:tall={tabs || net}><MetricChart bare series={lines} {unit} from={data.from} to={data.to} step={data.step} height={0} /></div>
    {/if}
</div>
{/if}

<style>
    /* the tile: the dashboard's card surface, roomy and quiet */
    .w { position: relative; display: flex; flex-direction: column; gap: 6px; height: 100%; min-height: 0; overflow: hidden; box-sizing: border-box; padding: 18px 20px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card, 8px); min-width: 0; }
    .hd { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
    .t { flex: 1; min-width: 0; font-size: 13px; font-weight: 500; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    /* the time range: the label as a quiet button; a click opens one solid row of ranges */
    .rb { display: inline-flex; align-items: center; gap: 2px; height: 22px; padding: 0 4px 0 7px; margin: -4px -6px -4px 0; border-radius: 6px; font-size: 12px; color: var(--text-secondary); cursor: pointer; }
    .rb:hover, .rb.on { background: var(--highlight-10); color: var(--text-primary); }
    .rpick { position: fixed; z-index: 300; display: flex; gap: 2px; padding: 3px; border-radius: 8px; background: var(--surface) linear-gradient(var(--highlight-10), var(--highlight-10)); border: 1px solid var(--border-strong); box-shadow: 0 12px 32px rgba(0, 0, 0, .6); }
    .rpick button { height: 26px; padding: 0 9px; border-radius: 6px; font-size: 12px; color: var(--text-secondary); white-space: nowrap; cursor: pointer; }
    .rpick button:hover { background: var(--highlight-10); color: var(--text-primary); }
    .rpick button.on { background: var(--highlight-15); box-shadow: inset 0 0 0 1px var(--border-strong); color: var(--text-primary); font-weight: 600; }
    .m { font-size: 12px; color: var(--text-secondary); opacity: .75; white-space: nowrap; }
    .empty { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 2px; font-size: 13px; color: var(--text-secondary); }
    .empty small { font-size: 12px; opacity: .75; }

    /* number: the figure large and tight, one quiet line, the history flush along the bottom */
    .big { font-size: 32px; font-weight: 600; letter-spacing: -0.035em; line-height: 1.1; color: var(--text-primary); font-variant-numeric: tabular-nums; white-space: nowrap; margin-top: 2px; }
    .big small { font-size: 15px; font-weight: 500; letter-spacing: 0; color: var(--text-secondary); margin-left: 4px; }
    .big.sm { font-size: 24px; }
    .sub { font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-height: 1.3em; }
    .flush { overflow: hidden; border-radius: 0 0 var(--radius-card, 8px) var(--radius-card, 8px); flex: 1; min-height: 28px; margin: 8px -20px -18px; display: flex; flex-direction: column; }
    /* the plot fills what the tile has left; it never makes the tile (or its row) taller */
    .flush { position: relative; }
    .flush > :global(*) { position: absolute; inset: 0; }

    .big.md { font-size: 26px; margin-bottom: 4px; }
    .pair { display: flex; gap: 28px; flex-wrap: wrap; }
    .pair > div { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .pl { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-secondary); }
    .pl b { width: 8px; height: 8px; border-radius: 2px; }
    .pair .big { margin: 0; }
    .dir { font-style: normal; font-weight: 500; color: var(--text-secondary); margin-right: 4px; font-size: .7em; }
    .sub .dir { font-size: 1em; margin-right: 3px; }
    .sub.c { text-align: center; }

    /* gauge: one host's ring, centred */
    .w.sq { padding: 12px 10px 10px; gap: 6px; align-items: center; }
    .gauge { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; }
    .rings { flex: 1; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-around; gap: 16px 12px; padding: 6px 0 2px; }
    .r1 { display: flex; flex-direction: column; align-items: center; gap: 8px; min-width: 0; }
    .gcap { display: flex; flex-direction: column; align-items: center; gap: 1px; max-width: 100%; text-align: center; }
    .gcap b { font-size: 12.5px; font-weight: 500; color: var(--text-primary); }
    .gcap span, .gcap b { max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .gcap span { font-size: 11.5px; color: var(--text-secondary); }

    /* bars: as tall as the row it sits in, like the Overview's tiles */
    .mb { height: 100%; box-sizing: border-box; overflow: hidden; padding: 18px 20px; gap: 6px; }
    /* the bar and its legend at the bottom, where a graph's plot would be */
    .bb { margin-top: auto; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
    .bb .ui-segbar { height: 8px; }

    /* line: each host's value now (the legend), then the plot */
    .lg { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 12.5px; color: var(--text-secondary); margin-top: 2px; }
    .lg span { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
    .lg b { width: 6px; height: 6px; border-radius: 50%; }
    /* hosts over a line graph: a legend line like the Overview tiles' (dot, name, value now),
       each one a toggle for its line; dimmed when off */
    .tabs { display: flex; flex-wrap: wrap; gap: 2px 14px; margin: 0 0 4px; }
    .tabs button { display: inline-flex; align-items: baseline; gap: 6px; padding: 1px 0; cursor: pointer; white-space: nowrap; transition: opacity .12s; }
    /* (name and figure on one baseline: the name's own box aligns by its text, not its dot) */
    .tabs .pl { white-space: nowrap; align-items: baseline; }
    .tabs .pl b { width: 6px; height: 6px; border-radius: 50%; align-self: center; }
    .tabs button:not(.on) { opacity: .4; }
    .tabs button:hover { opacity: 1; }
    .tabs button:not(.on):hover { opacity: .7; }
    .tv { font-size: 12.5px; font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; white-space: nowrap; }
    .tv :global(small), .tv small { font-size: 11px; font-weight: 500; color: var(--text-secondary); margin-left: 1px; }
    .tv :global(i) { font-style: normal; font-size: 11.5px; font-weight: 500; color: var(--text-secondary); margin-right: 2px; }
    .tv :global(i.u) { margin-left: 6px; }
    .lg.key { font-size: 11.5px; }
    .lg em + em { margin-left: 2px; }
    .lg em { font-style: normal; font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; }
    .plot { flex: 1; display: flex; flex-direction: column; justify-content: flex-end; margin: 6px -20px -18px; }

    @media (max-width: 760px) {
        .w { padding: 14px 16px; }
        .big { font-size: 26px; }
        .flush { margin: 6px -16px -14px; }
        .plot { margin: 6px -16px -14px; }
    }
</style>
