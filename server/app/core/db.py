import json
import sqlite3
import os
import time
from app.core.logger import log
from app.core.db_writer import DBWriter
from app.core import paths

DB_PATH = paths.metrics_db()
_writer = None

def get_writer():
    global _writer
    if not _writer:
        _writer = DBWriter(DB_PATH)
    return _writer

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # WAL lets API reads run concurrently with the background writer
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('''CREATE TABLE IF NOT EXISTS metrics (timestamp INTEGER, node TEXT, cpu REAL, mem REAL, net REAL)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_metrics_time ON metrics(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_metrics_node_ts ON metrics(node, timestamp)')
        c.execute('''CREATE TABLE IF NOT EXISTS api_latency (timestamp INTEGER, endpoint_id TEXT, latency_ms REAL, status_code INTEGER)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_api_latency_ep_ts ON api_latency(endpoint_id, timestamp DESC)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_latency_time ON api_latency(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_latency_ep ON api_latency(endpoint_id)')
        c.execute('''CREATE TABLE IF NOT EXISTS service_metrics (timestamp INTEGER, service_type TEXT, service_id TEXT, mem_mb REAL, cpu REAL)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_svc_ts ON service_metrics(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_svc_id ON service_metrics(service_type, service_id, timestamp)')
        # status column added later for uptime history; rows written before it stay NULL (unknown)
        try: c.execute('ALTER TABLE service_metrics ADD COLUMN status TEXT')
        except sqlite3.OperationalError: pass
        c.execute('''CREATE TABLE IF NOT EXISTS disk_metrics (timestamp INTEGER, node TEXT, used_bytes REAL, total_bytes REAL)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_disk_node_ts ON disk_metrics(node, timestamp)')
        # other hosts' ports, checked from Arrakis (ok 1/0, ms the answer's round trip)
        c.execute('''CREATE TABLE IF NOT EXISTS host_checks (timestamp INTEGER, host TEXT, port INTEGER, ok INTEGER, ms REAL)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_checks_host_ts ON host_checks(host, timestamp)')
        # OrbStack machines' own cgroup usage, every 5 s (host 'arrakis' or a host id), so a
        # machine's graphs survive a dashboard restart or a moment the machine looked stopped
        c.execute('''CREATE TABLE IF NOT EXISTS machine_metrics (timestamp REAL, host TEXT, name TEXT, cpu REAL, mem REAL, mem_limit REAL)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_machine_ts ON machine_metrics(host, name, timestamp)')
        conn.commit()
        conn.close()
        get_writer() # start background thread
    except Exception as e:
        log.error(f"Failed to initialize metrics DB: {e}")

def insert_latency(endpoint_id, latency_ms, status_code):
    get_writer().execute('INSERT INTO api_latency VALUES (?, ?, ?, ?)', (int(time.time()), endpoint_id, latency_ms, status_code))

def get_recent_latencies(limit=5):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        cutoff = int(time.time()) - 86400
        c.execute(f'''
            SELECT endpoint_id, latency_ms, status_code, timestamp
            FROM (SELECT endpoint_id, latency_ms, status_code, timestamp, ROW_NUMBER() OVER (PARTITION BY endpoint_id ORDER BY timestamp DESC) as rn FROM api_latency WHERE timestamp >= ?)
            WHERE rn <= ? ORDER BY endpoint_id, rn ASC
        ''', (cutoff, limit))
        rows = c.fetchall()
        result = {}
        for ep_id, lat, code, ts in rows:
            if ep_id not in result: result[ep_id] = []
            result[ep_id].append({"latency": lat, "status": code, "timestamp": ts})
        conn.close()
        return result
    except Exception as e:
        log.error(f"Failed to fetch latencies: {e}")
        return {}

def insert_metrics(node, cpu, mem, net=0.0):
    get_writer().execute('INSERT INTO metrics (timestamp, node, cpu, mem, net) VALUES (?, ?, ?, ?, ?)', (int(time.time()), node, cpu, mem, net))

def insert_machine_metric(host, name, t, cpu, mem, mem_limit):
    get_writer().execute('INSERT INTO machine_metrics (timestamp, host, name, cpu, mem, mem_limit) VALUES (?, ?, ?, ?, ?, ?)',
                         (t, host, name, cpu, mem, mem_limit))

def get_machine_history(host, name, since):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        rows = conn.execute('SELECT timestamp, cpu, mem, mem_limit FROM machine_metrics WHERE host = ? AND name = ? AND timestamp > ? ORDER BY timestamp',
                            (host, name, since)).fetchall()
        conn.close()
        return [{"t": t, "cpu": cpu, "mem": mem, "memLimit": lim} for t, cpu, mem, lim in rows]
    except Exception as e:
        log.error(f"Failed to read machine history: {e}")
        return []

def rename_machine_metrics(host, old, new):
    get_writer().execute('UPDATE machine_metrics SET name = ? WHERE host = ? AND name = ?', (new, host, old))

def get_historical_metrics(hours=24):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        cutoff = int(time.time()) - (hours * 3600)
        if hours <= 0.1: interval = 5
        elif hours <= 1: interval = 60
        elif hours <= 24: interval = 300
        elif hours <= 168: interval = 3600
        else: interval = 3 * 3600
        c.execute(f'''
            SELECT node, CAST(timestamp/({interval}) AS INTEGER)*{interval} as ts, AVG(cpu) as avg_cpu, AVG(mem) as avg_mem, AVG(COALESCE(net, 0.0)) as avg_net
            FROM metrics WHERE timestamp > ? GROUP BY node, ts ORDER BY ts ASC
        ''', (cutoff,))
        result = {}
        for row in c.fetchall():
            node, ts, cpu, mem, net = row
            if node not in result: result[node] = []
            result[node].append({"ts": ts, "cpu": round(cpu, 1), "mem": round(mem, 2), "net": round(net, 2)})
        if 'arrakis' in result: result['host'] = result['arrakis']
        if 'sietch' in result: result['vm'] = result['sietch']
        conn.close()
        return result
    except Exception as e:
        log.error(f"DB read failed: {e}")
        return {'host': [], 'vm': []}

def insert_service_metric(service_type, service_id, mem_mb, cpu, status=None):
    get_writer().execute('INSERT INTO service_metrics (timestamp, service_type, service_id, mem_mb, cpu, status) VALUES (?, ?, ?, ?, ?, ?)',
                         (int(time.time()), service_type, service_id, mem_mb, cpu, status))

def get_service_uptime(hours=24, buckets=48):
    """Per service, a list of `buckets` slots: 'up' (all samples running), 'down' (none),
    'partial' (mixed) or None (no status samples). Plus overall uptime %."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        now = int(time.time())
        start = now - int(hours * 3600)
        size = max(1, int(hours * 3600) // buckets)
        c.execute('''
            SELECT service_type, service_id, (timestamp - ?) / ? AS b,
                   SUM(status = 'running'), COUNT(*)
            FROM service_metrics WHERE timestamp >= ? AND status IS NOT NULL
            GROUP BY service_type, service_id, b
        ''', (start, size, start))
        result = {}
        for stype, sid, b, up, total in c.fetchall():
            key = f"{stype}:{sid}"
            r = result.setdefault(key, {"slots": [None] * buckets, "up": 0, "total": 0})
            if 0 <= b < buckets:
                r["slots"][b] = 'up' if up == total else 'down' if up == 0 else 'partial'
            r["up"] += up; r["total"] += total
        conn.close()
        for r in result.values():
            r["pct"] = round(100 * r.pop("up") / r.pop("total"), 2) if r["total"] else None
        return {"bucket_seconds": size, "services": result}
    except Exception as e:
        log.error(f"Failed to get service uptime: {e}")
        return {"bucket_seconds": 0, "services": {}}

def insert_disk_metric(node, used_bytes, total_bytes):
    get_writer().execute('INSERT INTO disk_metrics VALUES (?, ?, ?, ?)', (int(time.time()), node, used_bytes, total_bytes))

def get_disk_history(node, hours=24):
    """[{ts, used, total}] bytes, averaged so a range comes back as at most a few hundred points."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        step = max(300, int(hours * 3600) // 300)
        rows = conn.execute('''SELECT CAST(timestamp / ? AS INTEGER) * ? AS ts, AVG(used_bytes), AVG(total_bytes)
                               FROM disk_metrics WHERE node = ? AND timestamp > ? GROUP BY ts ORDER BY ts''',
                            (step, step, node, int(time.time() - hours * 3600))).fetchall()
        conn.close()
        return [{"ts": ts, "used": u, "total": t} for ts, u, t in rows]
    except Exception as e:
        log.error(f"Failed to read disk history: {e}")
        return []


def _slots(rows, buckets):
    """(bucket, good, total) rows -> 'up' (all good) / 'partial' / 'down' (none) per slot; None without rows."""
    slots = [None] * buckets
    for b, good, total in rows:
        if 0 <= b < buckets:
            slots[b] = 'up' if good == total else 'down' if good == 0 else 'partial'
    return slots


def get_host_presence(node, hours=24, buckets=48, every=5, since=0):
    """When a host was reporting: per slot, 'up' (covered at least 90% of the time), 'partial', or
    'down' (no reports). Covered = between two reports that came less than `gap` apart, so an agent
    that reports every 6-7 s instead of exactly every 5 s still counts as fully up. pct is the
    covered share of the whole window. Slots before `since` (when it was added) or its first row stay None."""
    gap = max(30, 6 * every)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        now = int(time.time())
        start = now - int(hours * 3600)
        size = max(1, int(hours * 3600) // buckets)
        first = conn.execute('SELECT MIN(timestamp) FROM metrics WHERE node = ?', (node,)).fetchone()[0]
        since = max(since, first or now)
        ts = [r[0] for r in conn.execute('SELECT DISTINCT timestamp FROM metrics WHERE node = ? AND timestamp >= ? ORDER BY 1',
                                         (node, start - gap))]
        conn.close()
        # covered intervals: each report covers until the next one if that came within `gap`,
        # and the latest report covers up to now while it is still fresh
        spans = [(a, b) for a, b in zip(ts, ts[1:]) if b - a <= gap]
        if ts and now - ts[-1] <= gap:
            spans.append((ts[-1], now))
        covered = [0.0] * buckets
        for a, b in spans:
            a, b = max(a, start), min(b, now)
            while a < b:
                k = min(buckets - 1, (a - start) // size)
                end = min(b, start + (k + 1) * size)
                covered[k] += end - a
                a = end
        slots, tot_cov, tot_len = [], 0.0, 0
        for k in range(buckets):
            b0, b1 = start + k * size, min(now, start + (k + 1) * size)
            if b1 <= since:
                slots.append(None)
                continue
            length = b1 - max(b0, since)
            cov = min(covered[k], length)
            tot_cov += cov
            tot_len += length
            slots.append('up' if cov >= 0.9 * length else 'down' if cov == 0 else 'partial')
        pct = round(100 * tot_cov / tot_len, 1) if tot_len else None
        return {"bucket_seconds": size, "slots": slots, "pct": pct}
    except Exception as e:
        log.error(f"Failed to read host presence: {e}")
        return {"bucket_seconds": 0, "slots": [], "pct": None}


def insert_host_check(host, port, ok, ms):
    get_writer().execute('INSERT INTO host_checks VALUES (?, ?, ?, ?, ?)', (int(time.time()), host, port, 1 if ok else 0, ms))


def get_host_checks_uptime(host, hours=24, buckets=48):
    """Per port: slots ('up' all checks passed, 'down' none, 'partial'), pass % and the median answer time."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        start = int(time.time()) - int(hours * 3600)
        size = max(1, int(hours * 3600) // buckets)
        rows = conn.execute('''SELECT port, (timestamp - ?) / ?, SUM(ok), COUNT(*) FROM host_checks
                               WHERE host = ? AND timestamp >= ? GROUP BY port, 2''', (start, size, host, start)).fetchall()
        conn.close()
        out = {}
        for port, b, good, total in rows:
            out.setdefault(port, []).append((b, good, total))
        return {"bucket_seconds": size, "ports": {
            str(p): {"slots": _slots(r, buckets),
                     "pct": round(100 * sum(g for _, g, _ in r) / sum(t for *_, t in r), 2)}
            for p, r in out.items()}}
    except Exception as e:
        log.error(f"Failed to read host checks: {e}")
        return {"bucket_seconds": 0, "ports": {}}


MIN_FORECAST_SPAN = 12 * 3600

def get_disk_forecast(node, days=7):
    """Least-squares fit of used bytes over the last `days`; returns growth/day and days until full."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute('SELECT timestamp, used_bytes, total_bytes FROM disk_metrics WHERE node = ? AND timestamp >= ? ORDER BY timestamp',
                  (node, int(time.time()) - days * 86400))
        rows = c.fetchall()
        conn.close()
        if not rows:
            return {"state": "collecting", "span_seconds": 0, "ready_in_seconds": MIN_FORECAST_SPAN}
        span = rows[-1][0] - rows[0][0]
        used, total = rows[-1][1], rows[-1][2]
        base = {"used_bytes": used, "total_bytes": total, "span_seconds": span}
        if span < MIN_FORECAST_SPAN or len(rows) < 3:
            return {**base, "state": "collecting", "ready_in_seconds": MIN_FORECAST_SPAN - span}
        n = len(rows)
        mx = sum(r[0] for r in rows) / n
        my = sum(r[1] for r in rows) / n
        var = sum((r[0] - mx) ** 2 for r in rows)
        slope = sum((r[0] - mx) * (r[1] - my) for r in rows) / var if var else 0  # bytes per second
        per_day = slope * 86400
        # under ~100MB/day is noise for a 245GB disk
        if per_day < 100 * 1024 ** 2:
            return {**base, "state": "stable", "bytes_per_day": per_day}
        return {**base, "state": "growing", "bytes_per_day": per_day, "days_until_full": (total - used) / per_day}
    except Exception as e:
        log.error(f"Disk forecast failed: {e}")
        return {"state": "error"}

def get_service_history(hours=3):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        cutoff = int(time.time()) - (hours * 3600)
        c.execute('''
            SELECT service_type, service_id, ts, mem, cpu FROM (
                SELECT service_type, service_id, timestamp as ts, mem_mb as mem, cpu as cpu, ROW_NUMBER() OVER(PARTITION BY service_type, service_id ORDER BY timestamp DESC) as rn FROM service_metrics WHERE timestamp > ?
            ) WHERE rn <= 5 ORDER BY service_type, service_id, ts ASC
        ''', (cutoff,))
        rows = c.fetchall()
        conn.close()
        result = {}
        for stype, sid, ts, mem, cpu in rows:
            key = f"{stype}:{sid}"
            if key not in result: result[key] = []
            result[key].append({"ts": ts, "mem": mem, "cpu": cpu})
        return result
    except Exception as e:
        log.error(f"Failed to get service history: {e}")
        return {}

# How long each kind of history is kept: (table, what it is, default days, most days allowed).
# Overridden per kind by the "data_keep" pref ({kind: days}), set from Settings → General.
KEEP = {
    "metrics":  ("metrics",         "Host CPU, memory and network", 30, 365),
    "disks":    ("disk_metrics",    "Disk usage (also feeds the full-disk forecast)", 30, 365),
    "services": ("service_metrics", "Container and daemon CPU / memory", 7, 90),
    "machines": ("machine_metrics", "OrbStack machine CPU / memory", 1, 30),
    "checks":   ("host_checks",     "Port checks of other hosts", 30, 365),
    "latency":  ("api_latency",     "API response times", 7, 90),
}


def keep_days():
    try:
        with open(paths.state('prefs')) as f:
            want = json.load(f).get("data_keep") or {}
    except (OSError, ValueError):
        want = {}
    out = {}
    for k, (_, _, default, most) in KEEP.items():
        try:
            out[k] = min(most, max(1, int(want.get(k, default))))
        except (TypeError, ValueError):
            out[k] = default
    return out


def table_rows():
    """Row count and oldest timestamp per kept table."""
    out = {}
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        for k, (table, *_rest) in KEEP.items():
            n, oldest = conn.execute(f'SELECT COUNT(*), MIN(timestamp) FROM {table}').fetchone()
            out[k] = {"rows": n, "oldest": oldest}
        conn.close()
    except Exception as e:
        log.error(f"table rows: {e}")
    return out


def cleanup_old_metrics():
    try:
        now = int(time.time())
        for k, days in keep_days().items():
            get_writer().execute(f'DELETE FROM {KEEP[k][0]} WHERE timestamp < ?', (now - days * 86400,))
    except Exception as e:
        pass

