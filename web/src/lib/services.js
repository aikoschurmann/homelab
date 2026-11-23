import { writable, derived } from 'svelte/store';
import { machines } from './stores.js';

// Host daemons and Docker containers as one list. Each item:
// { key: 'daemon:dashboard', kind: 'daemon' | 'container', host, id, name, status, mem_mb, cpu, ... }
const raw = writable({ daemons: null, containers: null, at: 0 });

// host: 'Mac' for daemons, the dashboard machine's name for containers
export const services = derived([raw, machines], ([$r, $m]) => {
    if (!$r.daemons && !$r.containers) return null;
    const vm = $m?.dashboard_vm || 'vm';
    return [
        ...($r.daemons || []).map(d => ({ ...d, raw: d, kind: 'daemon', key: 'daemon:' + d.id, cpu: +d.cpu || 0, host: 'Mac' })),
        ...($r.containers || []).map(c => ({ ...c, raw: c, kind: 'container', key: 'container:' + c.id, cpu: +c.cpu || 0, host: vm })),
    ].map(s => ({ ...s, startedAt: s.status === 'running' && s.uptime_seconds != null ? $r.at - s.uptime_seconds * 1000 : null }));
});

export async function fetchServices() {
    try {
        const [d, c] = await Promise.all([
            fetch('/api/host/daemons').then(r => r.json()),
            fetch('/api/vm/containers').then(r => r.json()),
        ]);
        raw.set({
            daemons: d.status === 'success' ? d.data || [] : null,
            containers: c.status === 'success' ? c.data || [] : null,
            at: Date.now(),
        });
    } catch (e) {}
}

// A service by its URL id; daemon ids win if a container shares the name
export const findService = (list, id) => (list || []).find(s => s.kind === 'daemon' && s.id === id) || (list || []).find(s => s.id === id);

// 24 h availability: 48 half-hour slots per service key
export const uptime = writable({ bucket_seconds: 1800, services: {} });
export async function fetchUptime() {
    try {
        const j = await fetch('/api/services/uptime?hours=24&buckets=48').then(r => r.json());
        if (j.status === 'success') uptime.set(j.data);
    } catch (e) {}
}

// ---- actions ------------------------------------------------------------------------
// key -> { act, state: 'running' | 'done' | 'error' }
export const actions = writable({});
const setAction = (key, v) => actions.update(a => { const n = { ...a }; v ? n[key] = v : delete n[key]; return n; });
const DONE = { start: 'started', stop: 'stopped', restart: 'restarted' };

export function serviceAction(svc, act) {
    const url = svc.kind === 'daemon'
        ? `/api/services/daemons/action/${encodeURIComponent(svc.id)}/${act}`
        : `/api/services/containers/action/${encodeURIComponent(svc.id)}/${act}`;
    setAction(svc.key, { act, state: 'running' });
    const es = new EventSource(url);
    let settled = false;
    const finish = (ok) => {
        settled = true;
        es.close();
        setAction(svc.key, ok ? null : { act, state: 'error' });
        window.showToast?.(ok ? `${svc.name} ${DONE[act]}` : `${svc.name}: ${act} failed`);
        fetchServices();
        if (!ok) setTimeout(() => setAction(svc.key, null), 4000);
    };
    es.onmessage = (e) => {
        try {
            const d = JSON.parse(e.data);
            if (d.status === 'done') finish(true);
            else if (d.status === 'error') finish(false);
        } catch (err) {}
    };
    es.onerror = () => { if (!settled) finish(false); };
}

export const BUSY_LABEL = { start: 'Starting', stop: 'Stopping', restart: 'Restarting' };

export function fmtUptime(ms) {
    if (ms == null) return '—';
    const s = Math.max(0, Math.floor(ms / 1000));
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : m ? `${m}m ${s % 60}s` : `${s}s`;
}
export const fmtMb = (mb) => mb == null ? '—' : mb >= 1024 ? (mb / 1024).toFixed(2) + ' GB' : mb.toFixed(mb >= 100 ? 0 : 1) + ' MB';
export const fmtPct = (p) => p == null ? '—' : p === 100 ? '100%' : p.toFixed(p >= 99 ? 2 : 1) + '%';
