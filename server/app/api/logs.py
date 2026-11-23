"""One search across logs: every container in the running OrbStack machines (docker logs) and
the Mac apps whose log files the dashboard knows (the dashboard itself, Jellyfin, OrbStack,
qBittorrent). Lines are matched on the server and returned newest first."""
import json, os, re, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.core.logger import log

logs_bp = Blueprint('logs', __name__)

ANSI = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
PROBLEM = re.compile(r'\b(error|errors|err|fatal|panic|exception|traceback|fail|failed|failure|critical|crit|warn|warning|denied|refused|timeout|timed out)\b', re.I)
WINDOWS = {'15m': 900, '1h': 3600, '6h': 6 * 3600, '24h': 86400, '7d': 7 * 86400}
MAX_LINES = 1000
TS_RE = re.compile(r'(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:[.,](\d+))?\s*(Z|[+-]\d{2}:?\d{2})?')
MAC_APPS = {'dashboard': 'Dashboard', 'jellyfin': 'Jellyfin', 'orbstack': 'OrbStack', 'qbittorrent': 'qBittorrent'}


def _ts(line):
    """Epoch seconds of the first timestamp in a line, or None. No zone means local time."""
    m = TS_RE.search(line[:80])
    if not m:
        return None
    try:
        d = datetime.strptime(f"{m.group(1)} {m.group(2)}", '%Y-%m-%d %H:%M:%S')
        frac = float('0.' + m.group(3)[:6]) if m.group(3) else 0.0
        z = m.group(4)
        if z:
            if z == 'Z':
                d = d.replace(tzinfo=timezone.utc)
            else:
                z = z.replace(':', '')
                off = (int(z[1:3]) * 60 + int(z[3:5])) * (1 if z[0] == '+' else -1)
                d = d.replace(tzinfo=timezone.utc).timestamp() - off * 60
                return d + frac
            return d.timestamp() + frac
        return time.mktime(d.timetuple()) + frac
    except ValueError:
        return None


def _machines():
    try:
        out = subprocess.run(['orb', 'list', '-f', 'json'], capture_output=True, text=True, timeout=10).stdout
        return [m['name'] for m in json.loads(out or '[]') if m.get('state') == 'running']
    except Exception:
        return []


# every container's lines since the window began, prefixed with its name, in one call per machine
_DOCKER_SH = r'''command -v docker >/dev/null 2>&1 || exit 0
for c in $(docker ps -a --format '{{.Names}}'); do
  docker logs --since "$1" --timestamps "$c" 2>&1 | tail -n 4000 | sed "s|^|$c |"
done'''


def _machine_lines(machine, since_s):
    try:
        out = subprocess.run(['orb', '-m', machine, '-u', 'root', 'sh', '-c', _DOCKER_SH, 'sh', f'{since_s}s'],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception as e:
        log.warning(f"logs from {machine}: {e}")
        return []
    rows = []
    for line in out.splitlines():
        name, _, rest = line.partition(' ')
        stamp, _, msg = rest.partition(' ')
        rows.append({"t": _ts(stamp), "source": name, "where": machine, "kind": "container", "line": ANSI.sub('', msg)})
    return rows


def _mac_lines(app_id, since):
    from app.api.services import _daemon_log_sources
    rows = []
    for path in _daemon_log_sources(app_id):
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', errors='replace') as f:
                f.seek(max(0, os.path.getsize(path) - 4 * 1024 * 1024))
                f.readline()
                last = None
                for line in f:
                    line = ANSI.sub('', line.rstrip('\n'))
                    if not line:
                        continue
                    t = _ts(line)
                    # a stack trace's lines have no time of their own: they belong to the line above
                    t = t if t is not None else last
                    last = t
                    if t is not None and t < since:
                        continue
                    rows.append({"t": t, "source": MAC_APPS[app_id], "where": "mac", "kind": "app", "line": line})
        except Exception as e:
            log.warning(f"logs from {path}: {e}")
    return rows


@logs_bp.route('/sources', methods=['GET'])
def sources():
    return jsonify({"status": "success", "data": {
        "machines": _machines(),
        "apps": [{"id": k, "name": v} for k, v in MAC_APPS.items()],
        "windows": list(WINDOWS)}})


@logs_bp.route('/search', methods=['GET'])
def search():
    q = (request.args.get('q') or '').strip()
    window = request.args.get('since', '1h')
    span = WINDOWS.get(window, 3600)
    problems = request.args.get('problems') in ('1', 'true')
    only = request.args.get('source') or ''        # '', 'mac', or a machine name
    since = time.time() - span
    t0 = time.perf_counter()
    jobs = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        if only in ('', 'mac'):
            jobs += [pool.submit(_mac_lines, a, since) for a in MAC_APPS]
        if only != 'mac':
            jobs += [pool.submit(_machine_lines, m, span) for m in _machines() if only in ('', m)]
        rows = [r for j in jobs for r in j.result()]
    try:
        rx = re.compile(q, re.I) if q and request.args.get('regex') in ('1', 'true') else None
    except re.error as e:
        return jsonify({"status": "error", "message": f"Not a valid pattern: {e}"}), 400
    ql = q.lower()
    hits = [r for r in rows
            if (not q or (rx.search(r['line']) if rx else ql in r['line'].lower() or ql in r['source'].lower()))
            and (not problems or PROBLEM.search(r['line']))]
    hits.sort(key=lambda r: r['t'] or 0, reverse=True)
    counts = {}
    for r in hits:
        counts[r['source']] = counts.get(r['source'], 0) + 1
    return jsonify({"status": "success", "data": {
        "lines": hits[:MAX_LINES], "total": len(hits), "scanned": len(rows), "by_source": counts,
        "ms": round((time.perf_counter() - t0) * 1000)}})
