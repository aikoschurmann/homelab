<script>
    // Who has devices on the tailnet, as one members list: you, then each person a machine
    // was shared with. A row unfolds that person's devices. Sharing itself is managed in
    // the Tailscale admin console.
    import { slide } from 'svelte/transition';
    import { ChevronDown, ExternalLink, Copy, Search, User, Users } from 'lucide-svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';
    import StatusPill from '../ui/StatusPill.svelte';
    import { machines } from '../../lib/stores.js';
    import { hosts, arrakisModel } from '../../lib/hosts.js';
    import { copyText } from '../../lib/clipboard.js';
    import { isShared, isTagged, displayName, deviceId, ago, clusterOf, deviceIcon } from '../../lib/tailscale.js';

    export let net;
    export let now = Date.now();
    export let open = () => {};

    $: me = net.self.user;
    $: peers = net.devices.filter(d => !d.self);
    $: cl = Object.fromEntries(net.devices.map(d => [d.id, clusterOf(d, $hosts, $machines?.machines, $arrakisModel)]));
    const seenAt = (d) => d.online ? Infinity : new Date(d.last_seen || 0).getTime();
    $: people = (() => {
        const g = new Map();
        for (const d of peers) {
            if (isTagged(d)) continue;
            const key = isShared(d) ? d.user || 'Shared user' : me;
            if (!g.has(key)) g.set(key, []);
            g.get(key).push(d);
        }
        const latest = (list) => Math.max(0, ...list.map(seenAt));
        return [...g.entries()].map(([user, devices]) => ({ user, you: user === me, devices: devices.sort((a, b) => seenAt(b) - seenAt(a) || a.name.localeCompare(b.name)) }))
            .sort((a, b) => (b.you - a.you) || latest(b.devices) - latest(a.devices));
    })();
    let q = '';
    $: shown = people.filter(p => !q || p.user.toLowerCase().includes(q.toLowerCase()) || p.devices.some(d => (d.name + ' ' + d.ip).toLowerCase().includes(q.toLowerCase())));

    let openRows = new Set();
    const toggle = (u) => { openRows.has(u) ? openRows.delete(u) : openRows.add(u); openRows = openRows; };

    const handle = (p) => p.user.split('@')[0];
    const active = (p) => {
        if (p.devices.some(d => d.online)) return 'Online now';
        const t = Math.max(0, ...p.devices.map(seenAt));
        return t ? 'Active ' + ago(new Date(t).toISOString(), now) : 'Never seen';
    };
    const copy = (t) => copyText(t).then(() => window.showToast?.('Copied ' + t), () => {});
    const menu = (p) => [
        { label: 'Copy email', icon: Copy, onClick: () => copy(p.user) },
        { label: p.you ? 'Your account in admin' : 'Manage sharing in admin', icon: ExternalLink, divider: true, onClick: () => window.open('https://login.tailscale.com/admin/users', '_blank', 'noopener') },
    ];
    // Tailscale hides the names of devices belonging to people you shared with, so they're named after their owner
    const nameOf = (d, p, i) => isShared(d) ? `${handle(p)}'s device${p.devices.length > 1 ? ' ' + (i + 1) : ''}` : displayName(d);
</script>

<div class="ts-sub">
    <div class="ui-listbar">
        <label class="ui-search"><Search size={14} /><input placeholder="Search people or devices" bind:value={q} /></label>
        <span class="ui-count">{shown.length} {shown.length === 1 ? 'person' : 'people'}</span>
    </div>

    <section class="ui-card members">
        {#each shown as p (p.user)}
            {@const on = p.devices.filter(d => d.online).length}
            {@const isOpen = openRows.has(p.user)}
            <div class="m" class:open={isOpen}>
                <button class="m-row" on:click={() => toggle(p.user)} aria-expanded={isOpen}>
                    <span class="av" class:on><svelte:component this={p.you ? User : Users} size={18} /></span>
                    <span class="who">
                        <span class="nm"><span class="nm-t">{handle(p)}</span>{#if p.you}<span class="ui-tag">You</span>{/if}</span>
                        <span class="em">{p.user}</span>
                    </span>
                    <span class="dv">{p.devices.length} {p.devices.length === 1 ? 'device' : 'devices'} · {p.you ? 'owner' : 'shared with them'}</span>
                    <span class="seen">{active(p)}</span>
                    <span class="pill">{#if on}<StatusPill state="running" label="{on} online" />{:else}<StatusPill state="stopped" label="Offline" />{/if}</span>
                    <span class="chev"><ChevronDown size={15} /></span>
                </button>
                <span class="act"><ActionMenu items={menu(p)} label="Actions for {p.user}" /></span>
            </div>
            {#if isOpen}
                <div class="devs" transition:slide={{ duration: 150 }}>
                    {#each p.devices as d, i (d.id)}
                        <a class="d" href="#tailscale/{deviceId(d)}" on:click|preventDefault={() => open(deviceId(d))}>
                            <span class="d-ic" class:on={d.online}><svelte:component this={deviceIcon(d, cl[d.id])} size={14} /></span>
                            <span class="d-nm">{nameOf(d, p, i)}</span>
                            <span class="d-ip ui-mono">{d.ip}</span>
                            <span class="d-st" class:on={d.online}>{d.online ? 'Online' : d.last_seen ? 'Seen ' + ago(d.last_seen, now) : 'Offline'}</span>
                        </a>
                    {/each}
                </div>
            {/if}
        {:else}
            <div class="ui-empty">No one matches.</div>
        {/each}
    </section>
</div>

<style>
    .members { overflow: hidden; }
    .m { position: relative; border-top: 1px solid var(--border); }
    .m:first-child { border-top: none; }
    .m-row { display: grid; grid-template-columns: 38px minmax(0, 1fr) 190px 130px 100px 16px; align-items: center; gap: 14px; width: 100%; padding: 14px 60px 14px 18px; text-align: left; cursor: pointer; color: inherit; transition: background-color .12s; }
    .m-row:hover { background: var(--highlight-3); }
    /* the host cards' icon tile */
    .av { width: 38px; height: 38px; border-radius: 9px; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); }
    .av.on { background: var(--accent-soft); color: var(--accent); }
    .who { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .nm { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: var(--accent); min-width: 0; }
    .nm-t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    .nm :global(.ui-tag) { flex-shrink: 0; }
    .m-row:hover .nm-t { text-decoration: underline; }
    .em { font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .dv, .seen { font-size: 13px; color: var(--text-secondary); white-space: nowrap; }
    .pill { display: flex; justify-content: flex-end; }
    .chev { display: flex; color: var(--text-secondary); transition: transform .15s ease; }
    .open .chev { transform: rotate(180deg); }
    .act { position: absolute; right: 14px; top: 33px; transform: translateY(-50%); }

    /* a person's devices, under their name, like the sidebar tree */
    .devs { padding: 4px 18px 8px; border-top: 1px solid var(--border); background: var(--highlight-3); }
    .d { display: grid; grid-template-columns: 38px minmax(0, 1fr) 130px 130px; align-items: center; gap: 12px; padding: 7px 0; font-size: 13.5px; color: var(--text-secondary); text-decoration: none; border-top: 1px solid var(--border); }
    .d:first-child { border-top: none; }
    .d-ic { justify-self: center; width: 28px; height: 28px; border-radius: 7px; display: flex; align-items: center; justify-content: center; background: var(--highlight-10); color: var(--text-secondary); }
    .d-ic.on { background: var(--accent-soft); color: var(--accent); }
    .d-nm { color: var(--text-primary); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .d:hover .d-nm { color: var(--accent); }
    .d-ip { font-size: 12px; }
    .d-st { text-align: right; white-space: nowrap; font-size: 13px; }
    .d-st.on { color: var(--green); }

    @media (max-width: 1000px) {
        .m-row { grid-template-columns: 38px minmax(0, 1fr) 120px 100px 16px; }
        .dv { display: none; }
    }
    @media (max-width: 640px) {
        .m-row { grid-template-columns: 38px minmax(0, 1fr) auto 16px; gap: 12px; padding: 12px 50px 12px 14px; }
        .seen { display: none; }
        .act { right: 6px; top: 31px; }
        .devs { padding-left: 14px; padding-right: 14px; }
        .d { grid-template-columns: 38px minmax(0, 1fr) auto; }
        .d-ip { display: none; }
    }
</style>
