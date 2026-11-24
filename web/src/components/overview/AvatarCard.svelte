<script>
    // A little companion: just a square with a face. Its mood follows the cluster: content
    // (looks around, blinks), busy when a host works hard (narrowed eyes, darting), worried
    // when a host is down (red, brows), asleep at night. Its eyes follow your pointer while you
    // move it, and go back to looking around when you stop. Hover it for what it's thinking.
    // Its look is picked from its toolbar while customizing.
    import { onMount, onDestroy } from 'svelte';
    export let cfg = {};
    export let state = {};   // { online, total, down: [names], busy: { name, cpu } | null, updates, now }

    import { AVATAR_LOOKS as LOOKS } from '../../lib/widgets.js';
    $: look = LOOKS.some(l => l[0] === cfg.look) ? cfg.look : 'visor';
    $: hour = new Date(state.now || Date.now()).getHours();
    $: mood = state.down?.length ? 'worried' : state.busy ? 'busy' : hour < 6 ? 'sleep' : 'content';
    $: line = mood === 'worried' ? `${state.down.join(', ')} ${state.down.length === 1 ? 'is' : 'are'} not answering.`
        : mood === 'busy' ? `${state.busy.name} is working hard: ${Math.round(state.busy.cpu)}% CPU.`
        : mood === 'sleep' ? 'All quiet. Zzz…'
        : `All ${state.total} hosts up${state.updates ? `, ${state.updates} updates waiting` : ''}.`;

    // the eyes: where and how big, by look and mood (a 100 × 100 face)
    $: eye = (() => {
        const w = look === 'dots' ? 14 : look === 'pixel' ? 14 : 13;
        const h = mood === 'sleep' ? 3 : mood === 'busy' ? 7 : look === 'dots' ? 14 : look === 'pixel' ? 14 : 22;
        const rx = look === 'pixel' ? 0 : look === 'dots' ? 7 : mood === 'sleep' ? 1.5 : 6;
        return { w, h, rx, y: 50 - h / 2 + (mood === 'sleep' ? 4 : 0) };
    })();

    // following the pointer: while it moves (and a little after), the eyes look at it
    let el, gx = 0, gy = 0, tracking = false, raf = 0, px = 0, py = 0, idleT;
    function onMove(e) {
        px = e.clientX; py = e.clientY; tracking = true;
        clearTimeout(idleT); idleT = setTimeout(() => { tracking = false; gx = gy = 0; }, 2500);
        if (!raf) raf = requestAnimationFrame(aim);
    }
    function aim() {
        raf = 0;
        if (!el) return;
        const r = el.getBoundingClientRect(), dx = px - (r.left + r.width / 2), dy = py - (r.top + r.height / 2);
        const d = Math.hypot(dx, dy) || 1, f = Math.min(1, d / 240);
        gx = dx / d * f * 7; gy = dy / d * f * 5;
    }
    $: follow = tracking && mood !== 'sleep';
    onMount(() => window.addEventListener('pointermove', onMove, { passive: true }));
    onDestroy(() => { if (typeof window !== 'undefined') window.removeEventListener('pointermove', onMove); clearTimeout(idleT); cancelAnimationFrame(raf); });
</script>

<div class="sq {mood} {look}" class:follow bind:this={el} title={line} role="img" aria-label="{cfg.name || 'Byte'}: {line}">
    <svg viewBox="0 0 100 100">
        {#if look === 'cat'}
            <path class="ear" d="M14 30 L22 6 L38 24 Z M86 30 L78 6 L62 24 Z" />
        {/if}
        <rect class="visor" x="12" y="22" width="76" height="58" rx={look === 'pixel' ? 4 : 18} />
        {#if look === 'pixel'}
            {#each Array(9) as _, k}<line class="scan" x1="14" x2="86" y1={27 + k * 6} y2={27 + k * 6} />{/each}
        {/if}
        <g class="aim" style="transform: translate({follow ? gx : 0}px, {follow ? gy : 0}px)">
        <g class="eyes">
            <g class="lid">
                <rect class="eye" x={36 - eye.w / 2} y={eye.y} width={eye.w} height={eye.h} rx={eye.rx} />
                <rect class="eye" x={64 - eye.w / 2} y={eye.y} width={eye.w} height={eye.h} rx={eye.rx} />
            </g>
        </g>
        </g>
        {#if mood === 'worried'}
            <path class="brow" d="M27 34 L42 39 M73 34 L58 39" />
        {/if}
        {#if look === 'cat'}
            <path class="whisk" d="M8 60 h14 M8 67 l14 -3 M92 60 h-14 M92 67 l-14 -3" />
        {/if}
        {#if mood === 'sleep'}<text class="z" x="74" y="20">z</text>{/if}
    </svg>
</div>

<style>
    .sq { --c: var(--accent); width: 136px; height: 100%; min-height: 136px; box-sizing: border-box; display: flex; align-items: center; justify-content: center;
        background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card, 8px); }
    .sq.worried { --c: var(--red); }
    .sq.sleep { --c: var(--text-secondary); }
    /* the face grows with its square (Small or Large on the grid): about 60% of its shorter side */
    .sq { container-type: size; }
    svg { width: 60cqmin; height: 60cqmin; max-width: 100%; max-height: 100%; overflow: visible; }
    .visor { fill: var(--bg); stroke: var(--border-strong); stroke-width: 1.5; }
    .ear { fill: var(--bg); stroke: var(--border-strong); stroke-width: 1.5; stroke-linejoin: round; }
    .scan { stroke: var(--highlight-5); stroke-width: 1; }
    .eye { fill: var(--c); filter: drop-shadow(0 0 4px var(--c)); transition: all .3s ease; }
    .brow, .whisk { fill: none; stroke: var(--c); stroke-width: 3; stroke-linecap: round; }
    .whisk { stroke: var(--border-strong); stroke-width: 1.5; }
    .z { font-size: 14px; font-weight: 700; fill: var(--text-secondary); animation: zz 2.6s ease-in-out infinite; }
    .aim { transition: transform .18s ease-out; }
    /* content: looks around now and then, and blinks */
    .eyes { animation: glance 7s ease-in-out infinite; }
    .lid { transform-origin: 50px 50px; animation: blink 4.6s infinite; }
    .busy .eyes { animation: dart 1.1s steps(1) infinite; }
    .busy .lid, .sleep .lid { animation: none; }
    .sleep .eyes { animation: breathe 4s ease-in-out infinite; }
    .worried .eyes { animation: none; }
    /* following the pointer: no looking around of its own meanwhile */
    .follow .eyes { animation: none; }
    @keyframes glance { 0%, 30%, 100% { transform: translateX(0); } 36%, 48% { transform: translateX(-7px); } 54%, 66% { transform: translateX(6px); } 72% { transform: translateX(0); } }
    @keyframes blink { 0%, 93%, 100% { transform: scaleY(1); } 96% { transform: scaleY(0.08); } }
    @keyframes dart { 0% { transform: translateX(-5px); } 33% { transform: translateX(5px); } 66% { transform: translateX(0); } }
    @keyframes breathe { 50% { opacity: .45; } }
    @keyframes zz { 0% { opacity: 0; transform: translate(0, 4px); } 50% { opacity: 1; } 100% { opacity: 0; transform: translate(8px, -8px); } }
    @media (prefers-reduced-motion: reduce) { .eyes, .lid, .z, .aim { animation: none !important; transition: none !important; } }
</style>
