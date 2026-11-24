// Takes the README screenshots from a running dashboard.
//
//   cd scripts/screenshots && npm install && npx playwright install chromium
//   npm run shoot                       # every shot, into docs/screenshots
//   npm run shoot -- --only overview,hero
//   npm run shoot -- --url http://other-host:5050
//
// Personal details are swapped for placeholders before each capture: Tailscale and LAN
// addresses, the tailnet name, emails, your user name and home folder, and your Cloudflare
// domain. Anything else (device or machine names, say) goes in $HOMELAB_HOME/screenshots.json:
//
//   { "replace": { "my-laptop": "atreides" }, "machine": "sietch" }
//
// That file stays on your computer, so the names never end up in the repo.

import { chromium } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(process.argv.slice(2).join(' ').split(/\s*--/).filter(Boolean)
    .map(a => { const [k, ...v] = a.split(/[= ]/); return [k, v.join(' ') || true]; }));
const URL = String(args.url || process.env.HOMELAB_URL || 'http://localhost:5050').replace(/\/$/, '');
const OUT = path.resolve(args.out || path.join(HERE, '../../docs/screenshots'));
const ONLY = args.only ? new Set(String(args.only).split(',')) : null;
const HOME_DIR = process.env.HOMELAB_HOME || path.join(os.homedir(), '.config/homelab');

const readJson = (f) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return {}; } };
const local = readJson(path.join(HOME_DIR, 'screenshots.json'));
const cfDomain = readJson(path.join(HOME_DIR, 'secrets/cloudflare.json')).domain;
const user = os.userInfo().username;

// [regex source, flags, replacement]; applied in the page to text, titles and inputs
const RULES = [
    ['\\b100\\.(?!100\\.100\\.100\\b|64\\.0\\.)\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\b', 'g', 'TS_IP'],
    ['\\b192\\.168\\.\\d{1,3}\\.(\\d{1,3})\\b', 'g', '192.168.1.$1'],
    ['\\b10\\.\\d{1,3}\\.\\d{1,3}\\.(\\d{1,3})\\b', 'g', '10.0.0.$1'],
    ['fd7a:115c:a1e0:[0-9a-f:]+', 'gi', 'fd7a:115c:a1e0::1'],
    ['tail[0-9a-f]{4,8}\\.ts\\.net', 'g', 'tailnet.ts.net'],
    ['[\\w.+-]+@(?![\\w.-]*\\.ts\\.net\\b)[\\w-]+(\\.[\\w-]+)+', 'g', 'you@example.com'],   // not user@host.tailnet.ts.net
    [esc(os.homedir()), 'g', '/Users/you'],
    ['\\b' + esc(user) + '\\b', 'g', 'you'],
    ...(cfDomain ? [[esc(cfDomain), 'gi', 'example.com']] : []),
    ...Object.entries(local.replace || {}).map(([k, v]) => [esc(k), 'gi', v]),
];
function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

// Runs in the page before the app: fixed look, no motion, and every text change scrubbed.
function prepare({ rules, theme }) {
    try {
        localStorage.setItem('arrakis_theme', theme);
        localStorage.setItem('arrakis_appearance', JSON.stringify({ accent: 'theme', size: 'm', corners: 'm', motion: 'off' }));
    } catch {}
    const res = rules.map(([s, f, r]) => [new RegExp(s, f), r]);
    const ips = new Map();
    const sub = (s) => {
        for (const [re, r] of res) s = r === 'TS_IP'
            ? s.replace(re, (m) => { if (!ips.has(m)) ips.set(m, '100.64.0.' + (10 + ips.size)); return ips.get(m); })
            : s.replace(re, r);
        return s;
    };
    const scrub = (root) => {
        const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        for (let t; (t = w.nextNode());) { const v = sub(t.nodeValue); if (v !== t.nodeValue) t.nodeValue = v; }
        if (root.querySelectorAll) for (const el of root.querySelectorAll('[title],input,textarea')) {
            if (el.title) el.title = sub(el.title);
            if (el.value) el.value = sub(el.value);
            if (el.placeholder) el.placeholder = sub(el.placeholder);
        }
    };
    window.__scrub = () => scrub(document.body);
    addEventListener('DOMContentLoaded', () => {
        const css = document.createElement('style');
        css.textContent = `*,*::before,*::after{transition:none!important;animation-duration:0s!important;animation-delay:0s!important;caret-color:transparent!important}
            ::-webkit-scrollbar{display:none}*{scrollbar-width:none}`;
        document.head.appendChild(css);
        scrub(document.body);
        new MutationObserver(ms => { for (const m of ms) scrub(m.target.nodeType === 3 ? m.target.parentNode : m.target); })
            .observe(document.body, { subtree: true, childList: true, characterData: true });
    });
}

const W = 1600, H = 900;   // 1600 wide: the overview fits three host cards a row
let browser;
async function newPage({ width = W, height = H, scale = 2, theme = 'dune', mobile = false } = {}) {
    const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: scale, colorScheme: 'dark',
        reducedMotion: 'reduce', isMobile: mobile, hasTouch: mobile });
    await ctx.addInitScript(prepare, { rules: RULES, theme });
    const page = await ctx.newPage();
    page.on('pageerror', e => console.warn('  page error:', e.message));
    return page;
}

// Loads a page and waits until it has data: no boot screen, spinners or skeletons, fonts in.
async function open(page, hash, settle = 2500) {
    await page.goto(`${URL}/${hash}`, { waitUntil: 'load' });
    await page.waitForSelector('.page-wrap, .setup', { timeout: 15000 });
    await page.waitForFunction(() => !document.querySelector('.boot'), null, { timeout: 20000 });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() => ![...document.querySelectorAll('.ui-spin, .ui-skeleton, .skeleton')]
        .some(e => e.offsetParent), null, { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(settle);
    await page.mouse.move(2, page.viewportSize().height - 2);
    await page.evaluate(() => window.__scrub());
}

// How tall the window must be to show the whole page.
function contentHeight(page) {
    return page.evaluate(() => {
        const sa = document.querySelector('.scroll-area'), wrap = document.querySelector('.page-wrap');
        if (!sa || !wrap) return document.documentElement.scrollHeight;
        const top = sa.getBoundingClientRect().top;
        const kids = [...wrap.querySelectorAll(':scope > *, :scope > * > *')];
        const bottom = Math.max(...kids.map(k => k.getBoundingClientRect().bottom)) + sa.scrollTop;
        return Math.ceil(top + bottom + 40);
    });
}
const clamp = (h, { min = 720, max = 1500 } = {}) => Math.max(min, Math.min(max, h));
async function setHeight(page, height) {
    await page.setViewportSize({ width: page.viewportSize().width, height });
    await page.waitForTimeout(600);
    await page.evaluate(() => window.__scrub());
}

const out = (name) => path.join(OUT, name + '.png');
const shot = async (page, name, opts = {}) => { await page.screenshot({ path: out(name), ...opts }); console.log('  ✓', name); };

async function machineName() {
    if (local.machine) return local.machine;
    try {
        const d = (await (await fetch(`${URL}/api/vms`)).json()).data;
        return d.dashboard_vm || d.machines.find(m => m.state === 'running')?.name || d.machines[0]?.name;
    } catch { return null; }
}

// ---------------------------------------------------------------- the shots
// Each shot is sized to its page's content. Shots the README shows side by side share a
// pair id and get one height (the shorter page's), so the two images line up.
const PAGES = [
    // name, route, settle ms, height limits, pair
    ['overview', '#overview', 3500, { max: 1500 }],
    ['host', '#infra/arrakis', 3000, { max: 1300 }],
    ['machines', '#infra/arrakis/vm', 2500, { min: 900, max: 1100 }, 'machines'],
    ['machine', null, 3000, { min: 900, max: 1100 }, 'machines'],
    ['storage', '#infra/arrakis/storage', 2500, { min: 900, max: 1100 }, 'network'],
    ['tailscale', '#tailscale', 3000, { min: 900, max: 1100 }, 'network'],
    ['backups', '#backups', 2500, { max: 1300 }],
    ['terminal', '#terminal', 2500, { min: 900, max: 1100 }, 'tools'],
    ['databases', '#databases', 2500, { min: 900, max: 1100 }, 'tools'],
    ['endpoints', '#endpoints', 12000, { max: 1000 }],   // live response times need a few rounds
];

async function pages() {
    const page = await newPage();
    const vm = await machineName();
    const todo = PAGES.map(([name, route, settle, fit, pair]) => ({ name, settle, fit, pair,
        hash: route || (vm ? `#infra/vm-${vm}` : null) }))
        .filter(s => !ONLY || ONLY.has(s.name) || PAGES.some(p => p[4] && p[4] === s.pair && ONLY.has(p[0])));
    // first pass: measure every page that is part of a pair
    const pairH = {};
    for (const s of todo.filter(s => s.pair && s.hash)) {
        await page.setViewportSize({ width: W, height: H });
        await open(page, s.hash, 800);
        const h = clamp(await contentHeight(page), s.fit);
        pairH[s.pair] = Math.min(pairH[s.pair] ?? Infinity, h);
    }
    for (const s of todo) {
        if (!s.hash) { console.log('  – machine: no machine found'); continue; }
        await page.setViewportSize({ width: W, height: s.pair ? pairH[s.pair] : H });
        await open(page, s.hash, s.settle);
        await setHeight(page, s.pair ? pairH[s.pair] : clamp(await contentHeight(page), s.fit));
        await shot(page, s.name);
    }
    await page.context().close();
}

// The name and machines steps of the first-run flow, cropped to the card and given one
// height so they sit side by side.
async function setup() {
    if (ONLY && !['setup-name', 'setup-machines'].some(n => ONLY.has(n))) return;
    const page = await newPage({ width: 1200, height: 1400 });
    const next = () => page.click('.ui-card-foot .ui-btn.primary').then(() => page.waitForTimeout(700));
    // the wrap stretches to the window; crop to what's actually in it
    const box = () => page.locator('.setup .wrap').evaluate(w => {
        const r = [...w.children].map(c => c.getBoundingClientRect()).filter(r => r.height);
        const x = Math.min(...r.map(r => r.left)), y = Math.min(...r.map(r => r.top));
        return { x: x - 40, y: y - 32, width: Math.max(...r.map(r => r.right)) - x + 80, height: Math.max(...r.map(r => r.bottom)) - y + 64 };
    });
    await open(page, '?setup', 1200);
    const nameBox = await box();
    await next(); await next();                              // past the look step
    await page.evaluate(() => window.__scrub());
    const machinesBox = await box();
    const height = Math.max(nameBox.height, machinesBox.height);
    await shot(page, 'setup-machines', { clip: { ...machinesBox, height } });
    await open(page, '?setup', 600);
    await shot(page, 'setup-name', { clip: { ...nameBox, height } });
    await page.click('.ui-btn.sm.exit').catch(() => {});   // the preview saves nothing; leave it tidily
    await page.context().close();
}

async function mobile() {
    const page = await newPage({ width: 390, height: 844, scale: 3, mobile: true });
    await open(page, '#overview', 3500);
    const buf = await page.screenshot();
    if (!ONLY || ONLY.has('mobile')) { fs.writeFileSync(out('mobile'), buf); console.log('  ✓ mobile'); }
    await page.context().close();
    return buf;
}

async function desktopFrame(theme = 'dune') {
    const page = await newPage({ theme });
    await open(page, '#overview', 3500);
    const buf = await page.screenshot();
    await page.context().close();
    return buf;
}

// ---------------------------------------------------------------- composites
const THEMES = [
    ['dune', 'Dune', '#0F0E0D', '#D6C2A0'], ['spice', 'Spice', '#170D08', '#FF8A3D'],
    ['ibad', 'Ibad', '#060E1C', '#3FB8FF'], ['caladan', 'Caladan', '#08130F', '#4FD1A5'],
    ['giedi', 'Giedi Prime', '#000000', '#E8E4DC'], ['bene-gesserit', 'Bene Gesserit', '#0A0710', '#B48CFF'],
    ['kaitain', 'Kaitain', '#0B0D1A', '#E8BE5A'], ['salusa', 'Salusa Secundus', '#111213', '#D9774A'],
    ['ix', 'Ix', '#0C0F10', '#BEE650'],
];
const dataUrl = (buf) => 'data:image/png;base64,' + buf.toString('base64');

async function render(name, html, width, height, fullPage = false) {
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2 });
    await page.setContent(html, { waitUntil: 'load' });
    await page.evaluate(() => Promise.all([...document.images].map(i => i.decode())));
    await shot(page, name, { omitBackground: true, fullPage });
    await page.close();
}

const FONT = `font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif;`;

async function hero(desktop, phone) {
    await render('hero', `<style>
        html{overflow:hidden}
        body{margin:0;width:1280px;height:820px;${FONT}
            background:radial-gradient(900px 500px at 15% -10%, rgba(214,194,160,.22), transparent 60%),
                       radial-gradient(700px 500px at 105% 110%, rgba(214,120,70,.16), transparent 60%), #0B0A09;
            position:relative;overflow:hidden;border-radius:18px}
        body::before{content:"";position:absolute;inset:0;background-image:radial-gradient(rgba(255,255,255,.05) 1px, transparent 1px);background-size:22px 22px;mask-image:linear-gradient(#000, transparent 85%)}
        .win{position:absolute;left:70px;top:64px;width:1040px;border-radius:12px;overflow:hidden;background:#0F0E0D;
            border:1px solid rgba(255,255,255,.10);box-shadow:0 50px 120px rgba(0,0,0,.65), 0 0 0 1px rgba(0,0,0,.5)}
        .bar{height:34px;display:flex;align-items:center;gap:8px;padding:0 14px;background:#161514;border-bottom:1px solid rgba(255,255,255,.06)}
        .bar i{width:11px;height:11px;border-radius:50%;display:block}
        .url{margin:0 auto;transform:translateX(-30px);font-size:12px;color:#8a8580;background:#0F0E0D;border:1px solid rgba(255,255,255,.06);border-radius:6px;padding:4px 60px}
        .win img{display:block;width:100%}
        .phone{position:absolute;right:56px;bottom:-140px;width:250px;padding:9px;border-radius:44px;background:#1c1b1a;
            border:1px solid rgba(255,255,255,.14);box-shadow:0 40px 100px rgba(0,0,0,.7)}
        .phone img{display:block;width:100%;border-radius:36px}
    </style>
    <div class="win"><div class="bar"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i>
        <span class="url">localhost:5050</span></div><img src="${dataUrl(desktop)}"></div>
    <div class="phone"><img src="${dataUrl(phone)}"></div>`, 1280, 820);
}

async function themes() {
    const tiles = [];
    for (const [id, label, bg, accent] of THEMES) tiles.push([label, bg, accent, await desktopFrame(id)]);
    await render('themes', `<style>
        body{margin:0;width:1280px;padding:36px;box-sizing:border-box;background:#0B0A09;${FONT};border-radius:18px}
        .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}
        figure{margin:0}
        figure img{display:block;width:100%;border-radius:8px;border:1px solid rgba(255,255,255,.09);box-shadow:0 14px 40px rgba(0,0,0,.5)}
        figcaption{display:flex;align-items:center;gap:8px;margin-top:10px;font-size:14px;color:#cfc9c0}
        figcaption i{width:10px;height:10px;border-radius:3px;display:block}
    </style><div class="grid">${tiles.map(([l, bg, a, b]) =>
        `<figure><img src="${dataUrl(b)}"><figcaption><i style="background:${a}"></i>${l}</figcaption></figure>`).join('')}</div>`,
    1280, 860, true);
}

// ---------------------------------------------------------------- run
fs.mkdirSync(OUT, { recursive: true });
browser = await chromium.launch();
try {
    console.log(`Shooting ${URL} → ${path.relative(process.cwd(), OUT) || '.'}`);
    await pages();
    await setup();
    const want = (n) => !ONLY || ONLY.has(n);
    if (want('mobile') || want('hero')) {
        const phone = await mobile();
        if (want('hero')) await hero(await desktopFrame(), phone);
    }
    if (want('themes')) await themes();
} finally {
    await browser.close();
}
