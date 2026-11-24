<script>
    // Some text of your own: a title and a few lines (links become clickable). Written on the
    // card itself while customizing (Normal / Large sits in its Customize toolbar); Large shows it as a big line, for a motto or a reminder.
    export let cfg = {};
    export let editing = false;
    export let onChange = () => {};

    $: title = cfg.title || '';
    $: body = cfg.body || '';
    $: big = cfg.size === 'big';
    // plain text, with each link made clickable (nothing else is read as markup)
    const parts = (s) => s.split(/(https?:\/\/[^\s<]+)/g).map((t, i) => ({ t, link: i % 2 === 1 }));
</script>

<section class="ui-card note" class:big>
    {#if editing}
        <div class="live-edit" data-nodrag>
            <input class="ui-input" placeholder="Title (optional)" maxlength="80" value={title} on:input={(e) => onChange({ title: e.currentTarget.value })} />
            <textarea class="ui-input area" class:big placeholder="Write something…" rows="3" maxlength="2000" value={body} on:input={(e) => onChange({ body: e.currentTarget.value })}></textarea>
        </div>
    {:else if title || body}
        {#if title}<div class="ui-card-head"><h2 class="ui-card-title">{title}</h2></div>{/if}
        {#if body}<div class="txt" class:top={!title}><p>{#each parts(body) as p}{#if p.link}<a class="ui-link" href={p.t} target="_blank" rel="noopener">{p.t}</a>{:else}{p.t}{/if}{/each}</p></div>{/if}
    {:else}
        <div class="txt top empty"><p>Nothing written yet. Write here under Customize.</p></div>
    {/if}
</section>

<style>
    .note { display: flex; flex-direction: column; }
    .txt p { margin: 0; }
    .txt { display: flex; align-items: flex-start; padding: 14px 20px 16px; font-size: 14px; line-height: 1.6; color: var(--text-primary); white-space: pre-wrap; overflow-wrap: anywhere; flex: 1; }
    .ui-card-head + .txt { border-top: 1px solid var(--border); }
    .txt.top { padding-top: 16px; }
    .txt.empty { color: var(--text-secondary); }
    .big .txt { font-size: 20px; line-height: 1.4; font-weight: 600; letter-spacing: -0.01em; }
    @media (max-width: 640px) { .txt, .live-edit { padding-left: 14px; padding-right: 14px; } }
    .live-edit { display: flex; flex-direction: column; gap: 8px; padding: 16px 20px; pointer-events: auto; }
    .area { height: auto; min-height: 72px; padding: 8px 10px; line-height: 1.5; resize: vertical; }
    /* while editing, the box already shows the text as it will look (Large: the big line) */
    .area.big { font-size: 20px; line-height: 1.4; font-weight: 600; letter-spacing: -0.01em; }
</style>
