// Drag to reorder a list or grid, with mouse or touch. Rows carry data-id (and data-n for
// their order when they sit in wrappers, e.g. two columns); [data-handle] starts a drag;
// [data-nodrag] inside keeps its own clicks.
// While dragging, a copy of the row follows the pointer and the list itself is reordered
// live (onMove(ids)), with the row left in its new place as a faded dashed outline, so the
// page reflows exactly as it will. Where it goes is worked out against the rows' places when
// the drag began, so the reflow can't make it flip back and forth. onDrop(ids) on release.
// A press that doesn't move a few pixels stays a click.
export function sortable(node, opts) {
    let o = opts;
    node.dataset.sortRoot = '';
    const rootOf = (r) => r.parentElement?.closest('[data-sort-root]');
    const rows = () => [...node.querySelectorAll('[data-id]')].filter(r => rootOf(r) === node).sort((a, b) => (+a.dataset.n || 0) - (+b.dataset.n || 0));

    let pending = null, el = null, id = null, sx = 0, sy = 0, others = [], ids0 = [], cur = [], clone = null, cb = null;

    function down(e) {
        if (e.button > 0) return;
        const h = e.target.closest('[data-handle]');
        const row = h && h.closest('[data-id]');
        const nd = e.target.closest('[data-nodrag]');
        if (!row || rootOf(row) !== node || (nd && nd !== node && node.contains(nd) && !nd.contains(node))) return;
        pending = row; sx = e.clientX; sy = e.clientY;
        window.addEventListener('pointermove', move, { passive: false });
        window.addEventListener('pointerup', up);
        window.addEventListener('pointercancel', up);
    }

    function start() {
        el = pending; id = el.dataset.id;
        const rs = rows();
        ids0 = rs.map(r => r.dataset.id); cur = ids0;
        others = rs.filter(r => r !== el).map(r => { const b = r.getBoundingClientRect(); return { id: r.dataset.id, cx: b.left + b.width / 2, cy: b.top + b.height / 2, h: b.height }; });
        cb = el.getBoundingClientRect();
        clone = el.cloneNode(true);
        Object.assign(clone.style, { position: 'fixed', left: cb.left + 'px', top: cb.top + 'px', width: cb.width + 'px', height: cb.height + 'px', margin: 0, zIndex: 1000, pointerEvents: 'none', opacity: '.92', boxShadow: '0 18px 40px rgba(0,0,0,.4)', transition: 'none', borderColor: 'var(--accent)' });
        clone.classList.add('dragging');
        document.body.appendChild(clone);
        placeholder(el, true);
        document.body.style.userSelect = 'none';
    }

    function placeholder(r, on) {
        Object.assign(r.style, on ? { opacity: '.35', outline: '2px dashed var(--accent)', outlineOffset: '-2px' } : { opacity: '', outline: '', outlineOffset: '' });
    }

    // the rows that come before the pointer: above it, or level with it and to its left
    function targetAt(px, py) {
        return others.filter(x => Math.abs(x.cy - py) <= x.h / 2 ? x.cx < px : x.cy < py).length;
    }

    function move(e) {
        if (!el && pending) {
            if (Math.hypot(e.clientX - sx, e.clientY - sy) < 6) return;
            start();
        }
        if (!el) return;
        e.preventDefault();
        clone.style.transform = `translate(${e.clientX - sx}px, ${e.clientY - sy}px)`;
        const t = targetAt(e.clientX, e.clientY);
        const next = others.map(x => x.id);
        next.splice(t, 0, id);
        if (next.join() !== cur.join()) {
            cur = next;
            o.onMove?.(next);
            // the row is re-rendered in its new place; keep it outlined there
            requestAnimationFrame(() => { const r = rows().find(x => x.dataset.id === id); if (r && r !== el) { placeholder(el, false); el = r; placeholder(el, true); } });
        }
    }

    function up() {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
        if (el) {
            clone?.remove(); clone = null;
            placeholder(el, false);
            document.body.style.userSelect = '';
            // swallow the click that ends a drag
            node.addEventListener('click', (c) => { c.stopPropagation(); c.preventDefault(); }, { capture: true, once: true });
            if (cur.join() !== ids0.join()) o.onDrop?.(cur);
        }
        el = null; pending = null; id = null;
    }

    node.addEventListener('pointerdown', down);
    return {
        update(n) { o = n; },
        destroy() { node.removeEventListener('pointerdown', down); up(); },
    };
}
