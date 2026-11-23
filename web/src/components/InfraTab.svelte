<script>
    import { onMount } from 'svelte';
    import { Server, Laptop, Trash2, Loader2, Check, Terminal } from 'lucide-svelte';
    import { stats, machines, fetchMachines, fetchMachineUsage, hostVms, visible } from '../lib/stores.js';
    import { vmRef, vmHost } from '../lib/vmref.js';
    import { services, fetchServices, fetchUptime, findService } from '../lib/services.js';
    import { href } from '../lib/infra.js';
    import { fetchDisks } from '../lib/storage.js';
    import MachineDetail from './machines/MachineDetail.svelte';
    import MachineCreate from './machines/MachineCreate.svelte';
    import ServiceDetail from './services/ServiceDetail.svelte';
    import { hosts, fetchHosts, addHost, removeHost, installCommand, hostState, hostStateLabel, fmtGb, fmtDisk } from '../lib/hosts.js';
    import { fmtMb } from '../lib/services.js';
    import InfraIndex from './hosts/InfraIndex.svelte';
    import ArrakisHost from './hosts/ArrakisHost.svelte';
    import RemoteHost from './hosts/RemoteHost.svelte';
    import PoolList from './compute/PoolList.svelte';
    import PoolDetail from './compute/PoolDetail.svelte';
    import PoolForm from './compute/PoolForm.svelte';
    import { fetchPools } from '../lib/compute.js';
    import StatusPill from './ui/StatusPill.svelte';
    import Tabs from './ui/Tabs.svelte';
    import CopyText from './ui/CopyText.svelte';
    import LiveChart from './ui/LiveChart.svelte';

    // Every node of the tree; routes are listed in lib/infra.js
    export let section = null;
    export let sub = null;
    export let onNavigate = () => {};

    $: page = !section ? 'list' : section === 'new' ? 'new' : section === 'arrakis' ? 'arrakis'
        : section === 'orbstack' || section.startsWith('orbstack~') ? 'create'
        : section === 'pools' ? (sub === 'new' ? 'pool-new' : 'pools') : section.startsWith('pool-') ? 'pool'
        : section.startsWith('vm-') ? 'machine' : section.startsWith('svc-') ? 'service' : 'detail';
    const go = (s, t = null) => onNavigate('Infra', s, t);

    // machines and services, as their own pages had them
    // a machine's ref (lib/vmref.js) and the host it runs on (null = Arrakis)
    $: machineName = page === 'machine' ? section.slice(3) : null;
    $: vmOn = page === 'machine' ? vmHost(machineName) : page === 'create' && section.startsWith('orbstack~') ? section.slice(9) : null;
    $: machineData = vmOn ? $hostVms[vmOn] : $machines;
    $: vmOnName = vmOn ? (($hosts || []).find(x => x.id === vmOn)?.name || vmOn) : null;
    const vmBack = (hid) => hid ? go(hid, 'vm') : go('arrakis', 'vm');
    $: svc = page === 'service' ? findService($services, section.slice(4)) : null;
    let now = Date.now();
    const toast = (m) => window.showToast?.(m);

    // ---- Arrakis figures for the cluster table (same sources as the Overview) ----------
    $: hd = $stats?.host?.details || {};
    const ratio = (s) => { const m = (s || '').match(/([0-9.]+)\s*[A-Za-z]*\s*\/\s*([0-9.]+)/); return m ? { used: +m[1], total: +m[2] } : null; };
    $: vmEngine = ($services || []).find(s => /orbstack/i.test(s.name || '') && s.status === 'running');
    $: pool = $machines?.pool;
    $: cores = $machines?.host?.cores || 0;
    $: upSince = (hd['Uptime'] || '').startsWith('T:') ? parseInt(hd['Uptime'].slice(2)) : null;
    $: arrakis = { cpu: parseFloat(hd['CPU Usage']), mem: ratio(hd['Memory']), disk: ratio(hd['Disk Space']), cores, os: 'macOS', up: upSince ? Date.now() / 1000 - upSince : null };
    $: vm = { running: !!vmEngine, cpu: vmEngine && cores ? (+vmEngine.cpu || 0) / cores : 0, memGb: vmEngine ? (vmEngine.mem_mb || 0) / 1024 : 0, limitGb: pool ? pool.memory_mib / 1024 : null, up: vmEngine?.uptime_seconds };

    // ---- add a host ------------------------------------------------------------------------
    let newName = '', adding = false, addError = '', added = null;
    async function submitAdd() {
        addError = '';
        adding = true;
        try { added = await addHost(newName.trim()); } catch (e) { addError = e.message; }
        adding = false;
    }
    $: addedHost = added && ($hosts || []).find(h => h.id === added.id);
    $: if (page !== 'new' && added) { added = null; newName = ''; }

    // ---- one host -------------------------------------------------------------------------
    $: h = page === 'detail' ? ($hosts || []).find(x => x.id === section) : null;
    $: r = h?.report;
    onMount(() => {
        fetchHosts(); fetchMachines(); fetchMachineUsage(); fetchServices(); fetchUptime(); fetchDisks(); fetchPools();
        const tick = setInterval(() => now = Date.now(), 1000);
        const t = setInterval(() => { if (visible()) { fetchHosts(); fetchMachineUsage(); } }, 5000);
        const mid = setInterval(() => { if (visible()) { fetchMachines(); fetchServices(); fetchDisks(); fetchPools(); } }, 10000);
        const slow = setInterval(() => { if (visible()) fetchUptime(); }, 60000);
        return () => { clearInterval(tick); clearInterval(t); clearInterval(mid); clearInterval(slow); };
    });
</script>

{#if page === 'list'}
    <InfraIndex {arrakis} {vm} />

{:else if page === 'new'}
    <div class="ui-page narrow">
        <div class="ui-head"><div><h1>Add host</h1><p>Watch another computer on your tailnet from this dashboard.</p></div></div>

        <section class="ui-card">
            <div class="step" class:done={added}>
                <span class="num">{#if added}<Check size={13} strokeWidth={3} />{:else}1{/if}</span>
                <div class="step-body">
                    <h2>Name it</h2>
                    {#if added}
                        <p class="ui-dim">{added.name}</p>
                    {:else}
                        <form class="name-row" on:submit|preventDefault={submitAdd}>
                            <input class="ui-input" class:bad={addError} placeholder="e.g. shitty-pc" bind:value={newName} maxlength="41" autofocus />
                            <button class="ui-btn primary" disabled={!newName.trim() || adding}>{#if adding}<Loader2 size={14} class="ui-spin" />{/if} Continue</button>
                        </form>
                        {#if addError}<p class="err">{addError}</p>{:else}<p class="ui-hint">How it shows on the dashboard. Its own hostname is fine.</p>{/if}
                    {/if}
                </div>
            </div>

            <div class="step" class:muted={!added} class:done={addedHost?.online}>
                <span class="num">{#if addedHost?.online}<Check size={13} strokeWidth={3} />{:else}2{/if}</span>
                <div class="step-body">
                    <h2>Run this on the computer</h2>
                    {#if added}
                        <div class="cmd"><Terminal size={14} /><CopyText text={added.command} /></div>
                        <p class="ui-hint">Works on macOS and Linux. It needs Tailscale (to reach Arrakis) and curl. Run it as root on Linux to install a systemd service; otherwise it starts with launchd (macOS) or cron.</p>
                    {:else}
                        <p class="ui-hint">A one-line install command appears here.</p>
                    {/if}
                </div>
            </div>

            <div class="step" class:muted={!added} class:done={addedHost?.online}>
                <span class="num">{#if addedHost?.online}<Check size={13} strokeWidth={3} />{:else}3{/if}</span>
                <div class="step-body">
                    <h2>Wait for the first report</h2>
                    {#if addedHost?.online}
                        <p class="ok-line">{added.name} is reporting{addedHost.report?.os ? ` · ${addedHost.report.os}` : ''}. <a class="ui-link" href={href.host(added.id)}>Open host</a> · <a class="ui-link" href="#overview">Overview</a></p>
                    {:else if added}
                        <p class="wait"><Loader2 size={13} class="ui-spin" /> Waiting for {added.name}…</p>
                    {:else}
                        <p class="ui-hint">It shows up here and on the Overview within a few seconds.</p>
                    {/if}
                </div>
            </div>
        </section>
    </div>

{:else if page === 'pools'}
    <PoolList />

{:else if page === 'pool-new'}
    <div class="ui-page narrow-wide">
        <div class="ui-head"><div><h1>New pool</h1><p>Pick computers from the cluster. Their cores and memory then work as one machine for the jobs you run on the pool.</p></div></div>
        <PoolForm saved={(p) => { toast(`${p.name} created. Start it from its page`); go('pool-' + p.name); }} cancel={() => go('pools')} />
    </div>

{:else if page === 'pool'}
    {#key section}
        <PoolDetail name={section.slice(5)} tab={sub || 'overview'} setTab={(t) => go(section, t === 'overview' ? null : t)} />
    {/key}

{:else if page === 'arrakis'}
    <ArrakisHost {arrakis} {vm} tab={sub || 'overview'} setTab={(t) => go('arrakis', t === 'overview' ? null : t)} />

{:else if page === 'create' || page === 'machine'}
    {#if machineData?.error}
        <div class="ui-page"><div class="ui-banner warn">{machineData.error}</div></div>
    {:else if !machineData}
        <div class="ui-page"><div class="ui-dim">Loading machines…</div></div>
    {:else if page === 'create'}
        <MachineCreate data={machineData} onHost={vmOn} hostName={vmOnName || 'Arrakis'} back={() => vmBack(vmOn)} created={(n) => go('vm-' + vmRef(vmOn, n))} />
    {:else if page === 'machine'}
        {#key machineName}
            <MachineDetail data={machineData} name={machineName} hostName={vmOnName || 'the Mac'} tab={sub || 'overview'} setTab={(t) => go(section, t === 'overview' ? null : t)} back={() => vmBack(vmOn)} />
        {/key}
    {/if}

{:else if page === 'service'}
    {#if !$services}
        <div class="ui-page"><div class="ui-dim">Loading…</div></div>
    {:else if page === 'service'}
        {#if svc}
            {#key svc.key}
                <ServiceDetail {svc} {now} host={svc.host === 'Mac' ? 'Arrakis' : svc.host} tab={sub || 'overview'} setTab={(t) => go('svc-' + svc.id, t === 'overview' ? null : t)} />
            {/key}
        {:else}
            <div class="ui-page"><div class="ui-head"><div><h1>{section.slice(4)}</h1><p>No service by this name.</p></div></div></div>
        {/if}
    {/if}

{:else if !h}
    <div class="ui-page"><div class="ui-head"><div><h1>{section}</h1><p>{$hosts ? 'This host was removed.' : 'Loading…'}</p></div></div></div>

{:else}
    {#key h.id}
        <RemoteHost {h} tab={sub || 'overview'} setTab={(t) => go(section, t === 'overview' ? null : t)} removed={() => go(null)} />
    {/key}
{/if}

<style>
    .narrow { max-width: 760px; }
    .narrow-wide { max-width: 1000px; }
    .step { display: grid; grid-template-columns: 26px 1fr; gap: 14px; padding: 20px; border-top: 1px solid var(--border); }
    .step:first-child { border-top: none; }
    .step.muted { opacity: 0.55; }
    .num { width: 26px; height: 26px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12.5px; font-weight: 600; background: var(--highlight-10); color: var(--text-secondary); }
    .step.done .num { background: var(--green); color: var(--surface); }
    .step-body { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
    .step-body h2 { margin: 3px 0 0; font-size: 14.5px; font-weight: 600; color: var(--text-primary); }
    .step-body p { margin: 0; }
    .name-row { display: flex; gap: 8px; max-width: 420px; }
    .name-row .ui-input { flex: 1; min-width: 0; }
    .err { font-size: 12.5px; color: var(--red); }
    .cmd { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; border-radius: var(--radius-card, 8px); background: var(--highlight-5); border: 1px solid var(--border); color: var(--text-secondary); min-width: 0; max-width: 100%; box-sizing: border-box; }
    .cmd :global(svg) { flex-shrink: 0; margin-top: 4px; }
    .cmd :global(.copy) { align-items: flex-start; }
    .cmd :global(code) { color: var(--text-primary); line-height: 1.6; }
    .wait { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-secondary); }
    .ok-line { font-size: 13px; color: var(--text-primary); }
    .lbl { font-size: 13.5px; font-weight: 500; }
    .ui-form-row .ui-hint { margin: 2px 0 0; }

    .id { display: flex; align-items: center; gap: 14px; }
    .icon { width: 52px; height: 52px; border-radius: 12px; border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); flex-shrink: 0; }
    .icon.on { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
    .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .chart { padding: 8px 12px; }
    .cn { display: inline-flex; align-items: center; gap: 8px; font-weight: 500; }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--highlight-30); flex-shrink: 0; }
    .dot.up { background: var(--green); }
    tr.down td { color: var(--text-secondary); }
    @media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
</style>
