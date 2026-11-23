<script>
    import { SN } from '../lib/server.js';
    import { onMount } from 'svelte';
    import { Database, Search, Key, Play, Loader2, ChevronLeft, ChevronRight, Table2, ArrowUp, ArrowDown, Filter, Download, RefreshCw, RotateCw, Copy, X } from 'lucide-svelte';
    import Tabs from './ui/Tabs.svelte';
    import Modal from './ui/Modal.svelte';
    import { copyText } from '../lib/clipboard.js';
    import { ago } from '../lib/tailscale.js';
    import { databases as dbStore, fetchDatabases } from '../lib/databases.js';

    // Routes: #databases, #databases/<id>, #databases/<id>/<table>, #databases/<id>/query
    // Ids: a file on the Mac (metrics.db, jellyfin), or <machine>:<file> / <host>~<machine>:<file>
    // for a database inside a machine, which is browsed as a snapshot copied to the Mac.
    export let section = null;
    export let sub = null;
    export let onNavigate = () => {};

    let databases = null, error = '', rescanning = false;
    $: databases = $dbStore;
    async function load(refresh = false) {
        try { await fetchDatabases(refresh); }
        catch (e) { error = e.message === 'Failed to fetch' ? 'Could not reach the backend' : e.message; }
    }
    async function rescan() { rescanning = true; await load(true); rescanning = false; }
    onMount(() => load());

    let now = Date.now();
    onMount(() => { const t = setInterval(() => now = Date.now(), 15000); return () => clearInterval(t); });

    const go = (db = null, s = null) => onNavigate('Databases', db, s);
    const home = (p) => (p || '').replace(/^\/Users\/[^/]+/, '~');
    function size(b) {
        if (!b) return '0 B';
        const i = Math.floor(Math.log(b) / Math.log(1024));
        return +(b / 1024 ** i).toFixed(i >= 2 ? 1 : 0) + ' ' + ['B', 'KB', 'MB', 'GB', 'TB'][i];
    }
    const num = (n) => (n ?? 0).toLocaleString();
    const rowsOf = (db) => (db.tables || []).reduce((a, t) => a + Math.max(0, t.rows || 0), 0);
    const where = (d) => d.machine ? (d.host ? `${d.machine} on ${d.host_name}` : d.machine) : 'the Mac';
    const copiedAgo = (d, now) => d.snapshot ? 'copied ' + ago(new Date(d.snapshot.at * 1000).toISOString(), now) : 'not copied yet';

    // the list, grouped like the sidebar: the Mac first, then each machine
    $: groups = (() => {
        const out = [];
        for (const d of databases || []) {
            const key = `${d.host || ''}|${d.machine || ''}`;
            let g = out.find(x => x.key === key);
            if (!g) out.push(g = { key, title: d.machine || SN, sub: d.machine ? `Machine on ${d.host_name}` : 'The Mac', machine: !!d.machine, dbs: [] });
            g.dbs.push(d);
        }
        return out;
    })();

    $: db = section && databases?.find(d => d.id === section);
    $: tab = sub === 'query' ? 'query' : 'tables';
    // the largest table is shown until one is picked, so the Tables tab never opens empty
    $: biggest = db?.tables?.length ? [...db.tables].filter(t => !t.view).sort((a, b) => b.rows - a.rows)[0] || db.tables[0] : null;
    $: table = db && tab === 'tables' ? (sub ? db.tables?.find(t => t.name === sub) : biggest) : null;

    // ---- snapshot of a machine's database ---------------------------------------------------
    let copying = false, copyErr = '', copiedFor = null;
    async function copySnapshot() {
        copying = true; copyErr = '';
        try {
            const j = await fetch(`/api/databases/${encodeURIComponent(db.id)}/snapshot`, { method: 'POST' }).then(r => r.json());
            if (j.status !== 'success') copyErr = j.message;
            else { await load(); shownKey = ''; }
        } catch (e) { copyErr = 'Could not reach the backend'; }
        copying = false;
    }
    // first visit: copy it so there is something to browse
    $: if (db?.machine && !db.snapshot && copiedFor !== db.id && !copying) { copiedFor = db.id; copySnapshot(); }

    // ---- table browser ------------------------------------------------------------------
    let tq = '';
    $: tablesShown = (db?.tables || []).filter(t => !tq || t.name.toLowerCase().includes(tq.toLowerCase()));
    let view = 'data';
    let sort = null, dir = 'desc';      // null = newest first (rowid)
    let filters = {}, showFilters = false;
    let page = { columns: [], rows: [], offset: 0, limit: 50, total: null }, loadingRows = false, rowsErr = '';
    const params = () => {
        const p = new URLSearchParams();
        if (sort) { p.set('sort', sort); p.set('dir', dir); }
        const f = Object.fromEntries(Object.entries(filters).filter(([, v]) => v && v.trim()));
        if (Object.keys(f).length) p.set('f', JSON.stringify(f));
        return p;
    };
    let seq = 0;
    async function loadRows(offset = 0) {
        if (!db || !table) return;
        const my = ++seq;
        loadingRows = true; rowsErr = '';
        const p = params(); p.set('limit', 50); p.set('offset', offset);
        try {
            const j = await fetch(`/api/databases/${encodeURIComponent(db.id)}/tables/${encodeURIComponent(table.name)}/rows?${p}`).then(r => r.json());
            if (my !== seq) return;
            if (j.status === 'success') page = j.data; else rowsErr = j.message;
        } catch (e) { if (my === seq) rowsErr = 'Could not load rows'; }
        if (my === seq) loadingRows = false;
    }
    let shownKey = '';
    $: if (table && db && `${db.id}/${table.name}` !== shownKey) {
        shownKey = `${db.id}/${table.name}`;
        view = 'data'; sort = null; dir = 'desc'; filters = {}; showFilters = false;
        loadRows(0);
    }
    function sortBy(c) {
        // times newest first, everything else A→Z
        if (sort !== c) { sort = c; dir = tcols[page.columns.indexOf(c)] ? 'desc' : 'asc'; }
        else if (dir !== (tcols[page.columns.indexOf(c)] ? 'asc' : 'desc')) dir = dir === 'asc' ? 'desc' : 'asc';
        else { sort = null; dir = 'desc'; }
        loadRows(0);
    }
    let ft;
    function onFilter() { clearTimeout(ft); ft = setTimeout(() => loadRows(0), 350); }
    function clearFilters() { filters = {}; loadRows(0); }
    $: filtered = Object.values(filters).some(v => v && v.trim());
    $: total = page.total ?? table?.rows ?? null;
    $: more = total == null ? page.rows.length === page.limit : page.offset + page.rows.length < total;
    $: exportHref = db && table ? `/api/databases/${encodeURIComponent(db.id)}/tables/${encodeURIComponent(table.name)}/export.csv?${(sort, dir, filters, params())}` : '';

    // ---- cells: Unix times in time-named columns read as dates ----------------------------
    const TIME_COL = /time|date|stamp|seen|created|updated|modified|expires?|(^|_)(ts|at|last)$/i;
    function timeCols(cols, rows) {
        return cols.map((c, i) => {
            if (!TIME_COL.test(c)) return null;
            const v = rows.find(r => typeof r[i] === 'number')?.[i];
            if (v == null) return null;
            return v > 9.4e8 && v < 4.2e9 ? 1000 : v > 9.4e11 && v < 4.2e12 ? 1 : null;
        });
    }
    const fmtTime = (v, mul) => new Date(v * mul).toLocaleString([], { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    // raw integers (ids) without thousands separators; floats trimmed
    function fmtCell(v, mul) {
        if (v === null) return 'NULL';
        if (mul && typeof v === 'number') return fmtTime(v, mul);
        return typeof v === 'number' && !Number.isInteger(v) ? String(+v.toFixed(4)) : String(v);
    }
    $: tcols = timeCols(page.columns, page.rows);

    // ---- one row, opened ------------------------------------------------------------------
    let openRow = null;   // { columns, row, tcols }
    const copy = (t) => copyText(t).then(() => window.showToast?.('Copied'), () => {});
    const rowJson = (o) => JSON.stringify(Object.fromEntries(o.columns.map((c, i) => [c, o.row[i]])), null, 2);

    // ---- query console ------------------------------------------------------------------
    let sql = '', running = false, result = null, qErr = '';
    $: if (db && !sql) sql = biggest ? `SELECT * FROM "${biggest.name}" LIMIT 20` : 'SELECT name FROM sqlite_master';
    async function runQuery() {
        running = true; qErr = '';
        try {
            const j = await fetch(`/api/databases/${encodeURIComponent(db.id)}/query`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sql }) }).then(r => r.json());
            if (j.status === 'success') result = j.data; else { qErr = j.message; result = null; }
        } catch (e) { qErr = 'Could not reach the backend'; }
        running = false;
    }
    const onKey = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); runQuery(); } };
    let lastDb = null;
    $: if (db?.id !== lastDb) { lastDb = db?.id; sql = ''; result = null; qErr = ''; tq = ''; copyErr = ''; }
    $: qcols = result ? timeCols(result.columns, result.rows) : [];
    function exportResult() {
        const esc = (v) => v === null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
        const text = [result.columns, ...result.rows].map(r => r.map(esc).join(',')).join('\n');
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
        a.download = `${db.name.replace(/\W+/g, '_')}_query.csv`;
        a.click();
        URL.revokeObjectURL(a.href);
    }
</script>

{#if !databases}
    <div class="ui-page"><div class="ui-dim">{error || 'Loading databases…'}</div></div>

{:else if section && !db}
    <div class="ui-page"><div class="ui-head"><div><h1>{section}</h1><p>No database with this id. <button class="ui-link" on:click={() => go()}>All databases</button></p></div></div></div>

{:else if db}
    <div class="ui-page">
        <div class="ui-head">
            <div class="id">
                <span class="icon"><Database size={20} /></span>
                <div>
                    <h1>{db.name} <span class="ui-tag">{db.type}</span></h1>
                    <div class="ui-meta">
                        <span>{db.service}</span>
                        {#if db.machine}<span>In {where(db)}</span>{/if}
                        <span>{size(db.size_bytes)}</span>
                        {#if db.tables}<span>{db.tables.length} tables · {num(rowsOf(db))} rows</span>{/if}
                        <span class="ui-mono">{home(db.path)}</span>
                    </div>
                </div>
            </div>
            {#if db.machine}
                <div class="ui-head-actions">
                    <span class="ui-dim copied" title="Browsing a read-only copy; the live file in the machine is never touched">{copying ? 'Copying…' : copiedAgo(db, now)}</span>
                    <button class="ui-btn" on:click={copySnapshot} disabled={copying}><span class:ui-spin={copying} class="rc"><RefreshCw size={13} /></span> Copy again</button>
                </div>
            {/if}
        </div>
        <Tabs tabs={[{ id: 'tables', label: 'Tables' }, { id: 'query', label: 'Query' }]} active={tab} onSelect={(t) => go(db.id, t === 'query' ? 'query' : null)} />

        {#if db.error}
            <div class="ui-banner warn">{db.error}</div>
        {:else if copyErr}
            <div class="ui-banner warn">Couldn't copy it from {where(db)}: {copyErr}</div>
        {:else if !db.tables}
            <div class="ui-card ui-empty"><Loader2 size={14} class="ui-spin" /> Copying {db.name} from {where(db)}…</div>
        {:else if tab === 'tables'}
            <div class="browser">
                <aside class="ui-card tlist">
                    <label class="tsearch"><Search size={13} /><input placeholder="Filter tables" bind:value={tq} /></label>
                    <div class="titems">
                        {#each tablesShown as t (t.name)}
                            <button class="titem" class:on={table?.name === t.name} on:click={() => go(db.id, t.name)}>
                                <Table2 size={13} /><span class="tn">{t.name}</span><span class="tr">{t.view ? 'view' : num(t.rows)}</span>
                            </button>
                        {:else}<div class="ui-dim pad">No tables</div>{/each}
                    </div>
                </aside>

                <section class="ui-card tmain">
                    {#if table}
                        <div class="ui-card-head">
                            <div><h2 class="ui-card-title mono">{table.name}</h2><p class="ui-card-desc">{table.view ? 'View' : num(table.rows) + ' rows'} · {table.columns} columns{table.indexes ? ` · ${table.indexes} indexes` : ''}</p></div>
                            <div class="head-tools">
                                {#if view === 'data'}
                                    <button class="ui-btn sm" class:on={showFilters || filtered} on:click={() => showFilters = !showFilters}><Filter size={13} /> Filter{#if filtered}<span class="fcount">{Object.values(filters).filter(v => v && v.trim()).length}</span>{/if}</button>
                                    <a class="ui-btn sm" href={exportHref} download title="Up to 100,000 rows, with the current sort and filters"><Download size={13} /> CSV</a>
                                {/if}
                                <div class="ui-seg"><button class:on={view === 'data'} on:click={() => view = 'data'}>Data</button><button class:on={view === 'schema'} on:click={() => view = 'schema'}>Schema</button></div>
                            </div>
                        </div>
                        {#if view === 'schema'}
                            <div class="grid-wrap" style="border-top: 1px solid var(--border)">
                            <table class="ui-tbl">
                                <thead><tr><th>Column</th><th>Type</th><th>Key</th></tr></thead>
                                <tbody>
                                    {#each table.col_list || [] as c}
                                        <tr><td class="ui-mono">{c.name}</td><td class="ui-dim ui-mono">{c.type || '—'}</td><td>{#if c.pk}<span class="pk"><Key size={11} /> Primary</span>{/if}</td></tr>
                                    {/each}
                                </tbody>
                            </table>
                            </div>
                        {:else}
                            <div class="grid-wrap" style="border-top: 1px solid var(--border)">
                                {#if rowsErr}<div class="ui-empty">{rowsErr}</div>
                                {:else}
                                <table class="grid">
                                    <thead>
                                        <tr>{#each page.columns as c}
                                            <th><button class="sorter" class:on={sort === c} on:click={() => sortBy(c)} title="Sort by {c}">{c}<span class="arrow">{#if sort === c}{#if dir === 'asc'}<ArrowUp size={11} />{:else}<ArrowDown size={11} />{/if}{/if}</span></button></th>
                                        {/each}</tr>
                                        {#if showFilters}
                                            <tr class="frow">{#each page.columns as c}
                                                <th><input placeholder="contains…" bind:value={filters[c]} on:input={onFilter} aria-label="Filter {c}" /></th>
                                            {/each}</tr>
                                        {/if}
                                    </thead>
                                    <tbody class:dim={loadingRows}>
                                        {#each page.rows as r}
                                            <tr on:click={() => openRow = { columns: page.columns, row: r, tcols }}>
                                                {#each r as v, i}<td class:null={v === null} class:n={typeof v === 'number' && !tcols[i]} class:t={tcols[i] && typeof v === 'number'} title={String(v)}>{fmtCell(v, tcols[i])}</td>{/each}
                                            </tr>
                                        {/each}
                                    </tbody>
                                </table>
                                {#if !page.rows.length && !loadingRows}<div class="ui-empty">{filtered ? 'No rows match the filters.' : 'Empty table'}</div>{/if}
                                {/if}
                            </div>
                            <div class="ui-card-foot">
                                <span>{#if loadingRows}<Loader2 size={13} class="ui-spin" /> Loading…{:else if page.rows.length}Rows {num(page.offset + 1)}–{num(page.offset + page.rows.length)}{total != null ? ` of ${num(total)}` : ''}{filtered ? ' matching' : ''}{sort ? ` · by ${sort}` : ', newest first'}{/if}
                                    {#if filtered && !loadingRows}<button class="ui-link clr" on:click={clearFilters}><X size={12} /> Clear filters</button>{/if}</span>
                                <span class="ui-btns">
                                    <button class="ui-btn sm" disabled={page.offset === 0 || loadingRows} on:click={() => loadRows(Math.max(0, page.offset - page.limit))}><ChevronLeft size={14} /> Previous</button>
                                    <button class="ui-btn sm" disabled={!more || loadingRows} on:click={() => loadRows(page.offset + page.limit)}>Next <ChevronRight size={14} /></button>
                                </span>
                            </div>
                        {/if}
                    {:else}<div class="ui-empty">Pick a table on the left.</div>{/if}
                </section>
            </div>

        {:else}
            <section class="ui-card">
                <div class="ui-card-head"><div><h2 class="ui-card-title">Query</h2><p class="ui-card-desc">Read-only SQL against {db.name}{db.machine ? ' (the copy)' : ''}: SELECT, WITH, PRAGMA or EXPLAIN, up to 500 rows and 5 seconds.</p></div></div>
                <div class="editor" style="border-top: 1px solid var(--border)">
                    <textarea bind:value={sql} on:keydown={onKey} spellcheck="false" rows="5" aria-label="SQL"></textarea>
                </div>
                <div class="ui-card-foot">
                    <span>{#if qErr}<span class="err">{qErr}</span>{:else if result}{num(result.rows.length)} rows{result.truncated ? ' (first 500)' : ''} · {result.ms} ms{:else}⌘ Enter runs the query{/if}</span>
                    <span class="ui-btns">
                        {#if result?.rows.length}<button class="ui-btn sm" on:click={exportResult}><Download size={13} /> CSV</button>{/if}
                        <button class="ui-btn sm primary" disabled={running || !sql.trim()} on:click={runQuery}>{#if running}<Loader2 size={13} class="ui-spin" />{:else}<Play size={13} />{/if} Run</button>
                    </span>
                </div>
            </section>
            {#if result}
                <section class="ui-card">
                    <div class="grid-wrap tall">
                        <table class="grid">
                            <thead><tr>{#each result.columns as c}<th><span class="sorter static">{c}</span></th>{/each}</tr></thead>
                            <tbody>{#each result.rows as r}<tr on:click={() => openRow = { columns: result.columns, row: r, tcols: qcols }}>{#each r as v, i}<td class:null={v === null} class:n={typeof v === 'number' && !qcols[i]} class:t={qcols[i] && typeof v === 'number'} title={String(v)}>{fmtCell(v, qcols[i])}</td>{/each}</tr>{/each}</tbody>
                        </table>
                        {#if !result.rows.length}<div class="ui-empty">No rows</div>{/if}
                    </div>
                </section>
            {/if}
        {/if}
    </div>

    <Modal open={!!openRow} title={table && tab === 'tables' ? `Row in ${table.name}` : 'Row'} width={620} onClose={() => openRow = null}>
        {#if openRow}
            <dl class="rowview">
                {#each openRow.columns as c, i}
                    {@const v = openRow.row[i]}
                    <div>
                        <dt>{c}</dt>
                        <dd class:null={v === null}>
                            <span class="v">{v === null ? 'NULL' : typeof v === 'number' && !openRow.tcols[i] ? fmtCell(v) : String(v)}</span>
                            {#if openRow.tcols[i] && typeof v === 'number'}<small>{fmtTime(v, openRow.tcols[i])}</small>{/if}
                        </dd>
                    </div>
                {/each}
            </dl>
        {/if}
        <svelte:fragment slot="footer">
            <button class="ui-btn sm" on:click={() => copy(rowJson(openRow))}><Copy size={13} /> Copy as JSON</button>
            <button class="ui-btn sm" on:click={() => openRow = null}>Close</button>
        </svelte:fragment>
    </Modal>

{:else}
    <div class="ui-page">
        <div class="ui-head">
            <div><h1>Databases</h1><p>SQLite databases on the Mac and inside its machines. Browsing is read-only; a machine's database is copied to the Mac first.</p></div>
            <div class="ui-head-actions"><button class="ui-btn" on:click={rescan} disabled={rescanning}><span class:ui-spin={rescanning} class="rc"><RotateCw size={14} /></span> Refresh</button></div>
        </div>
        <div class="summary">
            <div class="ui-stat"><span class="ui-stat-label">Databases</span><span class="ui-stat-value">{databases.length}</span><span class="ui-stat-sub">on the Mac and {groups.filter(g => g.machine).length} {groups.filter(g => g.machine).length === 1 ? 'machine' : 'machines'}</span></div>
            <div class="ui-stat"><span class="ui-stat-label">On disk</span><span class="ui-stat-value">{size(databases.reduce((a, d) => a + (d.size_bytes || 0), 0))}</span><span class="ui-stat-sub">all files together</span></div>
            <div class="ui-stat"><span class="ui-stat-label">Rows</span><span class="ui-stat-value">{num(databases.reduce((a, d) => a + rowsOf(d), 0))}</span><span class="ui-stat-sub">across {databases.reduce((a, d) => a + (d.tables?.length || 0), 0)} tables{databases.some(d => !d.tables) ? ', not counting ones not copied yet' : ''}</span></div>
        </div>
        {#each groups as g (g.key)}
            <section class="ui-card">
                <div class="ui-card-head grp"><div><h2 class="ui-card-title">{g.title}</h2><p class="ui-card-desc">{g.sub}</p></div>
                    {#if g.machine}<a class="ui-link" href="#infra/vm-{g.dbs[0].host ? encodeURIComponent(g.dbs[0].host) + '~' : ''}{encodeURIComponent(g.dbs[0].machine)}">Open machine</a>{/if}
                </div>
                <div class="ui-tbl-wrap">
                    <table class="ui-tbl dbs">
                        <colgroup><col /><col class="w-by" /><col class="w-n" /><col class="w-r" /><col class="w-s" /></colgroup>
                        <thead><tr><th>Database</th><th>Used by</th><th>Tables</th><th>Rows</th><th>Size</th></tr></thead>
                        <tbody>
                            {#each g.dbs as d (d.id)}
                                <tr class="click" on:click={() => go(d.id)}>
                                    <td>
                                        <div class="dbn"><span class="ic"><Database size={15} /></span>
                                            <span class="dbm"><span class="nm">{d.name}</span><small><span class="ui-mono">{home(d.path)}</span>{#if d.machine}{' · ' + copiedAgo(d, now)}{/if}</small></span>
                                        </div>
                                    </td>
                                    <td>{d.service}</td>
                                    <td class="num">{d.tables ? d.tables.length : '—'}</td>
                                    <td class="num">{d.tables ? num(rowsOf(d)) : '—'}</td>
                                    <td class="num">{size(d.size_bytes)}</td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </section>
        {/each}
        {#if !databases.length}<div class="ui-card ui-empty">No databases found.</div>{/if}
    </div>
{/if}

<style>
    .summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
    .id { display: flex; align-items: center; gap: 16px; min-width: 0; }
    .icon { width: 52px; height: 52px; border-radius: 12px; display: flex; align-items: center; justify-content: center; background: var(--accent-soft); color: var(--accent); flex-shrink: 0; }
    .ui-head h1 { line-height: 1.2; }
    .id .ui-meta { margin-top: 6px; }
    .copied { font-size: 12.5px; }
    .rc { display: inline-flex; }
    .grp { align-items: center; }

    /* list */
    .dbs { table-layout: fixed; }
    .dbs td { overflow: hidden; text-overflow: ellipsis; }
    .w-by { width: 140px; } .w-n { width: 90px; } .w-r { width: 120px; } .w-s { width: 100px; }
    .dbn { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .dbm { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .dbm small { font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .dbm small .ui-mono { font-size: 11.5px; }
    .ic { width: 30px; height: 30px; border-radius: 7px; background: var(--accent-soft); color: var(--accent); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .nm { font-weight: 600; color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    tr.click:hover .nm { text-decoration: underline; }
    .num { font-variant-numeric: tabular-nums; }
    .mono { font-family: 'JetBrains Mono', monospace; font-size: 14px; }

    /* table browser */
    /* the table list and the open table share one height; each scrolls inside itself */
    .browser { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 16px; height: clamp(440px, calc(100vh - 250px), 960px); }
    .tlist { display: flex; flex-direction: column; min-height: 0; }
    .tsearch { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--border); color: var(--text-secondary); }
    .tsearch input { border: none; outline: none; background: transparent; font: inherit; font-size: 13px; color: var(--text-primary); width: 100%; }
    .titems { overflow-y: auto; padding: 6px; flex: 1; min-height: 0; }
    .titem { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 8px; border-radius: 6px; font-size: 13px; color: var(--text-secondary); cursor: pointer; text-align: left; }
    .titem:hover { background: var(--highlight-5); color: var(--text-primary); }
    .titem.on { background: var(--accent-soft); color: var(--accent); }
    .tn { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: 'JetBrains Mono', monospace; font-size: 12.5px; }
    .tr { font-size: 11.5px; font-variant-numeric: tabular-nums; color: var(--text-secondary); }
    .pad { padding: 10px; }
    .tmain { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
    .tmain > .ui-empty { margin: auto; }
    .pk { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--amber); }
    .head-tools { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .head-tools .ui-btn.on { border-color: var(--accent); color: var(--accent); }
    .fcount { font-size: 11px; font-weight: 600; min-width: 16px; height: 16px; padding: 0 4px; border-radius: 8px; background: var(--accent-soft); display: inline-flex; align-items: center; justify-content: center; box-sizing: border-box; }
    .clr { display: inline-flex; align-items: center; gap: 3px; margin-left: 10px; font-size: 12.5px; }

    /* data grid: wide tables scroll inside the grid only */
    .grid-wrap { overflow: auto; max-height: 560px; }
    .tmain .grid-wrap { flex: 1; min-height: 0; max-height: none; }
    .grid-wrap.tall { max-height: 640px; }
    .grid { border-collapse: collapse; font-family: 'JetBrains Mono', monospace; font-size: 12px; min-width: 100%; }
    .grid th { position: sticky; top: 0; background: var(--surface); box-shadow: inset 0 -1px 0 var(--border); text-align: left; padding: 0; white-space: nowrap; z-index: 1; }
    .grid .frow th { top: 33px; padding: 4px 6px; }
    .sorter { display: flex; align-items: center; gap: 4px; width: 100%; padding: 8px 12px; font-family: 'Inter', sans-serif; font-weight: 600; font-size: 12px; color: var(--text-secondary); cursor: pointer; text-align: left; white-space: nowrap; }
    .sorter:hover { color: var(--text-primary); }
    .sorter.on { color: var(--accent); }
    .sorter.static { cursor: default; }
    .sorter.static:hover { color: var(--text-secondary); }
    .arrow { display: inline-flex; width: 11px; }
    .frow input { width: 100%; min-width: 80px; box-sizing: border-box; height: 26px; padding: 0 7px; border-radius: 5px; border: 1px solid var(--border-strong); background: var(--highlight-3); color: var(--text-primary); font: inherit; font-family: 'Inter', sans-serif; font-size: 12px; font-weight: 400; outline: none; }
    .frow input:focus { border-color: var(--accent); }
    .grid td { padding: 6px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; max-width: 280px; overflow: hidden; text-overflow: ellipsis; color: var(--text-primary); }
    .grid td.n { text-align: right; font-variant-numeric: tabular-nums; }
    .grid td.t { font-family: 'Inter', sans-serif; font-variant-numeric: tabular-nums; color: var(--text-primary); }
    .grid td.null { color: var(--text-secondary); font-style: italic; }
    .grid tbody tr { cursor: pointer; }
    .grid tbody tr:hover td { background: var(--highlight-3); }
    .grid tbody.dim { opacity: 0.5; transition: opacity .15s; }

    /* one row */
    .rowview { margin: 0; display: flex; flex-direction: column; max-height: 60vh; overflow-y: auto; }
    .rowview > div { display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--border); }
    .rowview > div:last-child { border-bottom: none; }
    .rowview dt { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-secondary); overflow-wrap: anywhere; }
    .rowview dd { margin: 0; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .rowview .v { font-family: 'JetBrains Mono', monospace; font-size: 12.5px; color: var(--text-primary); white-space: pre-wrap; overflow-wrap: anywhere; }
    .rowview dd.null .v { color: var(--text-secondary); font-style: italic; }
    .rowview small { font-size: 12px; color: var(--text-secondary); }

    .editor textarea { display: block; width: 100%; box-sizing: border-box; border: none; outline: none; resize: vertical; padding: 14px 20px; font-family: 'JetBrains Mono', monospace; font-size: 13px; line-height: 1.6; background: var(--highlight-3); color: var(--text-primary); min-height: 110px; }
    .err { color: var(--red); }
    @media (max-width: 900px) { .browser { grid-template-columns: 1fr; grid-template-rows: 240px 560px; height: auto; } .summary { grid-template-columns: 1fr; } }
    @media (max-width: 760px) {
        .w-by { width: 0; } .dbs th:nth-child(2), .dbs td:nth-child(2) { padding: 0; font-size: 0; }
        .w-n { width: 0; } .dbs th:nth-child(3), .dbs td:nth-child(3) { padding: 0; font-size: 0; }
        .w-r { width: 88px; } .w-s { width: 84px; }
        .rowview > div { grid-template-columns: 1fr; gap: 2px; }
    }
    /* phone: cards inset 14px, so this lines up with the card's header */
    @media (max-width: 768px) { .editor textarea { padding-left: 14px; padding-right: 14px; } }
</style>
