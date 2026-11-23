import { writable } from 'svelte/store';

// Drives on Arrakis, from /api/storage/disks:
// [{ id, name, size, internal, protocol, ssd, ejectable, image, system, protected,
//    volumes: [{ id, name, format, size, mounted, mount_point, writable, used, free }] }]
export const disks = writable(null);
export const disksError = writable('');

export async function fetchDisks() {
    try {
        const j = await fetch('/api/storage/disks').then(r => r.json());
        if (j.status === 'success') { disks.set(j.data); disksError.set(''); }
        else disksError.set(j.message || 'Could not read the drives');
    } catch (e) { disksError.set('Could not reach the backend'); }
}

const toast = (m) => window.showToast?.(m);
async function post(url) {
    const j = await fetch(url, { method: 'POST' }).then(r => r.json()).catch(() => ({ status: 'error', message: 'Could not reach the backend' }));
    if (j.status !== 'success') toast(j.message || 'That did not work');
    await fetchDisks();
    return j.status === 'success';
}

export const ejectDisk = async (d) => (await post(`/api/storage/disks/${d.id}/eject`)) && toast(`${d.name} ejected. You can unplug it.`);
export const mountVolume = async (v) => (await post(`/api/storage/volumes/${v.id}/mount`)) && toast(`${v.name} mounted`);
export const unmountVolume = async (v) => (await post(`/api/storage/volumes/${v.id}/unmount`)) && toast(`${v.name} unmounted`);

// totals over mounted volumes; internal and external apart
export function storageTotals(list) {
    const vols = (list || []).flatMap(d => d.volumes.filter(v => v.mounted && v.size).map(v => ({ ...v, internal: d.internal })));
    const sum = (xs, k) => xs.reduce((a, v) => a + (v[k] || 0), 0);
    const ext = vols.filter(v => !v.internal), int = vols.filter(v => v.internal);
    return {
        size: sum(vols, 'size'), used: sum(vols, 'used'), free: sum(vols, 'free'),
        external: { size: sum(ext, 'size'), used: sum(ext, 'used'), free: sum(ext, 'free'), count: ext.length },
        internal: { size: sum(int, 'size'), used: sum(int, 'used'), free: sum(int, 'free') },
    };
}
