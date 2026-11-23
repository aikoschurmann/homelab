<script>
    // One person on a shared machine: what they may do there. Same card + form-row layout
    // as the machine's Settings tab; one save bar for the whole page.
    import { ArrowLeft, Copy, Check, Trash2, Loader2, KeyRound } from 'lucide-svelte';
    import Stepper from '../Stepper.svelte';
    import Switch from '../ui/Switch.svelte';
    import { api } from '../../lib/machines.js';
    import { refreshMachines } from '../../lib/stores.js';
    import { vmUrl } from '../../lib/vmref.js';
    import { copyText } from '../../lib/clipboard.js';
    import { presetOf, applyPreset } from '../../lib/perms.js';
    import { ago } from '../../lib/tailscale.js';

    export let data;
    export let m;
    export let ref;           // machine ref
    export let user;          // login name
    export let back = () => {};

    $: share = m.share;
    $: k = share?.keys?.find(x => x.user === user && x.perms);
    $: schema = data.sharing?.permissions;
    $: running = m.state === 'running';
    $: host = share?.hostname || m.name;
    $: cores = m.cpu || data.pool?.cpu || 0;

    // draft of the permissions; reset whenever the saved ones change
    let p = null, savedJson = '';
    $: if (k && JSON.stringify(k.perms) !== savedJson) { savedJson = JSON.stringify(k.perms); p = structuredClone(k.perms); }
    $: dirty = p && JSON.stringify(p) !== savedJson;
    $: preset = p && presetOf(p, schema);
    $: sftp = p?.access === 'sftp';
    function set(patch) { p = { ...p, ...patch }; }
    $: if (p && p.root === 'some' && !p.sudo.length && schema?.sudo?.length) p = { ...p, sudo: [schema.sudo[0].id] };
    const toggleSudo = (id) => set({ sudo: p.sudo.includes(id) ? p.sudo.filter(x => x !== id) : [...p.sudo, id] });
    const today = new Date().toISOString().slice(0, 10);
    const inWeek = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);

    let saving = false, error = '';
    async function save() {
        saving = true; error = '';
        const r = await api(vmUrl(ref, '/share/keys/perms'), { method: 'PUT', body: JSON.stringify({ fp: k.fp, perms: p }) });
        saving = false;
        if (r.status !== 'success') { error = r.message || 'Could not save'; return; }
        window.showToast?.(`Saved. ${user}'s new permissions are in effect`);
        refreshMachines(ref);
    }

    // save these permissions as a preset of your own
    let savingPreset = false, spName = '', spDesc = '', spDays = 0;
    function startPreset() {
        savingPreset = true; spName = ''; spDesc = '';
        spDays = p.expires ? Math.max(0, Math.round((new Date(p.expires) - new Date(k.added * 1000)) / 864e5)) : 0;
    }
    async function savePreset() {
        const r = await api('/api/vms/sharing/presets', { method: 'POST', body: JSON.stringify({ label: spName, desc: spDesc, perms: p, expires_days: +spDays || 0 }) });
        if (r.status === 'success') { window.showToast?.(`Preset ${spName} saved`); savingPreset = false; refreshMachines(ref); }
    }

    let confirmRemove = false, removing = false;
    async function remove() {
        removing = true;
        const r = await api(vmUrl(ref, '/share/keys'), { method: 'DELETE', body: JSON.stringify({ fp: k.fp }) });
        removing = false;
        if (r.status === 'success') { window.showToast?.(`${user} removed`); await refreshMachines(ref); back(); }
    }

    let copied = false;
    async function copyLogin() { try { await copyText(`ssh ${user}@${host}`); copied = true; setTimeout(() => copied = false, 1200); } catch (e) {} }
</script>

<button class="back" on:click={back}><ArrowLeft size={14} /> All people</button>

{#if !k || !p}
    <div class="ui-card ui-empty">{share ? `No one called ${user} on ${m.name}.` : `${m.name} isn't shared.`}</div>
{:else}
    <section class="ui-card">
        <div class="ui-card-head phead">
            <div class="who">
                <span class="ic"><KeyRound size={16} /></span>
                <div>
                    <h2 class="ui-card-title">{k.label || k.comment || user}</h2>
                    <p class="ui-card-desc"><span class="ui-mono">{user}@{host}</span> · added {k.added ? ago(k.added * 1000) : '—'} · {k.last_login ? `last login ${ago(k.last_login * 1000)}` : share.logins_known ? 'never logged in' : 'last login unknown'}</p>
                </div>
            </div>
            <div class="ui-btns">
                {#if confirmRemove}
                    <button class="ui-btn sm" on:click={() => confirmRemove = false}>Cancel</button>
                    <button class="ui-btn sm danger" disabled={removing} on:click={remove}>{#if removing}<Loader2 size={13} class="ui-spin" />{/if}Remove {user}</button>
                {:else}
                    <button class="ui-btn sm" on:click={copyLogin}>{#if copied}<Check size={13} />{:else}<Copy size={13} />{/if} Login command</button>
                    <button class="ui-btn sm danger-outline" disabled={!running} title={running ? 'Remove this person and their files' : `Start ${m.name} to remove`} on:click={() => confirmRemove = true}><Trash2 size={13} /></button>
                {/if}
            </div>
        </div>
        <div class="rows">
            <div class="ui-form-row">
                <div><div class="ui-label">Preset</div><div class="ui-hint">A starting point; change anything below</div></div>
                <div class="ctl col">
                    <div class="ui-seg">{#each schema.presets as pr}<button class:on={preset?.id === pr.id} on:click={() => p = applyPreset(pr)}>{pr.label}</button>{/each}</div>
                    <div class="ui-hint">{preset ? preset.desc : 'Custom: doesn\'t match a preset.'}</div>
                    {#if !preset && !dirty}
                        {#if savingPreset}
                            <form class="sp" on:submit|preventDefault={savePreset}>
                                <input class="ui-input" placeholder="Name, e.g. Student" maxlength="30" bind:value={spName} />
                                <input class="ui-input" placeholder="What it's for (optional)" maxlength="120" bind:value={spDesc} />
                                <label class="spx">Expires after <input class="ui-input mono" type="number" min="0" max="3650" bind:value={spDays} /> days <span class="ui-dim">(0 = never)</span></label>
                                <span class="ui-btns"><button type="button" class="ui-btn sm" on:click={() => savingPreset = false}>Cancel</button><button class="ui-btn sm primary" disabled={!spName.trim()}>Save preset</button></span>
                            </form>
                        {:else}<button class="ui-btn sm" on:click={startPreset}>Save as preset…</button>{/if}
                    {/if}
                </div>
            </div>
        </div>
    </section>

    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Access</h2><p class="ui-card-desc">How {user} gets in and what they can run.</p></div></div>
        <div class="rows">
            <div class="ui-form-row">
                <div><div class="ui-label">Login</div></div>
                <div class="ctl col">
                    <div class="ui-seg"><button class:on={!sftp} on:click={() => set({ access: 'shell' })}>Shell</button><button class:on={sftp} on:click={() => set({ access: 'sftp', root: 'none', sudo: [], docker: false, forward: false })}>Files only</button></div>
                    {#if sftp}<div class="ui-hint">SFTP into their own folder. No shell, so nothing below runs.</div>{/if}
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Root</div><div class="ui-hint">Passwordless sudo</div></div>
                <div class="ctl col">
                    <div class="ui-seg">{#each [['none', 'None'], ['some', 'Some commands'], ['full', 'Full']] as [id, l]}<button class:on={p.root === id} disabled={sftp} on:click={() => set({ root: id, sudo: id === 'some' ? p.sudo : [] })}>{l}</button>{/each}</div>
                    {#if p.root === 'some'}
                        <div class="checks">{#each schema.sudo as g}<label class="chk"><input type="checkbox" checked={p.sudo.includes(g.id)} on:change={() => toggleSudo(g.id)} />{g.label} <span class="ui-dim">{g.desc}</span></label>{/each}</div>
                    {/if}
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Docker</div><div class="ui-hint">{share.docker === false ? 'Not installed here' : 'Docker group'}</div></div>
                <div class="ctl"><Switch bind:checked={p.docker} disabled={sftp}>Use Docker</Switch></div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Processes</div></div>
                <div class="ctl"><Switch bind:checked={p.procs}>See other people's processes</Switch></div>
            </div>
        </div>
        {#if !sftp && (p.root !== 'none' || p.docker)}
            <div class="ui-card-foot"><span class="warn">{p.root === 'full' || p.docker ? `${p.root === 'full' ? 'Full root' : 'Docker'} lets ${user} lift every limit on this page and read everyone's files on ${m.name}.` : 'Installing packages or running services as root can be turned into full root by someone determined.'}</span></div>
        {/if}
    </section>

    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Network</h2><p class="ui-card-desc">Where {user}'s programs may connect to.</p></div></div>
        <div class="rows">
            <div class="ui-form-row">
                <div><div class="ui-label">Reach</div></div>
                <div class="ctl col">
                    <div class="ui-seg">{#each [['internet', 'Internet only'], ['full', 'Everything'], ['none', 'Nothing']] as [id, l]}<button class:on={p.net === id} on:click={() => set({ net: id })}>{l}</button>{/each}</div>
                    <div class="ui-hint">{{ internet: 'Your LAN, the tailnet, this Mac and other machines are blocked.', full: 'Including your LAN, the tailnet and other machines.', none: 'Only this machine itself (localhost).' }[p.net]}</div>
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Port forwarding</div><div class="ui-hint">ssh -L / -R</div></div>
                <div class="ctl"><Switch bind:checked={p.forward} disabled={sftp}>Allow</Switch></div>
            </div>
        </div>
    </section>

    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Limits</h2><p class="ui-card-desc">For everything {user} runs, together. Disk space is limited for the whole machine in Settings.</p></div></div>
        <div class="rows">
            <div class="ui-form-row">
                <div><div class="ui-label">CPU</div><div class="ui-hint">{cores ? `Machine: ${cores} ${cores === 1 ? 'core' : 'cores'}` : ''}</div></div>
                <div class="ctl">
                    <div class="ui-seg"><button class:on={!p.cpu} on:click={() => set({ cpu: 0 })}>No cap</button><button class:on={!!p.cpu} on:click={() => set({ cpu: p.cpu || Math.min(1, cores || 1) })}>Cap</button></div>
                    {#if p.cpu}<Stepper min={0.25} max={cores || 64} step={0.25} unit={p.cpu === 1 ? 'core' : 'cores'} bind:value={p.cpu} />{/if}
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Memory</div></div>
                <div class="ctl">
                    <div class="ui-seg"><button class:on={!p.mem_mib} on:click={() => set({ mem_mib: 0 })}>No cap</button><button class:on={!!p.mem_mib} on:click={() => set({ mem_mib: p.mem_mib || 512 })}>Cap</button></div>
                    {#if p.mem_mib}<Stepper min={128} max={65536} step={128} unit="MB" bind:value={p.mem_mib} />{/if}
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Processes</div><div class="ui-hint">Stops fork bombs</div></div>
                <div class="ctl">
                    <div class="ui-seg"><button class:on={!p.pids} on:click={() => set({ pids: 0 })}>No cap</button><button class:on={!!p.pids} on:click={() => set({ pids: p.pids || 256 })}>Cap</button></div>
                    {#if p.pids}<Stepper min={32} max={8192} step={32} unit="max" bind:value={p.pids} />{/if}
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Expires</div></div>
                <div class="ctl col">
                    <div class="row-in">
                        <div class="ui-seg"><button class:on={!p.expires} on:click={() => set({ expires: '' })}>Never</button><button class:on={!!p.expires} on:click={() => set({ expires: p.expires || inWeek })}>On a date</button></div>
                        {#if p.expires}<input class="ui-input date" type="date" min={today} value={p.expires} on:change={e => set({ expires: e.target.value })} />{/if}
                    </div>
                    {#if p.expires}<div class="ui-hint">No logins after this day; open sessions end within the hour.</div>{/if}
                </div>
            </div>
        </div>
    </section>

    {#if dirty || error}
        <div class="ui-savebar">
            <span class:err={error}>{error || (running ? 'Unsaved changes' : `Start ${m.name} to save`)}</span>
            <span class="ui-btns">
                <button class="ui-btn sm" on:click={() => { p = structuredClone(k.perms); error = ''; }}>Reset</button>
                <button class="ui-btn sm primary" disabled={!running || saving} on:click={save}>{#if saving}<Loader2 size={13} class="ui-spin" />{/if}Save</button>
            </span>
        </div>
    {/if}
{/if}

<style>
    .back { display: inline-flex; align-items: center; gap: 6px; align-self: flex-start; font-size: 13px; color: var(--text-secondary); cursor: pointer; padding: 2px 0; }
    .back:hover { color: var(--text-primary); }
    .who { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .who .ic { width: 36px; height: 36px; border-radius: 8px; display: grid; place-items: center; background: var(--highlight-10); color: var(--text-secondary); flex-shrink: 0; }
    .rows { border-top: 1px solid var(--border); }
    .ctl { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .ctl.col { flex-direction: column; align-items: flex-start; gap: 8px; }
    .row-in { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .date { width: 160px; }
    .checks { display: grid; gap: 7px; }
    .chk { display: flex; align-items: baseline; gap: 8px; font-size: 13px; cursor: pointer; }
    .warn { color: var(--red); }
    .sp { display: grid; gap: 8px; width: 100%; max-width: 440px; }
    .spx { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-secondary); }
    .spx input { width: 76px; }
    @media (max-width: 640px) {
        .phead { flex-direction: column; align-items: stretch; gap: 12px; }
        .who .ui-mono { overflow-wrap: anywhere; }
    }
</style>
