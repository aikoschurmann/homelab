import { writable } from 'svelte/store';

// The backend's route catalog (GET /api/endpoints), grouped; the API endpoints page and
// the sidebar's list of groups both read it
export const endpointGroups = writable(null);

export async function fetchEndpoints() {
    try {
        const j = await fetch('/api/endpoints').then(r => r.json());
        if (j.status === 'success') endpointGroups.set(j.data);
    } catch (e) {}
}
export const groupSlug = (g) => 'g-' + g.toLowerCase();
