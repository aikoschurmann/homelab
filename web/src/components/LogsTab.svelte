<script>
    import { onMount } from 'svelte';
    import { Search, Loader2, RotateCw } from 'lucide-svelte';
    import { SN } from '../lib/server.js';

    // One search across every container's logs (all running OrbStack machines) and the Mac
    // apps' log files, newest first. A search starting with / is a pattern (regex).
    let sources = null, q = '', since = '1h', problems = false, source = '';
    let data = null, error = '', loading = false, seq = 0;
    const WINDOWS = [['15m', '15 min'], ['1h', '1 h'], ['6h', '6 h'], ['24h', '24 h'], ['7d', '7 days']];

    $: regex = q.startsWith('/') && q.length > 1;
    $: term = regex ? q.slice(1).replace(/\/$/, '') : q;
    async function search() {
        const my = ++seq;
        loading = true; error = '';
        const u = new URLSearchParams({ q: term, since, source, ...(problems ? { problems: '1' } : {}), ...(regex ? { regex: '1' } : {}) });
        try {
            const j = await fetch('/api/logs/search?' + u).then(r => r.json());
            if (my !== seq) return;
            if (j.status === 'success') data = j.data; else error = j.message;
        } catch (e) { if (my === seq) error = 'Search failed'; }
        finally { if (my === seq) loading = false; }
    }
    let timer;
    // typing waits a moment; the switches search at once
    $: term, (clearTimeout(timer), timer = setTimeout(search, 350));
    $: since, problems, source, search();
    onMount(async () => {
        try { const j = await fetch('/api/logs/sources').then(r => r.json()); if (j.status === 'success') sources = j.data; } catch (e) {}
    });

    const time = (t) => {
        if (!t) return '—';
        const d = new Date(t * 1000), today = new Date().toDateString() === d.toDateString();
        return today ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                     : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    };
    const PROBLEM = /\b(error|errors|err|fatal|panic|exception|traceback|fail|failed|failure|critical|crit|warn|warning|denied|refused|timeout|timed out)\b/i;
    // the time column already says when: drop a timestamp the line starts with
    const STAMP = /^\s*[[(]?\w?\)?\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s*(?:Z|[+-]\d{2}:?\d{2})?[\])]?\s*(?:-\s*)?/;
    const esc = (s) => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
    function mark(line) {
        const e = esc(line.replace(STAMP, ''));
        if (!term) return e;
        try {
            const rx = new RegExp(regex ? term : term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
            // match on the escaped text so a highlight can't break the markup
            return e.replace(new RegExp(esc(rx.source), 'gi'), m => `<mark>${m}</mark>`);
        } catch (err) { return e; }
    }
</script>

<div class="ui-page">
    <div class="ui-head">
        <div><h1>Logs</h1><p>Every container in the running machines and the Mac apps' log files, searched together on {SN}.</p></div>
        <div class="ui-head-actions"><button class="ui-btn" on:click={search} disabled={loading}>{#if loading}<Loader2 size={14} class="ui-spin" />{:else}<RotateCw size={14} />{/if} Refresh</button></div>
    </div>

    <div class="ui-listbar">
        <label class="ui-search"><Search size={14} /><input placeholder="Search, or /pattern/" bind:value={q} spellcheck="false" /></label>
        <div class="ui-seg">{#each WINDOWS as [v, l]}<button class:on={since === v} on:click={() => since = v}>{l}</button>{/each}</div>
        <div class="ui-seg">
            <button class:on={!problems} on:click={() => problems = false}>All</button>
            <button class:on={problems} on:click={() => problems = true}>Problems</button>
        </div>
        <span class="ui-count">{#if data}{data.total > data.lines.length ? `newest ${data.lines.length} of ${data.total}` : `${data.total} ${data.total === 1 ? 'line' : 'lines'}`}{/if}</span>
        <select class="ui-select src" bind:value={source} aria-label="Where">
            <option value="">Everywhere</option>
            <option value="mac">Apps on the Mac</option>
            {#each sources?.machines || [] as m}<option value={m}>Containers in {m}</option>{/each}
        </select>
    </div>

    <section class="ui-card">
        {#if error}
            <div class="ui-empty">{error}</div>
        {:else if !data}
            <div class="ui-empty"><Loader2 size={14} class="ui-spin" /> Searching…</div>
        {:else if !data.lines.length}
            <div class="ui-empty">{term || problems ? 'Nothing matches in this window.' : 'No log lines in this window.'}</div>
        {:else}
            <div class="ui-tbl-wrap scroll" class:dim={loading}>
                <table class="ui-tbl">
                    <thead><tr><th class="shrink tcol">Time</th><th class="shrink c-sm">Source</th><th>Message</th></tr></thead>
                    <tbody>
                        {#each data.lines as r, i (i)}
                            <tr>
                                <td class="t tcol"><span class="lvl" class:bad={PROBLEM.test(r.line)}></span>{time(r.t)}</td>
                                <td class="c-sm s" title={r.where === 'mac' ? 'App on the Mac' : `Container in ${r.where}`}>{r.source}</td>
                                <td class="m"><div class="when"><span class="lvl" class:bad={PROBLEM.test(r.line)}></span>{time(r.t)} · {r.source}</div>{@html mark(r.line)}</td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </div>
        {/if}
    </section>
</div>

<style>
    .src { width: auto; height: 32px; }
    .scroll { max-height: calc(100vh - 260px); overflow-y: auto; }
    .scroll thead th { position: sticky; top: 0; background: var(--surface); z-index: 1; }
    .ui-tbl td { padding-top: 8px; padding-bottom: 8px; vertical-align: top; }
    .ui-tbl tbody tr:first-child td { padding-top: 10px; }
    .t { color: var(--text-secondary); font-variant-numeric: tabular-nums; font-size: 12.5px; }
    .lvl { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 8px; vertical-align: middle; background: transparent; }
    .lvl.bad { background: var(--red); }
    .s { font-weight: 500; max-width: 160px; overflow: hidden; text-overflow: ellipsis; }
    .m { white-space: pre-wrap; overflow-wrap: anywhere; font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.5; width: 100%; }
    .m :global(mark) { background: var(--accent-soft); color: var(--accent); border-radius: 2px; padding: 0 1px; }
    .dim { opacity: 0.55; }
    .t { white-space: nowrap; }
    .when { display: none; }
    /* phone: time and source go on a grey line above the message, which gets the full width */
    @media (max-width: 640px) {
        .src { width: 100%; }
        .tcol { display: none; }
        .when { display: block; font-family: 'Inter', sans-serif; font-size: 11.5px; color: var(--text-secondary); margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .when .lvl:not(.bad) { display: none; }
        .ui-tbl .m, .ui-tbl th:last-child { padding-left: 14px; }
    }
</style>
