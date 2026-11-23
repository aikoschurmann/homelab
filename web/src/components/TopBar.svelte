<script>
    import { Menu, Search, ChevronRight } from 'lucide-svelte';
    import UplinkStatus from './UplinkStatus.svelte';
    import { groupOf, childrenOf, tabLabel } from '../lib/nav.js';
    import { machines, crumbLabels } from '../lib/stores.js';
    import { services } from '../lib/services.js';
    import { hosts } from '../lib/hosts.js';
    import { pools } from '../lib/compute.js';
    import { pathOf, nodeOf } from '../lib/infra.js';
    import { tsCounts, fetchTailnet } from '../lib/tailscale.js';
    import { cfCounts } from '../lib/cloudflare.js';
    import { databases } from '../lib/databases.js';
    import { onMount } from 'svelte';
    // someone the owner gave view-only access sees that here (the server refuses their changes)
    let me = null;
    onMount(async () => { try { const j = await fetch('/api/access/me').then(r => r.json()); if (j.status === 'success') me = j.data; } catch (e) {} });
    import { backups } from '../lib/backups.js';
    export let activeTab;
    export let activeSection = null;
    export let activeSub = null;
    export let isMobileMenuOpen = false;
    export let onNavigate = () => {};

    $: group = groupOf(activeTab);
    // a section that isn't in the menu (e.g. "new") still gets a crumb
    $: found = activeSection && (childrenOf(activeTab, $machines?.machines, $services, $tsCounts, $hosts, activeSection, $cfCounts, $databases, $backups).find(c => c.id === activeSection)
        || { id: activeSection, label: activeSection === 'new' ? 'Create' : $crumbLabels[activeSection] || activeSection });
    // pages can register a friendlier label for their own ids (e.g. an endpoint's method + path)
    $: section = found && ($crumbLabels[activeSection] ? { ...found, label: $crumbLabels[activeSection] } : found);
    const cap = (s) => s[0].toUpperCase() + s.slice(1);
    // the OrbStack VM and Apps tabs of Arrakis read as their tree nodes
    $: node = activeTab === 'Infra' ? nodeOf(activeSection, activeSub) : null;
    // the list itself (#infra) is the Hosts root of the tree
    $: infraPath = activeTab === 'Infra' ? pathOf(node || 'hosts', $machines?.machines, $hosts, $services, $pools) : [];
    $: crumbSub = node !== activeSection ? null : activeSub;
    const SUB = { new: 'Create machine', vm: 'OrbStack VM', apps: 'Apps' };

    const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform);
    // The palette listens for ⌘K / Ctrl+K on window
    const openPalette = () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, ctrlKey: !isMac, bubbles: true }));

</script>

<header class="topbar">
    <button class="icon-btn menu" on:click={() => isMobileMenuOpen = true} aria-label="Open menu"><Menu size={18} /></button>

    <nav class="crumbs" aria-label="Breadcrumb">
        {#if activeTab === 'Infra'}
            {#if infraPath.length}
                <button class="crumb link" on:click={() => onNavigate('Infra', null)}>Infrastructure</button>
                {#each infraPath as n, i}
                    <ChevronRight size={13} class="sep" />
                    {#if i < infraPath.length - 1 || crumbSub}<button class="crumb link" on:click={() => onNavigate('Infra', n.id)}>{n.label}</button>{:else}<span class="crumb cur">{n.label}</span>{/if}
                {/each}
                {#if crumbSub}<ChevronRight size={13} class="sep" /><span class="crumb cur">{crumbSub === 'new' && activeSection === 'pools' ? 'New pool' : crumbSub.startsWith('job-') ? 'Run' : crumbSub.startsWith('file-') ? decodeURIComponent(crumbSub.slice(5)) : crumbSub.startsWith('person-') ? crumbSub.slice(7) : SUB[crumbSub] || cap(crumbSub)}</span>{/if}
            {:else}<span class="crumb cur">Infrastructure</span>{/if}
        {:else}
        {#if group}<span class="crumb dim">{group}</span><ChevronRight size={13} class="sep" />{/if}
        {#if section}
            <button class="crumb link" on:click={() => onNavigate(activeTab, null)}>{tabLabel(activeTab)}</button>
            <ChevronRight size={13} class="sep" />
            {#if activeSub}
                <button class="crumb link" on:click={() => onNavigate(activeTab, activeSection)}>{section.label}</button>
                <ChevronRight size={13} class="sep" />
                <span class="crumb cur">{cap(activeSub)}</span>
            {:else}
                <span class="crumb cur">{section.label}</span>
            {/if}
        {:else}
            <span class="crumb cur">{tabLabel(activeTab)}</span>
        {/if}
        {/if}
    </nav>

    <div class="right">
        <button class="search" on:click={openPalette}>
            <Search size={14} />
            <span class="search-txt">Search or run a command</span>
            <span class="keys"><kbd>{isMac ? '⌘' : 'Ctrl'}</kbd><kbd>K</kbd></span>
        </button>
        {#if me && me.role === 'viewer'}<span class="ui-tag viewonly" title="Signed in through Tailscale as {me.login}">View only · {me.name}</span>{/if}
        <div class="uplink-wrap"><UplinkStatus compact /></div>
    </div>
</header>

<style>
    .topbar { height: 52px; flex-shrink: 0; display: flex; align-items: center; gap: 14px; padding: 0 14px 0 20px; background: var(--chrome, var(--surface)); border-bottom: 1px solid var(--border); position: relative; z-index: 30; }

    .crumbs { display: flex; align-items: center; gap: 6px; min-width: 0; font-size: 13.5px; }
    .crumbs :global(.sep) { color: var(--text-secondary); opacity: 0.6; flex-shrink: 0; }
    .crumb { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .crumb.dim { color: var(--text-secondary); }
    .crumb.link { color: var(--text-secondary); cursor: pointer; font-size: inherit; }
    .crumb.link:hover { color: var(--text-primary); text-decoration: underline; }
    .crumb.cur { color: var(--text-primary); font-weight: 600; }

    .right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
    /* a quiet filled field: no outline until hovered, keys as small separate caps */
    .search { display: flex; align-items: center; gap: 9px; width: 300px; height: 32px; padding: 0 6px 0 11px; border: 1px solid transparent; border-radius: 8px; background: var(--highlight-5); color: var(--text-secondary); font-size: 13px; cursor: pointer; box-sizing: border-box; transition: background-color .12s, border-color .12s, color .12s; }
    .search:hover { background: var(--highlight-10); border-color: var(--border); color: var(--text-primary); }
    .search:focus-visible { outline: none; border-color: var(--accent); }
    .search-txt { flex: 1; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .keys { display: flex; gap: 3px; }
    kbd { min-width: 18px; height: 20px; box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; font-family: inherit; font-size: 11px; font-weight: 500; padding: 0 5px; border-radius: 5px; border: 1px solid var(--border); background: var(--surface); color: var(--text-secondary); }
    .uplink-wrap { padding: 0 6px; }
    .icon-btn { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 6px; color: var(--text-secondary); cursor: pointer; flex-shrink: 0; }
    .icon-btn:hover { background: var(--highlight-10); color: var(--text-primary); }
    .menu { display: none; }

    @media (max-width: 1000px) {
        .search { width: auto; }
        .search-txt, .keys { display: none; }
    }
    @media (max-width: 768px) {
        .topbar { gap: 8px; padding: 0 8px; }
        .menu { display: flex; }
        .crumb.dim, .crumb.link, .crumbs :global(.sep) { display: none; }
        .crumb.cur { font-size: 15px; }
        .right { gap: 4px; }
        .search { width: 32px; height: 32px; padding: 0; justify-content: center; border: none; background: none; }
    }
    .viewonly { white-space: nowrap; }
</style>
