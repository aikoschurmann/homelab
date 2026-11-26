"""History for the Metrics page: every host metric the dashboard keeps, as time series.

GET /api/metrics/catalog  which metrics exist and which hosts have data for each
GET /api/metrics/series   ?key=cpu&nodes=arrakis,giedi-pi&range=24h -> one averaged series per host
"""
import sqlite3, threading, time

from flask import Blueprint, jsonify, request

from app.core.db import DB_PATH
from app.core.logger import log

metrics_bp = Blueprint('metrics', __name__)

# key -> (label, unit, table, value column/expression, node column, key filter)
# units: pct %, gb (GiB of memory), bytes, bps (bytes/s), c (°C), mbit (Mbit/s)
METRICS = {
    "cpu":         ("CPU",              "pct",   "metrics",      "cpu",                "node", None),
    "mem":         ("Memory used",      "gb",    "metrics",      "mem",                "node", None),
    "disk":        ("Storage used",     "bytes", "disk_metrics", "used_bytes",         "node", None),
    "net_rx":      ("Download",         "bps",   "samples",      "value",              "node", "net_rx"),
    "net_tx":      ("Upload",           "bps",   "samples",      "value",              "node", "net_tx"),
    "temp_cpu":    ("CPU temperature",  "c",     "samples",      "value",              "node", "temp_cpu"),
    "temp_ssd":    ("SSD temperature",  "c",     "samples",      "value",              "node", "temp_ssd"),
    "wifi_signal": ("Wi-Fi signal",     "pct",   "samples",      "value",              "node", "wifi_signal"),
    "wifi_rate":   ("Wi-Fi link speed", "mbit",  "samples",      "value",              "node", "wifi_rate"),
}
RANGES = {"1h": 3600, "6h": 6 * 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
POINTS = 240
# nodes that are not hosts of their own (Arrakis's old VM row is its OrbStack machine)
SKIP_NODES = {"sietch"}

_cat = {"at": 0, "data": None}
_lock = threading.Lock()


def _conn():
    return sqlite3.connect(DB_PATH, timeout=5)


def _names():
    """node id -> display name: this server, then the hosts with agents."""
    from app.core import server_cfg
    out = {"arrakis": server_cfg.name()}
    try:
        from app.api.hosts import _load
        for h in _load():
            out[h['id']] = h['name']
    except Exception:  # noqa: BLE001
        pass
    return out


def _caps():
    """node id -> what it has in all: cores, memory (GiB, as the mem metric) and storage
    (bytes, the latest disk_metrics total), so a bar can show "of 24 cores" / "of 35.7 GB"."""
    import os
    import psutil
    out = {"arrakis": {"cores": os.cpu_count() or 0, "mem": psutil.virtual_memory().total / 2**30}}
    try:
        from app.api import hosts as hs
        with hs._lock:
            latest = dict(hs._latest)
        for h in hs._load():
            r = latest.get(h['id']) or {}
            out[h['id']] = {"cores": r.get('cores') or 0, "mem": (r.get('mem_total') or 0) / 2**30}
    except Exception:  # noqa: BLE001
        pass
    c = _conn()
    try:
        # (SQLite: with MAX, the bare column comes from that newest row)
        for node, total, _ in c.execute('SELECT node, total_bytes, MAX(timestamp) FROM disk_metrics '
                                        'WHERE timestamp >= ? GROUP BY node', (int(time.time()) - 7 * 86400,)):
            if node in out and total:
                out[node]["disk"] = total
    except sqlite3.OperationalError:
        pass
    finally:
        c.close()
    return out


def _catalog():
    with _lock:
        if _cat["data"] and time.time() - _cat["at"] < 60:
            return _cat["data"]
    since = int(time.time()) - 7 * 86400
    have = {}
    c = _conn()
    try:
        for node, in c.execute('SELECT DISTINCT node FROM metrics WHERE timestamp >= ?', (since,)):
            have.setdefault("cpu", set()).add(node)
            have.setdefault("mem", set()).add(node)
        for node, in c.execute('SELECT DISTINCT node FROM disk_metrics WHERE timestamp >= ?', (since,)):
            have.setdefault("disk", set()).add(node)
        for key, node in c.execute('SELECT DISTINCT key, node FROM samples WHERE timestamp >= ?', (since,)):
            have.setdefault(key, set()).add(node)
    except sqlite3.OperationalError as e:
        log.warning(f"metrics catalog: {e}")
    finally:
        c.close()
    names = _names()
    order = list(names)
    data = {
        "metrics": [{"key": k, "label": m[0], "unit": m[1],
                     "nodes": sorted((n for n in have.get(k, ()) if n not in SKIP_NODES), key=lambda n: (order.index(n) if n in order else 99, n))}
                    for k, m in METRICS.items()],
        "names": names,
        "ranges": list(RANGES),
    }
    from app.services.samples import wifi_info
    data["wifi"] = {n: {k: w.get(k) for k in ("ssid", "dbm", "rate", "at")} for n, w in wifi_info.items()}
    with _lock:
        _cat.update(at=time.time(), data=data)
    return data


@metrics_bp.route('/catalog', methods=['GET'])
def catalog():
    # (capacity fresh each time: a host that just came back fills in on its next report)
    return jsonify({"status": "success", "data": {**_catalog(), "caps": _caps()}})


@metrics_bp.route('/series', methods=['GET'])
def series():
    key = request.args.get('key', '')
    if key not in METRICS:
        return jsonify({"status": "error", "message": "unknown metric"}), 400
    rng = request.args.get('range', '24h')
    span = RANGES.get(rng, 86400)
    label, unit, table, col, ncol, kf = METRICS[key]
    nodes = [n for n in (request.args.get('nodes') or '').split(',') if n][:12]
    if not nodes:
        nodes = next((m["nodes"] for m in _catalog()["metrics"] if m["key"] == key), [])
    now = int(time.time())
    since = now - span
    step = max(60, span // POINTS)
    out, stats = [], None
    c = _conn()
    try:
        for n in nodes:
            sql = (f'SELECT (timestamp / ?) * ? AS b, AVG({col}), MAX({col}) FROM {table} '
                   f'WHERE {ncol} = ? AND timestamp >= ?' + (' AND key = ?' if kf else '') + ' GROUP BY b ORDER BY b')
            args = [step, step, n, since] + ([kf] if kf else [])
            rows = c.execute(sql, args).fetchall()
            # the newest value as it stands, not a bucket's average
            q = f'SELECT timestamp, {col} FROM {table} WHERE {ncol} = ?' + (' AND key = ?' if kf else '') + ' ORDER BY timestamp DESC LIMIT 1'
            last = c.execute(q, [n] + ([kf] if kf else [])).fetchone()
            out.append({"node": n, "points": [[(b + step / 2) * 1000, round(v, 3)] for b, v, _ in rows if v is not None],
                        "last": {"t": last[0] * 1000, "v": last[1]} if last and last[0] >= now - 15 * 60 else None,
                        "max": max((mx for _, _, mx in rows if mx is not None), default=None)})
        agg = request.args.get('agg')
        if agg in ('sum', 'avg', 'cores') and out:
            stats = _agg_stats(c, [s["node"] for s in out], since, table, col, ncol, kf, agg)
    except sqlite3.OperationalError as e:
        log.warning(f"metrics series {key}: {e}")
    finally:
        c.close()
    data = {"key": key, "label": label, "unit": unit, "range": rng,
            "step": step, "from": since * 1000, "to": now * 1000, "series": out}
    if stats:
        data["agg"] = stats
    return jsonify({"status": "success", "data": data})


def _agg_stats(c, nodes, since, table, col, ncol, kf, agg):
    """The hosts together over the range, minute by minute (each host's latest minute carried
    forward, from when every host has reported): their sum, their average, or for CPU the cores
    busy (each host's % of its cores). Its average and peak, at the same one-minute grain whatever
    the range, so a longer range's peak is never lower than a shorter one's."""
    cores = {n: (v.get("cores") or 0) for n, v in _caps().items()} if agg == 'cores' else {}
    if agg == 'cores' and not all(cores.get(n) for n in nodes):
        return None
    ph = ','.join('?' * len(nodes))
    rows = c.execute(f'SELECT timestamp / 60 AS b, {ncol}, AVG({col}) FROM {table} '
                     f'WHERE {ncol} IN ({ph}) AND timestamp >= ?' + (' AND key = ?' if kf else '') +
                     f' GROUP BY b, {ncol} ORDER BY b', [*nodes, since] + ([kf] if kf else [])).fetchall()
    last, total, peak, k = {}, 0.0, None, 0
    i = 0
    while i < len(rows):
        b = rows[i][0]
        while i < len(rows) and rows[i][0] == b:
            _, n, v = rows[i]
            if v is not None:
                last[n] = min(v, 100) / 100 * cores[n] if agg == 'cores' else v   # (a host past 100%: a reading's rounding)
            i += 1
        if len(last) < len(nodes):
            continue
        t = sum(last.values())
        if agg == 'avg':
            t /= len(nodes)
        total += t
        k += 1
        peak = t if peak is None or t > peak else peak
    return {"avg": total / k, "peak": peak} if k else None
