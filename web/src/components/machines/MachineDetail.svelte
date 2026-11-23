<script>
    import { openShell } from '../../lib/terminal.js';
    import { onMount } from 'svelte';
    import { Play, Square, RotateCw, Trash2, Loader2, ExternalLink, LogOut, Server, Box, Settings2, Network, ChevronRight, SquareTerminal } from 'lucide-svelte';
    import { gbFromMib } from '../../lib/stores.js';
    import { api } from '../../lib/machines.js';
    import { refreshMachines } from '../../lib/stores.js';
    import { vmRef, vmHost, vmName, vmUrl } from '../../lib/vmref.js';
    import { busy, machineAction, tailscaleJoin, tailscaleLeave, samples, latest, startSampling, imageLabel, tsLabel, fmtBytes, fmtDuration } from '../../lib/machines.js';
    import StatusPill from '../ui/StatusPill.svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';
    import Tabs from '../ui/Tabs.svelte';
    import CopyText from '../ui/CopyText.svelte';
    import LiveChart from '../ui/LiveChart.svelte';
    import { bucketed } from '../../lib/spark.js';
    import PairGrid from '../ui/PairGrid.svelte';
    import MachineWorkloads from './MachineWorkloads.svelte';
    import MachineSharing from './MachineSharing.svelte';
    import PersonPage from './PersonPage.svelte';
    import MachineSettings from './MachineSettings.svelte';

    export let data;
    export let name;                  // machine ref (vmref.js): its name on Arrakis, <host>~<name> elsewhere
    export let hostName = 'the Mac';  // the computer it runs on, in words
    export let tab = 'overview';
    export let setTab = () => {};
    export let back = () => {};

    const TABS = [
        { id: 'overview', label: 'Overview' },
        { id: 'workloads', label: 'Workloads' },
        { id: 'metrics', label: 'Metrics' },
        { id: 'networking', label: 'Networking' },
        { id: 'sharing', label: 'Sharing' },
        { id: 'settings', label: 'Settings' },
    ];

    $: mname = vmName(name);
    $: m = (data.machines || []).find(x => x.name === mname);
    $: job = data.jobs?.[mname];
    $: running = m?.state === 'running';
    $: b = $busy[name];
    $: s = $latest[name];
    $: pts = $samples[name] || [];
    // sparklines span the samples there are (history restarts with the backend), minus
    // the first one, whose CPU figure has no earlier reading to compare with
    $: sparkPts = pts.slice(1);
    $: sparkWin = sparkPts.length > 1 ? Math.min(3600000, Math.max(5 * 60000, sparkPts.at(-1).t - sparkPts[0].t)) : 3600000;
    $: isDash = !!data.dashboard_vm && mname === data.dashboard_vm;
    $: pool = data.pool;
    $: host = data.host;

    // Sample usage while the page is open and the machine runs
    let stop = null;
    $: if (running && !stop) stop = startSampling(name);
    $: if (!running && stop) { stop(); stop = null; }
    onMount(() => () => stop?.());

    const pct = (a, b) => b ? Math.min(100, (a / b) * 100) : 0;
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
    const agoS = (t) => { const x = Math.max(0, Date.now() / 1000 - t); return x < 90 ? `${Math.round(x)} s ago` : `${Math.round(x / 60)} min ago`; };

    // ---- overview: what runs inside -------------------------------------------------------
    let work = null;
    async function loadWork() {
        if (!running || tab !== 'overview') return;
        try { const j = await fetch(vmUrl(name, '/workloads')).then(r => r.json()); if (j.status === 'success') work = j.data; } catch (e) {}
    }
    $: if (running && tab === 'overview') loadWork();
    onMount(() => { const t = setInterval(loadWork, 30000); return () => clearInterval(t); });
    $: runRows = work ? [
        { icon: Box, name: 'Containers', tab: 'workloads',
          sub: work.docker == null ? 'Docker is not installed' : work.docker.length ? work.docker.slice(0, 4).map(c => c.name).join(', ') + (work.docker.length > 4 ? ` +${work.docker.length - 4}` : '') : 'none',
          value: work.docker == null ? '—' : `${work.docker.filter(c => c.state === 'running').length} of ${work.docker.length}` },
        { icon: Settings2, name: 'Services', tab: 'workloads',
          sub: (() => { const own = work.services.filter(u => !u.base); return own.length ? own.slice(0, 4).map(u => u.unit).join(', ') + (own.length > 4 ? ` +${own.length - 4}` : '') : 'only the standard system ones'; })(),
          value: String(work.services.filter(u => !u.base).length) },
        { icon: Network, name: 'Listening ports', tab: 'workloads',
          sub: work.listening.length ? work.listening.slice(0, 6).map(l => l.port).join(', ') + (work.listening.length > 6 ? ` +${work.listening.length - 6}` : '') : 'none',
          value: `${work.listening.filter(l => !l.local_only).length} open` },
    ] : [];
    $: detailRows = m ? [
        [{ k: 'Operating system', v: s?.os || imageLabel(m.image) }, { k: `Shell on ${hostName}`, v: `orb -m ${m.name}`, copy: true }],
        [{ k: 'Image', v: `${m.image?.distro} · ${m.image?.version} · ${m.image?.variant || 'default'}` }, { k: `SSH on ${hostName}`, v: `ssh ${m.name}@orb`, copy: true }],
        [{ k: 'Architecture', v: m.image?.arch }, { k: 'Local hostname', v: `${m.name}.orb.local`, copy: true }],
        [{ k: 'Kernel', v: s?.kernel || '—', mono: true }, m.tailscale?.state === 'running' && m.tailscale.dns ? { k: 'Tailscale SSH', v: `ssh ${m.username || 'root'}@${m.tailscale.dns}`, copy: true } : { k: 'Tailscale', v: tsLabel(m.tailscale), action: { label: tsLabel(m.tailscale) + ' · set up', onClick: () => setTab('networking') } }],
        [{ k: 'CPU limit', v: m.cpu ? plural(m.cpu, 'core') : `Shares the pool (${pool.cpu} cores)` }, { k: 'IP address', v: running && m.ip ? m.ip : '—', copy: true }],
        [{ k: 'Memory limit', v: m.memory_mib ? gbFromMib(m.memory_mib) : `Shares the pool (${gbFromMib(pool.memory_mib)})` }, { k: 'Default user', v: m.username || '—', mono: true }],
        [{ k: 'Mac files', v: m.isolated ? (m.isolate_network ? 'Isolated, network too' : 'Isolated, not mounted') : 'Mounted' }, { k: 'Disk limit', v: m.disk_bytes ? `${Math.round(m.disk_bytes / 2 ** 30)} GB` : 'None' }],
    ] : [];
    const BUSY = { start: 'Starting', stop: 'Stopping', restart: 'Restarting', delete: 'Deleting', join: 'Joining Tailscale', leave: 'Leaving Tailscale', share: 'Sharing', unshare: 'Unsharing', limits: 'Saving' };

    let confirmLeave = false;

    $: menuItems = m ? [
        running ? { label: 'Restart', icon: RotateCw, onClick: () => machineAction(name, 'restart') } : { label: 'Start', icon: Play, onClick: () => machineAction(name, 'start') },
        running ? { label: 'Stop', icon: Square, onClick: () => machineAction(name, 'stop') } : null,
        m.tailscale?.state === 'running' ? { label: 'Open in Tailscale admin', icon: ExternalLink, onClick: () => window.open(`https://login.tailscale.com/admin/machines/${m.tailscale.ip}`, '_blank', 'noopener') } : null,
        { label: 'Delete machine…', icon: Trash2, danger: true, divider: true, onClick: () => setTab('settings') },
    ] : [];
</script>

<div class="ui-page">
    <div>
        {#if !m}
            <div class="ui-head"><div><h1>{mname}</h1><p>{job?.state === 'creating' ? 'Being created…' : 'This machine no longer exists.'}</p></div></div>
        {:else}
            <div class="ui-head">
                <div class="id">
                    <span class="icon" class:on={running}><Server size={20} /></span>
                    <div>
                    <h1>{m.name}
                        {#if b}<StatusPill state="starting" label={BUSY[b]} />{:else}<StatusPill state={m.state} />{/if}
                        {#if isDash}<span class="ui-tag">Dashboard</span>{/if}
                    </h1>
                    <div class="ui-meta">
                        <span>{s?.os || imageLabel(m.image)}</span>
                        <span>{m.image?.arch}{m.image?.arch === 'arm64' ? ' (native)' : ' (Rosetta)'}</span>
                        {#if running && m.ip}<span>IP <b class="ui-mono">{m.ip}</b></span>{/if}
                        {#if running && s}<span>Up {fmtDuration(s.uptime_secs)}</span>{/if}
                    </div>
                    </div>
                </div>
                <div class="ui-head-actions">
                    {#if running && !name.includes('~')}<button class="ui-btn" on:click={() => openShell(name)} title="A tmux session named shell on this machine"><SquareTerminal size={14} /> Shell</button>{/if}
                    {#if running}
                        <button class="ui-btn" disabled={!!b} on:click={() => machineAction(name, 'restart')}>{#if b === 'restart'}<Loader2 size={14} class="ui-spin" /> Restarting…{:else}<RotateCw size={14} /> Restart{/if}</button>
                        <button class="ui-btn" disabled={!!b} on:click={() => machineAction(name, 'stop')}>{#if b === 'stop'}<Loader2 size={14} class="ui-spin" /> Stopping…{:else}<Square size={14} /> Stop{/if}</button>
                    {:else}
                        <button class="ui-btn primary" disabled={!!b} on:click={() => machineAction(name, 'start')}>{#if b === 'start'}<Loader2 size={14} class="ui-spin" /> Starting…{:else}<Play size={14} /> Start{/if}</button>
                    {/if}
                    <ActionMenu items={menuItems} label="More actions" />
                </div>
            </div>
        {/if}
    </div>

    {#if m}
    <Tabs tabs={TABS} active={tab.startsWith('person-') ? 'sharing' : tab} onSelect={setTab} />

    {#if tab === 'overview'}
        {#if !running}
            <div class="ui-banner warn">This machine is {m.state}. Usage figures appear once it runs. <button class="ui-link" on:click={() => machineAction(name, 'start')}>Start it</button></div>
        {/if}
        <div class="ui-stats">
            <div class="ui-stat">
                <span class="ui-stat-label">CPU</span>
                <span class="ui-stat-value">{s && running ? s.cpu_pct.toFixed(1) + '%' : '—'}<small>of {m.cpu ? m.cpu + ' cores' : pool.cpu + ' cores (pool)'}</small></span>
                <div class="spark">{#if running && pts.length > 1}<LiveChart points={bucketed(sparkPts.map(p => [p.t, p.cpu]))} windowMs={sparkWin} height={36} bare />{/if}</div>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Memory</span>
                <span class="ui-stat-value">{s && running ? fmtBytes(s.mem_bytes) : '—'}<small>of {m.memory_mib ? gbFromMib(m.memory_mib) : gbFromMib(pool.memory_mib) + ' (pool)'}</small></span>
                <div class="spark">{#if running && pts.length > 1}<LiveChart points={bucketed(sparkPts.map(p => [p.t, p.mem / 2 ** 30]))} windowMs={sparkWin} height={36} color="var(--metric-mem)" min={0} max={s ? s.mem_limit_bytes / 2 ** 30 : null} bare />{/if}</div>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Disk</span>
                <span class="ui-stat-value">{m.disk_usage || '—'}</span>
                <span class="ui-stat-sub">on the shared OrbStack disk</span>
            </div>
            <div class="ui-stat">
                <span class="ui-stat-label">Uptime</span>
                <span class="ui-stat-value">{s && running ? fmtDuration(s.uptime_secs) : '—'}</span>
                <span class="ui-stat-sub">{s && running ? `${s.processes} processes` : 'not running'}</span>
            </div>
        </div>

        <!-- what runs inside, from the 30 s workloads scan -->
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">What runs here</h2><p class="ui-card-desc">{work ? `Read from inside ${m.name} ${agoS(work.at)}.` : running ? 'Reading…' : 'Shown while the machine runs.'}</p></div></div>
            {#if work}
                <div class="lt" role="table">
                    <div class="lt-r lt-h" role="row"><span></span><span>Part</span><span>Count</span><span></span></div>
                    {#each runRows as r}
                        <button class="lt-r" on:click={() => setTab(r.tab)}>
                            <span class="lt-ic"><svelte:component this={r.icon} size={15} /></span>
                            <span class="lt-n"><b>{r.name}</b><small>{r.sub}</small></span>
                            <span class="lt-v">{r.value}</span>
                            <ChevronRight size={15} class="lt-go" />
                        </button>
                    {/each}
                </div>
            {/if}
        </section>

        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Details</h2><p class="ui-card-desc">How it is configured, and how to open a shell on it.</p></div></div>
            <PairGrid rows={detailRows} heads={["Configuration", "Connect"]} />
        </section>

    {:else if tab === 'workloads'}
        <MachineWorkloads {name} {running} linkContainers={isDash} />

    {:else if tab === 'metrics'}
        <p class="ui-hint" style="margin: 0">Usage of this machine alone, from its own cgroup. Last hour, sampled every 5 seconds.</p>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">CPU</h2><p class="ui-card-desc">Percent of the {m.cpu ? m.cpu + ' cores it is limited to' : pool.cpu + ' pool cores it can use'}</p></div>
                <span class="big">{s && running ? s.cpu_pct.toFixed(1) + '%' : '—'}</span></div>
            <div class="ui-card-body chart">
                {#if pts.length > 1}<LiveChart windowMs={3600000} points={pts.map(p => [p.t, p.cpu])} max={100} unit="%" />
                {:else}<div class="ui-empty">{running ? 'Collecting samples…' : 'Not running.'}</div>{/if}
            </div>
        </section>
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Memory</h2><p class="ui-card-desc">Used, against {m.memory_mib ? 'its own limit' : 'the shared pool'} of {s ? fmtBytes(s.mem_limit_bytes) : '—'}</p></div>
                <span class="big">{s && running ? fmtBytes(s.mem_bytes) : '—'}</span></div>
            <div class="ui-card-body chart">
                {#if pts.length > 1}<LiveChart windowMs={3600000} points={pts.map(p => [p.t, p.mem / 2 ** 30])} max={s ? +(s.mem_limit_bytes / 2 ** 30).toFixed(1) : null} color="var(--metric-mem)" unit=" GB" />
                {:else}<div class="ui-empty">{running ? 'Collecting samples…' : 'Not running.'}</div>{/if}
            </div>
        </section>

    {:else if tab === 'networking'}
        <section class="ui-card">
            <div class="ui-card-head"><div><h2 class="ui-card-title">Local network</h2><p class="ui-card-desc">Reachable from the Mac and from other machines.</p></div></div>
            <dl class="ui-kv" style="border-top: 1px solid var(--border)">
                <dt>IPv4 address</dt><dd>{#if running && m.ip}<CopyText text={m.ip} />{:else}<span class="ui-dim">Assigned when running</span>{/if}</dd>
                <dt>Hostname</dt><dd><CopyText text="{m.name}.orb.local" /></dd>
            </dl>
        </section>
        <section class="ui-card">
            <div class="ui-card-head">
                <div><h2 class="ui-card-title">Tailscale</h2><p class="ui-card-desc">Puts the machine on your tailnet with Tailscale SSH, so it is reachable from anywhere.</p></div>
                <StatusPill state={job?.kind === 'tailscale' && job.state === 'creating' ? 'joining' : m.tailscale?.state === 'running' ? 'connected' : ''} label={job?.kind === 'tailscale' && job.state === 'creating' ? 'Joining…' : running ? tsLabel(m.tailscale) : 'Unknown'} />
            </div>
            {#if m.tailscale?.state === 'running'}
                <dl class="ui-kv" style="border-top: 1px solid var(--border)">
                    <dt>Tailscale IP</dt><dd><CopyText text={m.tailscale.ip} /></dd>
                    <dt>DNS name</dt><dd>{#if m.tailscale.dns}<CopyText text={m.tailscale.dns} />{:else}—{/if}</dd>
                    <dt>Tags</dt><dd>{m.tailscale.tags?.length ? m.tailscale.tags.join(', ') : 'None'}</dd>
                </dl>
                <div class="ui-card-foot">
                    {#if confirmLeave}
                        <span>Log {mname} out of Tailscale? It drops off the tailnet until it joins again.</span>
                        <span class="ui-btns"><button class="ui-btn sm" on:click={() => confirmLeave = false}>Cancel</button><button class="ui-btn sm danger" on:click={() => { confirmLeave = false; tailscaleLeave(name); }}>Leave tailnet</button></span>
                    {:else}
                        <span>To share this machine with a person, use the Tailscale admin console.</span>
                        <span class="ui-btns">
                            <a class="ui-btn sm" href="https://login.tailscale.com/admin/machines/{m.tailscale.ip}" target="_blank" rel="noopener">Share <ExternalLink size={12} /></a>
                            <button class="ui-btn sm danger-outline" on:click={() => confirmLeave = true}><LogOut size={13} /> Leave</button>
                        </span>
                    {/if}
                </div>
            {:else}
                <div class="ui-card-foot">
                    {#if job?.kind === 'tailscale' && job.state === 'error'}<span>Join failed: {job.message || 'unknown error'}</span>
                    {:else if !running}<span>Start the machine to join it to Tailscale.</span>
                    {:else if !data.tailscale_key}<span>Add a Tailscale auth key in <a class="ui-link" href="#settings/tailscale">Settings</a> to join machines.</span>
                    {:else}<span>Installs Tailscale if needed and logs in with the stored auth key.</span>{/if}
                    <span class="ui-btns"><button class="ui-btn sm primary" disabled={!running || !data.tailscale_key || !!b || job?.state === 'creating'} on:click={() => tailscaleJoin(name)}>{#if b === 'join'}<Loader2 size={13} class="ui-spin" />{/if}{m.tailscale?.state === 'missing' ? 'Join tailnet' : 'Reconnect'}</button></span>
                </div>
            {/if}
        </section>


    {:else if tab === 'sharing'}
        <MachineSharing {data} {m} {job} ref={name} openPerson={(u) => setTab('person-' + u)} />
    {:else if tab.startsWith('person-')}
        <PersonPage {data} {m} ref={name} user={tab.slice(7)} back={() => setTab('sharing')} />

    {:else if tab === 'settings'}
        <MachineSettings {data} {m} {name} {back} />
    {/if}
    {/if}
</div>

<style>
    .id { display: flex; align-items: center; gap: 16px; min-width: 0; }
    .ui-head { padding: 4px 0 2px; }
    .ui-head h1 { line-height: 1.2; }
    .icon { width: 52px; height: 52px; border-radius: 12px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); border: 1px solid var(--border); }
    .icon.on { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
    .id .ui-meta { margin-top: 6px; }
    .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
    .big { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text-primary); white-space: nowrap; }
    .chart { padding-top: 8px; padding-bottom: 8px; }
    .spark { height: 36px; margin: 2px -4px -4px; }
    .lt { border-top: 1px solid var(--border); }
    .lt-r { display: grid; grid-template-columns: 30px minmax(0, 1fr) 150px 16px; gap: 0 16px; align-items: center; width: 100%; padding: 12px 20px; border-bottom: 1px solid var(--border); text-align: left; font-size: 13px; color: var(--text-primary); cursor: pointer; box-sizing: border-box; }
    .lt-r:last-child { border-bottom: none; }
    .lt-r:not(.lt-h):hover { background: var(--highlight-3); }
    .lt-r:hover b, .lt-r:hover :global(.lt-go) { color: var(--accent); }
    /* same look as the host's "What uses" header: quiet labels, every column left-aligned */
    .lt-h { padding-top: 14px; padding-bottom: 10px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); cursor: default; }
    .lt-ic { width: 30px; height: 30px; border-radius: var(--radius-card, 8px); display: flex; align-items: center; justify-content: center; background: var(--accent-soft); color: var(--accent); }
    .lt-n { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .lt-n b { font-weight: 600; }
    .lt-n small { font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .lt-v { font-weight: 500; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .lt-r :global(.lt-go) { color: var(--text-secondary); }
    a.ui-btn { text-decoration: none; }
    @media (max-width: 1000px) { .cols { grid-template-columns: 1fr; } }
    /* phone: cards inset 14px, so this lines up with the card's header */
    @media (max-width: 768px) { .lt-r, .dash-note { padding-left: 14px; padding-right: 14px; } .lt-r { grid-template-columns: 30px minmax(0, 1fr) 64px 14px; gap: 0 10px; } }
</style>
