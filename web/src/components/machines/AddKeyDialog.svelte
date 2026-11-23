<script>
    import { Loader2, KeyRound, AlertCircle, Copy, Check } from 'lucide-svelte';
    import Modal from '../ui/Modal.svelte';
    import { applyPreset } from '../../lib/perms.js';
    import { copyText } from '../../lib/clipboard.js';
    import { refreshMachines } from '../../lib/stores.js';
    import { vmUrl, vmName } from '../../lib/vmref.js';

    export let open = false;
    export let name;        // machine ref (vmref.js)
    export let schema = null;   // data.sharing.permissions
    export let host = '';       // <name>.<domain>, for the connect preview
    export let onAdded = () => {};

    let label = '', key = '', saving = false, error = '', ta, preset = 'guest';
    let username = '', userEdited = false;
    const cleanUser = (s) => s.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^[^a-z]+/, '').replace(/[-_]+$/, '').slice(0, 32);
    // one line like the other inputs, growing to fit a pasted key (RSA keys run several lines)
    function grow() { if (!ta) return; ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 2 + 'px'; }
    $: if (open) reset();
    function reset() { label = ''; key = ''; error = ''; saving = false; username = ''; userEdited = false; preset = schema?.presets?.[0]?.id || 'guest'; }

    // Until the owner types a username, keep it in sync with the label (or the key's own
    // comment). The server validates/dedupes it and has the last word.
    $: if (!userEdited) username = cleanUser(label || info?.comment || '') || '';

    // What the pasted text is, checked as you type so problems show before saving
    const KEY_RE = /^(ssh-(?:ed25519|rsa|dss)|ecdsa-sha2-nistp\d+|sk-[\w@.-]+)\s+([A-Za-z0-9+/]+={0,3})(?:\s+(.*))?$/;
    $: text = key.trim();
    $: lines = text ? text.split(/\r?\n/).filter(l => l.trim()) : [];
    $: parsed = lines.length === 1 ? lines[0].trim().match(KEY_RE) : null;
    $: problem = !text ? ''
        : text.startsWith('-----BEGIN') ? 'This is a private key. It must never leave their computer: ask for the line that starts with ssh-ed25519 instead.'
        : lines.length > 1 ? 'Paste one key at a time.'
        : !parsed ? 'This isn\'t an SSH public key. It should look like ssh-ed25519 AAAA… name@computer.'
        : parsed[2].length < 40 ? 'This key looks cut off. Copy the whole line.'
        : '';
    $: info = parsed && !problem ? { type: parsed[1].replace(/^ssh-/, '').toUpperCase(), comment: parsed[3] || '' } : null;

    async function save() {
        saving = true; error = '';
        const r = await fetch(vmUrl(name, '/share/keys'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: text, label: label || info?.comment || '', perms: applyPreset(schema?.presets?.find(p => p.id === preset)), username }) })
            .then(r => r.json()).catch(e => ({ status: 'error', message: String(e) }));
        saving = false;
        if (r.status !== 'success') { error = r.message || 'Could not add the key'; return; }
        const who = r.user && host ? `${r.user}@${host}` : (label || info?.comment || 'It');
        window.showToast?.(`Key added — ${who} can log in now`);
        await refreshMachines(name); open = false; onAdded(r.user);
    }

    const GET_KEY = '[ -f ~/.ssh/id_ed25519.pub ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519; cat ~/.ssh/id_ed25519.pub';
    let copied = false;
    async function copyCmd() { try { await copyText(GET_KEY); copied = true; setTimeout(() => copied = false, 1200); } catch (e) {} }
</script>

<Modal bind:open title="Add a key" width={540} description="Adds one person or device to {vmName(name)} with its own login user and its own permissions.">
    <form class="form" id="add-key-form" on:submit|preventDefault={() => info && username && !saving && save()}>
        <div class="field">
            <label class="ui-label" for="ak-key">Public key</label>
            <!-- svelte-ignore a11y-autofocus -->
            <textarea id="ak-key" class="ui-input ui-mono" class:bad={problem} rows="1" spellcheck="false" autocomplete="off" autofocus
                bind:this={ta} on:input={grow}
                placeholder="ssh-ed25519 AAAAC3Nza… stilgar@laptop" bind:value={key}></textarea>
            {#if problem}
                <div class="msg bad"><AlertCircle size={14} />{problem}</div>
            {:else if info}
                <div class="msg ok"><KeyRound size={14} /><span class="ty">{info.type}</span>{info.comment ? `Key for ${info.comment}` : 'Valid public key'}</div>
            {:else}
                <div class="ui-hint">Ask them to run this and send you the line it prints (macOS and Linux; the Sharing tab has Windows too):</div>
                <div class="cmd"><code>{GET_KEY}</code><button type="button" on:click={copyCmd} aria-label="Copy" title="Copy">{#if copied}<Check size={13} />{:else}<Copy size={13} />{/if}</button></div>
            {/if}
        </div>
        <div class="field">
            <label class="ui-label" for="ak-label">Name <span class="ui-dim">(optional)</span></label>
            <input id="ak-label" class="ui-input" maxlength="60" placeholder={info?.comment || 'e.g. Stilgar\'s laptop'} bind:value={label} />
            <div class="ui-hint">So you can tell keys apart later{info?.comment ? `; leave empty to use "${info.comment}"` : ''}.</div>
        </div>
        <div class="field">
            <label class="ui-label" for="ak-user">Username</label>
            <input id="ak-user" class="ui-input ui-mono" maxlength="32" placeholder="stilgar" value={username}
                on:input={(e) => { userEdited = true; username = cleanUser(e.target.value); e.target.value = username; }} />
            <div class="ui-hint">The Linux login name on {vmName(name)}. Lowercase letters, digits, <span class="ui-mono">-</span> and <span class="ui-mono">_</span>.</div>
        </div>
        {#if info && username}<div class="connects">Connects as <span class="ui-mono">{username}@{host || vmName(name)}</span></div>{/if}
        {#if schema}
            <div class="field">
                <span class="ui-label">Permissions</span>
                <div class="ui-seg pre">{#each schema.presets as pr}<button type="button" class:on={preset === pr.id} on:click={() => preset = pr.id}>{pr.label}</button>{/each}</div>
                <div class="ui-hint">{schema.presets.find(p => p.id === preset)?.desc} You can fine-tune everything on their page after adding.</div>
            </div>
        {/if}
        {#if error}<div class="msg bad"><AlertCircle size={14} />{error}</div>{/if}
    </form>
    <svelte:fragment slot="footer">
        <button class="ui-btn" type="button" on:click={() => open = false}>Cancel</button>
        <button class="ui-btn primary" type="submit" form="add-key-form" disabled={!info || !username || saving}>{#if saving}<Loader2 size={14} class="ui-spin" />{/if}Add key</button>
    </svelte:fragment>
</Modal>

<style>
    .form { display: grid; gap: 18px; }
    .field { display: grid; gap: 6px; }
    textarea { display: block; width: 100%; height: 34px; min-height: 34px; max-height: 180px; padding: 7px 10px; resize: none; overflow-y: auto; font-size: 12px; line-height: 18px; word-break: break-all; }
    textarea.bad { border-color: var(--red); }
    .msg { display: flex; align-items: flex-start; gap: 8px; font-size: 12.5px; line-height: 1.45; }
    .msg :global(svg) { flex-shrink: 0; margin-top: 1px; }
    .msg.bad { color: var(--red); }
    .msg.ok { color: var(--green); align-items: center; }
    .ty { font-size: 10.5px; font-weight: 600; letter-spacing: 0.04em; padding: 1px 6px; border: 1px solid currentColor; border-radius: 4px; }
    .pre { width: fit-content; flex-wrap: wrap; }
    .connects { margin-top: -10px; font-size: 12.5px; color: var(--text-secondary); }
    .connects .ui-mono { color: var(--text-primary); }
    .cmd { display: flex; align-items: flex-start; gap: 6px; padding: 8px 8px 8px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--highlight-3); }
    .cmd code { flex: 1; min-width: 0; font-family: 'JetBrains Mono', monospace; font-size: 11.5px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text-primary); }
    .cmd button { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 4px; color: var(--text-secondary); cursor: pointer; flex-shrink: 0; }
    .cmd button:hover { background: var(--highlight-10); color: var(--text-primary); }
</style>
