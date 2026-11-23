import { writable } from 'svelte/store';

// Outdated packages per computer (GET /api/updates); the Updates page polls it and the
// sidebar lists each computer under Updates from the same copy
export const updates = writable(null);

export async function fetchUpdates() {
    const j = await fetch('/api/updates').then(r => r.json());
    if (j.status !== 'success') throw new Error(j.message || 'Could not load updates');
    updates.set(j.data);
    return j.data;
}
