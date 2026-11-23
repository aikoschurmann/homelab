import { writable } from 'svelte/store';

// Every database the dashboard can browse (GET /api/databases); the Databases page and the
// sidebar share it, so a fresh copy or rescan shows in both
export const databases = writable(null);

export async function fetchDatabases(refresh = false) {
    const j = await fetch('/api/databases' + (refresh ? '?refresh=1' : '')).then(r => r.json());
    if (j.status !== 'success') throw new Error(j.message || 'Could not list databases');
    databases.set(j.data);
    return j.data;
}
