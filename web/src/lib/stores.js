import { vmHost, vmBase } from './vmref.js';
import { writable } from 'svelte/store';

// App-wide live state. App.svelte feeds `stats` and `uplink`; `endpoints` is the
// API-latency list the Overview polls.

export const stats = writable(null);
export const uplink = writable({ ok: true, method: 'HTTP', lastFetchAt: null, pollIntervalMs: 5000 });
export const endpoints = writable([]);
// breadcrumb labels pages register for their own ids, e.g. endpoint id -> "GET /vms"
export const crumbLabels = writable({});

// Connection state for the status pill: 'connecting' | 'live' | 'stale' | 'down'
export function uplinkState(u, now) {
    if (!u.ok) return 'down';
    if (!u.lastFetchAt) return 'connecting';
    const age = now - u.lastFetchAt;
    return age > Math.max(15000, u.pollIntervalMs * 3) ? 'stale' : 'live';
}

const EMPTY_HIST = () => Array.from({ length: 5 }, () => ({ latency: 0, status: 0 }));

export async function fetchEndpoints() {
    try {
        const [epJson, latJson] = await Promise.all([
            fetch('/api/endpoints').then(r => r.json()),
            fetch('/api/latency?limit=25').then(r => r.json()),
        ]);
        if (epJson.status !== 'success' || latJson.status !== 'success') return;
        const eps = [];
        for (const group of epJson.data) {
            for (const e of group.endpoints || []) {
                const records = latJson.data[`${e.method} ${e.path}`] || [];
                if (records.length > 0) {
                    const hist = [...records].reverse().slice(-5);
                    while (hist.length < 5) hist.unshift({ latency: 0, status: 0 });
                    e.history = hist;
                    e.status = records[0].status;
                    e.latency = records[0].latency;
                } else {
                    e.history = EMPTY_HIST();
                    e.status = null;
                    e.latency = null;
                }
                eps.push(e);
            }
        }
        endpoints.set(eps);
    } catch (e) {}
}

// OrbStack machines, the shared pool they draw from, and the host it is carved from
export const machines = writable(null);

export async function fetchMachines() {
    try {
        const j = await fetch('/api/vms').then(r => r.json());
        if (j.status === 'success') machines.set(j.data);
    } catch (e) {}
}

// Memory figures come and go as MiB; people read GB
export const gbFromMib = (mib) => mib == null ? '--' : (mib / 1024).toFixed(mib % 1024 ? 1 : 0) + ' GB';

// Hidden tabs don't poll; a tab coming back refreshes at once
export const visible = () => typeof document === 'undefined' || !document.hidden;

// Latest per-machine usage from the server's background sampler (cached, cheap to poll)
export const machineUsage = writable({});

export async function fetchMachineUsage() {
    try {
        const j = await fetch('/api/vms/usage').then(r => r.json());
        if (j.status === 'success') machineUsage.set(j.data.machines);
    } catch (e) {}
}

// Another host's OrbStack, when the dashboard manages it: host id -> the same payload as
// /api/vms (machines, jobs, pool, host, sharing…). Kept fresh by fetchHosts.
export const hostVms = writable({});
const vmFetchedAt = {};

export async function fetchHostVms(hid) {
    vmFetchedAt[hid] = Date.now();
    try {
        const j = await fetch(vmBase(hid)).then(r => r.json());
        hostVms.update(v => ({ ...v, [hid]: j.status === 'success' ? j.data : { error: j.message } }));
    } catch (e) {}
}
export const hostVmsStale = (hid, ms = 8000) => Date.now() - (vmFetchedAt[hid] || 0) > ms;

// refresh whichever host's machine list a machine (ref) is on
export const refreshMachines = (ref) => vmHost(ref) ? fetchHostVms(vmHost(ref)) : fetchMachines();
