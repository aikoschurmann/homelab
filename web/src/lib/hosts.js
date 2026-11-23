import { writable, get } from 'svelte/store';
import { hostVms, fetchHostVms, hostVmsStale } from './stores.js';
import { Server } from 'lucide-svelte';
import AppleIcon from '../components/ui/AppleIcon.svelte';
import RaspberryPiIcon from '../components/ui/RaspberryPiIcon.svelte';

// Other computers in the cluster, each reporting through the Arrakis agent.
// Arrakis itself is not in this list: its figures come from the dashboard's own stats.
// { id, name, added, online, last_seen, report: { os, cores, cpu_pct, mem_used, mem_total, disk_used, disk_total, uptime_secs, ip, containers } }
export const hosts = writable(null);

export async function fetchHosts() {
    try {
        const j = await fetch('/api/hosts').then(r => r.json());
        if (j.status === 'success') {
            hosts.set(withVms(j.data.hosts, get(hostVms)));
            if (j.data.arrakis?.model) arrakisModel.set(j.data.arrakis.model);
            for (const h of j.data.hosts) if (orbManaged(h) && hostVmsStale(h.id)) fetchHostVms(h.id);
        }
    } catch (e) {}
}

// the dashboard manages this host's OrbStack (switched on, agent 6 connected)
export const orbManaged = (h) => !!(h?.orb_manage && h?.rpc);
// each host carries its OrbStack machine list (or null) as h.vms, for the tree and pages
const withVms = (list, vms) => (list || []).map(h => ({ ...h, vms: orbManaged(h) ? vms[h.id] || null : null }));
hostVms.subscribe(v => hosts.update(list => list && withVms(list, v)));

export async function setOrbManage(id, on) {
    const j = await fetch(`/api/hosts/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ orb_manage: on }) }).then(r => r.json());
    if (j.status !== 'success') throw new Error(j.message || 'Could not change that');
    await fetchHosts();
}

export async function addHost(name) {
    const j = await fetch('/api/hosts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }).then(r => r.json());
    if (j.status !== 'success') throw new Error(j.message || 'Could not add the host');
    await fetchHosts();
    return j.data;
}

export async function removeHost(id) {
    const j = await fetch(`/api/hosts/${encodeURIComponent(id)}`, { method: 'DELETE' }).then(r => r.json());
    if (j.status !== 'success') throw new Error(j.message || 'Could not remove the host');
    await fetchHosts();
}

export async function installCommand(id) {
    const j = await fetch(`/api/hosts/${encodeURIComponent(id)}/install`).then(r => r.json());
    return j.status === 'success' ? j.data : null;
}

// a host's state for StatusPill: never reported yet, reporting, or gone quiet
export const hostState = (h) => h.online ? 'running' : h.last_seen ? 'offline' : 'waiting';
export const hostStateLabel = (h) => h.online ? 'Online' : h.last_seen ? 'Offline' : 'Waiting for agent';

const trim1 = (v) => String(+v.toFixed(1));
// memory in binary GB (16 GB of RAM), disk in decimal GB like df and Finder (245 GB)
export const fmtGb = (b) => b == null ? '—' : b >= 2 ** 40 ? trim1(b / 2 ** 40) + ' TB' : (b >= 100 * 2 ** 30 ? (b / 2 ** 30).toFixed(0) : trim1(b / 2 ** 30)) + ' GB';
export const fmtDisk = (b) => b == null ? '—' : b >= 1e12 ? trim1(b / 1e12) + ' TB' : (b / 1e9).toFixed(0) + ' GB';

// ---- icon by hardware model ------------------------------------------------------------

// Arrakis's model ("Mac mini"), from /api/hosts
export const arrakisModel = writable('');
// Brand logos for known hardware: any Mac → Apple, "Raspberry Pi …" → Raspberry Pi; anything else → server
export function hostIcon(model, os) {
    const m = model || '';
    if (/\bi?mac/i.test(m) || /macos/i.test(os || '')) return AppleIcon;
    if (/raspberry pi/i.test(m)) return RaspberryPiIcon;
    return Server;
}

// ---- actions: queued on Arrakis, run by the host's agent on its next report (agent 4+) ----

export const ACTIONS_FROM = 4;
export const canAct = (h) => +(h?.report?.agent || 0) >= ACTIONS_FROM;

const VERB_LABEL = {
    'service-start': 'Start', 'service-stop': 'Stop', 'service-restart': 'Restart',
    'container-start': 'Start', 'container-stop': 'Stop', 'container-restart': 'Restart',
    'vm-start': 'Start', 'vm-stop': 'Stop', 'vm-restart': 'Restart', 'disk-eject': 'Eject', 'volume-mount': 'Mount',
    'reboot': 'Reboot', 'update-agent': 'Update agent',
};
export const actionLabel = (a) => a.target ? `${VERB_LABEL[a.verb] || a.verb} ${a.target}` : VERB_LABEL[a.verb] || a.verb;

export async function queueAction(id, verb, target = '') {
    const j = await fetch(`/api/hosts/${encodeURIComponent(id)}/actions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ verb, target }) }).then(r => r.json());
    if (j.status !== 'success') throw new Error(j.message || 'Could not queue that');
    return j.data;
}

export async function fetchActions(id) {
    try { const j = await fetch(`/api/hosts/${encodeURIComponent(id)}/actions`).then(r => r.json()); return j.status === 'success' ? j.data : []; } catch (e) { return []; }
}

// Drives and OrbStack machines, from the inventory agent 5 sends every minute
// (null until the host has reported one, or when it has no OrbStack)
async function getData(url) {
    try { const j = await fetch(url).then(r => r.json()); return j.status === 'success' ? j.data : null; } catch (e) { return null; }
}
export const hostStorage = (id) => getData(`/api/hosts/${encodeURIComponent(id)}/storage`);
export const hostMachines = (id) => getData(`/api/hosts/${encodeURIComponent(id)}/machines`);
export const INVENTORY_FROM = 5;

// The order hosts are listed in (sidebar tree, Overview), as ids including 'arrakis'.
// Kept in /api/prefs (host_order) so every device shows the same order.
export const hostOrder = writable([]);
export async function fetchHostOrder() {
    try {
        const j = await fetch('/api/prefs').then(r => r.json());
        if (j.status === 'success' && Array.isArray(j.data?.host_order)) hostOrder.set(j.data.host_order);
    } catch (e) {}
}
export async function saveHostOrder(ids) {
    hostOrder.set(ids);
    try { await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ host_order: ids }) }); } catch (e) {}
}
// items sorted by the saved order; ones it doesn't name yet keep their place at the end
export function byOrder(items, order, id = (x) => x.id) {
    const pos = new Map((order || []).map((k, i) => [k, i]));
    return items.map((x, i) => [x, i]).sort(([a, i], [b, j]) => (pos.get(id(a)) ?? 1e6 + i) - (pos.get(id(b)) ?? 1e6 + j)).map(([x]) => x);
}
