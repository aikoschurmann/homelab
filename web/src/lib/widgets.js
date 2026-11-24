import { writable, derived } from 'svelte/store';

// The Overview's sections in their default order; the page's "Customize" menu can reorder
// and hide them, and hide single host cards. Host card order is the shared host order
// (lib/hosts.js), the same one the sidebar uses.
export const OVERVIEW_WIDGETS = [
    { id: 'webapps', label: 'Web apps' },
    { id: 'attention', label: 'Updates, apps and backups' },
    { id: 'totals', label: 'Cluster totals' },
    { id: 'host', label: 'Host cards' },
    { id: 'tailscale', label: 'Tailscale' },
    { id: 'shortcuts', label: 'Shortcuts' },
    { id: 'compute', label: 'Compute pools' },
    { id: 'api-latency', label: 'API latency' },
    { id: 'uptime', label: 'Uptime checks' },
    { id: 'pihole', label: 'Pi-hole' },
    { id: 'machines', label: 'Machines' },
];
// pages the shortcuts section can link to; the Overview fills in each one's figure
export const SHORTCUTS = [
    { id: 'databases', label: 'Databases' }, { id: 'terminal', label: 'Terminal' }, { id: 'backups', label: 'Backups' },
    { id: 'updates', label: 'Updates' }, { id: 'apps', label: 'Apps' }, { id: 'logs', label: 'Logs' },
    { id: 'tailscale', label: 'Tailscale' }, { id: 'cloudflare', label: 'Cloudflare' }, { id: 'pihole', label: 'Pi-hole' },
    { id: 'endpoints', label: 'API endpoints' },
];
const SC_IDS = SHORTCUTS.map(x => x.id);
const IDS = OVERVIEW_WIDGETS.map(w => w.id);

// sections made of tiles, whose tiles can be hidden one by one
export const SECTION_TILES = {
    attention: [{ id: 'updates', label: 'Package updates' }, { id: 'apps', label: 'Apps' }, { id: 'backups', label: 'Backups' }],
    totals: [{ id: 'hosts', label: 'Hosts' }, { id: 'cpu', label: 'CPU' }, { id: 'mem', label: 'Memory' }, { id: 'disk', label: 'Storage' }],
};
// how many cluster tiles per row ('auto' follows the screen width)
export const COLS = ['auto', '1', '2', '3', '4'];

// { order, hidden, hidden_hosts }: kept in /api/prefs (overview_layout) so every device
// shows the same page, with a copy in this browser so it paints right away
const LOCAL = 'overview_layout';
const OLD = 'overview_hidden_widgets_v2';

function norm(l = {}) {
    // sections added since the layout was saved go in at their default place
    const order = (l.order || []).filter(id => IDS.includes(id));
    IDS.forEach((id, i) => {
        if (order.includes(id)) return;
        const before = IDS.slice(0, i).reverse().find(p => order.includes(p));
        order.splice(before ? order.indexOf(before) + 1 : 0, 0, id);
    });
    return { order, hidden: (l.hidden || []).filter(id => IDS.includes(id)), hidden_hosts: l.hidden_hosts || [],
        hidden_tiles: l.hidden_tiles || [], totals_cols: COLS.includes(l.totals_cols) ? l.totals_cols : 'auto',
        // sections at half width sit two to a row
        widths: Object.fromEntries(Object.entries(l.widths || {}).filter(([k, v]) => IDS.includes(k) && v === 'half')),
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
const update = (fn) => { let cur; layout.subscribe(v => cur = v)(); save(norm(fn(cur))); };
const toggle = (list, id) => list.includes(id) ? list.filter(x => x !== id) : [...list, id];

export const toggleWidget = (id) => update(l => ({ ...l, hidden: toggle(l.hidden, id) }));
export const toggleHostCard = (id) => update(l => ({ ...l, hidden_hosts: toggle(l.hidden_hosts, id) }));
export const toggleTile = (id) => update(l => ({ ...l, hidden_tiles: toggle(l.hidden_tiles, id) }));
export const setTotalsCols = (v) => update(l => ({ ...l, totals_cols: v }));
export const setWidth = (id, w) => update(l => ({ ...l, widths: { ...l.widths, [id]: w } }));
export const setShortcuts = (list) => update(l => ({ ...l, shortcuts: list }));
export const setWidgetOrder = (order) => update(l => ({ ...l, order }));
export const showAllWidgets = () => update(l => ({ ...l, hidden: [], hidden_hosts: [], hidden_tiles: [] }));
export const resetLayout = () => update(() => ({}));

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
