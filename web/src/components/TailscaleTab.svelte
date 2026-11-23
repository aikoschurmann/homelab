<script>
    import { SN } from '../lib/server.js';
    import { onMount } from 'svelte';
    import { ExternalLink } from 'lucide-svelte';
    import Tabs from './ui/Tabs.svelte';
    import { tailnet, fetchTailnet, deviceId } from '../lib/tailscale.js';
    import { fetchMachines, visible } from '../lib/stores.js';
    import { hosts, fetchHosts } from '../lib/hosts.js';
    import DeviceList from './tailscale/DeviceList.svelte';
    import DeviceDetail from './tailscale/DeviceDetail.svelte';
    import PingPage from './tailscale/PingPage.svelte';
    import PeoplePage from './tailscale/PeoplePage.svelte';
    import ServerPage from './tailscale/ServerPage.svelte';
    import TailscaleSummary from './tailscale/TailscaleSummary.svelte';

    // Routes: #tailscale (all devices), #tailscale/f-<filter>, #tailscale/ping|people|server,
    // #tailscale/<name or IP>[/ping]
    export let section = null;
    export let sub = null;
    export let onNavigate = () => {};

    $: net = $tailnet;
    $: filter = section?.startsWith('f-') ? section.slice(2) : null;
    const PAGES = ['ping', 'people', 'server'];
    $: pageOf = PAGES.includes(section) ? section : null;
    $: device = section && !filter && !pageOf && net?.devices.find(d => deviceId(d) === section);

    // one header and tab bar over Devices, Ping, People and This server; a device's own page has neither
    const TABS = [{ id: 'devices', label: 'Devices' }, { id: 'ping', label: 'Ping' }, { id: 'people', label: 'People' }, { id: 'server', label: 'This server' }];
    $: tab = pageOf || 'devices';
    const go = (f) => onNavigate('Tailscale', f === 'all' ? null : 'f-' + f);
    const openDevice = (id, s = null) => onNavigate('Tailscale', id, s);

    let now = Date.now();
    onMount(() => {
        fetchTailnet();
        fetchMachines();
        if (!$hosts) fetchHosts();
        const tick = setInterval(() => now = Date.now(), 1000);
        const poll = setInterval(() => visible() && fetchTailnet(), 10000);
        return () => { clearInterval(tick); clearInterval(poll); };
    });
</script>

{#if !net}
    <div class="ui-page"><div class="ui-dim">Loading the tailnet…</div></div>
{:else if section && !device && !filter && !pageOf}
    <div class="ui-page"><div class="ui-head"><div><h1>{section}</h1><p>No device by this name on the tailnet. <button class="ui-link" on:click={() => onNavigate('Tailscale', null)}>All devices</button></p></div></div></div>
{:else if device}
    {#key device.id}<DeviceDetail d={device} me={net.self.user} {now} autoPing={sub === 'ping'} />{/key}
{:else}
    <div class="ui-page">
        <div class="ui-head">
            <div>
                <h1>Tailscale</h1>
                <p>Every device on <span class="ui-mono">{net.magic_dns}</span>, as {SN} sees it. Tailscale {net.version}.</p>
            </div>
            <div class="ui-head-actions">
                <a class="ui-btn" href="https://login.tailscale.com/admin/machines" target="_blank" rel="noopener">Admin console <ExternalLink size={13} /></a>
            </div>
        </div>
        {#if net.health?.length}<div class="ui-banner warn">{net.health.join(' · ')}</div>{/if}

        <TailscaleSummary {net} {now} />

        <Tabs tabs={TABS} active={tab} onSelect={(t) => onNavigate('Tailscale', t === 'devices' ? null : t)} />

        {#if tab === 'ping'}<PingPage {net} {now} />
        {:else if tab === 'people'}<PeoplePage {net} {now} open={openDevice} />
        {:else if tab === 'server'}<ServerPage {net} {now} />
        {:else}<DeviceList {net} {now} filter={filter || 'all'} setFilter={go} open={openDevice} />{/if}
    </div>
{/if}

<style>
    /* each tab's content, spaced like the page around it */
    :global(.ts-sub) { display: flex; flex-direction: column; gap: 20px; min-width: 0; }
</style>
