<script>
    import { SN } from '../../lib/server.js';
    import { onMount } from 'svelte';
    import { Loader2, Check, Cpu, Zap, Layers, SlidersHorizontal } from 'lucide-svelte';
    import { gbFromMib, fetchMachines, fetchHostVms } from '../../lib/stores.js';
    import { vmBase } from '../../lib/vmref.js';
    import { api } from '../../lib/machines.js';
    import Stepper from '../Stepper.svelte';

    export let data;
    export let back = () => {};
    export let created = () => {};   // created(name)
    export let onHost = null;        // another host's id: create there; null = on Arrakis
    export let hostName = SN;

    $: host = data.host;
    $: pool = data.pool;
    $: taken = new Set((data.machines || []).map(m => m.name));

    const NAMES = { alma: 'AlmaLinux', alpine: 'Alpine', arch: 'Arch Linux', centos: 'CentOS Stream', debian: 'Debian', devuan: 'Devuan', fedora: 'Fedora', gentoo: 'Gentoo', kali: 'Kali', nixos: 'NixOS', openeuler: 'openEuler', opensuse: 'openSUSE', oracle: 'Oracle Linux', rocky: 'Rocky Linux', ubuntu: 'Ubuntu', void: 'Void' };
    const pretty = (d) => NAMES[d] || d[0].toUpperCase() + d.slice(1);

    let images = null;
    let creating = false;
    let form = { name: '', distro: 'ubuntu', version: '', arch: 'arm64', limits: false, cpu: 2, gb: 2, tailscale: false };
    $: distroDef = images?.distros.find(d => d.distro === form.distro);
    $: if (distroDef && !distroDef.versions.some(v => v.id === form.version)) form.version = distroDef.default || distroDef.versions[0]?.id || '';
    $: versionLabel = distroDef?.versions.find(v => v.id === form.version)?.label || form.version;
    $: nm = form.name.trim();
    $: nameErr = !nm ? '' : !/^[a-z0-9][a-z0-9-]{0,62}$/.test(nm) ? 'Use lowercase letters, digits and dashes, starting with a letter or digit.' : taken.has(nm) ? 'A machine with this name already exists.' : '';
    $: ready = nm && !nameErr && images && form.version;

    onMount(async () => {
        const r = await api(`${vmBase(onHost)}/images`);
        if (r.status === 'success') images = r.data;
        if (data.tailscale_key) form.tailscale = true;
    });

    async function create() {
        creating = true;
        const r = await api(vmBase(onHost), { method: 'POST', body: JSON.stringify({
            name: nm, distro: form.distro, version: form.version, arch: form.arch,
            cpu: form.limits ? form.cpu : 0, memory_mib: form.limits ? Math.round(form.gb * 1024) : 0,
            tailscale: form.tailscale && data.tailscale_key,
        }) });
        creating = false;
        if (r.status === 'success') { window.showToast?.(r.message); await (onHost ? fetchHostVms(onHost) : fetchMachines()); created(nm); }
    }
</script>

<div class="ui-page">
    <div class="ui-head">
        <div>
            <h1>Create a machine</h1>
            <p>A new Linux machine on {hostName}. The image downloads first, so creating can take a few minutes.</p>
        </div>
    </div>

    <div class="layout">
        <div class="form">
            <!-- 1. name -->
            <section class="step">
                <div class="step-head"><span class="n">1</span><div><h2>Name</h2><p>Also its hostname on {hostName}.</p></div></div>
                <div class="step-body">
                    <div class="name-field" class:bad={nameErr}>
                        <input class="name-input" placeholder="dev" autocomplete="off" spellcheck="false" bind:value={form.name} aria-label="Machine name" />
                        <span class="suffix">.orb.local</span>
                    </div>
                    {#if nameErr}<p class="err">{nameErr}</p>{/if}
                </div>
            </section>

            <!-- 2. image -->
            <section class="step">
                <div class="step-head"><span class="n">2</span><div><h2>Image</h2><p>Pick a distribution, then a release.</p></div></div>
                <div class="step-body">
                    {#if !images}
                        <div class="ui-dim loading"><Loader2 size={14} class="ui-spin" /> Loading images…</div>
                    {:else}
                        <div class="distros" role="radiogroup" aria-label="Distribution">
                            {#each images.distros as d}
                                <button class="tile" class:on={form.distro === d.distro} role="radio" aria-checked={form.distro === d.distro} on:click={() => form.distro = d.distro}>
                                    <span class="tile-name">{pretty(d.distro)}</span>
                                    <span class="tile-sub">{d.versions.length > 1 ? `${d.versions.length} releases` : 'rolling'}</span>
                                    {#if form.distro === d.distro}<span class="tick"><Check size={11} strokeWidth={3} /></span>{/if}
                                </button>
                            {/each}
                        </div>
                        {#if distroDef?.versions.length > 1}
                            <div class="sub-label">Release</div>
                            <div class="chips" role="radiogroup" aria-label="Release">
                                {#each distroDef.versions as v}
                                    <button class="chip" class:on={form.version === v.id} role="radio" aria-checked={form.version === v.id} on:click={() => form.version = v.id}>
                                        {v.label}{#if v.id === distroDef.default}<em>default</em>{/if}
                                    </button>
                                {/each}
                            </div>
                        {/if}
                    {/if}
                </div>
            </section>

            <!-- 3. architecture -->
            <section class="step">
                <div class="step-head"><span class="n">3</span><div><h2>Architecture</h2><p>The Mac runs arm64 natively; amd64 goes through Rosetta.</p></div></div>
                <div class="step-body">
                    <div class="options two">
                        {#each images?.arches || ['arm64'] as a}
                            <button class="option" class:on={form.arch === a} on:click={() => form.arch = a}>
                                <span class="radio"></span>
                                <span class="o-icon">{#if a === 'arm64'}<Zap size={16} />{:else}<Cpu size={16} />{/if}</span>
                                <span class="o-text"><b>{a}</b><small>{a === 'arm64' ? 'Native, full speed' : 'x86 software, emulated and slower'}</small></span>
                            </button>
                        {/each}
                    </div>
                </div>
            </section>

            <!-- 4. resources -->
            <section class="step">
                <div class="step-head"><span class="n">4</span><div><h2>Resources</h2><p>Machines share one pool of {pool.cpu} cores and {gbFromMib(pool.memory_mib)} unless they get their own limits.</p></div></div>
                <div class="step-body">
                    <div class="options two">
                        <button class="option" class:on={!form.limits} on:click={() => form.limits = false}>
                            <span class="radio"></span>
                            <span class="o-icon"><Layers size={16} /></span>
                            <span class="o-text"><b>Share the pool</b><small>Uses what it needs, up to the whole pool</small></span>
                        </button>
                        <button class="option" class:on={form.limits} on:click={() => form.limits = true}>
                            <span class="radio"></span>
                            <span class="o-icon"><SlidersHorizontal size={16} /></span>
                            <span class="o-text"><b>Set limits</b><small>Caps this machine inside the pool</small></span>
                        </button>
                    </div>
                    {#if form.limits}
                        <div class="limits">
                            <div class="limit"><span class="sub-label">CPU</span><Stepper bind:value={form.cpu} min={1} max={host.cores} step={1} unit="cores" /></div>
                            <div class="limit"><span class="sub-label">Memory</span><Stepper bind:value={form.gb} min={1} max={host.memory_mib / 1024} step={0.5} unit="GB" /></div>
                        </div>
                    {/if}
                </div>
            </section>

            <!-- 5. network -->
            <section class="step last">
                <div class="step-head"><span class="n">5</span><div><h2>Tailscale</h2><p>Join your tailnet with Tailscale SSH once the machine is up.</p></div></div>
                <div class="step-body">
                    <label class="switch-row" class:disabled={!data.tailscale_key}>
                        <span class="switch" class:on={form.tailscale && data.tailscale_key}><input type="checkbox" bind:checked={form.tailscale} disabled={!data.tailscale_key} /><i></i></span>
                        <span>{#if data.tailscale_key}Join the tailnet after creating{:else}Add an auth key in <a class="ui-link" href="#settings/tailscale">Settings</a> to join automatically{/if}</span>
                    </label>
                </div>
            </section>
        </div>

        <!-- summary -->
        <aside class="summary">
            <div class="ui-card">
                <div class="ui-card-head"><h2 class="ui-card-title">Summary</h2></div>
                <dl class="sum">
                    <dt>Name</dt><dd class="ui-mono">{nm || '—'}</dd>
                    <dt>Image</dt><dd>{pretty(form.distro)} {versionLabel || ''}</dd>
                    <dt>Architecture</dt><dd>{form.arch}{form.arch === 'arm64' ? ' (native)' : ' (Rosetta)'}</dd>
                    <dt>CPU</dt><dd>{form.limits ? `${form.cpu} cores` : `Pool, ${pool.cpu} cores`}</dd>
                    <dt>Memory</dt><dd>{form.limits ? `${form.gb} GB` : `Pool, ${gbFromMib(pool.memory_mib)}`}</dd>
                    <dt>Tailscale</dt><dd>{form.tailscale && data.tailscale_key ? 'Joins' : 'No'}</dd>
                </dl>
                <div class="sum-actions">
                    <button class="ui-btn primary wide" disabled={creating || !ready} on:click={create}>{#if creating}<Loader2 size={14} class="ui-spin" /> Creating…{:else}Create machine{/if}</button>
                    <button class="ui-btn wide" on:click={back}>Cancel</button>
                </div>
            </div>
        </aside>
    </div>
</div>

<style>
    .layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 24px; align-items: start; }
    .form { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card, 8px); }

    .step { padding: 22px 24px; border-bottom: 1px solid var(--border); }
    .step.last { border-bottom: none; }
    .step-head { display: flex; gap: 14px; align-items: flex-start; }
    .n { width: 24px; height: 24px; border-radius: 50%; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; background: var(--accent-soft); color: var(--accent); }
    h2 { margin: 1px 0 0; font-size: 15px; font-weight: 600; color: var(--text-primary); }
    .step-head p { margin: 3px 0 0; font-size: 13px; color: var(--text-secondary); }
    .step-body { margin: 16px 0 0 38px; }

    .name-field { display: flex; align-items: center; max-width: 420px; height: 38px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); overflow: hidden; }
    .name-field:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
    .name-field.bad { border-color: var(--red); }
    .name-input { flex: 1; min-width: 0; height: 100%; border: none; outline: none; background: transparent; padding: 0 12px; font-family: 'JetBrains Mono', monospace; font-size: 14px; color: var(--text-primary); }
    .suffix { padding: 0 12px; height: 100%; display: flex; align-items: center; font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--text-secondary); background: var(--highlight-5); border-left: 1px solid var(--border); }
    .err { margin: 6px 0 0; font-size: 12.5px; color: var(--red); }
    .loading { display: flex; align-items: center; gap: 8px; font-size: 13px; }

    .distros { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
    .tile { position: relative; display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-card, 8px); background: var(--surface); cursor: pointer; text-align: left; transition: border-color .12s, background .12s; }
    .tile:hover { border-color: var(--border-strong); background: var(--highlight-3); }
    .tile.on { border-color: var(--accent); background: var(--accent-soft); box-shadow: inset 0 0 0 1px var(--accent); }
    .tile-name { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
    .tile-sub { font-size: 12px; color: var(--text-secondary); }
    .tick { position: absolute; top: 8px; right: 8px; width: 16px; height: 16px; border-radius: 50%; background: var(--accent-fill); color: var(--accent-fg); display: flex; align-items: center; justify-content: center; }

    .sub-label { display: block; font-size: 12.5px; font-weight: 600; color: var(--text-secondary); margin: 16px 0 8px; }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 12px; border: 1px solid var(--border); border-radius: 15px; font-size: 13px; color: var(--text-primary); cursor: pointer; background: var(--surface); }
    .chip:hover { border-color: var(--border-strong); }
    .chip.on { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); font-weight: 600; }
    .chip em { font-style: normal; font-size: 11px; font-weight: 500; color: var(--text-secondary); }

    .options.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 640px; }
    .option { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-card, 8px); background: var(--surface); cursor: pointer; text-align: left; transition: border-color .12s, background .12s; }
    .option:hover { border-color: var(--border-strong); }
    .option.on { border-color: var(--accent); background: var(--accent-soft); box-shadow: inset 0 0 0 1px var(--accent); }
    .radio { width: 16px; height: 16px; border-radius: 50%; border: 1.5px solid var(--border-strong); flex-shrink: 0; box-sizing: border-box; }
    .option.on .radio { border: 5px solid var(--accent-fill); }
    .o-icon { width: 32px; height: 32px; border-radius: 7px; background: var(--highlight-10); color: var(--text-secondary); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .option.on .o-icon { background: var(--surface); color: var(--accent); }
    .o-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .o-text b { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
    .o-text small { font-size: 12px; color: var(--text-secondary); }
    .limits { display: flex; gap: 28px; flex-wrap: wrap; margin-top: 4px; }
    .limit .sub-label { margin-top: 14px; }

    .switch-row { display: inline-flex; align-items: center; gap: 12px; font-size: 13.5px; color: var(--text-primary); cursor: pointer; }
    .switch-row.disabled { cursor: default; color: var(--text-secondary); }
    .switch { position: relative; width: 36px; height: 20px; flex-shrink: 0; }
    .switch input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: inherit; }
    .switch i { position: absolute; inset: 0; border-radius: 10px; background: var(--highlight-30); transition: background .15s; pointer-events: none; }
    .switch i::after { content: ''; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.25); transition: transform .15s; }
    .switch.on i { background: var(--accent-fill); }
    .switch.on i::after { transform: translateX(16px); }

    .summary { position: sticky; top: 16px; }
    .sum { margin: 0; padding: 4px 20px 8px; border-top: 1px solid var(--border); display: grid; grid-template-columns: auto 1fr; }
    .sum dt, .sum dd { margin: 0; padding: 9px 0; font-size: 13px; border-bottom: 1px solid var(--border); }
    .sum dt { color: var(--text-secondary); padding-right: 12px; }
    .sum dd { color: var(--text-primary); text-align: right; overflow-wrap: anywhere; }
    .sum dt:nth-last-of-type(1), .sum dd:last-of-type { border-bottom: none; }
    .sum-actions { display: flex; flex-direction: column; gap: 8px; padding: 12px 20px 18px; }
    .wide { width: 100%; height: 36px; }

    @media (max-width: 1100px) {
        .layout { grid-template-columns: 1fr; }
        .summary { position: static; }
    }
    @media (max-width: 640px) {
        .step { padding: 18px 14px; }
        .step-body { margin-left: 0; }
        .options.two { grid-template-columns: 1fr; }
        .distros { grid-template-columns: repeat(2, 1fr); }
    }
    /* phone: cards inset 14px, so this lines up with the card's header */
    @media (max-width: 768px) { .sum-actions { padding-left: 14px; padding-right: 14px; } }
</style>
