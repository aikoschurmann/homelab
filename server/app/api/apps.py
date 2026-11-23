"""Installing apps from the catalogue into a machine, and keeping Compose apps up to date.

Installed = every Compose project Docker runs in the OrbStack machines (whether installed
from here or by hand). An image has an update when its registry's digest for the tag differs
from the one it was pulled at; asked of the registry with HEAD (no download, no rate limit).
"""
import json, re, secrets, subprocess, threading, time, urllib.request, urllib.error, uuid
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, request

from app.core.catalog import APPS, BY_ID
from app.core.logger import log

apps_bp = Blueprint('apps', __name__)

_jobs = {}
_lock = threading.Lock()
_digests = {}        # image ref -> (time, remote digest | None)
_docker = {}         # machine -> (time, has docker)
DIGEST_EVERY = 6 * 3600


def _orb(machine, script, *args, timeout=60, stdin=None):
    return subprocess.run(['orb', '-m', machine, '-u', 'root', 'sh', '-c', script, 'sh', *args],
                          input=stdin, capture_output=True, text=True, timeout=timeout)


def machines():
    """Running machines that have Docker."""
    try:
        out = subprocess.run(['orb', 'list', '-f', 'json'], capture_output=True, text=True, timeout=10).stdout
        names = [m['name'] for m in json.loads(out or '[]') if m.get('state') == 'running']
    except Exception:
        return []
    res = []
    for n in names:
        hit = _docker.get(n)
        if not hit or time.time() - hit[0] > 300:
            ok = _orb(n, 'command -v docker >/dev/null && docker info >/dev/null 2>&1', timeout=20).returncode == 0
            _docker[n] = hit = (time.time(), ok)
        if hit[1]:
            res.append(n)
    return res


# ---- registry digests ------------------------------------------------------------------------
def _split(ref):
    """image ref -> (registry, repository, tag)"""
    ref = ref.split('@')[0]
    name, tag = (ref.rsplit(':', 1) if ':' in ref.split('/')[-1] else (ref, 'latest'))
    first = name.split('/')[0]
    if '.' in first or ':' in first or first == 'localhost':
        reg, repo = first, name[len(first) + 1:]
    else:
        reg, repo = 'registry-1.docker.io', name
    if reg in ('docker.io', 'index.docker.io'):
        reg = 'registry-1.docker.io'
    if reg == 'registry-1.docker.io' and '/' not in repo:
        repo = 'library/' + repo
    return reg, repo, tag


ACCEPT = ', '.join(['application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json',
                    'application/vnd.docker.distribution.manifest.v2+json', 'application/vnd.oci.image.manifest.v1+json'])


def remote_digest(ref):
    hit = _digests.get(ref)
    if hit and time.time() - hit[0] < DIGEST_EVERY:
        return hit[1]
    reg, repo, tag = _split(ref)
    url = f"https://{reg}/v2/{repo}/manifests/{tag}"
    digest = None
    try:
        def head(token=None):
            h = {'Accept': ACCEPT, 'User-Agent': 'homelab-dashboard'}
            if token:
                h['Authorization'] = f'Bearer {token}'
            return urllib.request.urlopen(urllib.request.Request(url, method='HEAD', headers=h), timeout=10)
        try:
            r = head()
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            ch = e.headers.get('WWW-Authenticate', '')
            kv = dict(re.findall(r'(\w+)="([^"]*)"', ch))
            q = f"{kv['realm']}?service={kv.get('service', '')}&scope={kv.get('scope', f'repository:{repo}:pull')}"
            tok = json.loads(urllib.request.urlopen(q, timeout=10).read())
            r = head(tok.get('token') or tok.get('access_token'))
        digest = r.headers.get('Docker-Content-Digest')
    except Exception as e:
        log.info(f"registry digest {ref}: {e}")
    _digests[ref] = (time.time(), digest)
    return digest


# ---- what's installed -----------------------------------------------------------------------
_PS_SH = r'''docker ps -a --format '{{json .}}'
echo '#images'
docker images --digests --format '{{.Repository}}:{{.Tag}} {{.Digest}} {{.ID}}' 2>/dev/null
echo '#inspect'
docker ps -aq | xargs -r docker inspect --format '{{.Name}}|{{.Image}}|{{index .Config.Labels "com.docker.compose.project.working_dir"}}|{{index .Config.Labels "com.docker.compose.project.config_files"}}' 2>/dev/null'''


def installed(machine, check=True):
    r = _orb(machine, _PS_SH, timeout=40)
    part, rows, img_digest, inspect = 'ps', [], {}, {}
    for line in r.stdout.splitlines():
        if line in ('#images', '#inspect'):
            part = line[1:]; continue
        if part == 'ps' and line.startswith('{'):
            rows.append(json.loads(line))
        elif part == 'images':
            bits = line.split()
            if len(bits) >= 3 and bits[1].startswith('sha256:'):
                img_digest.setdefault(bits[2], set()).add(bits[1])
        elif part == 'inspect':
            bits = line.split('|')
            if len(bits) >= 2:
                inspect[bits[0].lstrip('/')] = {"image_id": bits[1].replace('sha256:', '')[:12],
                                                "workdir": bits[2] if len(bits) > 2 else '', "files": bits[3] if len(bits) > 3 else ''}
    projects = {}
    for c in rows:
        labels = dict(kv.split('=', 1) for kv in (c.get('Labels') or '').split(',') if '=' in kv)
        p = labels.get('com.docker.compose.project')
        if not p:
            continue
        info = inspect.get(c['Names'], {})
        local = img_digest.get(info.get('image_id', ''), set())
        projects.setdefault(p, {"project": p, "machine": machine, "workdir": info.get('workdir'), "files": info.get('files'), "containers": []})
        projects[p]["containers"].append({"name": c['Names'], "image": c['Image'], "state": c.get('State'), "status": c.get('Status'),
                                          "ports": c.get('Ports'), "_local": local})
    if check:
        # only images pulled from a registry (a locally built one has no digest to compare)
        refs = {c['image'] for p in projects.values() for c in p['containers'] if c['_local'] and not c['image'].startswith('sha256')}
        with ThreadPoolExecutor(max_workers=8) as pool:
            remote = dict(zip(refs, pool.map(remote_digest, refs)))
        for p in projects.values():
            for c in p['containers']:
                rd = remote.get(c['image'])
                c['update'] = None if not rd or not c['_local'] else rd not in c['_local']
    for p in projects.values():
        for c in p['containers']:
            c.pop('_local', None)
        p['catalog'] = p['project'] if p['project'] in BY_ID else None
        p['running'] = sum(1 for c in p['containers'] if c['state'] == 'running')
        p['updates'] = sum(1 for c in p['containers'] if c.get('update'))
    return sorted(projects.values(), key=lambda p: p['project'])


# ---- jobs -----------------------------------------------------------------------------------
def _job(**kw):
    j = {"id": uuid.uuid4().hex[:10], "state": "running", "started": int(time.time()), "log": '', **kw}
    with _lock:
        _jobs[j['id']] = j
    return j


def _run(j, machine, script, *args, stdin=None, timeout=1800):
    try:
        r = _orb(machine, script, *args, stdin=stdin, timeout=timeout)
        j['log'] = ((r.stdout or '') + (r.stderr or ''))[-8000:]
        j['state'] = 'done' if r.returncode == 0 else 'failed'
        if r.returncode:
            tail = [l for l in (r.stderr or r.stdout or '').strip().splitlines() if l.strip()]
            j['error'] = tail[-1][:300] if tail else f'exit {r.returncode}'
    except Exception as e:
        j.update(state='failed', error=str(e))
    j['finished'] = int(time.time())
    # the images just pulled are the newest: their digests are worth asking again
    _digests.clear()


_INSTALL_SH = r'''set -e
mkdir -p "/opt/stacks/$1"
cd "/opt/stacks/$1"
[ -e compose.yml ] && { echo "/opt/stacks/$1 already exists" >&2; exit 1; }
cat > compose.yml
: > .installed-by-dashboard
docker compose up -d 2>&1'''

# compose's own files when it has them, else the project name alone (containers it already knows)
_COMPOSE_SH = r'''p=$1; wd=$2; files=$3; act=$4
set --
[ -n "$wd" ] && [ -d "$wd" ] && cd "$wd"
old=$IFS; IFS=,; for f in $files; do [ -f "$f" ] && set -- "$@" -f "$f"; done; IFS=$old
case "$act" in
  update) docker compose -p "$p" "$@" pull 2>&1 && docker compose -p "$p" "$@" up -d 2>&1 ;;
  restart) docker compose -p "$p" "$@" restart 2>&1 ;;
  remove) docker compose -p "$p" "$@" down 2>&1 &&
    # a folder the dashboard made for this app goes too (its data is in named volumes, which stay)
    if [ -f "/opt/stacks/$p/.installed-by-dashboard" ]; then rm -f "/opt/stacks/$p/compose.yml" "/opt/stacks/$p/.installed-by-dashboard"; rmdir "/opt/stacks/$p" 2>/dev/null; fi; true ;;
esac'''


# ---- routes ---------------------------------------------------------------------------------
@apps_bp.route('/catalog', methods=['GET'])
def catalog():
    return jsonify({"status": "success", "data": {
        "apps": [{k: a[k] for k in ('id', 'name', 'category', 'port', 'icon', 'desc')} for a in APPS],
        "machines": machines()}})


@apps_bp.route('/installed', methods=['GET'])
def list_installed():
    check = request.args.get('check', '1') != '0'
    ms = machines()
    with ThreadPoolExecutor(max_workers=4) as pool:
        out = [p for ps in pool.map(lambda m: installed(m, check), ms) for p in ps]
    with _lock:
        jobs = [dict(j) for j in _jobs.values() if j['state'] == 'running' or time.time() - j.get('finished', 0) < 900]
    return jsonify({"status": "success", "data": {"projects": out, "machines": ms, "jobs": jobs}})


@apps_bp.route('/install', methods=['POST'])
def install():
    b = request.get_json(silent=True) or {}
    app, machine = BY_ID.get(b.get('app')), b.get('machine')
    if not app:
        return jsonify({"status": "error", "message": "Unknown app"}), 404
    if machine not in machines():
        return jsonify({"status": "error", "message": "Pick a running machine that has Docker"}), 400
    try:
        port = int(b.get('port') or app['port'])
        assert 1 <= port <= 65535
    except (ValueError, AssertionError):
        return jsonify({"status": "error", "message": "Port must be 1 to 65535"}), 400
    busy = _orb(machine, "ss -ltnH 2>/dev/null | awk '{print $4}' | sed 's/.*://' || netstat -ltn | awk 'NR>2 {print $4}' | sed 's/.*://'", timeout=15).stdout.split()
    if str(port) in busy:
        return jsonify({"status": "error", "message": f"Port {port} is already in use in {machine}"}), 409
    try:
        tz = subprocess.run(['readlink', '/etc/localtime'], capture_output=True, text=True).stdout.strip().split('zoneinfo/')[-1] or 'UTC'
    except Exception:
        tz = 'UTC'
    compose = app['compose'].format(port=port, secret=secrets.token_urlsafe(24), tz=tz)
    j = _job(kind='install', app=app['id'], name=app['name'], machine=machine, port=port)
    threading.Thread(target=_run, args=(j, machine, _INSTALL_SH, app['id']), kwargs={"stdin": compose}, daemon=True).start()
    return jsonify({"status": "success", "data": j})


@apps_bp.route('/<machine>/<project>/<action>', methods=['POST'])
def act(machine, project, action):
    if action not in ('update', 'restart', 'remove'):
        return jsonify({"status": "error", "message": "Unknown action"}), 400
    if machine not in machines() or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', project):
        return jsonify({"status": "error", "message": "Unknown app"}), 404
    p = next((p for p in installed(machine, check=False) if p['project'] == project), None)
    if not p:
        return jsonify({"status": "error", "message": "No such app"}), 404
    with _lock:
        if any(j.get('project') == project and j['machine'] == machine and j['state'] == 'running' for j in _jobs.values()):
            return jsonify({"status": "error", "message": "Already busy"}), 409
    j = _job(kind=action, project=project, machine=machine)
    threading.Thread(target=_run, args=(j, machine, _COMPOSE_SH, project, p.get('workdir') or '', p.get('files') or '', action), daemon=True).start()
    return jsonify({"status": "success", "data": j})
