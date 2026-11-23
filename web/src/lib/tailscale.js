import { SN } from './server.js';
import { writable, derived } from 'svelte/store';
import { Monitor, Smartphone, Users, Box } from 'lucide-svelte';
import AppleIcon from '../components/ui/AppleIcon.svelte';
import { hostIcon } from './hosts.js';

// The tailnet as the Mac sees it (GET /api/tailscale)
export const tailnet = writable(null);

export async function fetchTailnet() {
    try {
        const j = await fetch('/api/tailscale').then(r => r.json());
        if (j.status === 'success') tailnet.set(j.data);
    } catch (e) {}
}

// Devices of people a machine was shared with arrive as "device-of-shared-to-user"
export const isShared = (d) => d.name === 'device-of-shared-to-user' || d.hostname === 'device-of-shared-to-user';
export const isTagged = (d) => (d.tags || []).length > 0;
// shared devices have no name of their own; show whose they are (the part before the @)
export const displayName = (d) => isShared(d) ? (d.user ? d.user.split('@')[0] : 'Shared user') : d.name;
// owner label: you, a tag (machines joined with an auth key), or the person it is shared with
export function ownerOf(d, me) {
    if (isTagged(d)) return d.tags.join(', ');
    if (isShared(d)) return d.user || 'shared';
    return d.user === me ? 'You' : (d.user || '—');
}
// URL id of a device: its MagicDNS short name, or the IP for shared placeholders
export const deviceId = (d) => isShared(d) ? d.ip : d.name;

// which devices each filter keeps
export const KEEP = {
    all: () => true,
    online: (d) => d.online,
    mine: (d) => !isShared(d) && !isTagged(d),
    tagged: (d) => isTagged(d),
    shared: (d) => isShared(d),
};
export const tsCounts = derived(tailnet, ($t) => $t ? Object.fromEntries(Object.entries(KEEP).map(([k, f]) => [k, $t.devices.filter(d => !d.self && f(d)).length])) : null);

export const fmtBytes = (b) => !b ? '—' : b >= 2 ** 30 ? (b / 2 ** 30).toFixed(2) + ' GB' : b >= 2 ** 20 ? (b / 2 ** 20).toFixed(1) + ' MB' : (b / 1024).toFixed(0) + ' KB';
export function ago(iso, now = Date.now()) {
    if (!iso) return '—';
    const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
    return s < 60 ? 'just now' : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;
}
export const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' }) : '—';
export const PHONE_OS = ['iOS', 'Android', 'tvOS'];

// What a device is in the cluster: a host (its agent reports this Tailscale IP),
// an OrbStack machine on Arrakis, or neither. Gives the icon the sidebar tree uses for it.
export function clusterOf(d, hostList, machineList, arrakisModel = '') {
    if (d.self) return { kind: 'host', name: SN, href: '#infra/arrakis', icon: hostIcon(arrakisModel, 'macOS') };
    const h = (hostList || []).find(x => x.report?.ip === d.ip);
    if (h) return { kind: 'host', name: h.name, href: `#infra/${h.id}`, icon: hostIcon(h.report?.model, h.report?.os) };
    const m = (machineList || []).find(x => x.tailscale?.ip === d.ip);
    if (m) return { kind: 'machine', name: m.name, href: `#infra/vm-${m.name}`, icon: Box, m };
    return null;
}
export function deviceIcon(d, c) {
    if (c) return c.icon;
    if (isShared(d)) return Users;
    if (d.os === 'macOS' || d.os === 'tvOS') return AppleIcon;
    return PHONE_OS.includes(d.os) ? Smartphone : Monitor;
}
