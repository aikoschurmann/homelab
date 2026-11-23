<script>
    import { SN } from '../lib/server.js';
    // Network tools, four tabs: Checks (ping / port / DNS from several computers at once, one
    // result row per computer), Speed test (Macs), Computers (how each is connected), API health.
    // Routes: #tools, #tools/speed, #tools/computers, #tools/api
    import { onMount } from 'svelte';
    import { Play, Loader2, RotateCw, ChevronDown, Check } from 'lucide-svelte';
    import Tabs from './ui/Tabs.svelte';
    import UptimeTab from './UptimeTab.svelte';
    import PiholeTab from './PiholeTab.svelte';
    import CopyText from './ui/CopyText.svelte';
    import { Box } from 'lucide-svelte';
    import { tailnet, fetchTailnet, isShared } from '../lib/tailscale.js';
    import { hosts, fetchHosts, hostIcon, arrakisModel } from '../lib/hosts.js';
    import { visible } from '../lib/stores.js';

    export let stats = null;
    export let section = null;
    export let onNavigate = () => {};

    $: tab = ['uptime', 'pihole', 'speed', 'computers', 'api'].includes(section) ? section : 'checks';
    const TABS = [{ id: 'checks', label: 'Checks' }, { id: 'uptime', label: 'Uptime' }, { id: 'pihole', label: 'Pi-hole' }, { id: 'speed', label: 'Speed test' }, { id: 'computers', label: 'Computers' }, { id: 'api', label: 'API health' }];

    const toast = (m) => window.showToast?.(m);
    const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body && JSON.stringify(body) }).then(r => r.json());
    const getData = (url) => fetch(url).then(r => r.json()).then(j => j.status === 'success' ? j.data : null).catch(() => null);

    let now = Date.now();
    function ago(t) {
        const s = Math.max(0, (now - t) / 1000);
        return s < 60 ? 'just now' : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;
    }

    // ---- the computers: Arrakis, its running machines, online cluster hosts -------------------
    let sources = [{ id: 'mac', name: SN, kind: 'host', os: 'macOS' }];
    const srcOf = (id) => sources.find(x => x.id === (id || 'mac'));
    const srcName = (id) => srcOf(id)?.name || id || SN;
    async function loadSources() {
        const d = await getData('/api/tools/sources');
        if (d?.length) sources = d;
    }
    // the same icon the sidebar tree uses for each computer
    const iconOf = (x) => x.id === 'mac' ? hostIcon($arrakisModel, 'macOS') : x.kind === 'machine' ? Box
        : hostIcon(($hosts || []).find(h => h.id === x.id)?.report?.model, x.os);

    // how each is connected (Computers tab), asked once per computer when the tab opens
    let infos = {};   // id -> { data } | { err }; absent while asking
    async function loadInfo(id) {
        const j = await fetch('/api/tools/info?from=' + encodeURIComponent(id)).then(r => r.json()).catch(() => null);
        infos = { ...infos, [id]: j?.status === 'success' ? { data: j.data } : { err: j?.message || 'Could not reach it' } };
    }
    let asked = new Set();
    $: if (tab === 'computers') for (const x of sources) if (!asked.has(x.id)) { asked.add(x.id); loadInfo(x.id); }
    const DNS_NAMES = { '100.100.100.100': 'MagicDNS', 'fd7a:115c:a1e0::53': 'MagicDNS' };
    const dnsOf = (i) => i?.dns?.find(d => d.includes('.')) || i?.dns?.[0];

    // ---- checks: one target, run from every ticked computer at once ------------------------
    const KINDS = [{ id: 'ping', label: 'Ping', run: 'Ping' }, { id: 'port', label: 'Port', run: 'Check' }, { id: 'dns', label: 'DNS lookup', run: 'Look up' }];
    const PLACEHOLDER = { ping: 'host or IP, e.g. giedi-pi', port: 'host or IP', dns: 'name, e.g. github.com' };
    let kind = 'ping', host = '', port = '';
    // ticked computers, remembered here; Arrakis alone to start
    const FKEY = 'arrakis_nettools_from_v2';
    let picked = ['mac'];
    try { picked = JSON.parse(localStorage.getItem(FKEY)) || ['mac']; } catch (e) {}
    $: try { localStorage.setItem(FKEY, JSON.stringify(picked)); } catch (e) {}
    $: pickedLive = sources.filter(x => picked.includes(x.id));
    const togglePick = (id) => picked = picked.includes(id) ? picked.filter(x => x !== id) : [...picked, id];
    let menuOpen = false, menuEl;
    const onDocClick = (e) => { if (menuOpen && menuEl && !menuEl.contains(e.target)) menuOpen = false; };
    $: fromLabel = pickedLive.length === 1 ? pickedLive[0].name : pickedLive.length === sources.length ? 'all computers' : `${pickedLive.length} computers`;

    // runs, newest first, kept in this browser: { id, kind, host, port, at, rows: [{ from, res | null while running }] }
    const HKEY = 'arrakis_nettools_runs';
    let runs = [];
    try { runs = JSON.parse(localStorage.getItem(HKEY)) || []; } catch (e) {}
    const keep = () => { try { localStorage.setItem(HKEY, JSON.stringify(runs.filter(x => x.rows.every(r => r.res)).slice(0, 15))); } catch (e) {} };
    let openId = runs[0]?.id ?? null;
    $: shown = runs.find(x => x.id === openId) || runs[0];
    $: busy = runs.some(x => x.rows.some(r => !r.res));

    async function runCheck(k = kind, h = host.trim(), p = port, from = pickedLive.map(x => x.id)) {
        if (!h || (k === 'port' && !p) || !from.length) return;
        const run = { id: Date.now(), kind: k, host: h, port: k === 'port' ? +p : null, at: Date.now(), rows: from.map(f => ({ from: f, res: null })) };
        runs = [run, ...runs].slice(0, 15); openId = run.id;
        await Promise.all(run.rows.map(async (row) => {
            try {
                const j = await post('/api/tools/' + k, k === 'port' ? { host: h, port: +p, from: row.from } : { host: h, from: row.from });
                row.res = j.status === 'success' ? { ok: true, ...j.data } : { ok: false, message: j.message };
            } catch (e) { row.res = { ok: false, message: 'No response' }; }
            runs = runs;
        }));
        keep();
    }
    const again = (x) => { kind = x.kind; host = x.host; port = x.port ?? ''; runCheck(x.kind, x.host, x.port, x.rows.map(r => r.from)); };
    function clearRuns() { runs = []; openId = null; keep(); }

    // what came back, as a short verdict and a plain line saying what it means
    // ({ label, note, bad }); x is the run (kind, host, port)
    const UNKNOWN = /resolve|unknown host|bad address|not known|nodename|no address/i;
    const NOT_RUN = /isn't running|isn't connected|online|ssh|permission denied|didn't answer|connection closed|no response/i;
    function outcome(x, r) {
        const k = x.kind, t = x.host;
        if (!r.ok) {
            const m = r.message || '';
            if (NOT_RUN.test(m)) return { label: "Couldn't run", note: m, bad: true };
            if (UNKNOWN.test(m) || (k === 'dns' && /not found/i.test(m))) return { label: k === 'dns' ? 'Not found' : 'Unknown host', note: `${t} doesn't resolve from here`, bad: true };
            if (/no route|unreachable/i.test(m)) return { label: 'Unreachable', note: `No route to ${t} from here`, bad: true };
            if (k === 'ping') return { label: 'No reply', note: m && m !== 'No answer' ? m : `${t} didn't answer any of the pings`, bad: true };
            return { label: 'Failed', note: m, bad: true };
        }
        if (k === 'ping') {
            if (r.loss >= 100) return { label: 'No reply', note: `${t} didn't answer any of the ${r.sent} pings`, bad: true };
            const lost = r.sent - (r.received ?? r.sent);
            return { label: `${r.avg_ms.toFixed(1)} ms`, note: `${r.min_ms?.toFixed(1) ?? '—'} to ${r.max_ms?.toFixed(1) ?? '—'} ms` + (lost ? ` · ${lost} of ${r.sent} lost` : ` · all ${r.sent} answered`), warn: lost > 0 };
        }
        if (k === 'port') {
            if (r.open) return { label: 'Open', note: r.ms != null ? `connected in ${r.ms} ms` : 'accepts connections' };
            if (/timed/.test(r.reason)) return { label: 'No reply', note: `Timed out after 4 s; a firewall is probably dropping port ${x.port}`, bad: true };
            return { label: 'Refused', note: `${t} is up, but nothing is listening on port ${x.port}`, bad: true };
        }
        return { label: r.addresses.length === 1 ? r.addresses[0] : `${r.addresses.length} addresses`, note: [r.addresses.length > 1 ? r.addresses.join(', ') : '', r.ms != null ? `${r.ms} ms` : ''].filter(Boolean).join(' · ') };
    }
    const fail = (x, r) => outcome(x, r).bad;
    // one line for a run in the Earlier list
    function runLine(x) {
        const done = x.rows.filter(r => r.res), bad = done.filter(r => fail(x, r.res));
        if (x.rows.length === 1 && done.length) return outcome(x, done[0].res).label;
        if (x.kind === 'ping' && done.length > bad.length) return `${done.length - bad.length} of ${x.rows.length} answered · fastest ${Math.min(...done.filter(r => !fail(x, r.res)).map(r => r.res.avg_ms)).toFixed(1)} ms`;
        return `${done.length - bad.length} of ${x.rows.length} ${x.kind === 'port' ? 'open' : 'answered'}`;
    }
    const kindLabel = (k) => KINDS.find(x => x.id === k)?.label;

    // targets offered while typing: tailnet devices and cluster hosts
    $: targets = [...new Set([
        ...($tailnet?.devices || []).filter(d => !d.self && !isShared(d)).map(d => d.name),
        ...($hosts || []).map(h => h.name),
    ])].sort();

    // ---- speed test ----------------------------------------------------------------------------
    let speed = null;
    // speed tests need macOS networkQuality: Arrakis and the Macs in the cluster
    let speedFrom = 'mac';
    $: macs = sources.filter(x => x.os === 'macOS');
    $: stRunning = (speed?.running || []).includes(speedFrom) || (speedFrom === 'mac' && stats?.bg?.speedtest_running);
    $: anyRunning = (speed?.running || []).length > 0;
    $: hist = (speed?.history || []).filter(h => (h.from || 'mac') === speedFrom);
    $: last = hist[0];
    $: lastErr = speed?.result?.status === 'error' && (speed.result.from || 'mac') === speedFrom && (!last || speed.result.at > last.at) ? speed.result.message : '';
    let wasRunning = false;
    $: if (wasRunning && !anyRunning) loadSpeed();
    $: wasRunning = anyRunning;
    async function loadSpeed() { speed = await getData('/api/network/speedtest') || speed; }
    async function runSpeedtest() {
        try {
            const j = await post('/api/network/speedtest', { from: speedFrom });
            if (j.status === 'error') return toast(j.message);
            speed = { ...(speed || {}), running: [...(speed?.running || []), speedFrom] };
            toast('Speed test started; it takes about 15 seconds');
        } catch (e) {}
    }
    const when = (t) => new Date(t * 1000).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

    // ---- API health: call every read of the dashboard's API and time it ----------------------
    // Reads that take an id get a real one (the first machine, host, tunnel…). What can't be
    // called from here is listed as skipped, with why, instead of failing.
    const SKIP = [
        [/^\/api\/hosts\/(rpc|report|backup-plan|install\.sh|backup\/)/, 'Used by host agents, needs their token'],
        [/stats_stream|^\/api\/term\b|\/stream\b|\/live$/, 'Live stream, never finishes'],
        [/\/action\//, 'Runs an action'],
        [/export\.csv|\/backups\/file\/|\/file$|\/install$|scrollback$/, 'File download'],
    ];
    async function samples() {
        const [vms, hs, cf, pools, tm, dbs] = await Promise.all(['/api/vms', '/api/hosts', '/api/cloudflare', '/api/compute/pools', '/api/tmux/sessions', '/api/databases'].map(u => fetch(u, { signal: AbortSignal.timeout(5000) }).then(r => r.json()).catch(() => null)));
        return {
            machine: vms?.data?.machines?.find(m => m.state === 'running')?.name || vms?.data?.machines?.[0]?.name,
            hid: hs?.data?.hosts?.find(h => h.online)?.id || hs?.data?.hosts?.[0]?.id,
            // machine lists need a host that runs OrbStack
            hidOrb: hs?.data?.hosts?.find(h => h.online && h.orb_manage)?.id,
            tid: cf?.data?.tunnels?.find(t => !t.deleted)?.id,
            pool: pools?.data?.[0]?.name,
            session: (tm?.sessions || tm?.data?.sessions)?.[0]?.name,
            db: dbs?.data?.[0]?.id,
        };
    }
    function fill(path, x) {
        let miss = false;
        const out = path.replace(/\{(\w+)\}/g, (_, k) => {
            const v = k === 'hid' ? (/\/machines$/.test(path) ? x.hidOrb : x.hid) : k === 'tid' ? x.tid : k === 'session' ? x.session : k === 'db_id' ? x.db
                : k === 'name' ? (path.includes('/compute/') ? x.pool : x.machine) : null;
            if (v == null) miss = true;
            return encodeURIComponent(v ?? '');
        });
        return miss ? null : out;
    }
    let apiRows = null, apiSkipped = [], apiRunning = false, showSkipped = false;
    // opening the tab lists the paths straight away; the ids to fill them in are looked up on Run
    async function loadApiList() {
        apiRunning = true;
        await buildApiRows(null);
        apiRunning = false;
    }
    async function buildApiRows(x) {
        try {
            const [j, xs] = await Promise.all([fetch('/api/endpoints').then(r => r.json()), x]);
            const groups = Array.isArray(j.data) ? j.data : (j.data?.groups || j.groups || []);
            const rows = [], skipped = [];
            for (const g of groups) for (const e of g.endpoints) {
                const why = e.method !== 'GET' ? 'Changes something' : SKIP.find(([re]) => re.test(e.path))?.[1];
                const url = why ? null : xs ? fill(e.path, xs) : e.path;
                if (why || !url) skipped.push({ group: g.name, path: e.path, method: e.method, desc: e.desc, why: why || 'Needs an id there is none of yet' });
                else rows.push({ group: g.name, path: e.path, url, desc: e.desc, state: 'wait' });
            }
            apiSkipped = skipped;
            apiRows = rows;
        } catch (e) { toast('Could not load the endpoint list'); }
    }
    async function runApiCheck() {
        apiRunning = true;
        await buildApiRows(samples());
        try {
            // a few at a time so slow endpoints don't hold the rest up
            let next = 0;
            const worker = async () => {
                while (next < apiRows.length) {
                    const i = next++, row = apiRows[i], t0 = performance.now();
                    row.state = 'run'; apiRows = apiRows;
                    try {
                        const ctl = new AbortController(), to = setTimeout(() => ctl.abort(), 30000);
                        const r = await fetch(row.url, { signal: ctl.signal });
                        const body = await r.json().catch(() => null);
                        clearTimeout(to);
                        row.code = r.status;
                        row.ok = r.ok && body?.status !== 'error';
                        row.note = !row.ok ? (body?.message || r.statusText || 'Error') : '';
                    } catch (e) { row.ok = false; row.note = e.name === 'AbortError' ? 'Timed out' : 'No response'; }
                    row.ms = Math.round(performance.now() - t0);
                    row.state = 'done'; apiRows = apiRows;
                }
            };
            await Promise.all([worker(), worker(), worker(), worker()]);
            apiAt = Date.now();
        } catch (e) { toast('Could not load the endpoint list'); }
        apiRunning = false;
    }
    $: apiDone = apiRows?.filter(r => r.state === 'done') || [];
    $: apiBad = apiDone.filter(r => !r.ok).length;
    $: apiSlow = apiDone.filter(r => r.ok && r.ms > 1000).length;
    $: apiTimes = apiDone.filter(r => r.ok).map(r => r.ms).sort((a, b) => a - b);
    $: apiMedian = apiTimes.length ? apiTimes[Math.floor(apiTimes.length / 2)] : null;
    $: apiSlowest = apiDone.filter(r => r.ok).sort((a, b) => b.ms - a.ms)[0];
    let apiAt = null;
    // opening the tab only lists what would be called; Run calls them
    $: if (tab === 'api' && !apiRows && !apiRunning) loadApiList();
    // failures first, then slowest
    $: apiSorted = apiRows && !apiRunning ? [...apiRows].sort((a, b) => (a.ok === b.ok ? 0 : a.ok ? 1 : -1) || b.ms - a.ms) : apiRows;

    onMount(() => {
        loadSources();
        if (!$hosts) fetchHosts();
        document.addEventListener('click', onDocClick);
        loadSpeed();
        if (!$tailnet) fetchTailnet();
        const t = setInterval(() => { now = Date.now(); if (anyRunning && visible()) loadSpeed(); }, 3000);
        const t2 = setInterval(() => visible() && loadSources(), 30000);
        return () => { clearInterval(t); clearInterval(t2); document.removeEventListener('click', onDocClick); };
    });
</script>

<div class="ui-page">
    <div class="ui-head">
        <div><h1>Network tools</h1><p>Check the network from any computer in the cluster, or from several at once.</p></div>
    </div>

    <Tabs tabs={TABS} active={tab} onSelect={(id) => onNavigate('Tools', id === 'checks' ? null : id)} />

    {#if tab === 'checks'}
        <!-- one toolbar: what, at what, from where -->
        <form class="ui-listbar runbar" on:submit|preventDefault={() => runCheck()}>
            <div class="ui-seg">
                {#each KINDS as k}<button type="button" class:on={kind === k.id} on:click={() => kind = k.id}>{k.label}</button>{/each}
            </div>
            <label class="ui-search host"><input class="mono" placeholder={PLACEHOLDER[kind]} list="nt-targets" bind:value={host} autocomplete="off" spellcheck="false" /></label>
            {#if kind === 'port'}<input class="ui-input mono port" placeholder="port" inputmode="numeric" bind:value={port} />{/if}
            <div class="pick" bind:this={menuEl}>
                <button type="button" class="ui-btn" aria-haspopup="menu" aria-expanded={menuOpen} on:click={() => menuOpen = !menuOpen}>From {fromLabel} <ChevronDown size={14} /></button>
                {#if menuOpen}
                    <div class="pick-menu" role="menu">
                        <div class="pick-head">Run from</div>
                        {#each sources as x}
                            {@const on = picked.includes(x.id)}
                            <button type="button" class="pick-item" role="menuitemcheckbox" aria-checked={on} on:click={() => togglePick(x.id)}>
                                <span class="box" class:on>{#if on}<Check size={11} strokeWidth={3} />{/if}</span>
                                <span class="pick-ic"><svelte:component this={iconOf(x)} size={13} /></span>{x.name}
                                {#if x.kind === 'machine'}<span class="ui-dim pick-k">machine</span>{/if}
                            </button>
                        {/each}
                        <div class="pick-foot"><button type="button" class="ui-link" on:click={() => picked = sources.map(x => x.id)}>All</button><button type="button" class="ui-link" on:click={() => picked = ['mac']}>Only {SN}</button></div>
                    </div>
                {/if}
            </div>
            <button class="ui-btn primary" disabled={busy || !host.trim() || (kind === 'port' && !port) || !pickedLive.length}>{#if busy}<Loader2 size={13} class="ui-spin" />{:else}<Play size={13} />{/if} {KINDS.find(k => k.id === kind).run}</button>
            <datalist id="nt-targets">{#each targets as t}<option value={t}></option>{/each}</datalist>
        </form>

        {#if shown}
            <!-- the open run: one row per computer it ran from -->
            <section class="ui-card">
                <div class="ui-card-head">
                    <div><h2 class="ui-card-title">{kindLabel(shown.kind)} <span class="ui-mono tgt">{shown.host}{shown.port ? ':' + shown.port : ''}</span></h2><p class="ui-card-desc">From {shown.rows.length === 1 ? srcName(shown.rows[0].from) : `${shown.rows.length} computers`} · {ago(shown.at)}</p></div>
                    <button class="ib" title="Run again" aria-label="Run again" disabled={busy} on:click={() => again(shown)}><RotateCw size={14} /></button>
                </div>
                <div class="ui-tbl-wrap"><table class="ui-tbl res-tbl">
                    <colgroup><col class="w-pc" /><col /></colgroup>
                    <thead><tr><th>From</th><th>Result</th></tr></thead>
                    <tbody>
                        {#each shown.rows as row (row.from)}
                            {@const x = srcOf(row.from) || { id: row.from, name: row.from, kind: 'host' }}
                            <tr>
                                <td><span class="pc"><span class="pc-ic"><svelte:component this={iconOf(x)} size={14} /></span>{x.name}</span></td>
                                <td>{#if row.res}{@const o = outcome(shown, row.res)}<span class="res"><span class:bad={o.bad} class:warn={o.warn}>{o.label}</span>{#if o.note}<small title={o.note}>{o.note}</small>{/if}</span>{:else}<Loader2 size={13} class="ui-spin dimspin" />{/if}</td>
                            </tr>
                        {/each}
                    </tbody>
                </table></div>
            </section>
        {:else}
            <section class="ui-card"><div class="ui-empty">Pick a check, type a target and choose which computers to run it from. Device names from the tailnet are suggested as you type.</div></section>
        {/if}

        {#if runs.length > 1}
            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">Earlier</h2><p class="ui-card-desc">Kept in this browser. Open one to see every computer's result.</p></div><button class="ui-btn sm" on:click={clearRuns}>Clear</button></div>
                <div class="ui-tbl-wrap"><table class="ui-tbl hist">
                    <colgroup><col class="w-kind" /><col class="w-target" /><col /><col class="w-when" /></colgroup>
                    <thead><tr><th>Check</th><th>Target</th><th>Result</th><th>When</th></tr></thead>
                    <tbody>
                        {#each runs as x (x.id)}
                            <tr class="click" class:cur={x === shown} on:click={() => openId = x.id}>
                                <td>{kindLabel(x.kind)}</td>
                                <td><span class="ui-mono">{x.host}{x.port ? ':' + x.port : ''}</span></td>
                                <td><span class="res"><span>{runLine(x)}</span><small>from {x.rows.map(r => srcName(r.from)).join(', ')}</small></span></td>
                                <td class="ui-dim">{ago(x.at)}</td>
                            </tr>
                        {/each}
                    </tbody>
                </table></div>
            </section>
        {/if}

    {:else if tab === 'speed'}
        <div class="ui-listbar">
            {#if macs.length > 1}<div class="ui-seg">{#each macs as x}<button class:on={speedFrom === x.id} on:click={() => speedFrom = x.id}>{x.name}</button>{/each}</div>{/if}
            <span class="ui-dim lead">{#if stRunning}Takes about 15 seconds{:else if lastErr}<span class="bad">Last run failed: {lastErr}</span>{:else if last}Last tested {ago(last.at * 1000)}{#if last.interface}{' over ' + last.interface}{/if}{:else}Measured with macOS networkQuality against Apple's servers{/if}</span>
            <button class="ui-btn primary push" disabled={stRunning} on:click={runSpeedtest}>{#if stRunning}<Loader2 size={13} class="ui-spin" /> Running…{:else}<Play size={13} /> Test {srcName(speedFrom)}{/if}</button>
        </div>
        <div class="ui-stats">
            <div class="ui-stat"><span class="ui-stat-label">Download</span><span class="ui-stat-value">{last ? last.dl : '—'}<small>Mbps</small></span><span class="ui-stat-sub">{hist.length > 1 ? `best ${Math.max(...hist.map(h => h.dl))} Mbps` : ' '}</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Upload</span><span class="ui-stat-value">{last ? last.ul : '—'}<small>Mbps</small></span><span class="ui-stat-sub">{hist.length > 1 ? `best ${Math.max(...hist.map(h => h.ul))} Mbps` : ' '}</span></div>
            <div class="ui-stat"><span class="ui-stat-label" title="Round trips per minute while the line is busy; higher is better">Responsiveness</span><span class="ui-stat-value">{last?.rpm ?? '—'}<small>RPM</small></span><span class="ui-stat-sub">round trips a minute under load</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Idle latency</span><span class="ui-stat-value">{last?.idle_ms ?? '—'}<small>ms</small></span><span class="ui-stat-sub">when nothing else is running</span></div>
        </div>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">History</h2><p class="ui-card-desc">Tests from {srcName(speedFrom)}, newest first. Only Macs can run them (macOS networkQuality).</p></div></div>
            {#if hist.length}
                <div class="ui-tbl-wrap"><table class="ui-tbl spd">
                    <thead><tr><th>When</th><th class="num">Download</th><th class="num">Upload</th><th class="num">Responsiveness</th><th class="num">Idle latency</th></tr></thead>
                    <tbody>
                        {#each hist as h}
                            <tr>
                                <td>{when(h.at)}<small class="sub">{ago(h.at * 1000)}{h.interface ? ' · ' + h.interface : ''}</small></td>
                                <td class="num">{h.dl} <span class="ui-dim">Mbps</span></td>
                                <td class="num">{h.ul} <span class="ui-dim">Mbps</span></td>
                                <td class="num">{h.rpm ?? '—'} <span class="ui-dim">RPM</span></td>
                                <td class="num">{h.idle_ms ?? '—'} <span class="ui-dim">ms</span></td>
                            </tr>
                        {/each}
                    </tbody>
                </table></div>
            {:else}
                <div class="ui-empty">{stRunning ? 'The first result will show here in a moment.' : 'No speed tests yet.'}</div>
            {/if}
        </section>

    {:else if tab === 'computers'}
        <section class="ui-card">
            <div class="ui-tbl-wrap"><table class="ui-tbl conn">
                <thead><tr><th>Computer</th><th>Addresses</th><th>Public address</th><th>DNS</th></tr></thead>
                <tbody>
                    {#each sources as x (x.id)}
                        {@const i = infos[x.id]?.data}
                        {@const err = infos[x.id]?.err}
                        <tr>
                            <td><span class="pc"><span class="pc-ic"><svelte:component this={iconOf(x)} size={14} /></span><span class="res"><span>{x.name}</span><small>{#if i}{[i.kind, i.interface].filter(Boolean).join(' · ')}{:else if err}<span class="bad">{err}</span>{:else}Asking…{/if}</small></span></span></td>
                            <td>{#if i}<span class="res"><span class="ui-mono">{i.lan_ip || '—'}</span><small>{i.tailscale_ip ? 'Tailscale ' + i.tailscale_ip : 'not on Tailscale'}{i.gateway ? ' · router ' + i.gateway : ''}</small></span>{/if}</td>
                            <td>{#if i}{#if i.public_ip}<CopyText text={i.public_ip} />{:else}<span class="ui-dim">Offline</span>{/if}{/if}</td>
                            <td>{#if i && dnsOf(i)}<span class="res"><span>{DNS_NAMES[dnsOf(i)] || dnsOf(i)}</span>{#if DNS_NAMES[dnsOf(i)]}<small class="ui-mono">{dnsOf(i)}</small>{/if}</span>{/if}</td>
                        </tr>
                    {/each}
                </tbody>
            </table></div>
        </section>

    {:else}
        <div class="ui-listbar">
            <span class="ui-dim lead">Calls every read of the dashboard's API from this browser and times it{#if apiAt && !apiRunning} · last run {ago(apiAt)}{/if}</span>
            <button class="ui-btn primary push" disabled={apiRunning} on:click={runApiCheck}>{#if apiRunning}<Loader2 size={13} class="ui-spin" /> {apiDone.length}/{apiRows?.length || '…'}{:else}<Play size={13} /> {apiAt ? 'Run again' : 'Run'}{/if}</button>
        </div>
        <div class="ui-stats">
            <div class="ui-stat"><span class="ui-stat-label">Answered</span><span class="ui-stat-value" class:bad={apiBad}>{apiAt || apiDone.length ? apiDone.length - apiBad : '—'}<small>of {apiRows?.length ?? '—'}</small></span><span class="ui-stat-sub" class:bad={apiBad}>{apiBad ? `${apiBad} failing` : apiAt && !apiRunning ? 'all fine' : ' '}</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Median time</span><span class="ui-stat-value">{apiMedian ?? '—'}<small>ms</small></span><span class="ui-stat-sub">half answer faster than this</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Slowest</span><span class="ui-stat-value">{apiSlowest?.ms ?? '—'}<small>ms</small></span><span class="ui-stat-sub ui-mono slowpath">{apiSlowest?.path || ' '}</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Over a second</span><span class="ui-stat-value" class:slow={apiSlow}>{apiAt ? apiSlow : '—'}</span><span class="ui-stat-sub">{apiSkipped.length ? `${apiSkipped.length} more not called (they change things)` : ' '}</span></div>
        </div>
        <section class="ui-card">
            {#if apiRows}
                <div class="ui-tbl-wrap"><table class="ui-tbl api">
                    <colgroup><col /><col class="w-grp" /><col class="w-st" /><col class="w-ms" /></colgroup>
                    <thead><tr><th>Endpoint</th><th>Group</th><th class="num">Status</th><th class="num">Time</th></tr></thead>
                    <tbody>
                        {#each apiSorted as r}
                            <tr>
                                <td><span class="ep"><span class="ui-mono">{r.url}</span>{#if r.note}<small class="bad">{r.note}</small>{:else if r.desc}<small>{r.desc}</small>{/if}</span></td>
                                <td class="ui-dim">{r.group}</td>
                                <td class="num" class:bad={r.state === 'done' && !r.ok}>{#if r.state === 'done'}{r.code ?? '—'}{:else if r.state === 'run'}<Loader2 size={12} class="ui-spin" />{:else}<span class="ui-dim">—</span>{/if}</td>
                                <td class="num" class:slow={r.ms > 1000}>{r.ms != null ? r.ms + ' ms' : ''}</td>
                            </tr>
                        {/each}
                        {#if showSkipped}
                            {#each apiSkipped as r}
                                <tr class="skip">
                                    <td><span class="ep"><span class="ui-mono"><b class="mth">{r.method}</b>{r.path}</span><small>{r.desc || ''}</small></span></td>
                                    <td class="ui-dim">{r.group}</td>
                                    <td class="num ui-dim" colspan="2">{r.why}</td>
                                </tr>
                            {/each}
                        {/if}
                    </tbody>
                </table></div>
                {#if apiSkipped.length}
                    <button class="more-btn" on:click={() => showSkipped = !showSkipped}>
                        {showSkipped ? 'Hide' : 'Show'} the {apiSkipped.length} endpoints not called
                        <span class="mchev" class:open={showSkipped}><ChevronDown size={14} /></span>
                    </button>
                {/if}
            {:else}
                <div class="ui-empty">Loading the endpoint list…</div>
            {/if}
        </section>
    {:else if tab === 'uptime'}
        <UptimeTab embedded />
    {:else if tab === 'pihole'}
        <PiholeTab />
    {/if}
</div>

<style>

    .runbar .host { flex: 1; min-width: 200px; }
    .runbar .host input { width: 100%; }
    .runbar .host input.mono { font-family: 'JetBrains Mono', monospace; font-size: 13px; }
    .runbar .port { height: 32px; }
    .runbar .port { flex: 0 0 90px; min-width: 0; }

    .hist { table-layout: fixed; }
    .w-kind { width: 120px; } .w-target { width: 28%; } .w-when { width: 110px; }
    .hist td { overflow: hidden; text-overflow: ellipsis; }
    .res { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .res > span, .res small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .res small, .sub { font-size: 12px; color: var(--text-secondary); }
    .sub { display: block; margin-top: 2px; }
    .bad, .sub.bad { color: var(--red); }
    .slow { color: var(--yellow); }
    /* same quiet icon button as the ⋯ menus */
    .ib { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 6px; color: var(--text-secondary); cursor: pointer; }
    .ib:hover:not(:disabled) { background: var(--highlight-10); color: var(--text-primary); }
    .ib:disabled { opacity: .35; cursor: default; }
    .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .api { table-layout: fixed; }
    .w-grp { width: 130px; } .w-st { width: 90px; } .w-ms { width: 90px; }
    .api td { overflow: hidden; }
    .ep { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .ep > * { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ep .ui-mono { font-size: 12.5px; }
    .ep small { font-size: 12px; color: var(--text-secondary); }
    .ep small.bad { color: var(--red); }
    .mth { font-weight: 500; color: var(--text-secondary); margin-right: 8px; font-size: 11px; }
    tr.skip td { color: var(--text-secondary); }
    tr.skip .num { white-space: normal; text-align: right; font-size: 12px; }
    /* the From menu: same checkbox menu as the Overview's Customize */
    .pick { position: relative; }
    .pick-menu { position: absolute; right: 0; top: calc(100% + 6px); z-index: 60; width: 240px; padding: 6px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card, 8px); box-shadow: 0 10px 28px rgba(0, 0, 0, 0.14); }
    .pick-head { font-size: 12px; font-weight: 600; color: var(--text-secondary); padding: 6px 8px; }
    .pick-item { display: flex; align-items: center; gap: 10px; width: 100%; padding: 7px 8px; border-radius: 5px; font-size: 13.5px; color: var(--text-primary); text-align: left; cursor: pointer; }
    .pick-item:hover { background: var(--highlight-10); }
    .pick-ic { display: flex; color: var(--text-secondary); margin-left: -2px; }
    .pick-k { margin-left: auto; font-size: 12px; }
    .box { width: 16px; height: 16px; border-radius: 4px; border: 1px solid var(--border-strong); display: flex; align-items: center; justify-content: center; flex-shrink: 0; color: var(--surface); }
    .box.on { background: var(--text-primary); border-color: var(--text-primary); }
    .pick-foot { display: flex; gap: 16px; border-top: 1px solid var(--border); margin-top: 4px; padding: 8px 8px 4px; font-size: 13px; }

    .pc { display: flex; align-items: center; gap: 10px; min-width: 0; font-weight: 500; color: var(--text-primary); }
    .pc-ic { display: flex; color: var(--text-secondary); flex-shrink: 0; }
    .tgt { font-size: 14px; font-weight: 500; margin-left: 4px; }
    .w-pc { width: 200px; }
    .warn { color: var(--yellow); }
    .res-tbl td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .res-tbl { table-layout: fixed; }
    tr.click { cursor: pointer; }
    tr.click:hover td { background: var(--highlight-3); }
    tr.cur td:first-child { box-shadow: inset 2px 0 0 var(--accent); }
    :global(.dimspin) { color: var(--text-secondary); }
    .more-btn { display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%; padding: 12px 20px; border-top: 1px solid var(--border); font-size: 13px; font-weight: 500; color: var(--text-secondary); cursor: pointer; }
    .more-btn:hover { color: var(--text-primary); background: var(--highlight-3); }
    .mchev { display: flex; transition: transform .2s; }
    .mchev.open { transform: rotate(180deg); }
    .lead { font-size: 13px; }
    .slowpath { font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ui-stat-value.bad, .ui-stat-sub.bad { color: var(--red); }
    .push { margin-left: auto; }

    @media (max-width: 560px) {
            .runbar .ui-seg { width: 100%; }
        .runbar .ui-seg button { flex: 1; }
        .runbar .host { flex-basis: 100%; }
        /* the From button starts its row here, so the menu opens to the right */
        .pick-menu { left: 0; right: auto; }
        .w-pc { width: 120px; }
        .res-tbl .res small { white-space: normal; }
        .conn th:nth-child(3), .conn td:nth-child(3), .conn th:nth-child(4), .conn td:nth-child(4) { display: none; }
        /* phone: check over target, result beside it; no When column */
        .hist { table-layout: auto; }
        .hist colgroup, .hist th:nth-child(4), .hist td:nth-child(4) { display: none; }
        .api colgroup, .api th:nth-child(2), .api td:nth-child(2) { display: none; }
        .api { table-layout: auto; }
        /* speed history: responsiveness + latency are in the tiles above, units are in the tiles too */
        .spd th:nth-child(n+4), .spd td:nth-child(n+4) { display: none; }
        .spd .ui-dim { display: none; }
        /* endpoint column takes what's left and truncates, so Status/Time stay on screen */
        .api td:first-child { width: 100%; max-width: 0; }
        .res > span, .res small { white-space: normal; }
    }
</style>
