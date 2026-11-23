<script>
    import { onMount } from 'svelte';
    import { SN } from '../lib/server.js';

    // Who else may open the dashboard: people on the tailnet, by their Tailscale login.
    let people = null, error = '', saving = {};
    async function load() {
        try {
            const j = await fetch('/api/access').then(r => r.json());
            if (j.status === 'success') people = j.data; else error = j.message;
        } catch (e) { error = 'Could not load'; }
    }
    onMount(load);
    async function set(p, role) {
        saving = { ...saving, [p.login]: true };
        try {
            const r = await fetch('/api/access', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ login: p.login, role }) }).then(r => r.json());
            if (r.status === 'success') { p.role = role; people = people; window.showToast?.(`${p.name}: ${role ? (role === 'admin' ? 'full access' : 'can view') : 'no access'}`); }
            else window.showToast?.(r.message || 'Could not save');
        } finally { saving = { ...saving, [p.login]: false }; }
    }
    const ROLES = [[null, 'No access'], ['viewer', 'View'], ['admin', 'Full']];
</script>

<section class="ui-card">
    <div class="ui-card-head"><div>
        <h2 class="ui-card-title">People</h2>
        <p class="ui-card-desc">Your own devices always have full access. Anyone else on your tailnet, including people a device was shared with, can open {SN}'s dashboard only if you allow it here. View shows everything but changes nothing, and has no terminal or backup downloads.</p>
    </div></div>
    {#if error}
        <div class="ui-empty">{error}</div>
    {:else if !people}
        <div class="ui-empty">Loading…</div>
    {:else if !people.length}
        <div class="ui-empty">Nobody else is on your tailnet. Share a device with someone in Tailscale and they show up here.</div>
    {:else}
        <div class="ui-tbl-wrap">
            <table class="ui-tbl">
                <thead><tr><th>Person</th><th class="c-sm">Devices</th><th class="shrink">Access</th></tr></thead>
                <tbody>
                    {#each people as p (p.login)}
                        <tr>
                            <td><div class="nm">{p.name}</div>{#if p.name !== p.login}<div class="sub ui-mono">{p.login}</div>{/if}</td>
                            <td class="c-sm ui-dim">{p.devices ? `${p.devices} on the tailnet` : 'not on the tailnet now'}</td>
                            <td><div class="ui-seg">{#each ROLES as [r, l]}<button class:on={(p.role || null) === r} disabled={saving[p.login]} on:click={() => set(p, r)}>{l}</button>{/each}</div></td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
    {/if}
</section>

<style>
    .nm { font-weight: 600; }
    .sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
</style>
