<script>
    import { onMount, onDestroy, tick } from 'svelte';
    import { RefreshCw, Play, Search } from 'lucide-svelte';

    export let kind;   // 'daemon' | 'container'
    export let id;

    let text = '';
    let source = null;
    let message = '';
    let error = '';
    let loading = true;
    let live = true;
    let lines = 200;
    let filter = '';
    let pre;
    let timer;

    async function load() {
        // keep the view pinned to the bottom only if the user hasn't scrolled up
        const atBottom = !pre || pre.scrollHeight - pre.scrollTop - pre.clientHeight < 24;
        try {
            const j = await fetch(`/api/services/logs/${kind}/${encodeURIComponent(id)}?lines=${lines}`).then(r => r.json());
            if (j.status === 'success') {
                text = j.log || '';
                source = j.source;
                message = j.message || '';
                error = '';
            } else {
                error = j.message || 'Could not read logs';
            }
        } catch (e) {
            error = 'Could not reach the dashboard backend';
        }
        loading = false;
        await tick();
        if (atBottom && pre) pre.scrollTop = pre.scrollHeight;
    }

    function schedule() {
        clearInterval(timer);
        if (live) timer = setInterval(load, 5000);
    }

    onMount(() => { load(); schedule(); });
    onDestroy(() => clearInterval(timer));

    $: q = filter.trim().toLowerCase();
    $: shown = (text ? text.split('\n') : []).filter(l => !q || l.toLowerCase().includes(q));

    function levelOf(line) {
        if (/\b(error|fatal|panic|exception|err|crit)\b/i.test(line)) return 'err';
        if (/\b(warn|warning|wrn)\b/i.test(line)) return 'warn';
        return '';
    }
</script>

<div class="log-viewer">
    <div class="ui-toolbar bar">
        <label class="ui-search"><Search size={14} /><input placeholder="Filter lines" bind:value={filter} /></label>
        <div class="ui-seg" title="Lines to fetch">
            {#each [200, 500, 1000] as n}<button class:on={lines === n} on:click={() => { lines = n; load(); }}>{n}</button>{/each}
        </div>
        <span class="spacer"></span>
        <button class="ui-btn sm" class:live title={live ? 'Pause live updates' : 'Resume live updates'} on:click={() => { live = !live; schedule(); }}>
            {#if live}<span class="pulse"></span> Live{:else}<Play size={13} /> Paused{/if}
        </button>
        <button class="ui-btn sm icon" title="Refresh now" on:click={load}><RefreshCw size={13} /></button>
    </div>
    <div class="log-body" bind:this={pre}>
        {#if loading}
            <div class="log-empty">Loading logs…</div>
        {:else if error}
            <div class="log-empty err">{error}</div>
        {:else if !text}
            <div class="log-empty">{message || 'No log output.'}</div>
        {:else if shown.length === 0}
            <div class="log-empty">No lines match “{filter}”.</div>
        {:else}
            {#each shown as line}<div class="log-line {levelOf(line)}">{line || ' '}</div>{/each}
        {/if}
    </div>
    <div class="log-source">{source || ' '}{q ? ` · ${shown.length} matching lines` : text ? ` · last ${text.split('\n').length} lines` : ''}</div>
</div>

<style>
    .log-viewer { display: flex; flex-direction: column; }
    .bar { gap: 8px; }
    .spacer { flex: 1; }
    .ui-btn.live { color: var(--green); }
    .pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--green); animation: pulse 1.6s ease-in-out infinite; }
    @keyframes pulse { 50% { opacity: .35; } }
    /* same dark pane as a terminal session's output */
    .log-body { background: #111214; color: #d6d8dc; padding: 12px 16px; height: 460px; overflow: auto; font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.55; }
    .log-line { white-space: pre-wrap; overflow-wrap: anywhere; }
    .log-line.err { color: #f28b82; }
    .log-line.warn { color: #f2c46d; }
    .log-empty { color: #9aa0a6; font-size: 13px; padding: 4px 0; font-family: 'Inter', sans-serif; }
    .log-empty.err { color: #f28b82; }
    .log-source { padding: 9px 16px; border-top: 1px solid var(--border); font-family: 'JetBrains Mono', monospace; font-size: 11.5px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; background: var(--highlight-3); border-radius: 0 0 var(--radius-card, 8px) var(--radius-card, 8px); }
    @media (max-width: 640px) { .log-body { height: 340px; font-size: 11px; padding: 10px; } .bar .ui-search { width: 100%; } }
</style>
