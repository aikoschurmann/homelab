"""Pi-hole (v6) stats and pausing blocking, for a Pi-hole container in this Mac's Docker or a
machine. The admin password is read from the container's own environment and stays on the
server; the API session is kept and reused (Pi-hole allows only a few at once)."""
import json, threading, time

from flask import Blueprint, jsonify, request

from app.core.logger import log

pihole_bp = Blueprint('pihole', __name__)
_lock = threading.Lock()
_ph = {"at": 0, "where": None}     # found Pi-hole: {"target", "url", "password"}
_sid = {"sid": None, "at": 0}


def _find():
    """Locate a running Pi-hole container: (target, base url, password), cached 10 minutes."""
    if _ph["where"] and time.time() - _ph["at"] < 600:
        return _ph["where"]
    from app.api.apps import targets, _orb
    found = None
    for t in targets():
        if not t['docker']:
            continue
        r = _orb(t['id'], r'''c=$(docker ps --filter ancestor=pihole/pihole --format '{{.Names}}' | head -1)
[ -n "$c" ] || c=$(docker ps --format '{{.Names}} {{.Image}}' | awk '$2 ~ /pihole/ {print $1; exit}')
[ -n "$c" ] || exit 0
docker port "$c" 80/tcp | head -1
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$c" | grep -E '^(FTLCONF_webserver_api_password|WEBPASSWORD)=' | head -1''', timeout=20)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        if len(lines) >= 1 and ':' in lines[0]:
            port = lines[0].rsplit(':', 1)[1]
            pw = lines[1].split('=', 1)[1] if len(lines) > 1 else ''
            # asked from inside its machine: macOS keeps background services off the local network
            found = {"target": t['id'], "url": f"http://127.0.0.1:{port}", "password": pw,
                     "admin": f"http://{'localhost' if t['id'] == 'mac' else t['id'] + '.orb.local'}:{port}/admin/"}
            break
    _ph.update(at=time.time(), where=found)
    return found


class _Unauthorized(Exception):
    pass


def _http(ph, method, path, body=None, sid=None):
    """One request to Pi-hole's API, made inside its machine (curl or busybox wget)."""
    from app.api.apps import _orb
    r = _orb(ph['target'], r'''m=$1; url=$2; sid=$3; body=$4
if command -v curl >/dev/null; then
  curl -s -w '\n%{http_code}' -X "$m" -H 'Content-Type: application/json' ${sid:+-H "X-FTL-SID: $sid"} ${body:+--data "$body"} "$url"
else
  out=$(wget -qO- -S --header 'Content-Type: application/json' ${sid:+--header "X-FTL-SID: $sid"} ${body:+--post-data "$body"} "$url" 2>/tmp/.ph.$$); rc=$?
  code=$(grep -m1 'HTTP/' /tmp/.ph.$$ | awk '{print $2}'); rm -f /tmp/.ph.$$
  printf '%s\n%s' "$out" "${code:-000}"
fi''', method, ph['url'] + path, sid or '', json.dumps(body) if body is not None else '', timeout=20)
    text, _, code = r.stdout.rpartition('\n')
    if code.strip() == '401':
        raise _Unauthorized()
    if not code.strip().startswith('2'):
        raise RuntimeError(f"HTTP {code.strip() or '?'}")
    return json.loads(text or '{}')


def _call(ph, method, path, body=None, retry=True):
    with _lock:
        if not _sid['sid'] and ph['password']:
            d = _http(ph, 'POST', '/api/auth', {"password": ph['password']})
            _sid.update(sid=(d.get('session') or {}).get('sid'), at=time.time())
        sid = _sid['sid']
    try:
        return _http(ph, method, path, body, sid)
    except _Unauthorized:
        if not retry:
            raise
        _sid['sid'] = None
        return _call(ph, method, path, body, retry=False)


@pihole_bp.route('', methods=['GET'])
def stats():
    ph = _find()
    if not ph:
        return jsonify({"status": "success", "data": {"found": False}})
    try:
        s = _call(ph, 'GET', '/api/stats/summary')
        dom = _call(ph, 'GET', '/api/stats/top_domains?blocked=true&count=10')
        cl = _call(ph, 'GET', '/api/stats/top_clients?count=10')
        bl = _call(ph, 'GET', '/api/dns/blocking')
    except Exception as e:
        _ph['at'] = 0       # look for it again next time (moved, restarted, new password)
        return jsonify({"status": "error", "message": f"Pi-hole didn't answer: {e}"}), 502
    q = s.get('queries') or {}
    return jsonify({"status": "success", "data": {
        "found": True, "target": ph['target'], "admin": ph['admin'],
        "queries": q.get('total'), "blocked": q.get('blocked'), "percent": q.get('percent_blocked'),
        "cached": q.get('cached'), "forwarded": q.get('forwarded'), "unique_domains": q.get('unique_domains'),
        "gravity": (s.get('gravity') or {}).get('domains_being_blocked'),
        "clients": (s.get('clients') or {}).get('active'),
        "top_blocked": dom.get('domains') or [], "top_clients": cl.get('clients') or [],
        "blocking": bl.get('blocking'), "timer": bl.get('timer')}})


@pihole_bp.route('/blocking', methods=['POST'])
def blocking():
    ph = _find()
    if not ph:
        return jsonify({"status": "error", "message": "No Pi-hole found"}), 404
    b = request.get_json(silent=True) or {}
    on = bool(b.get('enabled', True))
    minutes = b.get('minutes')
    body = {"blocking": on, "timer": int(minutes) * 60 if (not on and minutes) else None}
    try:
        r = _call(ph, 'POST', '/api/dns/blocking', body)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 502
    log.info(f"pihole blocking -> {on} ({minutes} min)")
    return jsonify({"status": "success", "data": {"blocking": r.get('blocking'), "timer": r.get('timer')}})
