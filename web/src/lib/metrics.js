import { writable, get } from 'svelte/store';

// The Metrics page: cards of host history (line graphs and single figures) the person
// arranges like the Overview. Layout kept in /api/prefs (metrics_layout) so every device
// shows the same page, with a copy in this browser so it paints right away.

export const RANGES = [['1h', '1 h'], ['6h', '6 h'], ['24h', '24 h'], ['7d', '7 d'], ['30d', '30 d']];
// the widget kinds; any metric can be shown as any of them (a gauge needs a fixed scale)
// (a graph of one host shows its figure over the history — what used to be the Number kind)
export const TYPES = [['line', 'Graph'], ['gauge', 'Gauge'], ['bars', 'Bars']];
// one host only (a gauge is always one ring); the others show every host picked (or all)
// download and upload together, mirrored around zero: a metric of its own made of two
export const NET = 'net';
// which kinds a metric can be shown as
export function kindsFor(meta) {
    if (!meta) return TYPES.map(t => t[0]);
    if (meta.key === NET) return ['line'];
    return TYPES.map(t => t[0]).filter(t => t !== 'gauge' || gaugeable(meta.unit));
}
// the theme colour a metric's single bar is drawn in (its parts are shades of it)
export function metricColor(key) {
    if (key === 'cpu' || key.startsWith('temp')) return 'var(--metric-cpu)';
    if (key === 'mem') return 'var(--metric-mem)';
    if (key === 'disk') return 'var(--metric-disk)';
    return 'var(--metric-net)';
}
// values that add up across hosts (memory, storage, traffic); the rest are averaged
export const additive = (unit) => unit !== 'pct' && unit !== 'c';

// Sizes, as Apple's widgets, on a grid of square cells (6 to a row on a desktop, 4 on a
// tablet, 2 on a phone, 8 on a very wide screen): Small 1×1, Medium 2×1, Large 2×2, Wide a
// whole row 1 high. Heights are always one or two cells, so nothing stretches to a neighbour.
// (kept in a widget's `width` field)
export const SIZE_NAMES = { s: 'Small', m: 'Medium', l: 'Large', full: 'Wide' };
export const SIZES = { line: [['m', 'Medium'], ['l', 'Large'], ['full', 'Wide']], bars: [['m', 'Medium'], ['full', 'Wide']], gauge: [['s', 'Small']] };
// a gauge: one host's ring in a small square
export const small = (c) => c.type === 'gauge';
// a size for this kind (older layouts: Auto/Third → Medium, Half → Large graph, Full → Wide)
export function sizeFor(type, w) {
    const ok = (SIZES[type] || SIZES.line).map(x => x[0]);
    if (ok.includes(w)) return w;
    if (type === 'gauge') return 's';
    if (w === 'full') return 'full';
    if (w === 'half' && ok.includes('l')) return 'l';
    return 'm';
}
// how many cells a row has at this width, and how big a cell is
export const cellsFor = (w) => w >= 1600 ? 8 : w >= 1000 ? 6 : w >= 620 ? 4 : 2;
export function cellOf(w, gap = 16) { const n = cellsFor(w); return { n, unit: (w - (n - 1) * gap) / n }; }
// a widget's grid spans: [columns, rows]
export function spanOf(c, cells) {
    const s = sizeFor(c.type, c.width);
    return s === 's' ? [1, 1] : s === 'm' ? [2, 1] : s === 'l' ? [2, 2] : [cells, 1];
}
// how big a widget of that size is on a page this wide: {w, h} in px
export function sizeOf(c, pageW, gap = 16) {
    const { n, unit } = cellOf(pageW, gap);
    const [cw, rh] = spanOf(c, n);
    return { w: Math.round(unit * cw + gap * (cw - 1)), h: Math.round(unit * rh + gap * (rh - 1)) };
}
export const widthOf = (c, pageW, gap = 16) => sizeOf(c, pageW, gap).w;

// ---- placing widgets on the grid, as Apple's desktop widgets ----------------------------------
// Each widget keeps the cell it was put in (per grid size: 6, 4 or 2 to a row), and empty
// cells stay empty. Widgets never placed on this grid (new ones, or a grid size never arranged)
// follow in order after them, each at the first spot that fits.
const hit = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
export function gridLayout(cards, n) {
    const out = {}, placed = [];
    const free = (p) => p.x >= 0 && p.x + p.w <= n && !placed.some(q => hit(p, q));
    const put = (id, p) => { out[id] = p; placed.push(p); };
    const sized = cards.map(c => { const [w, h] = spanOf(c, n); return { c, w: Math.min(w, n), h }; });
    const fixed = sized.filter(s => s.c.pos?.[n]).sort((a, b) => a.c.pos[n].y - b.c.pos[n].y || a.c.pos[n].x - b.c.pos[n].x);
    // placed by hand: where they were put (pushed down if two ever overlap)
    for (const s of fixed) {
        const p = { x: Math.max(0, Math.min(n - s.w, s.c.pos[n].x)), y: s.c.pos[n].y, w: s.w, h: s.h };
        while (!free(p)) p.y++;
        put(s.c.id, p);
    }
    // the rest in order, from below those (or from the top when none were placed by hand)
    let r = fixed.length ? Math.max(...placed.map(p => p.y + p.h)) : 0, c = 0;
    for (const s of sized.filter(s => !s.c.pos?.[n])) {
        const p = { x: c, y: r, w: s.w, h: s.h };
        while (!free(p)) { p.x++; if (p.x + p.w > n) { p.x = 0; p.y++; } }
        put(s.c.id, p); r = p.y; c = p.x + p.w;
    }
    return out;
}
// one widget moved to (x, y): whatever is in its way moves out of it. One widget of the same
// size takes the moved one's old place (a swap); anything else moves down as far as it must.
// Always worked out from the layout as it was when the drag began, so when the widget moves on,
// the others go back.
export function pushLayout(snap, id, x, y, n) {
    const me = snap[id];
    const at = { ...me, x: Math.max(0, Math.min(n - me.w, x)), y: Math.max(0, y) };
    const out = { [id]: at };
    const others = Object.entries(snap).filter(([k]) => k !== id).sort((a, b) => a[1].y - b[1].y || a[1].x - b[1].x);
    const inWay = others.filter(([, o]) => hit(o, at));
    if (inWay.length === 1 && inWay[0][1].w === me.w && inWay[0][1].h === me.h && !hit(me, at)) out[inWay[0][0]] = { ...inWay[0][1], x: me.x, y: me.y };
    for (const [k, o] of others) {
        if (out[k]) continue;
        const p = { ...o };
        while (Object.values(out).some(q => hit(p, q))) p.y++;
        out[k] = p;
    }
    return out;
}
// keep a grid's places (all its widgets, for this grid size)
export const setPositions = (n, map) => update(l => ({ ...l, cards: l.cards.map(c => map[c.id] ? { ...c, pos: { ...(c.pos || {}), [n]: { x: map[c.id].x, y: map[c.id].y } } } : c) }));

// the fixed scale a gauge or bar fills against: percentages and temperatures have one;
// for the rest the bars compare the hosts against the largest
export function scaleMax(unit) {
    return unit === 'pct' ? 100 : unit === 'c' ? 100 : null;
}
export const gaugeable = (unit) => scaleMax(unit) != null;

// one colour per host, the same in every card, by the host's place in the server's list,
// taken from the active theme's own colours
const HOST = ['var(--metric-cpu)', 'var(--metric-net)', 'var(--metric-mem)', 'var(--metric-disk)', 'var(--text-primary)'];
export function hostColor(node, cat) {
    const i = Object.keys(cat?.names || {}).indexOf(node);
    return i < 0 ? 'var(--text-secondary)' : HOST[i % HOST.length];
}

// ---- formatting by unit -------------------------------------------------------------------
const trim = (v, d) => String(+v.toFixed(d));
function bytes(v, rate) {
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (Math.abs(v) >= 1000 && i < u.length - 1) { v /= 1000; i++; }
    return [trim(v, v < 10 ? 1 : 0), u[i] + (rate ? '/s' : '')];
}
// [number, unit] so a figure can set the unit smaller
export function parts(v, unit) {
    if (v == null || !isFinite(v)) return ['—', ''];
    switch (unit) {
        case 'pct': return [trim(v, v < 10 ? 1 : 0), '%'];
        case 'gb': return [trim(v, v < 10 ? 1 : 0), 'GB'];
        case 'bytes': return bytes(v, false);
        case 'bps': return bytes(v, true);
        case 'c': return [trim(v, 0), '°C'];
        case 'mbit': return [trim(v, 0), 'Mbit/s'];
        default: return [trim(v, 1), ''];
    }
}
export const fmt = (v, unit) => { const [n, u] = parts(v, unit); return u ? (u === '%' || u === '°C' ? n + u : `${n} ${u}`) : n; };

// ---- catalog: which metrics exist and which hosts have data -------------------------------
export const catalog = writable(null);
let catAt = 0;
export async function loadCatalog(force = false) {
    if (!force && get(catalog) && Date.now() - catAt < 60000) return get(catalog);
    try {
        const j = await fetch('/api/metrics/catalog').then(r => r.json());
        if (j.status === 'success') {
            // download & upload together, for the hosts that send either
            const ms = j.data.metrics, at = ms.findIndex(m => m.key === 'net_tx');
            if (at >= 0) {
                const nodes = [...new Set([...ms[at - 1]?.nodes || [], ...ms[at].nodes])].sort((a, b) => Object.keys(j.data.names).indexOf(a) - Object.keys(j.data.names).indexOf(b));
                ms.splice(at + 1, 0, { key: NET, label: 'Download & upload', unit: 'bps', nodes });
            }
            catalog.set(j.data); catAt = Date.now();
        }
    } catch (e) {}
    return get(catalog);
}

// series, cached briefly so cards showing the same metric share one request
const cache = new Map();
// the newest value of each metric and host, whichever fetch brought it: a widget's "now" is the
// same whatever its time range (each range is its own fetch, cached for a while, so each would
// otherwise carry a reading of a different age)
const latest = new Map();
function keepLatest(key, d) {
    if (!d) return d;
    const fresh = Date.now() - 15 * 60e3;
    for (const s of d.series || []) {
        const k = key + '|' + s.node, o = latest.get(k);
        if (s.last && (!o || s.last.t >= o.t)) latest.set(k, s.last);
        else if (o && o.t >= fresh) s.last = o;
    }
    return d;
}
export function fetchSeries(key, nodes, range) {
    if (key === NET) {
        // each host's download, with its upload alongside
        return Promise.all([fetchSeries('net_rx', nodes, range), fetchSeries('net_tx', nodes, range)]).then(([rx, tx]) => {
            if (!rx && !tx) return null;
            const base = rx || tx, up = Object.fromEntries((tx?.series || []).map(s => [s.node, s]));
            const nodesAll = [...new Set([...(rx?.series || []), ...(tx?.series || [])].map(s => s.node))];
            const none = { points: [], last: null, max: null };
            return { ...base, key: NET, unit: 'bps', series: nodesAll.map(n => ({ ...((rx?.series || []).find(s => s.node === n) || { node: n, ...none }), up: up[n] || none })) };
        });
    }
    const q = `key=${encodeURIComponent(key)}&range=${range}${nodes?.length ? '&nodes=' + nodes.map(encodeURIComponent).join(',') : ''}`;
    const hit = cache.get(q);
    if (hit && Date.now() - hit.at < 30000) return hit.p.then(d => keepLatest(key, d));
    const p = fetch('/api/metrics/series?' + q).then(r => r.json()).then(j => j.status === 'success' ? j.data : null).catch(() => null);
    p.then(d => keepLatest(key, d));
    cache.set(q, { at: Date.now(), p });
    return p;
}

// ---- layout ------------------------------------------------------------------------------
const LOCAL = 'metrics_layout';
let n = 0;
const nid = () => 'c' + Date.now().toString(36) + (n++).toString(36);
const card = (type, metric, width, extra = {}) => ({ id: nid(), type, metric, width, nodes: [], node: null, title: '', ...extra });
const gauge = (metric, node) => card('gauge', metric, 's', { node });

export function defaults() {
    return {
        v: 2,
        range: '24h',
        cards: [
            gauge('cpu', 'arrakis'),
            gauge('temp_cpu', 'arrakis'),
            card('line', NET, 'auto', { nodes: ['arrakis'] }),
            card('line', 'cpu', 'auto'),
            card('line', 'temp_cpu', 'auto'),
            card('bars', 'mem', 'auto'),
            card('bars', 'disk', 'auto'),
            card('line', NET, 'full'),
        ],
    };
}

function norm(l) {
    if (!l || !Array.isArray(l.cards)) return defaults();
    return {
        v: 2,
        range: RANGES.some(r => r[0] === l.range) ? l.range : '24h',
        cards: l.cards.filter(c => c && c.id && c.metric).map(c => ({
            id: String(c.id), type: TYPES.some(t => t[0] === c.type) ? c.type : 'line', metric: String(c.metric),
            // a gauge is always small (a wider one became one per host)
            width: sizeFor(TYPES.some(t => t[0] === c.type) ? c.type : 'line', c.width),
            // a former number (or figure) widget is a graph of its one host
            nodes: (c.type === 'number' || c.type === 'figure') && c.node ? [String(c.node)] : Array.isArray(c.nodes) ? c.nodes.map(String) : [],
            node: c.type === 'gauge' && c.node ? String(c.node) : null,
            title: typeof c.title === 'string' ? c.title.slice(0, 60) : '',
            // its own time range (null: the layout's)
            range: RANGES.some(r => r[0] === c.range) ? c.range : null,
            // where it sits, per grid (cells to a row): { 6: {x, y}, ... } — placed by hand
            pos: Object.fromEntries(Object.entries(c.pos || {}).filter(([n, p]) => +n > 0 && p && Number.isInteger(p.x) && Number.isInteger(p.y) && p.x >= 0 && p.y >= 0).map(([n, p]) => [n, { x: p.x, y: p.y }])),
        })),
    };
}

function loadLocal() {
    try { const l = JSON.parse(localStorage.getItem(LOCAL)); if (l) return norm(l); } catch (e) {}
    return defaults();
}

export const mlayout = writable(loadLocal());
let loadP = null;
// once per page load; callers can await it (the Overview places widgets once both layouts are in)
export function loadLayout() { return loadP ||= fetchLayout(); }
async function fetchLayout() {
    try {
        const j = await fetch('/api/prefs').then(r => r.json());
        if (j.status === 'success' && j.data?.metrics_layout) {
            const l = norm(j.data.metrics_layout);
            if (!j.data.metrics_layout.v) save(l);      // migrated: keep it that way everywhere
            else {
                mlayout.set(l);
                try { localStorage.setItem(LOCAL, JSON.stringify(l)); } catch (e) {}
            }
        }
    } catch (e) {}
}

let timer;
function save(l) {
    mlayout.set(l);
    try { localStorage.setItem(LOCAL, JSON.stringify(l)); } catch (e) {}
    clearTimeout(timer);
    timer = setTimeout(() => fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ metrics_layout: l }) }).catch(() => {}), 400);
}
const update = (fn) => save(norm(fn(get(mlayout))));

export const setRange = (range) => update(l => ({ ...l, range }));
export const setCard = (id, patch) => update(l => ({ ...l, cards: l.cards.map(c => c.id === id ? { ...c, ...patch } : c) }));
export const removeCard = (id) => update(l => ({ ...l, cards: l.cards.filter(c => c.id !== id) }));
export const addCard = (c) => { const x = { ...card(c.type, c.metric, c.width, c), id: nid() }; update(l => ({ ...l, cards: [...l.cards, x] })); return x.id; };
export const setOrder = (ids) => update(l => ({ ...l, cards: ids.map(id => l.cards.find(c => c.id === id)).filter(Boolean) }));
export function moveCard(id, d) {
    update(l => {
        const o = [...l.cards], i = o.findIndex(c => c.id === id), j = i + d;
        if (i < 0 || j < 0 || j >= o.length) return l;
        [o[i], o[j]] = [o[j], o[i]];
        return { ...l, cards: o };
    });
}
export const resetLayout = () => save(defaults());

// gauges used to hold a ring per host: give each host a gauge of its own, in the same place
export function splitGauges(cat) {
    const l = get(mlayout);
    if (!cat || !l.cards.some(c => small(c) && !c.node)) return;
    update(l => ({ ...l, cards: l.cards.flatMap(c => {
        if (!small(c) || c.node) return [c];
        const avail = cat.metrics.find(m => m.key === c.metric)?.nodes || [];
        const ns = (c.nodes.length ? c.nodes.filter(n => avail.includes(n)) : avail);
        if (!ns.length) return [c];
        return ns.map((n, k) => ({ ...c, id: k ? nid() : c.id, node: n, nodes: [], width: 'auto' }));
    }) }));
}
