import { SN } from './server.js';
// Every setting in the dashboard, wherever it lives, for the ⌘K box. Each entry opens its
// page and highlights the row: `label` is the row's (or card's) label as the page shows it,
// `kw` adds words people might type instead.

const G = (title, where, hash, label, kw = '') => ({ title, where, hash, label: label || title, kw });

const GLOBAL = [
    G('Theme', 'Settings → General', '#settings', 'Appearance', 'dark light colours'),
    G('Accent colour', 'Settings → General', '#settings', 'Accent', 'color'),
    G('Text size', 'Settings → General', '#settings', 'Text size', 'font zoom'),
    G('Corners', 'Settings → General', '#settings', 'Corners', 'radius rounded'),
    G('Animations', 'Settings → General', '#settings', 'Animations', 'motion'),
    G('Dashboard updates', 'Settings → General', '#settings', 'Dashboard updates', 'refresh poll interval'),
    G('Database telemetry refresh', 'Settings → General', '#settings', 'Database telemetry', 'poll'),
    G('Alerts on or off', 'Settings → Alerts', '#settings/alerts', 'Alerts', 'notifications'),
    G('Discord webhook', 'Settings → Alerts', '#settings/alerts', 'Discord webhook', 'alerts'),
    G('ntfy topic', 'Settings → Alerts', '#settings/alerts', 'ntfy topic', 'alerts push phone'),
    G('What to report', 'Settings → Alerts', '#settings/alerts', 'What to report', 'alert kinds'),
    G('Disk threshold', 'Settings → Alerts', '#settings/alerts', 'Disk threshold', 'full alert'),
    G('Host offline after', 'Settings → Alerts', '#settings/alerts', 'Host offline after', 'alert'),
    G('Remind me', 'Settings → Alerts', '#settings/alerts', 'Remind me', 'repeat alert'),
    G('Quiet hours', 'Settings → Alerts', '#settings/alerts', 'Quiet hours', 'night alerts'),
    G('What to back up', 'Settings → Backups', '#settings/backups', "What's backed up", 'backup parts jellyfin dashboard containers'),
    G('Extra backup folders', 'Settings → Backups', '#settings/backups', 'Extra folders', 'backup'),
    G('Backups folder', 'Settings → Backups', '#settings/backups', 'Backups folder', 'backup destination location'),
    G('Second backup copy', 'Settings → Backups', '#settings/backups', 'Second copy', 'backup external drive t7 offsite'),
    G('Backup schedule', 'Settings → Backups', '#settings/backups', 'Frequency', 'backup time daily weekly'),
    G('Snapshots to keep', 'Settings → Backups', '#settings/backups', 'Keep', 'backup retention'),
    G('Sharing domain', 'Settings → Sharing', '#settings/sharing', 'Domain', 'cloudflare ssh share'),
    G('Sharing presets', 'Settings → Sharing', '#settings/sharing', 'Sharing presets', 'permissions guest developer admin'),
    G('History kept', 'Settings → Data', '#settings/data', 'History kept', 'retention metrics days database'),
    G('Tailscale auth key', 'Settings → Integrations', '#settings/integrations', 'Tailscale auth key', 'tailnet'),
    G('Cloudflare API token', 'Settings → Integrations', '#settings/integrations', 'Cloudflare API token', 'sharing ssh'),
    G('OrbStack pool size', `${SN} → Settings`, '#infra/arrakis/settings', 'OrbStack pool', 'cpu memory machines'),
    G('Machine ports on the LAN', `${SN} → Settings`, '#infra/arrakis/settings', 'Machine ports on the LAN', 'orbstack expose network'),
    G('Docker ports on the LAN', `${SN} → Settings`, '#infra/arrakis/settings', 'Docker ports on the LAN', 'orbstack expose pihole dns containers'),
    G('HTTPS for .orb.local', `${SN} → Settings`, '#infra/arrakis/settings', 'HTTPS for .orb.local', 'orbstack certificate'),
    G('Pause while the Mac sleeps', `${SN} → Settings`, '#infra/arrakis/settings', 'Pause while the Mac sleeps', 'orbstack power sleep'),
    G('Rosetta', `${SN} → Settings`, '#infra/arrakis/settings', 'Rosetta for Intel binaries', 'orbstack x86 amd64 emulation'),
    G('Hosts & machines overview', 'Settings → Hosts & machines', '#settings/hosts', 'Hosts & machines', 'all settings computers people'),
];

const MACHINE = [
    ['Name', 'rename'], ['CPU', 'cpu limit cores'], ['Memory', 'memory limit ram'], ['Disk', 'disk limit storage size'],
    ['Mac files', 'isolation isolate'], ['Shared folders', 'mounts mount folder'], ['SSH agent', 'forward keys'],
    ['Mac network', 'isolate network block'], ['Ports', 'web address orb.local http https'], ['Timezone', 'time zone clock'],
    ['Updates', 'automatic upgrade packages'], ['Delete machine', 'remove'],
];

export function settingsIndex(machineList = [], hostList = []) {
    const out = GLOBAL.map(e => ({ ...e }));
    for (const m of machineList || []) {
        const hash = `#infra/vm-${encodeURIComponent(m.name)}/settings`;
        for (const [label, kw] of MACHINE) out.push(G(`${label === 'Ports' ? 'Web ports' : label}`, `${m.name} → Settings`, hash, label, `${kw} machine vm ${m.name}`));
        for (const k of (m.share?.keys || []).filter(k => k.perms)) {
            out.push(G(`${k.user}'s permissions`, `${m.name} → Sharing`, `#infra/vm-${encodeURIComponent(m.name)}/person-${k.user}`, 'Preset',
                `person people root sudo network limits expiry ${k.label || ''}`));
        }
    }
    for (const h of hostList || []) {
        const hash = `#infra/${h.id}/settings`;
        out.push(G('Agent', `${h.name} → Settings`, hash, 'Agent', 'install update uninstall host'));
        if (h.caps?.orbstack || h.orb_manage) out.push(G('Manage OrbStack', `${h.name} → Settings`, hash, 'Managed by the dashboard', 'host machines orbstack'));
        if (h.orb_manage) out.push(G('OrbStack pool size', `${h.name} → Settings`, hash, 'OrbStack pool', 'cpu memory'));
        out.push(G('Remove host', `${h.name} → Settings`, hash, 'Remove host', 'delete'));
    }
    return out;
}

// Open a setting: go to its page, then scroll its row into view and flash it. The page may
// still be loading, so keep looking for a few seconds.
export function openSetting(entry) {
    location.hash = entry.hash;
    const want = entry.label.trim().toLowerCase();
    const started = Date.now();
    const find = () => {
        const sel = '.ui-form-row .ui-label, .ui-form-row .lbl, .ui-card-title';
        for (const el of document.querySelectorAll(sel)) {
            const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim().toLowerCase();
            if (own === want || el.textContent.trim().toLowerCase() === want) return el.closest('.ui-form-row') || el.closest('.ui-card');
        }
        return null;
    };
    const tick = () => {
        const el = find();
        if (el) {
            el.scrollIntoView({ block: 'center', behavior: 'smooth' });
            el.classList.remove('setting-flash'); void el.offsetWidth; el.classList.add('setting-flash');
            setTimeout(() => el.classList.remove('setting-flash'), 2200);
        } else if (Date.now() - started < 4000) setTimeout(tick, 150);
    };
    setTimeout(tick, 120);
}
