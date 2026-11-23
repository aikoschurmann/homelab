// Infrastructure: one tree for everything that computes, and one route for each node.
//
//   #infra                      the whole cluster
//   #infra/arrakis              Arrakis, the server this dashboard runs on
//   #infra/arrakis/vm           the OrbStack VM on Arrakis (a tab): its machines, pool
//   #infra/orbstack/new         create a machine (on another host: #infra/orbstack~<host>/new)
//   #infra/vm-<ref>[/<tab>]     one machine; ref = its name, or <host>~<name> on another host
//   #infra/arrakis/apps         apps on macOS itself (a tab)
//   #infra/svc-<id>[/<tab>]     one service (a Mac app or a container)
//   #infra/<host>               another host, reporting through the agent
//   #infra/new                  add a host
//   #infra/pools[/new]          compute pools (make one)
//   #infra/pool-<name>[/<tab>]  one compute pool
//
// Machines, Services and Hosts used to be pages of their own; their old links
// still land on the right node.

import { vmRef, vmHost, vmName } from './vmref.js';
import { byOrder } from './hosts.js';

export const href = {
    root: '#infra',
    arrakis: '#infra/arrakis',
    vm: '#infra/arrakis/vm',
    newMachine: '#infra/orbstack/new',
    newMachineOn: (hid) => hid ? `#infra/orbstack~${encodeURIComponent(hid)}/new` : '#infra/orbstack/new',
    machine: (name, tab) => `#infra/vm-${encodeURIComponent(name)}${tab ? '/' + tab : ''}`,
    apps: '#infra/arrakis/apps',
    service: (id, tab) => `#infra/svc-${encodeURIComponent(id)}${tab ? '/' + tab : ''}`,
    host: (id) => `#infra/${encodeURIComponent(id)}`,
    newHost: '#infra/new',
    pools: '#infra/pools',
    newPool: '#infra/pools/new',
    pool: (name, tab) => `#infra/pool-${encodeURIComponent(name)}${tab ? '/' + tab : ''}`,
};

// a service's place in the tree: Mac apps under "apps", containers under their machine
export const serviceParent = (s) => s.host === 'Mac' ? 'apps' : 'vm-' + s.host;

// old (tab, section, sub) → new { tab: 'Infra', section, sub }, or null if not an old route
export function legacyRoute(tab, section, sub) {
    // the OrbStack VM and macOS apps are tabs of Arrakis now; their tree ids still route there
    if (tab === 'Infra' && section === 'orbstack' && sub !== 'new') return { tab: 'Infra', section: 'arrakis', sub: 'vm' };
    if (tab === 'Infra' && section === 'apps') return { tab: 'Infra', section: 'arrakis', sub: 'apps' };
    // the Hosts root is #infra itself
    if (tab === 'Infra' && section === 'hosts') return { tab: 'Infra', section: null, sub: null };
    if (tab === 'Infra' && section === 'arrakis' && sub === 'machines') return { tab: 'Infra', section: 'arrakis', sub: 'vm' };
    if (tab === 'Machines') {
        if (!section) return { tab: 'Infra', section: 'arrakis', sub: 'vm' };
        if (section === 'new') return { tab: 'Infra', section: 'orbstack', sub: 'new' };
        return { tab: 'Infra', section: 'vm-' + section, sub };
    }
    if (tab === 'Services') {
        if (!section) return { tab: 'Infra', section: null, sub: null };
        if (section === 'on-mac') return { tab: 'Infra', section: 'arrakis', sub: 'apps' };
        if (section.startsWith('on-')) return { tab: 'Infra', section: 'vm-' + section.slice(3), sub: 'workloads' };
        return { tab: 'Infra', section: 'svc-' + section, sub };
    }
    if (tab === 'Hosts') return { tab: 'Infra', section: section || null, sub: null };
    return null;
}
export const LEGACY_TABS = ['Machines', 'Services', 'Hosts'];

// The tree the sidebar shows. Every host and machine expands the same way — to its page
// tabs — so none is a dead-end leaf. Each node carries where it navigates: { section, sub }
// → #infra/<section>[/<sub>] ('overview' is the default tab, sub = null). Containers stay
// off the tree (a machine can hold dozens); they live on the machine's page and table.
const tabNode = (section, sub, label) => ({ id: section + '/' + (sub || 'overview'), label, kind: 'tab', section, sub: sub || null });
const MACHINE_TABS = [['workloads', 'Workloads'], ['metrics', 'Metrics'], ['networking', 'Networking'], ['sharing', 'Sharing'], ['settings', 'Settings']];
// a remote host's tabs: OrbStack VM and Storage only where its agent reports them
// a Mac lists its apps (as Arrakis does); Linux its workloads (services, containers, ports)
const isMacHost = (h) => /macos/i.test(h.report?.os || '');
const remoteTabs = (h) => [(h.caps?.orbstack || h.vms) && ['vm', 'OrbStack VM'], isMacHost(h) ? ['apps', 'macOS apps'] : ['workloads', 'Workloads'], h.caps?.storage != null && ['storage', 'Storage'], ['metrics', 'Metrics'], ['settings', 'Settings']].filter(Boolean);

const POOL_TABS = [['jobs', 'Jobs'], ['files', 'Files'], ['settings', 'Settings']];

export function tree(machineList, hostList, order = [], poolList = null) {
    // The host/machine row itself IS Overview (click it to select it); its children are the
    // other tabs, so there's no redundant "Overview" child stealing the highlight.
    const machineNode = (m, hid = null) => {
        const sec = 'vm-' + vmRef(hid, m.name);
        return {
            id: sec, label: m.name, kind: 'machine', section: sec, sub: null,
            state: m.state === 'running' ? 'running' : 'stopped',
            children: MACHINE_TABS.map(([s, l]) => tabNode(sec, s, l)),
        };
    };
    const arrakis = { id: 'arrakis', label: 'Arrakis', kind: 'host', section: 'arrakis', sub: null, state: 'running', children: [
        { id: 'orbstack', label: 'OrbStack VM', kind: 'vm', section: 'arrakis', sub: 'vm', children: (machineList || []).map((m) => machineNode(m)) },
        { id: 'apps', label: 'macOS apps', kind: 'apps', section: 'arrakis', sub: 'apps' },
        tabNode('arrakis', 'storage', 'Storage'),
        tabNode('arrakis', 'metrics', 'Metrics'),
        tabNode('arrakis', 'settings', 'Settings'),
    ] };
    const remote = (h) => ({
        id: h.id, label: h.name, kind: 'host', section: h.id, sub: null, state: h.online ? 'running' : 'stopped',
        // a managed host's OrbStack unfolds into its machines, as Arrakis's does
        children: remoteTabs(h).map(([s, l]) => s === 'vm' && h.vms?.machines
            ? { ...tabNode(h.id, s, l), kind: 'vm', children: h.vms.machines.map(m => machineNode(m, h.id)) }
            : tabNode(h.id, s, l)),
    });
    // One "Hosts" root (the cluster, #infra) that every host falls under.
    const roots = [{ id: 'hosts', label: 'Hosts', kind: 'group', section: null, sub: null, children: byOrder([arrakis, ...(hostList || []).map(remote)], order) }];
    // compute pools: several of those hosts used as one machine
    if (poolList) roots.push({ id: 'compute', label: 'Compute', kind: 'group', section: 'pools', sub: null, children: poolList.map(p => ({
        id: 'pool-' + p.name, label: p.name, kind: 'pool', section: 'pool-' + p.name, sub: null, state: p.running ? 'running' : 'stopped',
        children: POOL_TABS.map(([s, l]) => tabNode('pool-' + p.name, s, l)),
    })) });
    return roots;
}

// Node-id chain root→active leaf, for the sidebar's highlight and auto-unfold. Matches the
// deepest node whose (section, sub) is the active route; a service (off-tree) highlights its
// host/machine.
export function treeActivePath(section, sub, machineList, hostList, serviceList, poolList = null) {
    // a pool's run and file pages (job-<id>, file-<path>) sit under its Jobs and Files tabs
    const want = sub?.startsWith('job-') ? 'jobs' : sub?.startsWith('file-') ? 'files' : sub?.startsWith('person-') ? 'sharing' : sub || null;
    let best = null;
    const walk = (nodes, trail) => {
        for (const n of nodes) {
            const here = [...trail, n.id];
            if (n.section === section && (n.sub || null) === want) best = here;
            if (n.children) walk(n.children, here);
        }
    };
    walk(tree(machineList, hostList, [], poolList), []);
    if (best) return best;
    if ((section || '').startsWith('svc-')) {
        const s = (serviceList || []).find(x => x.id === section.slice(4));
        if (s) return serviceParent(s) === 'apps'
            ? treeActivePath('arrakis', 'apps', machineList, hostList, serviceList)
            : treeActivePath(serviceParent(s), null, machineList, hostList, serviceList);
    }
    return [];
}

// labels for nodes that aren't in the sidebar tree
function extraLabel(section, serviceList) {
    if (section === 'new') return 'Add host';
    if (section === 'pools') return 'Compute';
    if (section?.startsWith('pool-')) return section.slice(5);
    if (section?.startsWith('svc-')) {
        const id = section.slice(4);
        return (serviceList || []).find(s => s.id === id)?.name || id;
    }
    if (section?.startsWith('vm-')) return vmName(section.slice(3));
    if (section?.startsWith('orbstack')) return 'New machine';
    return section;
}

// A tab of Arrakis that stands for a tree node, so the sidebar can highlight it
export const nodeOf = (section, sub) => section === 'arrakis' && sub === 'vm' ? 'orbstack' : section === 'arrakis' && sub === 'apps' ? 'apps' : section;

// Root-to-node chain for breadcrumbs and for unfolding the sidebar: [{ id, label }]
export function pathOf(section, machineList, hostList, serviceList, poolList = null) {
    if (!section) return [];
    const t = tree(machineList, hostList, [], poolList || []);
    const walk = (nodes, trail) => {
        for (const n of nodes) {
            const here = [...trail, { id: n.id, label: n.label }];
            if (n.id === section) return here;
            const found = n.children && walk(n.children, here);
            if (found) return found;
        }
        return null;
    };
    let p = walk(t, []);
    if (p) return p;
    if (section.startsWith('svc-')) {
        const s = (serviceList || []).find(x => x.id === section.slice(4));
        const up = s ? pathOf(serviceParent(s), machineList, hostList, serviceList) : [];
        return [...up, { id: section, label: extraLabel(section, serviceList) }];
    }
    // a machine or the create page under its host's OrbStack VM node
    const hid = section.startsWith('vm-') ? vmHost(section.slice(3)) : section.startsWith('orbstack~') ? section.slice(9) : null;
    if (section.startsWith('vm-') || section.startsWith('orbstack')) return [...pathOf(hid ? hid + '/vm' : 'orbstack', machineList, hostList, serviceList), { id: section, label: extraLabel(section) }];
    return [{ id: section, label: extraLabel(section, serviceList) }];
}
