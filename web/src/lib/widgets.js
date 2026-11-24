import { writable, derived } from 'svelte/store';

// The Overview's sections in their default order; the page's "Customize" menu can reorder
// and hide them, and hide single host cards. Host card order is the shared host order
// (lib/hosts.js), the same one the sidebar uses.
export const OVERVIEW_WIDGETS = [
    { id: 'webapps', label: 'Web apps' },
    { id: 'attention', label: 'Updates, apps and backups' },
    { id: 'totals', label: 'Cluster totals' },
    { id: 'tailscale', label: 'Tailscale' },
    { id: 'shortcuts', label: 'Shortcuts' },
    { id: 'compute', label: 'Compute pools' },
    { id: 'api-latency', label: 'API latency' },
    { id: 'uptime', label: 'Uptime checks' },
    { id: 'pihole', label: 'Pi-hole' },
];
// pages the shortcuts section can link to; the Overview fills in each one's figure
export const SHORTCUTS = [
    { id: 'databases', label: 'Databases' }, { id: 'terminal', label: 'Terminal' }, { id: 'backups', label: 'Backups' },
    { id: 'updates', label: 'Updates' }, { id: 'apps', label: 'Apps' }, { id: 'logs', label: 'Logs' },
    { id: 'tailscale', label: 'Tailscale' }, { id: 'cloudflare', label: 'Cloudflare' }, { id: 'pihole', label: 'Pi-hole' },
    { id: 'endpoints', label: 'API endpoints' },
];
const SC_IDS = SHORTCUTS.map(x => x.id);
// a section's kind, for a copy of it too ('tailscale#k3x' → 'tailscale')
export const baseOf = (t) => String(t).split('#')[0];
// another of something already on the page gets a tag of its own
export const copyOf = (t) => t + '#' + Math.random().toString(36).slice(2, 6);
const IDS = OVERVIEW_WIDGETS.map(w => w.id);

// sections made of tiles, whose tiles can be hidden one by one
export const SECTION_TILES = {
    attention: [{ id: 'updates', label: 'Package updates' }, { id: 'apps', label: 'Apps' }, { id: 'backups', label: 'Backups' }],
    totals: [{ id: 'hosts', label: 'Hosts' }, { id: 'cpu', label: 'CPU' }, { id: 'mem', label: 'Memory' }, { id: 'disk', label: 'Storage' }],
};
// the tiles' order inside each section (tiles added since come last)
function tileOrder(o = {}) {
    return Object.fromEntries(Object.entries(SECTION_TILES).map(([k, ts]) => {
        const ids = ts.map(t => t.id), saved = (o?.[k] || []).filter(x => ids.includes(x));
        return [k, [...saved, ...ids.filter(x => !saved.includes(x))]];
    }));
}
// which neighbouring tiles share one card (a line between them instead of a gap), per section;
// a pair is 'a|b' in either order. Updates, apps and backups start as one card.
export const joinKey = (a, b) => [a, b].sort().join('|');
function tileJoins(j) {
    // 'metrics': metric widgets next to each other, by widget id
    const def = { totals: [], attention: [joinKey('updates', 'apps'), joinKey('apps', 'backups')], metrics: [] };
    return Object.fromEntries(Object.keys(def).map(k => [k, Array.isArray(j?.[k]) ? j[k] : def[k]]));
}
// how many cluster tiles per row ('auto' follows the screen width)
export const COLS = ['auto', '1', '2', '3', '4'];

// { order, hidden, hidden_hosts }: kept in /api/prefs (overview_layout) so every device
// shows the same page, with a copy in this browser so it paints right away
const LOCAL = 'overview_layout';
const OLD = 'overview_hidden_widgets_v2';

function norm(l = {}) {
    // sections added since the layout was saved go in at their default place
    // metric widgets sit among the sections as 'm:<widget id>' ('metrics': where they all went before)
    // host cards each on their own as 'h:<host id>' ('host': where they all were before; a fresh
    // page starts with them there)
    const src = l.order?.length ? l.order : [...IDS.slice(0, IDS.indexOf('totals') + 1), 'host'];
    // items: a section ('tailscale', a copy 'tailscale#k3x'), a metric widget 'm:<id>', a host's card
    // 'h:<id>', a machine's card 'v:<name>' (cards and copies can be there more than once)
    const order = src.filter(id => IDS.includes(baseOf(id)) || /^[mhv]:/.test(id) || ['metrics', 'host', 'machines'].includes(id));
    IDS.forEach((id, i) => {
        if (order.includes(id)) return;
        const before = IDS.slice(0, i).reverse().find(p => order.includes(p));
        order.splice(before ? order.indexOf(before) + 1 : 0, 0, id);
    });
    return { order, hidden: (l.hidden || []).filter(id => IDS.includes(id)), hidden_hosts: l.hidden_hosts || [],
        hidden_tiles: l.hidden_tiles || [], tile_order: tileOrder(l.tile_order), tile_joins: tileJoins(l.tile_joins), totals_cols: COLS.includes(l.totals_cols) ? l.totals_cols : 'auto',
        // sections at half width sit two to a row
        widths: Object.fromEntries(Object.entries(l.widths || {}).filter(([k, v]) => IDS.includes(baseOf(k)) && v === 'half')),
        shortcuts: Array.isArray(l.shortcuts) ? l.shortcuts.filter(x => SC_IDS.includes(x)) : ['databases', 'terminal'] };
}

function loadLocal() {
    try { const l = JSON.parse(localStorage.getItem(LOCAL)); if (l) return norm(l); } catch (e) {}
    try { return norm({ hidden: JSON.parse(localStorage.getItem(OLD)) || [] }); } catch (e) { return norm(); }
}

export const layout = writable(loadLocal());
export const hiddenWidgets = derived(layout, l => new Set(l.hidden));

export async function fetchLayout() {
    try {
        const j = await fetch('/api/prefs').then(r => r.json());
        if (j.status === 'success' && j.data?.overview_layout) layout.set(norm(j.data.overview_layout));
    } catch (e) {}
}

let saveTimer;
function save(l) {
    layout.set(l);
    try { localStorage.setItem(LOCAL, JSON.stringify(l)); } catch (e) {}
    // dragging saves on every step; the server gets the last one
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ overview_layout: l }) }).catch(() => {}), 400);
}
// Merges belong to a spot between two neighbours, not to the two tiles: after any reorder a
// merge is kept only if the same two tiles are still side by side, in the same order (the one
// dragged leaves its merges behind, and two tiles that meet again later don't snap back together).
const seqOf = (l, kind) => kind === 'metrics' ? l.order.filter(t => !l.hidden.includes(t)).map(t => t.startsWith('m:') ? t.slice(2) : '§' + t)
    : (l.tile_order[kind] || []).filter(t => !l.hidden_tiles.includes(t));
const pairs = (s) => new Set(s.slice(1).map((t, i) => s[i] + '|' + t));
function keepJoins(prev, next) {
    const tj = { ...next.tile_joins };
    for (const kind of Object.keys(tj)) {
        const a = seqOf(prev, kind), b = seqOf(next, kind);
        if (a.join() === b.join()) continue;
        const was = pairs(a), now = pairs(b);
        tj[kind] = tj[kind].filter(k => { const [x, y] = k.split('|'); return (was.has(x + '|' + y) && now.has(x + '|' + y)) || (was.has(y + '|' + x) && now.has(y + '|' + x)); });
    }
    return { ...next, tile_joins: tj };
}
const update = (fn) => { let cur; layout.subscribe(v => cur = v)(); save(keepJoins(cur, norm(fn(cur)))); };
const toggle = (list, id) => list.includes(id) ? list.filter(x => x !== id) : [...list, id];

export const toggleWidget = (id) => update(l => ({ ...l, hidden: toggle(l.hidden, id) }));
export const toggleHostCard = (id) => update(l => ({ ...l, hidden_hosts: toggle(l.hidden_hosts, id) }));
export const toggleTile = (id) => update(l => ({ ...l, hidden_tiles: toggle(l.hidden_tiles, id) }));
export const toggleJoin = (kind, a, b) => update(l => {
    const k = joinKey(a, b), cur = l.tile_joins[kind];
    return { ...l, tile_joins: { ...l.tile_joins, [kind]: cur.includes(k) ? cur.filter(x => x !== k) : [...cur, k] } };
});
// drop the merges of a section that fn(a, b) says no longer sit side by side
export const keepJoinsIf = (kind, fn) => update(l => ({ ...l, tile_joins: { ...l.tile_joins, [kind]: l.tile_joins[kind].filter(k => fn(...k.split('|'))) } }));
export const setTileOrder = (kind, ids) => update(l => ({ ...l, tile_order: { ...l.tile_order, [kind]: [...ids, ...l.tile_order[kind].filter(x => !ids.includes(x))] } }));
export const setTotalsCols = (v) => update(l => ({ ...l, totals_cols: v }));
export const setWidth = (id, w) => update(l => ({ ...l, widths: { ...l.widths, [id]: w } }));
export const setShortcuts = (list) => update(l => ({ ...l, shortcuts: list }));
export const setWidgetOrder = (order) => update(l => ({ ...l, order }));
export const showAllWidgets = () => update(l => ({ ...l, hidden: [], hidden_hosts: [], hidden_tiles: [] }));
export const resetLayout = () => update(() => ({}));

// keep the metric widgets in the order: new ones where the old Metrics section was (else after
// the cluster totals for a first set, else at the end), removed ones out
export function syncMetrics(cardIds) {
    let cur; layout.subscribe(v => cur = v)();
    const want = cardIds.map(i => 'm:' + i), wantSet = new Set(want);
    let order = cur.order.filter(t => !t.startsWith('m:') || wantSet.has(t));
    const missing = want.filter(t => !order.includes(t));
    const old = order.indexOf('metrics');
    if (old >= 0) order.splice(old, 1, ...missing);
    else if (missing.length) {
        const first = !order.some(t => t.startsWith('m:'));
        const at = first && order.includes('totals') ? order.indexOf('totals') + 1 : order.length;
        order.splice(at, 0, ...missing);
    }
    if (order.join() !== cur.order.join()) save(norm({ ...cur, order }));
}
// the old "Host cards" section becomes a card per host it showed, where it was (once)
export function syncHosts(hostIds) {
    let cur; layout.subscribe(v => cur = v)();
    if (!cur.order.includes('host')) return;
    const tokens = cur.hidden.includes('host') ? [] : hostIds.filter(h => !cur.hidden_hosts.includes(h)).map(h => 'h:' + h).filter(t => !cur.order.includes(t));
    save(norm({ ...cur, order: cur.order.flatMap(t => t === 'host' ? tokens : [t]), hidden: cur.hidden.filter(x => x !== 'host') }));
}
// the old Machines section becomes a card per machine, where it was (once; dropped if hidden)
export function syncMachines(names) {
    let cur; layout.subscribe(v => cur = v)();
    if (!cur.order.includes('machines')) return;
    const tokens = cur.hidden.includes('machines') ? [] : names.map(n => 'v:' + n).filter(t => !cur.order.includes(t));
    save(norm({ ...cur, order: cur.order.flatMap(t => t === 'machines' ? tokens : [t]), hidden: cur.hidden.filter(x => x !== 'machines') }));
}
// insert items (section ids or tokens) before or after another, or at the end
export function placeItems(items, target) {
    let cur; layout.subscribe(v => cur = v)();
    const o = cur.order.filter(t => !items.includes(t));
    let at = target ? o.indexOf(target.id) : -1;
    at = at < 0 ? o.length : at + (target.after ? 1 : 0);
    o.splice(at, 0, ...items);
    save(norm({ ...cur, order: o, hidden: cur.hidden.filter(x => !items.includes(x)) }));
}
// these items in this order, each taking one of the places they hold now
export const reorderWithin = (tokens) => update(l => {
    const set = new Set(tokens), o = [...l.order];
    let k = 0;
    o.forEach((t, i) => { if (set.has(t)) o[i] = tokens[k++]; });
    return { ...l, order: o };
});
// a widget dropped from the page (its settings are removed with it)
export const orderWithout = (token) => update(l => ({ ...l, order: l.order.filter(t => t !== token) }));

// How tall each section really is on the Overview (and how wide it was), per width, so the
// Customize preview can draw every section at its true proportions. Kept in this browser.
const HKEY = 'overview_heights';
function loadH() { try { return JSON.parse(localStorage.getItem(HKEY)) || {}; } catch (e) { return {}; } }
export const sectionSizes = writable(loadH());
let hTimer;
export function measureSection(node, key) {
    let k = key;
    const ro = new ResizeObserver(() => {
        const w = node.offsetWidth, h = node.offsetHeight;
        if (!w || !h) return;
        sectionSizes.update(m => {
            if (m[k] && Math.abs(m[k].h - h) < 2 && Math.abs(m[k].w - w) < 2) return m;
            const n = { ...m, [k]: { w, h } };
            clearTimeout(hTimer); hTimer = setTimeout(() => { try { localStorage.setItem(HKEY, JSON.stringify(n)); } catch (e) {} }, 500);
            return n;
        });
    });
    ro.observe(node);
    return { update(nk) { k = nk; }, destroy() { ro.disconnect(); } };
}
