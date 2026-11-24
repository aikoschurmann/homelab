<script>
    import { Box } from 'lucide-svelte';
    import { SN } from '../../lib/server.js';
    import { hosts, hostOrder, byOrder, arrakisModel, hostIcon, fmtGb, fmtDisk } from '../../lib/hosts.js';
    import { stats, machines, machineUsage } from '../../lib/stores.js';
    import { disks, storageTotals } from '../../lib/storage.js';
    import { href } from '../../lib/infra.js';

    // The cluster as a rack: one unit per host (2U) and per machine (1U), top to bottom, U
    // numbers counting up from the bottom as on a real rack. Each unit: what it is and a front
    // panel of live lights (power, CPU blinking faster the busier it is, network flickering with
    // traffic); the same compact row at every width. A unit opens its page.
    export let arrakis = {};     // as the host cards get it: { cpu, mem: { used, total } GB, disk: { used, total } GB, cores, net (Mbps), up (s) }

    // the agents send byte counters: traffic is the change between two reports
    let prev = {}, rates = {};
    $: if ($hosts) {
        const next = { ...prev }, r = { ...rates };
        for (const h of $hosts) {
            const rep = h.report;
            if (!rep || rep.net_rx == null) continue;
            const p = prev[h.id], dt = p ? rep.at - p.at : 0;
            if (p && dt > 0) r[h.id] = { rx: (rep.net_rx - p.rx) * 8 / dt / 1e6, tx: (rep.net_tx - p.tx) * 8 / dt / 1e6 };
            next[h.id] = { rx: rep.net_rx, tx: rep.net_tx, at: rep.at };
        }
        prev = next; rates = r;
    }
    const shortOs = (os) => (os || '').replace(/ GNU\/Linux/, '').replace(/ LTS$/, '').replace(/ \(.*\)$/, '');
    $: ext = storageTotals($disks).external;
    $: runningVms = ($machines?.machines || []).filter(m => m.state === 'running');

    $: hostUnits = byOrder([{ id: 'arrakis' }, ...($hosts || [])], $hostOrder).map(h => {
        if (h.id === 'arrakis') {
            const a = arrakis;
            return { id: 'arrakis', name: SN, tag: 'This server', icon: hostIcon($arrakisModel, 'macOS'), on: true, u: 2, to: href.arrakis,
                sub: [$arrakisModel || 'Mac', 'macOS', a.cores ? `${a.cores} cores` : ''].filter(Boolean).join(' · '),
                cpu: isFinite(a.cpu) ? a.cpu : null, cores: a.cores, mem: a.mem ? a.mem.used * 2 ** 30 : null, memTotal: a.mem ? a.mem.total * 2 ** 30 : 0,
                disk: a.disk ? a.disk.used * 1e9 + ext.used : null, diskTotal: a.disk ? a.disk.total * 1e9 + ext.size : 0,
                net: a.net != null ? { total: a.net } : null, up: a.up };
        }
        const r = h.report || {}, on = !!h.online;
        return { id: h.id, name: h.name, icon: hostIcon(r.model, r.os), on, u: 2, to: '#infra/' + encodeURIComponent(h.id),
            sub: h.report ? [r.model, shortOs(r.os), r.cores ? `${r.cores} cores` : ''].filter(Boolean).join(' · ') : 'Agent not installed yet',
            cpu: on ? r.cpu_pct ?? null : null, cores: r.cores, mem: on ? r.mem_used ?? null : null, memTotal: r.mem_total || 0,
            disk: r.disk_used ?? null, diskTotal: r.disk_total || 0, net: on ? rates[h.id] || null : null, up: on ? r.uptime_secs : null };
    });
    $: vmUnits = ($machines?.machines || []).map(m => {
        const u = $machineUsage[m.name] || {}, on = m.state === 'running';
        const distro = m.image?.distro ? m.image.distro[0].toUpperCase() + m.image.distro.slice(1) + (m.image.version ? ' ' + m.image.version : '') : 'Linux';
        return { id: 'vm:' + m.name, name: m.name, icon: Box, on, vm: true, u: 1, to: href.machine(m.name),
            sub: `${distro} · machine on ${SN}`,
            cpu: on ? u.cpu ?? null : null, cores: m.cpu, mem: on ? u.mem ?? null : null, memTotal: u.memLimit || (m.memory_mib || 0) * 2 ** 20, up: on ? u.up : null };
    });
    // Arrakis's machines are racked right under it
    $: units = hostUnits.flatMap(h => h.id === 'arrakis' ? [h, ...vmUnits] : [h]);
    $: total = units.reduce((a, x) => a + x.u, 0);
    $: powered = units.filter(x => x.on).length;
    // each unit's U numbers, the top one first
    $: slots = (() => { let top = total; return units.map(x => { const s = Array.from({ length: x.u }, (_, k) => top - k); top -= x.u; return s; }); })();
    $: cores = hostUnits.filter(x => x.on).reduce((a, x) => a + (x.cores || 0), 0);
    $: memAll = hostUnits.filter(x => x.on).reduce((a, x) => a + (x.memTotal || 0), 0);

    // a busier CPU blinks faster: 1.6 s a blink when idle, 0.15 s flat out
    const cpuBlink = (c) => c == null || c < 0.5 ? null : Math.max(0.15, 1.6 - Math.min(100, c) / 100 * 1.45);
    // traffic flickers from 1.2 s (a trickle) to 0.1 s (100 Mbps and up), on a log scale
    const netBlink = (n) => n == null || n < 0.02 ? null : Math.max(0.1, 1.2 - Math.min(1, Math.log10(n * 50 + 1) / Math.log10(5001)) * 1.1);
    const netOf = (x) => x.net ? (x.net.total ?? (x.net.rx + x.net.tx)) : null;
    const fmtNet = (n) => n == null ? '—' : n >= 100 ? Math.round(n) + ' Mbps' : n >= 1 ? n.toFixed(1) + ' Mbps' : Math.round(n * 1000) + ' kbps';
</script>

<section class="ui-card rack" id="sec-rack">
    <div class="ui-card-head">
        <div><h2 class="ui-card-title">Rack</h2><p class="ui-card-desc">{units.length} units in {total}U · {powered === units.length ? 'all powered' : `${powered} of ${units.length} powered`} · {cores} cores · {fmtGb(memAll)} memory</p></div>
        <span class="legend" aria-hidden="true"><span><i class="led pwr lit"></i>Power</span><span><i class="led cpu lit"></i>CPU</span><span><i class="led net lit"></i>Network</span></span>
    </div>
    <div class="units">
        {#each units as x, i (x.id)}
            <a class="unit" class:off={!x.on} class:one={x.u === 1} href={x.to}>
                <span class="rail ui-mono" aria-label="Rack units {slots[i].join(', ')}">{#each slots[i] as n}<span>{n}</span>{/each}</span>
                <span class="body">
                    <span class="ic" class:on={x.on}><svelte:component this={x.icon} size={18} /></span>
                    <span class="title">
                        <span class="nm"><span class="nm-t">{x.name}</span></span>
                        <span class="sub">{x.sub}</span>
                    </span>
                    <!-- the front panel: its lights -->
                    <span class="panel">
                        <span class="leds" role="img" aria-label="{x.on ? 'Powered' : 'Off'}{x.cpu != null ? `, CPU ${Math.round(x.cpu)}%` : ''}{x.vm ? '' : `, ${fmtNet(netOf(x))}`}">
                            <i class="led pwr" class:lit={x.on}></i>
                            <i class="led cpu" class:lit={cpuBlink(x.cpu)} style={cpuBlink(x.cpu) ? `--p: ${cpuBlink(x.cpu)}s` : ''}></i>
                            <i class="led net" class:lit={netBlink(netOf(x))} class:na={x.vm} style={netBlink(netOf(x)) ? `--p: ${netBlink(netOf(x))}s` : ''}></i>
                        </span>
                    </span>
                </span>
            </a>
        {/each}
    </div>
</section>

<style>
    .legend { display: flex; gap: 14px; margin-top: 2px; font-size: 12px; color: var(--text-secondary); white-space: nowrap; }
    .legend span { display: inline-flex; align-items: center; gap: 6px; }
    .legend .led { animation: none; }
    .units { border-top: 1px solid var(--border); }
    .unit { display: flex; align-items: stretch; color: inherit; text-decoration: none; min-width: 0; transition: background .12s; }
    .unit + .unit { border-top: 1px solid var(--border); }
    .unit:hover { background: var(--highlight-3); }
    .unit:hover .nm-t { text-decoration: underline; }
    .unit:last-child { border-radius: 0 0 var(--radius-card, 8px) var(--radius-card, 8px); }
    /* the rack's rail: a cell per U, the unit's own numbers */
    .rail { width: 40px; flex-shrink: 0; display: flex; flex-direction: column; border-right: 1px solid var(--border); background: var(--highlight-3); }
    .rail span { flex: 1; display: flex; align-items: center; justify-content: center; font-size: 11px; color: var(--text-secondary); }
    .rail span + span { border-top: 1px dashed var(--border); }
    .body { flex: 1; min-width: 0; display: flex; align-items: center; gap: 16px; padding: 16px 20px 16px 16px; }
    .unit.one .body { padding-top: 12px; padding-bottom: 12px; }
    .ic { width: 38px; height: 38px; border-radius: 9px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); }
    .ic.on { background: var(--accent-soft); color: var(--accent); }
    .title { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
    .nm { display: flex; align-items: center; gap: 8px; min-width: 0; font-size: 15px; font-weight: 600; color: var(--accent); }
    .nm-t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    .nm :global(.ui-tag) { flex-shrink: 0; }
    .unit.off .nm { color: var(--text-secondary); }
    .sub { font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    /* the front panel */
    .panel { flex-shrink: 0; display: flex; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--highlight-3); }
    .leds { display: flex; gap: 8px; }
    .led { width: 7px; height: 7px; border-radius: 50%; background: var(--highlight-15); }
    .led.na { opacity: .35; }
    .led.pwr.lit { background: var(--green); box-shadow: 0 0 5px var(--green); }
    .led.cpu.lit { background: var(--metric-cpu); box-shadow: 0 0 5px var(--metric-cpu); animation: blink var(--p) steps(1) infinite; }
    .led.net.lit { background: var(--metric-net); box-shadow: 0 0 5px var(--metric-net); animation: blink var(--p) steps(1) infinite; animation-delay: -.2s; }
    @keyframes blink { 50% { opacity: .2; box-shadow: none; } }
    @media (prefers-reduced-motion: reduce) { .led.lit { animation: none !important; } }
    .unit.off .panel { opacity: .55; }
    @media (max-width: 640px) {
        .body { gap: 12px; padding: 12px 14px 12px 12px; }
        .rail { width: 32px; }
        .legend { display: none; }
    }
</style>
