// Terminal tab helpers: window/pane actions, saved commands and the one-click shells on
// Infrastructure pages.
import { writable } from 'svelte/store';

const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json());
export const sessionUrl = (name, rest = '') => `/api/tmux/sessions/${encodeURIComponent(name)}${rest}`;
export const act = (name, body) => post(sessionUrl(name, '/act'), body);
export const sendLine = (name, text, enter = true) => post(sessionUrl(name, '/send'), { text, enter });

// start a session (or open it if it's already running) and go to its page
export async function launch({ name, target = 'mac', command = '', cwd = '' }) {
    const j = await post('/api/tmux/sessions', { name, target, command: command || undefined, cwd: cwd || undefined, reuse: true });
    if (j.status !== 'success') { window.showToast?.(j.message || 'Could not start the session'); return null; }
    if (j.message) window.showToast?.(j.message);
    window.location.hash = `#terminal/${j.session}`;
    return j.session;
}
// the "Shell" buttons on the Mac, machine and host pages: one session named "shell" per place
export const openShell = (where) => launch({ name: 'shell', target: where });

export const presets = writable([]);
export async function fetchPresets() {
    try { const j = await fetch('/api/tmux/presets').then(r => r.json()); if (j.status === 'success') presets.set(j.presets); } catch (e) {}
}
export async function savePresets(list) {
    const j = await fetch('/api/tmux/presets', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ presets: list }) }).then(r => r.json());
    if (j.status === 'success') presets.set(j.presets);
    else window.showToast?.(j.message || 'Could not save');
    return j.status === 'success';
}
