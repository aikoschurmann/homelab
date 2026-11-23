<script>
    import { copyText } from '../lib/clipboard.js';
    import { onMount } from 'svelte';
    import { Search, Send, Copy, Check, Loader2, AlertTriangle, ExternalLink } from 'lucide-svelte';
    import { visible } from '../lib/stores.js';
    import Tabs from './ui/Tabs.svelte';
    import StatusPill from './ui/StatusPill.svelte';
    import LiveChart from './ui/LiveChart.svelte';
    import { crumbLabels } from '../lib/stores.js';
    import { endpointGroups, fetchEndpoints } from '../lib/endpoints.js';

    // Routes: #endpoints, #endpoints/g-<group>, #endpoints/<id>[/history]
    export let section = null;
    export let sub = null;
    export let onNavigate = () => {};

    $: groups = $endpointGroups;
    let latency = {};          // "METHOD /path" -> [{ latency, status, timestamp }], newest first
    async function loadLatency() {
        try { const j = await fetch('/api/latency?limit=60').then(r => r.json()); if (j.status === 'success') latency = j.data; } catch (e) {}
    }
    onMount(() => {
        fetchEndpoints(); loadLatency();
        const t = setInterval(() => visible() && loadLatency(), 10000);
        return () => clearInterval(t);
    });

    const slug = (g) => 'g-' + g.toLowerCase();
    $: all = (groups || []).flatMap(g => g.endpoints.map(e => ({ ...e, group: g.name, key: `${e.method} ${e.path}` })));
    $: groupFilter = section?.startsWith('g-') ? section : null;
    $: endpoint = section && !groupFilter ? all.find(e => e.id === section) : null;
    // reactive, so rows redraw when `latency` arrives
    $: recs = (e) => latency[e.key] || [];
    const median = (xs) => { const v = [...xs].sort((a, b) => a - b); return v.length ? v[v.length >> 1] : null; };
    const fmtMs = (ms) => ms == null ? '—' : ms < 1 ? ms.toFixed(2) + ' ms' : ms < 10 ? ms.toFixed(1) + ' ms' : Math.round(ms) + ' ms';
    const shortPath = (p) => p.replace(/^\/api/, '');

    // ---- list -----------------------------------------------------------------------------
    let q = '', searchEl;
    let method = 'all';
    // every word must match somewhere: path, description, group or a parameter name
    const hay = (e) => `${e.method} ${e.path} ${e.desc} ${e.group} ${(e.params || []).map(p => p.key).join(' ')}`.toLowerCase();
    $: words = q.toLowerCase().split(/\s+/).filter(Boolean);
    $: shown = all.filter(e =>
        (!groupFilter || slug(e.group) === groupFilter) &&
        (method === 'all' || e.method === method) &&
        words.every(w => hay(e).includes(w)));
    $: shownGroups = (groups || []).map(g => ({ ...g, eps: shown.filter(e => e.group === g.name) })).filter(g => g.eps.length);
    $: activeGroup = groupFilter ? (groups || []).find(g => slug(g.name) === groupFilter) : null;
    const countIn = (g) => g.endpoints.length;

    // path with its {params} and the search words marked
    const esc = (t) => t.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    function mark(text, ws) {
        let h = esc(text);
        for (const w of ws) if (w.length > 1) h = h.replace(new RegExp(`(${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})(?![^<]*>)`, 'gi'), '<mark>$1</mark>');
        return h;
    }
    const pathHtml = (path, ws) => mark(path, ws).replace(/\{(\w+)\}/g, '<span class="pp">{$1}</span>');

    function onKey(e) {
        if (e.key === '/' && !endpoint && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') { e.preventDefault(); searchEl?.focus(); }
    }
    function searchKey(e) {
        if (e.key === 'Enter' && shown.length === 1) onNavigate('Endpoints', shown[0].id);
        if (e.key === 'Escape') q = '';
    }
    $: if (all.length) crumbLabels.update(c => ({ ...c, ...Object.fromEntries(all.map(e => [e.id, `${e.method} ${shortPath(e.path)}`])), ...Object.fromEntries((groups || []).map(g => [slug(g.name), g.name])) }));
    $: measured = all.filter(e => recs(e).length && e.group !== 'Internal');
    $: medAll = median(measured.map(e => recs(e)[0].latency));
    $: slowest = [...measured].sort((a, b) => recs(b)[0].latency - recs(a)[0].latency)[0];
    $: errors = measured.filter(e => recs(e)[0].status >= 500).length;

    // ---- try it ---------------------------------------------------------------------------
    let values = {};
    let shownId = null;
    $: if (endpoint && endpoint.id !== shownId) {
        shownId = endpoint.id;
        values = Object.fromEntries((endpoint.params || []).map(p => [p.key, p.value || '']));
        result = null; confirmSend = false;
    }
    $: pathKeys = endpoint ? [...endpoint.path.matchAll(/\{(\w+)\}/g)].map(m => m[1]) : [];
    $: reads = endpoint && endpoint.method === 'GET' && !/\/action\//.test(endpoint.path);
    $: missing = pathKeys.filter(k => !String(values[k] ?? '').trim());
    // a placeholder is a usable example unless it's a hint like "0 = automatic" or "(optional)"
    const usable = (ph) => ph && !/…|^\(|=|\bor\b/.test(ph);
    $: canFill = endpoint && (endpoint.params || []).some(p => usable(p.placeholder) && !String(values[p.key] ?? '').trim());
    function fillExamples() { values = Object.fromEntries((endpoint.params || []).map(p => [p.key, String(values[p.key] ?? '').trim() || (usable(p.placeholder) ? p.placeholder : '')])); }
    $: siblings = endpoint ? all.filter(e => e.group === endpoint.group && e.id !== endpoint.id) : [];

    function build(e, vals) {
        let path = e.path;
        const rest = {};
        for (const p of e.params || []) {
            const v = String(vals[p.key] ?? '').trim();
            if (pathKeys.includes(p.key)) { if (v) path = path.replace(`{${p.key}}`, encodeURIComponent(v)); }
            else if (v && v !== '(optional)') rest[p.key] = p.type === 'number' ? Number(v) : p.type === 'json' ? (() => { try { return JSON.parse(v); } catch (e) { return v; } })() : v;
        }
        const inQuery = e.method === 'GET' || e.method === 'DELETE';
        if (inQuery && Object.keys(rest).length) path += '?' + new URLSearchParams(rest).toString();
        return { url: path, body: !inQuery && Object.keys(rest).length ? rest : null };
    }
    $: req = endpoint ? build(endpoint, values) : null;
    $: curl = req ? `curl -X ${endpoint.method} '${location.origin}${req.url}'` + (req.body ? ` -H 'Content-Type: application/json' -d '${JSON.stringify(req.body)}'` : '') : '';

    let sending = false, result = null, confirmSend = false;
    async function send() {
        if (!reads && !confirmSend) { confirmSend = true; return; }
        confirmSend = false; sending = true;
        const started = performance.now();
        try {
            const res = await fetch(req.url, { method: endpoint.method, headers: req.body ? { 'Content-Type': 'application/json' } : {}, body: req.body ? JSON.stringify(req.body) : undefined });
            const text = await res.text();
            let pretty = text;
            try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch (e) {}
            const server = res.headers.get('X-Response-Time');
            result = {
                status: res.status, ok: res.ok,
                ms: server != null ? parseFloat(server) : performance.now() - started,
                size: new Blob([text]).size,
                type: res.headers.get('content-type') || '',
                body: pretty.length > 200000 ? pretty.slice(0, 200000) + '\n… (cut at 200 KB)' : pretty,
            };
        } catch (err) {
            result = { status: 0, ok: false, ms: performance.now() - started, size: 0, type: '', body: String(err) };
        }
        sending = false;
        loadLatency();
    }
    let copied = '';
    async function copy(text, what) { try { await copyText(text); copied = what; setTimeout(() => copied = '', 1200); } catch (e) {} }
    const fmtSize = (b) => b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(1) + ' KB' : (b / 1048576).toFixed(1) + ' MB';

    // ---- history --------------------------------------------------------------------------
    $: hist = endpoint ? recs(endpoint) : [];
    $: histPts = [...hist].reverse().map(r => [r.timestamp * 1000, r.latency]);
    $: histSpan = hist.length > 1 ? (hist[0].timestamp - hist[hist.length - 1].timestamp) * 1000 : 3600000;
    const when = (t) => new Date(t * 1000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' });
</script>

<svelte:window on:keydown={onKey} />

{#if !groups}
    <div class="ui-page"><div class="ui-dim">Loading endpoints…</div></div>

{:else if endpoint}
    {@const last = hist[0]}
    <div class="ui-page">
        <div class="ui-head">
            <div>
                <h1 class="ep-title"><span class="m {endpoint.method.toLowerCase()}">{endpoint.method}</span><span class="path">{endpoint.path}</span></h1>
                <p>{endpoint.desc}</p>
            </div>
            <div class="ui-head-actions">
                <button class="ui-btn" on:click={() => copy(curl, 'curl')}>{#if copied === 'curl'}<Check size={13} /> Copied{:else}<Copy size={13} /> Copy curl{/if}</button>
            </div>
        </div>

        <!-- same four tiles as the list -->
        <div class="summary">
            <div class="ui-stat"><span class="ui-stat-label">Median response</span><span class="ui-stat-value">{fmtMs(median(hist.map(r => r.latency)))}</span><span class="ui-stat-sub">{hist.length ? `over the last ${hist.length} ${hist.length === 1 ? 'call' : 'calls'}` : 'never called'}</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Last call</span><span class="ui-stat-value"><span class="code big" class:bad={last && last.status >= 400}>{last ? last.status : '—'}</span>{#if last}<small>{fmtMs(last.latency)}</small>{/if}</span><span class="ui-stat-sub">{last ? when(last.timestamp) : 'no calls recorded'}</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Group</span><span class="ui-stat-value"><button class="grp-link" on:click={() => onNavigate('Endpoints', slug(endpoint.group))}>{endpoint.group}</button></span><span class="ui-stat-sub">{siblings.length + 1} endpoints</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Kind</span><span class="ui-stat-value">{reads ? 'Read' : 'Change'}</span><span class="ui-stat-sub">{reads ? 'safe to send any time' : 'changes something on Arrakis'}</span></div>
        </div>

        <Tabs tabs={[{ id: 'try', label: 'Try it' }, { id: 'history', label: 'History' }]} active={sub === 'history' ? 'history' : 'try'} onSelect={(t) => onNavigate('Endpoints', endpoint.id, t === 'history' ? 'history' : null)} />

        {#if sub !== 'history'}
            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">Request</h2><p class="ui-card-desc">{endpoint.params?.length ? (reads ? 'Fill in the parameters, then send.' : 'Fill in the parameters. Sending asks you to confirm first.') : 'No parameters: send it as is.'}</p></div>
                    {#if canFill}<button class="ui-btn sm" on:click={fillExamples}>Fill in examples</button>{/if}</div>
                {#if endpoint.params?.length}
                    <div class="params">
                        {#each endpoint.params as p}
                            <div class="ui-form-row">
                                <div><label class="ui-label mono" for="p-{p.key}">{p.key}</label><div class="ui-hint">{pathKeys.includes(p.key) ? 'in the path, required' : endpoint.method === 'GET' || endpoint.method === 'DELETE' ? 'query string' : 'JSON body'}{p.type === 'number' ? ' · number' : p.type === 'json' ? ' · JSON' : ''}</div></div>
                                {#if p.type === 'json' && (p.placeholder || '').length > 24}
                                    <textarea id="p-{p.key}" class="ui-input mono json" rows="3" spellcheck="false" placeholder={p.placeholder} bind:value={values[p.key]}></textarea>
                                {:else}
                                    <input id="p-{p.key}" class="ui-input mono" type={p.type === 'number' ? 'number' : 'text'} placeholder={p.placeholder} bind:value={values[p.key]} />
                                {/if}
                            </div>
                        {/each}
                    </div>
                {/if}
                <!-- the URL that will be called, with the send button beside it -->
                <div class="reqbar">
                    <span class="m {endpoint.method.toLowerCase()}">{endpoint.method}</span>
                    <code class="url">{req.url}</code>
                    {#if confirmSend}<button class="ui-btn sm" on:click={() => confirmSend = false}>Cancel</button>{/if}
                    <button class="ui-btn sm {confirmSend ? 'danger' : 'primary'}" disabled={sending || missing.length} on:click={send}>
                        {#if sending}<Loader2 size={13} class="ui-spin" /> Sending…{:else if confirmSend}Yes, send{:else}<Send size={13} /> Send{/if}
                    </button>
                </div>
                {#if missing.length || confirmSend}
                    <div class="ui-card-foot">
                        <span>{#if missing.length}Fill in {missing.join(', ')} first.{:else}<span class="warn"><AlertTriangle size={13} /> This sends {endpoint.method} {req.url} and changes something on Arrakis.</span>{/if}</span>
                    </div>
                {/if}
            </section>

            {#if result}
                <section class="ui-card resp">
                    <div class="ui-card-head">
                        <div><h2 class="ui-card-title">Response</h2>
                            <p class="ui-card-desc">{result.type.split(';')[0] || 'no body'} · {fmtSize(result.size)} · {fmtMs(result.ms)}</p></div>
                        <span class="ui-btns">
                            <StatusPill state={result.ok ? 'running' : 'error'} label={result.status ? String(result.status) : 'Failed'} />
                            <button class="ui-btn sm icon" title="Copy response" on:click={() => copy(result.body, 'body')}>{#if copied === 'body'}<Check size={13} />{:else}<Copy size={13} />{/if}</button>
                        </span>
                    </div>
                    <pre class="body">{result.body}</pre>
                </section>
            {/if}

            {#if siblings.length}
                <section class="ui-card">
                    <div class="ui-card-head"><div><h2 class="ui-card-title">More in {endpoint.group} <span class="cnt">{siblings.length}</span></h2></div></div>
                    <div class="rows">
                        {#each siblings as e (e.id)}
                            {@const r = recs(e)}
                            {@const lastN = r.slice(0, 12).reverse()}
                            {@const top = Math.max(1, ...lastN.map(x => x.latency))}
                            <button class="row" on:click={() => onNavigate('Endpoints', e.id)}>
                                <span class="m {e.method.toLowerCase()}">{e.method === 'DELETE' ? 'DEL' : e.method}</span>
                                <span class="epn"><span class="path">{@html pathHtml(shortPath(e.path), [])}</span><small>{e.desc}</small></span>
                                <span class="bars">{#each lastN as x}<i class:bad={x.status >= 500} style="height: {Math.max(2, x.latency / top * 18)}px" title="{fmtMs(x.latency)} · {x.status}"></i>{/each}</span>
                                <span class="num">{r.length ? fmtMs(r[0].latency) : ''}</span>
                                <span class="st">{#if r.length}<span class="code" class:bad={r[0].status >= 400}>{r[0].status}</span>{:else}<span class="ui-dim">never called</span>{/if}</span>
                            </button>
                        {/each}
                    </div>
                </section>
            {/if}
        {:else}
            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">Response time</h2><p class="ui-card-desc">The last {hist.length} calls to this endpoint, from any client.</p></div></div>
                <div class="ui-card-body">
                    {#if histPts.length > 1}<LiveChart points={histPts} windowMs={histSpan * 1.05} unit=" ms" dots height={200} />
                    {:else}<div class="ui-empty">Not enough calls yet.</div>{/if}
                </div>
            </section>
            <section class="ui-card">
                <table class="ui-tbl">
                    <thead><tr><th>When</th><th>Status</th><th>Time</th></tr></thead>
                    <tbody>
                        {#each hist as r}
                            <tr><td>{when(r.timestamp)}</td><td><span class="code" class:bad={r.status >= 400}>{r.status}</span></td><td class="num">{fmtMs(r.latency)}</td></tr>
                        {:else}<tr><td colspan="3" class="ui-dim">No calls recorded.</td></tr>{/each}
                    </tbody>
                </table>
            </section>
        {/if}
    </div>

{:else}
    <div class="ui-page">
        <div class="ui-head">
            <div><h1>API endpoints</h1><p>Every route the dashboard backend serves on :5050, with live response times. Open one to try it.</p></div>
        </div>

        <div class="summary">
            <div class="ui-stat"><span class="ui-stat-label">Endpoints</span><span class="ui-stat-value">{all.length}</span><span class="ui-stat-sub">in {groups.length} groups</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Median response</span><span class="ui-stat-value">{fmtMs(medAll)}</span><span class="ui-stat-sub">latest call of each endpoint</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Slowest</span><span class="ui-stat-value">{slowest ? fmtMs(recs(slowest)[0].latency) : '—'}</span><span class="ui-stat-sub">{slowest ? `${slowest.method} ${shortPath(slowest.path)}` : '—'}</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Server errors</span><span class="ui-stat-value">{errors}</span><span class="ui-stat-sub">endpoints whose last call failed</span></div>
        </div>

        <Tabs tabs={[{ id: 'all', label: 'All' }, ...groups.map(g => ({ id: slug(g.name), label: g.name }))]} active={groupFilter || 'all'} onSelect={(t) => onNavigate('Endpoints', t === 'all' ? null : t)} />

            <div class="main">
                <div class="ui-listbar">
                    <label class="ui-search wide"><Search size={14} /><input bind:this={searchEl} placeholder="Search paths, descriptions, parameters…" bind:value={q} on:keydown={searchKey} /><kbd>/</kbd></label>
                    <div class="ui-seg">{#each ['all', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as m}<button class:on={method === m} on:click={() => method = m}>{m === 'all' ? 'All' : m === 'DELETE' ? 'DEL' : m}</button>{/each}</div>
                    <span class="ui-count">{shown.length} of {activeGroup ? countIn(activeGroup) : all.length}</span>
                </div>

                {#each shownGroups as g (g.name)}
                    <section class="ui-card">
                        <div class="ui-card-head"><div><h2 class="ui-card-title">{g.name} <span class="cnt">{g.eps.length}</span></h2>{#if g.doc}<p class="ui-card-desc">{g.doc}</p>{/if}</div></div>
                        <div class="rows">
                            {#each g.eps as e (e.id)}
                                {@const r = recs(e)}
                                {@const last = r.slice(0, 12).reverse()}
                                {@const top = Math.max(1, ...last.map(x => x.latency))}
                                <button class="row" on:click={() => onNavigate('Endpoints', e.id)}>
                                    <span class="m {e.method.toLowerCase()}">{e.method === 'DELETE' ? 'DEL' : e.method}</span>
                                    <span class="epn"><span class="path">{@html pathHtml(shortPath(e.path), words)}</span><small>{@html mark(e.desc, words)}</small></span>
                                    <span class="bars">{#each last as x}<i class:bad={x.status >= 500} style="height: {Math.max(2, x.latency / top * 18)}px" title="{fmtMs(x.latency)} · {x.status}"></i>{/each}</span>
                                    <span class="num">{r.length ? fmtMs(r[0].latency) : ''}</span>
                                    <span class="st">{#if r.length}<span class="code" class:bad={r[0].status >= 400}>{r[0].status}</span>{:else}<span class="ui-dim">never called</span>{/if}</span>
                                </button>
                            {/each}
                        </div>
                    </section>
                {:else}
                    <div class="ui-card ui-empty">Nothing matches "{q}".{#if groupFilter} <button class="ui-link" on:click={() => onNavigate('Endpoints', null)}>Search all groups</button>{/if}</div>
                {/each}
            </div>
    </div>
{/if}

<style>
    .main { display: grid; gap: 16px; min-width: 0; }
    .ui-search.wide { flex: 1 1 280px; width: auto; max-width: 460px; }
    kbd { font-family: 'JetBrains Mono', monospace; font-size: 11px; padding: 0 5px; border: 1px solid var(--border-strong); border-radius: 4px; color: var(--text-secondary); }
    .cnt { font-size: 12px; font-weight: 500; color: var(--text-secondary); margin-left: 4px; }
    .rows { border-top: 1px solid var(--border); }
    .row { display: grid; grid-template-columns: 56px minmax(0, 1fr) 70px 70px 90px; gap: 14px; align-items: center; width: 100%; padding: 10px 20px; text-align: left; border-top: 1px solid var(--border); cursor: pointer; }
    .row:first-child { border-top: none; }
    .row:hover { background: var(--highlight-3); }
    .row:hover .path { text-decoration: underline; }
    .row .num { text-align: right; font-size: 12.5px; color: var(--text-secondary); }
    .row .st { text-align: right; font-size: 12px; }
    .epn :global(mark) { background: color-mix(in srgb, var(--accent) 28%, transparent); color: inherit; border-radius: 2px; }
    .path :global(.pp) { color: var(--text-secondary); }
    .grp-link { color: var(--accent); cursor: pointer; }
    .grp-link:hover { text-decoration: underline; }
    textarea.json { height: auto; resize: vertical; min-height: 34px; padding: 7px 10px; font-size: 12px; line-height: 1.5; justify-self: stretch; }
    @media (max-width: 900px) {
        .row { grid-template-columns: 50px minmax(0, 1fr) 60px; padding: 10px 14px; }
        .row .bars, .row .st { display: none; }
            }
    .summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
    .reqbar { display: flex; align-items: center; gap: 12px; padding: 12px 16px 12px 20px; border-top: 1px solid var(--border); background: var(--highlight-3); }
    .reqbar .url { flex: 1; min-width: 0; font-family: 'JetBrains Mono', monospace; font-size: 12.5px; color: var(--text-primary); overflow-wrap: anywhere; }
    .code.big { font-size: 22px; }
    .ui-stat-value .grp-link { font: inherit; }
    .m { display: inline-flex; justify-content: center; min-width: 46px; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 600; background: var(--highlight-10); color: var(--text-secondary); box-sizing: border-box; }
    .m.get { background: rgba(74, 111, 165, 0.12); color: var(--blue); }
    .m.post { background: rgba(63, 125, 92, 0.12); color: var(--green); }
    .m.patch, .m.put { background: rgba(201, 147, 46, 0.14); color: var(--amber); }
    .m.delete { background: rgba(184, 76, 62, 0.12); color: var(--red); }
    .epn { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .path { font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 500; color: var(--accent); }
    .epn small { font-size: 12px; color: var(--text-secondary); white-space: normal; }
    .epn .path { overflow-wrap: anywhere; white-space: normal; }
    .bars { display: inline-flex; align-items: flex-end; gap: 2px; height: 18px; }
    .bars i { width: 4px; border-radius: 1px; background: var(--metric-cpu); opacity: 0.55; }
    .bars i.bad { background: var(--red); opacity: 1; }
    .num { font-variant-numeric: tabular-nums; }
    .code { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--green); }
    .code.bad { color: var(--red); }

    .ep-title { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .ep-title .m { font-size: 13px; padding: 4px 10px; }
    .ep-title .path { font-size: 18px; color: var(--text-primary); font-weight: 600; }
    .params { border-top: 1px solid var(--border); }
    .params .ui-form-row { grid-template-columns: 170px 1fr; }
    .params .ui-input { justify-self: stretch; }
    .mono { font-family: 'JetBrains Mono', monospace; }
    .warn { display: inline-flex; align-items: center; gap: 6px; color: var(--amber); }
    .resp .body { margin: 0; border-top: 1px solid var(--border); padding: 14px 20px; min-height: 240px; max-height: 620px; overflow: auto; font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text-primary); background: var(--highlight-3); border-radius: 0 0 var(--radius-card, 8px) var(--radius-card, 8px); }
    @media (max-width: 1100px) { .summary { grid-template-columns: 1fr 1fr; } }
    @media (max-width: 640px) { .epn .path { overflow-wrap: anywhere; white-space: normal; } .ep-title .path { font-size: 15px; overflow-wrap: anywhere; } }
    /* phone: cards inset 14px, so this lines up with the card's header */
    @media (max-width: 768px) { .reqbar, .resp .body { padding-left: 14px; padding-right: 14px; } }
</style>
