<script>
    // Thin, continuous availability strip: one segment per slot ('up' | 'partial' | 'down' | null)
    export let slots = [];
    export let bucketSeconds = 1800;
    export let height = 6;

    function title(i, st) {
        const end = Date.now() - (slots.length - 1 - i) * bucketSeconds * 1000;
        const fmt = (t) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        return `${fmt(end - bucketSeconds * 1000)}–${fmt(end)} · ${{ up: 'Up', down: 'Down', partial: 'Partly down' }[st] || 'No data'}`;
    }
</script>

<div class="strip" style="height: {height}px">
    {#each slots as st, i}<i class={st || 'none'} title={title(i, st)}></i>{/each}
</div>

<style>
    .strip { display: flex; width: 100%; border-radius: 3px; overflow: hidden; background: var(--highlight-10); }
    i { flex: 1; height: 100%; }
    /* the theme's own status colours, lightly toned down so a mixed strip reads clearly without glaring */
    .up { background: var(--green); opacity: 0.7; }
    .partial { background: var(--yellow); opacity: 0.85; }
    .down { background: var(--red); opacity: 0.9; }
    .none { background: transparent; }
    i:hover { opacity: 1; filter: brightness(1.1); }
</style>
