// navigator.clipboard only exists on secure origins (https, localhost); the dashboard is
// usually opened over plain http on a LAN/tailnet address, so fall back to execCommand.
export async function copyText(text) {
    if (window.isSecureContext && navigator.clipboard) {
        try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall through */ }
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { /* ignore */ }
    ta.remove();
    if (!ok) throw new Error('copy failed');
    return true;
}
