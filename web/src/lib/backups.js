import { writable } from 'svelte/store';

// Snapshots and schedule (GET /api/backups/details); shared by the Backups page and the sidebar.
// Each file carries its part's display name (`label`) from the backend.
export const backups = writable(null);

export async function fetchBackups() {
    try {
        const j = await fetch('/api/backups/details').then(r => r.json());
        if (j.status === 'success') backups.set(j.data);
    } catch (e) {}
}

export const snapLabel = (sec) => new Date(sec * 1000).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
