<script>
    import { onMount } from 'svelte';
    import { visible } from '../../lib/stores.js';
    import PairGrid from '../ui/PairGrid.svelte';

    // Temperatures, drive health (SMART) and the power source of one host, in the same
    // two-column grid as Details. hid: null for this server, else another host's id.
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

    const HEALTH = { ok: 'Healthy', warn: 'Bad sectors', failing: 'Failing' };
    const hours = (h) => h >= 24 * 365 ? `${(h / 24 / 365).toFixed(1)} yrs on` : `${Math.round(h / 24)} days on`;
    const deg = (c) => `${Math.round(c)} °C`;
    $: t = hw?.temps;
    $: left = hw ? [
        t?.cpu != null && { k: 'CPU', v: deg(t.cpu), bad: t.cpu >= hw.warn.cpu, title: t.sensors.map(s => `${s.name}: ${s.c} °C`).join('\n') },
        t?.ssd != null && { k: 'SSD', v: deg(t.ssd), bad: t.ssd >= hw.warn.ssd },
        ...(t ? [] : [{ k: 'Temperatures', v: 'Not reported' }]),
    ].filter(Boolean) : [];
    $: drives = (hw?.drives || []).map(d => ({
        k: d.internal ? 'Internal drive' : d.name,
        v: d.health === 'unknown'
            ? (hid || hw.smartctl ? 'Health not reported' : 'Not reported over USB')
            : [HEALTH[d.health], d.temp != null ? deg(d.temp) : null, d.wear != null ? `${d.wear}% worn` : null, d.hours != null ? hours(d.hours) : null].filter(Boolean).join(' · '),
        bad: d.health === 'failing' || d.health === 'warn',
        title: [d.name, d.bus, d.detail, d.health === 'unknown' && !hid && !hw.smartctl ? 'brew install smartmontools reads health over USB' : null].filter(Boolean).join('\n'),
    }));
    $: power = hw?.power?.source ? (hw.power.ups?.length
        ? hw.power.ups.map(u => ({ k: 'UPS', v: [hw.power.source === 'ups' ? 'On battery' : 'On mains', u.pct != null ? `${u.pct}%` : null, u.remaining ? `${u.remaining} left` : null].filter(Boolean).join(' · '), bad: hw.power.source === 'ups', title: u.name }))
        : [{ k: 'Power', v: hw.power.source === 'battery' ? 'On battery' : 'Mains, no UPS' }]) : [];
    $: right = [...drives, ...power];
    $: rows = Array.from({ length: Math.max(left.length, right.length) }, (_, i) => [left[i] || null, right[i] || null]);
    $: empty = hw && !t && !(hw.drives || []).length && !hw.power;
</script>

<section class="ui-card">
    <div class="ui-card-head"><div><h2 class="ui-card-title">Hardware health</h2><p class="ui-card-desc">Temperatures, drives and power, read every 30 s.</p></div></div>
    {#if !hw}
        <div class="ui-empty">Reading…</div>
    {:else if empty}
        <div class="ui-empty">{agentOld ? `Update ${name}'s agent (⋯ → Update agent) so it reports temperatures, drive health and UPS power.` : 'Nothing reported yet.'}</div>
    {:else}
        <PairGrid {rows} heads={['Temperatures', 'Drives and power']} />
    {/if}
</section>
