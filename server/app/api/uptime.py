import sqlite3, time
from flask import Blueprint, jsonify, request

from app.core.db import DB_PATH, _slots
from app.core.logger import log
from app.services import uptime

uptime_bp = Blueprint('uptime', __name__)


def _history(hours=24, buckets=48):
    """Per check: 24 h of slots, the share of passing runs, and the median response time."""
    out = {}
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        start = int(time.time()) - hours * 3600
        size = max(1, hours * 3600 // buckets)
        rows = conn.execute('''SELECT check_id, (timestamp - ?) / ?, SUM(ok), COUNT(*) FROM uptime_checks
                               WHERE timestamp >= ? GROUP BY check_id, 2''', (start, size, start)).fetchall()
        ms = conn.execute('''SELECT check_id, ms FROM uptime_checks WHERE timestamp >= ? AND ok = 1 AND ms IS NOT NULL
                             ORDER BY check_id, ms''', (start,)).fetchall()
        conn.close()
        by = {}
        for cid, b, good, total in rows:
            by.setdefault(cid, []).append((b, good, total))
        times = {}
        for cid, v in ms:
            times.setdefault(cid, []).append(v)
        for cid, r in by.items():
            t = times.get(cid) or []
            out[cid] = {"slots": _slots(r, buckets),
                        "pct": round(100 * sum(g for _, g, _ in r) / sum(n for *_, n in r), 2),
                        "median_ms": t[len(t) // 2] if t else None}
        return size, out
    except Exception as e:
        log.error(f"uptime history: {e}")
        return 0, {}


def _view(c, hist):
    last = uptime._last.get(c['id'])
    cert = uptime.cert_of(c['url'])
    return {**c, "status": uptime.status(c), "last": last, "history": hist.get(c['id']),
            "cert": {k: cert.get(k) for k in ('expires', 'issuer', 'error')} if cert else None}


@uptime_bp.route('', methods=['GET'])
def list_checks():
    size, hist = _history()
    return jsonify({"status": "success", "data": {
        "bucket_seconds": size, "cert_warn_days": uptime.CERT_WARN_DAYS,
        "checks": [_view(c, hist) for c in uptime.load()]}})


@uptime_bp.route('', methods=['POST'])
def add_check():
    c, err = uptime.add(request.get_json(silent=True) or {})
    if err:
        return jsonify({"status": "error", "message": err}), 400
    uptime.run_one(c)
    size, hist = _history()
    return jsonify({"status": "success", "data": _view(c, hist)})


@uptime_bp.route('/<cid>', methods=['PUT'])
def edit_check(cid):
    c, err = uptime.update(cid, request.get_json(silent=True) or {})
    if err:
        return jsonify({"status": "error", "message": err}), 400 if err != 'No such check' else 404
    uptime.run_one(c)
    return jsonify({"status": "success"})


@uptime_bp.route('/<cid>', methods=['DELETE'])
def delete_check(cid):
    if not uptime.remove(cid):
        return jsonify({"status": "error", "message": "No such check"}), 404
    return jsonify({"status": "success"})


@uptime_bp.route('/<cid>/run', methods=['POST'])
def run_check(cid):
    c = next((c for c in uptime.load() if c['id'] == cid), None)
    if not c:
        return jsonify({"status": "error", "message": "No such check"}), 404
    return jsonify({"status": "success", "data": uptime.run_one(c)})
