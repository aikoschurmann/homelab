<script>
    // Overview's Tailscale card: one line of totals, then online devices split by how they reach Arrakis.
    // Earlier layouts are kept in saved/TailscaleCard.2026-11-20.variants.svelte.
    import { infoPop } from '../../lib/infoPop.js';
    import { ArrowRight, ArrowDown, ArrowUp, Info, Monitor, Smartphone, Users } from 'lucide-svelte';
    import { tailnet, isShared, displayName, deviceId, fmtBytes as tsBytes, PHONE_OS } from '../../lib/tailscale.js';

    export let peers = [];

    // the Tailscale page's own data when loaded, so both count the same devices
    $: tsDevices = $tailnet?.devices;
    $: peersTotal = tsDevices ? tsDevices.length : peers.length;
    $: tsOnline = (tsDevices || []).filter(d => d.online);
    $: tsRx = (tsDevices || []).reduce((a, d) => a + d.rx_bytes, 0);
    $: tsTx = (tsDevices || []).reduce((a, d) => a + d.tx_bytes, 0);
    // direct before relayed, then by name
    const tsRank = (d) => d.connection === 'direct' ? 0 : 1;
    $: tsList = tsOnline.filter(d => !d.self).sort((a, b) => tsRank(a) - tsRank(b) || a.name.localeCompare(b.name));
    $: tsPeerTotal = Math.max(0, peersTotal - 1);
    $: tsActive = tsList.filter(d => d.state === 'active').length;
    // only a device in use has a path (direct or relayed); an idle one has no open session
    $: cols = [
        ['In use', 'on', tsList.filter(d => d.state === 'active'), 'Traffic in the last few minutes'],
        ['Idle', 'idle', tsList.filter(d => d.state !== 'active'), 'Online, no open session'],
    ];

    const tip = (d) => [d.os, d.ip, d.connection === 'relay' && d.relay ? 'relay ' + d.relay : '', d.state !== 'active' ? 'idle' : ''].filter(Boolean).join(' · ');
    const total = (d) => d.rx_bytes + d.tx_bytes;
</script>

<section class="ui-card ts-card" id="sec-tailscale">
    <div class="ui-card-head">
        <div>
            <h2 class="ui-card-title">Tailscale <button type="button" class="info" use:infoPop aria-label="About connections"><Info size={13} /><span class="info-pop" role="tooltip"><b>Direct</b>: Arrakis and the device talk peer to peer, the fastest path.<br /><b>Relayed</b>: traffic goes through a Tailscale relay server because no direct path was found. It works, just slower.<br /><b>Traffic</b>: bytes between Arrakis and each device, counted by Tailscale since it last started on Arrakis. It goes back to zero when Tailscale restarts.</span></button></h2>
            <p class="ui-card-desc">Devices on {$tailnet?.magic_dns || 'your tailnet'}, as Arrakis sees them.</p>
        </div>
        <a class="ui-link more" href="#tailscale">Devices <ArrowRight size={13} /></a>
    </div>

    <div class="slim">
        <span class="grp"><b>{tsList.length}</b> of {tsPeerTotal} online</span>
        <span class="grp"><b>{tsActive}</b> in use</span>
        <span class="grp io" title="Counted by Tailscale since it last started on Arrakis">
            <span><ArrowDown size={13} /><b>{tsBytes(tsRx)}</b> received</span>
            <span><ArrowUp size={13} /><b>{tsBytes(tsTx)}</b> sent</span>
            <small>since Tailscale started</small>
        </span>
    </div>

    <div class="d-cols">
        {#each cols as [label, cls, list, hint]}
            <div class="d-col">
                <div class="d-hd"><span class="cd {cls}"></span>{label} <small>{list.length}</small><span class="d-hint">{hint}</span></div>
                {#each list.slice(0, 6) as d (d.id)}
                    <a class="d-row" class:idle={d.state !== 'active'} href="#tailscale/{deviceId(d)}" title={tip(d)}>
                        <span class="ts-ic">{#if isShared(d)}<Users size={14} />{:else if PHONE_OS.includes(d.os)}<Smartphone size={14} />{:else}<Monitor size={14} />{/if}</span>
                        <span class="d-nm"><b>{displayName(d)}</b><small>{#if d.connection}<span class="pth {d.connection}">{d.connection === 'direct' ? 'Direct' : 'Relayed'}</span> · {/if}{[d.os, d.ip].filter(Boolean).join(' · ')}</small></span>
                        <span class="d-tr"><span>{total(d) ? tsBytes(total(d)) : '—'}</span>{#if total(d)}<small><ArrowDown size={10} />{tsBytes(d.rx_bytes)} <ArrowUp size={10} />{tsBytes(d.tx_bytes)}</small>{/if}</span>
                    </a>
                {:else}<div class="d-none">None</div>{/each}
                {#if list.length > 6}<a class="ts-more" href="#tailscale/f-online">+{list.length - 6} more <ArrowRight size={12} /></a>{/if}
            </div>
        {/each}
    </div>
</section>

<style>
    .ts-card { display: flex; flex-direction: column; }
    .more { font-size: 13px; white-space: nowrap; margin-top: 2px; }

    .cd { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; opacity: 0.8; display: inline-block; }
    .cd.on { background: var(--green); } .cd.idle { background: var(--text-secondary); }
    .pth.direct { color: var(--green); } .pth.relay { color: var(--amber); }
    .ts-ic { width: 28px; height: 28px; border-radius: 7px; background: var(--accent-soft); color: var(--accent); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .idle .ts-ic { background: var(--highlight-10); color: var(--text-secondary); }
    .ts-more { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px 0; font-size: 12.5px; color: var(--accent); text-decoration: none; font-weight: 500; }
    .ts-more:hover { text-decoration: underline; }

    /* totals line */
    .slim { display: flex; align-items: center; flex-wrap: wrap; gap: 10px 0; padding: 16px 20px; border-top: 1px solid var(--border); font-size: 13px; color: var(--text-secondary); }
    .grp { display: inline-flex; align-items: baseline; gap: 6px; white-space: nowrap; padding: 0 24px; }
    .grp:first-child { padding-left: 0; }
    .grp + .grp { border-left: 1px solid var(--border); }
    .slim b { font-size: 15px; color: var(--text-primary); font-weight: 600; font-variant-numeric: tabular-nums; }
    .io { gap: 18px; margin-left: auto; padding-right: 0; cursor: help; }
    .io > span { display: inline-flex; align-items: baseline; gap: 5px; }
    .io :global(svg) { align-self: center; opacity: 0.6; }
    .io small { font-size: 12px; opacity: 0.8; }

    /* devices */
    .d-cols { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid var(--border); flex: 1; }
    .d-col { display: flex; flex-direction: column; padding: 10px 10px 12px; min-width: 0; }
    .d-col + .d-col { border-left: 1px solid var(--border); }
    .d-hd { display: flex; align-items: center; gap: 7px; padding: 2px 10px 6px; font-size: 12.5px; font-weight: 600; color: var(--text-primary); }
    .d-hd small { font-weight: 400; color: var(--text-secondary); }
    .d-hint { margin-left: auto; font-size: 11.5px; font-weight: 400; color: var(--text-secondary); white-space: nowrap; }
    .d-row { display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 7px 10px; border-radius: 6px; text-decoration: none; color: var(--text-primary); min-width: 0; }
    .d-row:hover { background: var(--highlight-5); }
    .d-nm { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .d-nm b { font-size: 13.5px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .d-row:hover .d-nm b { color: var(--accent); }
    .d-nm small { font-size: 11.5px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
    .idle .d-nm b, .idle .d-tr { opacity: 0.6; }
    .d-tr { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .d-tr small { display: inline-flex; align-items: center; gap: 2px; font-size: 11px; color: var(--text-secondary); }
    .d-tr small :global(svg:nth-of-type(2)) { margin-left: 4px; }
    .d-none { padding: 8px 10px; font-size: 12.5px; color: var(--text-secondary); }

    .info { position: relative; display: inline-flex; vertical-align: -1px; margin-left: 4px; color: var(--text-secondary); opacity: 0.6; cursor: help; }
    .info:hover, .info:focus-visible { opacity: 1; }
    .info-pop { position: absolute; left: calc(-10px + var(--dx, 0px)); max-width: calc(100vw - 24px); top: calc(100% + 8px); width: 280px; text-align: left; padding: 8px 10px; border-radius: 6px; background: var(--text-primary); color: var(--surface); font-size: 12px; font-weight: 400; line-height: 1.45; letter-spacing: 0; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18); display: none; z-index: 5; }
    .info:hover .info-pop, .info:focus-visible .info-pop, :global(.info.open) .info-pop { display: block; animation: info-in .15s ease; }
    @keyframes info-in { from { opacity: 0; transform: translateY(-4px); } }

    /* the traffic group drops to its own line before things get tight */
    @media (max-width: 1100px) {
        .io { flex-basis: 100%; margin-left: 0; padding-left: 0; border-left: none !important; }
    }
    @media (max-width: 760px) {
        .ui-card-head { flex-wrap: wrap; }
        .slim { padding: 14px; }
        .io { flex-wrap: wrap; gap: 6px 16px; }
        .d-cols { grid-template-columns: 1fr; }
        .d-col { padding-left: 4px; padding-right: 4px; }
        .d-col + .d-col { border-left: none; border-top: 1px solid var(--border); }
        .d-hint { display: none; }
    }
</style>
