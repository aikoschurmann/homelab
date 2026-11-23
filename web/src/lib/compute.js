import { writable } from 'svelte/store';

// Compute pools (/api/compute): computers of the cluster used as one big machine.
// [{ name, python, packages, scheduler, port, nodes: { id: { ssh, tags, procs } },
//    running, counts: { cores, workers, hosts, processing, tasks }, op, jobs: { total, running } }]
export const pools = writable(null);

const toast = (m) => window.showToast?.(m);
const base = (name) => `/api/compute/pools/${encodeURIComponent(name)}`;

export async function api(url, opts = {}) {
    const j = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts })
        .then(r => r.json()).catch(e => ({ status: 'error', message: String(e) }));
    return j;
}

export async function fetchPools() {
    const j = await api('/api/compute/pools');
    if (j.status === 'success') pools.set(j.data);
}

export const getPool = async (name) => (await api(base(name))).data || null;
export const poolLive = async (name) => (await api(`${base(name)}/live`)).data || null;
export const poolMetrics = async (name, since = 0) => (await api(`${base(name)}/metrics?since=${since}`)).data || null;
export const candidates = async () => (await api('/api/compute/candidates')).data || [];
export async function sshCheck(ssh, host = null, via = undefined) {
    const j = await api('/api/compute/ssh-check', { method: 'POST', body: JSON.stringify({ ssh, host, via }) });
    return j.data || { ok: false, message: j.message };
}

// create / save: throws with the backend's message
async function must(url, opts) {
    const j = await api(url, opts);
    if (j.status !== 'success') throw new Error(j.message || 'That did not work');
    await fetchPools();
    return j.data;
}
export const createPool = (def) => must('/api/compute/pools', { method: 'POST', body: JSON.stringify(def) });
export const savePool = (name, def) => must(base(name), { method: 'PATCH', body: JSON.stringify(def) });
export const deletePool = (name) => must(base(name), { method: 'DELETE' });

// start (pool up: also applies changed settings) or stop: runs in the background on Arrakis
export async function poolOp(name, kind) {
    const j = await api(`${base(name)}/${kind}`, { method: 'POST' });
    if (j.status !== 'success') toast(j.message);
    await fetchPools();
    return j.status === 'success';
}

// jobs: `pool run <script>` in the pool's folder
export const listJobs = async (name) => (await api(`${base(name)}/jobs`)).data || [];
export const jobOutput = async (name, id, offset = 0) => (await api(`${base(name)}/jobs/${id}?offset=${offset}`)).data || null;
export async function jobLast(name, id, n = 4) {
    const last = (await api(`${base(name)}/jobs/${id}?tail=${n}`)).data?.last;
    return Array.isArray(last) ? last : last ? [String(last)] : [];   // lines, whatever the backend's version
}
export async function runJob(name, script, args = '') {
    const j = await api(`${base(name)}/jobs`, { method: 'POST', body: JSON.stringify({ script, args }) });
    if (j.status !== 'success') { toast(j.message); return null; }
    fetchPools();
    return j.data;
}
export async function stopJob(name, id) {
    const j = await api(`${base(name)}/jobs/${id}/stop`, { method: 'POST' });
    if (j.status !== 'success') toast(j.message);
}
export async function deleteJob(name, id) {
    const j = await api(`${base(name)}/jobs/${id}`, { method: 'DELETE' });
    if (j.status !== 'success') toast(j.message);
}

// the pool folder's files
export const listFiles = async (name) => (await api(`${base(name)}/files`)).data || [];
export async function readFile(name, path) {
    const j = await api(`${base(name)}/file?path=${encodeURIComponent(path)}`);
    if (j.status !== 'success') { toast(j.message); return null; }
    return j.data.text;
}
export async function writeFile(name, path, text) {
    const j = await api(`${base(name)}/file`, { method: 'PUT', body: JSON.stringify({ path, text }) });
    if (j.status !== 'success') toast(j.message);
    return j.status === 'success';
}
export async function removeFile(name, path) {
    const j = await api(`${base(name)}/file?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
    if (j.status !== 'success') toast(j.message);
    return j.status === 'success';
}

export const poolState = (p) => p?.op?.state === 'running' ? 'starting' : p?.running ? 'running' : 'stopped';
export const poolStateLabel = (p) => p?.op?.state === 'running' ? (p.op.kind === 'up' ? 'Starting' : 'Stopping') : p?.running ? 'Running' : 'Stopped';
export const JOB_PILL = { running: 'starting', done: 'running', failed: 'error', stopped: 'stopped', unknown: 'stopped' };
export const JOB_LABEL = { running: 'Running', done: 'Done', failed: 'Failed', stopped: 'Stopped', unknown: 'Unknown' };

// ---- a pool's readings, for the cards (Compute page, Overview) ----------------------------
// Fetches each running pool's new readings and keeps the last 10 minutes: { name: [reading] }
export async function updateReadings(list, readings) {
    let out = readings;
    for (const p of (list || []).filter(x => x.running)) {
        const have = out[p.name] || [];
        const d = await poolMetrics(p.name, have.length ? have[have.length - 1].t : Date.now() / 1000 - 600);
        if (d?.points?.length) {
            const fresh = d.points.filter(r => !have.length || r.t > have[have.length - 1].t);
            out = { ...out, [p.name]: [...have, ...fresh].filter(r => r.t > Date.now() / 1000 - 600) };
        }
    }
    return out;
}
// Throughput is in the job's own unit when it counts its work with pool.count() (e.g.
// "candidates"), else in tasks finished: one long task per core would otherwise read as ~0/s.
export function workUnit(rs = []) {
    for (let i = rs.length - 1; i >= Math.max(0, rs.length - 15); i--)
        for (const n of Object.values(rs[i].nodes)) if (n.unit) return n.unit;
    return null;
}
export const amount = (n, unit) => (n ? (unit ? n.work || 0 : n.done || 0) : 0);
export const unitLabel = (unit) => unit ? unit[0].toUpperCase() + unit.slice(1) : 'Tasks';

// Right now: cores busy of how many, throughput per second (last 10 s), and the
// history of cores busy for a strip
export function poolNow(p, rs = []) {
    const last = rs[rs.length - 1];
    const fresh = !!(p.running && p.op?.state !== 'running' && last && Date.now() / 1000 - last.t < 10);
    const sum = (r, k) => Object.values(r.nodes).reduce((a, n) => a + n[k], 0);
    const unit = workUnit(rs);
    const recent = rs.filter(r => last && r.t > last.t - 10);
    const rate = recent.length > 1 ? recent.slice(1).reduce((a, r) => a + Object.values(r.nodes).reduce((x, n) => x + amount(n, unit), 0), 0) / (recent[recent.length - 1].t - recent[0].t) : 0;
    // the scale: the cores the pool has now while it runs (old readings can be from a bigger or
    // differently split pool); when stopped or mid start, the most seen, so it doesn't jump
    const cap = fresh ? sum(last, 'cores') : rs.reduce((m, r) => Math.max(m, sum(r, 'cores')), p.counts?.cores || 0);
    // the strip spans what there is, from 1 minute up to 10
    const win = rs.length ? Math.min(600000, Math.max(60000, (last.t - rs[0].t) * 1000)) : 600000;
    return { fresh, busy: fresh ? sum(last, 'busy') : 0, cores: cap, rate, unit, win, pts: rs.map(r => [r.t * 1000, sum(r, 'busy')]) };
}
export const fmtRate = (v) => v < 10 ? v.toFixed(1) : String(Math.round(v));
// categorical colour slots (validated on the dark surface), assigned in host order
export const SLOTS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
