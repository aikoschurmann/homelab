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

    function listen() {
        window.addEventListener('pointermove', move, { passive: false });
        window.addEventListener('pointerup', up);
        window.addEventListener('pointercancel', up);
    }
    // a list inside a row of another list (the tiles of a section): pulled well out of its own
    // list, the drag becomes a drag of the row it sits in (the section moves, the tiles go back)
    node.__begin = (row, x0, y0, e) => { pending = row; sx = x0; sy = y0; listen(); start(); move(e); };
    function outerRow() {
        const row = node.parentElement?.closest('[data-id]'), outer = row && rootOf(row);
        return outer?.__begin && row.matches('[data-handle]') ? { outer, row } : null;
    }
    function handOff(e) {
        const b = node.getBoundingClientRect(), M = 28;
        if (e.clientX > b.left - M && e.clientX < b.right + M && e.clientY > b.top - M && e.clientY < b.bottom + M) return false;
        const t = outerRow();
        if (!t) return false;
        const x0 = sx, y0 = sy;
        if (cur.join() !== ids0.join()) o.onMove?.(ids0);
        cancel();
        t.outer.__begin(t.row, x0, y0, e);
        return true;
    }
    function cancel() {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
        clone?.remove(); clone = null;
        if (el) placeholder(el, false);
        document.body.style.userSelect = ''; noAnchor(false); edgeSince = 0;
        el = null; pending = null; id = null; lock = null;
        if (raf) { cancelAnimationFrame(raf); raf = 0; }
        clearTimeout(candTimer); cand = null;
    }

    function down(e) {
        if (e.button > 0) return;
        const h = e.target.closest('[data-handle]');
        const row = h && h.closest('[data-id]');
        const nd = e.target.closest('[data-nodrag]');
        if (!row || rootOf(row) !== node || (nd && nd !== node && node.contains(nd) && !nd.contains(node))) return;
        pending = row; sx = e.clientX; sy = e.clientY;
        listen();
    }

    function start() {
        el = pending; id = el.dataset.id;
        const rs = rows();
        ids0 = rs.map(r => r.dataset.id); cur = ids0;
        others = rs.filter(r => r !== el).map(r => { const b = r.getBoundingClientRect(); return { id: r.dataset.id, cx: b.left + b.width / 2, cy: b.top + b.height / 2, h: b.height }; });
        cb = el.getBoundingClientRect();
        offX = sx - cb.left; offY = sy - cb.top;
        clone = el.cloneNode(true);
        Object.assign(clone.style, { position: 'fixed', left: cb.left + 'px', top: cb.top + 'px', width: cb.width + 'px', height: cb.height + 'px', margin: 0, zIndex: 1000, pointerEvents: 'none', opacity: '.92', boxShadow: '0 18px 40px rgba(0,0,0,.4)', transition: 'none', borderColor: 'var(--accent)' });
        clone.classList.add('dragging');
        if (el.matches('.tj-l, .tj-r')) clone.classList.add('sort-free');
        document.body.appendChild(clone);
        placeholder(el, true);
        document.body.style.userSelect = 'none';
        noAnchor(true);
    }

    // the browser keeps what is on screen in place when things above it change height (scroll
    // anchoring): while dragging, the reorder itself would scroll the page, so it's off
    function noAnchor(on) {
        const sc = scroller(), t = sc === window ? document.documentElement : sc;
        t.style.overflowAnchor = on ? 'none' : '';
    }

    function placeholder(r, on) {
        Object.assign(r.style, on ? { opacity: '.35', outline: '1px dashed var(--accent)', outlineOffset: '0px' } : { opacity: '', outline: '', outlineOffset: '' });
        // a tile merged with a neighbour moves as a card of its own (see .sort-free)
        r.classList.toggle('sort-free', on && r.matches('.tj-l, .tj-r'));
    }

    // Where it goes: by what is under the pointer NOW (rows change size as the order changes, so
    // the places they had when the drag began say little). Over the first half of a row: before
    // it; the second half: after it (halves left/right, or top/bottom for a row across the
    // page). Over a gap or its own placeholder: nothing changes. After a move relative to a
    // row, that row is ignored until the pointer has left it, so a reflow can't flip it back.
    let lock = null, lockX = 0, lockY = 0;

    // A grid of square cells (the metric widgets: [data-cells] = cells to a row, with __moveTo
    // and __commit from MetricsGrid): while the dragged widget is over its own grid, it moves to
    // the cell under it and the others move out of its way (no reordering); away from the grid,
    // it is an item of the list again (and the grid goes back as it was).
    let activeGrid = null, lastCell = '', offX = 0, offY = 0;
    // a cell counts once the pointer has rested on it a moment (as a list place does), so the
    // others don't jump on every cell passed on the way; letting go takes the cell at once
    let gridCand = '', gridTimer = 0;
    function gridTarget(px, py, now = false) {
        const g = el?.parentElement?.closest('[data-cells]');
        if (!g || !g.__moveTo || !el.dataset.span) return undefined;
        const b = g.getBoundingClientRect();
        const n = +g.dataset.cells, gap = parseFloat(getComputedStyle(g).columnGap) || 0, unit = (b.width - (n - 1) * gap) / n;
        // over the grid, or just under it (a new row)
        if (px < b.left - unit / 2 || px > b.right + unit / 2 || py < b.top - unit / 2 || py > b.bottom + unit * 0.6) {
            clearTimeout(gridTimer); gridCand = '';
            if (activeGrid) { activeGrid.__moveTo(null); activeGrid = null; lastCell = ''; }
            return undefined;
        }
        const [w] = el.dataset.span.split(' ').map(Number);
        // the cell its top-left corner is nearest, where it was picked up kept under the pointer
        const x = Math.max(0, Math.min(n - Math.min(w, n), Math.round((px - offX - b.left) / (unit + gap))));
        const y = g.__rowAt ? g.__rowAt(py - offY) : Math.max(0, Math.round((py - offY - b.top) / (unit + gap)));
        const key = x + ',' + y;
        const go = () => { gridCand = ''; if (!el) return; lastCell = key; activeGrid = g; g.__moveTo(el.dataset.mid, x, y); };
        if (key === lastCell) { clearTimeout(gridTimer); gridCand = ''; }
        else if (now) { clearTimeout(gridTimer); go(); }
        else if (key !== gridCand) { gridCand = key; clearTimeout(gridTimer); gridTimer = setTimeout(go, DWELL); }
        return null;
    }

    function targetAt(px, py, now = false) {
        const gt = gridTarget(px, py, now);
        if (gt !== undefined) return gt;
        if (performance.now() < settleAt) return null;
        const rs = rows().filter(r => r !== el);
        const ids = cur.filter(x => x !== id);
        // what can be dropped on: each row, but a line of rows of another kind than the dragged
        // one (data-group 'h|…' / 'p|…' vs its data-kind) as one block: above or below it
        const kind = el.dataset.kind || '', units = [], byGroup = {};
        for (const r of rs) {
            const g = r.dataset.group, b = r.getBoundingClientRect();
            if (g && g.split('|')[0] !== kind) {
                const u = byGroup[g];
                if (u) { u.last = r.dataset.id; u.b = { left: Math.min(u.b.left, b.left), right: Math.max(u.b.right, b.right), top: Math.min(u.b.top, b.top), bottom: Math.max(u.b.bottom, b.bottom) }; continue; }
                units.push(byGroup[g] = { key: g, first: r.dataset.id, last: r.dataset.id, b: { left: b.left, right: b.right, top: b.top, bottom: b.bottom }, block: true });
            } else units.push({ key: r.dataset.id, first: r.dataset.id, last: r.dataset.id, b });
        }
        for (const u of units) {
            const b = u.b;
            if (px < b.left || px > b.right || py < b.top || py > b.bottom) continue;
            if (u.key === lock && Math.hypot(px - lockX, py - lockY) < 32) return null;
            lock = null;
            const across = u.block || (b.right - b.left) > node.clientWidth * 0.75;
            const after = across ? py > (b.top + b.bottom) / 2 : px > (b.left + b.right) / 2;
            const t = after ? ids.indexOf(u.last) + 1 : ids.indexOf(u.first);
            return { ids: [...ids.slice(0, t), id, ...ids.slice(t)], rel: u.key };
        }
        // in the empty room to the right of the last of a line (a third host card, a lone half):
        // after it
        const side = rs.filter(r => !r.dataset.group || r.dataset.group.split('|')[0] === kind).map(r => [r, r.getBoundingClientRect()]).filter(([, b]) => py >= b.top && py <= b.bottom && px > b.right && b.width < node.clientWidth * 0.75)
            .sort((a, b) => b[1].right - a[1].right)[0];
        if (side && !rs.some(r => { const b = r.getBoundingClientRect(); return b.left > side[1].right && py >= b.top && py <= b.bottom; })) {
            const sid = side[0].dataset.id;
            if (sid !== lock || Math.hypot(px - lockX, py - lockY) >= 32) {
                const t = ids.indexOf(sid) + 1;
                return { ids: [...ids.slice(0, t), id, ...ids.slice(t)], rel: sid };
            }
        }
        // off the rows: past the last one goes at the end
        if (lock && !rs.some(r => r.dataset.id === lock && (b => px >= b.left && px <= b.right && py >= b.top && py <= b.bottom)(r.getBoundingClientRect()))) lock = null;
        const last = rs.at(-1)?.getBoundingClientRect();
        if (last && py > last.bottom && py > Math.max(...rs.map(r => r.getBoundingClientRect().bottom))) return { ids: [...ids, id], rel: null };
        return null;
    }

    // near the top or bottom of the window, the page scrolls (faster the closer), so a row can
    // be taken anywhere on a long page; the target is worked out again as the page moves
    let px = 0, py = 0, raf = 0;
    // what scrolls the page: the nearest parent that scrolls, else the window
    function scroller() {
        for (let p = node.parentElement; p && p !== document.body; p = p.parentElement) {
            const oy = getComputedStyle(p).overflowY;
            if ((oy === 'auto' || oy === 'scroll') && p.scrollHeight > p.clientHeight) return p;
        }
        return window;
    }
    // only right at the edge of what scrolls (not the window: the page scrolls under a top bar),
    // and only once the pointer has stayed there a moment, so passing near an edge on the way
    // to a row doesn't scroll the page out from under the pointer
    let edgeSince = 0;
    const EDGE = 48, EDGE_WAIT = 300;
    function scrollTick() {
        raf = 0;
        if (!el) return;
        const sc = scroller(), r = sc === window ? { top: 0, bottom: window.innerHeight } : sc.getBoundingClientRect();
        const top = Math.max(0, r.top), bottom = Math.min(window.innerHeight, r.bottom);
        const v = py < top + EDGE ? -(top + EDGE - py) : py > bottom - EDGE ? py - (bottom - EDGE) : 0;
        if (!v) { edgeSince = 0; return; }
        const now = performance.now();
        if (!edgeSince) edgeSince = now;
        if (now - edgeSince >= EDGE_WAIT) { sc.scrollBy(0, Math.max(-16, Math.min(16, v / 2))); retarget(); }
        raf = requestAnimationFrame(scrollTick);
    }
    // a place only counts once the pointer has rested on it a moment, so passing over rows on
    // the way (the first of a lower line, say) doesn't move anything
    let cand = null, candTimer = 0;
    const DWELL = 120;
    // the others glide from where they were to where they are now (FLIP), and no new place is
    // picked while they do (their boxes are moving under the pointer)
    let settleAt = 0;
    const GLIDE = 200;
    function apply(t) {
        cur = t.ids;
        lock = t.rel; lockX = px; lockY = py;
        const was = new Map(rows().map(r => [r.dataset.id, r.getBoundingClientRect()]));
        o.onMove?.(t.ids);
        settleAt = performance.now() + GLIDE;
        // the row is re-rendered in its new place; keep it outlined there
        requestAnimationFrame(() => {
            if (!id) return;
            const rs = rows();
            const r = rs.find(x => x.dataset.id === id); if (r && r !== el) { placeholder(el, false); el = r; placeholder(el, true); }
            for (const x of rs) {
                const a = was.get(x.dataset.id), b = x.getBoundingClientRect();
                if (!a) continue;
                const dx = a.left - b.left, dy = a.top - b.top;
                if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
                x.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: GLIDE, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' });
            }
            setTimeout(() => el && retarget(), GLIDE + 10);
        });
    }
    function retarget() {
        const t = targetAt(px, py);
        const k = t && t.ids.join() !== cur.join() ? t.ids.join() : null;
        if (k === cand) return;
        cand = k; clearTimeout(candTimer);
        if (!k) return;
        candTimer = setTimeout(() => {
            cand = null;
            if (!el) return;
            const t2 = targetAt(px, py);
            if (t2 && t2.ids.join() === k) apply(t2);
        }, DWELL);
    }

    function move(e) {
        if (!el && pending) {
            if (Math.hypot(e.clientX - sx, e.clientY - sy) < 6) return;
            start();
        }
        if (!el) return;
        e.preventDefault();
        if (handOff(e)) return;
        clone.style.transform = `translate(${e.clientX - sx}px, ${e.clientY - sy}px)`;
        px = e.clientX; py = e.clientY;
        retarget();
        if (!raf) raf = requestAnimationFrame(scrollTick);
    }

    function up() {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
        if (el) {
            // let go before the pause was up: where the pointer is still counts
            clearTimeout(candTimer); cand = null;
            const t = targetAt(px, py, true);
            if (t && t.ids.join() !== cur.join()) apply(t);
            clearTimeout(gridTimer); gridCand = '';
            if (activeGrid) { activeGrid.__commit(); activeGrid = null; lastCell = ''; }
            clone?.remove(); clone = null;
            placeholder(el, false);
            document.body.style.userSelect = ''; noAnchor(false); edgeSince = 0;
            // swallow the click that ends a drag
            node.addEventListener('click', (c) => { c.stopPropagation(); c.preventDefault(); }, { capture: true, once: true });
            if (cur.join() !== ids0.join()) o.onDrop?.(cur);
        }
        el = null; pending = null; id = null; lock = null;
        if (raf) { cancelAnimationFrame(raf); raf = 0; }
        clearTimeout(candTimer); cand = null;
    }

    node.addEventListener('pointerdown', down);
    return {
        update(n) { o = n; },
        destroy() { node.removeEventListener('pointerdown', down); up(); },
    };
}
