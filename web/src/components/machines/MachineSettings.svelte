<script>
    // A machine's Settings tab. Resources and isolation are one draft with one save bar
    // (both need a restart to apply); renaming and deleting are their own actions.
    import { Loader2, RotateCw, ArrowRight, X, Plus } from 'lucide-svelte';
    import Stepper from '../Stepper.svelte';
    import Switch from '../ui/Switch.svelte';
    import { api, busy, machineAction } from '../../lib/machines.js';
    import { gbFromMib, refreshMachines } from '../../lib/stores.js';
    import { vmRef, vmHost, vmName, vmUrl } from '../../lib/vmref.js';

    export let data;
    export let m;
    export let name;          // machine ref
    export let back = () => {};

    $: mname = vmName(name);
    $: host = data.host;
    $: pool = data.pool;
    $: isDash = !!data.dashboard_vm && mname === data.dashboard_vm;
    $: b = $busy[name];
    $: running = m.state === 'running';

    // ---- one draft for everything with a save button --------------------------------
    // OrbStack options (resources, isolation, folders, agent, web ports) apply after a
    // restart; the machine's own system settings (timezone, updates) apply at once.
    const fromM = (m) => ({
        cpuOwn: !!m.cpu, cpu: m.cpu || Math.min(2, host.cores),
        memOwn: !!m.memory_mib, gb: m.memory_mib ? +(m.memory_mib / 1024).toFixed(1) : 2,
        diskOwn: !!m.disk_bytes, disk: m.disk_bytes ? Math.round(m.disk_bytes / 2 ** 30) : 16,
        isolated: !!m.isolated, isolate_network: !!m.isolate_network,
        mounts: (m.mounts || []).map(x => ({ ...x })), agent: !!m.forward_ssh_agent,
        http: m.http_port || 0, https: m.https_port || 0,
    });
    const out = (d) => ({
        limits: { cpu: d.cpuOwn ? d.cpu : 0, memory_mib: d.memOwn ? Math.round(d.gb * 1024) : 0, disk_gib: d.diskOwn ? d.disk : 0 },
        iso: { isolated: d.isolated, isolate_network: d.isolated && d.isolate_network },
        opts: { mounts: d.isolated ? d.mounts : [], forward_ssh_agent: d.isolated && d.agent, http_port: +d.http || 0, https_port: +d.https || 0 },
    });
    let d = null, base = null;
    $: cur = JSON.stringify(out(fromM(m)));
    $: if (cur !== JSON.stringify(base)) { base = JSON.parse(cur); d = fromM(m); }
    $: o = d && out(d);
    $: changed = o ? Object.fromEntries(Object.keys(o).map(k => [k, JSON.stringify(o[k]) !== JSON.stringify(base[k])])) : {};

    // system settings inside the machine
    let sys = null, sysBase = null, timezones = [];
    async function loadSys() {
        if (!running) return;
        const r = await api(vmUrl(name, '/system'));
        if (r.status === 'success') { timezones = r.data.timezones; sysBase = { timezone: r.data.timezone, autoupdate: r.data.autoupdate, pm: r.data.package_manager }; sys = { ...sysBase }; }
    }
    $: if (running && !sysBase) loadSys();
    $: sysChanged = sys && sysBase && (sys.timezone !== sysBase.timezone || sys.autoupdate !== sysBase.autoupdate);
    $: dirty = (o && Object.values(changed).some(Boolean)) || sysChanged;

    let saving = false, needsRestart = false, error = '';
    async function save() {
        saving = true; error = '';
        const steps = [
            changed.limits && (() => api(vmUrl(name, '/limits'), { method: 'PATCH', body: JSON.stringify(o.limits) })),
            changed.iso && (() => api(vmUrl(name, '/isolation'), { method: 'PATCH', body: JSON.stringify(o.iso) })),
            changed.opts && (() => api(vmUrl(name, '/options'), { method: 'PATCH', body: JSON.stringify(o.opts) })),
            sysChanged && (() => api(vmUrl(name, '/system'), { method: 'PATCH', body: JSON.stringify({ timezone: sys.timezone, autoupdate: sys.autoupdate }) })),
        ].filter(Boolean);
        const restartish = changed.limits || changed.iso || changed.opts;
        for (const step of steps) {
            const r = await step();
            if (r.status !== 'success') { error = r.message || 'Could not save'; break; }
        }
        saving = false;
        if (!error) {
            if (sysChanged) sysBase = { ...sys };
            needsRestart = running && restartish;
            if (!needsRestart) window.showToast?.('Saved');
        }
        await refreshMachines(name);
    }
    async function restart() { if (await machineAction(name, 'restart')) needsRestart = false; }
    function reset() { d = fromM(m); if (sysBase) sys = { ...sysBase }; error = ''; }

    // shared folders
    let newSrc = '', newDest = '';
    const destFor = (src) => '/mnt/' + (src.replace(/\/+$/, '').split('/').pop() || 'shared');
    function addMount() {
        const src = newSrc.trim().replace(/^~(?=\/|$)/, data.home || '~');
        if (!src) return;
        d = { ...d, mounts: [...d.mounts, { source: src, dest: newDest.trim() || destFor(src) }] };
        newSrc = ''; newDest = '';
    }
    const removeMount = (i) => d = { ...d, mounts: d.mounts.filter((_, j) => j !== i) };

    // ---- rename ------------------------------------------------------------------------
    let newName = '', renaming = false;
    $: if (m && !newName && !renaming) newName = m.name;
    $: nameOk = /^[a-z0-9][a-z0-9-]{0,62}$/.test(newName) && newName !== mname;
    async function rename() {
        renaming = true;
        const r = await api(vmUrl(name, '/rename'), { method: 'POST', body: JSON.stringify({ name: newName }) });
        if (r.status === 'success') {
            window.showToast?.(r.data.dashboard_restarting ? `Renamed to ${newName}. The dashboard restarts to pick it up` : `Renamed to ${newName}`);
            const to = `#infra/vm-${encodeURIComponent(vmRef(vmHost(name), newName))}/settings`;
            if (r.data.dashboard_restarting) setTimeout(() => { location.hash = to; location.reload(); }, 3000);
            else { await refreshMachines(name); location.hash = to; }
        }
        renaming = false;
    }

    // ---- delete ------------------------------------------------------------------------
    let confirmName = '';
    async function del() { if (await machineAction(name, 'delete')) back(); }
</script>

<section class="ui-card">
    <div class="ui-card-head"><div><h2 class="ui-card-title">General</h2></div></div>
    <div class="rows">
        <div class="ui-form-row">
            <div><div class="ui-label">Name</div><div class="ui-hint">Lowercase, digits and dashes</div></div>
            <div class="ctl col">
                <form class="ctl" on:submit|preventDefault={() => nameOk && rename()}>
                    <input class="ui-input mono" bind:value={newName} maxlength="63" spellcheck="false" />
                    {#if newName !== mname}<button class="ui-btn sm primary" disabled={!nameOk || renaming}>{#if renaming}<Loader2 size={13} class="ui-spin" />{/if}Rename</button>{/if}
                </form>
                {#if newName !== mname && isDash}<div class="ui-hint">This is the dashboard's machine; the dashboard restarts by itself to follow the new name.</div>{/if}
            </div>
        </div>
    </div>
</section>

{#if d}
<section class="ui-card">
    <div class="ui-card-head"><div><h2 class="ui-card-title">Resources</h2><p class="ui-card-desc">Caps inside the OrbStack pool. Applied when {mname} restarts.</p></div></div>
    <div class="rows res">
        <div class="ui-form-row">
            <div><div class="ui-label">CPU</div><div class="ui-hint">Pool: {pool.cpu} cores</div></div>
            <div class="ctl">
                <div class="ui-seg"><button class:on={!d.cpuOwn} on:click={() => d.cpuOwn = false}>No limit</button><button class:on={d.cpuOwn} on:click={() => d.cpuOwn = true}>Limit</button></div>
                {#if d.cpuOwn}<Stepper bind:value={d.cpu} min={1} max={host.cores} step={1} unit={d.cpu === 1 ? 'core' : 'cores'} />{/if}
            </div>
        </div>
        <div class="ui-form-row">
            <div><div class="ui-label">Memory</div><div class="ui-hint">Pool: {gbFromMib(pool.memory_mib)}</div></div>
            <div class="ctl">
                <div class="ui-seg"><button class:on={!d.memOwn} on:click={() => d.memOwn = false}>No limit</button><button class:on={d.memOwn} on:click={() => d.memOwn = true}>Limit</button></div>
                {#if d.memOwn}<Stepper bind:value={d.gb} min={1} max={host.memory_mib / 1024} step={0.5} unit="GB" />{/if}
            </div>
        </div>
        <div class="ui-form-row">
            <div><div class="ui-label">Disk</div><div class="ui-hint">{m.disk_usage || '—'} used</div></div>
            <div class="ctl">
                <div class="ui-seg"><button class:on={!d.diskOwn} on:click={() => d.diskOwn = false}>No limit</button><button class:on={d.diskOwn} on:click={() => d.diskOwn = true}>Limit</button></div>
                {#if d.diskOwn}<Stepper bind:value={d.disk} min={2} max={2048} step={1} unit="GB" />{/if}
            </div>
        </div>
    </div>
</section>

<section class="ui-card">
    <div class="ui-card-head"><div><h2 class="ui-card-title">Isolation</h2><p class="ui-card-desc">What {mname}, and everyone who logs in to it, can reach on this Mac.</p></div></div>
    <div class="rows">
        <div class="ui-form-row">
            <div><div class="ui-label">Mac files</div><div class="ui-hint">/Users, /Volumes, <span class="ui-mono">mac</span> command</div></div>
            <div class="ctl col">
                <Switch bind:checked={d.isolated} disabled={!!m.share && m.isolated}>Isolated</Switch>
                {#if !d.isolated}<div class="ui-hint bad">Anyone on {mname} can read your Mac's files and run commands on it{m.share ? ', and it is shared' : ''}.</div>
                {:else if m.share && m.isolated}<div class="ui-hint">Required while {mname} is shared.</div>{/if}
            </div>
        </div>
        {#if d.isolated}
            <div class="ui-form-row">
                <div><div class="ui-label">Shared folders</div><div class="ui-hint">Read and write</div></div>
                <div class="ctl col wide">
                    {#if d.mounts.length}
                        <div class="mounts">
                            {#each d.mounts as mt, i}
                                <div class="mt"><span class="ui-mono src" title={mt.source}>{mt.source}</span><ArrowRight size={13} /><span class="ui-mono">{mt.dest}</span>
                                    <button class="x" title="Stop sharing this folder" aria-label="Remove" on:click={() => removeMount(i)}><X size={14} /></button></div>
                            {/each}
                        </div>
                    {/if}
                    <form class="addm" on:submit|preventDefault={addMount}>
                        <input class="ui-input mono" placeholder="/Users/{m.username || 'you'}/Projects" bind:value={newSrc} spellcheck="false" />
                        <ArrowRight size={13} />
                        <input class="ui-input mono dst" placeholder={newSrc ? destFor(newSrc) : '/mnt/projects'} bind:value={newDest} spellcheck="false" />
                        <button class="ui-btn sm" disabled={!newSrc.trim()}><Plus size={13} /> Add</button>
                    </form>
                    {#if m.share && d.mounts.length}<div class="ui-hint bad">People who log in can read these folders (and change them, if they have root).</div>{/if}
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">SSH agent</div><div class="ui-hint">Use your Mac's SSH keys</div></div>
                <div class="ctl col">
                    <Switch bind:checked={d.agent}>Forward</Switch>
                    {#if d.agent && m.share}<div class="ui-hint bad">Anyone with root on {mname} could use your keys while it runs.</div>{/if}
                </div>
            </div>
        {/if}
        <div class="ui-form-row">
            <div><div class="ui-label">Mac network</div><div class="ui-hint">The Mac and other machines</div></div>
            <div class="ctl col">
                <Switch checked={d.isolated && d.isolate_network} disabled={!d.isolated} on:change={(e) => d.isolate_network = e.target.checked}>Blocked</Switch>
                {#if !d.isolated}<div class="ui-hint">Needs the Mac's files isolated first.</div>
                {:else if d.isolate_network}<div class="ui-hint">The internet still works.</div>{/if}
            </div>
        </div>
    </div>
</section>

<section class="ui-card">
    <div class="ui-card-head"><div><h2 class="ui-card-title">Web address</h2><p class="ui-card-desc">Which port <span class="ui-mono">{mname}.orb.local</span> opens in your browser.</p></div></div>
    <div class="rows">
        <div class="ui-form-row">
            <div><div class="ui-label">Ports</div><div class="ui-hint">Empty = the first web server found</div></div>
            <div class="ctl">
                <label class="port"><span>HTTP</span><input class="ui-input mono" type="number" min="1" max="65535" placeholder="Auto" value={d.http || ''} on:input={e => d.http = +e.target.value || 0} /></label>
                <label class="port"><span>HTTPS</span><input class="ui-input mono" type="number" min="1" max="65535" placeholder="Auto" value={d.https || ''} on:input={e => d.https = +e.target.value || 0} /></label>
            </div>
        </div>
    </div>
</section>
{/if}

<section class="ui-card">
    <div class="ui-card-head"><div><h2 class="ui-card-title">System</h2><p class="ui-card-desc">Inside {mname}. Applied right away.</p></div></div>
    <div class="rows">
        {#if !running}
            <div class="ui-empty">Start {mname} to change these.</div>
        {:else if !sys}
            <div class="ui-empty"><Loader2 size={14} class="ui-spin" /></div>
        {:else}
            <div class="ui-form-row">
                <div><div class="ui-label">Timezone</div><div class="ui-hint">For logs and scheduled jobs</div></div>
                <div class="ctl">
                    <select class="ui-select" bind:value={sys.timezone}>
                        {#if sys.timezone && !timezones.includes(sys.timezone)}<option value={sys.timezone}>{sys.timezone}</option>{/if}
                        {#each timezones as tz}<option value={tz}>{tz.replaceAll('_', ' ')}</option>{/each}
                    </select>
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Updates</div><div class="ui-hint">Daily <span class="ui-mono">{sys.pm === 'apk' ? 'apk upgrade' : sys.pm === 'apt-get' ? 'apt upgrade' : `${sys.pm || 'package'} upgrade`}</span></div></div>
                <div class="ctl"><Switch bind:checked={sys.autoupdate}>Install updates automatically</Switch></div>
            </div>
        {/if}
    </div>
</section>

<section class="ui-card danger">
    <div class="ui-card-head"><div><h2 class="ui-card-title">Delete machine</h2>
        <p class="ui-card-desc">Deletes {mname} and its disk{m.tailscale?.state === 'running' ? ', after logging it out of Tailscale' : ''}. This can't be undone.{isDash ? ' The dashboard reads its container figures from it.' : ''}</p></div></div>
    <div class="ui-card-body danger-body">
        <div class="ui-field">
            <label for="confirm-del">Type <b class="ui-mono">{mname}</b> to confirm</label>
            <input id="confirm-del" class="ui-input mono" autocomplete="off" bind:value={confirmName} />
        </div>
        <button class="ui-btn danger" disabled={confirmName !== mname || !!b} on:click={del}>{#if b === 'delete'}<Loader2 size={14} class="ui-spin" />{/if} Delete machine</button>
    </div>
</section>

{#if dirty || needsRestart || error}
    <div class="savebar">
        {#if dirty || error}
            <span class={error ? 'err' : ''}>{error || 'Unsaved changes'}</span>
            <span class="ui-btns">
                <button class="ui-btn sm" on:click={reset}>Reset</button>
                <button class="ui-btn sm primary" disabled={saving} on:click={save}>{#if saving}<Loader2 size={13} class="ui-spin" />{/if}Save</button>
            </span>
        {:else}
            <span>Saved. Restart {mname} to apply.</span>
            <span class="ui-btns">
                <button class="ui-btn sm" on:click={() => needsRestart = false}>Later</button>
                <button class="ui-btn sm primary" disabled={!!b} on:click={restart}>{#if b === 'restart'}<Loader2 size={13} class="ui-spin" />{:else}<RotateCw size={13} />{/if} Restart now</button>
            </span>
        {/if}
    </div>
{/if}

<style>
    .rows { border-top: 1px solid var(--border); }
    .ctl { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .ctl.col { flex-direction: column; align-items: flex-start; gap: 8px; }
    .ctl .ui-input { width: 240px; max-width: 100%; }
    .bad { color: var(--red); }
    /* same widths in every resource row, whatever the unit */
    .res .ui-seg button { width: 84px; text-align: center; padding: 0; }
    .wide { justify-self: stretch; width: 100%; }
    .mounts { display: grid; gap: 0; width: 100%; max-width: 640px; border: 1px solid var(--border); border-radius: 8px; }
    .mt { display: flex; align-items: center; gap: 8px; padding: 6px 6px 6px 12px; font-size: 12.5px; color: var(--text-secondary); border-top: 1px solid var(--border); }
    .mt:first-child { border-top: none; }
    .mt .ui-mono { color: var(--text-primary); }
    .mt .src { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
    .mt .x { margin-left: auto; width: 26px; height: 26px; border-radius: 5px; display: grid; place-items: center; color: var(--text-secondary); cursor: pointer; flex-shrink: 0; }
    .mt .x:hover { background: var(--highlight-10); color: var(--red); }
    .addm { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--text-secondary); width: 100%; max-width: 640px; }
    .addm .ui-input { flex: 1 1 220px; width: auto; }
    .addm .dst { flex: 0 1 160px; }
    .port { display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-secondary); }
    .ctl .port .ui-input { width: 96px; }
    .ui-select { min-width: 240px; }
    .danger-body { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; border-top: 1px solid var(--border); }
    .danger-body .ui-field { flex: 0 1 280px; }
    .savebar { position: sticky; bottom: 12px; z-index: 5; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px 10px 18px; border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); box-shadow: 0 8px 24px rgba(0,0,0,.25); font-size: 13px; color: var(--text-secondary); }
    .savebar .err { color: var(--red); }
</style>
