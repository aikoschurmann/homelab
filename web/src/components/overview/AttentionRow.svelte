<script>
    import { onMount } from 'svelte';
    import { visible } from '../../lib/stores.js';

    // What may want a look: package updates on every computer, Compose apps with a newer
    // image or a stopped container, and the backups. Each tile opens its page. Bars are one
    // theme colour each, split into shades, like the cluster tiles below.
    export let now = Date.now();
    export let pendingUpdates = 0;
    export let updTargets = [];
    export let backup = null;          // /api/backups/details
    export let hide = [];              // parts left out under Customize: 'updates', 'apps', 'backups'
    $: parts = ['updates', 'apps', 'backups'].filter(x => !hide.includes(x));

    let apps = null, runs = null;
    async function fetchApps() {
        try { const j = await fetch('/api/apps/installed').then(r => r.json()); if (j.status === 'success') apps = j.data; } catch (e) {}
    }
    async function fetchRuns() {
        try { const j = await fetch('/api/backups/runs').then(r => r.json()); if (j.status === 'success') runs = j.data; } catch (e) {}
    }
    onMount(() => {
        fetchApps(); fetchRuns();
        const t = setInterval(() => { if (visible()) { fetchApps(); fetchRuns(); } }, 60000);
        return () => clearInterval(t);
    });

    const SHADES = [1, 0.7, 0.5, 0.35, 0.25];
    const pct = (a, b) => b ? a / b * 100 : 0;
    const ago = (t) => { const s = Math.max(0, now / 1000 - t); return s < 90 ? 'just now' : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`; };
    const inT = (t) => { const s = Math.max(0, t - now / 1000); return s < 3600 ? `in ${Math.round(s / 60)} min` : `in ${Math.round(s / 3600)} h`; };

    // updates: one part per computer, most first
    // past three computers the rest share one "N others" part, like the cluster tiles
    $: updAll = [...updTargets].sort((a, b) => b.packages.length - a.packages.length).map(t => ({ name: t.name, n: t.packages.length }));
    $: updSegs = [
        ...(updAll.length > 4 ? updAll.slice(0, 3) : updAll).map((x, i) => ({ ...x, shade: SHADES[i] })),
        ...(updAll.length > 4 ? [{ name: `${updAll.length - 3} others`, n: updAll.slice(3).reduce((a, x) => a + x.n, 0), shade: 0.25 }] : []),
    ];

    // apps: fine, newer image, not fully running
    $: projects = apps?.projects || [];
    $: appUpd = projects.filter(p => p.updates);
    $: appDown = projects.filter(p => p.running < p.containers.length);
    $: appSegs = [
        { name: 'up to date', n: projects.length - new Set([...appUpd, ...appDown]).size, shade: 1 },
        { name: 'newer image', n: appUpd.length, shade: 0.5 },
        { name: 'not running', n: appDown.length, shade: 0.3, bad: true },
    ].filter(s => s.n);

    // backups: the last 14 days, one cell each (a day with a good run is filled, a failed one red)
    const DAYS = 14;
    $: days = (() => {
        const out = [], end = new Date(now); end.setHours(0, 0, 0, 0);
        const keyOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        // today counts once it has run; before that the strip ends yesterday
        if (!(runs || []).some(r => r.timestamp.startsWith(keyOf(end)))) end.setDate(end.getDate() - 1);
        for (let i = DAYS - 1; i >= 0; i--) {
            const d = new Date(end); d.setDate(d.getDate() - i);
            const key = keyOf(d);
            const day = (runs || []).filter(r => r.timestamp.startsWith(key));
            const state = day.some(r => r.state === 'ok') ? 'ok' : day.some(r => r.state === 'failed' || r.state === 'error') ? 'bad' : day.length ? 'other' : 'none';
            out.push({ key, state, label: d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) });
        }
        return out;
    })();
    $: okDays = days.filter(d => d.state === 'ok').length;
    // a daily backup older than two days means a run was missed
    $: stale = backup?.last_success && now / 1000 - backup.last_success > 2 * 86400;
</script>

{#if parts.length}
<section class="ui-card att" style="grid-template-columns: repeat({parts.length}, minmax(0, 1fr))">
    {#if parts.includes('updates')}
    <a class="cell" href="#updates">
        <span class="ui-stat-label"><span class="lg">Package updates</span><span class="sm">Updates</span></span>
        <span class="ui-stat-value">{pendingUpdates}<small>{pendingUpdates ? `on ${updAll.length} ${updAll.length === 1 ? 'computer' : 'computers'}` : 'all up to date'}</small></span>
        <div class="ui-segbar wide" title={updAll.map(x => `${x.name}: ${x.n}`).join('\n')}>{#each updSegs as s}<i style="width: {pct(s.n, pendingUpdates)}%; background: var(--metric-net); opacity: {s.shade}"></i>{/each}</div>
        <span class="ui-stat-sub ph">{pendingUpdates ? `${updAll.length} ${updAll.length === 1 ? 'computer' : 'computers'}` : 'up to date'}</span>
        <span class="ui-stat-sub short">{!pendingUpdates ? 'nothing to install' : updAll.length === 1 ? `all on ${updAll[0].name}` : `most on ${updAll[0].name} (${updAll[0].n})`}</span>
        <span class="ui-stat-sub ui-legend wide">{#each updSegs as s}<span><b style="background: var(--metric-net); opacity: {s.shade}"></b>{s.name} {s.n}</span>{:else}nothing to install{/each}</span>
    </a>
    {/if}
    {#if parts.includes('apps')}
    <a class="cell" href="#apps/installed">
        <span class="ui-stat-label">Apps</span>
        <span class="ui-stat-value">{apps ? projects.length : '—'}<small>{apps ? (appUpd.length || appDown.length ? `${appUpd.length + appDown.length} need a look` : 'all fine') : ''}</small></span>
        <div class="ui-segbar wide">{#each appSegs as s}<i style="width: {pct(s.n, projects.length)}%; background: {s.bad ? 'var(--red)' : 'var(--metric-disk)'}; opacity: {s.bad ? 1 : s.shade}"></i>{/each}</div>
        <span class="ui-stat-sub ph" class:bad={appDown.length}>{!apps ? '…' : appDown.length ? `${appDown.length} not running` : appUpd.length ? `${appUpd.length} to update` : 'all fine'}</span>
        <span class="ui-stat-sub short" class:bad={appDown.length}>{!apps ? 'Looking…' : appDown.length ? `${appDown.map(p => p.project).join(', ')} not fully running` : appUpd.length ? `${appUpd.map(p => p.project).join(', ')}: newer image` : 'running and up to date'}</span>
        <span class="ui-stat-sub ui-legend wide">{#if !apps}Looking…{:else}{#each appSegs as s}<span class:bad={s.bad}><b style="background: {s.bad ? 'var(--red)' : 'var(--metric-disk)'}; opacity: {s.bad ? 1 : s.shade}"></b>{s.n} {s.name}</span>{:else}no Compose apps yet{/each}{/if}</span>
    </a>
    {/if}
    {#if parts.includes('backups')}
    <a class="cell" href="#backups/runs">
        <span class="ui-stat-label"><span class="lg">Backups</span><span class="sm">Backup</span></span>
        <span class="ui-stat-value" class:bad={stale}>{backup?.last_success ? ago(backup.last_success) : '—'}<small>{backup?.running ? 'running now' : backup?.next_run ? `next ${inT(backup.next_run)}` : ''}</small></span>
        <div class="strip wide" aria-label="Backups over the last {DAYS} days">{#each days as d (d.key)}<i class={d.state} title="{d.label}: {d.state === 'ok' ? 'backed up' : d.state === 'bad' ? 'failed' : d.state === 'other' ? 'ran, unfinished' : 'no backup'}"></i>{/each}</div>
        <span class="ui-stat-sub ph">{backup?.running ? 'running now' : backup?.next_run ? `next ${inT(backup.next_run)}` : '—'}</span>
        <span class="ui-stat-sub sub-b">{runs ? `${okDays} of the last ${DAYS} days` : 'Looking…'}</span>
    </a>
    {/if}
</section>
{/if}

<style>
    /* one card in three parts, so it doesn't read as more tiles beside the cluster's */
    .att { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); overflow: hidden; }
    .cell { display: flex; flex-direction: column; gap: 6px; padding: 16px 20px; min-width: 0; text-decoration: none; color: inherit; transition: background .12s; }
    .cell + .cell { border-left: 1px solid var(--border); }
    .cell:hover { background: var(--highlight-3); }
    .bad { color: var(--red); }
    .att .ui-segbar { margin-top: 2px; }
    /* one thin cell per day, same height as the bars beside it */
    .strip { display: grid; grid-template-columns: repeat(14, 1fr); gap: 2px; height: 6px; margin-top: 2px; }
    .strip i { border-radius: 2px; background: var(--highlight-15); }
    .strip i.ok { background: var(--accent); }
    .strip i.other { background: var(--accent); opacity: 0.4; }
    .strip i.bad { background: var(--red); }
    .short { display: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    /* narrower: no bars, just the figure and one short line, so it stays one compact row */
    @media (max-width: 1150px) {
        .wide { display: none !important; }
        .short { display: block; }
        .cell { gap: 3px; padding: 12px 16px; }
    }
    .sm, .ph { display: none; }
    /* phone: the same three side by side, smaller: label, figure, one grey line */
    @media (max-width: 760px) {
        .cell { padding: 12px 12px; gap: 2px; }
        .lg, .short, .sub-b, .cell .ui-stat-value small { display: none; }
        .sm { display: inline; }
        .ph { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .cell .ui-stat-value { font-size: 17px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    }
</style>
