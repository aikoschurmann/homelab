<script>
    import { SN } from '../../lib/server.js';
    // A host's Storage tab: summary tiles, then one card per drive. Arrakis's and every
    // other host's, from /api/storage/disks or /api/hosts/<id>/storage (same shape).
    import { storageTotals } from '../../lib/storage.js';
    import { fmtDisk } from '../../lib/hosts.js';
    import DriveCard from '../ui/DriveCard.svelte';

    export let disks;                   // the drive list
    export let host = SN;
    export let onEject = null;
    export let onMount = null;
    export let hint = '';

    const pct = (a, b) => b ? Math.min(100, Math.max(0, (a / b) * 100)) : 0;
    $: st = storageTotals(disks);
    $: vols = disks.flatMap(d => d.volumes.filter(v => v.mounted && v.size).map(v => ({ v, d })));
</script>

<div class="ui-summary">
    <div class="ui-stat">
        <span class="ui-stat-label">Drives</span>
        <span class="ui-stat-value">{disks.length}</span>
        <span class="ui-stat-sub">{disks.filter(d => d.internal).length} internal · {disks.filter(d => !d.internal).length} external</span>
    </div>
    <div class="ui-stat">
        <span class="ui-stat-label">Capacity</span>
        <span class="ui-stat-value">{fmtDisk(st.size)}</span>
        <div class="ui-segbar">{#each vols as x, i}<i style="width: {pct(x.v.size, st.size)}%; background: var(--text-secondary); opacity: {i ? 0.45 : 1}"></i>{/each}</div>
        <span class="ui-stat-sub ui-legend">{#each vols as x, i}<span><b style="background: var(--text-secondary); opacity: {i ? 0.45 : 1}"></b>{x.v.name} {fmtDisk(x.v.size)}</span>{/each}</span>
    </div>
    <div class="ui-stat">
        <span class="ui-stat-label">Used</span>
        <span class="ui-stat-value">{fmtDisk(st.used)}<small>of {fmtDisk(st.size)}</small></span>
        <div class="ui-meter"><i style="width: {pct(st.used, st.size)}%; background: var(--text-secondary)"></i></div>
    </div>
    <div class="ui-stat">
        <span class="ui-stat-label">Free</span>
        <span class="ui-stat-value">{fmtDisk(st.free)}</span>
        <span class="ui-stat-sub">{fmtDisk(st.internal.free)} internal · {fmtDisk(st.external.free)} external</span>
    </div>
</div>
<div class="ui-cardgrid">
    {#each disks as d (d.id)}
        <DriveCard {d} {host} fmt={fmtDisk} {onEject} onMount={onMount && ((x) => x.volumes[0] && onMount(x.volumes[0]))} />
    {/each}
</div>
{#if hint}<p class="ui-hint" style="margin: 0">{hint}</p>{/if}
