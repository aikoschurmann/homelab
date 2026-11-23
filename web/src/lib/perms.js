// Per-person permissions on shared machines (see cftunnel.py / share_policy.sh)
const KEYS = ['access', 'root', 'sudo', 'docker', 'net', 'forward', 'procs', 'cpu', 'mem_mib', 'pids', 'expires'];
const norm = (p) => JSON.stringify(KEYS.map(k => k === 'sudo' ? [...(p?.[k] || [])].sort() : (p?.[k] ?? null)));

/** The preset these permissions match exactly, or null when customised. */
export function presetOf(perms, schema) {
    // a preset with a relative expiry matches whatever date it produced
    return schema?.presets?.find(pr => pr.expires_days
        ? !!perms?.expires && norm({ ...pr.perms, expires: '' }) === norm({ ...perms, expires: '' })
        : norm(pr.perms) === norm(perms)) || null;
}

/** The permissions a preset gives someone added today (relative expiry becomes a date). */
export function applyPreset(pr) {
    const p = structuredClone(pr.perms);
    p.expires = pr.expires_days ? new Date(Date.now() + pr.expires_days * 864e5).toISOString().slice(0, 10) : '';
    return p;
}

export const NET_LABEL = { full: 'Full network', internet: 'Internet only', none: 'No network' };

/** One line for the keys table: "Developer" or "Custom · Some sudo · Internet only · 1 core". */
export function permSummary(perms, schema) {
    if (!perms) return '';
    const bits = [];
    if (perms.access === 'sftp') bits.push('Files only');
    bits.push({ none: 'No root', some: 'Some sudo', full: 'Full root' }[perms.root]);
    if (perms.docker) bits.push('Docker');
    bits.push(NET_LABEL[perms.net]);
    if (perms.cpu) bits.push(`${perms.cpu} ${perms.cpu === 1 ? 'core' : 'cores'}`);
    if (perms.mem_mib) bits.push(perms.mem_mib >= 1024 ? `${+(perms.mem_mib / 1024).toFixed(2)} GB` : `${perms.mem_mib} MB`);
    if (perms.expires) bits.push(`until ${perms.expires}`);
    return bits.filter(Boolean).join(' · ');
}

export const isRoot = (p) => p?.root === 'full' || !!p?.docker;
export const expired = (p) => !!p?.expires && p.expires < new Date().toISOString().slice(0, 10);
