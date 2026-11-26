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
// Every size is named by its share of the row (on a desktop-wide page, 6 cells): a widget 1/6
// (one cell), 1/3 (two), 1/3 tall (two by two) or the full width; a section or card 1/3, 1/2 or
// the full width. (kept in a widget's `width` field, a section's cfg `cell`)
const W = [['s', '1/6'], ['m', '1/3'], ['l', '1/3 tall'], ['full', 'Full width']];
const pick = (...k) => W.filter(([z]) => k.includes(z));
const SHARE = [['auto', 'Auto'], ['m', '1/3'], ['half', '1/2'], ['full', 'Full width']];
export const SIZES = { line: pick('m', 'l', 'full'), bars: pick('m', 'full'), gauge: pick('s'),
    // sections that sit on the grid as widgets do
    avatar: pick('s', 'm', 'l'), text: pick('s', 'm', 'l', 'full'),
    // host and machine cards (Auto: as many to a row as fit at 380px or more, as the Infrastructure
    // page's cards), and every other section
    host: SHARE, machine: SHARE, section: SHARE.slice(1) };
export const sizeName = (type, z) => (SIZES[type] || SIZES.line).find(x => x[0] === z)?.[1] || z;

// ---- sizes per card (what the Overview's grid uses) ------------------------------------------
// Each kind of card has the widths that make sense for it, and for each width its height in cells
// (a cell: a square, 6 to a row on a desktop). Most have one height per width, set by what they
// show at that width; a few (graphs, avatar, text) can be 1 or 2 high. The first listed is the
// default. Widths are a share of the row on a desktop-wide page.
export const WIDTH_NAMES = { auto: 'Auto', '1/6': '1/6', '1/3': '1/3', '1/2': '1/2', '2/3': '2/3', full: 'Full width' };
const SIXTHS = { '1/6': 1, '1/3': 2, '1/2': 3, '2/3': 4, full: 6 };
const one = (ws, hs) => Object.fromEntries(ws.map(w => [w, hs]));
export const CARD_SIZES = {
    // Only a width is chosen. A row is as tall as the tallest thing in it and everything in it
    // stretches to that; a widget, the avatar or a text card is at least one cell (a square) tall.
    line: one(['1/3', '2/3', 'full'], ['auto']), bars: one(['1/3', 'full'], ['auto']), gauge: { '1/6': ['auto'] },
    avatar: one(['1/6', '1/3'], ['auto']), text: one(['1/6', '1/3', '1/2', '2/3', 'full'], ['auto']),
    host: one(['1/3', '1/2'], ['auto']), machine: one(['1/3', '1/2'], ['auto']),
    totals: one(['full', '1/2', '1/3'], ['auto']), attention: one(['full', '1/2', '1/3'], ['auto']),
    tailscale: one(['full', '1/2'], ['auto']), shortcuts: one(['full', '1/2', '1/3'], ['auto']),
    compute: one(['full', '1/2'], ['auto']), pihole: one(['full', '1/2'], ['auto']), uptime: one(['full', '1/2'], ['auto']),
    'api-latency': one(['full', '1/2'], ['auto']), rack: one(['full', '1/2'], ['auto']),
    webapps: { full: ['auto'] },
    section: one(['full', '1/2'], ['auto']),
};
const sizesOf = (type) => CARD_SIZES[type] || CARD_SIZES.section;
export const widthsFor = (type) => Object.keys(sizesOf(type));
export const heightsFor = (type, wk) => sizesOf(type)[wk] || [1];
export const heightName = (h) => `${h} high`;
// a card's width and height: what it was set to if that's one of its sizes, else the nearest from
// its older single size, else its first
const OLD = { s: '1/6', m: '1/3', l: '1/3', full: 'full', half: '1/2', auto: '1/3' };
export function dimsOf(type, w, h, old) {
    const ws = widthsFor(type);
    const ow = OLD[old] || OLD[sizeFor(type, old)];
    const wk = ws.includes(w) ? w : ws.includes(ow) ? ow : ws[0];
    const hs = heightsFor(type, wk);
    const oh = old === 'l' ? 2 : null;
    const hk = hs.includes(h) ? h : hs.includes(+h) ? +h : hs.includes(oh) ? oh : hs[0];
    return { wk, hk };
}
const SMALL = ['line', 'bars', 'gauge', 'avatar', 'text', 'host', 'machine'];
export const isSection = (type) => !SMALL.includes(type);
// cells across for a width on a row of n cells: exact on a desktop; a tablet rounds up (a third is
// half the row) and gives sections the whole row; a phone gives everything but 1/6 the whole row
export function colsFor(wk, n, type, fitCols) {
    if (wk === 'auto') return Math.min(n, fitCols || Math.ceil(n / 2));
    const c6 = SIXTHS[wk] || 2;
    if (wk === 'full' || (n <= 2 && c6 > 1)) return n;
    if (n <= 4) return !SMALL.includes(type) ? n : Math.min(n, Math.ceil(c6 * n / 6));
    return Math.min(n, Math.max(1, Math.round(c6 * n / 6)));
}
// a gauge: one host's ring in a small square
export const small = (c) => c.type === 'gauge';
// a size for this kind (older layouts: Auto/Third → Medium, Half → Large graph, Full → Wide)
export function sizeFor(type, w) {
    const ok = (SIZES[type] || SIZES.line).map(x => x[0]);
    if (ok.includes(w)) return w;
    if (ok.length === 1) return ok[0];
    if (w === 'full') return 'full';
    if (w === 'half' && ok.includes('l')) return 'l';
    return 'm';
}
// how many cells a row has at this width, and how big a cell is
export const cellsFor = (w) => w >= 1600 ? 8 : w >= 1000 ? 6 : w >= 620 ? 4 : 2;
export function cellOf(w, gap = 16) { const n = cellsFor(w); return { n, unit: (w - (n - 1) * gap) / n }; }
// a widget's grid spans: [columns, rows]
export function spanOf(c, cells) {
    if (c.wk) return [colsFor(c.wk, cells, c.type, c.fitCols), c.hk === 'auto' ? 1 : +c.hk];
    const s = sizeFor(c.type, c.width);
    // a card or section: a width, its row as tall as it needs. A phone gives each the whole row;
    // a tablet too, except host and machine cards (two to a row there)
    if (c.rows) {
        const whole = s === 'full' || cells <= 2 || (cells <= 4 && c.type === 'section');
        const third = cells >= 6 ? Math.round(cells / 3) : Math.min(2, cells);
        return [whole ? cells : s === 'auto' ? (c.fitCols || Math.ceil(cells / 2)) : s === 'half' ? Math.ceil(cells / 2) : third, c.rows];
    }
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
        // in the way (it grew, or the screen is narrower): the nearest free spot on its own row,
        // else the next rows down, from the left
        if (!free(p)) {
            const xs = [...Array(n - s.w + 1).keys()];
            const near = xs.slice().sort((a, b) => Math.abs(a - p.x) - Math.abs(b - p.x)).find(x => free({ ...p, x }));
            if (near != null) p.x = near;
            else for (p.y++; ; p.y++) { const x = xs.find(x => free({ ...p, x })); if (x != null) { p.x = x; break; } }
        }
        put(s.c.id, p);
    }
    // the rest in order, from below those (or from the top when none were placed by hand)
    let r = fixed.length ? Math.max(...placed.map(p => p.y + p.h)) : 0, c = 0;
    for (const s of sized.filter(s => !s.c.pos?.[n])) {
        const p = { x: c, y: r, w: s.w, h: s.h };
        while (!free(p)) { p.x++; if (p.x + p.w > n) { p.x = 0; p.y++; } }
        put(s.c.id, p); r = p.y; c = p.x + p.w;
    }
    // the avatar or a text card on Auto height: as tall as the tallest item that starts on its row,
    // as far as the cells under it are free
    for (const s of sized.filter(s => s.c.fill)) {
        const p = out[s.c.id], others = Object.entries(out).filter(([k]) => k !== s.c.id).map(([, q]) => q);
        const want = Math.max(1, ...others.filter(q => q.y === p.y).map(q => q.h));
        while (p.h < want && !others.some(q => hit({ ...p, h: p.h + 1 }, q))) p.h++;
    }
    return closeRows(out);
}
// rows with nothing in them close up (gaps beside a widget stay), so nothing floats below blank space
function closeRows(out) {
    const used = new Set();
    for (const p of Object.values(out)) for (let y = p.y; y < p.y + p.h; y++) used.add(y);
    const rows = [...used].sort((a, b) => a - b), at = new Map(rows.map((y, i) => [y, i]));
    for (const p of Object.values(out)) p.y = at.get(p.y);
    return out;
}
// one widget moved to (x, y): whatever is in its way moves out of it. One widget of the same
// size takes the moved one's old place (a swap); anything else moves down as far as it must.
// Always worked out from the layout as it was when the drag began, so when the widget moves on,
// the others go back.
export function pushLayout(snap, id, x, y, n, pcx = null) {
    const me = snap[id];
    const at = { ...me, x: Math.max(0, Math.min(n - me.w, x)), y: Math.max(0, y) };
    const out = { [id]: at };
    const others = Object.entries(snap).filter(([k]) => k !== id).sort((a, b) => a[1].y - b[1].y || a[1].x - b[1].x);
    // the pointer over an empty cell, the widget's edge just over a neighbour (the drop cell is
    // rounded from that edge): it slides to the free spot under the pointer instead of pushing
    // the neighbour down a row. Only with the pointer on the neighbour itself does it push.
    const blocked = (p) => others.some(([, o]) => hit(o, p));
    if (pcx != null && me.w < n && blocked(at) && !blocked({ x: pcx, y: at.y, w: 1, h: 1 })) {
        const near = [...Array(n - at.w + 1).keys()].filter(x => x <= pcx && pcx < x + at.w && !blocked({ ...at, x }))
            .sort((a, b) => Math.abs(a - at.x) - Math.abs(b - at.x))[0];
        if (near != null) at.x = near;
    }
    const inWay = others.filter(([, o]) => hit(o, at));
    // (not a whole-row item: those insert where they're dropped, the rest moving down, as a list does)
    if (me.w < n && inWay.length === 1 && inWay[0][1].w === me.w && inWay[0][1].h === me.h && !hit(me, at)) out[inWay[0][0]] = { ...inWay[0][1], x: me.x, y: me.y };
    for (const [k, o] of others) {
        if (out[k]) continue;
        const p = { ...o };
        const taken = (q) => Object.values(out).some(r => hit(q, r)) || others.some(([j, r]) => j !== k && !out[j] && hit(q, r));
        if (Object.values(out).some(q => hit(p, q))) {
            // room on its own row: it slides along it (the side the moved one isn't on first),
            // as Apple's widgets do; only with no room does it go down a row
            const side = o.x + o.w / 2 >= at.x + at.w / 2 ? 1 : -1;
            const xs = [...Array(n - p.w + 1).keys()].filter(x => !taken({ ...p, x }))
                .sort((a, b) => Math.abs(a - o.x) - Math.abs(b - o.x) || (b - a) * side);
            if (xs.length) p.x = xs[0];
            else while (Object.values(out).some(q => hit(p, q))) p.y++;
        }
        out[k] = p;
    }
    return out;
}
// the arrows: a widget and the one before / after it in reading order trade places. On one row
// the pair keeps its span (the later one now starts where the earlier one did); across rows each
// takes the other's spot. Anything then in the way moves down.
const reading = (a, b) => a.y - b.y || a.x - b.x;
export function swapLayout(snap, id, d, n) {
    const order = Object.entries(snap).sort((a, b) => reading(a[1], b[1])).map(([k]) => k);
    const i = order.indexOf(id), j = i + d;
    if (i < 0 || j < 0 || j >= order.length) return null;
    const other = order[j], A = snap[id], B = snap[other];
    const fit = (p, x) => Math.max(0, Math.min(n - p.w, x));
    let a, b;
    if (A.y === B.y) {
        const [first, second] = d < 0 ? [A, B] : [B, A];      // first = whichever ends up on the left
        const L = Math.min(A.x, B.x);
        const p1 = { ...first, x: fit(first, L) }, p2 = { ...second, x: fit(second, L + first.w) };
        [a, b] = d < 0 ? [p1, p2] : [p2, p1];
    } else {
        a = { ...A, x: fit(A, B.x), y: B.y };
        b = { ...B, x: fit(B, A.x), y: A.y };
    }
    const out = { [id]: a, [other]: b };
    for (const [k, o] of Object.entries(snap).filter(([k]) => k !== id && k !== other).sort((x, y) => reading(x[1], y[1]))) {
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
            // its width and height on the Overview's grid (set in its bar; dimsOf checks them against its sizes)
            ...(typeof c.w === 'string' && c.w in SIXTHS ? { w: c.w } : {}),
            ...([1, 2].includes(+c.h) ? { h: +c.h } : {}),
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
