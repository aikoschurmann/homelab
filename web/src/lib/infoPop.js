// Svelte action for an ⓘ button holding a `.info-pop` tooltip.
// - Hidden tooltips use display:none, so they never widen the page.
// - When shown, the tooltip is position:fixed under the button and clamped to the viewport.
//   Fixed boxes don't count toward the page's scroll width, so even the frame before it is
//   placed can't make a phone scroll sideways (an absolute one near the right edge did).
// - Tapping toggles it (phones have no hover, and Safari doesn't focus buttons on tap).
export function infoPop(node) {
    const pop = () => node.querySelector('.info-pop');
    function place() {
        const p = pop();
        if (!p) return;
        const vw = document.documentElement.clientWidth;
        const b = node.getBoundingClientRect();
        const w = Math.min(280, vw - 24);
        Object.assign(p.style, {
            position: 'fixed',
            width: `${w}px`,
            maxWidth: 'none',
            left: `${Math.round(Math.max(12, Math.min(b.left - 10, vw - 12 - w)))}px`,
            top: `${Math.round(b.bottom + 8)}px`,
        });
    }
    function toggle(e) {
        e.preventDefault();
        e.stopPropagation();
        place();
        node.classList.toggle('open');
    }
    function outside(e) {
        if (!node.contains(e.target)) node.classList.remove('open');
    }
    // a fixed tooltip doesn't follow the page, so close a tapped one on scroll
    function scrolled() {
        if (node.classList.contains('open')) node.classList.remove('open');
        place();
    }
    node.addEventListener('pointerenter', place);
    node.addEventListener('focus', place);
    node.addEventListener('click', toggle);
    document.addEventListener('click', outside);
    window.addEventListener('scroll', scrolled, { capture: true, passive: true });
    return {
        destroy() {
            node.removeEventListener('pointerenter', place);
            node.removeEventListener('focus', place);
            node.removeEventListener('click', toggle);
            document.removeEventListener('click', outside);
            window.removeEventListener('scroll', scrolled, { capture: true });
        },
    };
}
