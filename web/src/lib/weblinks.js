import { writable, get } from 'svelte/store';

// Web UI shortcuts, kept in /api/prefs (web_links) so every device sees the same ones.
// key -> { url?, pinned?, off?, name? }. Service keys ('container:pihole', 'daemon:…') or
// 'custom:<id>' for a link that isn't a service (then name is required).
// A url may be ':8096/path', meaning "this port on whatever host the dashboard is open on":
// OrbStack forwards the VM's published ports to the Mac, so containers and Mac apps both
// answer there, over the LAN, Tailscale or localhost alike.
export const webLinks = writable({});

export async function loadWebLinks() {
    try {
        const j = await fetch('/api/prefs').then(r => r.json());
        if (j.status === 'success') webLinks.set(j.data?.web_links || {});
    } catch (e) {}
}

// Changes one key on top of the server's latest map, so another tab or device's edits survive
async function change(key, fn) {
    await loadWebLinks();
    const map = { ...get(webLinks) };
    const next = fn(map[key]);
    next ? map[key] = next : delete map[key];
    webLinks.set(map);
    try {
        await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ web_links: map }) });
    } catch (e) { window.showToast?.('Could not save the shortcut'); }
}

export const setLink = (key, patch) => change(key, (cur) => {
    const next = { ...(cur || {}), ...patch };
    Object.keys(next).forEach(k => (next[k] == null || next[k] === '' || next[k] === false) && delete next[k]);
    return Object.keys(next).length ? next : null;
});
export const removeLink = (key) => change(key, () => null);

// ---- guessing a service's web UI -----------------------------------------------------
const WEB_PORTS = [80, 443, 8080, 8443, 9000, 9443, 3000, 5000, 8000, 8096, 8123, 8181, 8384, 9090];
const NOT_WEB = [22, 53, 67, 123, 3306, 5432, 6379, 27017];
const PATHS = { pihole: '/admin/' };
// Mac apps don't report ports; the usual ones for apps people run
const APP_PORTS = [[/jellyfin/i, 8096], [/qbittorrent/i, 8080], [/plex/i, 32400, '/web'], [/sonarr/i, 8989], [/radarr/i, 7878], [/prowlarr/i, 9696]];

export function guessUrl(svc) {
    if (svc.kind === 'daemon') {
        const m = APP_PORTS.find(([re]) => re.test(svc.name || svc.id));
        return m ? `:${m[1]}${m[2] || '/'}` : null;
    }
    // "0.0.0.0:8181->80/tcp, [::]:8181->80/tcp" -> [{ host: 8181, inner: 80 }]
    const pub = [...(svc.ports || '').matchAll(/:(\d+)->(\d+)\/tcp/g)].map(x => ({ host: +x[1], inner: +x[2] }))
        .filter(p => !NOT_WEB.includes(p.inner));
    if (!pub.length) return null;
    const rank = (p) => { const i = WEB_PORTS.indexOf(p.inner); return i < 0 ? 99 : i; };
    // Portainer's 8000 is its agent tunnel, not the UI
    const best = [...pub].sort((a, b) => rank(a) - rank(b) || (a.inner === 8000) - (b.inner === 8000))[0];
    const tls = [443, 8443, 9443].includes(best.inner) ? 'https:' : '';
    const path = Object.entries(PATHS).find(([n]) => (svc.image || svc.name || '').includes(n))?.[1] || '/';
    return `${tls}:${best.host}${path}`;
}

// What to open: the saved url, else the guess, unless the guess was switched off
export function linkOf(links, svc) {
    const l = links[svc.key];
    if (l?.off) return null;
    return l?.url || guessUrl(svc);
}

// ':8096/' -> 'http://<this host>:8096/'; 'https::9443/' -> https on this host; full urls pass through
export function absUrl(u) {
    if (!u) return null;
    const m = u.match(/^(https?:)?:(\d+)(\/.*)?$/);
    if (m) return `${m[1] || 'http:'}//${location.hostname}:${m[2]}${m[3] || '/'}`;
    return /^[a-z]+:\/\//i.test(u) ? u : 'http://' + u;
}

// Overview tiles: pinned services that still exist, then custom links
export function pinnedLinks(links, services) {
    const out = [];
    for (const [key, l] of Object.entries(links)) {
        if (!l.pinned) continue;
        if (key.startsWith('custom:')) { if (l.url) out.push({ key, name: l.name || l.url, url: l.url, custom: true }); continue; }
        const svc = (services || []).find(s => s.key === key);
        const url = svc ? linkOf(links, svc) : l.url;
        if (url) out.push({ key, name: l.name || svc?.name || key.split(':').slice(1).join(':'), url, svc, running: svc ? svc.status === 'running' : null });
    }
    return out.sort((a, b) => a.name.localeCompare(b.name));
}

// one dialog for the whole app: editLink(svc) for a service, editLink() for a new custom link
export const editing = writable(null);
export const editLink = (svc = null, key = null) => editing.set({ svc, key: key || svc?.key || null });
