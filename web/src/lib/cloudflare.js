import { writable, derived } from 'svelte/store';

// The zone, tunnels and DNS records as the saved API token sees them (GET /api/cloudflare)
export const cloudflare = writable(null);
export const cloudflareError = writable('');

export async function fetchCloudflare() {
    try {
        const j = await fetch('/api/cloudflare').then(r => r.json());
        if (j.status === 'success') { cloudflare.set(j.data); cloudflareError.set(''); }
        else cloudflareError.set(j.message || 'Cloudflare request failed');
    } catch (e) { cloudflareError.set('Could not reach the backend'); }
}

// Active = a connector is up; inactive = still exists but nothing is connected;
// deleted = removed, but Cloudflare still lists it for a while
export const isActive = (t) => !t.deleted && ['healthy', 'degraded'].includes(t.status);
export const KEEP = {
    all: (t) => !t.deleted,
    active: isActive,
    inactive: (t) => !t.deleted && !isActive(t),
    deleted: (t) => t.deleted,
};
// URL id: the name, or the id for a deleted one (an old tunnel may share a live one's name)
export const tunnelKey = (t) => t.deleted ? t.id : t.name;
// sidebar counts
export const cfCounts = derived(cloudflare, ($c) => $c?.logged_in ? {
    ...Object.fromEntries(Object.entries(KEEP).map(([k, f]) => [k, $c.tunnels.filter(f).length])),
    dns: $c.records.length,
    // an open tunnel sits under its filter in the sidebar
    tunnels: Object.fromEntries($c.tunnels.map(t => [tunnelKey(t), { label: t.name, parent: 'f-' + (t.deleted ? 'deleted' : isActive(t) ? 'active' : 'inactive') }])),
} : null);

// a shared machine's page: Sharing tab, on whichever host it lives
export const machineHref = (t) => `#infra/vm-${t.host ? encodeURIComponent(t.host) + '~' : ''}${encodeURIComponent(t.machine)}/sharing`;
export const colos = (t) => [...new Set(t.connections.map(c => c.colo.toUpperCase()))];
// the oldest open connection = how long the connector has been up
export const upSince = (t) => t.connections.map(c => c.opened_at).filter(Boolean).sort()[0] || null;
export const STATUS = {
    healthy: { state: 'running', label: 'Healthy' },
    degraded: { state: 'waiting', label: 'Degraded' },
    down: { state: 'error', label: 'Down' },
    inactive: { state: '', label: 'Inactive' },
};
