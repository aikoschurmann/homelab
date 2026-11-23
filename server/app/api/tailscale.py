"""The Mac's view of the tailnet: every device, how it is reached, and traffic.

Reads `tailscale status --json` (cached for a few seconds) and normalises it.
Pinging a device runs `tailscale ping`, which also tells whether the path is
direct or relayed through a DERP server.
"""
from flask import Blueprint, jsonify
import ipaddress
import json
import re
import subprocess
import threading
import time

from app.core.logger import log

tailscale_bp = Blueprint('tailscale', __name__)

CACHE_SECONDS = 5
_cache = {"at": 0, "data": None}
_lock = threading.Lock()


def _ts(*args, timeout=10):
    res = subprocess.run(["tailscale", *args], capture_output=True, text=True, timeout=timeout)
    return res.returncode, res.stdout, res.stderr.strip()


def _node(n, users, is_self=False):
    ips = n.get('TailscaleIPs') or []
    v4 = next((ip for ip in ips if ':' not in ip), None)
    cur = n.get('CurAddr') or ''
    relay = n.get('Relay') or ''
    online = bool(n.get('Online')) or is_self
    user = users.get(str(n.get('UserID'))) or {}
    return {
        "id": n.get('ID'),
        "name": (n.get('DNSName') or '').split('.')[0] or n.get('HostName'),
        "hostname": n.get('HostName'),
        "dns": (n.get('DNSName') or '').rstrip('.'),
        "os": n.get('OS') or '',
        "ip": v4,
        "ipv6": next((ip for ip in ips if ':' in ip), None),
        "online": online,
        # active = traffic in the last few minutes; online but quiet = idle
        "state": "active" if online and (n.get('Active') or is_self) else "idle" if online else "offline",
        "self": is_self,
        # only a peer with a live session has a path: direct when a peer-to-peer address is in
        # use, else relayed via DERP. An idle peer has no CurAddr simply because nothing is open.
        "connection": ("direct" if cur else "relay") if online and n.get('Active') and not is_self else None,
        "endpoint": cur or None,
        "relay": relay or None,
        "rx_bytes": n.get('RxBytes') or 0,
        "tx_bytes": n.get('TxBytes') or 0,
        "last_seen": n.get('LastSeen') if not online and not (n.get('LastSeen') or '').startswith('0001') else None,
        "last_handshake": None if (n.get('LastHandshake') or '').startswith('0001') else n.get('LastHandshake'),
        "created": n.get('Created'),
        "key_expiry": n.get('KeyExpiry'),
        "tags": n.get('Tags') or [],
        "exit_node": bool(n.get('ExitNode')),
        "exit_node_option": bool(n.get('ExitNodeOption')),
        "user": user.get('LoginName') or user.get('DisplayName'),
    }


def _status():
    with _lock:
        if _cache["data"] and time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["data"]
    code, out, err = _ts("status", "--json")
    if code != 0 and not out:
        raise RuntimeError(err or "tailscale status failed")
    d = json.loads(out)
    users = {str(k): v for k, v in (d.get('User') or {}).items()}
    me = _node(d.get('Self') or {}, users, is_self=True)
    peers = [_node(p, users) for p in (d.get('Peer') or {}).values()]
    order = {"active": 0, "idle": 1, "offline": 2}
    peers.sort(key=lambda p: (order[p["state"]], p["name"] or ""))
    data = {
        "backend_state": d.get('BackendState'),
        "version": (d.get('Version') or '').split('-')[0],
        "tailnet": (d.get('CurrentTailnet') or {}).get('Name'),
        "magic_dns": d.get('MagicDNSSuffix'),
        "health": d.get('Health') or [],
        "self": me,
        "devices": [me] + peers,
    }
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data


@tailscale_bp.route('', methods=['GET'])
@tailscale_bp.route('/', methods=['GET'])
def status():
    try:
        return jsonify({"status": "success", "data": _status()})
    except Exception as e:  # noqa: BLE001
        log.warning(f"tailscale status: {e}")
        return jsonify({"status": "error", "message": str(e)})


# the time is a Go duration: "12ms", "523µs", "1.2s", or "0s" for a very fast LAN reply
PONG_RE = re.compile(r'pong from \S+ \((\S+)\) via (.+?) in ([0-9.]+)(µs|us|ms|s)\b')
_TO_MS = {"µs": 0.001, "us": 0.001, "ms": 1, "s": 1000}


@tailscale_bp.route('/ping/<ip>', methods=['POST'])
def ping(ip):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return jsonify({"status": "error", "message": "not an IP address"})
    try:
        code, out, err = _ts("ping", "-c", "4", "--timeout", "3s", ip, timeout=20)
        pongs = [{"via": m.group(2), "ms": round(float(m.group(3)) * _TO_MS[m.group(4)], 2)} for m in PONG_RE.finditer(out)]
        if not pongs:
            return jsonify({"status": "error", "message": (out or err).strip().splitlines()[-1] if (out or err) else "no reply"})
        last = pongs[-1]["via"]
        return jsonify({"status": "success", "data": {
            "pongs": pongs,
            "best_ms": min(p["ms"] for p in pongs),
            "path": "relay" if last.startswith("DERP") else "direct",
            "via": last,
            "note": "direct connection not established" in out and "Relayed: no direct path yet" or None,
        }})
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "timed out"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})
