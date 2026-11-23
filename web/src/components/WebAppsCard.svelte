<script>
    import { Globe, Plus, Pencil } from 'lucide-svelte';
    import { webLinks, pinnedLinks, absUrl, editLink } from '../lib/weblinks.js';
    import { services } from '../lib/services.js';

    // Overview launcher: one row of pinned web UIs; the pencil on hover edits or unpins
    $: tiles = pinnedLinks($webLinks, $services).map(t => ({ ...t, href: absUrl(t.url) }));
</script>

<section class="ui-card wa-card" id="sec-webapps">
    <span class="wa-title">Web apps</span>
    <div class="wa-list">
        {#each tiles as t (t.key)}
            <span class="wa" class:down={t.running === false}>
                <a href={t.href} target="_blank" rel="noopener noreferrer" title={t.running === false ? `${t.name} is not running` : t.href}><Globe size={14} />{t.name}</a>
                <button class="ed" title="Edit or unpin" aria-label="Edit {t.name}" on:click={() => editLink(t.svc || null, t.key)}><Pencil size={12} /></button>
            </span>
        {:else}
            <span class="ui-dim hint">Pin a service from its ⋯ menu, or</span>
        {/each}
        <button class="wa add" title="Add a link" on:click={() => editLink()}><Plus size={14} />{#if !tiles.length}Add link{/if}</button>
    </div>
</section>

<style>
    .wa-card { display: flex; align-items: center; gap: 16px; padding: 12px 16px 12px 20px; }
    .wa-title { font-size: 14px; font-weight: 600; color: var(--text-primary); flex-shrink: 0; }
    .wa-list { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-width: 0; }
    .wa { display: inline-flex; align-items: center; height: 32px; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); transition: border-color .12s; }
    .wa:hover { border-color: var(--accent); }
    .wa a { display: inline-flex; align-items: center; gap: 7px; height: 100%; padding: 0 12px; font-size: 13.5px; font-weight: 500; color: var(--text-primary); text-decoration: none; white-space: nowrap; }
    .wa a :global(svg) { color: var(--accent); }
    .wa a:hover { color: var(--accent); }
    .ed { display: none; align-items: center; justify-content: center; width: 24px; height: 24px; margin: 0 4px 0 -6px; border-radius: 12px; color: var(--text-secondary); cursor: pointer; }
    .wa:hover .ed, .ed:focus-visible { display: inline-flex; }
    .ed:hover { background: var(--highlight-10); color: var(--text-primary); }
    .wa.down a { color: var(--text-secondary); }
    .wa.down a :global(svg) { color: var(--text-secondary); }
    .add { gap: 6px; padding: 0 10px; color: var(--text-secondary); border-style: dashed; cursor: pointer; font-size: 13px; }
    .add:hover { color: var(--accent); }
    .hint { font-size: 13px; }
    @media (hover: none) { .ed { display: inline-flex; } }
    @media (max-width: 640px) {
        .wa-card { flex-direction: column; align-items: flex-start; gap: 10px; padding: 14px; }
    }
</style>
