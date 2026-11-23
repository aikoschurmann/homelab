<script>
    import { SN } from '../../lib/server.js';
    // One drive, the way a person thinks of it: its volume's name, the hardware in plain
    // words, how full it is. Plumbing (device ids, mount paths) stays in the hover title.
    import { HardDrive, Lock } from 'lucide-svelte';

    export let d;                       // a drive from /api/storage/disks
    export let fmt = (b) => String(b);  // byte formatter
    export let onEject = null;          // shown for external drives
    export let onMount = null;          // shown when a volume isn't mounted
    export let host = SN;        // whose drive it is, for internal ones

    // "PSSD T7" → "Samsung T7", "APPLE SSD AP0256Z" → "Built-in Apple SSD"
    function model(name, internal) {
        if (/^apple ssd/i.test(name)) return 'Built-in Apple SSD';
        if (/pssd\s*t(\d)/i.test(name)) return 'Samsung T' + name.match(/pssd\s*t(\d)/i)[1];
        if (/^disk image$/i.test(name)) return 'Disk image';
        return name.replace(/\s+/g, ' ').trim() || (internal ? 'Internal drive' : 'External drive');
    }
    const FORMAT_NOTE = { exfat: 'exFAT: also works on Windows', apfs: 'APFS: Mac only', msdos: 'FAT32: works everywhere, 4 GB file limit', ntfs: 'NTFS: read-only on a Mac' };
    const pct = (a, b) => b ? Math.min(100, Math.max(0, (a / b) * 100)) : 0;

    $: v = d.volumes[0] || {};
    $: title = v.name || model(d.name, d.internal);
    // usable size of the main volume, so it matches the totals elsewhere (the raw disk adds recovery partitions)
    $: sub = [model(d.name, d.internal), !d.internal && d.protocol && !d.image ? d.protocol : '', fmt(d.volumes?.[0]?.size || d.size)].filter(Boolean).join(' · ');
    $: mounted = d.volumes.some(x => x.mounted);
    $: note = FORMAT_NOTE[(v.format || '').toLowerCase()] || v.format || '';
    $: hover = [d.id, ...d.volumes.map(x => `${x.id} ${x.format || ''} ${x.mount_point || 'not mounted'}`)].join('\n');
</script>

<div class="drive" class:off={!mounted} title={hover}>
    <div class="dh">
        <span class="ic"><HardDrive size={18} /></span>
        <div class="dt">
            <b>{title}{#if d.protected}<span class="lock" title="Protected: this drive won't be erased"><Lock size={12} /></span>{/if}</b>
            <small>{sub}</small>
        </div>
        {#if !mounted}<span class="pill">Not mounted</span>{/if}
    </div>

    {#if mounted && v.size}
        <div class="use">
            <div class="nums"><span><b>{fmt(v.used)}</b> used</span><span><b>{fmt(v.free)}</b> free</span></div>
            <div class="bar"><i style="width: {pct(v.used, v.size)}%"></i></div>
        </div>
        {#each d.volumes.slice(1).filter(x => x.mounted && x.size) as x}
            <div class="more"><span>{x.name}</span><span>{fmt(x.used)} of {fmt(x.size)}</span></div>
        {/each}
    {/if}

    <div class="df">
        <span class="note">{d.internal ? `Inside ${host}` : note}</span>
        {#if !mounted && onMount}<button class="ui-btn sm" on:click={() => onMount(d)}>Mount</button>
        {:else if d.ejectable && onEject}<button class="ui-btn sm" on:click={() => onEject(d)}>Eject</button>{/if}
    </div>
</div>

<style>
    .drive { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; display: flex; flex-direction: column; min-width: 0; }
    .dh { display: flex; align-items: center; gap: 12px; padding: 16px 18px 6px; }
    .ic { width: 38px; height: 38px; border-radius: 9px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--accent-soft); color: var(--accent); }
    .off .ic { background: var(--highlight-10); color: var(--text-secondary); }
    .dt { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
    .dt b { display: flex; align-items: center; gap: 7px; font-size: 15px; font-weight: 600; color: var(--text-primary); }
    .dt small { font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .lock { display: inline-flex; color: var(--text-secondary); }
    .pill { height: 22px; padding: 0 8px; border-radius: 11px; display: inline-flex; align-items: center; font-size: 12px; font-weight: 500; background: var(--highlight-10); color: var(--text-secondary); white-space: nowrap; }
    .use { padding: 12px 18px 16px; display: flex; flex-direction: column; gap: 8px; }
    .nums { display: flex; justify-content: space-between; font-size: 13px; color: var(--text-secondary); }
    .nums b { font-size: 18px; font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; margin-right: 3px; letter-spacing: -0.01em; }
    .bar { height: 8px; border-radius: 4px; background: var(--highlight-15); overflow: hidden; }
    .bar i { display: block; height: 100%; border-radius: 4px; background: var(--text-secondary); transition: width .4s ease; }
    .more { display: flex; justify-content: space-between; padding: 0 18px 10px; font-size: 12.5px; color: var(--text-secondary); }
    .df { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 46px; padding: 0 18px; margin-top: auto; border-top: 1px solid var(--border); background: var(--highlight-3); border-radius: 0 0 10px 10px; }
    .note { font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
