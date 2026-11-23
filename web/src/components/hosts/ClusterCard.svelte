<script>
    // The cluster: totals across every online host, then a tree you open like folders.
    // Host → (Arrakis: OrbStack VM → machines → containers and services; macOS apps)
    //      → (other hosts: the same, from their agent; plus any containers). Bars only on host rows.
    import { onMount } from 'svelte';
    import { Server, Laptop, Layers, Box, Cpu, Plus, ArrowRight, ChevronRight, Settings2 } from 'lucide-svelte';
    import { machines, machineUsage, gbFromMib, visible } from '../../lib/stores.js';
    import { services, fmtMb } from '../../lib/services.js';
    import { hosts, fmtGb, hostIcon, arrakisModel, hostOrder, byOrder } from '../../lib/hosts.js';
    import { imageLabel, fmtBytes } from '../../lib/machines.js';
    import { vmRef, vmBase } from '../../lib/vmref.js';

    // { cpu, mem: { used, total } GB, disk: { used, total } GB, cores, os, up } seconds
    export let arrakis = {};
    // { running, cpu, memGb, limitGb, up } — the OrbStack VM
    export let vm = {};
    export let title = 'Hosts';
    export let link = true;          // "All hosts" link in the head (off on the Hosts page)
    export let bare = false;         // just the tree: the Infrastructure page's table view

    $: machineList = $machines?.machines || [];
    $: remote = $hosts || [];
    // rows in the order saved from the sidebar (Arrakis included)
    $: rows = byOrder([{ id: 'arrakis' }, ...remote], $hostOrder).map(x => x.id);
    // a remote host's line under its name, like its Overview card: machines · containers · apps
    function hostSummary(h, cs) {
        const r = h.report || {}, ms = h.vms?.machines;
        const nm = ms ? ms.filter(m => m.state === 'running').length : h.caps?.machines;
        const apps = (r.apps || []).filter(a => !/orbstack/i.test(a.name)).length;
        const run = cs.filter(c => c.status === 'running').length;
        return [(ms || h.caps?.orbstack) ? plural(nm || 0, 'machine') : '', run ? plural(run, 'container') : '', apps ? plural(apps, 'app') : ''].filter(Boolean).join(' · ') || 'Nothing tracked yet';
    }
    $: svc = $services || [];
    $: apps = svc.filter(s => s.host === 'Mac' && !/orbstack/i.test(s.name || '')).sort(byRun);
    const byRun = (a, b) => (b.status === 'running') - (a.status === 'running') || (b.mem_mb || 0) - (a.mem_mb || 0);

    // ---- open folders, remembered per browser ----------------------------------------------
    const KEY = 'arrakis_hosts_open';
    let open = new Set(['h:arrakis', 'vm']);
    try { const v = JSON.parse(localStorage.getItem(KEY)); if (Array.isArray(v)) open = new Set(v); } catch (e) {}
    function toggle(k) {
        open.has(k) ? open.delete(k) : open.add(k);
        open = open;
        try { localStorage.setItem(KEY, JSON.stringify([...open])); } catch (e) {}
        if (k.startsWith('m:') && open.has(k)) loadWorkloads(k.slice(2));
    }
    $: isOpen = (k) => open.has(k);

    // what runs inside a machine: its containers and its own (non-system) services
    let work = {};
    async function loadWorkloads(name) {
        try { const j = await fetch(`/api/vms/${encodeURIComponent(name)}/workloads`).then(r => r.json()); if (j.status === 'success') work = { ...work, [name]: j.data }; } catch (e) {}
    }
    // other hosts' machines: their latest usage, from that host's sampler (cheap to poll)
    let hostUsage = {};
    async function loadHostUsage() {
        for (const h of remote.filter(x => x.vms?.machines?.length)) {
            try { const j = await fetch(`${vmBase(h.id)}/usage`).then(r => r.json()); if (j.status === 'success') hostUsage = { ...hostUsage, [h.id]: j.data.machines }; } catch (e) {}
        }
    }
    onMount(() => {
        for (const k of open) if (k.startsWith('m:')) loadWorkloads(k.slice(2));
        loadHostUsage();
        const t = setInterval(() => { if (visible()) for (const k of open) if (k.startsWith('m:')) loadWorkloads(k.slice(2)); }, 30000);
        const t2 = setInterval(() => visible() && loadHostUsage(), 10000);
        return () => { clearInterval(t); clearInterval(t2); };
    });
    // container figures from the Services list where it has them (the dashboard machine)
    $: inside = (name) => {
        const w = work[name];
        if (!w) return null;
        const live = Object.fromEntries(svc.filter(s => s.host === name).map(s => [s.name, s]));
        return [
            ...(w.docker || []).map(c => ({ kind: 'container', name: c.name, sub: shortImage(c.image), running: c.state === 'running', cpu: live[c.name]?.cpu, mem: live[c.name]?.mem_mb, up: live[c.name]?.uptime_seconds, href: live[c.name] ? `#infra/svc-${encodeURIComponent(live[c.name].id)}` : `#infra/vm-${name}/workloads` })),
            ...(w.services || []).filter(u => !u.base).map(u => ({ kind: 'service', name: u.unit, sub: u.description || 'systemd service', running: true, href: `#infra/vm-${name}/workloads` })),
        ].sort((a, b) => (b.mem || 0) - (a.mem || 0));
    };
    $: hasInside = (m) => m.state === 'running' && (($machineUsage[m.name]?.runs?.containers || 0) + ($machineUsage[m.name]?.runs?.services || 0)) > 0;

    // ---- cluster totals: physical hosts that are online (machines live inside Arrakis) -----
    $: live = remote.filter(h => h.online && h.report);
    $: totCores = (arrakis.cores || 0) + live.reduce((a, h) => a + (h.report.cores || 0), 0);
    $: usedCores = (arrakis.cores && isFinite(arrakis.cpu) ? arrakis.cpu / 100 * arrakis.cores : 0) + live.reduce((a, h) => a + (h.report.cpu_pct || 0) / 100 * (h.report.cores || 0), 0);
    $: totMem = (arrakis.mem?.total || 0) + live.reduce((a, h) => a + h.report.mem_total / 2 ** 30, 0);
    $: usedMem = (arrakis.mem?.used || 0) + live.reduce((a, h) => a + h.report.mem_used / 2 ** 30, 0);
    $: totDisk = (arrakis.disk?.total || 0) + live.reduce((a, h) => a + (h.report.disk_total || 0) / 1e9, 0);
    $: usedDisk = (arrakis.disk?.used || 0) + live.reduce((a, h) => a + (h.report.disk_used || 0) / 1e9, 0);
    $: runningMachines = machineList.filter(m => m.state === 'running').length;
    $: vmContainers = machineList.reduce((a, m) => a + ($machineUsage[m.name]?.runs?.containers_running || 0), 0);
    $: remoteContainers = live.reduce((a, h) => a + (h.report.containers || []).filter(c => c.status === 'running').length, 0);

    const pct = (a, b) => b ? Math.min(100, Math.max(0, (a / b) * 100)) : 0;
    const fmtUp = (s) => { if (!s) return '—'; const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`; };
    const ago = (t) => { const s = Math.max(0, Date.now() / 1000 - t); return s < 90 ? `${Math.round(s)}s ago` : s < 5400 ? `${Math.round(s / 60)}m ago` : s < 129600 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`; };
    const cpuTxt = (v) => v == null || !isFinite(v) ? '—' : (v < 10 ? v.toFixed(1) : Math.round(v)) + '%';
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
    const shortOs = (os) => (os || '').replace(/ LTS$/, '').replace(/ \(.*\)$/, '');
    const shortImage = (img) => (img || '').replace(/^(lscr\.io|ghcr\.io|docker\.io|quay\.io)\//, '').replace(/:latest$/, '');
    const specs = (os, cores, memBytes) => [shortOs(os), cores ? `${cores} cores` : '', memBytes ? fmtGb(memBytes) : ''].filter(Boolean).join(' · ');
    const tb = (gb) => gb >= 1000 ? (gb / 1000).toFixed(1) + ' TB' : gb.toFixed(0) + ' GB';
</script>

<section class="ui-card" id="sec-host">
    {#if !bare}
    <div class="ui-card-head">
        <div>
            <h2 class="ui-card-title">{title}</h2>
            <p class="ui-card-desc">{1 + live.length} of {plural(1 + remote.length, 'host')} online · {plural(runningMachines, 'machine')} · {plural(vmContainers + remoteContainers, 'container')}</p>
        </div>
        <div class="head-actions">
            <a class="ui-btn" href="#infra/new"><Plus size={14} /> Add host</a>
            {#if link}<a class="ui-link more" href="#infra">All hosts <ArrowRight size={12} /></a>{/if}
        </div>
    </div>

    <!-- cluster totals -->
    <div class="tot">
        <div class="cell">
            <span class="k">CPU</span>
            <span class="v">{usedCores.toFixed(1)}<small>of {totCores} cores</small></span>
            <span class="bar"><i style="width: {pct(usedCores, totCores)}%; background: var(--metric-cpu)"></i></span>
        </div>
        <div class="cell">
            <span class="k">Memory</span>
            <span class="v">{usedMem.toFixed(1)}<small>of {totMem.toFixed(0)} GB</small></span>
            <span class="bar"><i style="width: {pct(usedMem, totMem)}%; background: var(--metric-mem)"></i></span>
        </div>
        <div class="cell">
            <span class="k">Disk</span>
            <span class="v">{tb(usedDisk)}<small>of {tb(totDisk)}</small></span>
            <span class="bar"><i style="width: {pct(usedDisk, totDisk)}%; background: var(--text-secondary)"></i></span>
        </div>
    </div>

    {/if}

    <div class="ct" class:bare role="treegrid">
        <div class="tr th" role="row"><span>Name</span><span>Details</span><span>CPU</span><span>Memory</span><span>Up</span></div>

        {#each rows as row (row)}
        {#if row === 'arrakis'}
        <!-- Arrakis -->
        <div class="tr host" role="row" aria-expanded={isOpen('h:arrakis')} on:click={() => toggle('h:arrakis')}>
            <span class="nm">
                <button class="car" class:open={isOpen('h:arrakis')} aria-label="Show what runs on Arrakis"><ChevronRight size={15} /></button>
                <span class="ic on"><svelte:component this={hostIcon($arrakisModel, 'macOS')} size={16} /></span>
                <span class="nm-t"><a href="#infra/arrakis" on:click|stopPropagation><b>Arrakis</b></a><small>This server</small></span>
            </span>
            <span class="det">{specs(arrakis.os || 'macOS', arrakis.cores, arrakis.mem ? arrakis.mem.total * 2 ** 30 : 0)}</span>
            <span class="m"><span class="bar"><i style="width: {pct(arrakis.cpu, 100)}%; background: var(--metric-cpu)"></i></span><span class="v">{cpuTxt(arrakis.cpu)}</span></span>
            <span class="m"><span class="bar"><i style="width: {arrakis.mem ? pct(arrakis.mem.used, arrakis.mem.total) : 0}%; background: var(--metric-mem)"></i></span><span class="v">{arrakis.mem ? arrakis.mem.used.toFixed(1) : '—'}<small>/ {arrakis.mem ? arrakis.mem.total.toFixed(0) : '—'} GB</small></span></span>
            <span class="up">{fmtUp(arrakis.up)}</span>
        </div>
        {#if isOpen('h:arrakis')}
            <!-- the OrbStack VM, a folder of machines -->
            <div class="tr l1" role="row" class:off={!vm.running} on:click={() => toggle('vm')}>
                <span class="nm"><button class="car" class:open={isOpen('vm')} aria-label="Show machines"><ChevronRight size={14} /></button><span class="ic sm"><Layers size={13} /></span><span class="nm-t"><b>OrbStack VM</b></span></span>
                <span class="det">Linux VM · {plural(runningMachines, 'machine')} running</span>
                <span class="n">{vm.running ? cpuTxt(vm.cpu) : '—'}</span>
                <span class="n">{vm.running ? vm.memGb.toFixed(1) : '—'}<small>/ {vm.limitGb ? vm.limitGb.toFixed(0) + ' GB' : 'pool'}</small></span>
                <span class="up">{vm.running ? fmtUp(vm.up) : '—'}</span>
            </div>
            {#if isOpen('vm')}
                {#each machineList as m (m.name)}
                    {@const u = m.state === 'running' ? $machineUsage[m.name] : null}
                    {@const k = 'm:' + m.name}
                    {@const kids = isOpen(k) ? inside(m.name) : null}
                    <div class="tr l2" role="row" class:off={m.state !== 'running'} on:click={() => hasInside(m) ? toggle(k) : location.hash = `#infra/vm-${m.name}`}>
                        <span class="nm">
                            {#if hasInside(m)}<button class="car" class:open={isOpen(k)} aria-label="Show what runs in {m.name}"><ChevronRight size={14} /></button>{:else}<span class="car-sp"></span>{/if}
                            <span class="dot" class:up={m.state === 'running'}></span>
                            <span class="nm-t"><a href="#infra/vm-{m.name}" on:click|stopPropagation><b>{m.name}</b></a>{#if m.name === $machines?.dashboard_vm}<span class="ui-tag">Dashboard</span>{/if}</span>
                        </span>
                        <span class="det">{imageLabel(m.image)}{#if u?.runs}{#if u.runs.containers}<i class="sep">·</i>{plural(u.runs.containers, 'container')}{/if}{#if u.runs.services}<i class="sep">·</i>{plural(u.runs.services, 'service')}{/if}{/if}{m.state !== 'running' ? ' · stopped' : ''}</span>
                        <span class="n">{u ? cpuTxt(u.cpu) : '—'}</span>
                        <span class="n">{u ? fmtBytes(u.mem) : '—'}<small>{m.memory_mib ? `/ ${gbFromMib(m.memory_mib)}` : ''}</small></span>
                        <span class="up">{u?.up ? fmtUp(u.up) : '—'}</span>
                    </div>
                    {#if isOpen(k) && hasInside(m)}
                        {#if !kids}<div class="tr l3 note" role="row"><span class="nm"><span class="car-sp"></span>Loading…</span></div>{/if}
                        {#each kids || [] as c (c.kind + c.name)}
                            <a class="tr l3" role="row" class:off={!c.running} href={c.href}>
                                <span class="nm"><span class="car-sp"></span><span class="kic">{#if c.kind === 'container'}<Box size={12} />{:else}<Settings2 size={12} />{/if}</span><span class="nm-t"><b>{c.name}</b></span></span>
                                <span class="det">{c.sub}</span>
                                <span class="n">{c.cpu != null && c.running ? cpuTxt(+c.cpu) : '—'}</span>
                                <span class="n">{c.mem != null && c.running ? fmtMb(c.mem) : '—'}</span>
                                <span class="up">{c.up && c.running ? fmtUp(c.up) : c.running ? '' : 'stopped'}</span>
                            </a>
                        {/each}
                    {/if}
                {/each}
            {/if}

            <!-- apps on macOS itself -->
            <div class="tr l1" role="row" on:click={() => toggle('apps')}>
                <span class="nm"><button class="car" class:open={isOpen('apps')} aria-label="Show apps"><ChevronRight size={14} /></button><span class="ic sm"><Cpu size={13} /></span><span class="nm-t"><b>macOS apps</b></span></span>
                <span class="det">{plural(apps.filter(s => s.status === 'running').length, 'app')} running on the Mac itself</span>
                <span class="n">{cpuTxt(apps.reduce((a, s) => a + (s.status === 'running' ? +s.cpu || 0 : 0), 0) / (arrakis.cores || 1))}</span>
                <span class="n">{fmtMb(apps.reduce((a, s) => a + (s.status === 'running' ? s.mem_mb || 0 : 0), 0))}</span>
                <span class="up"></span>
            </div>
            {#if isOpen('apps')}
                {#each apps as s (s.key)}
                    <a class="tr l2" role="row" class:off={s.status !== 'running'} href="#infra/svc-{encodeURIComponent(s.id)}">
                        <span class="nm"><span class="car-sp"></span><span class="dot" class:up={s.status === 'running'}></span><span class="nm-t"><b>{s.name}</b></span></span>
                        <span class="det">{s.type || 'app'}</span>
                        <span class="n">{s.status === 'running' ? cpuTxt(+s.cpu || 0) : '—'}</span>
                        <span class="n">{s.status === 'running' ? fmtMb(s.mem_mb) : '—'}</span>
                        <span class="up">{s.status === 'running' && s.uptime_seconds ? fmtUp(s.uptime_seconds) : '—'}</span>
                    </a>
                {/each}
            {/if}
        {/if}

        {:else}
            <!-- another host: like Arrakis, its OrbStack VM and machines, its apps (a Mac), containers -->
            {@const h = remote.find(x => x.id === row)}
            {@const r = h.report}
            {@const cs = (r?.containers || []).slice().sort((a, b) => (b.status === 'running') - (a.status === 'running') || (b.mem_mb || 0) - (a.mem_mb || 0))}
            {@const k = 'h:' + h.id}
            {@const hms = h.vms?.machines || []}
            {@const hasVm = !!(h.vms || h.caps?.orbstack)}
            {@const orb = (r?.apps || []).find(a => /orbstack/i.test(a.name))}
            {@const happs = (r?.apps || []).filter(a => !/orbstack/i.test(a.name))}
            {@const hc = r?.cores || 1}
            {@const any = hasVm || happs.length || cs.length}
            <div class="tr host" role="row" class:off={!h.online} on:click={() => any ? toggle(k) : location.hash = `#infra/${h.id}`}>
                <span class="nm">
                    {#if any}<button class="car" class:open={isOpen(k)} aria-label="Show what runs on {h.name}"><ChevronRight size={15} /></button>{:else}<span class="car-sp"></span>{/if}
                    <span class="ic" class:on={h.online}><svelte:component this={hostIcon(r?.model, r?.os)} size={16} /></span>
                    <span class="nm-t"><a href="#infra/{h.id}" on:click|stopPropagation><b>{h.name}</b></a><small class:st={!h.online}>{h.online ? hostSummary(h, cs) : h.last_seen ? `Offline · ${ago(h.last_seen)}` : 'Waiting for agent'}</small></span>
                </span>
                <span class="det">{r ? specs(r.os, r.cores, r.mem_total) : 'Run the install command on it'}</span>
                {#if h.online && r}
                    <span class="m"><span class="bar"><i style="width: {pct(r.cpu_pct, 100)}%; background: var(--metric-cpu)"></i></span><span class="v">{cpuTxt(r.cpu_pct)}</span></span>
                    <span class="m"><span class="bar"><i style="width: {pct(r.mem_used, r.mem_total)}%; background: var(--metric-mem)"></i></span><span class="v">{(r.mem_used / 2 ** 30).toFixed(1)}<small>/ {Math.round(r.mem_total / 2 ** 30)} GB</small></span></span>
                    <span class="up">{fmtUp(r.uptime_secs)}</span>
                {:else}
                    <span class="n dim">—</span><span class="n dim">—</span><span class="up">—</span>
                {/if}
            </div>
            {#if isOpen(k)}
                {#if hasVm}
                    {@const vk = 'vm:' + h.id}
                    <div class="tr l1" role="row" class:off={!orb} on:click={() => hms.length ? toggle(vk) : location.hash = `#infra/${h.id}/vm`}>
                        <span class="nm">{#if hms.length}<button class="car" class:open={isOpen(vk)} aria-label="Show machines on {h.name}"><ChevronRight size={14} /></button>{:else}<span class="car-sp"></span>{/if}<span class="ic sm"><Layers size={13} /></span><span class="nm-t"><b>OrbStack VM</b></span></span>
                        <span class="det">{h.caps?.orbstack === 'stopped' && !h.vms ? 'OrbStack not running' : `Linux VM · ${plural(hms.filter(m => m.state === 'running').length, 'machine')} running`}</span>
                        <span class="n">{orb ? cpuTxt(orb.cpu / hc) : '—'}</span>
                        <span class="n">{orb ? (orb.mem_mb / 1024).toFixed(1) : '—'}<small>/ {h.vms?.pool ? gbFromMib(h.vms.pool.memory_mib) : 'pool'}</small></span>
                        <span class="up">{orb ? fmtUp(orb.uptime_seconds) : '—'}</span>
                    </div>
                    {#if isOpen(vk)}
                        {#each hms as m (m.name)}
                            {@const u = m.state === 'running' ? hostUsage[h.id]?.[m.name] : null}
                            <a class="tr l2" role="row" class:off={m.state !== 'running'} href="#infra/vm-{encodeURIComponent(vmRef(h.id, m.name))}">
                                <span class="nm"><span class="car-sp"></span><span class="dot" class:up={m.state === 'running'}></span><span class="nm-t"><b>{m.name}</b></span></span>
                                <span class="det">{imageLabel(m.image)}{#if u?.runs?.containers}<i class="sep">·</i>{plural(u.runs.containers, 'container')}{/if}{#if u?.runs?.services}<i class="sep">·</i>{plural(u.runs.services, 'service')}{/if}{m.state !== 'running' ? ' · stopped' : ''}</span>
                                <span class="n">{u ? cpuTxt(u.cpu) : '—'}</span>
                                <span class="n">{u ? fmtBytes(u.mem) : '—'}<small>{m.memory_mib ? `/ ${gbFromMib(m.memory_mib)}` : ''}</small></span>
                                <span class="up">{u?.up ? fmtUp(u.up) : '—'}</span>
                            </a>
                        {/each}
                    {/if}
                {/if}
                {#if happs.length}
                    {@const ak = 'apps:' + h.id}
                    <div class="tr l1" role="row" on:click={() => toggle(ak)}>
                        <span class="nm"><button class="car" class:open={isOpen(ak)} aria-label="Show apps on {h.name}"><ChevronRight size={14} /></button><span class="ic sm"><Cpu size={13} /></span><span class="nm-t"><b>macOS apps</b></span></span>
                        <span class="det">{plural(happs.length, 'app')} running on the Mac itself</span>
                        <span class="n">{cpuTxt(happs.reduce((a, x) => a + x.cpu, 0) / hc)}</span>
                        <span class="n">{fmtMb(happs.reduce((a, x) => a + x.mem_mb, 0))}</span>
                        <span class="up"></span>
                    </div>
                    {#if isOpen(ak)}
                        {#each happs as x (x.id)}
                            <a class="tr l2" role="row" href="#infra/{h.id}/apps">
                                <span class="nm"><span class="car-sp"></span><span class="dot up"></span><span class="nm-t"><b>{x.name}</b></span></span>
                                <span class="det">{x.type === 'app' ? 'app' : 'program'}{x.ports.length ? ` · :${x.ports.slice(0, 2).join(' :')}` : ''}</span>
                                <span class="n">{cpuTxt(x.cpu / hc)}</span>
                                <span class="n">{fmtMb(x.mem_mb)}</span>
                                <span class="up">{fmtUp(x.uptime_seconds)}</span>
                            </a>
                        {/each}
                    {/if}
                {/if}
                {#each cs as c (c.id)}
                    <a class="tr l1" role="row" class:off={c.status !== 'running'} href="#infra/{h.id}">
                        <span class="nm"><span class="car-sp"></span><span class="kic"><Box size={12} /></span><span class="nm-t"><b>{c.name}</b></span></span>
                        <span class="det">{shortImage(c.image)}</span>
                        <span class="n">{c.status === 'running' ? cpuTxt(+c.cpu || 0) : '—'}</span>
                        <span class="n">{c.status === 'running' ? fmtMb(c.mem_mb) : '—'}</span>
                        <span class="up">{c.status === 'running' ? fmtUp(c.uptime_seconds) : 'stopped'}</span>
                    </a>
                {/each}
            {/if}
        {/if}
        {/each}
    </div>

    {#if !remote.length && !bare}
        <a class="foot" href="#infra/new"><Plus size={13} /> Add another computer: run one command on it and it shows up here</a>
    {/if}
</section>

<style>
    .head-actions { display: flex; align-items: center; gap: 14px; flex-shrink: 0; }
    .head-actions .ui-btn { height: 30px; text-decoration: none; }
    .more { font-size: 13px; white-space: nowrap; }

    /* totals */
    .tot { display: grid; grid-template-columns: repeat(3, 1fr); border-top: 1px solid var(--border); }
    .cell { display: flex; flex-direction: column; gap: 6px; padding: 14px 20px 16px; min-width: 0; }
    .cell + .cell { border-left: 1px solid var(--border); }
    .cell .k { font-size: 12.5px; color: var(--text-secondary); }
    .cell .v { text-align: left; font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; white-space: nowrap; }
    .cell .v small { font-size: 12.5px; font-weight: 400; color: var(--text-secondary); margin-left: 5px; letter-spacing: 0; }
    .cell .bar { height: 5px; }

    /* tree */
    .ct { border-top: 1px solid var(--border); container-type: inline-size; }
    .ct.bare { border-top: none; }
    .tr { display: grid; grid-template-columns: minmax(220px, 1.3fr) minmax(0, 1.4fr) 120px 150px 64px; gap: 0 22px; align-items: center; padding: 13px 20px; border-bottom: 1px solid var(--border); font-size: 13.5px; color: var(--text-primary); text-decoration: none; cursor: pointer; }
    .tr:last-child { border-bottom: none; }
    .tr:hover:not(.th):not(.note) { background: var(--highlight-3); }
    /* same look as .ui-tbl: quiet labels, every column left-aligned, one rule weight */
    .th { cursor: default; padding-top: 14px; padding-bottom: 10px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); background: none; border-bottom-color: var(--border); }
    .host { padding-top: 13px; padding-bottom: 13px; }
    .l1 .nm { padding-left: 26px; }
    .l2 .nm { padding-left: 52px; }
    .l3 .nm { padding-left: 78px; }
    .l1, .l2, .l3 { background: var(--highlight-3); }
    .note { color: var(--text-secondary); cursor: default; }

    .nm { display: flex; align-items: center; gap: 9px; min-width: 0; }
    .car { width: 20px; height: 20px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 4px; color: var(--text-secondary); cursor: pointer; transition: transform .15s ease; }
    .car:hover { background: var(--highlight-10); color: var(--text-primary); }
    .car.open { transform: rotate(90deg); }
    .car-sp { width: 20px; flex-shrink: 0; }
    .ic { width: 32px; height: 32px; border-radius: var(--radius-card, 8px); flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); }
    .ic.on { background: var(--accent-soft); color: var(--accent); }
    .ic.sm { width: 22px; height: 22px; border-radius: 6px; }
    .kic { width: 18px; display: flex; justify-content: center; color: var(--text-secondary); flex-shrink: 0; }
    .nm-t { display: flex; align-items: center; gap: 8px; min-width: 0; }
    .host .nm-t { flex-direction: column; align-items: flex-start; gap: 1px; }
    .nm-t a { color: inherit; text-decoration: none; min-width: 0; max-width: 100%; display: block; }
    .nm-t a:hover b { color: var(--accent); text-decoration: underline; }
    .nm-t b { display: block; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .host .nm-t b { font-size: 14px; font-weight: 600; }
    a.tr:hover .nm-t b { color: var(--accent); }
    .nm-t small { font-size: 12px; color: var(--text-secondary); white-space: nowrap; }
    .nm-t small.st { color: var(--red); }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--highlight-30); flex-shrink: 0; margin: 0 5px; }
    .dot.up { background: var(--green); }

    .det { font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    .sep { font-style: normal; margin: 0 6px; opacity: 0.6; }
    .m { display: grid; grid-template-columns: 40px minmax(24px, 1fr); align-items: center; gap: 10px; min-width: 0; }
    .tr > .m:nth-child(4) { grid-template-columns: 76px minmax(24px, 1fr); }
    .m .v { order: -1; }
    .bar { height: 4px; border-radius: 2px; background: var(--highlight-10); overflow: hidden; display: block; }
    .bar i { display: block; height: 100%; border-radius: 2px; min-width: 2px; transition: width .4s ease; }
    .v, .n { font-variant-numeric: tabular-nums; white-space: nowrap; }
    .v { font-weight: 500; }
    .v small, .n small { font-weight: 400; color: var(--text-secondary); margin-left: 3px; font-size: 12px; }
    .dim { color: var(--text-secondary); }
    .up { color: var(--text-secondary); font-variant-numeric: tabular-nums; white-space: nowrap; }
    .off .nm-t b, .off .n { color: var(--text-secondary); }

    .foot { display: flex; align-items: center; gap: 7px; padding: 12px 20px; border-top: 1px solid var(--border); font-size: 12.5px; color: var(--text-secondary); text-decoration: none; }
    .foot:hover { color: var(--accent); background: var(--highlight-3); }

    @container (max-width: 860px) {
        .tr { grid-template-columns: minmax(0, 1fr) 100px 130px 60px; gap: 0 16px; }
        .tr > :nth-child(2) { display: none; }
    }
    @container (max-width: 560px) {
        .tr { grid-template-columns: minmax(0, 1fr) 46px 70px; gap: 0 10px; padding: 12px 14px; }
        .host { padding-top: 12px; padding-bottom: 12px; }
        .tr > :nth-child(5) { display: none; }
        .bar { display: none; }
        .m, .tr > .m:nth-child(4) { grid-template-columns: 1fr; }
        .n small, .v small { display: none; }
        .l1 .nm { padding-left: 14px; }
        .l2 .nm { padding-left: 28px; }
        .l3 .nm { padding-left: 42px; }
    }
    @media (max-width: 760px) {
        .head-actions .more { display: none; }
        .tot { grid-template-columns: 1fr 1fr; }
        .cell { padding: 12px 14px; }
        .cell:nth-child(3) { grid-column: 1 / -1; border-left: none; border-top: 1px solid var(--border); }
        .cell .v { font-size: 17px; }
        .foot { padding: 12px 14px; }
    }
</style>
