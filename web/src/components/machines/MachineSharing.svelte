<script>
    import { copyText } from '../../lib/clipboard.js';
    import { Loader2, Copy, Check, Plus, Trash2, Pencil, KeyRound, Globe, ShieldCheck } from 'lucide-svelte';
    import { api, busy, shareMachine, unshareMachine } from '../../lib/machines.js';
    import { refreshMachines } from '../../lib/stores.js';
    import { vmUrl, vmHost } from '../../lib/vmref.js';
    import StatusPill from '../ui/StatusPill.svelte';
    import ActionMenu from '../ui/ActionMenu.svelte';
    import AddKeyDialog from './AddKeyDialog.svelte';
    import { presetOf, permSummary, isRoot, expired } from '../../lib/perms.js';
    import { ago } from '../../lib/tailscale.js';

    export let data;
    export let m;
    export let job;
    export let ref = null;      // the machine's ref (vmref.js); its name on Arrakis
    export let openPerson = () => {};

    $: name = ref || m.name;
    $: running = m.state === 'running';
    $: b = $busy[name];
    $: sharing = job?.kind === 'share' && job.state === 'creating';
    $: domain = data.sharing?.domain || 'your domain';
    $: share = m.share;
    $: user = share?.user || m.username || 'root';
    $: host = share?.hostname || (vmHost(name) ? `${m.name}-${vmHost(name)}.${domain}` : `${m.name}.${domain}`);

    // ---- keys ------------------------------------------------------------------------
    let adding = false, confirmUnshare = false, removing = null, confirmKey = null;
    async function onShare() { await shareMachine(name); }
    async function removeKey(k) {
        removing = k.fp;
        const r = await api(vmUrl(name, '/share/keys'), { method: 'DELETE', body: JSON.stringify({ fp: k.fp }) });
        removing = null; confirmKey = null;
        if (r.status === 'success') { window.showToast?.('Key removed'); refreshMachines(name); }
    }
    let renaming = null, labelText = '';
    const keyName = (k) => k.label || k.comment || 'Unnamed key';
    $: schema = data.sharing?.permissions;
    $: cores = m.cpu || data.pool?.cpu || 0;
    async function saveLabel(k) {
        const r = await api(vmUrl(name, '/share/keys'), { method: 'PATCH', body: JSON.stringify({ fp: k.fp, label: labelText }) });
        if (r.status === 'success') { renaming = null; refreshMachines(name); }
    }
    const since = (t) => t ? new Date(t * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—';

    // ---- connect instructions --------------------------------------------------------
    let os = 'mac';
    const OSES = [{ id: 'mac', label: 'macOS' }, { id: 'linux', label: 'Linux' }, { id: 'windows', label: 'Windows' }];
    $: steps = [
        {
            title: 'Install cloudflared',
            hint: 'Cloudflare\'s connector. SSH goes through it instead of straight to an IP.',
            cmd: {
                mac: 'brew install cloudflared',
                linux: 'curl -fsSL -o cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$(uname -m | sed \'s/x86_64/amd64/;s/aarch64/arm64/\')" && sudo install cloudflared /usr/local/bin/ && rm cloudflared',
                windows: 'winget install --id Cloudflare.cloudflared',
            }[os],
        },
        {
            title: 'Tell SSH to use it (once)',
            hint: `Covers every machine shared on ${domain}, not just this one.`,
            cmd: {
                mac: `printf '\\nHost *.${domain}\\n  ProxyCommand cloudflared access ssh --hostname %%h\\n' >> ~/.ssh/config`,
                linux: `mkdir -p ~/.ssh && printf '\\nHost *.${domain}\\n  ProxyCommand cloudflared access ssh --hostname %%h\\n' >> ~/.ssh/config`,
                windows: `New-Item -ItemType Directory -Force $HOME\\.ssh | Out-Null; Add-Content $HOME\\.ssh\\config "\`nHost *.${domain}\`n  ProxyCommand cloudflared.exe access ssh --hostname %h"`,
            }[os],
        },
        {
            title: 'Send the owner your public key',
            hint: 'Creates a key if there isn\'t one yet, then prints the public half. Send that line; it\'s safe to share.',
            cmd: {
                mac: '[ -f ~/.ssh/id_ed25519.pub ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519; cat ~/.ssh/id_ed25519.pub',
                linux: '[ -f ~/.ssh/id_ed25519.pub ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519; cat ~/.ssh/id_ed25519.pub',
                windows: 'if (!(Test-Path $HOME\\.ssh\\id_ed25519.pub)) { ssh-keygen -t ed25519 }; Get-Content $HOME\\.ssh\\id_ed25519.pub',
            }[os],
        },
        { title: 'Connect', hint: 'Use the username the owner added for you (shown next to your key on their dashboard).', cmd: `ssh <username>@${host}` },
    ];
    $: osLabel = OSES.find(o => o.id === os).label;
    $: message = `How to get into ${m.name} (${osLabel}):\n\n` + steps.map((s, i) => `${i + 1}. ${s.title}\n   ${s.cmd}`).join('\n\n') + '\n';

    let copied = null;
    async function copy(text, id) {
        try { await copyText(text); copied = id; setTimeout(() => { if (copied === id) copied = null; }, 1200); } catch (e) {}
    }
</script>

{#if !share}
    <section class="ui-card">
        <div class="ui-card-head">
            <div><h2 class="ui-card-title">Share over SSH</h2><p class="ui-card-desc">Gives {m.name} a public address, <span class="ui-mono">{host}</span>, that people can SSH into once you add their key. Nothing is reachable until you share it, and stopping removes the address and the keys again.</p></div>
            <StatusPill state={sharing ? 'joining' : ''} label={sharing ? 'Sharing…' : 'Not shared'} />
        </div>
        <div class="ui-card-foot">
            {#if job?.kind === 'share' && job.state === 'error'}<span class="err">Sharing failed: {job.message || 'unknown error'}</span>
            {:else if !data.sharing?.logged_in}<span>Save a Cloudflare API token in <span class="ui-mono">~/.homelab_cloudflare.json</span> first.</span>
            {:else if !running}<span>Start {m.name} to share it.</span>
            {:else if !m.isolated}<span>{m.name} can currently see your Mac's files. Sharing turns that off first (restarts {m.name} once), then installs SSH (keys only) and the permission system.</span>
            {:else}<span>Installs an SSH server in {m.name} if needed (keys only, no passwords) and the permission system. You add people next.</span>{/if}
            <span class="ui-btns"><button class="ui-btn sm primary" disabled={!running || !data.sharing?.logged_in || !!b || sharing} on:click={onShare}>{#if b === 'share' || sharing}<Loader2 size={13} class="ui-spin" />{/if}{sharing ? 'Sharing…' : 'Share'}</button></span>
        </div>
    </section>
{:else}
    <section class="ui-card">
        <div class="ui-card-head keys-head">
            <div class="keys-headl">
                <div class="keys-ttl"><h2 class="ui-card-title">Keys</h2><StatusPill state="connected" label="Shared" /></div>
                {#if confirmUnshare}
                    <p class="addr-warn">Stop sharing {m.name}? The address goes offline{share.keys.length ? ` and ${share.keys.length === 1 ? 'its key is' : `all ${share.keys.length} keys are`} removed` : ''}.</p>
                {:else}
                    <div class="addr-left">
                        <span class="addr-ic"><Globe size={14} /></span>
                        <code class="addr-name">{host}</code>
                        <button class="addr-copy" on:click={() => copy(host, 'host')} title="Copy hostname" aria-label="Copy hostname">{#if copied === 'host'}<Check size={13} />{:else}<Copy size={13} />{/if}</button>
                        <span class="addr-since">· Shared {since(share.since)}</span>
                    </div>
                {/if}
            </div>
            <div class="ui-btns keys-actions">
                {#if confirmUnshare}
                    <button class="ui-btn sm" on:click={() => confirmUnshare = false}>Cancel</button>
                    <button class="ui-btn sm danger" on:click={() => { confirmUnshare = false; unshareMachine(name); }}>Stop sharing</button>
                {:else}
                    <button class="ui-btn sm danger-outline" disabled={!!b || sharing} on:click={() => confirmUnshare = true}>{#if b === 'unshare'}<Loader2 size={13} class="ui-spin" />{/if}Stop sharing</button>
                    <button class="ui-btn sm" disabled={!running || sharing} title={running ? '' : `Start ${m.name} to add keys`} on:click={() => adding = true}><Plus size={13} /> Add key</button>
                {/if}
            </div>
        </div>
        <div class="ui-tbl-wrap" style="border-top: 1px solid var(--border)">
            {#if share.keys.length}
                <table class="ui-tbl keys">
                    <thead><tr><th>Name</th><th>Permissions</th><th class="c-sm">Added</th><th>Last login</th><th class="c-md">Fingerprint</th><th class="shrink"></th></tr></thead>
                    <tbody>
                        {#each share.keys as k (k.fp)}
                            {#if confirmKey === k.fp}
                                <tr class="confirm">
                                    <td colspan="6">
                                        <div class="confirm-row">
                                            <span>Remove <b>{keyName(k)}</b>? It can't log in to {m.name} any more.</span>
                                            <span class="ui-btns"><button class="ui-btn sm" on:click={() => confirmKey = null}>Cancel</button><button class="ui-btn sm danger" disabled={!!removing} on:click={() => removeKey(k)}>{#if removing === k.fp}<Loader2 size={13} class="ui-spin" />{/if}Remove key</button></span>
                                        </div>
                                    </td>
                                </tr>
                            {:else}
                                <tr>
                                    <td>
                                        {#if renaming === k.fp}
                                            <form class="rename" on:submit|preventDefault={() => saveLabel(k)}>
                                                <!-- svelte-ignore a11y-autofocus -->
                                                <input class="ui-input sm" bind:value={labelText} placeholder={k.comment || 'e.g. Stilgar\'s laptop'} maxlength="60" autofocus on:keydown={e => e.key === 'Escape' && (renaming = null)} />
                                                <button class="ui-btn sm primary" type="submit">Save</button>
                                                <button class="ui-btn sm" type="button" on:click={() => renaming = null}>Cancel</button>
                                            </form>
                                        {:else}
                                            <div class="kn">
                                                <span class="ic"><KeyRound size={14} /></span>
                                                <div class="kt">
                                                    {#if k.perms}<button class="nm link" title={k.comment && k.comment !== keyName(k) ? k.comment : ''} on:click={() => openPerson(k.user)}>{keyName(k)}</button>{:else}<span class="nm" title={k.comment && k.comment !== keyName(k) ? k.comment : ''}>{keyName(k)}</span>{/if}
                                                    <span class="sub ui-mono">{k.user}@{m.name}</span>
                                                </div>
                                            </div>
                                        {/if}
                                    </td>
                                    <td class="perm">
                                        {#if k.perms}
                                            <button class="perm-btn" title="Open {k.user}'s permissions" on:click={() => openPerson(k.user)}>
                                                <span class="pn" class:root={isRoot(k.perms)}>{presetOf(k.perms, schema)?.label || 'Custom'}{#if expired(k.perms)} <span class="exp">· expired</span>{/if}</span>
                                                <span class="ps">{permSummary(k.perms, schema)}</span>
                                            </button>
                                        {:else}<span class="ui-dim" title="Logs in as the machine's own user; its rights aren't managed here">Machine's own user</span>{/if}
                                    </td>
                                    <td class="c-sm ui-dim" title={k.added ? since(k.added) : 'Added before dates were recorded'}>{k.added ? ago(k.added * 1000) : '—'}</td>
                                    <td title={k.last_login ? since(k.last_login) : ''}>
                                        {#if !share.logins_known}<span class="ui-dim">Unknown while stopped</span>
                                        {:else if k.last_login}{ago(k.last_login * 1000)}
                                        {:else}<span class="ui-dim">Never</span>{/if}
                                    </td>
                                    <td class="c-md"><span class="fp" title={k.fp}><span class="ty">{k.type.toUpperCase()}</span><span class="ui-mono ui-dim">{k.fp.slice(7, 19)}…</span></span></td>
                                    <td class="shrink">
                                        <ActionMenu label="Key actions" items={[
                                            ...(k.perms ? [{ label: 'Permissions', icon: ShieldCheck, onClick: () => openPerson(k.user) }] : []),
                                            { label: 'Rename', icon: Pencil, onClick: () => { renaming = k.fp; labelText = k.label || ''; } },
                                            { label: 'Copy login command', icon: Copy, onClick: () => copy(`ssh ${k.user}@${host}`, 'fp') },
                                            { label: 'Copy fingerprint', icon: Copy, onClick: () => copy(k.fp, 'fp') },
                                            { label: running ? 'Remove key' : `Start ${m.name} to remove`, icon: Trash2, danger: true, divider: true, disabled: !running, onClick: () => confirmKey = k.fp },
                                        ]} />
                                    </td>
                                </tr>
                            {/if}
                        {/each}
                    </tbody>
                </table>
            {:else}
                <div class="ui-empty">
                    <div class="empty-t">No keys yet</div>
                    <div>Nobody can log in until you add one. Send the person the instructions below; step 3 gives you their key.</div>
                    <button class="ui-btn sm empty-btn" disabled={!running} on:click={() => adding = true}><Plus size={13} /> Add key</button>
                </div>
            {/if}
        </div>
    </section>

    <section class="ui-card" id="connect">
        <div class="ui-card-head">
            <div><h2 class="ui-card-title">How to connect</h2><p class="ui-card-desc">What the other person runs on their computer. Copy it all and send it to them.</p></div>
            <button class="ui-btn sm" on:click={() => copy(message, 'all')}>{#if copied === 'all'}<Check size={13} /> Copied{:else}<Copy size={13} /> Copy instructions{/if}</button>
        </div>
        <div class="os"><div class="ui-seg">{#each OSES as o}<button class:on={os === o.id} on:click={() => os = o.id}>{o.label}</button>{/each}</div></div>
        <ol class="steps">
            {#each steps as st, i}
                <li>
                    <span class="n">{i + 1}</span>
                    <div class="body">
                        <div class="t">{st.title}</div>
                        <div class="ui-hint">{st.hint}</div>
                        <div class="cmd"><code>{st.cmd}</code><button on:click={() => copy(st.cmd, i)} aria-label="Copy" title="Copy">{#if copied === i}<Check size={13} />{:else}<Copy size={13} />{/if}</button></div>
                    </div>
                </li>
            {/each}
        </ol>
    </section>
{/if}

{#if share}
    <AddKeyDialog bind:open={adding} {name} {host} {schema} onAdded={(u) => openPerson(u)} />
{/if}

<style>
    .err { color: var(--red); }
    .keys-headl { display: grid; gap: 7px; min-width: 0; }
    .keys-ttl { display: flex; align-items: center; gap: 10px; }
    .keys-actions { flex-shrink: 0; flex-wrap: wrap; justify-content: flex-end; }
    .addr-left { display: flex; align-items: center; gap: 6px; min-width: 0; }
    .addr-ic { color: var(--text-secondary); display: inline-flex; flex-shrink: 0; }
    .addr-name { font-family: 'JetBrains Mono', monospace; font-size: 12.5px; color: var(--text-secondary); overflow-wrap: anywhere; }
    .addr-copy { width: 24px; height: 24px; border-radius: 5px; display: inline-flex; align-items: center; justify-content: center; color: var(--text-secondary); cursor: pointer; flex-shrink: 0; }
    .addr-copy:hover { background: var(--highlight-10); color: var(--text-primary); }
    .addr-since { font-size: 12px; color: var(--text-secondary); white-space: nowrap; }
    .addr-warn { margin: 0; font-size: 13px; color: var(--text-secondary); }
    @media (max-width: 640px) {
        .keys-head { flex-direction: column; align-items: stretch; gap: 10px; }
        .keys-actions { justify-content: flex-start; }
        .addr-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    }
    .keys .kn { display: flex; align-items: center; gap: 10px; min-width: 0; }
    .keys .ic { width: 28px; height: 28px; border-radius: 6px; display: grid; place-items: center; background: var(--highlight-10); color: var(--text-secondary); flex-shrink: 0; }
    .keys .kt { display: grid; min-width: 0; }
    .keys .nm { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .keys .sub { font-size: 11.5px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .keys .fp { display: inline-flex; align-items: center; gap: 8px; font-size: 12px; }
    .keys .ty { font-size: 10.5px; font-weight: 600; letter-spacing: 0.04em; color: var(--text-secondary); padding: 2px 6px; border: 1px solid var(--border-strong); border-radius: 4px; }
    .perm-btn { display: grid; gap: 1px; text-align: left; max-width: 340px; padding: 3px 6px; margin: -3px -6px; border-radius: 6px; cursor: pointer; }
    .perm-btn:hover { background: var(--highlight-10); }
    .keys .nm.link { text-align: left; cursor: pointer; }
    .keys .nm.link:hover { text-decoration: underline; }
    .perm .pn { font-weight: 500; color: var(--text-primary); }
    .perm .pn.root { color: var(--red); }
    .perm .exp { color: var(--red); font-weight: 400; }
    .perm .ps { font-size: 11.5px; color: var(--text-secondary); white-space: normal; line-height: 1.35; }
    .keys .rename { display: flex; gap: 6px; align-items: center; }
    .keys .rename input { width: 220px; height: 28px; font-size: 13px; }
    .keys tr.confirm td { background: var(--highlight-3); }
    .confirm-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; white-space: normal; font-size: 13px; }
    .empty-btn { margin-top: 14px; }
    .empty-t { font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
    .os { padding: 12px 20px 0; border-top: 1px solid var(--border); }
    .steps { list-style: none; margin: 0; padding: 6px 20px 18px; display: grid; gap: 0; }
    .steps li { display: grid; grid-template-columns: 24px 1fr; gap: 12px; padding: 12px 0; border-top: 1px solid var(--border); }
    .steps li:first-child { border-top: none; }
    .n { width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; font-size: 12px; font-weight: 600; background: var(--accent-soft); color: var(--accent); }
    .body { display: grid; gap: 4px; min-width: 0; }
    .t { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
    .cmd { display: flex; align-items: flex-start; gap: 6px; margin-top: 4px; padding: 8px 8px 8px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--highlight-3); }
    .cmd code { flex: 1; min-width: 0; font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text-primary); }
    .cmd button { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 4px; color: var(--text-secondary); cursor: pointer; flex-shrink: 0; }
    .cmd button:hover { background: var(--highlight-10); color: var(--text-primary); }
    @media (max-width: 768px) { .os, .steps { padding-left: 14px; padding-right: 14px; } }
</style>
