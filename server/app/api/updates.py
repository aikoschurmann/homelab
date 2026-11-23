"""Package updates on every computer: what is outdated, and applying them.

    mac            Homebrew on this server (brew outdated --json=v2 / brew upgrade)
    vm:<machine>   each running OrbStack machine's package manager (apk, apt, dnf, pacman)
    host:<id>      another computer, from its agent's inventory (#@updates <manager>);
                   applying asks the agent to run its "upgrade" action (Linux needs a root agent)

Lists are refreshed every 30 minutes in the background, or on Check now.
"""
import json, re, shutil, subprocess, threading, time, uuid

from flask import Blueprint, jsonify, request

from app.core.logger import log

updates_bp = Blueprint('updates', __name__)

EVERY = 1800
_lock = threading.Lock()
_state = {}          # target id -> {"packages", "manager", "checked", "error"}
_jobs = {}
_checking = threading.Event()

BREW = next((p for p in ('/opt/homebrew/bin/brew', '/usr/local/bin/brew') if shutil.os.path.exists(p)), shutil.which('brew'))

# the machine's own package manager: list what's outdated (refreshing its index first)
_LIST_SH = r'''if command -v apk >/dev/null; then echo apk; apk update -q >/dev/null 2>&1; apk list -u 2>/dev/null
elif command -v apt-get >/dev/null; then echo apt; apt-get update -qq >/dev/null 2>&1; apt list --upgradable 2>/dev/null
elif command -v dnf >/dev/null; then echo dnf; dnf -q check-update 2>/dev/null
elif command -v pacman >/dev/null; then echo pacman; pacman -Sy >/dev/null 2>&1; pacman -Qu 2>/dev/null
else echo none; fi; true'''

# upgrade everything, or the packages given as arguments
_UPGRADE_SH = r'''if command -v apk >/dev/null; then apk update && apk upgrade "$@"
elif command -v apt-get >/dev/null; then export DEBIAN_FRONTEND=noninteractive; apt-get update -qq &&
  if [ $# -gt 0 ]; then apt-get install -y --only-upgrade "$@"; else apt-get -y upgrade; fi
elif command -v dnf >/dev/null; then dnf -y upgrade "$@"
elif command -v pacman >/dev/null; then if [ $# -gt 0 ]; then pacman -S --noconfirm "$@"; else pacman -Syu --noconfirm; fi
else echo 'no known package manager' >&2; exit 1; fi'''


# ---- parsing each manager's list --------------------------------------------------------------
def parse(manager, text):
    out = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line or line.startswith(('Listing', 'WARNING', 'Last metadata', 'Obsoleting')):
            continue
        m = None
        if manager == 'apt':
            m = re.match(r'^([^/\s]+)/\S+ (\S+) \S+ \[upgradable from: ([^\]]+)\]', line)
            m and out.append({"name": m.group(1), "current": m.group(3), "latest": m.group(2)})
        elif manager == 'apk':
            m = re.match(r'^(\S+) .*\[upgradable from: (\S+)\]', line)
            if m:
                nm = re.match(r'^(.+?)-(\d[^-]*-r\d+)$', m.group(1))
                old = re.match(r'^(.+?)-(\d[^-]*-r\d+)$', m.group(2))
                out.append({"name": nm.group(1) if nm else m.group(1), "latest": nm.group(2) if nm else '', "current": old.group(2) if old else m.group(2)})
        elif manager == 'dnf':
            m = re.match(r'^(\S+)\.\S+\s+(\S+)\s+\S+$', line)
            m and out.append({"name": m.group(1), "current": None, "latest": m.group(2)})
        elif manager == 'pacman':
            m = re.match(r'^(\S+) (\S+) -> (\S+)', line)
            m and out.append({"name": m.group(1), "current": m.group(2), "latest": m.group(3)})
        elif manager == 'brew':
            m = re.match(r'^(\S+) \(([^)]*)\) [<!=]+ (.+)$', line)
            m and out.append({"name": m.group(1), "current": m.group(2), "latest": m.group(3)})
    return out


# ---- reading them ------------------------------------------------------------------------------
def _mac():
    if not BREW:
        return {"manager": None, "packages": [], "error": "Homebrew isn't installed"}
    r = subprocess.run([BREW, 'outdated', '--json=v2'], capture_output=True, text=True, timeout=180)
    j = json.loads(r.stdout or '{}')
    pk = [{"name": f['name'], "current": ', '.join(f.get('installed_versions') or []), "latest": f.get('current_version'), "pinned": f.get('pinned')}
          for f in j.get('formulae', [])]
    pk += [{"name": c['name'], "current": ', '.join(c.get('installed_versions') or []) if isinstance(c.get('installed_versions'), list) else c.get('installed_versions'),
            "latest": c.get('current_version'), "cask": True} for c in j.get('casks', [])]
    return {"manager": "brew", "packages": pk}


def _machines():
    try:
        out = subprocess.run(['orb', 'list', '-f', 'json'], capture_output=True, text=True, timeout=10).stdout
        return [m['name'] for m in json.loads(out or '[]') if m.get('state') == 'running']
    except Exception:
        return []


def _machine(name):
    r = subprocess.run(['orb', '-m', name, '-u', 'root', 'sh', '-c', _LIST_SH], capture_output=True, text=True, timeout=240)
    lines = r.stdout.splitlines()
    manager = lines[0].strip() if lines else 'none'
    if manager == 'none':
        return {"manager": None, "packages": [], "error": "No known package manager"}
    return {"manager": manager, "packages": parse(manager, '\n'.join(lines[1:]))}


def check(only=None):
    """Refresh the lists (all targets, or one) in the background."""
    def run():
        targets = [('mac', _mac)] + [(f"vm:{m}", lambda m=m: _machine(m)) for m in _machines()]
        for tid, fn in targets:
            if only and tid != only:
                continue
            with _lock:
                _state.setdefault(tid, {})["checking"] = True
            try:
                res = fn()
            except Exception as e:
                res = {"packages": [], "error": str(e)}
            with _lock:
                _state[tid] = {**res, "checked": int(time.time()), "checking": False}
        _checking.clear()
    if only or not _checking.is_set():
        _checking.set()
        threading.Thread(target=run, daemon=True).start()


def loop():
    time.sleep(60)          # let the dashboard settle after a restart
    while True:
        check()
        time.sleep(EVERY)


def start():
    threading.Thread(target=loop, daemon=True, name='updates').start()


# ---- other hosts, from their agent's inventory ----------------------------------------------
def _hosts():
    from app.api.hosts import _load, _built, _public
    out = []
    for h in _load():
        def build(sections, at):
            for k, body in sections.items():
                if k.startswith('updates '):
                    mgr = k.split(' ', 1)[1].strip()
                    return {"manager": mgr, "packages": parse(mgr, body), "checked": int(at)}
            return None
        res = _built(h['id'], 'updates', build)
        view = _public(h)
        rep = view.get('report') or {}
        out.append({"id": f"host:{h['id']}", "name": h['name'], "kind": "host", "online": view.get('online'),
                    "root": rep.get('root'), "agent": rep.get('agent'), "os": rep.get('os'),
                    **(res or {"manager": None, "packages": [], "checked": None})})
    return out


def overview():
    from app.core import server_cfg
    with _lock:
        st = {k: dict(v) for k, v in _state.items()}
    targets = [{"id": "mac", "name": server_cfg.name(), "kind": "mac", **st.get('mac', {"packages": [], "checked": None})}]
    targets += [{"id": tid, "name": tid[3:], "kind": "machine", **v} for tid, v in sorted(st.items()) if tid.startswith('vm:')]
    try:
        targets += _hosts()
    except Exception as e:
        log.warning(f"updates of hosts: {e}")
    return targets


# ---- applying --------------------------------------------------------------------------------
def _apply(j, tid, packages):
    try:
        if tid == 'mac':
            r = subprocess.run([BREW, 'upgrade', *packages], capture_output=True, text=True, timeout=3600,
                               env={**__import__('os').environ, 'HOMEBREW_NO_INSTALL_CLEANUP': '1'})
        elif tid.startswith('vm:'):
            r = subprocess.run(['orb', '-m', tid[3:], '-u', 'root', 'sh', '-c', _UPGRADE_SH, 'sh', *packages],
                               capture_output=True, text=True, timeout=3600)
        else:
            raise RuntimeError('unknown target')
        j["output"] = ((r.stdout or '') + (r.stderr or ''))[-6000:]
        j["state"] = 'done' if r.returncode == 0 else 'failed'
        if r.returncode != 0:
            j["error"] = (r.stderr or r.stdout).strip().splitlines()[-1][:300] if (r.stderr or r.stdout).strip() else f"exit {r.returncode}"
    except Exception as e:
        j.update(state='failed', error=str(e))
    j["finished"] = int(time.time())
    check(only=tid)


@updates_bp.route('', methods=['GET'])
def list_updates():
    with _lock:
        jobs = [dict(j) for j in _jobs.values() if j['state'] == 'running' or time.time() - j.get('finished', 0) < 600]
    return jsonify({"status": "success", "data": {"targets": overview(), "jobs": jobs, "checking": _checking.is_set()}})


@updates_bp.route('/check', methods=['POST'])
def check_now():
    check((request.get_json(silent=True) or {}).get('target'))
    return jsonify({"status": "success"})


@updates_bp.route('/<path:tid>/apply', methods=['POST'])
def apply(tid):
    body = request.get_json(silent=True) or {}
    packages = [p for p in (body.get('packages') or []) if isinstance(p, str) and re.fullmatch(r'[A-Za-z0-9@._+:/-]+', p)]
    if tid.startswith('host:'):
        from app.api.hosts import queue_action
        return queue_action(tid[5:], {"verb": "upgrade"})
    if tid != 'mac' and not tid.startswith('vm:'):
        return jsonify({"status": "error", "message": "Unknown computer"}), 404
    with _lock:
        if any(j['target'] == tid and j['state'] == 'running' for j in _jobs.values()):
            return jsonify({"status": "error", "message": "Already updating"}), 409
        j = {"id": uuid.uuid4().hex[:10], "target": tid, "packages": packages, "state": "running", "started": int(time.time())}
        _jobs[j['id']] = j
    threading.Thread(target=_apply, args=(j, tid, packages), daemon=True).start()
    return jsonify({"status": "success", "data": j})
