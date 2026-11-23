<script>
    import { onMount } from 'svelte';
    import { Thermometer, HardDrive, Plug, BatteryWarning } from 'lucide-svelte';
    import { visible } from '../../lib/stores.js';

    // Temperatures, drive health (SMART) and the power source of one host.
    // hid: null for this server, else another host's id (from its agent's inventory)
    export let hid = null;
    export let name = '';
    export let agentOld = false;   // its agent predates hardware reports

    let hw = null;
    async function load() {
        try {
            const j = await fetch(hid ? `/api/hardware/${encodeURIComponent(hid)}` : '/api/hardware').then(r => r.json());
            if (j.status === 'success') hw = j.data;
        } catch (e) {}
    }
    $: hid, load();
    onMount(() => { const t = setInterval(() => visible() && load(), 30000); return () => clearInterval(t); });

    const tone = (c, limit) => c == null ? '' : c >= limit ? 'bad' : c >= limit - 10 ? 'warn' : 'ok';
    const DRIVE = { ok: ['ok', 'Healthy'], warn: ['warn', 'Bad sectors'], failing: ['bad', 'Failing'], unknown: ['', 'Not reported'] };
    const hours = (h) => h >= 24 * 365 ? `${(h / 24 / 365).toFixed(1)} years on` : h >= 48 ? `${Math.round(h / 24)} days on` : `${h} h on`;
    $: t = hw?.temps;
    $: rows = hw ? [
        ...(t?.cpu != null ? [{ icon: Thermometer, name: 'CPU', sub: `Hottest of ${t.sensors.length} sensor${t.sensors.length === 1 ? '' : 's'}`, value: `${Math.round(t.cpu)} °C`, tone: tone(t.cpu, hw.warn.cpu), title: t.sensors.map(s => `${s.name}: ${s.c} °C`).join('\n') }] : []),
        ...(t?.ssd != null ? [{ icon: Thermometer, name: 'SSD', sub: 'Flash storage', value: `${Math.round(t.ssd)} °C`, tone: tone(t.ssd, hw.warn.ssd) }] : []),
        ...(hw.drives || []).map(d => ({ icon: HardDrive, name: d.name, tone: DRIVE[d.health]?.[0] ?? '', value: DRIVE[d.health]?.[1] ?? '—',
            sub: [d.internal === true ? 'Internal' : d.internal === false ? 'External' : null, d.bus, d.temp != null ? `${d.temp} °C` : null,
                  d.hours != null ? hours(d.hours) : null, d.wear != null ? `${d.wear}% worn` : null, d.health !== 'ok' ? d.detail : null].filter(Boolean).join(' · ') })),
        ...(hw.power?.source ? (hw.power.ups?.length ? hw.power.ups.map(u => ({
            icon: hw.power.source === 'ups' ? BatteryWarning : Plug, name: u.name, tone: hw.power.source === 'ups' ? 'bad' : 'ok',
            value: hw.power.source === 'ups' ? 'On battery' : 'On mains',
            sub: ['UPS', u.pct != null ? `${u.pct}% charged` : null, u.remaining ? `${u.remaining} left` : null, u.state].filter(Boolean).join(' · ') }))
            : [{ icon: Plug, name: 'Power', sub: 'No UPS connected', value: hw.power.source === 'battery' ? 'On battery' : 'On mains', tone: hw.power.source === 'battery' ? 'warn' : 'ok' }]) : []),
    ] : [];
    $: unknownExternal = (hw?.drives || []).some(d => d.health === 'unknown');
</script>

<section class="ui-card">
    <div class="ui-card-head">
        <div>
            <h2 class="ui-card-title">Hardware</h2>
            <p class="ui-card-desc">Temperatures, drive health and power.
                {#if !hid && hw && !hw.smartctl && unknownExternal}For USB drives' health and wear, install smartmontools: <span class="ui-mono">brew install smartmontools</span>.{/if}</p>
        </div>
    </div>
    {#if !hw}
        <div class="ui-empty">Reading…</div>
    {:else if !rows.length}
        <div class="ui-empty">{agentOld ? `Update ${name}'s agent (⋯ → Update agent) so it reports temperatures, drive health and UPS power.` : 'Nothing reported yet.'}</div>
    {:else}
        <div class="hw">
            {#each rows as r}
                <div class="hw-r" title={r.title || null}>
                    <span class="ic"><svelte:component this={r.icon} size={15} /></span>
                    <span class="n"><b>{r.name}</b>{#if r.sub}<small>{r.sub}</small>{/if}</span>
                    <span class="v {r.tone}"><i></i>{r.value}</span>
                </div>
            {/each}
        </div>
    {/if}
</section>

<style>
    .hw { border-top: 1px solid var(--border); }
    .hw-r { display: grid; grid-template-columns: 30px minmax(0, 1fr) auto; gap: 0 14px; align-items: center; padding: 11px 20px; border-bottom: 1px solid var(--border); font-size: 13px; }
    .hw-r:last-child { border-bottom: none; }
    .ic { width: 30px; height: 30px; border-radius: var(--radius-card, 8px); display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); }
    .n { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .n b { font-weight: 600; }
    .n small { font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .v { display: inline-flex; align-items: center; gap: 6px; font-weight: 500; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .v i { width: 7px; height: 7px; border-radius: 50%; background: var(--highlight-30); }
    .v.ok i { background: var(--green); }
    .v.warn i { background: var(--amber); }
    .v.bad { color: var(--red); }
    .v.bad i { background: var(--red); }
    @media (max-width: 768px) { .hw-r { padding-left: 14px; padding-right: 14px; } }
</style>
