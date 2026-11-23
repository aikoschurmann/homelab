<script>
    import Modal from './ui/Modal.svelte';
    import { webLinks, editing, setLink, removeLink, guessUrl, absUrl } from '../lib/weblinks.js';

    // Edits one web UI shortcut; opened from anywhere with editLink(svc) / editLink()
    let name = '', url = '', pinned = false, key = null, svc = null, guess = null;
    $: if ($editing) init($editing);
    function init(e) {
        svc = e.svc; key = e.key || `custom:${Date.now().toString(36)}`;
        const l = $webLinks[key] || {};
        guess = svc ? guessUrl(svc) : null;
        name = l.name || ''; url = l.url || ''; pinned = !!l.pinned;
    }
    $: custom = !svc && !key?.startsWith('container:') && !key?.startsWith('daemon:');
    $: isNew = !$webLinks[key];
    $: effective = url.trim() || guess;
    $: canSave = custom ? !!(name.trim() && url.trim()) : !!effective;
    const close = () => editing.set(null);

    async function saveIt() {
        if (!canSave) return;
        await setLink(key, { name: name.trim() || null, url: url.trim() || null, pinned, off: null });
        window.showToast?.('Shortcut saved');
        close();
    }
    // a service without a web UI keeps an "off" mark so the guess doesn't come back
    async function remove() {
        custom ? await removeLink(key) : await setLink(key, { off: true, pinned: null, url: null, name: null });
        window.showToast?.(custom ? 'Shortcut removed' : `${svc?.name || 'Service'}: web UI removed`);
        close();
    }
</script>

<Modal open={!!$editing} onClose={close} width={420} title={custom ? (isNew ? 'Add link' : 'Edit link') : svc?.name || 'Web UI'}>
    <form class="f" on:submit|preventDefault={saveIt}>
        <div class="ui-field">
            <label for="wl-name">Name</label>
            <input id="wl-name" class="ui-input" bind:value={name} placeholder={svc?.name || 'Router'} />
        </div>
        <div class="ui-field">
            <label for="wl-url">Address</label>
            <input id="wl-url" class="ui-input mono" bind:value={url} placeholder={guess || ':8080 or http://192.168.1.1'} spellcheck="false" autocapitalize="off" />
            {#if effective}<span class="to ui-mono" title=":port means this dashboard's own address">→ {absUrl(effective)}</span>{/if}
        </div>
        <label class="sw-row">
            <span class="sw" class:on={pinned}><input type="checkbox" bind:checked={pinned} /><i></i></span>
            Show on Overview
        </label>
        <button type="submit" hidden aria-label="Save"></button>
    </form>
    <svelte:fragment slot="footer">
        {#if !custom || !isNew}<button class="ui-btn danger-outline" style="margin-right: auto" on:click={remove}>{custom ? 'Remove' : 'No web UI'}</button>{/if}
        <button class="ui-btn" on:click={close}>Cancel</button>
        <button class="ui-btn primary" disabled={!canSave} on:click={saveIt}>Save</button>
    </svelte:fragment>
</Modal>

<style>
    .f { display: flex; flex-direction: column; gap: 16px; padding-top: 4px; }
    .to { font-size: 12px; color: var(--text-secondary); overflow-wrap: anywhere; }
    .sw-row { display: inline-flex; align-items: center; gap: 10px; font-size: 13.5px; color: var(--text-primary); cursor: pointer; }
    .sw { position: relative; width: 36px; height: 20px; flex-shrink: 0; }
    .sw input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: inherit; }
    .sw i { position: absolute; inset: 0; border-radius: 10px; background: var(--highlight-30); transition: background .15s; pointer-events: none; }
    .sw i::after { content: ''; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.25); transition: transform .15s; }
    .sw.on i { background: var(--accent-fill); }
    .sw.on i::after { transform: translateX(16px); }
</style>
