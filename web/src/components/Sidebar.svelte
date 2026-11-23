<script>
    import { X, ChevronRight, ChevronDown, PanelLeftClose, PanelLeftOpen, Laptop, Server, Plus, Cpu } from 'lucide-svelte';
    import { tree, treeActivePath } from '../lib/infra.js';
    import { onMount } from 'svelte';
    import { slide } from 'svelte/transition';
    import { NAV, childrenOf, foldParents } from '../lib/nav.js';
    import { machines, fetchMachines, visible } from '../lib/stores.js';
    import { services, fetchServices } from '../lib/services.js';
    import { hosts, fetchHosts, hostIcon, arrakisModel, hostOrder, fetchHostOrder, saveHostOrder } from '../lib/hosts.js';
    import { pools, fetchPools } from '../lib/compute.js';
    import { tsCounts, fetchTailnet } from '../lib/tailscale.js';
    import { cfCounts, fetchCloudflare } from '../lib/cloudflare.js';
    import { databases, fetchDatabases } from '../lib/databases.js';
    import { backups, fetchBackups } from '../lib/backups.js';
    import { updates, fetchUpdates } from '../lib/updates.js';
    import { endpointGroups, fetchEndpoints } from '../lib/endpoints.js';
    export let activeTab = "Overview";
    export let activeSection = null;
    export let activeSub = null;
    export let isMobileMenuOpen = false;
    export let collapsed = false;
    export let stats = null;
    export let onNavigate = () => {};

    $: svcList = $services || [...(stats?.daemons || []), ...(stats?.containers || [])];
    $: running = svcList.filter(s => s.status === 'running').length;
    $: total = svcList.length;
    $: machineList = $machines?.machines || [];

    // Unfolded parents and folded groups, remembered per browser. Arriving on a page
    // unfolds it; the chevron (or clicking the open page again) folds it, the active
    // page included.
    const load = (k) => { try { return new Set(JSON.parse(localStorage.getItem(k)) || []); } catch (e) { return new Set(); } };
    const save = (k, set) => { try { localStorage.setItem(k, JSON.stringify([...set])); } catch (e) {} };
    let expanded = load('arrakis_nav_expanded');
    let foldedGroups = load('arrakis_nav_groups_folded');

    function setOpen(tab, open) {
        if (open === expanded.has(tab)) return;
        open ? expanded.add(tab) : expanded.delete(tab);
        expanded = expanded;
        save('arrakis_nav_expanded', expanded);
    }
    // folds slide only when you click a chevron; rows that arrive with fetched data
    // (a VM's machines, a host's pages) just appear
    let animate = false, animTimer;
    function clicked() { animate = true; clearTimeout(animTimer); animTimer = setTimeout(() => animate = false, 250); }
    $: sl = { duration: animate ? 150 : 0 };

    // opened only because you arrived there: folds again when you leave
    const autoOpened = new Set();
    const toggle = (tab) => { clicked(); autoOpened.delete(tab); setOpen(tab, !expanded.has(tab)); };
    function toggleGroup(label) {
        clicked();
        foldedGroups.has(label) ? foldedGroups.delete(label) : foldedGroups.add(label);
        foldedGroups = foldedGroups;
        save('arrakis_nav_groups_folded', foldedGroups);
    }

    // a folded parent entry (Network) opens the same way, so its chevron can close it again
    const parentOf = (tab) => { const p = NAV.flatMap(g => g.items).find(i => i.tab === tab)?.parent; return p ? 'parent:' + p : null; };
    let lastTab = null;
    $: if (activeTab !== lastTab) {
        for (const t of [lastTab, parentOf(lastTab)]) if (t && t !== parentOf(activeTab) && autoOpened.has(t)) { autoOpened.delete(t); setOpen(t, false); }
        for (const t of [activeTab, parentOf(activeTab)]) if (t && !expanded.has(t)) { autoOpened.add(t); setOpen(t, true); }
        lastTab = activeTab;
    }

    // Parent row: go to the page (arriving unfolds it); clicking the row of the page you're on folds/unfolds it
    function goParent(tab) {
        onNavigate(tab, null);
        isMobileMenuOpen = false;
    }
    function goChild(tab, child) {
        onNavigate(tab, child.id || null);
        isMobileMenuOpen = false;
    }

    // ---- infrastructure tree ----------------------------------------------------------
    $: infraTree = tree(machineList, $hosts, $hostOrder, $pools || []);

    // ---- drag a host up or down the tree; the order is saved for every device ------------
    let dragId = null, dropId = null, dropAfter = false;
    function hostDragStart(e, id) {
        dragId = id;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', id);
    }
    function hostDragOver(e, id) {
        if (!dragId || id === dragId) return;
        e.preventDefault();
        const r = e.currentTarget.getBoundingClientRect();
        dropId = id; dropAfter = e.clientY > r.top + r.height / 2;
    }
    function hostDrop(e, id) {
        e.preventDefault();
        if (dragId && id !== dragId) {
            const ids = infraTree[0].children.map(c => c.id).filter(x => x !== dragId);
            ids.splice(ids.indexOf(id) + (dropAfter ? 1 : 0), 0, dragId);
            saveHostOrder(ids);
        }
        dragId = dropId = null;
    }
    // the node-id chain to the active route; its last id is the highlighted leaf, the rest unfold
    $: activePath = activeTab === 'Infra' ? treeActivePath(activeSection, activeSub, machineList, $hosts, $services, $pools || []) : [];
    $: activeLeaf = activePath[activePath.length - 1] || null;
    let treeOpen = load('arrakis_tree_open_v2');
    if (!treeOpen.size) treeOpen = new Set(['hosts', 'arrakis', 'orbstack']);
    // opened only because you arrived there (like Tools): folds again when you leave, and isn't saved
    const treeAuto = new Set();
    const saveTree = () => save('arrakis_tree_open_v2', new Set([...treeOpen].filter(id => !treeAuto.has(id))));
    function toggleNode(id) {
        clicked();
        treeAuto.delete(id);
        treeOpen.has(id) ? treeOpen.delete(id) : treeOpen.add(id);
        treeOpen = treeOpen;
        saveTree();
    }
    // arriving somewhere unfolds the way there and the node itself — but only when the route actually
    // changes, so you can still fold a section you're currently inside (the reactive won't re-open it).
    let lastPathKey = null;
    $: {
        const key = activePath.join('>');
        if (key !== lastPathKey) {
            lastPathKey = key;
            for (const id of [...treeAuto]) if (!activePath.includes(id)) { treeAuto.delete(id); treeOpen.delete(id); }
            for (const id of activePath) if (!treeOpen.has(id)) { treeAuto.add(id); treeOpen.add(id); }
            treeOpen = treeOpen;
        }
    }
    // a tab's children split at their headings: [{ heading: null, items }, { heading: 'Kept', items }, …]
    function headGroups(kids) {
        const out = [{ heading: null, items: [] }];
        for (const c of kids) {
            if (c.heading) out.push({ heading: c.heading, items: [] });
            out[out.length - 1].items.push(c);
        }
        return out.filter(g => g.items.length);
    }
    let foldedHeads = load('arrakis_nav_heads_folded');
    function toggleHead(k) {
        clicked();
        foldedHeads.has(k) ? foldedHeads.delete(k) : foldedHeads.add(k);
        foldedHeads = foldedHeads;
        save('arrakis_nav_heads_folded', foldedHeads);
    }
    function goNode(section, sub = null) {
        onNavigate('Infra', section, sub);
        isMobileMenuOpen = false;
    }

    let mobile = false;
    // Machine names fill the Machines submenu, so keep the list warm even off that page
    onMount(() => {
        const mq = window.matchMedia('(max-width: 768px)');
        mobile = mq.matches;
        const onMq = (e) => mobile = e.matches;
        mq.addEventListener('change', onMq);
        fetchMachines(); fetchHosts(); fetchHostOrder(); fetchPools();
        fetchServices();
        fetchTailnet(); fetchCloudflare(); fetchDatabases().catch(() => {}); fetchBackups(); fetchEndpoints(); fetchUpdates().catch(() => {});
        const t = setInterval(() => { if (visible()) { fetchMachines(); fetchServices(); fetchTailnet(); fetchHosts(); fetchPools(); fetchCloudflare(); fetchUpdates().catch(() => {}); } }, 30000);
        return () => { clearInterval(t); mq.removeEventListener('change', onMq); };
    });
</script>


{#snippet treeNode(n, depth)}
    {@const kids = n.children || []}
    {@const open = treeOpen.has(n.id)}
    {@const here = activeTab === 'Infra' && n.id === activeLeaf}
    {@const within = !here && activePath.includes(n.id)}
    <div class="tn-row" class:active={here} class:in={within} class:tab={n.kind === 'tab'} class:page={n.kind === 'tab' && !['vm', 'apps', 'workloads'].includes(n.sub)} class:off={n.kind === 'host' && n.state !== 'running'} style="--d: {depth}"
        class:dragging={dragId === n.id} class:drop-before={dropId === n.id && !dropAfter} class:drop-after={dropId === n.id && dropAfter}
        draggable={n.kind === 'host'} role={n.kind === 'host' ? 'listitem' : null}
        on:dragstart={(e) => n.kind === 'host' && hostDragStart(e, n.id)} on:dragover={(e) => n.kind === 'host' && hostDragOver(e, n.id)}
        on:dragleave={() => dropId === n.id && (dropId = null)} on:drop={(e) => n.kind === 'host' && hostDrop(e, n.id)} on:dragend={() => dragId = dropId = null}>
        {#if kids.length || n.kind === 'group'}
            <button class="tn-car" class:open on:click={() => toggleNode(n.id)} aria-label="{open ? 'Collapse' : 'Expand'} {n.label}" aria-expanded={open}><ChevronRight size={13} /></button>
        {:else}<span class="tn-car-sp"></span>{/if}
        <button class="tn-btn" class:top={depth === 0} title={n.label} on:click={() => here && (kids.length || n.kind === 'group') ? toggleNode(n.id) : goNode(n.section, n.sub)} aria-current={here ? 'page' : null}>
            {#if n.kind === 'group'}<span class="tn-ic"><svelte:component this={n.id === 'compute' ? Cpu : Server} size={15} /></span>
            {:else if n.kind === 'host'}<span class="tn-ic" class:off={n.state !== 'running'}><svelte:component this={n.id === 'arrakis' ? hostIcon($arrakisModel, 'macOS') : hostIcon(($hosts || []).find(x => x.id === n.id)?.report?.model, ($hosts || []).find(x => x.id === n.id)?.report?.os)} size={15} /></span>
            {:else if n.kind === 'machine' || n.kind === 'pool'}<span class="state-dot {n.state}"></span>{/if}
            <span class="txt">{n.label}</span>
            {#if n.kind === 'vm' && kids.length}<span class="sub-count">{kids.filter(k => k.state === 'running').length}/{kids.length}</span>{/if}
        </button>
    </div>
    {#if (kids.length || n.kind === 'group') && open}
        <div class="tn-kids" style="--d: {depth}" transition:slide={sl}>
            {#each kids as k (k.id)}{@render treeNode(k, depth + 1)}{/each}
            <!-- each root ends with its own "add" row: a host under Hosts, a pool under Compute -->
            {#if n.id === 'hosts' || n.id === 'compute'}
                {@const add = n.id === 'hosts' ? { label: 'Add host', section: 'new', sub: null } : { label: 'New pool', section: 'pools', sub: 'new' }}
                <div class="tn-row" class:active={activeTab === 'Infra' && activeSection === add.section && (activeSub || null) === add.sub} style="--d: {depth + 1}">
                    <span class="tn-car-sp"></span>
                    <button class="tn-btn add" on:click={() => goNode(add.section, add.sub)}><span class="tn-ic plain"><Plus size={14} /></span><span class="txt">{add.label}</span></button>
                </div>
            {/if}
        </div>
    {/if}
{/snippet}

{#snippet infraTreeBlock()}
    {#each infraTree as n (n.id)}{@render treeNode(n, 0)}{/each}
{/snippet}

{#snippet treeChild(item, child, depth)}
    <div class="tn-row" class:active={activeTab === item.tab && (activeSection ?? '') === child.id} style="--d: {child.nested ? depth + 1 : depth}">
        <span class="tn-car-sp"></span>
        <button class="tn-btn" title={child.label} on:click={() => goChild(item.tab, child)}>
            {#if child.state}<span class="state-dot {child.state}"></span>{/if}
            <span class="txt">{child.label}</span>
            {#if child.count != null}<span class="sub-count" class:warn={child.warn}>{child.count}</span>{/if}
        </button>
    </div>
{/snippet}

<!-- a Tools item drawn with the infrastructure tree's rows, so both groups look alike -->
{#snippet treeItem(item)}
    {@const open = expanded.has(item.tab)}
    {@const active = activeTab === item.tab}
    {@const kids = item.sub ? childrenOf(item.tab, null, null, $tsCounts, null, active ? activeSection : null, $cfCounts, $databases, $backups, $endpointGroups, $updates) : []}
    {@const childOn = active && kids.some(c => c.id === (activeSection ?? ''))}
    <div class="tn-row" class:active={active && !childOn} class:in={active && childOn} style="--d: 0">
        {#if kids.length}
            <button class="tn-car" class:open on:click={() => toggle(item.tab)} aria-label="{open ? 'Collapse' : 'Expand'} {item.tab}" aria-expanded={open}><ChevronRight size={13} /></button>
        {:else}<span class="tn-car-sp"></span>{/if}
        <button class="tn-btn top" on:click={() => active && !activeSection && kids.length ? toggle(item.tab) : goParent(item.tab)} aria-current={active ? 'page' : null}>
            <span class="tn-ic"><svelte:component this={item.icon} size={15} /></span>
            <span class="txt">{item.label || item.tab}</span>
        </button>
    </div>
    {#if kids.length && open}
        <div class="tn-kids" style="--d: 0" transition:slide={sl}>
            {#each headGroups(kids) as g, gi}
                {#if g.heading}
                    <!-- a heading ("Kept", where a database lives) is a foldable row; its items sit one level in -->
                    {@const hk = `${item.tab}:${g.heading}`}
                    {@const hOpen = !foldedHeads.has(hk) || g.items.some(c => active && (activeSection ?? '') === c.id)}
                    <div class="tn-row head" style="--d: 1">
                        <button class="tn-car" class:open={hOpen} on:click={() => toggleHead(hk)} aria-label="{hOpen ? 'Collapse' : 'Expand'} {g.heading}" aria-expanded={hOpen}><ChevronRight size={13} /></button>
                        <button class="tn-btn" on:click={() => toggleHead(hk)}><span class="txt">{g.heading}</span><span class="sub-count">{g.items.filter(c => !c.nested).length}</span></button>
                    </div>
                    {#if hOpen}
                        <div class="tn-kids" style="--d: 1" transition:slide={sl}>{#each g.items as child}{@render treeChild(item, child, 2)}{/each}</div>
                    {/if}
                {:else}
                    {#each g.items as child}{@render treeChild(item, child, 1)}{/each}
                {/if}
            {/each}
        </div>
    {/if}
{/snippet}

<!-- one entry for several pages (Network: Tailscale, Cloudflare, tools); the name opens the first -->
{#snippet parentItem(p)}
    {@const open = expanded.has(p.tab)}
    {@const inside = p.items.some(i => i.tab === activeTab)}
    <div class="tn-row" class:in={inside} style="--d: 0">
        <button class="tn-car" class:open on:click={() => toggle(p.tab)} aria-label="{open ? 'Collapse' : 'Expand'} {p.label}" aria-expanded={open}><ChevronRight size={13} /></button>
        <button class="tn-btn top" on:click={() => inside ? toggle(p.tab) : goParent(p.items[0].tab)}>
            <span class="tn-ic"><svelte:component this={p.icon} size={15} /></span>
            <span class="txt">{p.label}</span>
        </button>
    </div>
    {#if open}
        <div class="tn-kids" style="--d: 0" transition:slide={sl}>
            {#each p.items as item (item.tab)}
                {@const here = activeTab === item.tab}
                {@const kids = item.pages ? item.children : []}
                {@const iOpen = kids.length && expanded.has(item.tab)}
                <!-- which tab is open: a listed one, else the first (a tunnel page belongs to Tunnels) -->
                {@const on = here && kids.length ? (kids.find(c => c.id && c.id === activeSection) || kids[0]).id : null}
                <div class="tn-row" class:active={here && !kids.length} class:in={here && kids.length} style="--d: 1">
                    {#if kids.length}<button class="tn-car" class:open={iOpen} on:click={() => toggle(item.tab)} aria-label="{iOpen ? 'Collapse' : 'Expand'} {item.tab}" aria-expanded={!!iOpen}><ChevronRight size={13} /></button>{:else}<span class="tn-car-sp"></span>{/if}
                    <button class="tn-btn" on:click={() => here && kids.length && !activeSection ? toggle(item.tab) : goParent(item.tab)} aria-current={here ? 'page' : null}>
                        <span class="tn-ic"><svelte:component this={item.icon} size={14} /></span>
                        <span class="txt">{item.label || item.tab}</span>
                    </button>
                </div>
                {#if iOpen}
                    <div class="tn-kids" style="--d: 1" transition:slide={sl}>
                        {#each kids as child}
                            <div class="tn-row" class:active={on === child.id} style="--d: 2">
                                <span class="tn-car-sp"></span>
                                <button class="tn-btn" title={child.label} on:click={() => goChild(item.tab, child)}><span class="txt">{child.label}</span></button>
                            </div>
                        {/each}
                    </div>
                {/if}
            {/each}
        </div>
    {/if}
{/snippet}

{#snippet navItem(item)}
                <!-- items are single pages: their children (filters, tabs, sections) live on the page,
                     except items marked sub (Cloudflare), whose filters are listed here too -->
                {@const open = expanded.has(item.tab)}
                {@const active = activeTab === item.tab}
                {@const kids = item.sub ? childrenOf(item.tab, null, null, $tsCounts, null, active ? activeSection : null, $cfCounts, $databases, $backups, $endpointGroups, $updates) : []}
                {@const childOn = active && kids.some(c => c.id === (activeSection ?? ''))}
                <div class="nav-item" class:has-kids={kids.length}>
                    <div class="row" class:active={active && !childOn} class:in={active}>
                        <button class="nav-btn" on:click={() => goParent(item.tab)} title={collapsed ? (item.label || item.tab) : null} aria-current={active ? 'page' : null}>
                            <svelte:component this={item.icon} size={16} />
                            <span class="txt">{item.label || item.tab}</span>
                            {#if item.tab === 'Services' && total}
                                <span class="nav-badge {running < total ? 'crit' : ''}" title="{running} of {total} services running">{running}/{total}</span>
                            {/if}
                            {#if item.tab === 'Machines' && machineList.length}
                                <span class="nav-badge">{machineList.length}</span>
                            {/if}
                        </button>
                        {#if kids.length}
                            <button class="chev" class:open on:click={() => toggle(item.tab)} aria-label="{open ? 'Collapse' : 'Expand'} {item.tab}" aria-expanded={open}>
                                <ChevronRight size={14} />
                            </button>
                        {/if}
                    </div>
                    {#if kids.length && (open || collapsed)}
                        <div class="sub" class:flyout={collapsed} transition:slide={collapsed ? { duration: 0 } : sl}>
                            {#if collapsed}<button class="fly-title" on:click={() => goParent(item.tab)}>{item.label || item.tab}</button>{/if}
                            {#each kids as child}
                                {#if child.sep}<div class="sub-sep"></div>{/if}
                                {#if child.heading}<div class="sub-head">{child.heading}</div>{/if}
                                <button class="sub-btn" class:nested={child.nested} class:active={active && (activeSection ?? '') === child.id} on:click={() => goChild(item.tab, child)}>
                                    {#if child.state}<span class="state-dot {child.state}"></span>{/if}
                                    <span class="txt">{child.label}</span>
                                    {#if child.count != null}<span class="sub-count" class:warn={child.warn}>{child.count}</span>{/if}
                                </button>
                            {/each}
                        </div>
                    {/if}
                </div>
{/snippet}

<aside class="sidebar {isMobileMenuOpen ? 'open' : ''}" class:rail={collapsed && !mobile}>
    <div class="mobile-head">
        <span class="mh-title">Navigation</span>
        <button class="icon-btn" on:click={() => isMobileMenuOpen = false} aria-label="Close menu"><X size={18} /></button>
    </div>

    <nav class="nav">
        {#each NAV.filter(g => !g.footer) as group}
            {@const folded = group.label && foldedGroups.has(group.label) && !collapsed}
            <div class="nav-group">
                {#if group.label}
                    <button class="nav-label" on:click={() => toggleGroup(group.label)} aria-expanded={!folded}>
                        {group.label}<span class="glyph" class:folded><ChevronDown size={12} /></span>
                    </button>
                {/if}
                {#if group.tree && !collapsed}
                    {#if !folded || activeTab === 'Infra'}<div class="tree">{@render infraTreeBlock()}</div>{/if}
                {:else if group.tree}
                    <div class="nav-item">
                        <div class="row" class:active={activeTab === 'Infra'}>
                            <button class="nav-btn" on:click={() => goNode(null)} title="Infrastructure"><Server size={16} /><span class="txt">Infrastructure</span></button>
                        </div>
                        <div class="sub flyout tree"><button class="fly-title" on:click={() => goNode(null)}>Infrastructure</button>{@render infraTreeBlock()}</div>
                    </div>
                {:else if !collapsed}
                    <div class="tree">
                        {#each foldParents(group.items).filter(i => !folded || i.tab === activeTab || i.items?.some(x => x.tab === activeTab)) as item (item.tab)}{#if item.parent}{@render parentItem(item)}{:else}{@render treeItem(item)}{/if}{/each}
                    </div>
                {:else}
                {#each group.items as item (item.tab)}
                    {@render navItem(item)}
                {/each}
                {/if}
            </div>
        {/each}
    </nav>

    <div class="sidebar-foot">
        <div class="foot-items">
            {#each NAV.filter(g => g.footer).flatMap(g => g.items) as item (item.tab)}
                {#if collapsed && !mobile}{@render navItem(item)}{:else}{@render treeItem(item)}{/if}
            {/each}
        </div>
        <button class="collapse-btn" on:click={() => collapsed = !collapsed} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            {#if collapsed}<PanelLeftOpen size={16} />{:else}<PanelLeftClose size={16} />{/if}
        </button>
    </div>
</aside>

<style>
    .sidebar { width: 248px; flex-shrink: 0; display: flex; flex-direction: column; background: var(--chrome, var(--surface)); border-right: 1px solid var(--border); box-sizing: border-box; transition: width 0.15s ease; }
    .nav { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 12px 10px; display: flex; flex-direction: column; gap: 14px; }
    .nav-label { display: flex; align-items: center; justify-content: space-between; width: 100%; font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-secondary); padding: 4px 10px; margin-bottom: 2px; border-radius: 5px; white-space: nowrap; cursor: pointer; text-align: left; }
    .nav-label:hover { color: var(--text-primary); background: var(--highlight-5); }
    .glyph { display: flex; opacity: 0; transition: transform .15s ease, opacity .15s; }
    .nav-label:hover .glyph, .glyph.folded { opacity: 1; }
    .glyph.folded { transform: rotate(-90deg); }

    .row { display: flex; align-items: center; border-radius: 6px; position: relative; }
    .row:hover { background: var(--highlight-10); }
    .row.in .nav-btn { color: var(--text-primary); }
    .row.active { background: var(--accent-soft); }
    .row.active .nav-btn { color: var(--accent); }
    .row.active::before { content: ''; position: absolute; left: -10px; top: 6px; bottom: 6px; width: 3px; border-radius: 0 3px 3px 0; background: var(--accent); }
    .nav-btn { flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; padding: 7px 10px; font-size: 13.5px; font-weight: 500; color: var(--text-secondary); cursor: pointer; text-align: left; white-space: nowrap; }
    .row.in .nav-btn { font-weight: 600; }
    .txt { overflow: hidden; text-overflow: ellipsis; }
    .chev { display: flex; align-items: center; justify-content: center; width: 26px; height: 26px; margin-right: 2px; border-radius: 5px; color: var(--text-secondary); cursor: pointer; flex-shrink: 0; transition: transform 0.2s cubic-bezier(0.22, 1, 0.36, 1), background-color .12s, color .12s; }
    .chev:hover { background: var(--highlight-15); color: var(--text-primary); }
    .chev.open { transform: rotate(90deg); }

    .sub { display: flex; flex-direction: column; gap: 1px; margin: 2px 0 4px 18px; padding-left: 10px; border-left: 1px solid var(--border); }
    .sub-btn { display: flex; align-items: center; gap: 8px; padding: 5px 10px; border-radius: 5px; font-size: 13px; color: var(--text-secondary); cursor: pointer; text-align: left; white-space: nowrap; min-width: 0; }
    .sub-btn:hover { background: var(--highlight-10); color: var(--text-primary); }
    .sub-btn.active { color: var(--accent); font-weight: 600; background: var(--accent-soft); }
    .sub-btn.nested { margin-left: 14px; padding-left: 10px; position: relative; }
    .sub-btn.nested::before { content: ''; position: absolute; left: 0; top: 50%; width: 6px; height: 1px; background: var(--border-strong); }
    .foot-items { flex: 1; min-width: 0; }
    .sub-count { margin-left: auto; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
    .sub-count.warn { color: var(--red); }
    .sub-head { font-size: 11px; font-weight: 600; color: var(--text-secondary); opacity: 0.6; padding: 8px 10px 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .sub-sep { height: 1px; margin: 4px 10px 4px 0; background: var(--highlight-5); }
    .state-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; background: var(--text-secondary); opacity: 0.6; }
    .state-dot.running { background: var(--green); opacity: 1; }

    .nav-badge { margin-left: auto; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; font-weight: 600; line-height: 1; padding: 3px 6px; border-radius: 99px; background: var(--highlight-10); color: var(--text-secondary); font-variant-numeric: tabular-nums; }
    .nav-badge.crit { background: rgba(184, 76, 62, 0.15); color: var(--red); }

    /* Settings and the collapse toggle share one row; the toggle is a bare icon on the right */
    .sidebar-foot { border-top: 1px solid var(--border); padding: 8px 10px; display: flex; align-items: center; gap: 4px; }
    .collapse-btn { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; flex-shrink: 0; border-radius: 6px; color: var(--text-secondary); cursor: pointer; }
    .collapse-btn:hover { background: var(--highlight-10); color: var(--text-primary); }

    /* Rail: icons only, submenus fly out on hover */
    .rail { width: 56px; }
    .rail .nav { overflow: visible; padding: 12px 8px; }
    .rail .txt, .rail .nav-badge, .rail .chev, .rail .nav-label { display: none; }
    .rail .nav-group + .nav-group { border-top: 1px solid var(--border); padding-top: 12px; }
    .rail .nav-btn { justify-content: center; padding: 8px; }
    .rail .row.active::before { left: -8px; }
    .rail .sidebar-foot { padding: 8px; flex-direction: column; align-items: stretch; }
    .rail .collapse-btn { width: auto; }
    .nav-item { position: relative; }
    .sub.flyout { display: none; position: absolute; left: calc(100% + 4px); top: -4px; margin: 0; padding: 6px; min-width: 180px; border: 1px solid var(--border); border-radius: var(--radius-card, 8px); background: var(--surface); box-shadow: 0 8px 24px rgba(0,0,0,0.12); z-index: 70; }
    .sub.flyout::before { content: ''; position: absolute; left: -8px; top: 0; bottom: 0; width: 8px; }
    /* stays up a moment after the pointer leaves, so a diagonal move to an entry doesn't close it */
    .rail .sub.flyout { display: flex; visibility: hidden; opacity: 0; transition: visibility 0s .15s, opacity .1s .05s; }
    .rail .nav-item:hover .sub.flyout { visibility: visible; opacity: 1; transition-delay: 0s; }
    .fly-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); padding: 4px 10px 6px; text-align: left; cursor: pointer; }
    .rail .sub.flyout .txt { display: inline; }

    /* infrastructure tree */
    .tree { display: flex; flex-direction: column; gap: 1px; }
    .tn-row { display: flex; align-items: center; border-radius: 6px; position: relative; padding-left: calc(var(--d) * 16px); }
    .tn-row:hover { background: var(--highlight-10); }
    .tn-row.active { background: var(--accent-soft); }
    /* dragging a host to reorder: a line where it will land */
    .tn-row.dragging { opacity: 0.5; }
    .tn-row.drop-before::after, .tn-row.drop-after::after { content: ''; position: absolute; left: calc(var(--d) * 16px); right: 0; height: 2px; border-radius: 1px; background: var(--accent); pointer-events: none; }
    .tn-row.drop-before::after { top: -1px; }
    .tn-row.drop-after::after { bottom: -1px; }
    .tn-row.active::before { content: ''; position: absolute; left: -10px; top: 6px; bottom: 6px; width: 3px; border-radius: 0 3px 3px 0; background: var(--accent); }
    .tn-car { width: 20px; height: 26px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; color: var(--text-secondary); border-radius: 4px; cursor: pointer; transition: transform .15s ease; }
    .tn-car:hover { color: var(--text-primary); }
    .tn-car.open { transform: rotate(90deg); }
    .tn-car-sp { width: 20px; flex-shrink: 0; }
    .tn-btn { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; padding: 6px 8px 6px 2px; font-size: 13px; color: var(--text-secondary); text-align: left; white-space: nowrap; cursor: pointer; }
    .tn-btn.top { font-size: 13.5px; font-weight: 500; }
    .tn-row:hover .tn-btn, .tn-row.in .tn-btn { color: var(--text-primary); }
    .tn-row.in .tn-btn { font-weight: 600; }
    .tn-row.active .tn-btn { color: var(--accent); font-weight: 600; }
    .tn-ic { display: flex; color: inherit; flex-shrink: 0; }
    .tn-ic.off { opacity: 0.5; }
    .tn-row.off .txt { opacity: 0.55; }
    /* a host's pages (Storage, Metrics, Settings) sit a little apart from what runs on it */
    :is(.tn-row:not(.page), .tn-kids) + .tn-row.page { margin-top: 6px; }
    .tn-btn .state-dot { margin: 0 4px 0 3px; }
    .tn-btn .sub-count { margin-left: auto; }
    .tn-btn.add { color: var(--text-secondary); font-size: 12.5px; }
    .tn-row.tab:not(.active) .tn-btn { color: var(--text-secondary); }
    /* heading rows (Kept, a database's machine): quieter than a page, and not a link */
    .tn-row.head .tn-btn { font-size: 12px; font-weight: 600; color: var(--text-secondary); }
    .tn-row.head .tn-btn .sub-count { font-weight: 400; opacity: .8; }
    .sub.flyout.tree { min-width: 220px; }
    .sub.flyout.tree .tn-row.active::before { display: none; }

    /* keyboard focus: a thin accent ring on the row's button */
    .tn-btn:focus-visible, .tn-car:focus-visible, .nav-btn:focus-visible, .chev:focus-visible, .sub-btn:focus-visible,
    .nav-label:focus-visible, .fly-title:focus-visible, .collapse-btn:focus-visible, .icon-btn:focus-visible { outline: 1px solid var(--accent); outline-offset: -1px; border-radius: 5px; }

    .mobile-head { display: none; }
    .icon-btn { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 6px; color: var(--text-secondary); cursor: pointer; }
    .icon-btn:hover { background: var(--highlight-10); color: var(--text-primary); }

    @media (max-width: 768px) {
        .sidebar, .sidebar.rail { position: fixed; top: 0; bottom: 0; left: -280px; width: 272px; z-index: 50; transition: left 0.2s ease-in-out; box-shadow: 2px 0 12px rgba(0,0,0,0.12); }
        .sidebar.open { left: 0; }
        .mobile-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 12px 4px 20px; }
        .mh-title { font-size: 13px; font-weight: 600; }
        .collapse-btn { display: none; }
    }
</style>
