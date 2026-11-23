<script>
    // Arrakis on the tailnet: its addresses, key, exit node and the Tailscale client itself.
    import { ago, fmtDate } from '../../lib/tailscale.js';
    import CopyText from '../ui/CopyText.svelte';

    export let net;
    export let now = Date.now();

    $: s = net.devices.find(d => d.self) || net.self;
    $: keyDays = s.key_expiry ? Math.round((new Date(s.key_expiry) - now) / 86400000) : null;
</script>

<div class="ts-sub">
    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Addresses</h2><p class="ui-card-desc">How other devices reach Arrakis.</p></div></div>
        <dl class="ui-kv">
            <dt>Tailscale IP</dt><dd><CopyText text={s.ip} /></dd>
            {#if s.ipv6}<dt>IPv6</dt><dd><CopyText text={s.ipv6} /></dd>{/if}
            <dt>MagicDNS name</dt><dd><CopyText text={s.dns || s.name} /></dd>
            <dt>Tailnet</dt><dd><span class="ui-mono">{net.magic_dns}</span></dd>
            <dt>Nearest relay</dt><dd>{s.relay || '—'}</dd>
        </dl>
    </section>

    <section class="ui-card">
        <div class="ui-card-head"><div><h2 class="ui-card-title">Node</h2><p class="ui-card-desc">This machine's place on the tailnet.</p></div></div>
        <dl class="ui-kv">
            <dt>Status</dt><dd>{net.backend_state || '—'}</dd>
            <dt>Exit node</dt><dd>{s.exit_node_option ? 'Offered to the tailnet' : 'Not offered'}</dd>
            <dt>Node key</dt><dd>{s.key_expiry ? (keyDays > 0 ? `Expires in ${keyDays} days` : 'Expired') + ' · ' + fmtDate(s.key_expiry) : 'Never expires'}</dd>
            <dt>Joined</dt><dd>{s.created ? fmtDate(s.created) + ' · ' + ago(s.created, now) : '—'}</dd>
            <dt>Owner</dt><dd>{s.user || '—'}</dd>
            <dt>Tailscale</dt><dd>{net.version ? 'Version ' + net.version : '—'}</dd>
            <dt>Health</dt><dd>{net.health?.length ? net.health.join(' · ') : 'No warnings'}</dd>
        </dl>
    </section>
</div>
