<script>
    import { Box } from 'lucide-svelte';
    import { machines, machineUsage } from '../../lib/stores.js';
    import { href } from '../../lib/infra.js';
    import { SN } from '../../lib/server.js';
    import ResourceCard from '../ui/ResourceCard.svelte';

    // The OrbStack machines on this server as cards, the same as the host cards: CPU and
    // memory, and each opens its page. The Overview keeps machines and usage fresh.
    $: list = $machines?.machines || [];
    const gb = (b) => b == null ? '—' : b >= 2 ** 30 ? (b / 2 ** 30).toFixed(1) + ' GB' : Math.round(b / 2 ** 20) + ' MB';
    const pct = (a, b) => b ? Math.min(100, a / b * 100) : 0;
    const go = (to) => location.hash = to;
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
</script>

<div class="ui-cardgrid" id="sec-machines">
    {#each list as m (m.name)}
        {@const u = $machineUsage[m.name]}
        {@const on = m.state === 'running'}
        <ResourceCard name={m.name} sub="{m.image?.distro || 'linux'}{m.image?.version ? ' ' + m.image.version : ''} · machine on {SN}" icon={Box} {on} off={!on}
            on:open={() => go(href.machine(m.name))}
            meters={[
                { k: 'CPU', p: on && u ? Math.min(100, u.cpu) : 0, color: 'var(--metric-cpu)', v: on && u ? u.cpu.toFixed(1) + '%' : '—', of: m.cpu ? `of ${plural(m.cpu, 'core')}` : 'shared cores' },
                { k: 'Memory', p: on && u ? pct(u.mem, u.memLimit) : 0, color: 'var(--metric-mem)', v: on && u ? gb(u.mem) : '—', of: u?.memLimit ? `of ${gb(u.memLimit)}` : '' },
            ]}
            chips={on && u?.runs ? [
                ...(u.runs.containers_running ? [{ label: plural(u.runs.containers_running, 'container'), onClick: () => go(href.machine(m.name)) }] : []),
                ...(u.runs.services ? [{ label: plural(u.runs.services, 'service'), onClick: () => go(href.machine(m.name)) }] : []),
            ] : []}
            note={on ? '' : m.state} />
    {:else}
        <div class="ui-card ui-empty">No machines on {SN} yet.</div>
    {/each}
</div>
