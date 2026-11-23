<script>
    import { onMount } from 'svelte';
    import { cloudflare, cloudflareError, fetchCloudflare, tunnelKey } from '../lib/cloudflare.js';
    import { visible } from '../lib/stores.js';
    import CloudflareHome from './cloudflare/CloudflareHome.svelte';
    import TunnelDetail from './cloudflare/TunnelDetail.svelte';

    // Routes: #cloudflare (tunnels), #cloudflare/f-<filter>, #cloudflare/dns (DNS records),
    // #cloudflare/<tunnel name, or id when deleted>
    export let section = null;
    export let onNavigate = () => {};

    $: cf = $cloudflare;
    $: filter = section?.startsWith('f-') ? section.slice(2) : null;
    $: listing = !section || section === 'dns' || filter;
    $: tunnel = !listing && cf?.tunnels?.find(t => tunnelKey(t) === section);

    let now = Date.now();
    onMount(() => {
        fetchCloudflare();
        const tick = setInterval(() => now = Date.now(), 1000);
        const poll = setInterval(() => visible() && fetchCloudflare(), 30000);
        return () => { clearInterval(tick); clearInterval(poll); };
    });
</script>

{#if !cf}
    <div class="ui-page"><div class="ui-dim">{$cloudflareError || 'Loading Cloudflare…'}</div></div>
{:else if !cf.logged_in}
    <div class="ui-page">
        <div class="ui-head"><div><h1>Cloudflare</h1><p>No API token saved. Add one in <a class="ui-link" href="#settings/integrations">Settings → Integrations</a> to see tunnels and DNS records here.</p></div></div>
    </div>
{:else if !listing && !tunnel}
    <div class="ui-page"><div class="ui-head"><div><h1>{section}</h1><p>No tunnel by this name. <button class="ui-link" on:click={() => onNavigate('Cloudflare', null)}>All tunnels</button></p></div></div></div>
{:else if tunnel}
    {#key tunnel.id}<TunnelDetail t={tunnel} zone={cf.zone} records={cf.records} {now} />{/key}
{:else}
    <CloudflareHome {cf} {now} view={section === 'dns' ? 'dns' : 'tunnels'} filter={filter || 'all'} {onNavigate} />
{/if}
