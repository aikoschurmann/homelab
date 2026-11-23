<script>
    import { onMount } from 'svelte';
    import { ExternalLink, Loader2 } from 'lucide-svelte';
    import { visible } from '../lib/stores.js';
    import { tailnet, fetchTailnet } from '../lib/tailscale.js';
    import StatusPill from './ui/StatusPill.svelte';

    // Pi-hole's numbers for today, and pausing its blocking (a tab of Network tools)
    let d = null, error = '', busy = false;
    async function load() {
        try {
            const j = await fetch('/api/pihole').then(r => r.json());
            if (j.status === 'success') { d = j.data; error = ''; } else error = j.message;
        } catch (e) { error = 'Could not reach the dashboard'; }
    }
    onMount(() => { load(); if (!$tailnet) fetchTailnet(); const t = setInterval(() => visible() && load(), 15000); return () => clearInterval(t); });

    async function setBlocking(enabled, minutes = null) {
        busy = true;
        try {
            const r = await fetch('/api/pihole/blocking', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled, minutes }) }).then(r => r.json());
            window.showToast?.(r.status === 'success' ? (enabled ? 'Blocking is back on' : minutes ? `Blocking paused for ${minutes < 60 ? minutes + ' min' : minutes / 60 + ' h'}` : 'Blocking paused') : r.message);
            await load();
        } finally { busy = false; }
    }
    const n = (v) => v == null ? '—' : Number(v).toLocaleString();
    $: names = Object.fromEntries(($tailnet?.devices || []).map(x => [x.ip, x.name]));
    const clientName = (c) => names[c.ip] || (c.name && c.name !== c.ip ? c.name : null) || (c.ip.startsWith('172.') ? 'Docker network (tailnet devices)' : c.ip);
    $: maxDom = Math.max(1, ...(d?.top_blocked || []).map(x => x.count));
    $: maxCl = Math.max(1, ...(d?.top_clients || []).map(x => x.count));
    const left = (s) => s >= 3600 ? `${Math.round(s / 3600)} h` : `${Math.max(1, Math.round(s / 60))} min`;
</script>

{#if !d}
    <div class="ui-dim">{error || 'Asking Pi-hole…'}</div>
{:else if !d.found}
    <section class="ui-card"><div class="ui-empty">No Pi-hole container is running on this Mac or in its machines. Install one, and its numbers show up here.</div></section>
{:else}
    <div class="ui-stats">
        <div class="ui-stat"><span class="ui-stat-label">Queries</span><span class="ui-stat-value">{n(d.queries)}</span><span class="ui-stat-sub">last 24 hours · {d.clients} active clients</span></div>
        <div class="ui-stat"><span class="ui-stat-label">Blocked</span><span class="ui-stat-value">{n(d.blocked)}<small>{d.percent != null ? d.percent.toFixed(1) + '%' : ''}</small></span><div class="ui-meter"><i style="width: {d.percent || 0}%; background: var(--accent)"></i></div></div>
        <div class="ui-stat"><span class="ui-stat-label">Blocklists</span><span class="ui-stat-value">{n(d.gravity)}</span><span class="ui-stat-sub">domains blocked</span></div>
        <div class="ui-stat"><span class="ui-stat-label">Answered from cache</span><span class="ui-stat-value">{d.queries ? Math.round(100 * d.cached / d.queries) + '%' : '—'}</span><span class="ui-stat-sub">{n(d.forwarded)} forwarded upstream</span></div>
    </div>

    <section class="ui-card">
        <div class="ui-card-head">
            <div><h2 class="ui-card-title">Blocking</h2><p class="ui-card-desc">Pi-hole in {d.target === 'mac' ? 'this Mac’s Docker' : d.target}. Pausing lets everything through, handy when a site breaks.</p></div>
            <a class="ui-btn sm" href={d.admin} target="_blank" rel="noopener noreferrer">Admin <ExternalLink size={13} /></a>
        </div>
        <div class="ui-card-foot">
            <span>{#if d.blocking === 'enabled'}<StatusPill state="running" label="Blocking" />{:else}<StatusPill state="waiting" label={d.timer ? `Paused, back in ${left(d.timer)}` : 'Paused'} />{/if}</span>
            <span class="ui-btns">
                {#if busy}<Loader2 size={14} class="ui-spin" />{/if}
                {#if d.blocking === 'enabled'}
                    <button class="ui-btn sm" disabled={busy} on:click={() => setBlocking(false, 5)}>Pause 5 min</button>
                    <button class="ui-btn sm" disabled={busy} on:click={() => setBlocking(false, 60)}>Pause 1 h</button>
                {:else}
                    <button class="ui-btn sm" disabled={busy} on:click={() => setBlocking(true)}>Resume now</button>
                {/if}
            </span>
        </div>
    </section>

    <div class="two">
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Most blocked</h2></div></div>
            <div class="ui-tbl-wrap"><table class="ui-tbl">
                <tbody>
                    {#each d.top_blocked as x}
                        <tr><td class="trunc ui-mono" title={x.domain}>{x.domain}</td><td class="bar"><div class="ui-meter"><i style="width: {100 * x.count / maxDom}%; background: var(--accent)"></i></div></td><td class="num">{n(x.count)}</td></tr>
                    {:else}<tr><td class="ui-dim">Nothing blocked yet today.</td></tr>{/each}
                </tbody>
            </table></div>
        </section>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Busiest clients</h2></div></div>
            <div class="ui-tbl-wrap"><table class="ui-tbl">
                <tbody>
                    {#each d.top_clients as c}
                        <tr><td class="trunc"><span>{clientName(c)}</span>{#if names[c.ip] || c.name}<small class="ui-mono ui-dim ip">{c.ip}</small>{/if}</td><td class="bar"><div class="ui-meter"><i style="width: {100 * c.count / maxCl}%; background: var(--text-secondary)"></i></div></td><td class="num">{n(c.count)}</td></tr>
                    {/each}
                </tbody>
            </table></div>
        </section>
    </div>
{/if}

<style>
    .two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .bar { width: 30%; }
    .ip { margin-left: 8px; }
    .num { text-align: right; font-variant-numeric: tabular-nums; width: 1%; }
    .ui-card-head .ui-btn { flex-shrink: 0; }
    @media (max-width: 1000px) { .two { grid-template-columns: 1fr; } }
</style>
