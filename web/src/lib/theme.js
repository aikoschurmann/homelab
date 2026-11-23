// Dark themes only; colours live in themes.css. Saved per browser.
export const THEMES = [
    { id: 'dune', label: 'Dune', bg: '#0F0E0D', surface: '#1A1817', accent: '#D6C2A0' },
    { id: 'spice', label: 'Spice', bg: '#170D08', surface: '#24150D', accent: '#FF8A3D' },
    { id: 'ibad', label: 'Ibad', bg: '#060E1C', surface: '#0D1A2F', accent: '#3FB8FF' },
    { id: 'caladan', label: 'Caladan', bg: '#08130F', surface: '#0F1F1A', accent: '#4FD1A5' },
    { id: 'giedi', label: 'Giedi Prime', bg: '#000000', surface: '#0B0B0B', accent: '#E8E4DC' },
    { id: 'bene-gesserit', label: 'Bene Gesserit', bg: '#0A0710', surface: '#14101D', accent: '#B48CFF' },
    { id: 'kaitain', label: 'Kaitain', bg: '#0B0D1A', surface: '#141829', accent: '#E8BE5A' },
    { id: 'salusa', label: 'Salusa Secundus', bg: '#111213', surface: '#1B1D1F', accent: '#D9774A' },
    { id: 'ix', label: 'Ix', bg: '#0C0F10', surface: '#151A1C', accent: '#BEE650' },
];
const KEY = 'arrakis_theme';

export function savedTheme() {
    let t = null;
    try { t = localStorage.getItem(KEY); } catch (e) {}
    // removed themes (light, dark, graphite, neon, …) land on Dune
    return THEMES.some(x => x.id === t) ? t : 'dune';
}

export function applyTheme(id, animate = false) {
    const set = () => document.documentElement.setAttribute('data-theme', id);
    animate && document.startViewTransition ? document.startViewTransition(set) : set();
    try { localStorage.setItem(KEY, id); } catch (e) {}
}

// ---- appearance extras (per browser): accent override, text size, corners, motion ----
export const ACCENTS = [
    { id: 'theme', label: 'Theme', color: null },
    { id: 'sand', label: 'Sand', color: '#D6C2A0' },
    { id: 'spice', label: 'Spice', color: '#FF8A3D' },
    { id: 'ibad', label: 'Ibad', color: '#3FB8FF' },
    { id: 'caladan', label: 'Caladan', color: '#4FD1A5' },
    { id: 'harkonnen', label: 'Harkonnen', color: '#E0484E' },
    { id: 'bene-gesserit', label: 'Bene Gesserit', color: '#B48CFF' },
];
export const SIZES = { s: 0.92, m: 1, l: 1.08 };
export const CORNERS = { sharp: '3px', m: '8px', round: '14px' };
const AKEY = 'arrakis_appearance';
const DEFAULTS = { accent: 'theme', size: 'm', corners: 'm', motion: 'on' };

export function savedAppearance() {
    let a = {};
    try { a = JSON.parse(localStorage.getItem(AKEY)) || {}; } catch (e) {}
    return { ...DEFAULTS, ...a };
}

export function applyAppearance(a, save = false) {
    const root = document.documentElement, st = root.style;
    const acc = ACCENTS.find(x => x.id === a.accent)?.color;
    const vars = ['--accent', '--accent-hover', '--accent-fill', '--accent-fg', '--accent-soft', '--logo-bg', '--logo-fg'];
    if (acc) {
        st.setProperty('--accent', acc);
        st.setProperty('--accent-hover', `color-mix(in srgb, ${acc} 75%, white)`);
        st.setProperty('--accent-fill', acc);
        st.setProperty('--accent-fg', '#111');
        st.setProperty('--accent-soft', `color-mix(in srgb, ${acc} 14%, transparent)`);
        st.setProperty('--logo-bg', acc);
        st.setProperty('--logo-fg', '#111');
    } else vars.forEach(v => st.removeProperty(v));
    // zoom scales every px size; the app shell divides 100vh by it so it still fits the window
    const z = SIZES[a.size] || 1;
    st.zoom = z === 1 ? '' : z;
    st.setProperty('--ui-zoom', z);
    st.setProperty('--radius-card', CORNERS[a.corners] || '8px');
    root.classList.toggle('reduce-motion', a.motion === 'off');
    if (save) try { localStorage.setItem(AKEY, JSON.stringify(a)); } catch (e) {}
}
