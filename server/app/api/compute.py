"""Compute pools: several computers of the cluster used as one big machine.

A pool is a folder ~/pools/<name>/ with pool.json (what the dashboard edits) and the
pool.yaml written from it for the pool tool (~/pool/pool.py, Dask underneath). The folder is
also the pool's project: its scripts are synced to every node and run as jobs. The tool does
the work (install, sync, start, stop, run); this module calls it and keeps track:

  up / down     a background operation per pool, its output kept for the page
  live          `pool live` (cores, memory, tasks per node), cached a few seconds
  metrics       `pool watch`, one long-running reader per pool while someone looks at it:
                a reading every 2 s (cores busy, tasks finished, queued, memory per
                computer), the last 30 minutes kept for the graphs
  jobs          `pool run <script>` as its own process; output in .pool-jobs/<id>.log
  files         the project's text files, to read and edit from the page

Deleting a pool moves its folder to ~/pools/.trash, since it may hold someone's code.
"""
from flask import Blueprint, jsonify, request
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

from app.core.logger import log
from app.core import server_cfg

compute_bp = Blueprint('compute', __name__)

POOLS = Path.home() / 'pools'
TOOL = Path.home() / 'pool' / 'pool.py'
UV = str(Path.home() / '.local' / 'bin' / 'uv')
NAME_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,30}$')
NODE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$')
SSH_RE = re.compile(r'^([A-Za-z0-9._-]+@)?[A-Za-z0-9._-]+$')
TAG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,30}$')
PKG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\-\[\],<>=!~ ]{0,80}$')
FIRST_PORT = 8786
TEXT_EXT = {'.py', '.txt', '.md', '.json', '.csv', '.yaml', '.yml', '.toml', '.sh', '.cfg', '.ini'}
MAX_FILE = 1_000_000
MAX_SETUP = 20_000

_lock = threading.Lock()
_ops = {}                  # pool name -> {"kind", "state", "log": [lines], "started", "ended"}
_live = {}                 # pool name -> (at, data)
_waiting = set()           # job ids this process started and is waiting on
_watch = {}                # pool name -> {"proc", "points": deque, "asked": ts, "error"}
WATCH_KEEP = 900           # 30 minutes of 2 s readings
WATCH_IDLE = 300           # stop reading when nobody has looked for 5 minutes


def _err(msg, code=400):
    return jsonify({"status": "error", "message": msg}), code


def _env():
    return {**os.environ, "PATH": f"{Path.home() / '.local' / 'bin'}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}


# ---- definitions ---------------------------------------------------------------------

def _dir(name):
    return POOLS / name


def _load(name):
    try:
        return json.loads((_dir(name) / 'pool.json').read_text())
    except (OSError, ValueError):
        return None


def _all():
    if not POOLS.is_dir():
        return []
    out = []
    for d in sorted(POOLS.iterdir()):
        if d.is_dir() and not d.name.startswith('.') and (d / 'pool.json').exists():
            cfg = _load(d.name)
            if cfg:
                out.append(cfg)
    return out


def _yaml_value(v):
    return json.dumps(v)       # a JSON string, list or number is valid YAML


def _q(v):
    """A YAML scalar: bare when that reads back as the same string, else JSON-quoted."""
    v = str(v)
    if re.match(r'^[A-Za-z0-9][A-Za-z0-9._/@+-]*$', v) and v.lower() not in ('yes', 'no', 'on', 'off', 'true', 'false', 'null'):
        try:
            float(v)
        except ValueError:
            return v
    return json.dumps(v)


def _write(cfg):
    """pool.json, and pool.yaml: the same definition as a file to read and edit (the Files
    tab saves it back through _from_yaml)."""
    d = _dir(cfg["name"])
    d.mkdir(parents=True, exist_ok=True)
    (d / 'pool.json').write_text(json.dumps(cfg, indent=2) + '\n')
    setup = (cfg.get("setup") or '').split('\n') if cfg.get("setup") else []
    L = ["# This pool's definition: edit here or in Settings; saved changes apply on the next start.", "",
         f"name: {_q(cfg['name'])}",
         f"python: {_q(cfg['python'])}",
         f"coordinator: {_q(cfg['scheduler'])}        # hands out the work",
         f"jobs_on: {_q(cfg.get('jobs_on') or 'arrakis')}        # where job scripts run: arrakis, or a node (its environment, setup included)",
         f"port: {cfg['port']}", "",
         "# pip packages, the same versions on every computer and for the job on Arrakis",
         "packages:" + ("" if cfg['packages'] else " []")]
    L += [f"  - {_q(x)}" for x in cfg['packages']]
    L += ["", "# Shell commands run once per computer, after the packages, in their own folder",
          "# ($POOL_WORK, importable from jobs). pip installs into the pool's Python.",
          "# Changing them gives every computer a fresh environment.",
          "setup: |" if setup else "setup: \"\""]
    L += [f"  {ln}" for ln in setup]
    L += ["", "computers:"]
    for node, spec in cfg["nodes"].items():
        L.append(f"  {_q(node)}:")
        L.append(f"    ssh: {_q(spec['ssh'])}")
        if spec.get("vm"):
            L.append("    vm: true")
        if spec.get("host"):
            L.append(f"    host: {_q(spec['host'])}")
        if spec.get("via"):
            L.append(f"    via: {_q(spec['via'])}")
        if spec.get("tags"):
            L.append(f"    tags: [{', '.join(_q(t) for t in spec['tags'])}]")
        if spec.get("procs"):
            L.append(f"    processes: {spec['procs']}")
    (d / 'pool.yaml').write_text('\n'.join(L) + '\n')


def _from_yaml(name, text):
    """An edited pool.yaml back into a definition: (cfg, error)."""
    import yaml
    try:
        y = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        mark = getattr(e, 'problem_mark', None)
        return None, f"pool.yaml line {mark.line + 1}: {getattr(e, 'problem', e)}" if mark else f"pool.yaml: {e}"
    if not isinstance(y, dict):
        return None, "pool.yaml should be a list of settings (python:, computers:, …)"
    cur = _load(name) or {}
    setup = y.get("setup") or []
    nodes = y.get("computers", y.get("nodes"))
    if not isinstance(nodes, dict):
        return None, "computers: one entry per computer, each with an ssh: line"
    body = {"python": y.get("python"), "packages": y.get("packages") or [],
            "setup": '\n'.join(str(x) for x in setup) if isinstance(setup, list) else str(setup),
            "scheduler": y.get("coordinator", y.get("scheduler")),
            "jobs_on": y.get("jobs_on") or 'arrakis',
            "nodes": {str(n): {**(v or {}), "procs": (v or {}).get("processes", (v or {}).get("procs"))}
                      for n, v in nodes.items()}}
    cfg, err = _clean(body, existing=cur)
    if cfg and y.get("port") not in (None, cur.get("port")):
        cfg["port"] = y["port"] if isinstance(y["port"], int) and 1024 < y["port"] < 65000 else cur.get("port")
    return cfg, err


def _clean(body, existing=None):
    """Validate a definition from the page; returns (cfg, error)."""
    name = (existing or {}).get("name") or (body.get("name") or '').strip().lower()
    if not NAME_RE.match(name):
        return None, "Name: lowercase letters, digits and dashes (up to 31)"
    python = str(body.get("python") or (existing or {}).get("python") or "3.13").strip()
    if not re.match(r'^3\.\d{1,2}$', python):
        return None, "Python: a version like 3.13"
    packages = body.get("packages", (existing or {}).get("packages", []))
    if isinstance(packages, str):
        packages = [p.strip() for p in re.split(r'[\n,]+', packages) if p.strip()]
    for p in packages:
        if not PKG_RE.match(p):
            return None, f"Not a package name: {p}"
    setup = str(body.get("setup", (existing or {}).get("setup")) or '').replace('\r\n', '\n').strip()
    if len(setup) > MAX_SETUP:
        return None, f"Setup script: at most {MAX_SETUP:,} characters"
    raw = body.get("nodes", (existing or {}).get("nodes"))
    if not raw:
        return None, "Pick at least one computer"
    nodes = {}
    for node, spec in (raw.items() if isinstance(raw, dict) else ((n.get("id"), n) for n in raw)):
        spec = spec or {}
        if not node or not NODE_RE.match(str(node)):
            return None, f"Bad computer name: {node}"
        ssh = (spec.get("ssh") or node).strip()
        if not SSH_RE.match(ssh):
            return None, f"{node}: the SSH login should look like user@host"
        tags = [t.strip().lower() for t in (spec.get("tags") or []) if str(t).strip()]
        for t in tags:
            if not TAG_RE.match(t):
                return None, f"{node}: tags are lowercase words ({t})"
        procs = spec.get("procs") or None
        if procs is not None and not (isinstance(procs, int) and 1 <= procs <= 256):
            return None, f"{node}: processes must be a number from 1 to 256"
        nodes[str(node)] = {"ssh": ssh, "tags": tags, "procs": procs, "vm": bool(spec.get("vm"))}
        if spec.get("vm") and spec.get("host"):      # the host it runs on (arrakis = through OrbStack)
            nodes[str(node)]["host"] = str(spec["host"])
        via = (spec.get("via") or '').strip()
        if spec.get("vm") and spec.get("host") != 'arrakis' and via:
            if not SSH_RE.match(via):                # the host's login: Arrakis reaches the VM through it
                return None, f"{node}: the host login should look like user@host"
            nodes[str(node)]["via"] = via
    scheduler = (body.get("scheduler") or (existing or {}).get("scheduler") or
                 ('arrakis' if 'arrakis' in nodes else next(iter(nodes))))
    # Arrakis can also coordinate without doing work itself
    if scheduler != 'arrakis' and scheduler not in nodes:
        return None, f"The coordinator has to be {server_cfg.name()} or one of the pool's computers"
    jobs_on = str(body.get("jobs_on", (existing or {}).get("jobs_on")) or 'arrakis')
    if jobs_on != 'arrakis' and jobs_on not in nodes:
        jobs_on = 'arrakis'                 # that node left the pool: back to Arrakis
    port = (existing or {}).get("port")
    if not port:
        used = {p["port"] for p in _all()}
        port = next(p for p in range(FIRST_PORT, FIRST_PORT + 400, 2) if p not in used)
    return {"name": name, "python": python, "packages": packages, "setup": setup, "scheduler": scheduler,
            "jobs_on": jobs_on, "port": port, "nodes": nodes}, None


# ---- state ---------------------------------------------------------------------------

def _address(cfg):
    """Where the coordinator is: the address `pool up` worked out and saved in the pool's state
    file (one place decides it); before a first start, Arrakis or the coordinator's host."""
    try:
        addr = json.loads((_dir(cfg["name"]) / '.pool-state.json').read_text())["address"]
        return addr.split('//')[-1].rsplit(':', 1)[0]
    except (OSError, ValueError, KeyError):
        pass
    if cfg["scheduler"] == 'arrakis':
        return '127.0.0.1'
    return cfg["nodes"].get(cfg["scheduler"], {}).get("ssh", cfg["scheduler"]).split('@')[-1]


def _counts(cfg):
    """The scheduler's own counters (its HTTP port is the pool's port + 1); None = not running."""
    try:
        with urllib.request.urlopen(f"http://{_address(cfg)}:{cfg['port'] + 1}/json/counts.json", timeout=2) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def _summary(cfg):
    c = _counts(cfg)
    with _lock:
        op = _ops.get(cfg["name"])
        op = {k: v for k, v in op.items() if k != 'log'} if op else None
    return {**cfg, "running": c is not None,
            "counts": c and {k: c.get(k) for k in ('cores', 'workers', 'hosts', 'processing', 'tasks', 'memory', 'clients')},
            "op": op, "jobs": _job_counts(cfg["name"]),
            "running_jobs": [{k: j[k] for k in ('id', 'script', 'args', 'started')} for j in _jobs(cfg["name"], 20) if j["state"] == 'running']}


def _tool(name, *args, timeout=None):
    return subprocess.run([UV, 'run', '-q', '--script', str(TOOL), *args], cwd=_dir(name), env=_env(),
                          capture_output=True, text=True, timeout=timeout)


def _run_op(name, kind):
    """`pool up` or `pool down` in the background, its output kept line by line."""
    try:
        p = subprocess.Popen([UV, 'run', '-q', '--script', str(TOOL), kind], cwd=_dir(name), env=_env(),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            with _lock:
                _ops[name]["log"].append(line.rstrip())
                del _ops[name]["log"][:-400]
        rc = p.wait()
        state = 'done' if rc == 0 else 'error'
    except Exception as e:  # noqa: BLE001
        with _lock:
            _ops[name]["log"].append(str(e))
        state = 'error'
    with _lock:
        _ops[name].update(state=state, ended=time.time())
        _live.pop(name, None)
    if kind == 'down':
        _stop_watch(name)
    log.info(f"pool {name}: {kind} {state}")


# ---- metrics: `pool watch` while someone looks ----------------------------------------

def _watch_reader(name, w):
    p = w["proc"]
    for line in p.stdout:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if "warning" in d:
            w["error"] = d["warning"]
        elif "nodes" in d:
            w["points"].append(d)
            w["error"] = None
            if len(w["points"]) % 15 == 0:      # every ~30 s: the graphs survive a dashboard restart
                _save_history(name, w)
        if time.time() - w["asked"] > WATCH_IDLE:
            p.terminate()
            break
    p.wait()
    _save_history(name, w)
    with _lock:
        if _watch.get(name) is w:
            w["proc"] = None


def _history_file(name):
    return _dir(name) / '.pool-metrics.json'


def _save_history(name, w):
    try:
        with _lock:
            pts = list(w["points"])
        _history_file(name).write_text(json.dumps(pts))
    except OSError as e:
        log.warning(f"pool {name}: saving graph history: {e}")


def _load_history(name):
    try:
        pts = json.loads(_history_file(name).read_text())
        return [p for p in pts if p.get("t", 0) > time.time() - WATCH_KEEP * 2]
    except (OSError, ValueError):
        return []


def _stop_watch(name):
    """The pool stopped: its watcher would otherwise keep trying to reach a coordinator
    that is gone (Dask's client retries quietly), and keep reporting 'watching'."""
    with _lock:
        w = _watch.get(name)
        p = w and w["proc"]
    if p:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except OSError:
            pass


def _watching(name, cfg):
    """The pool's watcher, started if it isn't running (and the pool is)."""
    with _lock:
        w = _watch.get(name)
        if w is None:
            w = _watch[name] = {"proc": None, "points": deque(_load_history(name), maxlen=WATCH_KEEP), "asked": 0, "error": None}
        w["asked"] = time.time()
        if w["proc"] is None and _counts(cfg) is not None:
            w["proc"] = subprocess.Popen([UV, 'run', '-q', '--script', str(TOOL), 'watch'], cwd=_dir(name), env=_env(),
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
            threading.Thread(target=_watch_reader, args=(name, w), daemon=True).start()
    return w


# ---- jobs ----------------------------------------------------------------------------

def _jobs_dir(name):
    return _dir(name) / '.pool-jobs'


def _job(name, jid, check=True):
    try:
        j = json.loads((_jobs_dir(name) / f'{jid}.json').read_text())
    except (OSError, ValueError):
        return None
    if check and j["state"] == 'running' and not _alive(j.get("pid")) and j["id"] not in _waiting:
        # the dashboard restarted while it ran: the process is gone and nobody saw it end
        j.update(state='unknown', ended=j.get("ended") or time.time())
        _save_job(name, j)
    return j


def _save_job(name, j):
    (_jobs_dir(name) / f'{j["id"]}.json').write_text(json.dumps(j))


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _jobs(name, limit=50):
    d = _jobs_dir(name)
    if not d.is_dir():
        return []
    ids = sorted((int(p.stem) for p in d.glob('*.json') if p.stem.isdigit()), reverse=True)[:limit]
    return [j for j in (_job(name, i) for i in ids) if j]


def _job_counts(name):
    js = _jobs(name, 200)
    return {"total": len(js), "running": sum(1 for j in js if j["state"] == 'running')}


def _wait_job(name, j, p, logf):
    rc = p.wait()
    logf.close()
    j = _job(name, j["id"], check=False) or j
    if j["state"] == 'running':
        j.update(state='done' if rc == 0 else ('stopped' if j.get("stopping") else 'failed'), rc=rc, ended=time.time())
        _save_job(name, j)
    _waiting.discard(j["id"])
    log.info(f"pool {name}: job {j['id']} {j['script']} -> {j['state']}")


def _project_path(name, rel):
    """A path inside the pool's project folder, never outside it or into its hidden state."""
    base = _dir(name).resolve()
    p = (base / rel).resolve()
    if base not in p.parents and p != base:
        return None
    if any(part.startswith('.') for part in p.relative_to(base).parts):
        return None
    return p


# ---- routes: pools -------------------------------------------------------------------

@compute_bp.route('/pools', methods=['GET'])
def list_pools():
    return jsonify({"status": "success", "data": [_summary(c) for c in _all()],
                    "tool": TOOL.exists() and os.path.exists(UV)})


@compute_bp.route('/candidates', methods=['GET'])
def candidates():
    """Computers a pool can use: Arrakis and every host of the cluster, with an SSH login guess
    (what an existing pool already uses for it, else the host's ssh_user, else its name)."""
    from app.api.hosts import _load as load_hosts, _public
    known = {}
    for c in _all():
        for n, spec in c["nodes"].items():
            known.setdefault(n, spec.get("ssh"))
    out = [{"id": "arrakis", "name": server_cfg.name(), "ssh": known.get("arrakis", "arrakis"), "online": True, "os": "macOS", "cores": os.cpu_count()}]
    for h in load_hosts():
        p = _public(h)
        r = p.get("report") or {}
        guess = known.get(h['id']) or (f"{h['ssh_user']}@{h['name']}" if h.get('ssh_user') else h['name'])
        out.append({"id": h['id'], "name": h['name'], "ssh": guess, "online": p["online"], "os": r.get("os"), "cores": r.get("cores")})
    # Arrakis's own OrbStack VMs: reached through OrbStack's SSH (<machine>@orb, its default
    # user, the Mac's keys); workers there offer their tailnet address when they have one
    try:
        from app.api.vms import _get_list
        machines, cfg = _get_list()
        pool_cpu = int(cfg.get('cpu') or 0) or os.cpu_count()
        taken = {c["id"] for c in out}
        for m in machines:
            mid = m["name"] if m["name"] not in taken else f"arrakis-{m['name']}"
            img = m.get("image") or {}
            ts = m.get("tailscale") or {}
            out.append({"id": mid, "name": m["name"], "vm": True, "parent": "arrakis",
                        "user": m.get("username"), "online": m.get("state") == 'running',
                        "ssh": known.get(mid) or f"{m.get('username') or 'root'}@{m['name']}",
                        "os": ' '.join(str(x) for x in (img.get("distro"), img.get("version")) if x).title() or None,
                        "cores": m.get("cpu") or pool_cpu, "tailnet": ts.get("ip") if ts.get("state") == 'running' else None})
    except Exception as e:  # noqa: BLE001 (OrbStack off: just the hosts)
        log.warning(f"compute candidates: no machines ({e})")
    # VMs on the other hosts: their OrbStack address is private to that host, so only the ones
    # on the tailnet can work in a pool (ssh <user>@<machine> through Tailscale SSH)
    from app.core import orbhost
    from app.api.vms import _get_list
    tailnet = _tailnet_ips()
    names = {h['id']: h['name'] for h in load_hosts()}
    for hid in orbhost.managed():
        token = orbhost.current.set(hid)
        try:
            machines, cfg = _get_list()          # that host's OrbStack, through its agent
        except Exception as e:  # noqa: BLE001
            log.warning(f"compute candidates: no machines on {hid} ({e})")
            continue
        finally:
            orbhost.current.reset(token)
        for m in machines:
            taken = {c["id"] for c in out}
            mid = m["name"] if m["name"] not in taken else f"{hid}-{m['name']}"
            img = m.get("image") or {}
            ip = (m.get("tailscale") or {}).get("ip") or tailnet.get(m["name"])
            out.append({"id": mid, "name": m["name"], "vm": True, "parent": hid, "user": m.get("username"),
                        "ssh": known.get(mid) or f"{m.get('username') or 'root'}@{m['name']}",
                        "online": m.get("state") == 'running' and bool(ip),
                        "os": ' '.join(str(x) for x in (img.get("distro"), img.get("version")) if x).title() or None,
                        "cores": m.get("cpu") or int(cfg.get('cpu') or 0) or None, "tailnet": ip})
    return jsonify({"status": "success", "data": out})


def _tailnet_ips():
    """{tailnet hostname: IPv4} of the peers this Mac sees online."""
    try:
        r = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=5, env=_env())
        peers = json.loads(r.stdout).get("Peer", {}).values()
        return {p["HostName"]: p["TailscaleIPs"][0] for p in peers if p.get("Online") and p.get("TailscaleIPs")}
    except Exception:  # noqa: BLE001
        return {}


@compute_bp.route('/ssh-check', methods=['POST'])
def ssh_check():
    body = request.get_json(silent=True) or {}
    target = (body.get("ssh") or '').strip()
    if not SSH_RE.match(target):
        return _err("That doesn't look like user@host")
    if body.get("host") == 'arrakis':     # one of Arrakis's VMs: OrbStack's SSH, user@machine@orb
        target += '@orb'
    via = (body.get("via") or '').strip()
    if via and SSH_RE.match(via):          # another host's VM: through that host's OrbStack
        machine = target.split('@')[-1]
        target = None
        cmd = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6', via,
               f"PATH=/opt/homebrew/bin:/usr/local/bin:$PATH orb -m {machine} echo ok"]
    try:
        r = subprocess.run(cmd if target is None else ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6', target, 'echo ok'],
                           capture_output=True, text=True, timeout=12)
        ok = r.returncode == 0 and r.stdout.strip() == 'ok'
        msg = f'{server_cfg.name()} can log in' if ok else ((r.stderr.strip().splitlines() or ['no answer'])[-1])
    except subprocess.TimeoutExpired:
        ok, msg = False, 'no answer within 12 s'
    return jsonify({"status": "success", "data": {"ok": ok, "message": msg}})


@compute_bp.route('/pools', methods=['POST'])
def create_pool():
    body = request.get_json(silent=True) or {}
    cfg, err = _clean(body)
    if err:
        return _err(err)
    if _dir(cfg["name"]).exists():
        return _err(f"A pool called {cfg['name']} already exists", 409)
    _write(cfg)
    (_dir(cfg["name"]) / 'job.py').write_text(STARTER_JOB)
    log.info(f"pool {cfg['name']} created: {', '.join(cfg['nodes'])}")
    return jsonify({"status": "success", "data": _summary(cfg)})


@compute_bp.route('/pools/<name>', methods=['GET'])
def get_pool(name):
    cfg = _load(name)
    if not cfg:
        return _err("No such pool", 404)
    with _lock:
        op = dict(_ops[name]) if name in _ops else None
    return jsonify({"status": "success", "data": {**_summary(cfg), "op": op, "path": str(_dir(name))}})


@compute_bp.route('/pools/<name>', methods=['PATCH'])
def update_pool(name):
    cur = _load(name)
    if not cur:
        return _err("No such pool", 404)
    cfg, err = _clean(request.get_json(silent=True) or {}, existing=cur)
    if err:
        return _err(err)
    _write(cfg)
    return jsonify({"status": "success", "data": _summary(cfg)})


@compute_bp.route('/pools/<name>', methods=['DELETE'])
def delete_pool(name):
    cfg = _load(name)
    if not cfg:
        return _err("No such pool", 404)
    if _counts(cfg) is not None:
        return _err("Stop the pool first")
    trash = POOLS / '.trash'
    trash.mkdir(exist_ok=True)
    dest = trash / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(_dir(name)), str(dest))
    log.info(f"pool {name} deleted (moved to {dest})")
    return jsonify({"status": "success", "data": {"moved_to": str(dest)}})


@compute_bp.route('/pools/<name>/<kind>', methods=['POST'])
def pool_op(name, kind):
    if kind not in ('up', 'down'):
        return _err("Unknown action", 404)
    if not _load(name):
        return _err("No such pool", 404)
    with _lock:
        if _ops.get(name, {}).get("state") == 'running':
            return _err("Already busy: wait for it to finish")
        _ops[name] = {"kind": kind, "state": 'running', "log": [], "started": time.time(), "ended": None}
    threading.Thread(target=_run_op, args=(name, kind), daemon=True).start()
    return jsonify({"status": "success"})


@compute_bp.route('/pools/<name>/live', methods=['GET'])
def pool_live(name):
    """Per computer: cores, memory, tasks in progress, CPU now (from the scheduler itself)."""
    cfg = _load(name)
    if not cfg:
        return _err("No such pool", 404)
    hit = _live.get(name)
    if hit and time.time() - hit[0] < 4:
        return jsonify({"status": "success", "data": hit[1]})
    if _counts(cfg) is None:
        data = {"ok": False, "error": "not running"}
    else:
        try:
            r = _tool(name, 'live', timeout=40)
            line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith('{')), '')
            data = json.loads(line) if line else {"ok": False, "error": (r.stderr.strip().splitlines() or ['no answer'])[-1]}
        except (subprocess.TimeoutExpired, ValueError) as e:
            data = {"ok": False, "error": str(e)}
    _live[name] = (time.time(), data)
    return jsonify({"status": "success", "data": data})


@compute_bp.route('/pools/<name>/metrics', methods=['GET'])
def pool_metrics(name):
    """Readings since ?since= (unix seconds); the first call starts the watcher, so the graph
    fills from then on."""
    cfg = _load(name)
    if not cfg:
        return _err("No such pool", 404)
    if _counts(cfg) is None:
        _stop_watch(name)
    w = _watching(name, cfg)
    since = request.args.get('since', default=0, type=float)
    with _lock:
        pts = [p for p in w["points"] if p["t"] > since]
    return jsonify({"status": "success", "data": {"points": pts, "watching": w["proc"] is not None,
                                                  "every": 2, "warning": w["error"]}})


# ---- routes: jobs --------------------------------------------------------------------

@compute_bp.route('/pools/<name>/jobs', methods=['GET'])
def list_jobs(name):
    if not _load(name):
        return _err("No such pool", 404)
    return jsonify({"status": "success", "data": _jobs(name)})


@compute_bp.route('/pools/<name>/jobs', methods=['POST'])
def start_job(name):
    if not _load(name):
        return _err("No such pool", 404)
    body = request.get_json(silent=True) or {}
    script = (body.get("script") or '').strip()
    p = _project_path(name, script)
    if not p or p.suffix != '.py' or not p.is_file():
        return _err("Pick a .py file from the pool's folder")
    args = body.get("args") or []
    if isinstance(args, str):
        import shlex
        try:
            args = shlex.split(args)
        except ValueError as e:
            return _err(f"Arguments: {e}")
    d = _jobs_dir(name)
    d.mkdir(exist_ok=True)
    jid = int(time.time() * 1000)
    rel = str(p.relative_to(_dir(name).resolve()))
    logf = open(d / f'{jid}.log', 'w')
    proc = subprocess.Popen([UV, 'run', '-q', '--script', str(TOOL), 'run', rel, *[str(a) for a in args]],
                            cwd=_dir(name), env={**_env(), "POOL_QUIET": "1"}, stdout=logf, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True)
    j = {"id": jid, "script": rel, "args": [str(a) for a in args], "state": 'running',
         "pid": proc.pid, "started": time.time(), "ended": None, "rc": None}
    _save_job(name, j)
    _waiting.add(jid)
    threading.Thread(target=_wait_job, args=(name, j, proc, logf), daemon=True).start()
    log.info(f"pool {name}: job {jid} {rel} started")
    return jsonify({"status": "success", "data": j})


@compute_bp.route('/pools/<name>/jobs/<int:jid>', methods=['GET'])
def get_job(name, jid):
    """The job, and its output from ?offset= (bytes) on, so the page can follow it."""
    j = _job(name, jid)
    if not j:
        return _err("No such job", 404)
    offset = max(0, request.args.get('offset', default=0, type=int))
    if request.args.get('tail'):
        # just its latest lines of output (?tail=N), for the pool's overview
        last = []
        try:
            with open(_jobs_dir(name) / f'{jid}.log', 'rb') as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 4000))
                lines = [l for l in f.read().decode(errors='replace').splitlines() if l.strip()]
                n = max(1, min(20, request.args.get('tail', default=1, type=int)))
                last = lines[-n:]
        except OSError:
            last = []
        return jsonify({"status": "success", "data": {**j, "last": last}})
    text, size = '', 0
    try:
        with open(_jobs_dir(name) / f'{jid}.log', 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            if offset < size:
                f.seek(max(offset, size - 400_000))
                text = f.read().decode(errors='replace')
    except OSError:
        pass
    return jsonify({"status": "success", "data": {**j, "output": text, "offset": size}})


@compute_bp.route('/pools/<name>/jobs/<int:jid>/stop', methods=['POST'])
def stop_job(name, jid):
    j = _job(name, jid)
    if not j:
        return _err("No such job", 404)
    if j["state"] != 'running':
        return _err("It isn't running")
    j["stopping"] = True
    _save_job(name, j)
    try:
        os.killpg(j["pid"], signal.SIGTERM)
    except OSError as e:
        return _err(str(e))
    return jsonify({"status": "success"})


@compute_bp.route('/pools/<name>/jobs/<int:jid>', methods=['DELETE'])
def delete_job(name, jid):
    j = _job(name, jid)
    if not j:
        return _err("No such job", 404)
    if j["state"] == 'running':
        return _err("Stop it first")
    for ext in ('json', 'log'):
        (_jobs_dir(name) / f'{jid}.{ext}').unlink(missing_ok=True)
    return jsonify({"status": "success"})


# ---- routes: files -------------------------------------------------------------------

@compute_bp.route('/pools/<name>/files', methods=['GET'])
def list_files(name):
    if not _load(name):
        return _err("No such pool", 404)
    base = _dir(name).resolve()
    out = []
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in ('__pycache__', 'node_modules', '.venv'))
        if Path(root) != base and len(Path(root).relative_to(base).parts) > 3:
            continue
        for f in sorted(files):
            if f.startswith('.'):
                continue
            p = Path(root) / f
            out.append({"path": str(p.relative_to(base)), "size": p.stat().st_size, "modified": p.stat().st_mtime,
                        "text": p.suffix.lower() in TEXT_EXT, "generated": f == 'pool.json'})
    return jsonify({"status": "success", "data": out})


@compute_bp.route('/pools/<name>/file', methods=['GET'])
def read_file(name):
    p = _project_path(name, request.args.get('path', ''))
    if not p or not p.is_file():
        return _err("No such file", 404)
    if p.suffix.lower() not in TEXT_EXT or p.stat().st_size > MAX_FILE:
        return _err("Only text files up to 1 MB open here")
    return jsonify({"status": "success", "data": {"path": request.args.get('path'), "text": p.read_text(errors='replace')}})


@compute_bp.route('/pools/<name>/file', methods=['PUT'])
def write_file(name):
    body = request.get_json(silent=True) or {}
    rel = (body.get("path") or '').strip()
    p = _project_path(name, rel)
    if p and rel == 'pool.yaml':
        cfg, err = _from_yaml(name, body.get("text") or '')
        if err:
            return _err(err)
        _write(cfg)
        p.write_text(body["text"])      # keep the file as written, comments and all
        return jsonify({"status": "success", "data": _summary(cfg)})
    if not p or p.name in ('pool.yaml', 'pool.json'):
        return _err("Pick a file name inside the pool's folder (pool.json is written from Settings)")
    if p.suffix.lower() not in TEXT_EXT:
        return _err(f"Text files only ({', '.join(sorted(TEXT_EXT))})")
    text = body.get("text")
    if not isinstance(text, str) or len(text) > MAX_FILE:
        return _err("Up to 1 MB of text")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return jsonify({"status": "success"})


@compute_bp.route('/pools/<name>/file', methods=['DELETE'])
def delete_file(name):
    p = _project_path(name, request.args.get('path', ''))
    if not p or not p.is_file() or p.name in ('pool.yaml', 'pool.json'):
        return _err("No such file", 404)
    p.unlink()
    return jsonify({"status": "success"})


STARTER_JOB = '''"""A first job: every core of the pool squares a number, then the results are added up.
Run it from the Jobs tab. `import pool` gives you the whole pool:

    pool.map(fn, items)          split work over every core, results in order
    pool.stream(fn, items)       results as they finish
    pool.first(fn)               fn(0), fn(1), ... until one returns something
    pool.put(obj)                send a big object once, pass it to every task
    pool.make_shards(fn, keys)   build data on the nodes and keep it there
    pool.each_shard(fn, data)    run fn where each piece lives
"""
import socket
from collections import Counter

import pool


def square(x):
    return x * x


def where(_):
    return socket.gethostname().split('.')[0]


if __name__ == "__main__":
    print(f"{pool.cpus()} cores and {pool.memory() / 2**30:.0f} GB on {len(pool.nodes())} computers")
    print("sum of squares:", sum(pool.map(square, range(1_000_000))))
    print("who did the work:", dict(Counter(pool.map(where, range(500)))))
'''
