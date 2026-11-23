"""Uptime checks: websites and services the dashboard fetches on a schedule, from this server.

A check is {id, name, url, every, expect}. Each run records whether it answered (status
below 400, and containing `expect` when set), how long it took and the HTTP status. For
https addresses the certificate's expiry is read every few hours, so an alert can warn
before it lapses. A public address is fetched through the internet like anyone else would,
so a check of it fails when people outside can't reach it.
"""
import json, socket, ssl, threading, time, urllib.request, urllib.error, uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from app.core import paths
from app.core.logger import log

FILE = paths.state('uptime')
EVERY_CHOICES = (30, 60, 300)
CERT_EVERY = 6 * 3600          # how often a certificate's expiry is read again
CERT_WARN_DAYS = 14            # alert this many days before a certificate lapses
DOWN_AFTER = 2                 # failed runs in a row before a check counts as down (one blip isn't an outage)

_lock = threading.Lock()
_last = {}       # id -> {"at", "ok", "ms", "code", "error"}
_fails = {}      # id -> failed runs in a row
_certs = {}      # host -> {"at", "expires", "issuer", "error"}
_wake = threading.Event()


# ---- the list -------------------------------------------------------------------------------
def load():
    try:
        with open(FILE) as f:
            data = json.load(f)
        return [c for c in data if isinstance(c, dict) and c.get('id') and c.get('url')]
    except (OSError, ValueError):
        return []


def _save(checks):
    with open(FILE, 'w') as f:
        json.dump(checks, f, indent=1)


def clean(body):
    """Validate an add/edit body -> (check fields, error)."""
    url = (body.get('url') or '').strip()
    if url and '://' not in url:
        url = 'https://' + url
    u = urlparse(url)
    if u.scheme not in ('http', 'https') or not u.hostname:
        return None, 'Enter an http:// or https:// address'
    name = (body.get('name') or '').strip()[:60] or u.hostname
    try:
        every = int(body.get('every') or 60)
    except (TypeError, ValueError):
        every = 60
    if every not in EVERY_CHOICES:
        every = 60
    expect = (body.get('expect') or '').strip()[:200] or None
    return {"name": name, "url": url, "every": every, "expect": expect}, None


def add(body):
    fields, err = clean(body)
    if err:
        return None, err
    with _lock:
        checks = load()
        c = {"id": uuid.uuid4().hex[:10], "created": int(time.time()), **fields}
        checks.append(c)
        _save(checks)
    return c, None


def update(cid, body):
    fields, err = clean(body)
    if err:
        return None, err
    with _lock:
        checks = load()
        c = next((c for c in checks if c['id'] == cid), None)
        if not c:
            return None, 'No such check'
        c.update(fields)
        _save(checks)
        _last.pop(cid, None); _fails.pop(cid, None)
    return c, None


def remove(cid):
    with _lock:
        checks = load()
        left = [c for c in checks if c['id'] != cid]
        if len(left) == len(checks):
            return False
        _save(left)
        _last.pop(cid, None); _fails.pop(cid, None)
    from app.core.db import get_writer
    get_writer().execute('DELETE FROM uptime_checks WHERE check_id = ?', (cid,))
    return True


# ---- running them ---------------------------------------------------------------------------
class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5


_opener = urllib.request.build_opener(_Redirects())


def run_one(c):
    """Fetch a check's address once and record the result."""
    t0 = time.perf_counter()
    ok, code, error = False, None, None
    try:
        req = urllib.request.Request(c['url'], headers={'User-Agent': 'homelab-dashboard uptime check',
                                                        'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8'})
        with _opener.open(req, timeout=10) as r:
            code = r.status
            body = r.read(256 * 1024) if c.get('expect') else b''
        ok = code < 400
        if ok and c.get('expect') and c['expect'].encode() not in body:
            ok, error = False, f"Answered {code} but without “{c['expect']}”"
    except urllib.error.HTTPError as e:
        code, error = e.code, f"HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        r = e.reason
        if isinstance(r, ssl.SSLCertVerificationError):
            error = f"Certificate problem: {r.verify_message or r}"
        elif isinstance(r, socket.gaierror):
            error = "The name doesn't resolve"
        elif isinstance(r, (TimeoutError, socket.timeout)):
            error = "No answer within 10 s"
        elif isinstance(r, ConnectionRefusedError):
            error = "Connection refused"
        else:
            error = str(r)
    except (TimeoutError, socket.timeout):
        error = "No answer within 10 s"
    except Exception as e:
        error = str(e)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    res = {"at": int(time.time()), "ok": ok, "ms": ms if ok else None, "code": code, "error": error}
    with _lock:
        _last[c['id']] = res
        _fails[c['id']] = 0 if ok else _fails.get(c['id'], 0) + 1
    from app.core.db import get_writer
    get_writer().execute('INSERT INTO uptime_checks VALUES (?, ?, ?, ?, ?)',
                         (res['at'], c['id'], 1 if ok else 0, res['ms'], code))
    if c['url'].startswith('https://'):
        _maybe_read_cert(urlparse(c['url']))
    return res


def _maybe_read_cert(u):
    host, port = u.hostname, u.port or 443
    key = f"{host}:{port}"
    hit = _certs.get(key)
    if hit and time.time() - hit['at'] < (600 if hit.get('error') or hit.get('unreachable') else CERT_EVERY):
        return
    info = {"at": time.time(), "expires": None, "issuer": None, "error": None}
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=8) as s:
            with ctx.wrap_socket(s, server_hostname=host) as ss:
                cert = ss.getpeercert()
        info['expires'] = int(ssl.cert_time_to_seconds(cert['notAfter']))
        issuer = dict(x[0] for x in cert.get('issuer', ()))
        info['issuer'] = issuer.get('organizationName') or issuer.get('commonName')
    except ssl.SSLCertVerificationError as e:
        info['error'] = e.verify_message or str(e)
    except Exception:
        info['unreachable'] = True     # can't tell anything about the certificate; try again soon
    _certs[key] = info


def cert_of(url):
    u = urlparse(url)
    if u.scheme != 'https':
        return None
    return _certs.get(f"{u.hostname}:{u.port or 443}")


def loop():
    """Runs each check when it is due, a few at a time."""
    pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix='uptime')
    running = set()
    while True:
        try:
            now = time.time()
            for c in load():
                last = _last.get(c['id'])
                if c['id'] in running or (last and now - last['at'] < c.get('every', 60)):
                    continue
                running.add(c['id'])
                fut = pool.submit(run_one, c)
                fut.add_done_callback(lambda f, cid=c['id']: running.discard(cid))
        except Exception as e:
            log.warning(f"uptime loop: {e}")
        _wake.wait(5)
        _wake.clear()


def start():
    threading.Thread(target=loop, daemon=True, name='uptime').start()


# ---- what the page and the alerts read ----------------------------------------------------
def status(c):
    last = _last.get(c['id'])
    if not last:
        return 'pending'
    if last['ok']:
        return 'up'
    return 'down' if _fails.get(c['id'], 0) >= DOWN_AFTER else 'flaky'


def problems():
    """Alert conditions: a check down twice in a row; a certificate lapsing soon or invalid."""
    out = {}
    for c in load():
        last = _last.get(c['id'])
        if status(c) == 'down':
            out[f"site:{c['name']}"] = f"{c['name']} is down: {last.get('error') or 'no answer'} ({c['url']})"
        cert = cert_of(c['url'])
        if cert and cert.get('expires'):
            days = (cert['expires'] - time.time()) / 86400
            if days < CERT_WARN_DAYS:
                when = 'has expired' if days < 0 else f"expires in {max(0, int(days))} day{'s' if int(days) != 1 else ''}"
                out[f"cert:{urlparse(c['url']).hostname}"] = f"The certificate for {urlparse(c['url']).hostname} {when}"
    return out
