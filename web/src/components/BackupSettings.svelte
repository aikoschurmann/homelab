<script>
    // Settings → Backups: what the nightly backup saves, where it goes, and when it runs.
    // Contents (~/.homelab_backup.json) and schedule (the launchd plist) are separate on the
    // server but share one save bar here.
    import { onMount } from 'svelte';
    import { Plus, X, Loader2, AlertTriangle, Check } from 'lucide-svelte';
    import Stepper from './Stepper.svelte';
    import Switch from './ui/Switch.svelte';

    const toast = (m) => window.showToast?.(m);
    const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    const pad = (n) => String(n).padStart(2, '0');
    function describe(c) {
        if (!c) return '—';
        if (c.frequency === 'hourly') return `Every ${c.hour} ${c.hour === 1 ? 'hour' : 'hours'}`;
        const at = `${pad(c.hour)}:${pad(c.minute)}`;
        return c.frequency === 'weekly' ? `${DAYS[c.day % 7]}s at ${at}` : `Daily at ${at}`;
    }

    let set = null, setSaved = null, sched = null, schedSaved = null, newFolder = '', saving = false;
    async function load() {
        const [st, c] = await Promise.all([
            fetch('/api/backups/settings').then(r => r.json()).catch(() => ({})),
            fetch('/api/backups/config').then(r => r.json()).catch(() => ({})),
        ]);
        if (st.status === 'success') { setSaved = st.data; set = structuredClone(st.data); }
        if (c.status === 'success') { schedSaved = c.data; sched = { ...c.data }; }
    }
    onMount(load);

    const pick = (x) => x && JSON.stringify({ dest: x.dest, parts: x.parts, folders: x.folders, copy_to: x.copy_to });
    $: setDirty = set && setSaved && pick(set) !== pick(setSaved);
    $: schedDirty = sched && schedSaved && JSON.stringify(sched) !== JSON.stringify(schedSaved);

    function setFreq(f) {
        sched.frequency = f;
        if (f === 'hourly' && (sched.hour < 1 || sched.hour > 168)) sched.hour = 6;
        if (f !== 'hourly' && sched.hour > 23) sched.hour = 4;
    }
    function addFolder() {
        const f = newFolder.trim();
        if (f && !set.folders.includes(f)) set = { ...set, folders: [...set.folders, f] };
        newFolder = '';
    }
    async function save() {
        saving = true;
        const req = (url, body) => fetch(url, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json()).catch(e => ({ message: String(e) }));
        let ok = true;
        if (setDirty) {
            const r = await req('/api/backups/settings', JSON.parse(pick(set)));
            if (r.status !== 'success') { ok = false; toast(r.message || 'Could not save'); }
        }
        if (ok && schedDirty) {
            const r = await req('/api/backups/config', sched);
            if (r.status !== 'success') { ok = false; toast(r.message || 'Could not save the schedule'); }
        }
        saving = false;
        if (ok) { toast('Saved. The next backup uses it'); await load(); }
    }
    function reset() { set = structuredClone(setSaved); sched = { ...schedSaved }; }
</script>

{#if !set || !sched}
    <div class="ui-card ui-empty">Loading…</div>
{:else}
    <section class="ui-card" data-setting="backup-parts">
        <div class="ui-card-head"><div><h2 class="ui-card-title">What's backed up</h2><p class="ui-card-desc">Each part becomes its own archive in every snapshot.</p></div></div>
        <div class="rows">
            {#each Object.entries(set.part_info) as [id, desc]}
                <div class="ui-form-row" data-setting="backup-part-{id}">
                    <div><div class="ui-label">{set?.part_labels?.[id] || id}</div><div class="ui-hint">{desc}</div></div>
                    <Switch bind:checked={set.parts[id]}>Include</Switch>
                </div>
            {/each}
            <div class="ui-form-row" data-setting="backup-folders">
                <div><div class="ui-label">Extra folders</div><div class="ui-hint">Any folders on the Mac, in one archive</div></div>
                <div class="flist">
                    {#each set.folders as f, i}
                        <div class="frow"><span class="ui-mono" title={f}>{f}</span><button class="x" aria-label="Remove {f}" title="Stop backing up this folder" on:click={() => set = { ...set, folders: set.folders.filter((_, j) => j !== i) }}><X size={14} /></button></div>
                    {/each}
                    <form class="fadd" on:submit|preventDefault={addFolder}>
                        <input class="ui-input mono" placeholder="~/Documents/Projects" bind:value={newFolder} spellcheck="false" />
                        <button class="ui-btn sm" disabled={!newFolder.trim()}><Plus size={13} /> Add</button>
                    </form>
                </div>
            </div>
        </div>
    </section>

    <section class="ui-card" data-setting="backup-where">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Where</h2><p class="ui-card-desc">Folders on the Mac. The Mac writes them itself, so an external drive is fine here.</p></div></div>
        <div class="rows">
            <div class="ui-form-row" data-setting="backup-dest">
                <div><div class="ui-label">Backups folder</div><div class="ui-hint">Snapshots already in the old folder stay there</div></div>
                <input class="ui-input mono wide" bind:value={set.dest} placeholder={set.default_dest} spellcheck="false" />
            </div>
            <div class="ui-form-row" data-setting="backup-copy">
                <div><div class="ui-label">Second copy</div><div class="ui-hint">Each new snapshot is copied here too, with the same retention</div></div>
                <div class="col">
                    <input class="ui-input mono wide" bind:value={set.copy_to} placeholder="/Volumes/Magic-Rock/Homelab-Backups (optional)" spellcheck="false" />
                    {#if setSaved.copy_to && setSaved.copy_status}
                        <div class="ui-hint {setSaved.copy_status.ok ? 'ok' : 'bad'}">{#if setSaved.copy_status.ok}<Check size={12} /> Last copy worked ({setSaved.copy_status.at}){:else}<AlertTriangle size={12} /> Last copy failed: {setSaved.copy_status.why}{/if}</div>
                    {:else if setSaved.copy_to}<div class="ui-hint">No copy made yet; the next backup makes one.</div>{/if}
                </div>
            </div>
        </div>
    </section>

    <section class="ui-card" data-setting="backup-schedule">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Schedule</h2><p class="ui-card-desc">When launchd runs the backup on the Mac, and how many snapshots to keep.</p></div></div>
        <div class="rows">
            <div class="ui-form-row" data-setting="backup-frequency">
                <div><div class="ui-label">Frequency</div><div class="ui-hint">Currently: {describe(schedSaved)}</div></div>
                <div class="ui-seg">
                    {#each [['hourly', 'Every few hours'], ['daily', 'Daily'], ['weekly', 'Weekly']] as [v, l]}<button class:on={sched.frequency === v} on:click={() => setFreq(v)}>{l}</button>{/each}
                </div>
            </div>
            {#if sched.frequency === 'weekly'}
                <div class="ui-form-row">
                    <div class="ui-label">Day</div>
                    <div class="days">{#each DAYS as d, i}<button class="day" class:on={sched.day % 7 === i} on:click={() => sched.day = i}>{d.slice(0, 3)}</button>{/each}</div>
                </div>
            {/if}
            {#if sched.frequency === 'hourly'}
                <div class="ui-form-row">
                    <div><div class="ui-label">Interval</div><div class="ui-hint">Counted from when the schedule is saved</div></div>
                    <Stepper bind:value={sched.hour} min={1} max={168} step={1} unit="hours" />
                </div>
            {:else}
                <div class="ui-form-row" data-setting="backup-time">
                    <div><div class="ui-label">Time</div><div class="ui-hint">Mac local time; if the Mac sleeps, it runs on wake</div></div>
                    <div class="time">
                        <Stepper bind:value={sched.hour} min={0} max={23} step={1} unit="h" />
                        <span>:</span>
                        <Stepper bind:value={sched.minute} min={0} max={59} step={5} unit="min" />
                    </div>
                </div>
            {/if}
            <div class="ui-form-row" data-setting="backup-keep">
                <div><div class="ui-label">Keep</div><div class="ui-hint">Older snapshots are deleted after each backup</div></div>
                <Stepper bind:value={sched.retention} min={1} max={60} step={1} unit="snapshots" />
            </div>
        </div>
    </section>

    {#if setDirty || schedDirty}
        <div class="ui-savebar">
            <span>{schedDirty ? `New schedule: ${describe(sched)}, keep ${sched.retention}` : 'Unsaved changes'}</span>
            <span class="ui-btns"><button class="ui-btn sm" on:click={reset}>Reset</button><button class="ui-btn sm primary" disabled={saving} on:click={save}>{#if saving}<Loader2 size={13} class="ui-spin" />{/if}Save</button></span>
        </div>
    {/if}
{/if}

<style>
    .rows { border-top: 1px solid var(--border); }
    .ui-form-row { align-items: center; }
    .rows .ui-form-row > * { min-width: 0; }
    .wide { width: 100%; max-width: 460px; min-width: 0; justify-self: stretch; box-sizing: border-box; }
    .col { display: grid; gap: 6px; justify-self: stretch; min-width: 0; }
    .col .ui-hint { overflow-wrap: anywhere; }
    .ui-hint.ok { color: var(--green); display: inline-flex; gap: 6px; align-items: center; }
    .ui-hint.bad { color: var(--red); display: inline-flex; gap: 6px; align-items: center; }
    .flist { display: grid; gap: 8px; justify-self: stretch; max-width: 560px; }
    .frow { display: flex; align-items: center; gap: 8px; padding: 4px 4px 4px 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 12.5px; }
    .frow .ui-mono { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
    .frow .x { margin-left: auto; width: 26px; height: 26px; border-radius: 5px; display: grid; place-items: center; color: var(--text-secondary); cursor: pointer; flex-shrink: 0; }
    .frow .x:hover { background: var(--highlight-10); color: var(--red); }
    .fadd { display: flex; gap: 8px; }
    .fadd .ui-input { flex: 1; min-width: 0; }
    .days { display: flex; gap: 6px; flex-wrap: wrap; }
    .day { height: 32px; min-width: 46px; padding: 0 10px; border: 1px solid var(--border-strong); border-radius: 6px; font-size: 13px; color: var(--text-secondary); cursor: pointer; background: var(--surface); }
    .day.on { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); font-weight: 600; }
    .time { display: flex; align-items: center; gap: 8px; }
    .time > span { color: var(--text-secondary); font-weight: 600; }
</style>
