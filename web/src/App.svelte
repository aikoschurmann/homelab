<script>
    import { SN } from './lib/server.js';
    import { savedTheme, applyTheme, applyAppearance, savedAppearance } from './lib/theme.js';
    import { onMount, tick } from 'svelte';
    import Sidebar from './components/Sidebar.svelte';
    import TopBar from './components/TopBar.svelte';
    import EndpointsView from './components/EndpointsView.svelte';
    import CommandPalette from './components/CommandPalette.svelte';
    import Toast from './components/Toast.svelte';
    import WebLinkDialog from './components/WebLinkDialog.svelte';
    import { loadWebLinks } from './lib/weblinks.js';
    import TerminalTab from './components/TerminalTab.svelte';
    import BackupsTab from './components/BackupsTab.svelte';
    import SettingsSection from './components/SettingsSection.svelte';
    import ToolsPage from './components/ToolsPage.svelte';
    import OverviewTab from './components/OverviewTab.svelte';
    import DatabasesTab from './components/DatabasesTab.svelte';
    import InfraTab from './components/InfraTab.svelte';
    import { legacyRoute, pathOf } from './lib/infra.js';
    import TailscaleTab from './components/TailscaleTab.svelte';
    import CloudflareTab from './components/CloudflareTab.svelte';
    import LogsTab from './components/LogsTab.svelte';
    import UpdatesTab from './components/UpdatesTab.svelte';
    import AppsTab from './components/AppsTab.svelte';
    import Sortable from 'sortablejs';
    import { Loader2 } from 'lucide-svelte';
    import { stats as statsStore, uplink, visible, machines } from './lib/stores.js';
    import { ALL_TABS, childrenOf } from './lib/nav.js';
    import { services } from './lib/services.js';
    import { hosts } from './lib/hosts.js';
    import { pools } from './lib/compute.js';
    import { tsCounts, fetchTailnet } from './lib/tailscale.js';

    // Hash is #tab or #tab/section, e.g. #machines/casaos
    // Hash is #tab, #tab/section or #tab/item/subtab, e.g. #machines/casaos/settings
    // old #machines / #services / #hosts links resolve to their Infrastructure node
    const parseHash = () => {
        // the Metrics page is a section of the Overview now (its editor is the Overview's)
        const mh = window.location.hash.match(/^#metrics(\/customize)?/i);
        if (mh) history.replaceState(null, '', '#overview' + (mh[1] ? '/customize' : ''));
        const [t, s, u] = window.location.hash.slice(1).split('/');
        const r = { tab: ALL_TABS.find(x => x.toLowerCase() === (t || '').toLowerCase()), section: s ? decodeURIComponent(s) : null, sub: u || null };
        return legacyRoute(r.tab, r.section, r.sub) || r;
    };

    let stats = null;
    let backups = null;
    let tmux = null;
    let historyData = null;
    let incusVms = [];
    let activeTab = parseHash().tab || 'Overview';
    let activeSection = parseHash().section;
    let activeSub = parseHash().sub;
    let isMobileMenuOpen = false;
    let sidebarCollapsed = false;
    try { sidebarCollapsed = localStorage.getItem('arrakis_sidebar_collapsed') === '1'; } catch (e) {}
    $: try { localStorage.setItem('arrakis_sidebar_collapsed', sidebarCollapsed ? '1' : '0'); } catch (e) {}

    $: if (activeTab) {
        const h = '#' + activeTab.toLowerCase() + (activeSection ? '/' + encodeURIComponent(activeSection) + (activeSub ? '/' + activeSub : '') : '');
        // real navigation gets a history entry (Back works); scroll-spy updates don't
        // an old #machines/… link is replaced, not stacked, so Back doesn't bounce on it
        const legacyHash = /^#(machines|services|hosts)\b|^#infra\/(orbstack|apps|hosts)$|^#infra\/arrakis\/machines$/i.test(window.location.hash);
        if (window.location.hash !== h) pushNext && !legacyHash ? history.pushState(null, '', h) : history.replaceState(null, '', h);
        pushNext = false;
    }

    let scrollEl;
    // Section ids scroll into view once the page has rendered them; pages that load
    // their data first (Machines, Endpoints) get a couple of seconds to catch up
    async function scrollToSection(tab, section, tries = 30) {
        await tick();
        if (tab !== activeTab || section !== activeSection) return;
        const child = section && childrenOf(tab, $machines?.machines, $services, $tsCounts, $hosts).find(c => c.id === section);
        // no anchor: the section is a page of its own (a machine, a create form)
        if (!child?.el) { scrollEl?.scrollTo({ top: 0 }); return; }
        const el = document.getElementById(child.el);
        if (el) {
            spyPausedUntil = Date.now() + 800;
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
            el.classList.remove('nav-flash'); void el.offsetWidth; el.classList.add('nav-flash');
        } else if (tries) setTimeout(() => scrollToSection(tab, section, tries - 1), 100);
    }

    let pushNext = false;
    function navigate(tab, section = null, sub = null) {
        const l = legacyRoute(tab, section, sub);
        if (l) ({ tab, section, sub } = l);
        pushNext = true;
        activeTab = tab;
        activeSection = section || null;
        activeSub = sub;
        isMobileMenuOpen = false;
        scrollToSection(tab, section);
    }

    // Scroll spy: the sidebar follows the section at the top of the page
    let spyPausedUntil = 0;
    function onScroll() {
        if (Date.now() < spyPausedUntil || !scrollEl) return;
        const kids = childrenOf(activeTab, $machines?.machines, $services, $tsCounts, $hosts);
        // on a page of its own (machine detail, create) there is nothing to follow
        if (activeSection && !kids.find(c => c.id === activeSection)?.el) return;
        const top = scrollEl.getBoundingClientRect().top + 90;
        let current = null;
        for (const c of kids) {
            if (!c.el) continue;
            const el = document.getElementById(c.el);
            if (el && el.getBoundingClientRect().top <= top) current = c.id;
        }
        if (scrollEl.scrollTop < 10) current = null;
        if (current !== activeSection) activeSection = current;
    }

    // Browser tab shows where you are
    $: document.title = `${activeTab === 'Infra' ? (pathOf(activeSection, $machines?.machines, $hosts, $services, $pools).at(-1)?.label || 'Infrastructure') : activeTab} · ${SN}`;

    let isFetching = false;
    let lastFetchAt = null;
    let uplinkOk = true;
    let connectionMethod = 'HTTP';
    let pollIntervalMs = 5000;

    $: statsStore.set(stats);
    $: uplink.set({ ok: uplinkOk, method: connectionMethod, lastFetchAt, pollIntervalMs });

    let sectionsEl;
    let footerEl;

    let sectionsOrder = ['row-overview', 'docker', 'native', 'tailscale', 'ssh', 'tmux'];
    let footerOrder = ['logs', 'backups', 'settings'];

    try {
        const s2 = JSON.parse(localStorage.getItem('arrakis_main_order'));
        if (s2 && s2.length) sectionsOrder = [...new Set([...s2, ...sectionsOrder])].filter(k => sectionsOrder.includes(k) && k !== 'chart');

        const s3 = JSON.parse(localStorage.getItem('arrakis_footer_order'));
        if (s3 && s3.length) footerOrder = [...new Set([...s3, ...footerOrder])].filter(k => footerOrder.includes(k));
    } catch(e){}

    let toastMsg = '';

    // a new message restarts the timer, so it isn't cut short by the previous one's
    let toastTimer;
    function showToast(msg) {
        toastMsg = msg;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toastMsg = '', 3200);
    }

    let sseSource = null;
    function initSSE() {
        if (sseSource) sseSource.close();
        sseSource = new EventSource('/api/stream');

        sseSource.onmessage = (event) => {
            try {
                const result = JSON.parse(event.data);
                if (result.status === 'success') {
                    stats = result.data;
                    uplinkOk = true;
                    connectionMethod = 'SSE';
                    lastFetchAt = Date.now();
                }
            } catch (e) {}
        };

        sseSource.onerror = () => {
            // The stream dropping isn't an outage by itself: HTTP polling takes over and
            // marks the uplink down only if that fails too
            sseSource.close();
            if (connectionMethod === 'SSE') { connectionMethod = 'HTTP'; fetchStats(true); }
            setTimeout(initSSE, 2000);
        };
    }

    let lastSlowFetchAt = 0;
    const SLOW_FETCH_MS = 60000; // backups + 24h history change slowly; no need to refetch every poll

    async function fetchStats(force = false) {
        if (isFetching) return;
        isFetching = true;
        try {
            // Stats are pushed via SSE; only fall back to HTTP polling when the stream is down
            const sseLive = sseSource && sseSource.readyState === EventSource.OPEN;
            const result = (force || !sseLive)
                ? await fetch('/api/stats').then(r => r.json())
                : { status: 'skipped' };

            if (result.status === 'success') {
                stats = result.data;
                uplinkOk = true;
                if (!sseSource || sseSource.readyState !== EventSource.OPEN) {
                    connectionMethod = 'HTTP';
                }
                lastFetchAt = Date.now();
            } else if (result.status !== 'skipped') {
                uplinkOk = false;
            }

            const slow = force || Date.now() - lastSlowFetchAt > SLOW_FETCH_MS;
            if (slow) lastSlowFetchAt = Date.now();
            Promise.all([
                slow ? fetch('/api/backups/config').then(r => r.json()).catch(() => null) : null,
                slow ? fetch('/api/backups').then(r => r.json()).catch(() => null) : null,
                fetch('/api/tmux/sessions').then(r => r.json()).catch(() => null),
                slow ? fetch('/api/history').then(r => r.json()).catch(() => null) : null
            ]).then(([bConfRes, bListRes, tRes, hRes]) => {
                if (tRes) tmux = tRes;
                if (hRes?.status === 'success') historyData = hRes.data;
                if (bConfRes?.status === 'success' && bListRes?.status === 'success') {
                    backups = { config: bConfRes.data, list: bListRes.data || [] };
                }
            });

        } catch (err) {
            // The fetch itself failed: the backend is unreachable
            if (!sseSource || sseSource.readyState !== EventSource.OPEN) uplinkOk = false;
            console.error(err);
        }
        isFetching = false;
    }

    // Polling honours the sync rate from Settings and pauses while the tab is hidden
    let pollTimer = null;
    function restartPolling(ms) {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(() => visible() && fetchStats(false), ms);
    }
    $: if (pollTimer) restartPolling(pollIntervalMs);

    // A tab left open keeps running the build it loaded (navigation only changes the #hash).
    // Every minute, compare the script index.html points at with the one running; when a
    // newer build is deployed, reload, unless someone is typing.
    const loadedBuild = [...document.scripts].map(s => s.src).find(src => /\/assets\/index-/.test(src)) || '';
    async function checkForNewBuild() {
        if (!loadedBuild || !visible()) return;
        try {
            const html = await fetch('/', { cache: 'no-store' }).then(r => r.text());
            const m = html.match(/\/static\/assets\/index-[A-Za-z0-9_-]+\.js/);
            if (!m || loadedBuild.endsWith(m[0])) return;
            const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
            if (typing) return;
            showToast('Dashboard updated, reloading…');
            setTimeout(() => location.reload(), 1200);
        } catch (e) {}
    }

    onMount(() => {
        window.showToast = showToast;
        loadWebLinks();
        const buildCheck = setInterval(checkForNewBuild, 60000);
        document.addEventListener('visibilitychange', checkForNewBuild);
        // Load theme
        applyTheme(savedTheme());
        applyAppearance(savedAppearance());

        const onHash = () => {
            const { tab, section, sub } = parseHash();
            if (tab && (tab !== activeTab || section !== activeSection || sub !== activeSub)) navigate(tab, section, sub);
        };
        if (activeSection) scrollToSection(activeTab, activeSection);
        window.addEventListener('hashchange', onHash);

        const onVisible = () => { if (visible()) fetchStats(true); };
        document.addEventListener('visibilitychange', onVisible);

        initSSE();
        fetchStats();
        restartPolling(pollIntervalMs);

        const initSortable = (el, group) => {
            if (el) {
                new Sortable(el, {
                    group: group,
                    animation: 150,
                    handle: '.drag-handle',
                    ghostClass: 'sortable-ghost',
                    onEnd: () => {
                        try {
                            const newOrder = Array.from(el.children).map(c => c.getAttribute('data-id')).filter(Boolean);
                            if(newOrder.length) {
                                localStorage.setItem(`arrakis_${group}_order`, JSON.stringify(newOrder));
                                if (group === 'main') sectionsOrder = newOrder;
                                if (group === 'footer') footerOrder = newOrder;
                            }
                        } catch (e) {
                            console.error('Sortable error:', e);
                        }
                    }
                });
            }
        };

        initSortable(sectionsEl, 'main');
        initSortable(footerEl, 'footer');

        return () => {
            if (pollTimer) clearInterval(pollTimer);
            clearInterval(buildCheck);
            document.removeEventListener('visibilitychange', checkForNewBuild);
            window.removeEventListener('hashchange', onHash);
            document.removeEventListener('visibilitychange', onVisible);
            if (sseSource) sseSource.close();
        };
    });
</script>

<div class="app-container">
    <TopBar {activeTab} {activeSection} {activeSub} bind:isMobileMenuOpen onNavigate={navigate} />
    <div class="app-body">
    <Sidebar {activeTab} {activeSection} {activeSub} bind:isMobileMenuOpen bind:collapsed={sidebarCollapsed} {stats} onNavigate={navigate} />
    {#if isMobileMenuOpen}
        <div class="mobile-overlay" on:click={() => isMobileMenuOpen = false} role="presentation"></div>
    {/if}

    <div class="main-content">
        <div class="scroll-area" bind:this={scrollEl} on:scroll={onScroll}>
            <div class="page-wrap">
            {#if !stats}
                <div class="boot"><Loader2 size={16} class="ui-spin" /> Connecting to {SN}…</div>
            {:else}
                {#if activeTab === 'Infra'}
                    <InfraTab section={activeSection} sub={activeSub} onNavigate={navigate} />
                {/if}

                {#if activeTab === 'Endpoints'}
                    <EndpointsView section={activeSection} sub={activeSub} onNavigate={navigate} />
                {/if}

                {#if activeTab === 'Tools'}
                    <ToolsPage {stats} section={activeSection} onNavigate={navigate} />
                {/if}

                {#if activeTab === 'Settings'}
                    <SettingsSection {stats} section={activeSection} onNavigate={navigate} bind:pollIntervalMs />
                {/if}

                {#if activeTab === 'Terminal'}
                    <TerminalTab sessions={tmux?.sessions || []} section={activeSection} onNavigate={navigate} refresh={() => fetchStats(true)} />
                {/if}

                {#if activeTab === 'Databases'}
                    <DatabasesTab section={activeSection} sub={activeSub} onNavigate={navigate} />
                {/if}

                {#if activeTab === 'Tailscale'}
                    <TailscaleTab section={activeSection} sub={activeSub} onNavigate={navigate} />
                {/if}

                {#if activeTab === 'Cloudflare'}
                    <CloudflareTab section={activeSection} onNavigate={navigate} />
                {/if}

                {#if activeTab === 'Logs'}
                    <LogsTab />
                {/if}

                {#if activeTab === 'Updates'}
                    <UpdatesTab section={activeSection} onNavigate={navigate} />
                {/if}

                {#if activeTab === 'Apps'}
                    <AppsTab section={activeSection} onNavigate={navigate} />
                {/if}



                {#if activeTab === 'Backups'}
                    <BackupsTab section={activeSection} onNavigate={navigate} />
                {/if}


                {#if activeTab === 'Overview'}
                    <OverviewTab {stats} {tmux} section={activeSection} sub={activeSub} onNavigate={navigate} />
                {/if}
            {/if}
            </div>
        </div>
    </div>
    </div>
</div>

<CommandPalette on:refresh={() => fetchStats(true)} on:toast={e => showToast(e.detail)} />
<Toast message={toastMsg} />
<WebLinkDialog />

<style>
    @media (max-width: 640px) {
    }
</style>
