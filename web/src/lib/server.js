// This server: its name, OS and what it has installed, from /api/server. Loaded once in
// main.js before the app mounts, so `SN` is a plain constant everywhere (a rename reloads).
export const server = { name: 'Server', os: '', features: {}, setup_done: true };

export async function loadServer() {
    try {
        const j = await fetch('/api/server').then(r => r.json());
        if (j.status === 'success') Object.assign(server, j.data);
    } catch { /* offline: keep the defaults, the app shows its own connecting state */ }
    SN = server.name;
    return server;
}

export async function saveServer(changes) {
    const j = await fetch('/api/server', {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
    }).then(r => r.json());
    if (j.status !== 'success') throw new Error(j.message || 'Could not save');
    Object.assign(server, j.data);
    return j.data;
}

// the server's display name ("Arrakis"); ES live binding, set before anything renders
export let SN = server.name;
