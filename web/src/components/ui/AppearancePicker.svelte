<script>
    // Theme, accent, text size, corners and animations: applied at once, saved in this
    // browser. Used by Settings → General and the first-run setup.
    import { Check } from 'lucide-svelte';
    import { THEMES, savedTheme, applyTheme, ACCENTS, savedAppearance, applyAppearance } from '../../lib/theme.js';

    let theme = savedTheme();
    function setTheme(t) {
        theme = t;
        applyTheme(t, true);
    }

    let look = savedAppearance();
    function setLook(k, v) {
        look = { ...look, [k]: v };
        applyAppearance(look, true);
    }
</script>

        <div class="themes">
            {#each THEMES as t}
                <button class="theme" class:on={theme === t.id} on:click={() => setTheme(t.id)} aria-pressed={theme === t.id}>
                    <span class="preview" style="--p-bg: {t.bg}; --p-surface: {t.surface}; --p-accent: {look.accent === 'theme' ? t.accent : ACCENTS.find(a => a.id === look.accent).color}">
                        <span class="p-side"><i class="p-logo"></i><i></i><i></i><i></i></span>
                        <span class="p-main"><span class="p-card"><i class="p-bar"></i><i></i></span><span class="p-card"><i></i><i></i></span></span>
                    </span>
                    <span class="tl">{t.label}{#if theme === t.id}<Check size={13} />{/if}</span>
                </button>
            {/each}
        </div>
        <div class="rows">
            <div class="ui-form-row">
                <div><div class="ui-label">Accent</div><div class="ui-hint">Buttons, links and highlights</div></div>
                <div class="accents">
                    {#each ACCENTS as a}
                        <button class="acc" class:on={look.accent === a.id} style={a.color ? `--c: ${a.color}` : ''} class:auto={!a.color} on:click={() => setLook('accent', a.id)} title={a.label} aria-label="{a.label} accent" aria-pressed={look.accent === a.id}>
                            {#if look.accent === a.id}<Check size={12} />{/if}
                        </button>
                    {/each}
                    <span class="acc-name">{ACCENTS.find(a => a.id === look.accent)?.label}</span>
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Text size</div><div class="ui-hint">Scales the whole dashboard</div></div>
                <div class="ui-seg">
                    {#each [['s', 'Small'], ['m', 'Default'], ['l', 'Large']] as [v, l]}<button class:on={look.size === v} on:click={() => setLook('size', v)}>{l}</button>{/each}
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Corners</div><div class="ui-hint">Cards and panels</div></div>
                <div class="ui-seg">
                    {#each [['sharp', 'Sharp'], ['m', 'Default'], ['round', 'Round']] as [v, l]}<button class:on={look.corners === v} on:click={() => setLook('corners', v)}>{l}</button>{/each}
                </div>
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Animations</div><div class="ui-hint">Fades, slides and transitions</div></div>
                <div class="ui-seg">
                    {#each [['on', 'On'], ['off', 'Off']] as [v, l]}<button class:on={look.motion === v} on:click={() => setLook('motion', v)}>{l}</button>{/each}
                </div>
            </div>
        </div>

<style>
    .accents { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .acc { width: 26px; height: 26px; border-radius: 50%; background: var(--c); display: flex; align-items: center; justify-content: center; cursor: pointer; color: #111; box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.25); }
    .acc.auto { background: conic-gradient(#D6C2A0, #FF8A3D, #E0484E, #B48CFF, #3FB8FF, #4FD1A5, #D6C2A0); }
    .acc.on { outline: 2px solid var(--text-primary); outline-offset: 2px; }
    .acc-name { margin-left: 6px; font-size: 13px; color: var(--text-secondary); }
    .themes { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; padding: 4px 20px 20px; }
    .theme { display: flex; flex-direction: column; gap: 8px; padding: 6px 6px 8px; border: 1px solid var(--border); border-radius: 10px; cursor: pointer; background: transparent; text-align: left; }
    .theme:hover { border-color: var(--border-strong); }
    .theme.on { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
    /* a tiny dashboard: sidebar with logo, two cards, one accent bar */
    .preview { display: flex; height: 78px; border-radius: 6px; overflow: hidden; background: var(--p-bg); border: 1px solid rgba(255, 255, 255, 0.06); }
    .p-side { width: 26%; display: flex; flex-direction: column; gap: 5px; padding: 7px 6px; background: var(--p-surface); }
    .p-side i { display: block; height: 4px; border-radius: 2px; background: rgba(255, 255, 255, 0.12); }
    .p-side .p-logo { width: 10px; height: 10px; border-radius: 3px; background: var(--p-accent); margin-bottom: 3px; }
    .p-main { flex: 1; display: flex; flex-direction: column; gap: 6px; padding: 8px; }
    .p-card { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 5px; padding: 0 7px; border-radius: 4px; background: var(--p-surface); }
    .p-card i { display: block; height: 4px; width: 70%; border-radius: 2px; background: rgba(255, 255, 255, 0.12); }
    .p-card .p-bar { width: 45%; background: var(--p-accent); }
    .tl { display: flex; align-items: center; justify-content: space-between; padding: 0 4px; font-size: 13px; font-weight: 500; color: var(--text-primary); }
    .tl :global(svg) { color: var(--accent); }

    .rows { border-top: 1px solid var(--border); }
</style>
