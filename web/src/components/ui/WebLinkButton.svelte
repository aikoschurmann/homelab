<script>
    import { Pin, PinOff, Link, ExternalLink } from 'lucide-svelte';
    import { webLinks, linkOf, absUrl, setLink, editLink } from '../../lib/weblinks.js';
    import ActionMenu from './ActionMenu.svelte';

    // ⋯ per service: open its web UI, pin it to the Overview, or set the address
    export let svc;
    $: url = svc ? absUrl(linkOf($webLinks, svc)) : null;
    $: pinned = !!$webLinks[svc?.key]?.pinned;
    $: items = [
        url ? { label: 'Open web UI', icon: ExternalLink, onClick: () => window.open(url, '_blank', 'noopener,noreferrer') } : null,
        url ? { label: pinned ? 'Unpin from Overview' : 'Pin to Overview', icon: pinned ? PinOff : Pin, onClick: () => setLink(svc.key, { pinned: !pinned }) } : null,
        { label: url ? 'Change address…' : 'Add web UI…', icon: Link, onClick: () => editLink(svc), divider: !!url },
    ];
</script>

<ActionMenu {items} label="Web UI for {svc.name}" />
