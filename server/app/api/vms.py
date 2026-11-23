"""OrbStack Linux machines: list, create, delete, start/stop, and resource limits.

OrbStack runs every machine inside one shared pool of CPU cores and memory that is
carved out of the Mac (``cpu`` and ``memory_mib`` in ``orb config``). A machine can
also carry its own limit (``machine.<name>.cpu`` / ``memory_mib``); 0 means "no own
limit, share the pool".

Every route works for Arrakis's OrbStack (/api/vms/...) and for another host's
(/api/hosts/<id>/vms/..., when its owner turned that on): orbhost.current says which,
`orb` calls go there, and every cache and job table below is kept per host.
"""
from flask import Blueprint, jsonify, request
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from collections import deque

import psutil

from app.core import cftunnel, orbhost
from app.core.config import VM_NAME
from app.core.db import get_machine_history, insert_machine_metric, rename_machine_metrics
from app.core.logger import log

vms_bp = Blueprint('vms', __name__)

NAME_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')
ARCHES = ('arm64', 'amd64')
MIN_POOL_MEMORY_MIB = 1024
MIN_MACHINE_MEMORY_MIB = 1024  # orb refuses smaller per-machine limits
HOST_RESERVE_MIB = 2048  # macOS itself needs some of the RAM


def _run(args, timeout=30):
    if args and args[0] == 'orb':
        code, out, err = orbhost.run(args[1:], timeout=timeout)
        return code, (out or '').strip(), (err or '').strip()
    res = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return res.returncode, res.stdout.strip(), res.stderr.strip()


@vms_bp.url_value_preprocessor
def _pick_host(endpoint, values):
    """/api/hosts/<hid>/vms/... works on that host's OrbStack; /api/vms/... on Arrakis's."""
    hid = (values or {}).pop('hid', None)
    orbhost.current.set(None if hid in (None, 'arrakis') else hid)


def _kv(text):
    out = {}
    for line in text.splitlines():
        k, sep, v = line.partition(':')
        if sep:
            out[k.strip()] = v.strip()
    return out


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _host():
    h = orbhost.host()
    if h is None:
        return {"cores": os.cpu_count() or 0, "memory_mib": round(psutil.virtual_memory().total / 2**20)}
    from app.api.hosts import host_report
    r = host_report(h) or {}
    return {"cores": r.get("cores") or 0, "memory_mib": round((r.get("mem_total") or 0) / 2**20)}


def _config():
    code, out, err = _run(["orb", "config", "show"], timeout=15)
    if code != 0:
        raise RuntimeError(err or "orb config show failed")
    return _kv(out)


# ---- images --------------------------------------------------------------------

_images_cache = orbhost.PerHost(lambda: {"at": 0, "data": None})


def _images():
    """Distros and versions from `orb create --help` (cached: it never changes mid-run)."""
    if _images_cache["data"] and time.time() - _images_cache["at"] < 3600:
        return _images_cache["data"]
    code, out, err = _run(["orb", "create", "--help"], timeout=15)
    text = out or err
    distros = []
    in_list = False
    for line in text.splitlines():
        if line.strip().startswith('Supported distros'):
            in_list = True
            continue
        if in_list:
            m = re.match(r'^\s+([a-z0-9]+):\s+(.*)$', line)
            if not m:
                if line.strip():
                    in_list = False
                continue
            versions, default = [], None
            for part in m.group(2).split(','):
                part = part.strip()
                is_default = part.endswith('(default)')
                part = part.replace('(default)', '').strip()
                # "noble/24.04" lists two names for one version; the first is what `orb create` takes
                name = part.split('/')[0]
                versions.append({"id": name, "label": part})
                if is_default:
                    default = name
            distros.append({"distro": m.group(1), "versions": versions, "default": default})
    data = {"distros": distros, "arches": list(ARCHES)}
    _images_cache.update(at=time.time(), data=data)
    return data


# ---- tailscale ---------------------------------------------------------------------

TS_KEY_FILE = os.path.expanduser('~/.homelab_tailscale.json')  # kept out of /api/prefs so it never reaches the browser


def _ts_key():
    try:
        with open(TS_KEY_FILE) as f:
            return (json.load(f).get('auth_key') or '').strip()
    except Exception:  # noqa: BLE001
        return ''


def _ts_save_key(key):
    with open(TS_KEY_FILE, 'w') as f:
        json.dump({"auth_key": key}, f)
    os.chmod(TS_KEY_FILE, 0o600)


_ts_cache = orbhost.PerHost()  # name -> (ts, status)


def _ts_status(name, max_age=20):
    """Tailscale state inside a machine: missing | stopped | needs_login | running."""
    hit = _ts_cache.get(name)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    status = {"state": "missing", "ip": None, "dns": None, "tags": []}
    try:
        code, out, err = _run(["orb", "-m", name, "sh", "-c", "command -v tailscale >/dev/null && tailscale status --json"], timeout=10)
        if code == 0 and out:
            j = json.loads(out)
            self_ = j.get('Self') or {}
            state = {"Running": "running", "NeedsLogin": "needs_login", "Stopped": "stopped"}.get(j.get('BackendState'), "stopped")
            ips = [ip for ip in self_.get('TailscaleIPs') or [] if ':' not in ip]
            status = {"state": state, "ip": ips[0] if ips else None, "dns": (self_.get('DNSName') or '').rstrip('.') or None, "tags": self_.get('Tags') or []}
        else:
            # either not installed (command -v failed) or installed with the daemon down
            status["state"] = "stopped" if _run(["orb", "-m", name, "sh", "-c", "command -v tailscale"], timeout=8)[0] == 0 else "missing"
    except Exception as e:  # noqa: BLE001
        log.warning(f"tailscale status {name}: {e}")
    _ts_cache[name] = (time.time(), status)
    return status


INSTALL_TS = "command -v tailscale >/dev/null || { (command -v curl >/dev/null && curl -fsSL https://tailscale.com/install.sh || wget -qO- https://tailscale.com/install.sh) | sudo sh; }"


# Tailscale between VMs on different Macs: each VM sits behind its Mac's OrbStack network, so
# neither can offer the other an address that works and they fall back to a relay (DERP,
# ~150 ms, 1-2 MB/s). OrbStack exposes a machine's listening ports on the Mac's LAN address
# (machines.expose_ports_to_lan), so: a fixed Tailscale UDP port per machine, advertised at
# <Mac LAN IP>:<port> (TS_DEBUG_PRETENDPOINT). Then the VMs connect directly, ~8 ms.
DIRECT_TS = r"""PORT=@PORT@ EP=@EP@
if [ -f /etc/conf.d/tailscale ]; then
  F=/etc/conf.d/tailscale
  sed -i '/^port=/d; /^export TS_DEBUG_PRETENDPOINT=/d; /direct path between VMs/d' $F
  echo "# arrakis: direct path between VMs on different Macs" >> $F
  echo "port=$PORT" >> $F
  [ -n "$EP" ] && echo "export TS_DEBUG_PRETENDPOINT=$EP:$PORT" >> $F
  rc-service tailscale restart >/dev/null 2>&1 || rc-service tailscale start >/dev/null 2>&1
elif [ -f /etc/default/tailscaled ]; then
  F=/etc/default/tailscaled
  sed -i '/^PORT=/d; /^TS_DEBUG_PRETENDPOINT=/d' $F
  echo "PORT=$PORT" >> $F
  [ -n "$EP" ] && echo "TS_DEBUG_PRETENDPOINT=$EP:$PORT" >> $F
  systemctl restart tailscaled
fi
true"""


def _ts_port(name):
    """The machine's own Tailscale port (fixed per name, so ports rarely clash on one Mac)."""
    import zlib
    return 41700 + zlib.crc32(name.encode()) % 800


def _mac_lan_ip():
    """The LAN address of the Mac whose OrbStack this is (None if unknown)."""
    import ipaddress
    hid = orbhost.host()
    try:
        if hid is None:
            iface = subprocess.run(['route', '-n', 'get', 'default'], capture_output=True, text=True, timeout=5).stdout
            iface = next((l.split(':', 1)[1].strip() for l in iface.splitlines() if 'interface:' in l), 'en0')
            ip = subprocess.run(['ipconfig', 'getifaddr', iface], capture_output=True, text=True, timeout=5).stdout.strip()
            return ip or None
        from app.api import hosts
        with hosts._lock:
            r = hosts._latest.get(hid)
        ip = r and r.get('ip')
        if ip and ipaddress.ip_address(ip).is_private and not ip.startswith('100.'):
            return ip
        # its tailnet address: the LAN address Tailscale on Arrakis reaches it at
        st = json.loads(subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=5,
                                       env={**os.environ, 'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'}).stdout)
        for peer in st.get("Peer", {}).values():
            if ip in peer.get("TailscaleIPs", []) and peer.get("CurAddr"):
                lan = peer["CurAddr"].rsplit(':', 1)[0].strip('[]')
                return lan if ipaddress.ip_address(lan).is_private else None
    except Exception as e:  # noqa: BLE001
        log.warning(f"tailscale direct path: no LAN address for {hid or 'arrakis'} ({e})")
    return None


def _ts_join(name):
    """Install Tailscale if needed and bring the node up with the stored auth key."""
    key = _ts_key()
    if not key:
        raise RuntimeError("No Tailscale auth key set (Settings → Tailscale)")
    code, out, err = _run(["orb", "-m", name, "sh", "-c", INSTALL_TS], timeout=600)
    if code != 0:
        raise RuntimeError(f"install failed: {(err or out)[-400:]}")
    lan = _mac_lan_ip()
    script = DIRECT_TS.replace('@PORT@', str(_ts_port(name))).replace('@EP@', lan or '')
    code, out, err = _run(["orb", "-m", name, "sudo", "sh", "-c", script], timeout=60)
    if code != 0:
        log.warning(f"tailscale direct path for {name}: {(err or out)[-200:]}")
    code, out, err = _run(["orb", "-m", name, "sudo", "tailscale", "up", f"--authkey={key}", "--ssh", f"--hostname={name}"], timeout=120)
    if code != 0:
        raise RuntimeError((err or out)[-400:] or "tailscale up failed")
    _ts_cache.pop(name, None)


def _ts_job(name):
    try:
        _ts_join(name)
        with _jobs_lock:
            _jobs[name] = {"kind": "tailscale", "state": "done", "message": "", "started": _jobs[name]["started"]}
    except Exception as e:  # noqa: BLE001
        with _jobs_lock:
            _jobs[name] = {"kind": "tailscale", "state": "error", "message": str(e), "started": _jobs[name]["started"]}
    _invalidate_list(name)
    log.info(f"tailscale join {name}: {_jobs[name]['state']}")


# ---- create jobs ---------------------------------------------------------------

_jobs = orbhost.PerHost()          # name -> {"state": "creating"|"error"|"done", "message": str, "started": ts}
_jobs_lock = threading.Lock()


def _create_job(name, args, join_tailscale=False):
    try:
        code, out, err = _run(args, timeout=1800)
        if code == 0 and join_tailscale:
            with _jobs_lock:
                _jobs[name] = {"kind": "tailscale", "state": "creating", "message": "joining Tailscale", "started": _jobs[name]["started"]}
            _ts_join(name)
        with _jobs_lock:
            if code == 0:
                _jobs[name] = {"kind": "create", "state": "done", "message": out, "started": _jobs[name]["started"]}
            else:
                _jobs[name] = {"kind": "create", "state": "error", "message": err or out or f"orb create exited {code}", "started": _jobs[name]["started"]}
    except Exception as e:  # noqa: BLE001
        with _jobs_lock:
            _jobs[name] = {"kind": _jobs[name].get("kind", "create"), "state": "error", "message": str(e), "started": _jobs[name]["started"]}
    _invalidate_list(name)
    log.info(f"orb create {name}: {_jobs[name]['state']}")


# ---- routes ----------------------------------------------------------------------

# The machine list costs several orb calls (list, config, info and tailscale per
# machine), so the sampler thread keeps it fresh and requests read the cache.
# Anything that changes a machine drops the cache so the next read is current.
_list_cache = orbhost.PerHost(lambda: {"at": 0, "machines": None, "cfg": None})
_list_lock = threading.Lock()
LIST_MAX_AGE = 30


def _build_list():
    code, out, err = _run(["orb", "list", "-f", "json"], timeout=15)
    if code != 0:
        raise RuntimeError(err or "orb list failed")
    cfg = _config()
    machines = []
    for m in json.loads(out or '[]'):
        name = m.get('name')
        running = m.get('state') == 'running'
        info = _kv(_run(["orb", "info", name], timeout=10)[1]) if running else {}
        machines.append({
            "name": name,
            "state": m.get('state'),
            "image": m.get('image', {}),
            "username": m.get('config', {}).get('default_username'),
            "isolated": bool(m.get('config', {}).get('isolated')),
            "isolate_network": cfg.get(f'machine.{name}.isolate_network') == 'true',
            "forward_ssh_agent": cfg.get(f'machine.{name}.forward_ssh_agent') == 'true',
            "http_port": _int(cfg.get(f'machine.{name}.http_port')),
            "https_port": _int(cfg.get(f'machine.{name}.https_port')),
            "mounts": _mounts(cfg.get(f'machine.{name}.mounts')),
            "ip": info.get('IPv4'),
            "disk_usage": info.get('Disk usage'),
            # 0 = no limit of its own; it shares the pool
            "cpu": _int(cfg.get(f'machine.{name}.cpu')),
            "memory_mib": _int(cfg.get(f'machine.{name}.memory_mib')),
            "disk_bytes": _int(cfg.get(f'machine.{name}.disk_bytes')),
            "tailscale": _ts_status(name) if running else {"state": "unknown", "ip": None, "dns": None, "tags": []},
            "share": cftunnel.share_info(name, running),
        })
    with _list_lock:
        _list_cache.update(at=time.time(), machines=machines, cfg=cfg)
    return machines, cfg


def _get_list(max_age=LIST_MAX_AGE):
    with _list_lock:
        if _list_cache["machines"] is not None and time.time() - _list_cache["at"] < max_age:
            return _list_cache["machines"], _list_cache["cfg"]
    return _build_list()


def _invalidate_list(name=None):
    with _list_lock:
        _list_cache["at"] = 0
    if name:
        _ts_cache.pop(name, None)


@vms_bp.route('', methods=['GET'])
@vms_bp.route('/', methods=['GET'])
def list_vms():
    try:
        machines, cfg = _get_list()
        known = {m["name"] for m in machines}
        with _jobs_lock:
            # finished jobs vanish once the machine shows up (or after the error is seen)
            for name, job in list(_jobs.items()):
                if job["state"] == "done" and name in known:
                    del _jobs[name]
            jobs = {k: dict(v) for k, v in _jobs.items()}
        return jsonify({"status": "success", "data": {
            "machines": machines,
            "jobs": jobs,
            "pool": {"cpu": _int(cfg.get('cpu')), "memory_mib": _int(cfg.get('memory_mib'))},
            "orb": {k: cfg.get(k) == "true" for k in ORB_SWITCHES},
            "host": _host(),
            "dashboard_vm": VM_NAME if orbhost.host() is None else None,  # the machine the Overview's live VM metrics come from
            "tailscale_key": bool(_ts_key()),
            "home": os.path.expanduser("~") if orbhost.host() is None else None,
            "sharing": {"logged_in": cftunnel.logged_in(), "domain": cftunnel.domain(), "permissions": cftunnel.permission_schema()},
        }})
    except Exception as e:  # noqa: BLE001
        log.error(f"list_vms: {e}")
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/images', methods=['GET'])
def images():
    try:
        return jsonify({"status": "success", "data": _images()})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/pool', methods=['PATCH'])
def set_pool():
    """Resize the shared OrbStack pool. Takes effect after OrbStack restarts."""
    body = request.get_json(silent=True) or {}
    host = _host()
    cpu, mem = _int(body.get('cpu'), -1), _int(body.get('memory_mib'), -1)
    disk = _int(body.get('disk_gib'), -1)
    if disk != -1 and disk != 0 and not (2 <= disk <= 4096):
        return jsonify({"status": "error", "message": "disk must be 0 (no limit) or 2..4096 GiB"})
    if cpu != -1 and not (1 <= cpu <= host["cores"]):
        return jsonify({"status": "error", "message": f"cpu must be between 1 and {host['cores']}"})
    max_mem = host["memory_mib"] - HOST_RESERVE_MIB
    if mem != -1 and not (MIN_POOL_MEMORY_MIB <= mem <= max_mem):
        return jsonify({"status": "error", "message": f"memory_mib must be between {MIN_POOL_MEMORY_MIB} and {max_mem}"})
    try:
        for key, val in (('cpu', cpu), ('memory_mib', mem), ('disk_bytes', disk if disk <= 0 else disk << 30)):
            if val != -1:
                code, out, err = _run(["orb", "config", "set", key, str(val)], timeout=15)
                if code != 0:
                    return jsonify({"status": "error", "message": err or out or f"could not set {key}"})
        _invalidate_list()
        return jsonify({"status": "success", "message": "Pool updated. Restart OrbStack to apply."})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


# OrbStack-wide switches the dashboard offers (all true/false in `orb config`).
# app.start_at_login is left out on purpose: `orb config` reports it differently depending on
# which process asks (false from a shell, true from the dashboard's launchd agent), so the
# dashboard can't show it truthfully. It's set in the OrbStack app.
ORB_SWITCHES = ("power.pause_in_sleep", "machines.expose_ports_to_lan", "docker.expose_ports_to_lan",
                "machines.forward_ports", "network.https", "ssh.expose_port", "rosetta")


@vms_bp.route('/orbstack', methods=['PATCH'])
def set_orbstack():
    """OrbStack-wide switches: {"app.start_at_login": true, …}. Some apply after OrbStack restarts."""
    body = request.get_json(silent=True) or {}
    bad = [k for k in body if k not in ORB_SWITCHES]
    if bad:
        return jsonify({"status": "error", "message": f"Not a setting the dashboard changes: {', '.join(bad)}"})
    out = err = ""
    try:
        for k, v in body.items():
            code, out, err = _run(["orb", "config", "set", k, "true" if v else "false"], timeout=15)
            if code != 0:
                return jsonify({"status": "error", "message": err or out or f"could not set {k}"})
        _invalidate_list()
        return jsonify({"status": "success", "restart": "Restart the machine" in (out or "") + (err or "")})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/pool/restart', methods=['POST'])
def restart_pool():
    """Restart OrbStack itself so a new pool size applies (every machine restarts)."""
    try:
        code, out, err = _run(["orb", "stop"], timeout=120)
        if code != 0:
            return jsonify({"status": "error", "message": err or out or "orb stop failed"})
        code, out, err = _run(["orb", "start"], timeout=180)
        if code != 0:
            return jsonify({"status": "error", "message": err or out or "orb start failed"})
        _invalidate_list()
        return jsonify({"status": "success"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/<name>/limits', methods=['PATCH'])
def set_limits(name):
    """Per-machine limit. 0 removes it (the machine shares the pool)."""
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    body = request.get_json(silent=True) or {}
    host = _host()
    cpu, mem = _int(body.get('cpu'), -1), _int(body.get('memory_mib'), -1)
    disk = _int(body.get('disk_gib'), -1)
    if disk != -1 and disk != 0 and not (2 <= disk <= 4096):
        return jsonify({"status": "error", "message": "disk must be 0 (no limit) or 2..4096 GiB"})
    if cpu != -1 and not (0 <= cpu <= host["cores"]):
        return jsonify({"status": "error", "message": f"cpu must be 0 (share the pool) or 1..{host['cores']}"})
    if mem != -1 and mem != 0 and not (MIN_MACHINE_MEMORY_MIB <= mem <= host["memory_mib"]):
        return jsonify({"status": "error", "message": "memory_mib must be 0 (share the pool) or at least 1024 (OrbStack's minimum)"})
    try:
        for key, val in (('cpu', cpu), ('memory_mib', mem), ('disk_bytes', disk if disk <= 0 else disk << 30)):
            if val != -1:
                code, out, err = _run(["orb", "config", "set", f"machine.{name}.{key}", str(val)], timeout=15)
                if code != 0:
                    return jsonify({"status": "error", "message": err or out or f"could not set {key}"})
        _invalidate_list(name)
        return jsonify({"status": "success", "message": "Limits saved. Restart the machine to apply."})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/<name>/isolation', methods=['PATCH'])
def set_isolation(name):
    """Mac access: `isolated` unmounts the Mac's files (/Users, /Volumes…) and removes the
    `mac` command; `isolate_network` also blocks the Mac's and other machines' addresses.
    A shared machine must stay isolated. Applies after a restart."""
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    body = request.get_json(silent=True) or {}
    if body.get('isolated') is False and cftunnel.shares().get(cftunnel.K(name)):
        return jsonify({"status": "error", "message": "Stop sharing it first: a shared machine must not see the Mac's files"})
    try:
        for key in ('isolated', 'isolate_network'):
            if key in body:
                code, out, err = _run(["orb", "config", "set", f"machine.{name}.{key}", "true" if body[key] else "false"], timeout=15)
                if code != 0:
                    return jsonify({"status": "error", "message": err or out or f"could not set {key}"})
        _invalidate_list(name)
        return jsonify({"status": "success", "message": "Saved. Restart the machine to apply."})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


def _mounts(raw):
    """`orb config` prints the mounts list comma-separated as SOURCE[:DEST]."""
    out = []
    for item in (raw or '').split(','):
        item = item.strip()
        if item:
            src, _, dest = item.partition(':')
            out.append({"source": src, "dest": dest or src})
    return out


# OrbStack writing to the exFAT T7 deadlocked macOS's exFAT driver (needed a reboot), and
# the home folder itself holds ~/.ssh and the dashboard's secrets.
_MOUNT_BLOCKED = ("/Volumes/Magic-Rock",)


def _clean_mount(mnt):
    src = os.path.normpath((mnt.get("source") or "").strip())
    dest = os.path.normpath((mnt.get("dest") or "").strip() or src)
    if not src.startswith("/") or not dest.startswith("/") or ":" in src + dest or "," in src + dest:
        raise ValueError("Folders must be absolute paths without : or ,")
    if orbhost.host() is None:
        home = os.path.expanduser("~")
        if src in ("/", "/Users", home) or home.startswith(src + "/"):
            raise ValueError(f"{src} would share your whole home folder (SSH keys and the dashboard's secrets included); pick a folder inside it")
        if any(src == b or src.startswith(b + "/") for b in _MOUNT_BLOCKED):
            raise ValueError(f"{src} is on the exFAT drive; OrbStack touching it froze macOS before")
        if src.startswith(os.path.join(home, ".")) or "/.ssh" in src:
            raise ValueError("Hidden folders like ~/.ssh can't be shared")
        if not os.path.isdir(src):
            raise ValueError(f"{src} isn't a folder on this Mac")
    if dest in ("/", "/etc", "/usr", "/bin", "/sbin", "/lib", "/var", "/root", "/home", "/proc", "/sys", "/dev"):
        raise ValueError(f"{dest} is a system folder inside the machine; mount somewhere like /mnt/{os.path.basename(src) or 'shared'}")
    return f"{src}:{dest}"


@vms_bp.route('/<name>/options', methods=['PATCH'])
def set_options(name):
    """OrbStack options that apply after a restart: shared folders and SSH agent forwarding
    (isolated machines only) and which ports <name>.orb.local opens."""
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    body = request.get_json(silent=True) or {}
    try:
        sets = []
        if 'forward_ssh_agent' in body:
            sets.append(('forward_ssh_agent', 'true' if body['forward_ssh_agent'] else 'false'))
        for key in ('http_port', 'https_port'):
            if key in body:
                v = _int(body[key], -1)
                if not 0 <= v <= 65535:
                    return jsonify({"status": "error", "message": f"{key} must be 0 (automatic) or a port number"})
                sets.append((key, str(v)))
        for key, val in sets:
            code, out, err = _run(["orb", "config", "set", f"machine.{name}.{key}", val], timeout=15)
            if code != 0:
                return jsonify({"status": "error", "message": err or out or f"could not set {key}"})
        if 'mounts' in body:
            want = [_clean_mount(x) for x in body['mounts'] or []]
            have = [f"{x['source']}:{x['dest']}" for x in _mounts(_config().get(f'machine.{name}.mounts'))]
            for item in [h for h in have if h not in want]:
                _run(["orb", "config", "remove", f"machine.{name}.mounts", item], timeout=15)
            for item in [w for w in want if w not in have]:
                code, out, err = _run(["orb", "config", "add", f"machine.{name}.mounts", item], timeout=15)
                if code != 0:
                    return jsonify({"status": "error", "message": err or out or "could not add the folder"})
        _invalidate_list(name)
        return jsonify({"status": "success", "message": "Saved. Restart the machine to apply."})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


# Inside the machine: timezone and a daily unattended package upgrade. Both apply at once.
SYSTEM_GET_SH = r"""
tz=$(cat /etc/timezone 2>/dev/null || readlink /etc/localtime | sed 's#.*/zoneinfo/##'); echo "tz=$tz"
for f in /etc/periodic/daily/homelab-autoupdate /etc/cron.daily/homelab-autoupdate; do [ -f "$f" ] && echo "auto=1"; done
for c in apk apt-get dnf pacman zypper; do command -v $c >/dev/null && { echo "pm=$c"; break; }; done
pgrep -x crond >/dev/null || pgrep -x cron >/dev/null && echo "cron=1"
true
"""
SYSTEM_SET_SH = r"""
set -e
TZ="$1"; AUTO="$2"
if [ -n "$TZ" ]; then
  [ -f "/usr/share/zoneinfo/$TZ" ] || { command -v apk >/dev/null && apk add --no-cache -q tzdata >/dev/null 2>&1; }
  [ -f "/usr/share/zoneinfo/$TZ" ] || { echo "no zoneinfo for $TZ in the machine" >&2; exit 1; }
  ln -sf "/usr/share/zoneinfo/$TZ" /etc/localtime; echo "$TZ" > /etc/timezone
fi
D=/etc/periodic/daily; [ -d $D ] || D=/etc/cron.daily
F=$D/homelab-autoupdate
if [ "$AUTO" = 1 ]; then
  mkdir -p $D
  if command -v apk >/dev/null; then C="apk upgrade --no-cache -q"
  elif command -v apt-get >/dev/null; then C="DEBIAN_FRONTEND=noninteractive apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get -y -qq upgrade"
  elif command -v dnf >/dev/null; then C="dnf -y -q upgrade"
  elif command -v pacman >/dev/null; then C="pacman -Syu --noconfirm"
  else echo "no known package manager" >&2; exit 1; fi
  printf '#!/bin/sh
# homelab dashboard: daily unattended upgrade
%s >/var/log/homelab-autoupdate.log 2>&1
' "$C" > $F; chmod 755 $F
  if command -v rc-service >/dev/null && ! pgrep -x crond >/dev/null; then rc-update add crond default >/dev/null 2>&1; rc-service crond start >/dev/null 2>&1 || true; fi
elif [ "$AUTO" = 0 ]; then rm -f /etc/periodic/daily/homelab-autoupdate /etc/cron.daily/homelab-autoupdate; fi
"""


@vms_bp.route('/<name>/system', methods=['GET'])
def get_system(name):
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    code, out, err = _run(["orb", "-m", name, "-u", "root", "sh", "-c", SYSTEM_GET_SH], timeout=15)
    if code != 0:
        return jsonify({"status": "error", "message": err or "machine not reachable"})
    kv = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    import zoneinfo
    return jsonify({"status": "success", "data": {"timezone": kv.get("tz", ""), "autoupdate": kv.get("auto") == "1",
                    "package_manager": kv.get("pm"), "timezones": sorted(zoneinfo.available_timezones())}})


@vms_bp.route('/<name>/system', methods=['PATCH'])
def set_system(name):
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    body = request.get_json(silent=True) or {}
    import zoneinfo
    tz = (body.get('timezone') or '').strip()
    if tz and tz not in zoneinfo.available_timezones():
        return jsonify({"status": "error", "message": f"Unknown timezone {tz}"})
    auto = '' if 'autoupdate' not in body else ('1' if body['autoupdate'] else '0')
    code, out, err = _run(["orb", "-m", name, "-u", "root", "sh", "-c", SYSTEM_SET_SH, "sh", tz, auto], timeout=120)
    if code != 0:
        return jsonify({"status": "error", "message": (err or out or "failed")[-300:]})
    return jsonify({"status": "success"})


def _ensure_isolated(name):
    """Sharing a machine that mounts the Mac would hand every guest the owner's files, keys
    and the `mac` command, so sharing isolates it first (one restart)."""
    m = next((x for x in _get_list(0)[0] if x["name"] == name), None)
    if m and m.get("isolated"):
        return
    for args in (["orb", "config", "set", f"machine.{name}.isolated", "true"], ["orb", "restart", name]):
        code, out, err = _run(args, timeout=120)
        if code != 0:
            raise RuntimeError(err or out or f"{' '.join(args)} failed")
    for _ in range(30):  # sshd/tailscale need a moment after the restart
        if _run(["orb", "-m", name, "-u", "root", "true"], timeout=10)[0] == 0:
            break
        time.sleep(1)
    _invalidate_list(name)
    log.info(f"isolated {name} from the Mac before sharing")


def _ts_logout_before_delete(name):
    """Log a machine out of Tailscale so it leaves the tailnet instead of lingering there as an
    offline device. Only for a running machine (`orb -m` would boot a stopped one); a failure is
    logged and the delete goes ahead."""
    try:
        code, out, _ = _run(["orb", "list", "-f", "json"], timeout=15)
        if code != 0 or not any(m.get('name') == name and m.get('state') == 'running' for m in json.loads(out or '[]')):
            return
        code, out, err = _run(["orb", "-m", name, "sh", "-c", "! command -v tailscale >/dev/null || sudo tailscale logout"], timeout=30)
        if code != 0:
            log.warning(f"tailscale logout before deleting {name}: {(err or out)[-200:]}")
    except Exception as e:  # noqa: BLE001
        log.warning(f"tailscale logout before deleting {name}: {e}")
    finally:
        _ts_cache.pop(name, None)


# Usage of one machine, read from its own cgroup: /proc inside an OrbStack machine
# describes the whole shared VM, the cgroup files describe just this machine.
# One read is a snapshot; CPU % comes from the difference between two reads.
# Only /proc and cgroup files are used for time, so it works on BusyBox (Alpine) too.
STATS_SH = r"""
echo "cpu_usec: $(awk '/^usage_usec/{print $2}' /sys/fs/cgroup/cpu.stat)"
echo "now_usec: $(awk '{printf "%.0f", $1 * 1000000}' /proc/uptime)"
echo "cpu_max: $(cat /sys/fs/cgroup/cpu.max)"
echo "mem_current: $(cat /sys/fs/cgroup/memory.current)"
echo "mem_max: $(cat /sys/fs/cgroup/memory.max)"
echo "pids: $(find /sys/fs/cgroup -name cgroup.procs -exec cat {} + 2>/dev/null | sort -u | wc -l)"
echo "started_secs: $(awk -v t="$(getconf CLK_TCK 2>/dev/null || echo 100)" -v up="$(cut -d' ' -f1 /proc/uptime)" '{printf "%.0f", up - $22 / t}' /proc/1/stat)"
echo "kernel: $(uname -r)"
. /etc/os-release 2>/dev/null; echo "os: $PRETTY_NAME"
"""


def _read(name):
    code, out, err = _run(["orb", "-m", name, "-u", "root", "sh", "-c", STATS_SH], timeout=10)
    if code != 0:
        raise RuntimeError(err or "machine not reachable")
    return _kv(out)


def _sample(name, cfg, prev=None):
    """prev: an earlier _read() of the same machine; without one, read twice."""
    if prev is None:
        prev = _read(name)
        time.sleep(0.4)
    kv = _read(name)
    quota, _, period = kv.get('cpu_max', 'max').partition(' ')
    # cores it may use: its own quota, else the pool
    cores = (int(quota) / int(period)) if quota.isdigit() and period.isdigit() else _int(cfg.get('cpu'))
    wall = _int(kv.get('now_usec')) - _int(prev.get('now_usec'))
    used = _int(kv.get('cpu_usec')) - _int(prev.get('cpu_usec'))
    cores_used = max(0, used) / wall if wall > 0 else 0
    mem_max = kv.get('mem_max', 'max')
    mem_limit = int(mem_max) if mem_max.isdigit() else _int(cfg.get('memory_mib')) * 2**20
    return kv, {
        "cpu_cores_used": round(cores_used, 3),
        "cpu_cores": cores,
        "cpu_pct": round(min(100, 100 * cores_used / cores), 1) if cores else None,
        "mem_bytes": _int(kv.get('mem_current')),
        "mem_limit_bytes": mem_limit,
        "mem_is_pool": not mem_max.isdigit(),
        "cpu_is_pool": not quota.isdigit(),
        "processes": _int(kv.get('pids')),
        "uptime_secs": _int(kv.get('started_secs')),
        "kernel": kv.get('kernel'),
        "os": kv.get('os'),
        "at": time.time(),
    }


# What runs inside a machine: Docker containers, running systemd services and
# listening sockets. Collected every 30 s by the sampler (one orb exec per machine).
WORKLOADS_SH = r"""
if command -v docker >/dev/null 2>&1; then
  echo "#docker"
  docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null
fi
if command -v systemctl >/dev/null 2>&1; then
  echo "#systemd"
  systemctl list-units --type=service --state=running --no-legend --plain 2>/dev/null
elif command -v rc-status >/dev/null 2>&1; then
  echo "#openrc"
  rc-status -a 2>/dev/null
fi
if command -v ss >/dev/null 2>&1; then
  echo "#listen"
  ss -ltnupH 2>/dev/null
else
  echo "#netstat"
  netstat -ltnup 2>/dev/null
fi
true
"""
# units every Linux box runs; shown separately so the interesting ones stand out
_BASE_UNITS = re.compile(r'^(systemd-|dbus|user@|getty@|console-getty|serial-getty|cron|crond|polkit|rsyslog|syslog|udisks2|accounts-daemon|unattended-upgrades|ssh|sshd|containerd|chrony|ntp|irqbalance|snapd|multipathd|networkd-dispatcher|ModemManager|NetworkManager|avahi-daemon|packagekit|upower|bootmisc|devfs|dmesg|hostname|hwclock|hwdrivers|localmount|loopback|modules|mdev|networking|procfs|savecache|sysctl|sysfs|cgroups|cgroup-delegate|killprocs|mount-ro|seedrng|swap|termencoding|machine-id|root|bluetooth|wpa_supplicant|rpcbind|nfs-blkmap|rtkit-daemon|colord|cups|cups-browsed|triggerhappy|hciuart|alsa-state|rng-tools-debian|dphys-swapfile|getty)$|^(systemd-|user@|getty@|serial-getty)')
_OPENRC_RE = re.compile(r'^\s*(\S+)\s+\[\s*started\b')
_NETSTAT_RE = re.compile(r'^(tcp|udp)6?\s+\d+\s+\d+\s+(\S+)\s+\S+\s+(?:LISTEN\s+)?(?:(\d+)/(\S+))?')
_LISTEN_RE = re.compile(r'^(\w+)\s+\S+\s+\d+\s+\d+\s+(\S+):(\d+)\s+\S+\s*(?:users:\(\("([^"]+)",pid=(\d+))?')


def _parse_workloads(out):
    section, docker, units, listen = None, None, [], {}
    for line in out.splitlines():
        if line.startswith('#'):
            section = line[1:].strip()
            if section == 'docker':
                docker = []
            continue
        if not line.strip():
            continue
        if section == 'docker':
            p = (line.split('\t') + [''] * 5)[:5]
            docker.append({"name": p[0], "image": p[1], "state": p[2], "status": p[3], "ports": p[4]})
        elif section == 'systemd':
            parts = line.split(None, 4)
            if len(parts) >= 4:
                unit = parts[0].removesuffix('.service')
                units.append({"unit": unit, "description": parts[4] if len(parts) > 4 else "", "base": bool(_BASE_UNITS.match(unit))})
        elif section == 'openrc':
            m = _OPENRC_RE.match(line)
            if m and not any(u["unit"] == m.group(1) for u in units):
                units.append({"unit": m.group(1), "description": "", "base": bool(_BASE_UNITS.match(m.group(1)))})
        elif section in ('listen', 'netstat', 'lsof'):
            if section == 'lsof':
                # macOS: "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME", NAME = "*:8096 (LISTEN)"
                p = line.split()
                if len(p) < 10 or not p[1].isdigit() or '(LISTEN)' not in line:
                    continue
                addr, _, port = p[8].rpartition(':')
                if not port.isdigit():
                    continue
                proto, pid, proc = 'tcp', p[1], p[0].replace('\\x20', ' ')
                addr = '0.0.0.0' if addr == '*' else addr
            elif section == 'listen':
                m = _LISTEN_RE.match(line)
                if not m:
                    continue
                proto, addr, port, proc, pid = m.groups()
            else:
                m = _NETSTAT_RE.match(line)
                if not m or ':' not in m.group(2):
                    continue
                proto, local, pid, proc = m.groups()
                proc = (proc or '').rstrip(':') or None
                addr, _, port = local.rpartition(':')
                if not port.isdigit():
                    continue
                addr = addr or '::'
            addr = addr.split('%')[0].strip('[]')
            local = addr.startswith('127.') or addr == '::1'
            key = (proto, int(port), proc)
            entry = listen.setdefault(key, {"proto": proto, "port": int(port), "process": proc or "?", "pid": int(pid) if pid else None, "addresses": [], "local_only": True})
            if addr not in entry["addresses"]:
                entry["addresses"].append(addr)
            entry["local_only"] = entry["local_only"] and local
    ports = sorted(listen.values(), key=lambda e: (e["proto"] != "tcp", e["port"]))
    return {"docker": docker, "services": units, "listening": ports, "at": time.time()}


_workloads = orbhost.PerHost()


def _collect_workloads(name):
    try:
        code, out, err = _run(["orb", "-m", name, "-u", "root", "sh", "-c", WORKLOADS_SH], timeout=15)
        if code == 0 or out:
            _workloads[name] = _parse_workloads(out)
    except Exception as e:  # noqa: BLE001
        log.warning(f"workloads {name}: {e}")


# Background sampler: every running machine, every 5 s, in parallel. Keeps the latest
# sample (served by /stats and /usage) and the last hour (served by /history), and
# refreshes the machine list cache every other pass.
HISTORY_EVERY = 5
HISTORY_KEEP = 720
_history = orbhost.PerHost()
_latest = orbhost.PerHost()
_raw = orbhost.PerHost()            # name -> last _read(), the baseline for the next CPU delta
_history_lock = threading.Lock()
_sampler_started = False


def _sample_one(name, cfg):
    try:
        kv, d = _sample(name, cfg, _raw.get(name))
        _raw[name] = kv
        with _history_lock:
            _latest[name] = d
            _history.setdefault(name, deque(maxlen=HISTORY_KEEP)).append(
                {"t": d["at"], "cpu": d["cpu_pct"], "mem": d["mem_bytes"], "memLimit": d["mem_limit_bytes"]})
        insert_machine_metric(orbhost.host() or 'arrakis', name, d["at"], d["cpu_pct"], d["mem_bytes"], d["mem_limit_bytes"])
    except Exception as e:  # noqa: BLE001
        _raw.pop(name, None)
        log.warning(f"machine sample {name}: {e}")


def _sampler():
    """Arrakis and every managed host, each in its own thread, every 5 s."""
    tick = 0
    while True:
        started = time.time()
        try:
            hosts = [None, *orbhost.managed()]
        except Exception as e:  # noqa: BLE001
            log.warning(f"machine sampler hosts: {e}")
            hosts = [None]
        passes = [orbhost.Thread(target=_sample_host, args=(h, tick), daemon=True) for h in hosts]
        for t in passes:
            t.start()
        for t in passes:
            t.join(timeout=12)
        tick += 1
        time.sleep(max(0.5, HISTORY_EVERY - (time.time() - started)))


def _sample_host(h, tick):
    orbhost.current.set(h)
    try:
        machines, cfg = _build_list() if tick % 2 == 0 else _get_list(max_age=LIST_MAX_AGE)
        running = [m["name"] for m in machines if m["state"] == "running"]
        threads = [orbhost.Thread(target=_sample_one, args=(n, cfg), daemon=True) for n in running]
        if tick % 6 == 0:
            threads += [orbhost.Thread(target=_collect_workloads, args=(n,), daemon=True) for n in running]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        with _history_lock:
            for name in list(_workloads):
                if name not in running:
                    _workloads.pop(name, None)
            for name in list(_history):
                if name not in running:
                    _history.pop(name, None)
                    _latest.pop(name, None)
                    _raw.pop(name, None)
    except Exception as e:  # noqa: BLE001
        log.warning(f"machine sampler{' ' + h if h else ''}: {e}")


def _ensure_sampler():
    global _sampler_started
    with _history_lock:
        if _sampler_started:
            return
        _sampler_started = True
    orbhost.Thread(target=_sampler, name="machine-sampler", daemon=True).start()
    threading.Thread(target=_direct_keeper, name="tailscale-direct", daemon=True).start()


READ_EP = ("grep -h -o 'TS_DEBUG_PRETENDPOINT=[0-9.]*:[0-9]*' /etc/conf.d/tailscale /etc/default/tailscaled "
           "2>/dev/null | head -n 1 | cut -d= -f2")


def _direct_refresh():
    """Machines with a direct path whose Mac has a new LAN address: advertise the new one
    (same port). A stale address doesn't break anything, it just falls back to the relay."""
    for hid in [None, *orbhost.managed()]:
        token = orbhost.current.set(hid)
        try:
            lan = _mac_lan_ip()
            if not lan:
                continue
            machines, _ = _get_list()
            for m in machines:
                if m.get("state") != 'running' or (m.get("tailscale") or {}).get("state") != 'running':
                    continue
                code, out, _ = _run(["orb", "-m", m["name"], "sh", "-c", READ_EP], timeout=20)
                ep = out.strip()
                if code or ':' not in ep or ep.split(':')[0] == lan:
                    continue
                port = ep.split(':')[1]
                script = DIRECT_TS.replace('@PORT@', port).replace('@EP@', lan)
                code, out, err = _run(["orb", "-m", m["name"], "sudo", "sh", "-c", script], timeout=60)
                log.info(f"tailscale direct path {orbhost.key(m['name'])}: {ep} -> {lan}:{port} ({'ok' if code == 0 else err[-200:]})")
        except Exception as e:  # noqa: BLE001
            log.warning(f"tailscale direct path check on {hid or 'arrakis'}: {e}")
        finally:
            orbhost.current.reset(token)


def _direct_keeper():
    time.sleep(60)                       # let the hosts' agents connect first
    while True:
        _direct_refresh()
        time.sleep(600)


_ensure_sampler()


@vms_bp.route('/usage', methods=['GET'])
def machines_usage():
    """Latest background sample of every running machine (no extra work per call)."""
    with _history_lock:
        latest = {name: {"t": d["at"], "cpu": d["cpu_pct"], "mem": d["mem_bytes"], "memLimit": d["mem_limit_bytes"], "up": d["uptime_secs"]} for name, d in _latest.items()}
    for name, w in list(_workloads.items()):
        latest.setdefault(name, {})["runs"] = {
            "containers": len(w["docker"]) if w["docker"] is not None else None,
            "containers_running": sum(1 for c in w["docker"] or [] if c["state"] == "running"),
            "services": sum(1 for u in w["services"] if not u["base"]),
        }
    return jsonify({"status": "success", "data": {"every": HISTORY_EVERY, "machines": latest}})


@vms_bp.route('/<name>/stats', methods=['GET'])
def machine_stats(name):
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    with _history_lock:
        cached = _latest.get(name)
    if cached and time.time() - cached["at"] < 3 * HISTORY_EVERY:
        return jsonify({"status": "success", "data": cached})
    try:
        # not sampled yet (just started): read it now
        _, d = _sample(name, _get_list()[1])
        return jsonify({"status": "success", "data": d})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/<name>/workloads', methods=['GET'])
def machine_workloads(name):
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    w = _workloads.get(name)
    if not w or time.time() - w["at"] > 120:
        _collect_workloads(name)
        w = _workloads.get(name)
    if not w:
        return jsonify({"status": "error", "message": "machine not reachable"})
    return jsonify({"status": "success", "data": w})


@vms_bp.route('/<name>/history', methods=['GET'])
def machine_history(name):
    # memory holds the hour since the backend started (or since the machine last looked
    # stopped); metrics.db fills in whatever came before that
    with _history_lock:
        pts = list(_history.get(name, []))
    since = time.time() - HISTORY_EVERY * HISTORY_KEEP
    first = pts[0]["t"] if pts else float('inf')
    older = [p for p in get_machine_history(orbhost.host() or 'arrakis', name, since) if p["t"] < first - 1]
    return jsonify({"status": "success", "data": {"every": HISTORY_EVERY, "points": older + pts}})


@vms_bp.route('/<name>/rename', methods=['POST'])
def rename_vm(name):
    """Rename a machine. Renaming the dashboard's own machine also saves the new name for
    the dashboard and restarts it, since that name is read once at startup."""
    body = request.get_json(silent=True) or {}
    new = (body.get('new_name') or body.get('name') or '').strip().lower()
    if not NAME_RE.match(new):
        return jsonify({"status": "error", "message": "Use lowercase letters, digits and dashes (start with a letter or digit)"}), 400
    if new == name:
        return jsonify({"status": "error", "message": "That's already its name"}), 400
    machines, _ = _get_list(max_age=0)
    names = {m["name"] for m in machines}
    if name not in names:
        return jsonify({"status": "error", "message": f"No machine called {name}"}), 404
    if new in names:
        return jsonify({"status": "error", "message": f"A machine called {new} already exists"}), 409
    code, out, err = _run(["orb", "rename", name, new], timeout=60)
    if code != 0:
        return jsonify({"status": "error", "message": err or out or "orb rename failed"}), 500
    try:
        cftunnel.rename(name, new, machine_running=any(m["name"] == name and m["state"] == "running" for m in machines))
    except Exception as e:  # noqa: BLE001
        log.warning(f"moving share {name} -> {new}: {e}")
    with _history_lock:
        for d in (_history, _latest, _raw, _workloads):
            if name in d:
                d[new] = d.pop(name)
    rename_machine_metrics(orbhost.host() or 'arrakis', name, new)
    _invalidate_list()
    restarting = name == VM_NAME and orbhost.host() is None
    if restarting:
        from app.core.config import VM_FILE
        fd = os.open(VM_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump({"vm_name": new}, f)
        import signal
        threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGTERM)).start()
        log.info(f"dashboard machine renamed {name} -> {new}; restarting to pick it up")
    return jsonify({"status": "success", "data": {"name": new, "dashboard_restarting": restarting}})


@vms_bp.route('/<name>/<action>', methods=['POST'])
def machine_action(name, action):
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    if action not in ('start', 'stop', 'restart', 'delete'):
        return jsonify({"status": "error", "message": "Unknown action"})
    try:
        if action == 'delete':
            _ts_logout_before_delete(name)
            cftunnel.unshare(name, machine_running=False)
        args = ["orb", "delete", "-f", name] if action == 'delete' else ["orb", action, name]
        code, out, err = _run(args, timeout=180)
        _invalidate_list(name)
        if code != 0:
            return jsonify({"status": "error", "message": err or out or f"orb {action} failed"})
        return jsonify({"status": "success", "stdout": out})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('', methods=['POST'])
@vms_bp.route('/', methods=['POST'])
def create_vm():
    """Start creating a machine; creation downloads an image, so it runs in the background
    and shows up under `jobs` in GET /api/vms until it finishes."""
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    distro = (body.get('distro') or '').strip()
    version = (body.get('version') or '').strip()
    arch = (body.get('arch') or '').strip()
    cpus, mem = _int(body.get('cpu')), _int(body.get('memory_mib'))
    join_ts = bool(body.get('tailscale'))
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "Name: lowercase letters, digits and dashes only"})
    if join_ts and not _ts_key():
        return jsonify({"status": "error", "message": "Set a Tailscale auth key in Settings first"})
    imgs = _images()
    d = next((x for x in imgs["distros"] if x["distro"] == distro), None)
    if not d:
        return jsonify({"status": "error", "message": "Unknown distro"})
    if version and version not in [v["id"] for v in d["versions"]]:
        return jsonify({"status": "error", "message": "Unknown version"})
    if arch and arch not in ARCHES:
        return jsonify({"status": "error", "message": "Unknown architecture"})
    host = _host()
    if cpus and not (1 <= cpus <= host["cores"]):
        return jsonify({"status": "error", "message": f"cpu must be 1..{host['cores']}"})
    if mem and not (MIN_MACHINE_MEMORY_MIB <= mem <= host["memory_mib"]):
        return jsonify({"status": "error", "message": "memory_mib must be at least 1024 (OrbStack's minimum)"})
    with _jobs_lock:
        if name in _jobs and _jobs[name]["state"] == "creating":
            return jsonify({"status": "error", "message": "That machine is already being created"})
        _jobs[name] = {"kind": "create", "state": "creating", "message": "", "started": time.time()}
    args = ["orb", "create"]
    if arch:
        args += ["-a", arch]
    if cpus:
        args += ["--cpus", str(cpus)]
    if mem:
        args += ["--memory", str(mem)]
    args += [f"{distro}:{version}" if version else distro, name]
    orbhost.Thread(target=_create_job, args=(name, args, join_ts), daemon=True).start()
    log.info(f"orb create started: {' '.join(args)}")
    return jsonify({"status": "success", "message": f"Creating {name}…"})


@vms_bp.route('/jobs/<name>', methods=['DELETE'])
def dismiss_job(name):
    with _jobs_lock:
        _jobs.pop(name, None)
    return jsonify({"status": "success"})


@vms_bp.route('/tailscale/key', methods=['GET'])
def ts_key_get():
    key = _ts_key()
    return jsonify({"status": "success", "data": {"set": bool(key), "hint": key[-4:] if key else ""}})


@vms_bp.route('/tailscale/key', methods=['PUT'])
def ts_key_put():
    key = ((request.get_json(silent=True) or {}).get('auth_key') or '').strip()
    if not key.startswith('tskey-'):
        return jsonify({"status": "error", "message": "That doesn't look like a Tailscale auth key (tskey-…)"})
    try:
        _ts_save_key(key)
        return jsonify({"status": "success"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/tailscale/key', methods=['DELETE'])
def ts_key_delete():
    try:
        if os.path.exists(TS_KEY_FILE):
            os.remove(TS_KEY_FILE)
        return jsonify({"status": "success"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


# ---- cloudflare api token (for public SSH sharing; stored like the Tailscale key, never returned) ----

@vms_bp.route('/cloudflare/token', methods=['GET'])
def cf_token_get():
    tok = cftunnel._token()
    data = {"set": bool(tok), "hint": tok[-4:] if tok else "", "domain": cftunnel.domain(),
            "domain_locked": bool(cftunnel.shares()) or bool(os.environ.get("HOMELAB_SHARE_DOMAIN")), "zones": []}
    if tok:
        try:
            data["zones"] = cftunnel.zones()
        except Exception as e:  # noqa: BLE001
            data["zones_error"] = str(e)
    return jsonify({"status": "success", "data": data})


@vms_bp.route('/cloudflare/domain', methods=['PUT'])
def cf_domain_put():
    """Pick which of the token's zones shared machines are named under (only while nothing is shared)."""
    try:
        cftunnel.set_domain((request.get_json(silent=True) or {}).get('domain'))
        _invalidate_list()
        return jsonify({"status": "success", "domain": cftunnel.domain()})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/sharing/presets', methods=['POST'])
def preset_save():
    """Save your own permission preset: label, desc, perms, expires_days (0 = never)."""
    b = request.get_json(silent=True) or {}
    try:
        pid = cftunnel.save_preset(b.get('label'), b.get('desc'), b.get('perms'), b.get('expires_days') or 0)
        _invalidate_list()
        return jsonify({"status": "success", "id": pid})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/sharing/presets/<pid>', methods=['DELETE'])
def preset_delete(pid):
    """Delete one of your own presets (people already using it keep their permissions)."""
    try:
        cftunnel.delete_preset(pid)
        _invalidate_list()
        return jsonify({"status": "success"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/cloudflare/token', methods=['PUT'])
def cf_token_put():
    tok = ((request.get_json(silent=True) or {}).get('api_token') or '').strip()
    if len(tok) < 30 or ' ' in tok:
        return jsonify({"status": "error", "message": "That doesn't look like a Cloudflare API token"})
    # check it with Cloudflare before replacing a working one
    try:
        req = urllib.request.Request("https://api.cloudflare.com/client/v4/user/tokens/verify",
                                     headers={"Authorization": f"Bearer {tok}", "User-Agent": "arrakis-dashboard"})
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = json.load(r).get("success")
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        return jsonify({"status": "error", "message": "Cloudflare rejected that token"})
    try:
        cftunnel._write_token_file({**cftunnel._token_file(), "api_token": tok})  # keeps the chosen domain
        cftunnel._ids.clear()  # zone/account ids may differ for the new token
        return jsonify({"status": "success"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/cloudflare/token', methods=['DELETE'])
def cf_token_delete():
    try:
        if os.path.exists(cftunnel.TOKEN_FILE):
            os.remove(cftunnel.TOKEN_FILE)
        cftunnel._ids.clear()
        return jsonify({"status": "success"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/<name>/tailscale/join', methods=['POST'])
def ts_join(name):
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    if not _ts_key():
        return jsonify({"status": "error", "message": "Set a Tailscale auth key in Settings first"})
    with _jobs_lock:
        if name in _jobs and _jobs[name]["state"] == "creating":
            return jsonify({"status": "error", "message": "That machine is busy"})
        _jobs[name] = {"kind": "tailscale", "state": "creating", "message": "", "started": time.time()}
    orbhost.Thread(target=_ts_job, args=(name,), daemon=True).start()
    return jsonify({"status": "success", "message": f"Joining {name} to Tailscale…"})


@vms_bp.route('/<name>/tailscale/leave', methods=['POST'])
def ts_leave(name):
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    try:
        code, out, err = _run(["orb", "-m", name, "sudo", "tailscale", "logout"], timeout=60)
        _invalidate_list(name)
        if code != 0:
            return jsonify({"status": "error", "message": err or out or "tailscale logout failed"})
        return jsonify({"status": "success"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


# ---- public sharing (Cloudflare Tunnel) ----------------------------------------------

def _share_job(name, username, keys):
    try:
        _ensure_isolated(name)
        cftunnel.share(name, username, keys)
        state, message = "done", ""
    except Exception as e:  # noqa: BLE001
        state, message = "error", str(e)
    with _jobs_lock:
        _jobs[name] = {"kind": "share", "state": state, "message": message, "started": _jobs[name]["started"]}
    _invalidate_list(name)
    log.info(f"share {name}: {state} {message}")


@vms_bp.route('/<name>/share', methods=['PUT'])
def share_vm(name):
    """Share a running machine over SSH at <name>.<domain>, or add keys to an existing share.
    Installing sshd can take a while, so it runs as a background job."""
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    if not cftunnel.logged_in():
        return jsonify({"status": "error", "message": "Save a Cloudflare API token in ~/.homelab_cloudflare.json first"})
    machines, _ = _get_list()
    m = next((x for x in machines if x["name"] == name), None)
    if not m:
        return jsonify({"status": "error", "message": f"No machine called {name}"}), 404
    if m["state"] != "running":
        return jsonify({"status": "error", "message": "Start the machine to share it"})
    keys = (request.get_json(silent=True) or {}).get('keys') or ''
    try:
        cftunnel._clean_keys(keys)
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)})
    with _jobs_lock:
        if name in _jobs and _jobs[name]["state"] == "creating":
            return jsonify({"status": "error", "message": "That machine is busy"})
        _jobs[name] = {"kind": "share", "state": "creating", "message": "", "started": time.time()}
    orbhost.Thread(target=_share_job, args=(name, m.get("username"), keys), daemon=True).start()
    return jsonify({"status": "success", "message": f"Sharing {name}…"})


@vms_bp.route('/<name>/share/keys', methods=['DELETE'])
def share_remove_key(name):
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    fp = ((request.get_json(silent=True) or {}).get('fp') or request.args.get('fp') or '').strip()
    try:
        cftunnel.remove_key(name, fp)
        _invalidate_list(name)
        return jsonify({"status": "success"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/<name>/share/keys', methods=['POST'])
def share_add_key(name):
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    body = request.get_json(silent=True) or {}
    try:
        m = next((x for x in _get_list()[0] if x["name"] == name), None)
        if m and not m.get("isolated"):
            return jsonify({"status": "error", "message": "This machine can see the Mac's files. Turn on isolation in Settings and restart it before adding people"})
        res = cftunnel.add_key(name, body.get('key') or '', body.get('label') or '', body.get('perms'), body.get('username') or '')
        _invalidate_list(name)
        return jsonify({"status": "success", **res})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/<name>/share/keys', methods=['PATCH'])
def share_label_key(name):
    body = request.get_json(silent=True) or {}
    try:
        cftunnel.label_key(name, (body.get('fp') or '').strip(), body.get('label') or '')
        _invalidate_list(name)
        return jsonify({"status": "success"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/<name>/share/keys/perms', methods=['PUT'])
def share_key_perms(name):
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    body = request.get_json(silent=True) or {}
    try:
        perms = cftunnel.set_perms(name, (body.get('fp') or '').strip(), body.get('perms'))
        _invalidate_list(name)
        return jsonify({"status": "success", "perms": perms})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@vms_bp.route('/<name>/share', methods=['DELETE'])
def unshare_vm(name):
    if not NAME_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    try:
        machines, _ = _get_list()
        running = any(x["name"] == name and x["state"] == "running" for x in machines)
        if not cftunnel.unshare(name, machine_running=running):
            return jsonify({"status": "error", "message": f"{name} isn't shared"})
        _invalidate_list(name)
        return jsonify({"status": "success"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})
