<script>
    import { ChevronUp, ChevronDown } from 'lucide-svelte';
    import Modal from '../ui/Modal.svelte';
    import Switch from '../ui/Switch.svelte';
    import SectionOptions from './SectionOptions.svelte';
    import { SN } from '../../lib/server.js';
    import { layout, baseOf, orderWithout, OVERVIEW_WIDGETS, toggleWidget, toggleHostCard, setWidth } from '../../lib/widgets.js';
    import { hosts, hostOrder, saveHostOrder, byOrder } from '../../lib/hosts.js';

    // A section's settings, as a widget has its own: its width, and what it shows
    // (tiles, host cards, shortcuts). Changes apply right away.
    export let open = false;
    export let id = null;

    // a copy of a section ('tailscale#k3x') has its own width; what it shows is the section's
    $: kind = id ? baseOf(id) : null;
    $: label = OVERVIEW_WIDGETS.find(w => w.id === kind)?.label || '';
    $: width = $layout.widths[id] === 'half' ? 'half' : 'full';
    $: hiddenHosts = new Set($layout.hidden_hosts);
    const shortOs = (o) => (o || '').replace(/ GNU\/Linux/, '').replace(/\s*\(.*\)$/, '');
    $: hostList = byOrder([{ id: 'arrakis', name: SN, os: 'macOS · this server' }, ...($hosts || []).map(h => ({ id: h.id, name: h.name, os: h.report ? shortOs(h.report.os) : 'agent not installed' }))], $hostOrder);
    function moveHost(hid, d) {
        const o = hostList.map(h => h.id), i = o.indexOf(hid), j = i + d;
        if (i < 0 || j < 0 || j >= o.length) return;
        [o[i], o[j]] = [o[j], o[i]];
        hostOrder.set(o); saveHostOrder(o);
    }
    const remove = () => { id.includes('#') ? orderWithout(id) : toggleWidget(id); open = false; };
</script>

<Modal bind:open title={label} width={480}>
    <div class="form">
        <div class="ui-field">
            <span class="ui-label">Width</span>
            <div class="ui-seg"><button type="button" class:on={width === 'full'} on:click={() => setWidth(id, 'full')}>Full</button><button type="button" class:on={width === 'half'} on:click={() => setWidth(id, 'half')}>Half</button></div>
            <span class="ui-hint">Half-width sections sit two to a row on wide screens.</span>
        </div>

        <SectionOptions {kind} />

        {#if kind === 'host'}
            <div class="ui-field">
                <span class="ui-label">Host cards</span>
                <div class="list">
                    {#each hostList as h, i (h.id)}
                        <div class="li">
                            <span class="nm"><b>{h.name}</b><small>{h.os}</small></span>
                            <span class="mv"><button title="Move up" disabled={i === 0} on:click={() => moveHost(h.id, -1)}><ChevronUp size={14} /></button><button title="Move down" disabled={i === hostList.length - 1} on:click={() => moveHost(h.id, 1)}><ChevronDown size={14} /></button></span>
                            <Switch checked={!hiddenHosts.has(h.id)} on:change={() => toggleHostCard(h.id)} label="Show {h.name}" />
                        </div>
                    {/each}
                </div>
            </div>
        {/if}

    </div>
    <svelte:fragment slot="footer">
        <button class="ui-btn danger-outline rm" on:click={remove}>Remove from page</button>
        <button class="ui-btn primary" on:click={() => open = false}>Done</button>
    </svelte:fragment>
</Modal>

<style>
    .form { display: flex; flex-direction: column; gap: 18px; }
    .rm { margin-right: auto; }
    .list { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
    .li { display: flex; align-items: center; gap: 10px; min-height: 42px; padding: 0 12px; font-size: 13.5px; color: var(--text-primary); }
    .li + .li { border-top: 1px solid var(--border); }
    .li > span:first-child { flex: 1; min-width: 0; }
    .li.off > span:first-child { color: var(--text-secondary); }
    .nm { display: flex; flex-direction: column; }
    .nm b { font-weight: 500; }
    .nm small { font-size: 12px; color: var(--text-secondary); }
    .mv { display: flex; gap: 2px; }
    .mv button { width: 26px; height: 26px; display: flex; align-items: center; justify-content: center; border-radius: 6px; color: var(--text-secondary); cursor: pointer; }
    .mv button:hover:not(:disabled) { background: var(--highlight-10); color: var(--text-primary); }
    .mv button:disabled { opacity: .3; cursor: default; }
</style>
