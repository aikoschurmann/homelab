<script>
    import { SN, server, saveServer } from '../lib/server.js';
    import { onMount } from 'svelte';
    import { Loader2, Send, ExternalLink, Check, Trash2, Server, Box, ChevronRight, User } from 'lucide-svelte';
    import { vmRef } from '../lib/vmref.js';
    import { presetOf, permSummary } from '../lib/perms.js';
    import Stepper from './Stepper.svelte';
    import AppearancePicker from './ui/AppearancePicker.svelte';
    import Tabs from './ui/Tabs.svelte';
    import BackupSettings from './BackupSettings.svelte';
    import { machines } from '../lib/stores.js';
    import { hosts, hostOrder, byOrder } from '../lib/hosts.js';

    export let stats = null;
    export let pollIntervalMs = 5000;
    export let section = null;
    export let onNavigate = () => {};

    const TABS = [{ id: 'general', label: 'General' }, { id: 'alerts', label: 'Alerts' }, { id: 'backups', label: 'Backups' }, { id: 'sharing', label: 'Sharing' },
        { id: 'data', label: 'Data' }, { id: 'integrations', label: 'Integrations' }, { id: 'hosts', label: 'Hosts & machines' }];
    // old section links (#settings/appearance, …) land on the tab that now holds them
    const OLD = { appearance: 'general', polling: 'general', tailscale: 'integrations' };
    // the network tools are a page of their own now
    $: if (section === 'tools' || section === 'network') onNavigate('Tools');
    $: tab = TABS.some(t => t.id === section) ? section : OLD[section] || 'general';

    const toast = (m) => window.showToast?.(m);
    const post = (url, body, method = 'POST') => fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body && JSON.stringify(body) }).then(r => r.json());

    // ---- this server: name and port (server.json) ------------------------------------------
    let srvName = server.name, srvPort = server.port, srvSaving = false;
    async function saveSrv() {
        srvSaving = true;
        try {
            const d = await saveServer({ name: srvName, port: Number(srvPort) });
            if (d.restart_needed) toast(`Saved. The new port applies after the dashboard restarts`);
            else location.reload();      // the name is read once at load
        } catch (e) { toast(e.message); }
        srvSaving = false;
    }

    // ---- data refresh -------------------------------------------------------------------
    let dbPoll = 10;
    async function setDbPoll(v) {
        dbPoll = v;
        try { await post('/api/prefs', { db_poll_interval: v }); toast('Database telemetry rate saved'); } catch (e) {}
    }

    // ---- alerts -------------------------------------------------------------------------
    const KINDS = [
        ['daemon', 'Mac apps', 'A watched app on the Mac stops'],
        ['container', 'Containers', 'A container stops'],
        ['health', 'Health checks', 'A container turns unhealthy'],
        ['host', 'Hosts', 'Another computer stops reporting in'],
        ['machine', 'Dashboard VM', 'The containers machine goes down'],
        ['disk', 'Disk space', 'A disk passes the threshold'],
        ['drive', 'External drives', 'A drive is unplugged or unmounted'],
        ['backup', 'Backups', 'A backup is overdue or incomplete'],
    ];
    const allKinds = () => Object.fromEntries(KINDS.map(([k]) => [k, true]));
    let alerts = { enabled: false, discord: '', ntfy: '', disk: 90, kinds: allKinds(), repeat: 6, grace: 60, resolved: true, actions: true, quiet: false, qFrom: 23, qTo: 8 };
    const HOURS = Array.from({ length: 24 }, (_, h) => h);
    const hh = (h) => String(h).padStart(2, '0') + ':00';
    let saved = null;            // last saved copy, to know when there are changes
    let alertsTesting = false, alertsState = '';   // '' | 'saving' | 'saved' | 'error'
    $: dirty = saved && JSON.stringify(alerts) !== JSON.stringify(saved);
    $: hasChannel = alerts.discord.trim() || alerts.ntfy.trim();
    // alerts save themselves shortly after the last edit, like every other setting here
    let saveTimer;
    // the "Saved" note shows in whichever card holds the setting that changed
    const CARD = { enabled: 'main', discord: 'main', ntfy: 'main', kinds: 'report', resolved: 'report', actions: 'report',
                   disk: 'timing', repeat: 'timing', grace: 'timing', quiet: 'timing', qFrom: 'timing', qTo: 'timing' };
    let saveCard = null, savedTimer;
    $: if (dirty) {
        const k = Object.keys(alerts).find(k => JSON.stringify(alerts[k]) !== JSON.stringify(saved[k]));
        if (k) saveCard = CARD[k];
        clearTimeout(saveTimer); saveTimer = setTimeout(saveAlerts, 700);
    }
    async function saveAlerts() {
        clearTimeout(saveTimer);
        alertsState = 'saving';
        const sent = structuredClone(alerts);
        try {
            const r = await post('/api/prefs', {
                alerts_enabled: sent.enabled,
                alerts_discord_webhook: sent.discord.trim(),
                alerts_ntfy_url: sent.ntfy.trim(),
                alerts_disk_threshold: Math.min(99, Math.max(50, parseInt(sent.disk) || 90)),
                alerts_kinds: sent.kinds,
                alerts_repeat_hours: sent.repeat,
                alerts_host_grace: sent.grace,
                alerts_notify_resolved: sent.resolved,
                alerts_notify_actions: sent.actions,
                alerts_quiet: sent.quiet ? [sent.qFrom, sent.qTo] : null,
            });
            if (r.status === 'success') { saved = sent; alertsState = 'saved'; clearTimeout(savedTimer); savedTimer = setTimeout(() => alertsState = alertsState === 'saved' ? '' : alertsState, 2500); }
            else { alertsState = 'error'; toast(r.message || 'Could not save alert settings'); }
        } catch (e) { alertsState = 'error'; toast('Could not save alert settings'); }
    }
    async function testAlerts() {
        alertsTesting = true;
        if (dirty) await saveAlerts();
        try {
            const r = await post('/api/alerts/test');
            toast(r.status === 'success' ? `Test sent via ${r.channels.join(' and ')}` : (r.message || 'Test failed'));
        } catch (e) { toast('Test failed'); }
        alertsTesting = false;
    }

    // ---- tailscale key (stored on the Mac; the browser only learns whether one is set) -----
    let tsKey = { set: false, hint: '' };
    let tsInput = '', tsSaving = false, confirmRemove = false;
    async function loadTsKey() {
        try { const j = await fetch('/api/vms/tailscale/key').then(r => r.json()); if (j.status === 'success') tsKey = j.data; } catch (e) {}
    }
    async function saveTsKey() {
        tsSaving = true;
        try {
            const j = await post('/api/vms/tailscale/key', { auth_key: tsInput.trim() }, 'PUT');
            toast(j.status === 'success' ? 'Tailscale key saved' : (j.message || 'Could not save key'));
            if (j.status === 'success') { tsInput = ''; await loadTsKey(); }
        } catch (e) { toast('Could not save key'); }
        tsSaving = false;
    }
    async function removeTsKey() {
        confirmRemove = false;
        try { await fetch('/api/vms/tailscale/key', { method: 'DELETE' }); await loadTsKey(); toast('Tailscale key removed'); } catch (e) {}
    }

    // ---- cloudflare token (public SSH sharing) -----------------------------------------------
    let cf = { set: false, hint: '', domain: '' };
    let cfInput = '', cfSaving = false, cfConfirm = false;
    async function loadCf() {
        try { const j = await fetch('/api/vms/cloudflare/token').then(r => r.json()); if (j.status === 'success') cf = j.data; } catch (e) {}
    }
    async function saveCf() {
        cfSaving = true;
        try {
            const j = await post('/api/vms/cloudflare/token', { api_token: cfInput.trim() }, 'PUT');
            toast(j.status === 'success' ? 'Cloudflare token saved' : (j.message || 'Could not save token'));
            if (j.status === 'success') { cfInput = ''; await loadCf(); }
        } catch (e) { toast('Could not save token'); }
        cfSaving = false;
    }
    async function removeCf() {
        cfConfirm = false;
        try { await fetch('/api/vms/cloudflare/token', { method: 'DELETE' }); await loadCf(); toast('Cloudflare token removed'); } catch (e) {}
    }

    // ---- Hosts & machines: every computer, its machines and their people, with what's set now
    const gbOf = (mib) => +(mib / 1024).toFixed(1) + ' GB';
    const cores = (n) => `${n} ${n === 1 ? 'core' : 'cores'}`;
    function machineVals(m) {
        return [
            m.cpu ? cores(m.cpu) : 'pool CPU',
            m.memory_mib ? gbOf(m.memory_mib) : 'pool memory',
            m.disk_bytes ? `${Math.round(m.disk_bytes / 2 ** 30)} GB disk` : 'no disk limit',
        ].join(' · ');
    }
    function machineRows(list, hid) {
        return [...(list || [])].sort((a, b) => a.name.localeCompare(b.name)).flatMap(m => {
            const ref = vmRef(hid, m.name), base = `#infra/vm-${encodeURIComponent(ref)}`;
            const flags = [m.isolated ? (m.isolate_network ? 'isolated, network too' : 'isolated') : 'sees your Mac', m.share && 'shared over SSH'].filter(Boolean);
            return [
                { level: 1, icon: Box, name: m.name, kind: 'Machine', vals: machineVals(m), flags, warn: !m.isolated, href: `${base}/settings` },
                ...(m.share?.keys || []).filter(k => k.perms).map(k => ({
                    level: 2, icon: User, name: k.user, kind: 'Person', href: `${base}/person-${k.user}`,
                    vals: (presetOf(k.perms, schema)?.label || 'Custom') + ' · ' + permSummary(k.perms, schema), flags: k.perms.expires ? [`until ${k.perms.expires}`] : [],
                })),
            ];
        });
    }
    $: places = byOrder([
        { id: 'arrakis', rows: [
            { level: 0, icon: Server, name: SN, kind: 'This server', href: '#infra/arrakis/settings',
              vals: $machines?.pool ? `OrbStack pool ${cores($machines.pool.cpu)} · ${gbOf($machines.pool.memory_mib)}` : 'OrbStack' },
            ...machineRows($machines?.machines, null),
        ] },
        ...($hosts || []).map(h => ({ id: h.id, rows: [
            { level: 0, icon: Server, name: h.name, kind: 'Host', href: `#infra/${h.id}/settings`,
              vals: [h.report?.agent ? `agent ${h.report.agent}` : 'agent',
                     h.orb_manage ? (h.vms?.pool ? `OrbStack pool ${cores(h.vms.pool.cpu)} · ${gbOf(h.vms.pool.memory_mib)}` : 'OrbStack managed')
                       : h.caps?.orbstack ? 'OrbStack not managed' : 'no OrbStack'].join(' · ') },
            ...(h.orb_manage ? machineRows(h.vms?.machines, h.id) : []),
        ] })),
    ], $hostOrder).flatMap(g => g.rows);

    // ---- how long history is kept ---------------------------------------------------------
    let keep = null, keepSaved = null, keepSaving = false;
    async function loadKeep() {
        try { const j = await fetch('/api/retention').then(r => r.json()); if (j.status === 'success') { keepSaved = j.data; keep = j.data.map(x => ({ ...x })); } } catch (e) {}
    }
    $: keepDirty = keep && keepSaved && keep.some((x, i) => x.days !== keepSaved[i].days);
    $: keepShrinks = keep && keepSaved && keep.filter((x, i) => x.days < keepSaved[i].days).map(x => x.label.split(' (')[0]);
    async function saveKeep() {
        keepSaving = true;
        const r = await post('/api/retention', Object.fromEntries(keep.map(x => [x.id, x.days])), 'PATCH');
        keepSaving = false;
        if (r?.status === 'success') { toast('Saved'); loadKeep(); } else toast(r?.message || 'Could not save');
    }
    const fmtRows = (n) => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'k' : String(n || 0);

    // ---- sharing domain + presets ---------------------------------------------------------
    let domainPick = '', domainSaving = false;
    $: if (cf.domain && !domainPick) domainPick = cf.domain;
    async function saveDomain() {
        domainSaving = true;
        const r = await post('/api/vms/cloudflare/domain', { domain: domainPick }, 'PUT');
        domainSaving = false;
        if (r?.status === 'success') { toast(`Machines are now shared under ${domainPick}`); loadCf(); } else toast(r?.message || 'Could not change the domain');
    }
    let schema = null, presetBusy = null;
    async function loadPresets() {
        try { const j = await fetch('/api/vms').then(r => r.json()); schema = (j.data || j).sharing?.permissions; } catch (e) {}
    }
    async function delPreset(id) {
        presetBusy = id;
        const r = await post(`/api/vms/sharing/presets/${encodeURIComponent(id)}`, null, 'DELETE');
        presetBusy = null;
        if (r?.status === 'success') { toast('Preset deleted'); loadPresets(); } else toast(r?.message || 'Could not delete');
    }

    onMount(async () => {
        loadTsKey();
        loadCf();
        loadKeep();
        loadPresets();
        try {
            const j = await fetch('/api/prefs').then(r => r.json());
            if (j.status === 'success') {
                dbPoll = j.data.db_poll_interval || 10;
                alerts = {
                    enabled: !!j.data.alerts_enabled,
                    discord: j.data.alerts_discord_webhook || '',
                    ntfy: j.data.alerts_ntfy_url || '',
                    disk: j.data.alerts_disk_threshold || 90,
                    kinds: { ...allKinds(), ...(j.data.alerts_kinds || {}) },
                    repeat: j.data.alerts_repeat_hours ?? 6,
                    grace: j.data.alerts_host_grace ?? 60,
                    resolved: j.data.alerts_notify_resolved ?? true,
                    actions: j.data.alerts_notify_actions ?? true,
                    quiet: !!j.data.alerts_quiet,
                    qFrom: j.data.alerts_quiet?.[0] ?? 23,
                    qTo: j.data.alerts_quiet?.[1] ?? 8,
                };
                saved = structuredClone(alerts);
            }
        } catch (e) {}
    });
</script>

{#snippet saveNote(card)}
    {#if saveCard === card && (dirty || alertsState)}
        <span class="save-state" class:err={alertsState === 'error' && !dirty}>
            {#if dirty || alertsState === 'saving'}<Loader2 size={12} class="ui-spin" /> Saving…
            {:else if alertsState === 'error'}Not saved
            {:else if alertsState === 'saved'}<Check size={12} /> Saved{/if}
        </span>
    {/if}
{/snippet}

<div class="ui-page settings">
    <div class="ui-head">
        <div>
            <h1>Settings</h1>
            <p>How the dashboard looks, how often it refreshes, and where it sends alerts.</p>
        </div>
    </div>

    <Tabs tabs={TABS} active={tab} onSelect={(t) => onNavigate('Settings', t === 'general' ? null : t)} />

    {#if tab === 'general'}
    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">This server</h2><p class="ui-card-desc">Kept in <span class="ui-mono">{server.home}/server.json</span>.</p></div></div>
        <div class="rows">
            <div class="ui-form-row">
                <div><div class="ui-label">Name</div><div class="ui-hint">What the dashboard calls this computer</div></div>
                <input class="ui-input srv-name" bind:value={srvName} maxlength="40" />
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Port</div><div class="ui-hint">Applies after a restart{#if server.port_active && server.port_active !== server.port} · running on {server.port_active}{/if}</div></div>
                <input class="ui-input srv-port" type="number" min="1024" max="65535" bind:value={srvPort} />
            </div>
        </div>
        <div class="ui-card-foot"><span>{server.os} · {server.hostname}</span>
            <span class="ui-btns"><button class="ui-btn sm primary" disabled={srvSaving || !srvName.trim() || (srvName.trim() === server.name && Number(srvPort) === server.port)} on:click={saveSrv}>{srvSaving ? 'Saving…' : 'Save'}</button></span>
        </div>
    </section>

    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Appearance</h2><p class="ui-card-desc">Saved in this browser.</p></div></div>
        <AppearancePicker />
    </section>

    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Data refresh</h2><p class="ui-card-desc">Faster is livelier but costs the Mac a little more work.</p></div></div>
        <div class="rows">
            <div class="ui-form-row">
                <div><div class="ui-label">Dashboard updates</div><div class="ui-hint">When the live stream drops</div></div>
                <div class="ui-seg">
                    {#each [[1000, '1 s'], [5000, '5 s'], [15000, '15 s']] as [v, l]}<button class:on={pollIntervalMs === v} on:click={() => pollIntervalMs = v}>{l}</button>{/each}
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Database telemetry</div><div class="ui-hint">Sizes and row counts</div></div>
                <div class="ui-seg">
                    {#each [[10, '10 s'], [30, '30 s'], [60, '60 s']] as [v, l]}<button class:on={dbPoll === v} on:click={() => setDbPoll(v)}>{l}</button>{/each}
                </div>
            </div>
        </div>
    </section>

    {:else if tab === 'alerts'}
    <section class="ui-card">
        <div class="ui-card-head">
            <div><h2 class="ui-card-title">Alerts</h2><p class="ui-card-desc">Push messages when something on the homelab goes wrong.</p></div>
            <span class="head-end">
                {@render saveNote('main')}
                <label class="switch" title={alerts.enabled ? 'Alerts on' : 'Alerts off'}>
                    <input type="checkbox" bind:checked={alerts.enabled} />
                    <i></i>
                </label>
            </span>
        </div>
        <div class="rows" class:muted={!alerts.enabled}>
            <div class="ui-form-row">
                <div><label class="ui-label" for="a-discord">Discord webhook</label><div class="ui-hint">From the channel's settings</div></div>
                <input id="a-discord" class="ui-input mono" type="url" placeholder="https://discord.com/api/webhooks/…" bind:value={alerts.discord} />
            </div>
            <div class="ui-form-row">
                <div><label class="ui-label" for="a-ntfy">ntfy topic</label><div class="ui-hint">Phone push via the ntfy app</div></div>
                <input id="a-ntfy" class="ui-input mono" type="url" placeholder="https://ntfy.sh/arrakis-xxxxxxxx" bind:value={alerts.ntfy} />
            </div>
        </div>
        <div class="ui-card-foot">
            <span>{#if !hasChannel}Add Discord or ntfy to receive alerts{/if}</span>
            <button class="ui-btn sm" disabled={alertsTesting || !hasChannel} on:click={testAlerts}>{#if alertsTesting}<Loader2 size={13} class="ui-spin" />{:else}<Send size={13} />{/if} Send test</button>
        </div>
    </section>

    <section class="ui-card" class:muted={!alerts.enabled}>
        <div class="ui-card-head"><div><h2 class="ui-card-title">What to report</h2><p class="ui-card-desc">Click to turn a kind of message on or off.</p></div>{@render saveNote('report')}</div>
        <div class="chips-wrap">
            <div class="chip-group">
                <span class="chip-head">Problems</span>
                <div class="chips">
                    {#each KINDS as [k, label, desc]}
                        <button class="chip" class:on={alerts.kinds[k]} title={desc} aria-pressed={alerts.kinds[k]} on:click={() => alerts.kinds[k] = !alerts.kinds[k]}>{#if alerts.kinds[k]}<Check size={13} />{/if}{label}</button>
                    {/each}
                </div>
            </div>
            <div class="chip-group">
                <span class="chip-head">Also tell me about</span>
                <div class="chips">
                    <button class="chip" class:on={alerts.resolved} title="A message when a problem clears" aria-pressed={alerts.resolved} on:click={() => alerts.resolved = !alerts.resolved}>{#if alerts.resolved}<Check size={13} />{/if}Recoveries</button>
                    <button class="chip" class:on={alerts.actions} title="Starts, stops and restarts done from the dashboard" aria-pressed={alerts.actions} on:click={() => alerts.actions = !alerts.actions}>{#if alerts.actions}<Check size={13} />{/if}Dashboard actions</button>
                </div>
            </div>
        </div>
    </section>

    <section class="ui-card" class:muted={!alerts.enabled}>
        <div class="ui-card-head"><div><h2 class="ui-card-title">Timing</h2><p class="ui-card-desc">When to speak up, and how often.</p></div>{@render saveNote('timing')}</div>
        <div class="rows">
            <div class="ui-form-row">
                <div><div class="ui-label">Disk threshold</div><div class="ui-hint">How full a disk may get</div></div>
                <Stepper bind:value={alerts.disk} min={50} max={99} step={1} unit="%" />
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Host offline after</div><div class="ui-hint">No reports for this long</div></div>
                <div class="ui-seg">
                    {#each [[30, '30 s'], [60, '1 min'], [300, '5 min'], [900, '15 min']] as [v, l]}<button class:on={alerts.grace === v} on:click={() => alerts.grace = v}>{l}</button>{/each}
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Remind me</div><div class="ui-hint">While a problem is still there</div></div>
                <div class="ui-seg">
                    {#each [[0, 'Never'], [1, 'Hourly'], [6, '6 h'], [24, 'Daily']] as [v, l]}<button class:on={alerts.repeat === v} on:click={() => alerts.repeat = v}>{l}</button>{/each}
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Quiet hours</div><div class="ui-hint">{alerts.quiet ? `Held until ${hh(alerts.qTo)}, then sent` : 'Held back, sent when they end'}</div></div>
                <div class="inline">
                    <div class="ui-seg">
                        {#each [[false, 'Off'], [true, 'On']] as [v, l]}<button class:on={alerts.quiet === v} on:click={() => alerts.quiet = v}>{l}</button>{/each}
                    </div>
                    {#if alerts.quiet}
                        <select class="ui-input hour" bind:value={alerts.qFrom}>{#each HOURS as h}<option value={h}>{hh(h)}</option>{/each}</select>
                        <span class="to">to</span>
                        <select class="ui-input hour" bind:value={alerts.qTo}>{#each HOURS as h}<option value={h}>{hh(h)}</option>{/each}</select>
                    {/if}
                </div>
            </div>
        </div>
    </section>

    {:else if tab === 'backups'}
    <BackupSettings />

    {:else if tab === 'sharing'}
    <section class="ui-card" data-setting="sharing-domain">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Domain</h2><p class="ui-card-desc">Shared machines get an address under this domain.</p></div></div>
        {#if !cf.set}<div class="ui-empty">Save a Cloudflare API token in <button class="ui-link" on:click={() => onNavigate('Settings', 'integrations')}>Integrations</button> first.</div>{/if}
        {#if cf.set}
            <div class="rows">
                <div class="ui-form-row">
                    <div><div class="ui-label">Domain</div><div class="ui-hint">Shared machines are named &lt;machine&gt;.{cf.domain}</div></div>
                    <div class="col-ctl">
                        <div class="inline">
                            <select class="ui-select" bind:value={domainPick} disabled={cf.domain_locked}>
                                {#each (cf.zones?.length ? cf.zones : [cf.domain]) as z}<option value={z}>{z}</option>{/each}
                            </select>
                            {#if domainPick !== cf.domain}<button class="ui-btn primary" disabled={domainSaving} on:click={saveDomain}>{domainSaving ? 'Saving…' : 'Use it'}</button>{/if}
                        </div>
                        {#if cf.domain_locked}<div class="ui-hint">Locked while machines are shared: their addresses are under {cf.domain}.</div>
                        {:else if cf.zones_error}<div class="ui-hint warn-txt">Couldn't list the token's domains: {cf.zones_error}</div>{/if}
                    </div>
                </div>
            </div>
        {/if}
    </section>

    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Sharing presets</h2><p class="ui-card-desc">Starting points when you add someone to a machine. Save your own from a person's page.</p></div></div>
        {#if !schema}<div class="ui-empty">Loading…</div>
        {:else}
            <div class="plist">
                {#each schema.presets as pr (pr.id)}
                    <div class="prow" title={pr.desc || ''}>
                        <span class="pn">{pr.label}</span>
                        <span class="ps">{permSummary(pr.perms, schema)}{pr.expires_days ? ` · access for ${pr.expires_days} days` : ''}{#if pr.custom && pr.desc}<span class="pd">{pr.desc}</span>{/if}</span>
                        {#if pr.custom}<button class="px" title="Delete preset" aria-label="Delete {pr.label}" disabled={presetBusy === pr.id} on:click={() => delPreset(pr.id)}><Trash2 size={14} /></button>{/if}
                    </div>
                {/each}
            </div>
        {/if}
    </section>

    {:else if tab === 'data'}
    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">History kept</h2><p class="ui-card-desc">How far back graphs and forecasts can look. Older readings are deleted from metrics.db.</p></div></div>
        <div class="rows">
            {#if !keep}<div class="ui-empty">Loading…</div>
            {:else}
                {#each keep as k}
                    <div class="ui-form-row">
                        <div><div class="ui-label">{k.label.split(' (')[0]}</div><div class="ui-hint">{fmtRows(k.rows)} readings{k.label.includes('(') ? ' · ' + k.label.split('(')[1].replace(')', '') : ''}</div></div>
                        <Stepper bind:value={k.days} min={1} max={k.max} step={1} unit={k.days === 1 ? 'day' : 'days'} />
                    </div>
                {/each}
            {/if}
        </div>
        {#if keepDirty}
            <div class="ui-card-foot">
                <span class:warn-txt={keepShrinks.length}>{keepShrinks.length ? `Saving deletes older ${keepShrinks.join(', ').toLowerCase()} history right away.` : 'Unsaved changes'}</span>
                <span class="ui-btns"><button class="ui-btn sm" on:click={() => keep = keepSaved.map(x => ({ ...x }))}>Reset</button><button class="ui-btn sm primary" disabled={keepSaving} on:click={saveKeep}>{keepSaving ? 'Saving…' : 'Save'}</button></span>
            </div>
        {/if}
    </section>

    {:else if tab === 'hosts'}
    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Hosts & machines</h2><p class="ui-card-desc">Each computer, machine and person has its own settings page. This is what's set on each right now; open a row to change it.</p></div></div>
        <div class="pl">
            <div class="pl-head"><span>Name</span><span>Set now</span></div>
            {#each places as r (r.href)}
                <a class="pl-row lv{r.level}" class:top={r.level === 0} href={r.href}>
                    <span class="pl-name"><span class="pl-ic"><svelte:component this={r.icon} size={14} /></span><span class="pl-nm">{r.name}</span><span class="pl-kind">{r.kind}</span></span>
                    <span class="pl-vals">{r.vals}{#each r.flags || [] as f, i}{' · '}<span class:pl-warn={r.warn && i === 0}>{f}</span>{/each}</span>
                    <ChevronRight size={14} class="pl-go" />
                </a>
            {/each}
        </div>
    </section>

    {:else if tab === 'integrations'}
    <section class="ui-card">
        <div class="ui-card-head">
            <div><h2 class="ui-card-title">Tailscale auth key</h2><p class="ui-card-desc">Lets a machine join your tailnet in one click. Stored on the Mac, never sent back to the browser.</p></div>
            {#if tsKey.set}<span class="keytag">Key set · …{tsKey.hint}</span>{:else}<span class="keytag none">No key</span>{/if}
        </div>
        <div class="rows">
            <div class="ui-form-row">
                <div><label class="ui-label" for="ts-key">{tsKey.set ? 'Replace key' : 'Auth key'}</label>
                    <div class="ui-hint">Reusable, tagged <code>tag:vm</code></div></div>
                <div class="inline">
                    <input id="ts-key" class="ui-input mono" type="password" placeholder="tskey-auth-…" autocomplete="off" bind:value={tsInput} />
                    <button class="ui-btn primary" disabled={tsSaving || !tsInput.trim().startsWith('tskey-')} on:click={saveTsKey}>{tsSaving ? 'Saving…' : 'Save'}</button>
                </div>
            </div>
        </div>
        <div class="ui-card-foot">
            <a class="ui-link" href="https://login.tailscale.com/admin/settings/keys" target="_blank" rel="noopener noreferrer">Generate a key in the Tailscale admin console <ExternalLink size={12} /></a>
            {#if tsKey.set}
                <span class="ui-btns">
                    {#if confirmRemove}
                        <button class="ui-btn sm" on:click={() => confirmRemove = false}>Keep</button>
                        <button class="ui-btn sm danger" on:click={removeTsKey}>Remove key</button>
                    {:else}
                        <button class="ui-btn sm danger-outline" on:click={() => confirmRemove = true}>Remove</button>
                    {/if}
                </span>
            {/if}
        </div>
    </section>


    <section class="ui-card">
        <div class="ui-card-head">
            <div><h2 class="ui-card-title">Cloudflare API token</h2><p class="ui-card-desc">Lets machines be shared over public SSH{cf.domain ? ` at <name>.${cf.domain}` : ''}. Stored on the Mac, never sent back to the browser.</p></div>
            {#if cf.set}<span class="keytag">Token set · …{cf.hint}</span>{:else}<span class="keytag none">No token</span>{/if}
        </div>
        <div class="rows">
            <div class="ui-form-row">
                <div><label class="ui-label" for="cf-token">{cf.set ? 'Replace token' : 'API token'}</label>
                    <div class="ui-hint">Tunnel Edit + DNS Edit</div></div>
                <div class="inline">
                    <input id="cf-token" class="ui-input mono" type="password" placeholder="Paste token" autocomplete="off" bind:value={cfInput} />
                    <button class="ui-btn primary" disabled={cfSaving || cfInput.trim().length < 30} on:click={saveCf}>{cfSaving ? 'Checking…' : 'Save'}</button>
                </div>
            </div>
        </div>
        <div class="ui-card-foot">
            <a class="ui-link" href="https://dash.cloudflare.com/profile/api-tokens" target="_blank" rel="noopener noreferrer">Create a token in the Cloudflare dashboard <ExternalLink size={12} /></a>
            {#if cf.set}
                <span class="ui-btns">
                    {#if cfConfirm}
                        <button class="ui-btn sm" on:click={() => cfConfirm = false}>Keep</button>
                        <button class="ui-btn sm danger" on:click={removeCf}>Remove token</button>
                    {:else}
                        <button class="ui-btn sm danger-outline" on:click={() => cfConfirm = true}>Remove</button>
                    {/if}
                </span>
            {/if}
        </div>
    </section>

    {/if}
</div>

<style>
    .rows { border-top: 1px solid var(--border); }
    .rows.muted, .ui-card.muted { opacity: 0.55; }
    .chips-wrap { display: flex; flex-direction: column; gap: 16px; padding: 4px 20px 20px; }
    .chip-group { display: flex; flex-direction: column; gap: 8px; }
    .chip-head { font-size: 12px; font-weight: 500; color: var(--text-secondary); }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 12px; border-radius: 15px; border: 1px solid var(--border-strong); color: var(--text-secondary); font-size: 13px; font-weight: 500; cursor: pointer; background: transparent; }
    .chip:hover { color: var(--text-primary); border-color: var(--highlight-30); }
    .chip.on { background: var(--accent-soft); border-color: color-mix(in srgb, var(--accent) 45%, transparent); color: var(--text-primary); padding-left: 9px; }
    .chip.on :global(svg) { color: var(--accent); }
    .api code { font-family: 'JetBrains Mono', monospace; font-size: 12.5px; background: none; padding: 0; }
    .api .dim, .dim { color: var(--text-secondary); }
    .api .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .api .slow { color: var(--yellow); }
    .api .note { margin-left: 10px; font-size: 12px; color: var(--red); }
    .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 10px; background: var(--highlight-30); vertical-align: middle; }
    .dot.ok { background: var(--green); }
    .dot.bad { background: var(--red); }
    .inline .ui-input.port { flex: 0 0 90px; min-width: 0; }
    .res { font-size: 13px; color: var(--text-primary); font-variant-numeric: tabular-nums; }
    .res.err { color: var(--red); }
    .hour { width: 92px; }
    .to { color: var(--text-secondary); font-size: 13px; }
    .ui-form-row { align-items: center; }
    .ui-form-row .ui-input { max-width: 460px; }
    .inline { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .inline .ui-input { flex: 1; min-width: 200px; max-width: 460px; }
    code { font-family: 'JetBrains Mono', monospace; font-size: 11.5px; padding: 1px 4px; border-radius: 3px; background: var(--highlight-10); }

    .settings :global(.tabs) { margin-bottom: 4px; }

    .switch { position: relative; width: 40px; height: 22px; flex-shrink: 0; cursor: pointer; margin-top: 2px; }
    .switch input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; }
    .switch i { position: absolute; inset: 0; border-radius: 11px; background: var(--highlight-30); transition: background .15s; pointer-events: none; }
    .switch i::after { content: ''; position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.25); transition: transform .15s; }
    .switch input:checked + i { background: var(--accent-fill); }
    .switch input:checked + i::after { transform: translateX(18px); }

    .keytag { font-size: 12px; font-weight: 500; padding: 3px 9px; border-radius: 11px; background: rgba(63, 125, 92, 0.12); color: var(--green); white-space: nowrap; }
    .keytag.none { background: var(--highlight-10); color: var(--text-secondary); }
    .save-state { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; }
    .head-end { display: flex; align-items: center; gap: 14px; }
    .save-state.err, .err { color: var(--red); }
    .speed { display: flex; gap: 40px; padding: 16px 20px 20px; border-top: 1px solid var(--border); }
    .speed div { display: flex; flex-direction: column; gap: 4px; }
    .speed b { font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; }
    .speed small { color: var(--text-secondary); font-size: 12px; }
    .col-ctl { display: grid; gap: 6px; }
    .warn-txt { color: var(--red); }
    .plist { border-top: 1px solid var(--border); }
    .prow { display: grid; grid-template-columns: 220px minmax(0, 1fr) 28px; gap: 4px 24px; align-items: center; padding: 11px 20px; border-top: 1px solid var(--border); }
    .prow:first-child { border-top: none; }
    .pn { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
    .ps { font-size: 13px; color: var(--text-secondary); min-width: 0; }
    .pd { display: block; font-size: 12px; margin-top: 2px; opacity: .85; }
    .px { width: 28px; height: 28px; border-radius: 6px; display: grid; place-items: center; color: var(--text-secondary); cursor: pointer; }
    .px:hover { background: var(--highlight-10); color: var(--red); }
    @media (max-width: 640px) {
        .prow { grid-template-columns: minmax(0, 1fr) 28px; padding: 10px 14px; }
        .prow .ps { grid-column: 1; }
        .prow .px { grid-column: 2; grid-row: 1 / span 2; }
    }
    .pl { border-top: 1px solid var(--border); }
    .pl-head, .pl-row { display: grid; grid-template-columns: minmax(220px, 34%) minmax(0, 1fr) 16px; gap: 16px; align-items: center; padding: 9px 20px; }
    .pl-head { padding-top: 10px; padding-bottom: 8px; font-size: 11.5px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--text-secondary); border-bottom: 1px solid var(--border); }
    .pl-head span:last-child { grid-column: 2 / span 2; }
    .pl-row { text-decoration: none; color: inherit; border-top: 1px solid var(--border); }
    .pl-row.top:not(:first-of-type) { border-top: 1px solid var(--border); }
    .pl-row:hover { background: var(--highlight-3); }
    .pl-row:hover .pl-nm { color: var(--accent); }
    .pl-name { display: flex; align-items: center; gap: 10px; min-width: 0; }
    .lv1 .pl-name { padding-left: 24px; }
    .lv2 .pl-name { padding-left: 48px; }
    .pl-ic { display: inline-flex; color: var(--text-secondary); flex-shrink: 0; }
    .pl-nm { font-size: 13.5px; font-weight: 600; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .lv2 .pl-nm { font-weight: 500; }
    .pl-kind { font-size: 11.5px; color: var(--text-secondary); white-space: nowrap; }
    .pl-vals { font-size: 13px; color: var(--text-secondary); min-width: 0; }
    .pl-warn { color: var(--red); }
    .pl-row :global(.pl-go) { color: var(--text-secondary); opacity: .6; }
    @media (max-width: 700px) {
        .pl-head { display: none; }
        .pl-row { grid-template-columns: minmax(0, 1fr) 16px; gap: 4px 10px; padding: 10px 14px; }
        .pl-vals { grid-column: 1; padding-left: 24px; }
        .lv1 .pl-name, .lv1 .pl-vals { padding-left: 18px; } .lv1 .pl-vals { padding-left: 42px; }
        .lv2 .pl-name { padding-left: 36px; } .lv2 .pl-vals { padding-left: 60px; }
        .pl-row :global(.pl-go) { grid-column: 2; grid-row: 1 / span 2; }
    }
    kbd { font-family: 'JetBrains Mono', monospace; font-size: 11px; padding: 0 5px; border: 1px solid var(--border-strong); border-radius: 4px; }
    .srv-name { max-width: 320px; }
    .srv-port { max-width: 120px; }
</style>
