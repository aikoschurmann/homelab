<script>
    import { onMount } from 'svelte';
    import { Search, Loader2, RotateCw } from 'lucide-svelte';
    import { SN } from '../lib/server.js';

    // One search across every container's logs (all running OrbStack machines) and the Mac
    // apps' log files, newest first.
    let sources = null, q = '', since = '1h', problems = false, source = '', regex = false;
    let data = null, error = '', loading = false, seq = 0;
    const WINDOWS = [['15m', '15 min'], ['1h', '1 hour'], ['6h', '6 hours'], ['24h', '24 hours'], ['7d', '7 days']];

    async function search() {
        const my = ++seq;
        loading = true; error = '';
        const u = new URLSearchParams({ q, since, source, ...(problems ? { problems: '1' } : {}), ...(regex ? { regex: '1' } : {}) });
        try {
            const j = await fetch('/api/logs/search?' + u).then(r => r.json());
            if (my !== seq) return;
            if (j.status === 'success') data = j.data; else error = j.message;
        } catch (e) { if (my === seq) error = 'Search failed'; }
        finally { if (my === seq) loading = false; }
    }
    let timer;
    // typing waits a moment; switches search at once
    $: q, regex, (clearTimeout(timer), timer = setTimeout(search, 350));
    $: since, problems, source, search();
    onMount(async () => {
        try { const j = await fetch('/api/logs/sources').then(r => r.json()); if (j.status === 'success') sources = j.data; } catch (e) {}
    });

    const time = (t) => t ? new Date(t * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';
    const PROBLEM = /\b(error|errors|err|fatal|panic|exception|traceback|fail|failed|failure|critical|crit|warn|warning|denied|refused|timeout|timed out)\b/i;
    const esc = (s) => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
    function mark(line) {
        const e = esc(line);
        if (!q) return e;
        try {
            const rx = new RegExp(regex ? q : q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
            return e.replace(new RegExp(rx.source.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'), 'gi'), m => `<mark>${m}</mark>`);
        } catch (err) { return e; }
    }
    $: bySource = data ? Object.entries(data.by_source).sort((a, b) => b[1] - a[1]) : [];
</script>

<div class="ui-page">
    <div class="ui-head">
        <div><h1>Logs</h1><p>Every container in the running machines and the Mac apps' log files, searched together on {SN}.</p></div>
        <div class="ui-head-actions"><button class="ui-btn" on:click={search} disabled={loading}>{#if loading}<Loader2 size={14} class="ui-spin" />{:else}<RotateCw size={14} />{/if} Refresh</button></div>
    </div>

    <div class="ui-listbar">
        <label class="ui-search wide"><Search size={14} /><input placeholder={regex ? 'Pattern, e.g. timeout|refused' : 'Search the lines, or a container name'} bind:value={q} spellcheck="false" /></label>
        <select class="ui-select narrow" bind:value={source} aria-label="Where">
            <option value="">Everywhere</option>
            <option value="mac">The Mac's apps</option>
            {#each sources?.machines || [] as m}<option value={m}>Containers in {m}</option>{/each}
        </select>
        <select class="ui-select narrow" bind:value={since} aria-label="How far back">
            {#each WINDOWS as [v, l]}<option value={v}>Last {l}</option>{/each}
        </select>
        <div class="ui-seg">
            <button class:on={!problems} on:click={() => problems = false}>All lines</button>
            <button class:on={problems} on:click={() => problems = true}>Problems</button>
        </div>
        <label class="rx"><input type="checkbox" bind:checked={regex} /> Pattern</label>
        <span class="ui-count">{#if data}{data.total > data.lines.length ? `newest ${data.lines.length} of ${data.total}` : `${data.total} ${data.total === 1 ? 'line' : 'lines'}`} · {data.ms} ms{/if}</span>
    </div>

    {#if bySource.length > 1}
        <div class="chips">{#each bySource as [s, n]}<button class="chip" on:click={() => q = s}>{s} <span class="n">{n}</span></button>{/each}</div>
    {/if}

    <section class="ui-card">
        {#if error}
            <div class="ui-empty">{error}</div>
        {:else if !data}
            <div class="ui-empty"><Loader2 size={14} class="ui-spin" /> Searching…</div>
        {:else if !data.lines.length}
            <div class="ui-empty">{q || problems ? 'Nothing matches in this window.' : 'No log lines in this window.'}</div>
        {:else}
            <div class="lines" class:dim={loading}>
                {#each data.lines as r, i (i)}
                    <div class="ln" class:bad={PROBLEM.test(r.line)}>
                        <span class="t">{time(r.t)}</span>
                        <span class="s" title={r.where === 'mac' ? 'App on the Mac' : `Container in ${r.where}`}>{r.source}</span>
                        <span class="m">{@html mark(r.line)}</span>
                    </div>
                {/each}
            </div>
        {/if}
    </section>
</div>

<style>
    .ui-search.wide { width: 340px; }
    .narrow { width: auto; height: 32px; }
    .rx { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary); cursor: pointer; }
    .rx input { accent-color: var(--accent); }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: -8px; }
    .chip { height: 26px; padding: 0 10px; border-radius: 13px; border: 1px solid var(--border); background: var(--surface); font-size: 12px; color: var(--text-primary); cursor: pointer; }
    .chip:hover { border-color: var(--accent); color: var(--accent); }
    .lines { font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.55; max-height: calc(100vh - 300px); min-height: 200px; overflow: auto; }
    .ln { display: grid; grid-template-columns: 132px 120px minmax(0, 1fr); gap: 0 14px; padding: 3px 20px; border-bottom: 1px solid var(--border); }
    .ln:last-child { border-bottom: none; }
    .ln:hover { background: var(--highlight-3); }
    .t { color: var(--text-secondary); white-space: nowrap; }
    .s { color: var(--accent); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .m { color: var(--text-primary); white-space: pre-wrap; overflow-wrap: anywhere; }
    .ln.bad .m { color: var(--red); }
    .m :global(mark) { background: var(--accent-soft); color: var(--accent); border-radius: 2px; padding: 0 1px; }
    .dim { opacity: 0.55; }
    @media (max-width: 768px) {
        .ui-search.wide { width: 100%; }
        .ln { grid-template-columns: 1fr; padding: 6px 14px; }
        .t, .s { font-size: 11px; }
    }
</style>
