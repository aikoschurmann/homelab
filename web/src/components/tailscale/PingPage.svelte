<script>
    import { SN } from '../../lib/server.js';
    // Ping every online device from Arrakis with `tailscale ping`: latency and whether the path is direct or relayed.
    import { Activity, Loader2 } from 'lucide-svelte';
    import { machines } from '../../lib/stores.js';
    import { hosts, arrakisModel } from '../../lib/hosts.js';
    import { displayName, isShared, deviceId, clusterOf, deviceIcon, ago } from '../../lib/tailscale.js';

    export let net;
    export let now = Date.now();

    $: peers = net.devices.filter(d => !d.self && d.online).sort((a, b) => a.name.localeCompare(b.name));
    $: offline = net.devices.filter(d => !d.self && !d.online).length;
    $: cl = Object.fromEntries(net.devices.map(d => [d.id, clusterOf(d, $hosts, $machines?.machines, $arrakisModel)]));

    // results by device id: { busy, data, err, at }
    let res = {};
    async function ping(d) {
        res[d.id] = { ...res[d.id], busy: true };
        try {
            const j = await fetch(`/api/tailscale/ping/${d.ip}`, { method: 'POST' }).then(r => r.json());
            res[d.id] = j.status === 'success' ? { data: j.data, at: Date.now() } : { err: j.message, at: Date.now() };
        } catch (e) { res[d.id] = { err: 'Could not reach the backend', at: Date.now() }; }
    }
    // three at a time, so a slow device doesn't hold up the rest
    let all = false;
    async function pingAll() {
        all = true;
        const queue = [...peers];
        await Promise.all([0, 1, 2].map(async () => { while (queue.length) await ping(queue.shift()); }));
        all = false;
    }
    $: done = peers.filter(d => res[d.id]?.data);
    $: best = done.length ? Math.min(...done.map(d => res[d.id].data.best_ms)) : null;
    $: avg = done.length ? done.reduce((a, d) => a + res[d.id].data.best_ms, 0) / done.length : null;
    $: relayed = done.filter(d => res[d.id].data.path === 'relay').length;
    // Tailscale reports a sub-millisecond LAN reply as 0s
    const ms = (v) => v == null ? '—' : v < 1 ? '<1' : v < 10 ? v.toFixed(1) : Math.round(v);
</script>

<div class="ts-sub">
    <section class="ui-card">
        <div class="ui-card-head">
            <div><h2 class="ui-card-title">Online devices</h2><p class="ui-card-desc">{#if done.length}{done.length} of {peers.length} answered · fastest {ms(best)} ms · average {ms(avg)} ms · {relayed} relayed{:else}Pinged from {SN} with <span class="ui-mono">tailscale ping</span>, which also tells whether the path is direct or relayed.{/if}{#if offline}{' · '}{offline} offline, not pinged{/if}</p></div>
            <button class="ui-btn" disabled={all || !peers.length} on:click={pingAll}>{#if all}<Loader2 size={14} class="ui-spin" />{:else}<Activity size={14} />{/if} Ping all</button>
        </div>
        <div class="ui-tbl-wrap">
            <table class="ui-tbl">
                <thead><tr><th>Device</th><th>Path</th><th>Latency</th><th class="shrink"></th></tr></thead>
                <tbody>
                    {#each peers as d (d.id)}
                        {@const r = res[d.id]}
                        <tr>
                            <td>
                                <a class="dev" href="#tailscale/{deviceId(d)}">
                                    <span class="ic"><svelte:component this={deviceIcon(d, cl[d.id])} size={15} /></span>
                                    <span class="dev-main"><span class="nm">{isShared(d) ? d.user : displayName(d)}</span><small><span class="ui-mono">{d.ip}</span> · {d.os || 'shared'}</small></span>
                                </a>
                            </td>
                            <td>
                                {#if r?.data}<span class="pth" class:relay={r.data.path === 'relay'}>{r.data.path === 'direct' ? 'Direct' : 'Relayed · ' + r.data.via}</span>
                                {:else if r?.err}<span class="ui-dim">{r.err}</span>
                                {:else}<span class="ui-dim">—</span>{/if}
                            </td>
                            <td>{#if r?.data}<b class="lat">{ms(r.data.best_ms)} ms</b>{#if r.at}<small class="ui-dim">{' · '}{ago(new Date(r.at).toISOString(), now)}</small>{/if}{:else}<span class="ui-dim">—</span>{/if}</td>
                            <td><button class="ui-btn sm" disabled={r?.busy} on:click={() => ping(d)}>{#if r?.busy}<Loader2 size={13} class="ui-spin" />{:else}Ping{/if}</button></td>
                        </tr>
                    {/each}
                </tbody>
            </table>
            {#if !peers.length}<div class="ui-empty">No other device is online.</div>{/if}
        </div>
    </section>
</div>

<style>
    .dev { display: flex; align-items: center; gap: 12px; min-width: 0; text-decoration: none; color: inherit; }
    .ic { width: 32px; height: 32px; border-radius: var(--radius-card, 8px); flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--accent-soft); color: var(--accent); }
    .dev-main { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .nm { font-weight: 600; color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .dev:hover .nm { text-decoration: underline; }
    .dev-main small { font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .pth { color: var(--green); white-space: nowrap; }
    .pth.relay { color: var(--amber); }
    .lat { font-weight: 500; font-variant-numeric: tabular-nums; white-space: nowrap; }
    @media (max-width: 760px) { .ic { display: none; } }
</style>
