"""Other hosts in the cluster: computers besides Arrakis that report to this dashboard.

Each host runs a small shell agent (macOS or Linux, no dependencies beyond sh and
curl) that POSTs a snapshot to /api/hosts/report every 5 s over Tailscale. Adding a
host mints a token; the one-line install command fetches install.sh with that token,
which writes the agent and registers it with launchd, systemd or cron.

Hosts are kept in $HOMELAB_HOME/secrets/hosts.json (0600). Reports and the last hour of
history live in memory, like the machines' samples.

Actions (restart a service or container, reboot, update the agent) are queued here
and handed to the agent in the reply to its next report, so they need no inbound
port on the host: the agent runs only the verbs it knows, on a name it validates,
and posts the result back. Arrakis also checks each host's open ports itself every
30 s (a real DNS query, an HTTP request, an SSH banner…), stored in metrics.db.

Every 60 s (agent 5) the agent also POSTs an inventory to /api/hosts/inventory: its
drives (a Mac's diskutil plists, built by storage.build_disks exactly like Arrakis's;
a Linux host's lsblk) and, where OrbStack is installed, its machines. Those back the
host's Storage and Machines tabs, and the vm-*/disk-eject/volume-mount actions.

Agent 6 also keeps a command channel open (a long poll on /api/hosts/rpc) through which
Arrakis runs `orb` on that host: the whole machine API (app/api/vms.py) then works for
its OrbStack too, at /api/hosts/<id>/vms. That is full control of the host's machines,
and through them of the host, so it only runs for hosts whose owner switched on
"Manage OrbStack from the dashboard" (orb_manage in $HOMELAB_HOME/secrets/hosts.json). The agent
only ever runs `orb`, never anything else.
"""
from flask import Blueprint, jsonify, request, Response
import base64
import json
import os
import plistlib
import re
import secrets
import socket
import ssl
import struct
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from app.core.logger import log
from app.core import paths
from app.core import server_cfg

hosts_bp = Blueprint('hosts', __name__)

STORE = paths.secret('hosts')
NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._-]{0,40}$')
REPORT_EVERY = 5
ONLINE_WITHIN = 20          # seconds since the last report
HISTORY_KEEP = 720          # one hour of 5 s reports
PORT = int(os.environ.get('PORT') or server_cfg.port())

_lock = threading.Lock()
_latest = {}                # host id -> parsed report
_history = {}               # host id -> deque of {t, cpu, mem, memTotal}
_last_disk = {}             # host id -> when its disk was last stored
DISK_EVERY = 300


# ---- store ---------------------------------------------------------------------------

def _load():
    try:
        with open(STORE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(hosts):
    tmp = STORE + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(hosts, f, indent=2)
    os.replace(tmp, STORE)


def _by_token(token):
    if not token:
        return None
    return next((h for h in _load() if secrets.compare_digest(h['token'], token)), None)


_server_url = None


def _server():
    """Where agents send reports: Arrakis's Tailscale address, which every host can reach."""
    global _server_url
    if not _server_url:
        ip = ''
        for cmd in (['tailscale', 'ip', '-4'], ['/Applications/Tailscale.app/Contents/MacOS/Tailscale', 'ip', '-4']):
            try:
                ip = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.split()[0]
                break
            except (OSError, IndexError, subprocess.SubprocessError):
                continue
        if not ip:
            return request.host_url.rstrip('/')
        _server_url = f'http://{ip}:{PORT}'
    return _server_url


def _command(h):
    return f"curl -fsSL '{_server()}/api/hosts/install.sh?t={h['token']}' | sh"


# ---- reports -------------------------------------------------------------------------

def _num(v, cast=float):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def _mib(s):
    """'11.4MiB' / '1.2GiB' / '512kB' -> MiB"""
    m = re.match(r'([0-9.]+)\s*([KMGT]?i?B)', s.strip(), re.I)
    if not m:
        return None
    v, u = float(m.group(1)), m.group(2).upper()
    return round(v * {'B': 1 / 2**20, 'KB': 1 / 1024, 'KIB': 1 / 1024, 'MB': 1, 'MIB': 1, 'GB': 1024, 'GIB': 1024, 'TB': 2**20, 'TIB': 2**20}.get(u, 1), 1)


def _parse(text):
    head, sep, work = text.partition('#workloads\n')
    kv, section, docker, dstats, svcuse = {}, None, None, {}, {}
    workloads, apps, macps = None, None, None
    if sep:
        from app.api.vms import _parse_workloads
        # dstats is ours; the rest is the same format the machines' scan produces
        plain = []
        for line in work.splitlines():
            if line.startswith('#'):
                section = line[1:].strip()
            if section == 'dstats' and not line.startswith('#'):
                p = (line.split('\t') + [''] * 3)[:3]
                dstats[p[0]] = {"cpu": _num(p[1].rstrip('%')), "mem_mb": _mib(p[2].split('/')[0])}
            elif section == 'svcuse' and not line.startswith('#'):
                p = (line.split('\t') + [''] * 3)[:3]
                b = _num(p[1], int)
                svcuse[p[0].removesuffix('.service')] = {"mem_mb": round(b / 2**20, 1) if b is not None else None, "cpu": _num(p[2])}
            elif section == 'macapps':
                if not line.startswith('#') and line.strip():
                    macps = (macps or []) + [line]
                elif line.startswith('#'):
                    macps = macps or []
            elif section not in ('dstats', 'svcuse'):
                plain.append(line)
        workloads = _parse_workloads('\n'.join(plain))
        # each service's memory and CPU (% of one core), where the agent measured them
        for u in workloads["services"]:
            u.update(svcuse.get(u["unit"].removesuffix('.service'), {}))
        docker = workloads["docker"]
        if macps is not None:
            apps = _mac_apps(macps, workloads["listening"])
        section = None
    for line in head.splitlines():
        if line.startswith('#'):
            section = line[1:].strip()
            continue
        if not line.strip():
            continue
        if section == 'docker':
            # agent 1: containers without the workloads section
            if docker is None:
                docker = []
            p = (line.split('\t') + [''] * 4)[:4]
            docker.append({"name": p[0], "image": p[1], "state": p[2], "status": p[3]})
        elif section == 'dstats':
            p = (line.split('\t') + [''] * 3)[:3]
            dstats[p[0]] = {"cpu": _num(p[1].rstrip('%')), "mem_mb": _mib(p[2].split('/')[0])}
        else:
            k, sep, v = line.partition(':')
            if sep:
                kv[k.strip()] = v.strip()

    from app.api.system import _parse_docker_uptime
    containers = None
    if docker is not None:
        containers = []
        for c in docker:
            running = c["state"] == "running"
            s = dstats.get(c["name"], {})
            containers.append({
                "id": c["name"], "name": c["name"], "image": c["image"],
                "status": "running" if running else "stopped",
                "uptime_seconds": _parse_docker_uptime(c["status"]) if running else 0,
                "cpu": s.get("cpu") or 0, "mem_mb": s.get("mem_mb"),
            })

    return {
        "hostname": kv.get('hostname'),
        "os": kv.get('os'),
        "kernel": kv.get('kernel'),
        "arch": kv.get('arch'),
        "model": kv.get('model'),
        "cores": _num(kv.get('cores'), int),
        "cpu_pct": _num(kv.get('cpu_pct')),
        "mem_total": _num(kv.get('mem_total'), int),
        "mem_used": _num(kv.get('mem_used'), int),
        "disk_total": _num(kv.get('disk_total_kb'), int) and _num(kv.get('disk_total_kb'), int) * 1024,
        "disk_used": _num(kv.get('disk_used_kb'), int) and _num(kv.get('disk_used_kb'), int) * 1024,
        "uptime_secs": _num(kv.get('uptime_secs'), int),
        "ip": kv.get('ip'),
        "agent": kv.get('agent'),
        "root": kv.get('root') == '1' if 'root' in kv else None,
        "fda": kv.get('fda') == '1' if 'fda' in kv else None,
        "containers": containers,
        "workloads": workloads,
        "apps": apps,
    }


# processes that are macOS itself, not an app someone runs
_MAC_SYSTEM = ('/System/', '/usr/', '/sbin/', '/bin/', '/Library/Apple/', '/private/var/', '/Library/Developer/CommandLineTools/')


def _etime(s):
    """ps etime "[[dd-]hh:]mm:ss" -> seconds"""
    days, _, rest = s.rpartition('-')
    parts = [int(x) for x in rest.split(':') if x.isdigit()]
    while len(parts) < 3:
        parts.insert(0, 0)
    return (int(days) if days.isdigit() else 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def _mac_apps(lines, listening):
    """ps lines (pid pcpu rss etime path) into one entry per app: an .app bundle with all its
    helpers, or a program listening on a port. CPU is % of one core, as for Arrakis's apps."""
    ports = {}
    for l in listening or []:
        if l.get('pid'):
            ports.setdefault(l['pid'], set()).add(l['port'])
    apps = {}
    for line in lines:
        p = line.split(None, 4)
        if len(p) < 5 or not p[0].isdigit():
            continue
        pid, path = int(p[0]), p[4].strip()
        if path.startswith(_MAC_SYSTEM):
            continue
        m = re.search(r'/([^/]+)\.app(/|$)', path)    # the outermost bundle: helpers fold into their app
        name = m.group(1) if m else os.path.basename(path)
        a = apps.setdefault(name, {"id": name, "name": name, "type": 'app' if m else 'daemon', "status": 'running',
                                   "cpu": 0.0, "mem_mb": 0.0, "ports": set(), "processes": 0, "uptime_seconds": 0})
        a["cpu"] += _num(p[1]) or 0
        a["mem_mb"] += (_num(p[2], int) or 0) / 1024
        a["ports"] |= ports.get(pid, set())
        a["processes"] += 1
        a["uptime_seconds"] = max(a["uptime_seconds"], _etime(p[3]))
    out = []
    for a in apps.values():
        a.update(cpu=round(a["cpu"], 1), mem_mb=round(a["mem_mb"], 1), ports=sorted(a["ports"]))
        out.append(a)
    return sorted(out, key=lambda a: -a["mem_mb"])


def _public(h):
    with _lock:
        r = _latest.get(h['id'])
    seen = r and r['at']
    out = {k: h[k] for k in ('id', 'name', 'added')}
    out["orb_manage"] = bool(h.get('orb_manage'))
    out["rpc"] = _rpc_connected(h['id'])
    out["online"] = bool(seen and time.time() - seen < ONLINE_WITHIN)
    out["last_seen"] = seen or None
    out["report"] = r
    out["agent_latest"] = AGENT_VERSION
    disks, vms = _disks_of(h['id']), _machines_of(h['id'])
    out["caps"] = {
        "storage": len(disks) if disks is not None else None,
        "orbstack": vms["orbstack"] if vms else None,
        "machines": len(vms["machines"]) if vms else None,
    }
    return out


@hosts_bp.route('/report', methods=['POST'])
def report():
    auth = request.headers.get('Authorization', '')
    h = _by_token(auth.removeprefix('Bearer ').strip())
    if not h:
        return jsonify({"status": "error", "message": "unknown token"}), 401
    try:
        r = _parse(request.get_data(as_text=True)[:200_000])
    except Exception as e:  # noqa: BLE001
        log.warning(f"host report {h['name']}: {e}")
        return jsonify({"status": "error", "message": "bad report"}), 400
    r["at"] = time.time()
    with _lock:
        prev = _latest.get(h['id'])
        # containers come every few reports; keep the last list between them
        if r["workloads"] is None and prev:
            r["workloads"] = prev.get("workloads")
            r["apps"] = prev.get("apps")
            if r["containers"] is None:
                r["containers"] = prev.get("containers")
        _latest[h['id']] = r
        _history.setdefault(h['id'], deque(maxlen=HISTORY_KEEP)).append(
            {"t": r["at"], "cpu": r["cpu_pct"], "mem": r["mem_used"], "memTotal": r["mem_total"]})
    # also into metrics.db (memory in GB, like Arrakis's rows), so history outlives a restart
    if r["cpu_pct"] is not None:
        try:
            from app.core.db import insert_metrics
            insert_metrics(h['id'], r["cpu_pct"], (r["mem_used"] or 0) / 2 ** 30)
        except Exception as e:  # noqa: BLE001
            log.warning(f"host metrics {h['name']}: {e}")
    if r["disk_total"] and time.time() - _last_disk.get(h['id'], 0) >= DISK_EVERY:
        _last_disk[h['id']] = time.time()
        try:
            from app.core.db import insert_disk_metric
            insert_disk_metric(h['id'], r["disk_used"], r["disk_total"])
        except Exception as e:  # noqa: BLE001
            log.warning(f"host disk {h['name']}: {e}")
    _start_checker()
    # plain text so a shell agent can read it: one "do <id> <verb> <target>" line per queued action
    lines = ['ok'] + [f"do {a['id']} {a['verb']} {a['target'] or '-'}" for a in _take_actions(h['id'])]
    return Response('\n'.join(lines) + '\n', mimetype='text/plain')


# ---- actions -------------------------------------------------------------------------

VERBS = {
    'service-start', 'service-stop', 'service-restart',
    'container-start', 'container-stop', 'container-restart',
    'vm-start', 'vm-stop', 'vm-restart', 'disk-eject', 'volume-mount',
    'reboot', 'update-agent', 'backup-folders', 'backup-sizes', 'backup',
}
VERB_FROM = {**{v: 5 for v in ('vm-start', 'vm-stop', 'vm-restart', 'disk-eject', 'volume-mount')},
             'backup-folders': 8, 'backup': 9, 'backup-sizes': 13}
NO_TARGET = {'reboot', 'update-agent', 'backup-folders', 'backup-sizes'}
AGENT_VERSION = 14          # what install.sh hands out now; bump with every change to AGENT_SH
BACKUP_FROM = 9             # first agent version that sends folders for the nightly backup (8 had a bug)
BACKUP_TTL = 3 * 3600       # a big folder can take a while to pack and send
TARGET_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9@._:_-]{0,127}$')
ACTIONS_FROM = 4            # first agent version that runs actions
QUEUE_TTL = 60              # an action the agent hasn't picked up by then is dropped
RESULT_TTL = 600            # one it took but never answered is marked unknown
_actions = {}               # host id -> [action], newest last
_action_seq = 0


def _agent_version(r):
    return _num((r or {}).get('agent'), int) or 0


def _expire(acts):
    now = time.time()
    for a in acts:
        if a['state'] == 'queued' and now - a['at'] > QUEUE_TTL:
            a.update(state='expired', output='The agent did not pick it up within a minute.')
        elif a['state'] == 'sent' and now - a['sent'] > (BACKUP_TTL if a['verb'] == 'backup' else RESULT_TTL):
            a.update(state='unknown', output='The agent took it but never reported back.')


def _take_actions(hid):
    with _lock:
        acts = _actions.get(hid, [])
        _expire(acts)
        out = [a for a in acts if a['state'] == 'queued']
        for a in out:
            a.update(state='sent', sent=time.time())
    return out


@hosts_bp.route('/result', methods=['POST'])
def action_result():
    """From the agent: "id: N", "rc: 0", a blank line, then the command's output."""
    auth = request.headers.get('Authorization', '')
    h = _by_token(auth.removeprefix('Bearer ').strip())
    if not h:
        return jsonify({"status": "error", "message": "unknown token"}), 401
    head, _, body = request.get_data(as_text=True)[:8000].partition('\n\n')
    kv = dict(l.split(':', 1) for l in head.splitlines() if ':' in l)
    aid, rc = _num(kv.get('id', '').strip(), int), _num(kv.get('rc', '').strip(), int)
    with _lock:
        a = next((a for a in _actions.get(h['id'], []) if a['id'] == aid), None)
        if a:
            a.update(state='done' if rc == 0 else 'failed', done=time.time(), output=body.strip()[:4000])
    if a:
        log.info(f"host {h['name']}: {a['verb']} {a['target'] or ''} -> rc {rc}")
    return jsonify({"status": "success"})


@hosts_bp.route('/<hid>/actions', methods=['GET'])
def list_actions(hid):
    with _lock:
        acts = _actions.get(hid, [])
        _expire(acts)
        return jsonify({"status": "success", "data": [dict(a) for a in acts[-20:]][::-1]})


def agent_version(hid):
    with _lock:
        return _agent_version(_latest.get(hid))


def action(hid, aid):
    with _lock:
        _expire(_actions.get(hid, []))
        a = next((a for a in _actions.get(hid, []) if a['id'] == aid), None)
        return dict(a) if a else None


@hosts_bp.route('/<hid>/actions', methods=['POST'])
def queue_action(hid, body=None):
    global _action_seq
    h = _find(hid)
    if not h:
        return jsonify({"status": "error", "message": "no such host"}), 404
    body = body if body is not None else (request.get_json(silent=True) or {})
    verb, target = body.get('verb', ''), (body.get('target') or '').strip()
    if verb not in VERBS:
        return jsonify({"status": "error", "message": f"Unknown action {verb!r}"}), 400
    if verb in NO_TARGET:
        target = ''
    elif not TARGET_RE.match(target):
        return jsonify({"status": "error", "message": "That isn't a valid service or container name"}), 400
    if verb.startswith('service-') and target.removesuffix('.service') == 'arrakis-agent':
        return jsonify({"status": "error", "message": "Use Update agent to restart the agent itself"}), 400
    refused = _refuse(hid, verb, target)
    if refused:
        return jsonify({"status": "error", "message": refused}), 400
    with _lock:
        r = _latest.get(hid)
        if _agent_version(r) < VERB_FROM.get(verb, ACTIONS_FROM):
            return jsonify({"status": "error", "message": f"{h['name']}'s agent is too old for that: use Update agent from the ⋯ menu, or run the install command again from Settings"}), 409
        _action_seq += 1
        a = {"id": _action_seq, "verb": verb, "target": target, "state": "queued", "at": time.time(), "sent": None, "done": None, "output": ""}
        acts = _actions.setdefault(hid, [])
        acts.append(a)
        del acts[:-50]
    log.info(f"host {h['name']}: queued {verb} {target}")
    return jsonify({"status": "success", "data": dict(a)})


def _refuse(hid, verb, target):
    """Why a drive or machine action can't go ahead, judged on the host's last inventory."""
    if verb.startswith('vm-'):
        vms = _machines_of(hid)
        if not vms or not any(m["name"] == target for m in vms["machines"]):
            return f"No OrbStack machine called {target} on this host"
    elif verb == 'disk-eject':
        d = next((d for d in _disks_of(hid) or [] if d["id"] == target), None)
        if not d:
            return "No such drive"
        if d["internal"] or d["system"] or not d["ejectable"]:
            return "Only external drives can be ejected"
    elif verb == 'volume-mount':
        if not any(v["id"] == target for d in _disks_of(hid) or [] for v in d["volumes"]):
            return "No such volume"
    return None


# ---- backups: a host's folders go into Arrakis's nightly snapshot (agent 8) -----------
# The folders are chosen on the dashboard (Backups → What's covered); the agent asks for
# them when it gets a "backup <timestamp>" action, packs them and uploads the archive.
# An upload is only taken while that host has that backup action outstanding.

def _agent_host():
    return _by_token(request.headers.get('Authorization', '').removeprefix('Bearer ').strip())


@hosts_bp.route('/backup-plan', methods=['GET'])
def backup_plan():
    h = _agent_host()
    if not h:
        return Response("unknown token\n", status=401, mimetype='text/plain')
    from app.core import backup_cfg
    plan = next((x for x in backup_cfg.load()["hosts"] if x["id"] == h['id']), None)
    return Response(''.join(f + '\n' for f in (plan or {}).get("folders", [])), mimetype='text/plain')


@hosts_bp.route('/backup/<ts>', methods=['PUT'])
def backup_upload(ts):
    h = _agent_host()
    if not h:
        return Response("unknown token\n", status=401, mimetype='text/plain')
    with _lock:
        waiting = any(a['verb'] == 'backup' and a['target'] == ts and a['state'] == 'sent' for a in _actions.get(h['id'], []))
    if not waiting or not re.fullmatch(r'\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d', ts):
        return Response("no backup is waiting for this\n", status=409, mimetype='text/plain')
    from app.core import backup_cfg
    out = os.path.join(backup_cfg.dest(), f"{backup_cfg.HOST}{h['id']}_{ts}.tar.gz")
    tmp = out + '.part'
    n = 0
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        while chunk := request.stream.read(1 << 20):
            f.write(chunk)
            n += len(chunk)
    os.replace(tmp, out)
    log.info(f"backup from {h['name']}: {n} bytes")
    return Response(f"stored {n} bytes\n", mimetype='text/plain')


# ---- inventory: drives and OrbStack machines, every 60 s (agent 5) ------------------

_inventory = {}             # host id -> {"at", "sections": {header: text}, "built": {}}


def _sections(text):
    """'#@<name>' header lines, each followed by that command's output."""
    out, name, buf = {}, None, []
    for line in text.split('\n'):
        if line.startswith('#@'):
            if name is not None:
                out[name] = '\n'.join(buf)
            name, buf = line[2:].strip(), []
        elif name is not None:
            buf.append(line)
    if name is not None:
        out[name] = '\n'.join(buf)
    return out


@hosts_bp.route('/inventory', methods=['POST'])
def inventory():
    auth = request.headers.get('Authorization', '')
    h = _by_token(auth.removeprefix('Bearer ').strip())
    if not h:
        return jsonify({"status": "error", "message": "unknown token"}), 401
    sections = _sections(request.get_data(as_text=True)[:2_000_000])
    with _lock:
        _inventory[h['id']] = {"at": time.time(), "sections": sections, "built": {}}
    return Response('ok\n', mimetype='text/plain')


def _built(hid, key, build):
    """The inventory's derived view, built once per inventory."""
    with _lock:
        inv = _inventory.get(hid)
    if not inv:
        return None
    if key not in inv["built"]:
        try:
            inv["built"][key] = build(inv["sections"], inv["at"])
        except Exception as e:  # noqa: BLE001
            log.warning(f"host {hid} {key}: {e}")
            inv["built"][key] = None
    return inv["built"][key]


_HW_FILE = paths.state('hardware')


def _hw_saved():
    try:
        with open(_HW_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def hardware_of(hid):
    """Temperatures, drive health and UPS from a host's last inventory (agent 14+ for Linux sensors).
    The last reading is kept on disk too, so a dashboard restart doesn't blank it until the
    host's next inventory (once a minute)."""
    from app.services.hardware import from_inventory
    def build(sections, at):
        hw = {**from_inventory(sections), "at": int(at)}
        try:
            saved = _hw_saved()
            saved[hid] = hw
            tmp = _HW_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(saved, f)
            os.replace(tmp, _HW_FILE)
        except OSError as e:
            log.warning(f"saving hardware of {hid}: {e}")
        return hw
    return _built(hid, "hardware", build) or _hw_saved().get(hid)


def _disks_of(hid):
    return _built(hid, "disks", _build_disks)


def _machines_of(hid):
    return _built(hid, "machines", _build_machines)


def _build_disks(s, _at):
    if 'diskutil list -plist' in s:
        from app.api.storage import build_disks

        def plist(args):
            text = s.get('diskutil ' + ' '.join(args))
            if not text:
                raise RuntimeError('not in the report: diskutil ' + ' '.join(args))
            return plistlib.loads(text.encode())
        # a Mac's system volume is mounted at / and its data at /System/Volumes/Data
        return build_disks(plist, lambda mp: mp in ('/', '/System/Volumes/Data'))
    if 'lsblk' in s:
        return _linux_disks(s['lsblk'], s.get('df', ''))
    return None


def _flag(v):
    return v in (True, 1, '1')


def _linux_disks(lsblk, df_text):
    """lsblk -J -b into the shape of /api/storage/disks."""
    from app.api.storage import protected_set
    devs = json.loads(lsblk or '{}').get('blockdevices', [])
    df = {}
    for line in df_text.splitlines()[1:]:
        p = line.split()
        if len(p) >= 6 and p[1].isdigit() and p[2].isdigit() and p[3].isdigit():
            df[p[5]] = (int(p[2]) * 1024, int(p[3]) * 1024)

    def flat(d):
        for c in d.get('children') or []:
            yield c
            yield from flat(c)

    protected = protected_set()
    disks = []
    for d in devs:
        name = d.get('name') or ''
        if d.get('type') != 'disk' or re.match(r'(zram|ram|loop)', name):
            continue
        vols = []
        for p in [d, *flat(d)]:
            fs = p.get('fstype')
            if not fs or fs in ('swap', 'LVM2_member', 'crypto_LUKS', 'zfs_member', 'linux_raid_member'):
                continue
            mp = p.get('mountpoint')
            used, free = _num(p.get('fsused'), int), _num(p.get('fsavail'), int)
            if mp in df and (used is None or free is None):
                used, free = df[mp]
            vols.append({
                "id": p.get('name'),
                "name": p.get('label') or ('System' if mp == '/' else os.path.basename(mp) if mp else p.get('name')),
                "format": fs, "size": _num(p.get('size'), int),
                "mounted": bool(mp), "mount_point": mp or None, "writable": not _flag(p.get('ro')),
                "used": used if mp else None, "free": free if mp else None, "role": None,
            })
        # the volume a person thinks of as the drive first: /, then the biggest mounted one
        vols.sort(key=lambda v: (not v["mounted"], v["mount_point"] != '/', -(v["size"] or 0)))
        tran = (d.get('tran') or '').lower()
        mmc = name.startswith('mmcblk')
        removable = _flag(d.get('rm')) or _flag(d.get('hotplug')) or tran == 'usb'
        model = ' '.join(x for x in ((d.get('vendor') or '').strip(), (d.get('model') or '').strip()) if x) or ('SD card' if mmc else name)
        system = any(v["mount_point"] == '/' for v in vols)
        fp = f"{model}|{_num(d.get('size'), int)}"
        disks.append({
            "id": name, "name": model, "size": _num(d.get('size'), int),
            "internal": system or not removable,
            "protocol": 'SD card' if mmc else tran.upper(),
            "ssd": d.get('rota') in (False, 0, '0'),
            "removable": removable, "ejectable": False, "smart": 'Not Supported', "image": False,
            "system": system, "protected": fp in protected, "fingerprint": fp, "volumes": vols,
        })
    disks.sort(key=lambda d: (not d["internal"], d["id"]))
    return disks


def _build_machines(s, at):
    if 'orb stopped' in s:
        return {"orbstack": "stopped", "machines": [], "pool": None, "at": at}
    if 'orb list' not in s:
        return None
    from app.api.vms import _kv, _int
    cfg = _kv(s.get('orb config', ''))
    machines = []
    for m in json.loads(s['orb list'] or '[]'):
        name = m.get('name')
        machines.append({
            "name": name, "state": m.get('state'), "image": m.get('image', {}),
            "username": (m.get('config') or {}).get('default_username'),
            # 0 = no limit of its own; it shares the pool
            "cpu": _int(cfg.get(f'machine.{name}.cpu')),
            "memory_mib": _int(cfg.get(f'machine.{name}.memory_mib')),
        })
    return {"orbstack": "running", "machines": machines,
            "pool": {"cpu": _int(cfg.get('cpu')), "memory_mib": _int(cfg.get('memory_mib'))}, "at": at}


@hosts_bp.route('/<hid>/storage', methods=['GET'])
def host_storage(hid):
    disks = _disks_of(hid)
    if disks is None:
        return jsonify({"status": "error", "message": "No drives reported yet (agent 5 sends them every minute)"}), 404
    with _lock:
        at = _inventory[hid]["at"]
    return jsonify({"status": "success", "data": disks, "at": at})


@hosts_bp.route('/<hid>/machines', methods=['GET'])
def host_machines(hid):
    vms = _machines_of(hid)
    if vms is None:
        return jsonify({"status": "error", "message": "No OrbStack on this host (or agent 5 hasn't reported yet)"}), 404
    return jsonify({"status": "success", "data": vms})


# ---- command channel: Arrakis runs `orb` on a host (agent 6) ------------------------

RPC_FROM = 6
RPC_POLL = 25               # seconds a poll waits for a command before returning empty
_rpc_cv = threading.Condition()
_rpc_queue = {}             # host id -> deque of commands waiting for its agent
_rpc_jobs = {}              # command id -> command (until answered or given up)
_rpc_seen = {}              # host id -> when its agent last polled
_rpc_waiting = set()        # host ids with a poll open right now
_rpc_gen = {}               # host id -> number of its newest poll; older polls give up
_rpc_seq = 0


class HostUnavailable(RuntimeError):
    pass


def _rpc_connected(hid):
    return hid in _rpc_waiting or time.time() - _rpc_seen.get(hid, 0) < RPC_POLL + 20


def host_report(hid):
    with _lock:
        return _latest.get(hid)


def managed_hosts():
    """Hosts whose OrbStack the dashboard manages: switched on and with the channel up."""
    return [h['id'] for h in _load() if h.get('orb_manage') and _rpc_connected(h['id'])]


def rpc(hid, args, stdin='', timeout=30):
    """Run `orb <args>` on host hid through its agent -> (returncode, stdout, stderr)."""
    global _rpc_seq
    h = _find(hid)
    if not h:
        raise HostUnavailable(f"No host called {hid}")
    if not h.get('orb_manage'):
        raise HostUnavailable(f"Managing OrbStack on {h['name']} is switched off (its Settings tab)")
    if not _rpc_connected(hid):
        raise HostUnavailable(f"{h['name']} isn't connected: it may be asleep or offline, or its agent is older than version {RPC_FROM}")
    with _rpc_cv:
        _rpc_seq += 1
        job = {"id": _rpc_seq, "hid": hid, "args": [str(a) for a in args], "stdin": stdin or '',
               "done": threading.Event(), "result": None}
        _rpc_jobs[job["id"]] = job
        _rpc_queue.setdefault(hid, deque()).append(job)
        _rpc_cv.notify_all()
    if not job["done"].wait(timeout + 10):
        with _rpc_cv:
            _rpc_jobs.pop(job["id"], None)
            q = _rpc_queue.get(hid)
            if q and job in q:
                q.remove(job)
        raise HostUnavailable(f"{h['name']} didn't answer within {timeout} s")
    return job["result"]


def _b64(text):
    return base64.b64encode(text.encode()).decode()


@hosts_bp.route('/rpc', methods=['GET'])
def rpc_poll():
    """From the agent: wait for the next command. Reply: id, stdin, then one argument per
    line, each base64 (empty reply = nothing to do)."""
    auth = request.headers.get('Authorization', '')
    h = _by_token(auth.removeprefix('Bearer ').strip())
    if not h:
        return jsonify({"status": "error", "message": "unknown token"}), 401
    hid, deadline = h['id'], time.time() + RPC_POLL
    with _rpc_cv:
        # The newest poll is the agent's live connection. An older one may belong to a
        # connection that died (the agent was replaced or the network dropped) and must not
        # take a command it can no longer deliver.
        mine = _rpc_gen[hid] = _rpc_gen.get(hid, 0) + 1
        _rpc_cv.notify_all()
        _rpc_waiting.add(hid)
        try:
            while True:
                if _rpc_gen.get(hid) != mine:
                    job = None
                    break
                q = _rpc_queue.get(hid)
                if q:
                    job = q.popleft()
                    break
                left = deadline - time.time()
                if left <= 0:
                    job = None
                    break
                _rpc_cv.wait(left)
        finally:
            if _rpc_gen.get(hid) == mine:
                _rpc_waiting.discard(hid)
            _rpc_seen[hid] = time.time()
    if not job:
        return Response('', mimetype='text/plain')
    lines = [str(job["id"]), _b64(job["stdin"]), *[_b64(a) for a in job["args"]]]
    return Response('\n'.join(lines) + '\n', mimetype='text/plain')


@hosts_bp.route('/rpc/<int:jid>', methods=['POST'])
def rpc_answer(jid):
    """From the agent: exit code, then stdout and stderr as base64, one line each."""
    auth = request.headers.get('Authorization', '')
    h = _by_token(auth.removeprefix('Bearer ').strip())
    if not h:
        return jsonify({"status": "error", "message": "unknown token"}), 401
    lines = (request.get_data(as_text=True)[:64_000_000].split('\n') + ['', '', ''])[:3]
    dec = lambda b: base64.b64decode(b.strip() or b'').decode(errors='replace')
    with _rpc_cv:
        job = _rpc_jobs.get(jid)
        if not job or job["hid"] != h['id']:
            return jsonify({"status": "error", "message": "no such command"}), 404
        _rpc_jobs.pop(jid, None)
    try:
        job["result"] = (_num(lines[0].strip(), int) if lines[0].strip() else 1, dec(lines[1]), dec(lines[2]))
    except ValueError:
        job["result"] = (1, '', 'the agent sent a garbled answer')
    job["done"].set()
    return Response('ok\n', mimetype='text/plain')


@hosts_bp.route('/<hid>', methods=['PATCH'])
def update_host(hid):
    """{"orb_manage": bool}: let the dashboard manage this host's OrbStack, or stop it."""
    body = request.get_json(silent=True) or {}
    if 'orb_manage' not in body:
        return jsonify({"status": "error", "message": "Nothing to change"}), 400
    with _lock:
        hosts = _load()
        h = next((x for x in hosts if x['id'] == hid), None)
        if not h:
            return jsonify({"status": "error", "message": "no such host"}), 404
        h['orb_manage'] = bool(body['orb_manage'])
        _save(hosts)
    log.info(f"host {h['name']}: manage OrbStack {'on' if h['orb_manage'] else 'off'}")
    return jsonify({"status": "success", "data": _public(h)})


# ---- checks: Arrakis tries each host's open ports ------------------------------------

CHECK_EVERY = 30
CHECK_STORE_EVERY = 60
CHECK_TIMEOUT = 3
TLS_PORTS = {443, 8443, 9443}
SKIP_PROCS = {'tailscaled'}
WILDCARD = {'0.0.0.0', '::', '*', '[::]'}
_checks = {}                # host id -> {port: result}
_checker = None


def _targets(r):
    """The ports worth checking from outside: TCP (plus DNS over UDP), reachable from the
    network on the address Arrakis would use, not ephemeral, not Tailscale's own."""
    ip, w = r.get('ip'), r.get('workloads') or {}
    out = {}
    for l in w.get('listening') or []:
        port, proc = l.get('port'), l.get('process') or ''
        if l.get('local_only') or proc in SKIP_PROCS or not port or port >= 32768:
            continue
        if not (WILDCARD & set(l.get('addresses') or []) or ip in (l.get('addresses') or [])):
            continue
        if l.get('proto') == 'udp' and port != 53:
            continue
        out.setdefault(port, proc)
    return ip, out


def _dns(ip, port):
    t0 = time.monotonic()
    qid = secrets.randbits(16)
    q = struct.pack('>HHHHHH', qid, 0x0100, 1, 0, 0, 0) + b'\x07example\x03com\x00' + struct.pack('>HH', 1, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(CHECK_TIMEOUT)
        s.sendto(q, (ip, port))
        data = s.recv(512)
    ms = (time.monotonic() - t0) * 1000
    rid, flags = struct.unpack('>HH', data[:4])
    rcode = flags & 0xF
    if rid != qid:
        return False, 'DNS reply did not match the query', ms
    if rcode == 2:
        return False, 'DNS answers SERVFAIL (its upstream may be down)', ms
    if rcode == 5:
        return True, f'DNS answers, but refuses queries from {server_cfg.name()}', ms
    return True, 'answers DNS', ms


def _tcp(ip, port):
    """Connect; name what answers: an SSH or VNC banner, an HTTP status, or just a connection.
    The time is the connection plus the answer, leaving out the wait for a banner that never comes."""
    t0 = time.monotonic()
    with socket.create_connection((ip, port), timeout=CHECK_TIMEOUT) as raw:
        s = raw
        if port in TLS_PORTS:
            ctx = ssl.create_default_context()
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
            s = ctx.wrap_socket(raw, server_hostname=ip)
        connected = (time.monotonic() - t0) * 1000
        s.settimeout(0.8)
        try:
            banner = s.recv(64)
        except (socket.timeout, TimeoutError):
            banner = b''
        if banner:
            ms = (time.monotonic() - t0) * 1000
            if banner.startswith(b'SSH-'):
                return True, 'SSH ' + banner.split(b'\r')[0].split(b'\n')[0][4:].decode(errors='replace'), ms
            return True, 'VNC server' if banner.startswith(b'RFB') else 'accepts connections', ms
        s.settimeout(CHECK_TIMEOUT)
        t1 = time.monotonic()
        try:
            s.sendall(f'HEAD / HTTP/1.0\r\nHost: {ip}\r\nUser-Agent: arrakis-check\r\n\r\n'.encode())
            head = s.recv(128)
        except OSError:
            head = b''
        if head.startswith(b'HTTP/'):
            ms = connected + (time.monotonic() - t1) * 1000
            code = _num(head.split()[1], int) if len(head.split()) > 1 else None
            return not (code and code >= 500), f'{"HTTPS" if s is not raw else "HTTP"} {code}', ms
        return True, 'accepts connections', connected


def _check(ip, port, proc):
    ms = None
    try:
        ok, detail, ms = (_dns if port == 53 else _tcp)(ip, port)
    except (OSError, ssl.SSLError, ValueError) as e:
        ok, detail = False, ('no answer in %d s' % CHECK_TIMEOUT if isinstance(e, (socket.timeout, TimeoutError))
                             else 'connection refused' if isinstance(e, ConnectionRefusedError)
                             else str(e) or type(e).__name__)
    return {"port": port, "process": proc, "kind": 'dns' if port == 53 else 'tcp', "ok": ok, "ms": round(ms, 1) if ok and ms is not None else None, "detail": detail, "at": time.time()}


def _check_loop():
    pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix='host-check')
    last_store = 0
    while True:
        try:
            store = time.time() - last_store >= CHECK_STORE_EVERY
            for h in _load():
                with _lock:
                    r = _latest.get(h['id'])
                if not r:
                    continue
                ip, ports = _targets(r)
                if not ip or not ports:
                    continue
                results = {x['port']: x for x in pool.map(lambda kv: _check(ip, *kv), ports.items())}
                with _lock:
                    _checks[h['id']] = results
                if store:
                    from app.core.db import insert_host_check
                    for x in results.values():
                        insert_host_check(h['id'], x['port'], x['ok'], x['ms'])
            if store:
                last_store = time.time()
        except Exception as e:  # noqa: BLE001
            log.warning(f"host checks: {e}")
        time.sleep(CHECK_EVERY)


def _start_checker():
    global _checker
    if _checker is None:
        with _lock:
            if _checker is None:
                _checker = threading.Thread(target=_check_loop, name='host-checks', daemon=True)
                _checker.start()


@hosts_bp.route('/<hid>/checks', methods=['GET'])
def host_checks(hid):
    """Latest result per port, plus ?hours=N (default 24) of pass/fail slots."""
    from app.core.db import get_host_checks_uptime
    hours = max(1.0, min(720.0, request.args.get('hours', default=24.0, type=float)))
    with _lock:
        latest = sorted(_checks.get(hid, {}).values(), key=lambda x: x['port'])
    return jsonify({"status": "success", "data": {"checks": latest, "every": CHECK_EVERY, **get_host_checks_uptime(hid, hours, 48)}})


@hosts_bp.route('/<hid>/presence', methods=['GET'])
def host_presence(hid):
    """When the host was reporting, in 48 slots over ?hours=N (default 24)."""
    from app.core.db import get_host_presence
    h = _find(hid)
    if not h:
        return jsonify({"status": "error", "message": "no such host"}), 404
    hours = max(1.0, min(720.0, request.args.get('hours', default=24.0, type=float)))
    return jsonify({"status": "success", "data": get_host_presence(hid, hours, 48, REPORT_EVERY, int(h['added']))})


@hosts_bp.route('/<hid>/disk', methods=['GET'])
def host_disk(hid):
    from app.core.db import get_disk_history
    hours = max(1.0, min(720.0, request.args.get('hours', default=24.0, type=float)))
    return jsonify({"status": "success", "data": get_disk_history(hid, hours)})


# ---- management ----------------------------------------------------------------------

_local_model = None


def _arrakis_model():
    """This Mac's model name ("Mac mini"), read once."""
    global _local_model
    if _local_model is None:
        try:
            out = subprocess.run(['system_profiler', 'SPHardwareDataType'], capture_output=True, text=True, timeout=15).stdout
            _local_model = next((l.split(':', 1)[1].strip() for l in out.splitlines() if 'Model Name' in l), '')
        except (OSError, subprocess.SubprocessError):
            _local_model = ''
    return _local_model


@hosts_bp.route('', methods=['GET'])
@hosts_bp.route('/', methods=['GET'])
def list_hosts():
    return jsonify({"status": "success", "data": {"hosts": [_public(h) for h in _load()], "server": _server(), "arrakis": {"model": _arrakis_model()}}})


@hosts_bp.route('', methods=['POST'])
@hosts_bp.route('/', methods=['POST'])
def add_host():
    name = ((request.get_json(silent=True) or {}).get('name') or '').strip()
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "Use letters, digits, spaces, dots, dashes or underscores (up to 41)."}), 400
    with _lock:
        hosts = _load()
        if name.lower() in ('arrakis', server_cfg.name().lower()) or any(h['name'].lower() == name.lower() for h in hosts):
            return jsonify({"status": "error", "message": f"A host called {name} already exists."}), 409
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'host'
        # ids share the #infra/<id> route with the tree's own nodes
        if slug in ('arrakis', 'hosts', 'new', 'orbstack', 'apps') or slug.startswith(('vm-', 'svc-')):
            slug = 'host-' + slug
        hid = slug
        n = 2
        while any(h['id'] == hid for h in hosts):
            hid, n = f'{slug}-{n}', n + 1
        h = {"id": hid, "name": name, "token": secrets.token_urlsafe(24), "added": time.time()}
        hosts.append(h)
        _save(hosts)
    return jsonify({"status": "success", "data": {**_public(h), "command": _command(h)}})


def _find(hid):
    return next((h for h in _load() if h['id'] == hid), None)


@hosts_bp.route('/<hid>', methods=['GET'])
def get_host(hid):
    h = _find(hid)
    if not h:
        return jsonify({"status": "error", "message": "no such host"}), 404
    return jsonify({"status": "success", "data": _public(h)})


@hosts_bp.route('/<hid>/install', methods=['GET'])
def install_command(hid):
    h = _find(hid)
    if not h:
        return jsonify({"status": "error", "message": "no such host"}), 404
    return jsonify({"status": "success", "data": {"command": _command(h), "uninstall": "sh ~/.arrakis-agent/uninstall.sh"}})


@hosts_bp.route('/<hid>/workloads', methods=['GET'])
def host_workloads(hid):
    """Containers, services and listening ports, in the machines' /workloads shape."""
    with _lock:
        r = _latest.get(hid)
    w = r and r.get("workloads")
    if not w:
        return jsonify({"status": "error", "message": "No workloads reported yet (agent 2 sends them every 30 s)"}), 404
    return jsonify({"status": "success", "data": w})


@hosts_bp.route('/<hid>/history', methods=['GET'])
def host_history(hid):
    """?hours=N (default 1). The last hour comes from memory at 5 s, with metrics.db filling
    in whatever came before a restart; longer spans are metrics.db's averages."""
    from app.core.db import get_historical_metrics
    hours = max(0.1, min(720.0, request.args.get('hours', default=1.0, type=float)))
    with _lock:
        mem_pts = list(_history.get(hid, [])) if hours <= 1 else []
        total = (_latest.get(hid) or {}).get("mem_total")
    first = mem_pts[0]["t"] if mem_pts else float('inf')
    rows = get_historical_metrics(hours=hours).get(hid, [])
    db_pts = [{"t": p["ts"], "cpu": p["cpu"], "mem": p["mem"] * 2 ** 30, "memTotal": total}
              for p in rows if p["ts"] < first - 60]
    return jsonify({"status": "success", "data": db_pts + mem_pts})


@hosts_bp.route('/<hid>', methods=['DELETE'])
def remove_host(hid):
    with _lock:
        hosts = _load()
        if not any(h['id'] == hid for h in hosts):
            return jsonify({"status": "error", "message": "no such host"}), 404
        _save([h for h in hosts if h['id'] != hid])
        _latest.pop(hid, None)
        _history.pop(hid, None)
        _actions.pop(hid, None)
        _checks.pop(hid, None)
        _inventory.pop(hid, None)
    return jsonify({"status": "success"})


# ---- agent ---------------------------------------------------------------------------

# Runs on the host. One snapshot every 5 s as "key: value" lines; Docker every 30 s
# in "#docker" / "#dstats" sections. The reply may carry actions ("do <id> <verb> <name>"). CPU % is the delta of two reads (Linux /proc/stat)
# or top's own two-sample figure (macOS).
AGENT_SH = r'''#!/bin/sh
# Arrakis host agent: reports this computer's usage to the dashboard.
URL="__URL__"
TOKEN="__TOKEN__"
OS_KIND=$(uname -s)
# where OrbStack's orb can be, whoever installed it
PATH="$PATH:$HOME/.orbstack/bin:/usr/local/bin:/opt/homebrew/bin"; export PATH
AGENT_PID=$$
[ -n "$HOME" ] && [ "$HOME" != / ] || HOME=$( (getent passwd "$(id -un)" 2>/dev/null || grep "^$(id -un):" /etc/passwd) | cut -d: -f6); export HOME
RPC_DIR="$HOME/.arrakis-agent/rpc"
# hardware model, once: "Mac mini", "MacBook Pro", "Raspberry Pi 4 Model B Rev 1.5", a PC's DMI name
if [ "$OS_KIND" = Darwin ]; then
  MODEL=$(system_profiler SPHardwareDataType 2>/dev/null | awk -F': ' '/Model Name/{print $2; exit}')
elif [ -r /proc/device-tree/model ]; then
  MODEL=$(tr -d '\000' < /proc/device-tree/model)
else
  MODEL=$(cat /sys/class/dmi/id/sys_vendor /sys/class/dmi/id/product_name 2>/dev/null | tr '\n' ' ')
fi
[ "$(id -u)" = 0 ] && IS_ROOT=1 || IS_ROOT=0
tick=0
prev_total=0; prev_idle=0; cpu_pct=

snapshot() {
  echo "agent: __VERSION__"
  echo "root: $IS_ROOT"
  echo "hostname: $(hostname 2>/dev/null | cut -d. -f1)"
  echo "kernel: $(uname -r)"
  echo "arch: $(uname -m)"
  [ -n "$MODEL" ] && echo "model: $MODEL"
  if [ "$OS_KIND" = Darwin ]; then
    echo "os: macOS $(sw_vers -productVersion 2>/dev/null)"
    # Full Disk Access: only then can it read the privacy database
    head -c 1 "$HOME/Library/Application Support/com.apple.TCC/TCC.db" >/dev/null 2>&1 && echo "fda: 1" || echo "fda: 0"
    echo "cores: $(sysctl -n hw.ncpu)"
    echo "cpu_pct: $(top -l 2 -n 0 -s 1 2>/dev/null | awk '/CPU usage/ {u=$3; s=$5} END {gsub("%","",u); gsub("%","",s); print u + s}')"
    page=$(sysctl -n hw.pagesize)
    echo "mem_total: $(sysctl -n hw.memsize)"
    echo "mem_used: $(vm_stat | awk -v p="$page" '/Pages active/ {a=$3} /Pages wired/ {w=$4} /occupied by compressor/ {c=$5} END {gsub("\\.","",a); gsub("\\.","",w); gsub("\\.","",c); printf "%.0f", (a + w + c) * p}')"
    echo "uptime_secs: $(( $(date +%s) - $(sysctl -n kern.boottime | sed 's/.*{ sec = \([0-9]*\).*/\1/') ))"
    df -Pk /System/Volumes/Data 2>/dev/null | awk 'NR==2 {print "disk_total_kb: " $2; print "disk_used_kb: " $2 - $4}'
  else
    . /etc/os-release 2>/dev/null; echo "os: ${PRETTY_NAME:-Linux}"
    echo "cores: $(grep -c ^processor /proc/cpuinfo)"
    [ -n "$cpu_pct" ] && echo "cpu_pct: $cpu_pct"
    awk '/^MemTotal/ {t=$2} /^MemAvailable/ {a=$2} END {printf "mem_total: %.0f\nmem_used: %.0f\n", t * 1024, (t - a) * 1024}' /proc/meminfo
    echo "uptime_secs: $(cut -d. -f1 /proc/uptime)"
    df -Pk / 2>/dev/null | awk 'NR==2 {print "disk_total_kb: " $2; print "disk_used_kb: " $2 - $4}'
  fi
  ip=$(tailscale ip -4 2>/dev/null | head -1)
  [ -n "$ip" ] && echo "ip: $ip"
  if [ $((tick % 6)) -eq 0 ]; then
    echo "#workloads"
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
      echo "#docker"
      docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null
      echo "#dstats"
      docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' 2>/dev/null
    fi
    if command -v systemctl >/dev/null 2>&1; then
      echo "#systemd"
      systemctl list-units --type=service --state=running --no-legend --plain 2>/dev/null
      [ -d /sys/fs/cgroup/system.slice ] && { echo "#svcuse"; svc_usage; }
    elif command -v rc-status >/dev/null 2>&1; then
      echo "#openrc"
      rc-status -a 2>/dev/null
    fi
    if command -v ss >/dev/null 2>&1; then
      echo "#listen"
      ss -ltnupH 2>/dev/null
    elif [ "$OS_KIND" = Darwin ]; then
      echo "#lsof"
      lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null
      # apps: processes inside an .app bundle, and anything listening on a port
      echo "#macapps"
      lp=" $(lsof -nP -iTCP -sTCP:LISTEN -t 2>/dev/null | sort -u | tr '\n' ' ') "
      ps -axo pid=,pcpu=,rss=,etime=,comm= 2>/dev/null | awk -v L="$lp" 'index($0, ".app/") || index(L, " " $1 " ")'
    else
      echo "#netstat"
      netstat -ltnup 2>/dev/null
    fi
  fi
  true
}

# Drives and OrbStack machines, every minute and after a drive or machine action:
# "#@<command>" then its output. A Mac sends the diskutil plists Arrakis's own Storage
# page reads; Linux sends lsblk. `orb list` would start OrbStack, so only while it runs.
inventory() {
  if [ "$OS_KIND" = Darwin ]; then
    for a in "list -plist" "list -plist physical" "apfs list -plist"; do
      echo "#@diskutil $a"; diskutil $a 2>/dev/null
    done
    for d in $(diskutil list -plist 2>/dev/null | sed -n 's:.*<string>\(disk[0-9s]*\)</string>.*:\1:p' | sort -u); do
      echo "#@diskutil info -plist $d"; diskutil info -plist "$d" 2>/dev/null
    done
  elif command -v lsblk >/dev/null 2>&1; then
    echo "#@lsblk"
    lsblk -J -b -o NAME,SIZE,TYPE,VENDOR,MODEL,TRAN,RM,HOTPLUG,ROTA,RO,MOUNTPOINT,FSTYPE,LABEL,FSAVAIL,FSUSED 2>/dev/null \
      || lsblk -J -b -o NAME,SIZE,TYPE,MODEL,RM,RO,MOUNTPOINT,FSTYPE,LABEL 2>/dev/null
    echo "#@df"; df -Pk 2>/dev/null
  fi
  # hardware health: temperatures, drive SMART (needs root and smartctl), UPS (NUT's upsc)
  if [ "$OS_KIND" = Darwin ]; then
    echo "#@pmset ps"; pmset -g ps 2>/dev/null
  else
    echo "#@temps"
    for z in /sys/class/thermal/thermal_zone*; do
      [ -r "$z/temp" ] && echo "$(cat "$z/type" 2>/dev/null) $(cat "$z/temp" 2>/dev/null)"
    done
    for d in /sys/class/hwmon/hwmon*; do
      n=$(cat "$d/name" 2>/dev/null)
      for t in "$d"/temp*_input; do
        [ -r "$t" ] || continue
        l=$(cat "${t%_input}_label" 2>/dev/null)
        echo "$n ${l:-$(basename "$t" _input)} $(cat "$t" 2>/dev/null)"
      done
    done
    if [ "$IS_ROOT" = 1 ] && command -v smartctl >/dev/null 2>&1 && command -v lsblk >/dev/null 2>&1; then
      for dev in $(lsblk -dno NAME,TYPE 2>/dev/null | awk '$2 == "disk" {print $1}'); do
        echo "#@smart /dev/$dev"; smartctl -j -H -A -i "/dev/$dev" 2>/dev/null
      done
    fi
  fi
  if command -v upsc >/dev/null 2>&1; then
    for u in $(upsc -l 2>/dev/null); do echo "#@upsc $u"; upsc "$u" 2>/dev/null; done
  fi
  if command -v orb >/dev/null 2>&1; then
    if orb status 2>/dev/null | grep -qi running; then
      echo "#@orb list"; orb list -f json 2>/dev/null
      echo "#@orb config"; orb config show 2>/dev/null
    else
      echo "#@orb stopped"
    fi
  fi
  true
}

# POST stdin to $URL/api/hosts/$1; prints the reply
post() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -m 10 -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: text/plain' --data-binary @- "$URL/api/hosts/$1"
  else
    wget -q -T 10 -O - --header="Authorization: Bearer $TOKEN" --post-file=/dev/stdin "$URL/api/hosts/$1"
  fi
}

# result <id> <exit code> <output>
result() {
  { echo "id: $1"; echo "rc: $2"; echo; printf '%s\n' "$3" | head -c 4000; } | post result >/dev/null 2>&1
}

# detached from this agent, so it survives the agent being stopped and replaced
detach() {
  if [ "$IS_ROOT" = 1 ] && command -v systemd-run >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemd-run --collect --quiet --unit="arrakis-agent-job-$$-$(date +%s)" /bin/sh -c "$1" >/dev/null 2>&1
  elif command -v setsid >/dev/null 2>&1; then
    setsid /bin/sh -c "$1" >/dev/null 2>&1 < /dev/null &
  elif command -v perl >/dev/null 2>&1; then
    perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV' /bin/sh -c "$1" >/dev/null 2>&1 < /dev/null &
  else
    nohup /bin/sh -c "$1" >/dev/null 2>&1 < /dev/null &
  fi
}

# Actions from the dashboard: only these verbs, only on a plain unit or container name
run_action() {
  id=$1; verb=$2; t=$3
  case "$t" in -) ;; ''|-*|*[!A-Za-z0-9@._:_-]*) result "$id" 2 "refused: bad name"; return ;; esac
  rc=0
  case "$verb" in
    service-start|service-stop|service-restart)
      a=${verb#service-}
      if command -v systemctl >/dev/null 2>&1; then out=$(systemctl "$a" "$t" 2>&1) || rc=$?
      elif command -v rc-service >/dev/null 2>&1; then out=$(rc-service "$t" "$a" 2>&1) || rc=$?
      else out="this host has neither systemd nor OpenRC"; rc=2
      fi ;;
    container-start|container-stop|container-restart)
      out=$(docker "${verb#container-}" "$t" 2>&1) || rc=$? ;;
    vm-start|vm-stop|vm-restart)
      if command -v orb >/dev/null 2>&1; then out=$(orb "${verb#vm-}" "$t" 2>&1) || rc=$?
      else out="OrbStack isn't installed here"; rc=2
      fi
      inventory | post inventory >/dev/null 2>&1 ;;
    disk-eject|volume-mount)
      if [ "$OS_KIND" != Darwin ]; then out="only Macs can do that from the dashboard"; rc=2
      elif [ "$verb" = disk-eject ] && diskutil info "$t" 2>/dev/null | grep -Eq 'Internal: +Yes'; then out="refused: $t is an internal drive"; rc=2
      elif [ "$verb" = disk-eject ]; then out=$(diskutil eject "$t" 2>&1) || rc=$?
      else out=$(diskutil mount "$t" 2>&1) || rc=$?
      fi
      inventory | post inventory >/dev/null 2>&1 ;;
    reboot)
      if [ "$IS_ROOT" != 1 ]; then result "$id" 1 "the agent isn't running as root, so it can't reboot"; return; fi
      result "$id" 0 "rebooting now"
      detach "sleep 1; systemctl reboot 2>/dev/null || shutdown -r now 2>/dev/null || reboot"
      return ;;
    backup-folders)
      # folders worth offering on the dashboard, one per line, straight away
      out=$(backup_candidates) ;;
    backup-sizes)
      # the same folders with their size in KB; slow on a big folder, so asked for separately
      out=$(backup_sizes) ;;
    backup)
      out=$(backup_run "$t" 2>&1) || rc=$? ;;
    update-agent)
      result "$id" 0 "updating: the new agent reports within a few seconds"
      detach "sleep 1; curl -fsSL '$URL/api/hosts/install.sh?t=$TOKEN' | sh"
      return ;;
    *) out="unknown action $verb"; rc=2 ;;
  esac
  [ -n "$out" ] || out="done"
  result "$id" "$rc" "$out"
}

# Folders worth backing up here. A Mac: the folders in the home folder (Library and
# Applications get rebuilt, not restored; OrbStack is the machines' own disks). Elsewhere: home and the usual data folders.
# (Kept out of $(...): macOS's sh can't parse a case statement inside one.)
backup_candidates() {
  if [ "$OS_KIND" = Darwin ]; then
    for d in "$HOME"/*/; do
      d=${d%/}
      case "${d##*/}" in
        Library|Applications|Public|OrbStack) ;;
        *) echo "$d" ;;
      esac
    done
  else
    for d in "$HOME" /home /root /etc /opt /srv /var/www /var/lib/docker/volumes; do [ -d "$d" ] && echo "$d"; done | sort -u
  fi
}

# "<folder><TAB><KB>" for each; a Mac measures only with Full Disk Access (without it
# macOS refuses or asks)
backup_sizes() {
  if [ "$OS_KIND" = Darwin ] && ! head -c 1 "$HOME/Library/Application Support/com.apple.TCC/TCC.db" >/dev/null 2>&1; then
    echo "no access"; return
  fi
  backup_candidates | while IFS= read -r d; do printf '%s\t%s\n' "$d" "$(du -sk "$d" 2>/dev/null | cut -f1)"; done
}

# backup_run <timestamp>: pack the folders Arrakis lists for this computer and upload them
backup_run() {
  ts=$1; f="${TMPDIR:-/tmp}/arrakis-backup.$(id -u).$$"
  curl -fsS -m 30 -H "Authorization: Bearer $TOKEN" "$URL/api/hosts/backup-plan" -o "$f.plan" || { echo "couldn't get the folder list"; return 1; }
  set --  # from here on $1... are the folders
  while IFS= read -r d; do [ -n "$d" ] && [ -e "$d" ] && set -- "$@" "${d#/}"; done < "$f.plan"
  rm -f "$f.plan"
  [ $# -gt 0 ] || { echo "none of the chosen folders exist here"; return 1; }
  ( cd / && tar -czf "$f.tgz" "$@" ) 2> "$f.err"; trc=$?
  # 1 = some file changed, vanished or couldn't be read while packing; the archive is still good
  if [ "$trc" -gt 1 ]; then head -c 1000 "$f.err"; rm -f "$f.tgz" "$f.err"; return 1; fi
  denied=$(grep -c -e 'Operation not permitted' -e 'Permission denied' "$f.err" 2>/dev/null)
  curl -fsS -m 10800 -T "$f.tgz" -H "Authorization: Bearer $TOKEN" "$URL/api/hosts/backup/$ts"; urc=$?
  # macOS keeps Documents, Desktop and the like from anything without Full Disk Access
  [ "${denied:-0}" -gt 0 ] && echo "skipped $denied items it isn't allowed to read$([ "$OS_KIND" = Darwin ] && echo ': give Arrakis Agent Full Disk Access')"
  rm -f "$f.tgz" "$f.err"
  return $urc
}

# Memory and CPU of each running service, from its cgroup (works without memory accounting,
# which Raspberry Pi OS turns off): "unit<TAB>bytes<TAB>cpu % of one core since the last pass"
svc_usage() {
  st="${TMPDIR:-/tmp}/arrakis-agent-svc.$(id -u)"; now=$(date +%s)
  for u in $(systemctl list-units --type=service --state=running --no-legend --plain 2>/dev/null | awk '{print $1}'); do
    d=/sys/fs/cgroup/system.slice/$u
    [ -r "$d/cgroup.procs" ] || continue
    kb=0
    for p in $(cat "$d/cgroup.procs" 2>/dev/null); do
      r=$(awk '/^VmRSS/ {print $2}' "/proc/$p/status" 2>/dev/null); kb=$((kb + ${r:-0}))
    done
    printf '%s\t%s\t%s\n' "$u" "$((kb * 1024))" "$(awk '/^usage_usec/ {print $2}' "$d/cpu.stat" 2>/dev/null)"
  done | awk -F'\t' -v now="$now" -v st="$st" '
    BEGIN { while ((getline l < st) > 0) { split(l, a, "\t"); if (a[1] == "#t") t0 = a[2]; else pu[a[1]] = a[2] } }
    { cpu = ""; if (t0 && now > t0 && $3 != "" && ($1 in pu)) cpu = sprintf("%.1f", ($3 - pu[$1]) / ((now - t0) * 1e4))
      print $1 "\t" $2 "\t" cpu; nu[$1] = $3 }
    END { print "#t\t" now > st; for (k in nu) print k "\t" nu[k] > st }'
}

# Command channel (only where OrbStack is installed): wait for a command from Arrakis,
# run it as `orb <args>` (never anything but orb), post back its exit code and output.
# Arrakis only sends commands to hosts whose owner switched on managing OrbStack.
rpc_loop() {
  mkdir -p "$RPC_DIR" && chmod 700 "$RPC_DIR"
  while kill -0 "$AGENT_PID" 2>/dev/null; do
    f="$RPC_DIR/poll"
    if curl -fsS -m $((__POLL__ + 15)) -H "Authorization: Bearer $TOKEN" "$URL/api/hosts/rpc" -o "$f" 2>/dev/null; then
      id=$(head -1 "$f")
      case "$id" in ''|*[!0-9]*) ;; *) mv "$f" "$RPC_DIR/job.$id"; run_rpc "$id" & ;; esac
    else
      sleep 5
    fi
  done
}

run_rpc() {
  jid=$1; j="$RPC_DIR/job.$jid"
  sed -n 2p "$j" | base64 -d > "$j.in" 2>/dev/null
  n=$(awk 'END {print NR}' "$j"); i=3
  set --  # from here on $1... are orb's arguments
  while [ "$i" -le "$n" ]; do
    set -- "$@" "$(sed -n "${i}p" "$j" | base64 -d 2>/dev/null)"
    i=$((i + 1))
  done
  orb "$@" < "$j.in" > "$j.out" 2> "$j.err"; rc=$?
  { echo "$rc"; base64 < "$j.out" | tr -d '\n'; echo; base64 < "$j.err" | tr -d '\n'; echo; } \
    | curl -fsS -m 60 -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: text/plain' --data-binary @- "$URL/api/hosts/rpc/$jid" >/dev/null 2>&1
  rm -f "$j" "$j.in" "$j.out" "$j.err"
}

# Linux CPU % from the change in /proc/stat since the last pass (kept out of the
# piped subshell so the previous reading survives)
linux_cpu() {
  set -- $(awk '/^cpu / {print $2+$3+$4+$5+$6+$7+$8+$9, $5+$6}' /proc/stat)
  cpu_pct=
  if [ "$prev_total" -gt 0 ] && [ "$1" -gt "$prev_total" ]; then
    cpu_pct=$(awk -v t=$(($1 - prev_total)) -v i=$(($2 - prev_idle)) 'BEGIN {printf "%.1f", 100 * (t - i) / t}')
  fi
  prev_total=$1; prev_idle=$2
}

[ "$OS_KIND" = Darwin ] || linux_cpu
command -v orb >/dev/null 2>&1 && command -v curl >/dev/null 2>&1 && rpc_loop &
while true; do
  [ "$OS_KIND" = Darwin ] || linux_cpu
  [ $((tick % 12)) -eq 0 ] && { inventory | post inventory >/dev/null 2>&1 & }
  snapshot | post report 2>/dev/null | while read -r w id verb t; do
    [ "$w" = do ] && run_action "$id" "$verb" "$t" &
  done
  tick=$((tick + 1))
  sleep __EVERY__
done
'''

# Writes the agent to ~/.arrakis-agent and keeps it running: launchd on macOS,
# a systemd unit as root, otherwise cron @reboot plus a start now.
INSTALL_SH = r'''#!/bin/sh
set -e
# a systemd service has no $HOME, and an update runs from inside one
[ -n "$HOME" ] && [ "$HOME" != / ] || HOME=$( (getent passwd "$(id -un)" 2>/dev/null || grep "^$(id -un):" /etc/passwd) | cut -d: -f6)
export HOME
DIR="$HOME/.arrakis-agent"
mkdir -p "$DIR"
cat > "$DIR/agent.sh" <<'ARRAKIS_AGENT'
__AGENT__
ARRAKIS_AGENT
chmod 700 "$DIR/agent.sh"
# An update on a Mac runs from inside the agent's own launchd job: stopping that job first
# would kill this script halfway, so the job is left running and restarted at the very end.
JOB="gui/$(id -u)/com.arrakis.agent"
IN_PLACE=0
[ "$(uname -s)" = Darwin ] && launchctl print "$JOB" >/dev/null 2>&1 && IN_PLACE=1
if [ -f "$DIR/uninstall.sh" ] && [ "$IN_PLACE" = 0 ]; then sh "$DIR/uninstall.sh" keep >/dev/null 2>&1 || true; fi

if [ "$(uname -s)" = Darwin ]; then
  # macOS grants Full Disk Access to apps, and treats a launchd job as whatever it starts.
  # Started as plain /bin/sh, the agent can't be granted it (and granting /bin/sh would
  # cover every script), so it runs under "Arrakis Agent.app": a launcher that starts
  # agent.sh as its child and stays its parent. Rebuilt only when its source changes, so
  # the access granted to it survives agent updates.
  RUN="/bin/sh"
  APP="$HOME/Applications/Arrakis Agent.app"
  if xcode-select -p >/dev/null 2>&1; then
    mkdir -p "$APP/Contents/MacOS"
    cat > "$DIR/launcher.c.new" <<'ARRAKIS_LAUNCHER'
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
extern char **environ;
static pid_t child;
static void pass(int sig) { if (child > 0) kill(child, sig); }
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    char *args[] = { "/bin/sh", argv[1], 0 };
    signal(SIGTERM, pass); signal(SIGINT, pass); signal(SIGHUP, pass);
    if (posix_spawn(&child, "/bin/sh", 0, 0, args, environ) != 0) return 1;
    int st;
    while (waitpid(child, &st, 0) < 0) {}
    return WIFEXITED(st) ? WEXITSTATUS(st) : 1;
}
ARRAKIS_LAUNCHER
    if ! cmp -s "$DIR/launcher.c.new" "$DIR/launcher.c" || [ ! -x "$APP/Contents/MacOS/arrakis-agent" ]; then
      cat > "$APP/Contents/Info.plist" <<'ARRAKIS_PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>com.arrakis.agent</string>
  <key>CFBundleName</key><string>Arrakis Agent</string>
  <key>CFBundleExecutable</key><string>arrakis-agent</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
</dict></plist>
ARRAKIS_PLIST
      cc -O2 -o "$APP/Contents/MacOS/arrakis-agent" -x c "$DIR/launcher.c.new" \
        && codesign --force -s - --identifier com.arrakis.agent "$APP" >/dev/null 2>&1 \
        && mv "$DIR/launcher.c.new" "$DIR/launcher.c"
    fi
    rm -f "$DIR/launcher.c.new"
    [ -x "$APP/Contents/MacOS/arrakis-agent" ] && RUN="$APP/Contents/MacOS/arrakis-agent"
  fi
  PLIST="$HOME/Library/LaunchAgents/com.arrakis.agent.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST.new" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.arrakis.agent</string>
  <key>ProgramArguments</key><array><string>$RUN</string><string>$DIR/agent.sh</string></array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Applications/Tailscale.app/Contents/MacOS</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
EOF
  SAME=0; cmp -s "$PLIST.new" "$PLIST" && SAME=1
  mv "$PLIST.new" "$PLIST"
  [ "$IN_PLACE" = 1 ] || launchctl bootstrap "gui/$(id -u)" "$PLIST"
  printf 'launchctl bootout "gui/$(id -u)/com.arrakis.agent" 2>/dev/null; rm -f "%s"\n' "$PLIST" > "$DIR/stop.sh"
  how="launchd (com.arrakis.agent, through $RUN)"
elif [ "$(id -u)" = 0 ] && command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  cat > /etc/systemd/system/arrakis-agent.service <<EOF
[Unit]
Description=Arrakis dashboard agent
After=network-online.target
[Service]
ExecStart=/bin/sh $DIR/agent.sh
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable arrakis-agent.service
  # restart, not just start: on an update the old agent is still running
  systemctl restart arrakis-agent.service
  printf 'systemctl disable --now arrakis-agent.service; rm -f /etc/systemd/system/arrakis-agent.service; systemctl daemon-reload\n' > "$DIR/stop.sh"
  how="systemd (arrakis-agent.service)"
else
  ( crontab -l 2>/dev/null | grep -v arrakis-agent; echo "@reboot /bin/sh $DIR/agent.sh >/dev/null 2>&1 # arrakis-agent" ) | crontab - 2>/dev/null || true
  nohup /bin/sh "$DIR/agent.sh" >/dev/null 2>&1 &
  echo $! > "$DIR/agent.pid"
  printf '( crontab -l 2>/dev/null | grep -v arrakis-agent ) | crontab - 2>/dev/null; kill "$(cat "%s/agent.pid")" 2>/dev/null\n' "$DIR" > "$DIR/stop.sh"
  how="cron @reboot (started now as pid $(cat "$DIR/agent.pid"))"
fi

cat > "$DIR/uninstall.sh" <<EOF
sh "$DIR/stop.sh" 2>/dev/null
[ "\$1" = keep ] || rm -rf "$DIR"
EOF
echo "Arrakis agent installed: $how"
echo "This host should show up on the dashboard within a few seconds."
echo "Remove it later with: sh ~/.arrakis-agent/uninstall.sh"
# last, since it also ends this script when it runs inside the job (an update)
# (launchd does the restart itself, so it completes even though this script goes with it)
if [ "$IN_PLACE" = 1 ] && [ "$SAME" = 1 ]; then
  launchctl kickstart -k "$JOB"
elif [ "$IN_PLACE" = 1 ]; then
  # the job's definition changed: reload it from a one-off job of its own
  launchctl submit -l com.arrakis.agent.reload -- /bin/sh -c "sleep 1; launchctl bootout $JOB; launchctl bootstrap gui/$(id -u) '$PLIST'; launchctl remove com.arrakis.agent.reload"
fi
'''


@hosts_bp.route('/install.sh', methods=['GET'])
def install_sh():
    h = _by_token(request.args.get('t', ''))
    if not h:
        return Response("echo 'Unknown host token: add the host on the dashboard first.' >&2; exit 1\n", status=404, mimetype='text/x-shellscript')
    agent = AGENT_SH.replace('__URL__', _server()).replace('__TOKEN__', h['token']).replace('__EVERY__', str(REPORT_EVERY)).replace('__POLL__', str(RPC_POLL)).replace('__VERSION__', str(AGENT_VERSION))
    return Response(INSTALL_SH.replace('__AGENT__', agent.strip()), mimetype='text/x-shellscript')
