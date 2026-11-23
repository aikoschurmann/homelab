<script>
    // OrbStack on one Mac (Arrakis, or a managed host): the pool every machine without its
    // own limit shares, and OrbStack-wide switches. One save bar; then restart OrbStack.
    import { Loader2, RotateCw } from 'lucide-svelte';
    import Stepper from '../Stepper.svelte';
    import Switch from '../ui/Switch.svelte';
    import { gbFromMib, fetchMachines, fetchHostVms } from '../../lib/stores.js';
    import { vmBase } from '../../lib/vmref.js';
    import { api } from '../../lib/machines.js';

    export let data;            // the machines payload: { host, pool, machines }
    export let onHost = null;   // another host's id; null = Arrakis
    export let hostName = 'Arrakis';

    const toast = (m) => window.showToast?.(m);
    $: base = vmBase(onHost);
    const refresh = () => onHost ? fetchHostVms(onHost) : fetchMachines();

    $: host = data?.host;
    $: pool = data?.pool;
    $: limited = (data?.machines || []).filter(m => m.memory_mib);
    $: maxGb = host ? Math.floor((host.memory_mib - 2048) / 1024) : 1;

    // [key, label, hint]: OrbStack-wide switches (see ORB_SWITCHES in vms.py)
    const SWITCHES = [
        ['machines.expose_ports_to_lan', 'Machine ports on the LAN', 'Other devices can reach machines'],
        ['docker.expose_ports_to_lan', 'Docker ports on the LAN', 'Other devices can reach containers (Pi-hole DNS!)'],
        ['machines.forward_ports', 'Forward to localhost', 'Machine servers also on the Mac\'s localhost'],
        ['network.https', 'HTTPS for .orb.local', 'Trusted certificates for name.orb.local'],
        ['ssh.expose_port', 'OrbStack SSH on the LAN', 'Built-in SSH server, port 32222'],
        ['power.pause_in_sleep', 'Pause while the Mac sleeps', 'Machines don\'t answer while it sleeps'],
        ['rosetta', 'Rosetta for Intel binaries', 'Run x86-64 programs on arm64'],
    ];
    $: orb = data?.orb || {};

    let cpu = 0, gb = 0, sw = {}, base0 = '', saving = false, needsRestart = false, restarting = false;
    $: snap = JSON.stringify([pool, orb]);
    $: if (pool && snap !== base0) { base0 = snap; cpu = pool.cpu; gb = +(pool.memory_mib / 1024).toFixed(1); sw = { ...orb }; }
    $: poolDirty = pool && (cpu !== pool.cpu || Math.round(gb * 1024) !== pool.memory_mib);
    $: swChanged = Object.fromEntries(SWITCHES.map(([k]) => k).filter(k => k in orb && !!sw[k] !== !!orb[k]).map(k => [k, !!sw[k]]));
    $: dirty = poolDirty || Object.keys(swChanged).length > 0;
    function reset() { cpu = pool.cpu; gb = +(pool.memory_mib / 1024).toFixed(1); sw = { ...orb }; }

    async function save() {
        saving = true;
        let ok = true;
        if (poolDirty) ok = (await api(`${base}/pool`, { method: 'PATCH', body: JSON.stringify({ cpu, memory_mib: Math.round(gb * 1024) }) })).status === 'success';
        if (ok && Object.keys(swChanged).length) ok = (await api(`${base}/orbstack`, { method: 'PATCH', body: JSON.stringify(swChanged) })).status === 'success';
        saving = false;
        if (ok) { needsRestart = true; await refresh(); }
    }
    async function restart() {
        restarting = true;
        const r = await api(`${base}/pool/restart`, { method: 'POST' });
        restarting = false;
        if (r.status === 'success') { needsRestart = false; toast('OrbStack restarted with the new pool'); refresh(); }
    }
</script>

{#if pool && host}
<section class="ui-card" data-setting="pool">
    <div class="ui-card-head"><div><h2 class="ui-card-title">OrbStack pool</h2><p class="ui-card-desc">The CPU and memory OrbStack takes from {hostName}. Every machine without its own limit shares it.</p></div></div>
    <div class="rows">
        <div class="ui-form-row" data-setting="pool-cpu">
            <div><div class="ui-label">CPU</div><div class="ui-hint">{hostName} has {host.cores} cores</div></div>
            <Stepper bind:value={cpu} min={1} max={host.cores} step={1} unit={cpu === 1 ? 'core' : 'cores'} />
        </div>
        <div class="ui-form-row" data-setting="pool-memory">
            <div><div class="ui-label">Memory</div><div class="ui-hint">{hostName} has {gbFromMib(host.memory_mib)}; macOS keeps 2 GB</div></div>
            <Stepper bind:value={gb} min={1} max={maxGb} step={0.5} unit="GB" />
        </div>
    </div>
    {#if limited.length}<div class="ui-card-foot"><span>Machines with their own memory limit: {limited.map(m => `${m.name} (${gbFromMib(m.memory_mib)})`).join(', ')}. A limit can't exceed the pool.</span></div>{/if}
</section>

<section class="ui-card" data-setting="orbstack">
    <div class="ui-card-head"><div><h2 class="ui-card-title">OrbStack</h2><p class="ui-card-desc">How OrbStack on {hostName} behaves, for every machine and container. Start at login is set in the OrbStack app.</p></div></div>
    <div class="rows">
        <slot name="manage" />
        {#each SWITCHES.filter(([k]) => k in orb) as [k, label, hint]}
            <div class="ui-form-row">
                <div><div class="ui-label">{label}</div><div class="ui-hint">{hint}</div></div>
                <Switch bind:checked={sw[k]}>{sw[k] ? 'On' : 'Off'}</Switch>
            </div>
        {/each}
    </div>
</section>

{#if dirty || needsRestart}
    <div class="savebar">
        {#if dirty}
            <span>Unsaved changes</span>
            <span class="ui-btns"><button class="ui-btn sm" on:click={reset}>Reset</button><button class="ui-btn sm primary" disabled={saving} on:click={save}>{#if saving}<Loader2 size={13} class="ui-spin" />{/if}Save</button></span>
        {:else}
            <span>Saved. Restart OrbStack to apply it (briefly stops Docker and every machine).</span>
            <span class="ui-btns"><button class="ui-btn sm" disabled={restarting} on:click={() => needsRestart = false}>Later</button><button class="ui-btn sm danger" disabled={restarting} on:click={restart}>{#if restarting}<Loader2 size={13} class="ui-spin" /> Restarting…{:else}<RotateCw size={13} /> Restart OrbStack{/if}</button></span>
        {/if}
    </div>
{/if}
{/if}

<style>
    .rows { border-top: 1px solid var(--border); }
    .ui-form-row { align-items: center; }
    .savebar { position: sticky; bottom: 12px; z-index: 5; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px 10px 18px; border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); box-shadow: 0 8px 24px rgba(0,0,0,.25); font-size: 13px; color: var(--text-secondary); }
</style>
