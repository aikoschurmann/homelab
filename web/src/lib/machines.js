import { writable, get } from 'svelte/store';
import { refreshMachines } from './stores.js';
import { vmUrl, vmName } from './vmref.js';
export { vmRef, vmHost, vmName, vmBase, vmUrl } from './vmref.js';

const toast = (m) => window.showToast?.(m);

export async function api(url, opts = {}) {
    const r = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts })
        .then(r => r.json())
        .catch(e => ({ status: 'error', message: String(e) }));
    if (r.status !== 'success') toast(r.message || 'Request failed');
    return r;
}

// machine ref (see vmref.js) -> action in flight ('start' | 'stop' | 'restart' | 'delete' | 'join' | 'leave' | 'limits')
export const busy = writable({});
const setBusy = (name, v) => busy.update(b => ({ ...b, [name]: v }));

const DONE = { start: 'started', stop: 'stopped', restart: 'restarted', delete: 'deleted' };

export async function machineAction(name, action) {
    setBusy(name, action);
    const r = await api(vmUrl(name, `/${action}`), { method: 'POST' });
    setBusy(name, null);
    if (r.status === 'success') { toast(`${vmName(name)} ${DONE[action]}`); await refreshMachines(name); }
    return r.status === 'success';
}

export async function tailscaleJoin(name) {
    setBusy(name, 'join');
    const r = await api(vmUrl(name, '/tailscale/join'), { method: 'POST' });
    setBusy(name, null);
    if (r.status === 'success') { toast(r.message); refreshMachines(name); }
}

export async function tailscaleLeave(name) {
    setBusy(name, 'leave');
    const r = await api(vmUrl(name, '/tailscale/leave'), { method: 'POST' });
    setBusy(name, null);
    if (r.status === 'success') { toast(`${vmName(name)} left the tailnet`); refreshMachines(name); }
}

export async function shareMachine(name, keys = '') {
    setBusy(name, 'share');
    const r = await api(vmUrl(name, '/share'), { method: 'PUT', body: JSON.stringify({ keys }) });
    setBusy(name, null);
    if (r.status === 'success') { toast(r.message); refreshMachines(name); }
    return r.status === 'success';
}

export async function unshareMachine(name) {
    setBusy(name, 'unshare');
    const r = await api(vmUrl(name, '/share'), { method: 'DELETE' });
    setBusy(name, null);
    if (r.status === 'success') { toast(`${vmName(name)} is no longer shared`); refreshMachines(name); }
}

export async function saveLimits(name, cpu, memory_mib, disk_gib) {
    setBusy(name, 'limits');
    const r = await api(vmUrl(name, '/limits'), { method: 'PATCH', body: JSON.stringify({ cpu, memory_mib, disk_gib }) });
    setBusy(name, null);
    if (r.status === 'success') refreshMachines(name);
    return r.status === 'success';
}

export const tsLabel = (t) => ({ running: 'Connected', needs_login: 'Logged out', stopped: 'Not running', missing: 'Not joined' }[t?.state] || '—');
export const imageLabel = (img) => img ? `${img.distro} ${img.version}` : '—';
export const fmtBytes = (b) => b == null ? '—' : b >= 2 ** 30 ? (b / 2 ** 30).toFixed(2) + ' GB' : (b / 2 ** 20).toFixed(0) + ' MB';
export function fmtDuration(s) {
    if (s == null) return '—';
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
}

// ---- live usage ------------------------------------------------------------------
// The server samples every running machine every 5 s and keeps the last hour; /stats
// returns its latest sample from cache. A machine page loads the history, then polls
// /stats and appends each sample it hasn't seen yet.
const MAX_SAMPLES = 720;
export const samples = writable({});   // name -> [{ t, cpu, mem, memLimit, ... }]
export const latest = writable({});    // name -> last stats payload

export function startSampling(name, everyMs = 5000) {
    let stopped = false, timer = null;
    fetch(vmUrl(name, '/history')).then(r => r.json()).then(r => {
        if (stopped || r.status !== 'success') return;
        const hist = r.data.points.map(p => ({ t: p.t * 1000, cpu: p.cpu, mem: p.mem, memLimit: p.memLimit }));
        samples.update(s => {
            const last = hist.length ? hist[hist.length - 1].t : 0;
            const live = (s[name] || []).filter(p => p.t > last);
            return { ...s, [name]: [...hist, ...live].slice(-MAX_SAMPLES) };
        });
    }).catch(() => {});
    async function tick() {
        if (stopped) return;
        if (!document.hidden) {
            try {
                const r = await fetch(vmUrl(name, '/stats')).then(r => r.json());
                if (r.status === 'success' && !stopped) {
                    const d = r.data;
                    latest.update(l => ({ ...l, [name]: d }));
                    samples.update(s => {
                        const arr = s[name] || [];
                        const t = d.at * 1000;
                        if (arr.length && arr[arr.length - 1].t >= t) return s;
                        return { ...s, [name]: [...arr, { t, cpu: d.cpu_pct, mem: d.mem_bytes, memLimit: d.mem_limit_bytes }].slice(-MAX_SAMPLES) };
                    });
                }
            } catch (e) {}
        }
        if (!stopped) timer = setTimeout(tick, everyMs);
    }
    tick();
    return () => { stopped = true; clearTimeout(timer); };
}

export const getLatest = (name) => get(latest)[name];
