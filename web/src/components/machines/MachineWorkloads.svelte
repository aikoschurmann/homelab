<script>
    import { vmUrl } from '../../lib/vmref.js';
    import { onMount } from 'svelte';
    import { Loader2, RotateCw, Square, Play } from 'lucide-svelte';
    import { visible } from '../../lib/stores.js';
    import StatusPill from '../ui/StatusPill.svelte';
    import WebLinkButton from '../ui/WebLinkButton.svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';

    // What runs inside one machine: containers, systemd services, listening ports
    export let name;
    export let running = true;
    export let linkContainers = false;   // containers on the dashboard machine have service pages
    export let url = null;               // another source in the same shape (a host's agent report)
    export let act = null;               // (verb, target) => void: a host whose agent takes actions
    export let reload = 0;               // bump to read again now (after an action finishes)

    let w = null, error = '';
    async function load() {
        try {
            const j = await fetch(url || vmUrl(name, '/workloads')).then(r => r.json());
            if (j.status === 'success') { w = j.data; error = ''; } else error = j.message;
        } catch (e) { error = 'Could not reach the backend'; }
    }
    onMount(() => {
        if (running) load();
        const t = setInterval(() => running && visible() && load(), 30000);
        return () => clearInterval(t);
    });

    $: reload && running && load();

    const containerMenu = (c) => c.state === 'running'
        ? [{ label: 'Restart', icon: RotateCw, onClick: () => act('container-restart', c.name) }, { label: 'Stop', icon: Square, danger: true, onClick: () => act('container-stop', c.name) }]
        : [{ label: 'Start', icon: Play, onClick: () => act('container-start', c.name) }];
    const serviceMenu = (u) => [{ label: 'Restart', icon: RotateCw, onClick: () => act('service-restart', u.unit) }, { label: 'Stop', icon: Square, danger: true, onClick: () => act('service-stop', u.unit) }];

    let showBase = false;
    $: apps = (w?.services || []).filter(u => !u.base);
    $: base = (w?.services || []).filter(u => u.base);

    // docker-proxy listeners belong to a container: map host port -> container name
    $: portOwner = (() => {
        const m = {};
        for (const c of w?.docker || []) {
            for (const part of (c.ports || '').split(',')) {
                const x = part.trim().match(/:(\d+)->/);
                if (x) m[x[1]] = c.name;
            }
        }
        return m;
    })();
    // published ports only, one per host port ("0.0.0.0:8080->80/tcp, [::]:8080->80/tcp" -> "8080→80/tcp")
    const published = (ports) => [...new Set((ports || '').split(',').map(p => p.trim()).map(p => {
        const x = p.match(/:(\d+)->(\S+)/);
        return x ? `${x[1]}→${x[2]}` : null;
    }).filter(Boolean))];
    // a container as a service for its web UI button; the dashboard machine's share keys with the Services page
    const asSvc = (c) => ({ key: linkContainers ? 'container:' + c.name : `container:${name}/${c.name}`, kind: 'container', name: c.name, image: c.image, ports: c.ports });
    const ago = (t) => { const s = Math.round(Date.now() / 1000 - t); return s < 60 ? `${s}s ago` : `${Math.round(s / 60)} min ago`; };
</script>

{#if !running}
    <div class="ui-banner warn">The machine is stopped, so nothing runs in it right now.</div>
{:else if !w}
    <div class="ui-card"><div class="ui-empty">{#if error}{error}{:else}<Loader2 size={14} class="ui-spin" /> Looking inside {name}…{/if}</div></div>
{:else}
    <p class="ui-hint" style="margin: 0">Read from inside {name} every 30 seconds · updated {ago(w.at)}</p>

    <section class="ui-card">
        <div class="ui-card-head"><div>
            <h2 class="ui-card-title">Docker containers</h2>
            <p class="ui-card-desc">{w.docker === null ? 'Docker is not installed on this machine.' : `${w.docker.filter(c => c.state === 'running').length} of ${w.docker.length} running`}</p>
        </div></div>
        {#if w.docker?.length}
            <div class="ui-tbl-wrap">
                <table class="ui-tbl">
                    <thead><tr><th>Name</th><th class="c-sm">Image</th><th>State</th><th class="c-md">Status</th><th class="c-sm">Published ports</th><th class="shrink"></th></tr></thead>
                    <tbody>
                        {#each w.docker as c}
                            <tr>
                                <td>{#if linkContainers}<a class="ui-link" href="#infra/svc-{encodeURIComponent(c.name)}">{c.name}</a>{:else}<b class="nm">{c.name}</b>{/if}</td>
                                <td class="ui-mono trunc c-sm" title={c.image}>{c.image}</td>
                                <td><StatusPill state={c.state === 'running' ? 'running' : c.state === 'restarting' ? 'starting' : 'stopped'} label={c.state[0].toUpperCase() + c.state.slice(1)} /></td>
                                <td class="ui-dim c-md">{c.status}</td>
                                <td class="c-sm wrap ports">{#each published(c.ports) as p}<code class="chip">{p}</code>{:else}<span class="ui-dim">—</span>{/each}</td>
                                <td><span class="row-act"><WebLinkButton svc={asSvc(c)} />{#if act}<ActionMenu items={containerMenu(c)} label="Actions for {c.name}" />{/if}</span></td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </div>
        {/if}
    </section>

    <section class="ui-card">
        <div class="ui-card-head">
            <div>
                <h2 class="ui-card-title">System services</h2>
                <p class="ui-card-desc">Running services (systemd or OpenRC). {base.length} standard ones (logging, cron, networking…) are hidden.</p>
            </div>
            {#if base.length}<button class="ui-btn sm" on:click={() => showBase = !showBase}>{showBase ? 'Hide' : 'Show'} standard</button>{/if}
        </div>
        <div class="ui-tbl-wrap">
            <table class="ui-tbl">
                <thead><tr><th>Unit</th><th>Description</th>{#if act}<th class="shrink"></th>{/if}</tr></thead>
                <tbody>
                    {#each showBase ? [...apps, ...base] : apps as u}
                        <tr class:base={u.base}><td class="ui-mono">{u.unit}</td><td class="wrap">{u.description || '—'}</td>{#if act}<td>{#if u.unit !== 'arrakis-agent'}<ActionMenu items={serviceMenu(u)} label="Actions for {u.unit}" />{/if}</td>{/if}</tr>
                    {/each}
                </tbody>
            </table>
            {#if !apps.length && !showBase}<div class="ui-empty">Only the standard system units are running.</div>{/if}
        </div>
    </section>

    <section class="ui-card">
        <div class="ui-card-head"><div>
            <h2 class="ui-card-title">Listening ports</h2>
            <p class="ui-card-desc">What accepts connections, and from where. Docker's port forwarders are shown as their container.</p>
        </div></div>
        <div class="ui-tbl-wrap">
            <table class="ui-tbl">
                <thead><tr><th>Port</th><th>Process</th><th>Reachable from</th><th class="c-md">Bound to</th></tr></thead>
                <tbody>
                    {#each w.listening as l}
                        {@const owner = l.process === 'docker-proxy' ? portOwner[l.port] : null}
                        <tr>
                            <td class="ui-mono">{l.port}<span class="ui-dim">/{l.proto}</span></td>
                            <td>{#if owner}{#if linkContainers}<a class="ui-link" href="#infra/svc-{encodeURIComponent(owner)}">{owner}</a>{:else}{owner}{/if} <span class="ui-dim">container</span>{:else}<span class="ui-mono">{l.process}</span>{/if}</td>
                            <td>{#if l.local_only}<span class="ui-dim">This machine only</span>{:else}Network{/if}</td>
                            <td class="ui-mono ui-dim c-md wrap">{l.addresses.join(', ')}</td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
    </section>
{/if}

<style>
    .nm { font-weight: 600; }
    .ports { line-height: 2; }
    .chip { white-space: nowrap; font-family: 'JetBrains Mono', monospace; font-size: 12px; padding: 2px 6px; border-radius: 4px; background: var(--highlight-10); margin-right: 4px; }
    .wrap { white-space: normal; }
    tr.base td { color: var(--text-secondary); }
    .row-act { display: inline-flex; align-items: center; gap: 4px; }
</style>
