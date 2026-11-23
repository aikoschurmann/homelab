import { SN } from './server.js';
import { groupSlug } from './endpoints.js';
import { Activity, Eye, Boxes, Database, Box, Archive, Terminal, Settings, Network, Server, Gauge, Cloud, Globe, ScrollText, PackageCheck, Store } from 'lucide-svelte';

// Sidebar tree. A child with `el` is a section of its page (the element id it scrolls
// to); a child with el: null is a page of its own (id '' = the tab's main page).
// Machines, Services and Tailscale add entries at runtime, and whichever item page is
// open (a service, a device, a database…) is shown nested under its parent entry.
const sec = (id, label) => ({ id, label, el: `sec-${id}` });
const page = (id, label) => ({ id, label, el: null });

export const NAV = [
    { items: [
        { tab: 'Overview', icon: Activity },
    ] },
    // the sidebar draws this group as the tree from lib/infra.js
    { label: 'Infrastructure', tree: true, items: [
        { tab: 'Infra', label: 'Infrastructure', icon: Server },
    ] },
    // one flat group: each is a page of its own (filters and tabs live on the page)
    { label: 'Tools', items: [
        // parent: the sidebar folds these into one entry; pages: its tabs show under it (filters stay on the page)
        { tab: 'Tools', label: 'Network tools', icon: Gauge, parent: 'Network', pages: true, children: [page('', 'Checks'), page('uptime', 'Uptime'), page('pihole', 'Pi-hole'), page('speed', 'Speed test'), page('computers', 'Computers'), page('api', 'API health')] },
        { tab: 'Tailscale', icon: Network, parent: 'Network', pages: true, children: [page('', 'Devices'), page('ping', 'Ping'), page('people', 'People'), page('server', 'This server')] },
        { tab: 'Cloudflare', icon: Cloud, parent: 'Network', pages: true, children: [page('', 'Tunnels'), page('dns', 'DNS records')] },
        // sub: its children show in the sidebar too (other items keep theirs on the page)
        { tab: 'Databases', icon: Database, sub: true, children: [page('', 'All databases')] },
        { tab: 'Backups', icon: Archive, sub: true, children: [page('', 'Snapshots'), page('coverage', "What's covered"), page('runs', 'Runs')] },
        { tab: 'Apps', icon: Store, sub: true, children: [page('', 'Catalogue'), page('installed', 'Installed')] },
        { tab: 'Terminal', icon: Terminal, sub: true, children: [page('', 'Sessions'), page('saved', 'Saved commands')] },
        // its groups are listed on the page itself (they come from the backend's route list)
        { tab: 'Endpoints', label: 'API endpoints', icon: Eye, sub: true, children: [page('', 'All endpoints')] },
        { tab: 'Updates', icon: PackageCheck, sub: true, children: [page('', 'All computers')] },
        { tab: 'Logs', icon: ScrollText },
    ] },
    // pinned to the bottom of the sidebar
    { footer: true, items: [
        { tab: 'Settings', icon: Settings, children: [
            page('', 'General'),
            page('alerts', 'Alerts'),
            page('backups', 'Backups'),
            page('sharing', 'Sharing'),
            page('access', 'Access'),
            page('data', 'Data'),
            page('integrations', 'Integrations'),
            page('hosts', 'Hosts & machines'),
        ] },
    ] },
];

export const TABS = NAV.flatMap(g => g.items.map(i => i.tab));
// old pages, now nodes of Infrastructure (lib/infra.js maps their routes)
export const ALL_TABS = [...TABS, 'Machines', 'Services', 'Hosts'];
export const tabLabel = (tab) => NAV.flatMap(g => g.items).find(i => i.tab === tab)?.label || tab;

// Hosts: one entry per host that reports through the agent
export const hostChildren = (list) => [{ id: 'arrakis', label: SN, el: null, state: 'running', sep: true },
    ...(list || []).map(h => ({ id: h.id, label: h.name, el: null, state: h.online ? 'running' : 'stopped' }))];

export const machineChildren = (list) => (list || []).map((m, i) => ({ id: m.name, label: m.name, el: null, state: m.state, sep: i === 0 }));

// Services: one entry per host (route #services/on-<host>), not one per service
export const hostSection = (host) => 'on-' + host.toLowerCase();
export function serviceChildren(list) {
    const hosts = [];
    for (const s of list || []) {
        let h = hosts.find(x => x.host === s.host);
        if (!h) hosts.push(h = { host: s.host, total: 0, down: 0 });
        h.total++;
        if (s.status !== 'running') h.down++;
    }
    return hosts.map((h, i) => ({ id: hostSection(h.host), label: h.host === 'Mac' ? 'On the Mac' : `On ${h.host}`, el: null, count: h.down ? `${h.total - h.down}/${h.total}` : h.total, warn: h.down > 0, sep: i === 0 }));
}

// Tailscale: one entry per device filter (route #tailscale/f-<filter>)
export const TS_FILTERS = [
    { id: 'online', label: 'Online' },
    { id: 'mine', label: 'My devices' },
    { id: 'tagged', label: 'Tagged' },
    { id: 'shared', label: 'Shared' },
];
export const tailscaleChildren = (counts) => counts ? TS_FILTERS.map((f, i) => ({ id: 'f-' + f.id, label: f.label, el: null, count: counts[f.id], sep: i === 0 })) : [];

// Cloudflare: tunnel filters (route #cloudflare/f-<filter>), then DNS records
export const CF_FILTERS = [
    { id: 'active', label: 'Active' },
    { id: 'inactive', label: 'Inactive' },
    { id: 'deleted', label: 'Deleted' },
];
export const cloudflareChildren = (counts) => counts ? [
    ...CF_FILTERS.map((f, i) => ({ id: 'f-' + f.id, label: f.label, el: null, count: counts[f.id], sep: i === 0 })),
    { id: 'dns', label: 'DNS records', el: null, count: counts.dns, sep: true },
] : [];

// Databases: each one, under a heading for where it lives (the Mac, then each machine)
export function databaseChildren(list) {
    let last = null;
    return (list || []).map(d => {
        const where = d.machine ? (d.host ? `${d.machine} on ${d.host_name}` : d.machine) : 'On the Mac';
        const item = { id: d.id, label: d.name, el: null, heading: where !== last ? where : null, sep: where !== last };
        last = where;
        return item;
    });
}

// Backups: every kept snapshot, newest first
export function backupChildren(details) {
    return (details?.snapshots || []).map((s, i) => ({
        id: s.timestamp, el: null, heading: i === 0 ? 'Kept' : null, sep: i === 0, warn: s.incomplete, count: s.incomplete ? 'failed' : null,
        label: new Date(s.created * 1000).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }),
    }));
}

// Updates: one entry per computer, with how many packages are waiting
export const updateChildren = (data) => (data?.targets || []).map((t, i) => ({ id: t.id, label: t.name, el: null, count: t.packages?.length || null, sep: i === 0 }));

// API endpoints: one entry per group (route #endpoints/g-<group>)
export const endpointChildren = (groups) => (groups || []).map((g, i) => ({ id: groupSlug(g.name), label: g.name, el: null, count: g.endpoints.length, sep: i === 0 }));

// The open item page (a service, device, database, snapshot, session) as a nested
// entry under the entry it belongs to, so the sidebar always shows where you are
function current(tab, section, kids, serviceList, cfCounts, epGroups) {
    if (!section || kids.some(c => c.id === section) || /^(f-|on-)/.test(section)) return kids;
    let parent = '', label = section;
    if (tab === 'Services') {
        const s = (serviceList || []).find(x => x.id === section);
        if (s) { parent = hostSection(s.host); label = s.name; }
    } else if (tab === 'Cloudflare') {
        const t = cfCounts?.tunnels?.[section];
        if (t) { parent = t.parent; label = t.label; }
    } else if (tab === 'Endpoints') {
        // a group (g-…) reads as its name; an endpoint as its path
        const grp = (epGroups || []).find(x => groupSlug(x.name) === section);
        const g = (epGroups || []).find(x => x.endpoints.some(e => e.id === section));
        const e = g?.endpoints.find(e => e.id === section);
        if (grp) label = grp.name;
        else if (e) { parent = groupSlug(g.name); label = e.path.replace(/^\/api/, ''); }
    } else if (tab === 'Terminal') {
        label = section.split(':').slice(1).join(':');
    } else if (tab === 'Backups') {
        label = section.replace(/^\d{4}-(\d\d)-(\d\d)_(\d\d)-(\d\d)-\d\d$/, '$2/$1 $3:$4');
    } else if (!['Tailscale', 'Cloudflare', 'Databases', 'Endpoints'].includes(tab)) {
        return kids;
    }
    const at = kids.findIndex(c => c.id === parent);
    const item = { id: section, label, el: null, nested: true };
    return at < 0 ? [...kids, item] : [...kids.slice(0, at + 1), item, ...kids.slice(at + 1)];
}

// Children of a tab, with live machines, services, tailnet counts and the open item
export function childrenOf(tab, machineList, serviceList, tsCounts, hostList, section = null, cfCounts = null, dbList = null, backupList = null, epGroups = null, updList = null) {
    const item = NAV.flatMap(g => g.items).find(i => i.tab === tab);
    let kids = item?.children || [];
    if (tab === 'Hosts') kids = [...kids, ...hostChildren(hostList)];
    if (tab === 'Machines') kids = [...kids, ...machineChildren(machineList)];
    if (tab === 'Services') kids = [...kids, ...serviceChildren(serviceList)];
    if (tab === 'Tailscale') kids = [...kids, ...tailscaleChildren(tsCounts)];
    if (tab === 'Cloudflare') kids = [...kids, ...cloudflareChildren(cfCounts)];
    if (tab === 'Databases') kids = [...kids, ...databaseChildren(dbList)];
    // Backups' snapshots and the API groups are listed on their pages; the sidebar stays at the pages
    if (tab === 'Updates') kids = [...kids, ...updateChildren(updList)];
    return current(tab, section, kids, serviceList, cfCounts, epGroups);
}

// a tab's first page ('' id), e.g. Terminal → Sessions, for the breadcrumb on the tab itself
export const firstPage = (tab) => { const c = NAV.flatMap(g => g.items).find(x => x.tab === tab)?.children; return c?.length > 1 && c[0].id === '' ? c[0].label : null; };
export const groupOf = (tab) => { const i = NAV.flatMap(g => g.items).find(x => x.tab === tab); return i?.parent || NAV.find(g => g.items.includes(i))?.label; };
export const PARENTS = { Network: { label: 'Network', icon: Globe } };
// a group's items with each parent's members folded into one { parent, items } entry, in place of the first
export function foldParents(items) {
    const out = [];
    for (const i of items) {
        if (!i.parent) { out.push(i); continue; }
        let p = out.find(x => x.parent === i.parent);
        if (!p) out.push(p = { parent: i.parent, tab: 'parent:' + i.parent, ...PARENTS[i.parent], items: [] });
        p.items.push(i);
    }
    return out;
}
