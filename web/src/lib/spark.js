// Average points ([ms, value]) into fixed time buckets, so the dense 5 s samplers (machines,
// remote hosts) read as smoothly as Arrakis's 1-min host history. Keeps the sparklines at one
// shared resolution instead of some being jagged. Only for the small overview sparklines —
// the full Metrics charts keep their raw detail.
export function bucketed(points, intervalMs = 60000) {
    if (!points || points.length < 2) return points || [];
    const out = [];
    let end = points[0][0] + intervalMs, vs = 0, ts = 0, c = 0;
    for (const [t, v] of points) {
        if (t >= end && c) {
            out.push([ts / c, vs / c]);
            vs = ts = c = 0;
            end = t + intervalMs;
        }
        if (v != null) { vs += v; ts += t; c++; }
    }
    if (c) out.push([ts / c, vs / c]);
    return out;
}
