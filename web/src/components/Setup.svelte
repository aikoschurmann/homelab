<script>
    // First run: name this server, pick its port and (with OrbStack) the machine that runs
    // the containers. Shown instead of the app until /api/server says setup_done.
    import { Check, Minus, Loader2, Server as ServerIcon } from 'lucide-svelte';
    import { server, saveServer } from '../lib/server.js';
    import { savedTheme, applyTheme, applyAppearance, savedAppearance } from '../lib/theme.js';

    applyTheme(savedTheme());
    applyAppearance(savedAppearance());

    let name = server.name;
    let port = server.port;
    let vm = server.vm_name && server.machines.includes(server.vm_name) ? server.vm_name : (server.machines[0] || '');
    let saving = false, error = '', restart = false;

    const TOOLS = [
        ['orbstack', 'OrbStack', 'Machines and their containers'],
        ['tailscale', 'Tailscale', 'Tailnet page, other hosts reporting in'],
        ['cloudflared', 'cloudflared', 'Sharing machines through Cloudflare Tunnels'],
        ['docker', 'Docker', 'Containers on this computer'],
        ['tmux', 'tmux', 'Terminal sessions that outlive the browser'],
    ];

    async function finish() {
        saving = true; error = '';
        try {
            const d = await saveServer({ name, port: Number(port), vm_name: vm || null, setup_done: true });
            if (d.restart_needed) restart = true;
            else location.href = '/';      // drops ?setup, if it was opened that way
        } catch (e) { error = e.message; }
        saving = false;
    }
</script>

<div class="setup">
    <section class="ui-card">
        <div class="ui-card-head">
            <div class="hd">
                <span class="ic"><ServerIcon size={20} /></span>
                <div><h1 class="ui-card-title">Set up this server</h1><p class="ui-card-desc">{server.os} · {server.hostname}. You can change all of this later under Settings.</p></div>
            </div>
        </div>
        {#if restart}
            <div class="ui-card-body">
                <div class="ui-banner">Saved. Restart the dashboard for the new port or machine to apply, then open it on port {port}.</div>
            </div>
        {:else}
        <div class="rows">
            <div class="ui-form-row">
                <div><div class="ui-label">Name</div><div class="ui-hint">What the dashboard calls this computer</div></div>
                <input class="ui-input" bind:value={name} maxlength="40" />
            </div>
            <div class="ui-form-row">
                <div><div class="ui-label">Port</div><div class="ui-hint">Applies after a restart</div></div>
                <input class="ui-input port" type="number" min="1024" max="65535" bind:value={port} />
            </div>
            {#if server.features.orbstack}
                <div class="ui-form-row">
                    <div><div class="ui-label">Main machine</div><div class="ui-hint">The OrbStack machine whose containers the dashboard tracks</div></div>
                    {#if server.machines.length}
                        <select class="ui-select" bind:value={vm}>{#each server.machines as m}<option value={m}>{m}</option>{/each}</select>
                    {:else}
                        <span class="ui-dim">No machines yet. Create one later from the OrbStack VM page.</span>
                    {/if}
                </div>
            {/if}
            <div class="ui-form-row">
                <div><div class="ui-label">Found on this computer</div><div class="ui-hint">Pages for tools that aren't installed stay empty</div></div>
                <ul class="tools">
                    {#each TOOLS as [id, label, what]}
                        <li class:off={!server.features[id]}>
                            {#if server.features[id]}<Check size={14} />{:else}<Minus size={14} />{/if}
                            <b>{label}</b><span class="ui-dim">{what}</span>
                        </li>
                    {/each}
                </ul>
            </div>
        </div>
        <div class="ui-card-foot">
            {#if error}<span class="err">{error}</span>{:else}<span>Settings are kept in <span class="ui-mono">{server.home}</span></span>{/if}
            <span class="ui-btns"><button class="ui-btn primary" disabled={saving || !name.trim()} on:click={finish}>{#if saving}<Loader2 size={14} class="ui-spin" /> Saving…{:else}Finish setup{/if}</button></span>
        </div>
        {/if}
    </section>
</div>

<style>
    .setup { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px 16px; box-sizing: border-box; background: var(--bg); }
    .setup .ui-card { width: 100%; max-width: 680px; }
    .hd { display: flex; gap: 12px; align-items: center; }
    .ic { width: 38px; height: 38px; border-radius: 8px; display: grid; place-items: center; background: var(--highlight-3); color: var(--text-secondary); flex: none; }
    h1.ui-card-title { font-size: 17px; }
    .rows { border-top: 1px solid var(--border); }
    .port { max-width: 120px; }
    .tools { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; font-size: 13px; }
    .tools li { display: grid; grid-template-columns: 14px max-content 1fr; align-items: baseline; gap: 8px; color: var(--green, var(--text-primary)); }
    .tools li :global(svg) { align-self: center; }
    .tools li b { color: var(--text-primary); font-weight: 500; }
    .tools li.off { color: var(--text-secondary); }
    .tools li.off b { color: var(--text-secondary); }
    .err { color: var(--red); }
    @media (max-width: 640px) { .setup :global(.ui-form-row) { grid-template-columns: 1fr; gap: 8px; } }
</style>
