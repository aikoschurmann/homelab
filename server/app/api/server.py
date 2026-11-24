"""/api/server: who this server is (name, port, OS), what it has installed, and the
first-run setup that names it. The UI reads this once at load; everywhere it says the
server's name comes from here."""
import json
import os
import platform
import socket
import subprocess

from flask import Blueprint, jsonify, request

from app.core import paths, server_cfg
from app.core.logger import log

server_bp = Blueprint('server', __name__)


def _machine_info():
    """OrbStack machines with what setup shows next to each: distro, version, running or not."""
    try:
        out = subprocess.run(["orb", "list", "-f", "json"], capture_output=True, text=True, timeout=10).stdout
        return [{"name": m["name"], "state": m.get("state") or "",
                 "distro": (m.get("image") or {}).get("distro") or "",
                 "version": (m.get("image") or {}).get("version") or ""}
                for m in json.loads(out or "[]") if m.get("name")]
    except Exception:
        return []


def _machines():
    return [m["name"] for m in _machine_info()]


def _port_free(port):
    """True when nothing else listens on the port (the dashboard's own port counts as free)."""
    if port == server_cfg.port():
        return True
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _info():
    from app.core.config import VM_NAME
    cfg = server_cfg.load()
    feats = server_cfg.features()
    info = _machine_info() if feats["orbstack"] else []
    return {
        **cfg,
        "port_active": server_cfg.port(),
        "hostname": socket.gethostname(),
        "os": {"Darwin": "macOS"}.get(platform.system(), platform.system()),
        "features": feats,
        "vm_name": VM_NAME if feats["orbstack"] else None,
        "machines": [m["name"] for m in info],
        "machine_info": info,
        "home": paths.HOME,
    }


@server_bp.route('', methods=['GET'])
def get_server():
    return jsonify({"status": "success", "data": _info()})


@server_bp.route('/port', methods=['GET'])
def check_port():
    try:
        port = int(request.args.get("port", ""))
    except ValueError:
        return jsonify({"status": "error", "message": "Not a port"}), 400
    ok = 1024 <= port <= 65535
    return jsonify({"status": "success", "data": {"port": port, "valid": ok, "free": ok and _port_free(port)}})


@server_bp.route('', methods=['PATCH'])
def patch_server():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if name is not None:
        name = str(name).strip()
        if not (1 <= len(name) <= 40) or any(c in name for c in '<>"/\\'):
            return jsonify({"status": "error", "message": "Name must be 1-40 characters, without < > \" / \\"}), 400
    port = body.get("port")
    if port is not None:
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 0
        if not 1024 <= port <= 65535:
            return jsonify({"status": "error", "message": "Port must be between 1024 and 65535"}), 400
        if not _port_free(port):
            return jsonify({"status": "error", "message": f"Port {port} is already in use on this computer"}), 400
    vm = body.get("vm_name")
    restart = False
    if vm == "":                                  # explicitly none (no OrbStack machine yet)
        vm = None
    if vm:
        from app.core.config import VM_FILE, VM_NAME
        if vm not in _machines():
            return jsonify({"status": "error", "message": f"No OrbStack machine called {vm}"}), 400
        if vm != VM_NAME:
            fd = os.open(VM_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"vm_name": vm}, f)
            restart = True
    before = server_cfg.load()
    cfg = server_cfg.save(name=name, port=port,
                          setup_done=True if body.get("setup_done") else None)
    restart = restart or cfg["port"] != before["port"]
    log.info(f"server settings: name={cfg['name']} port={cfg['port']} setup_done={cfg['setup_done']}")
    # the VM name and port are read at startup: under launchd/systemd (KeepAlive / Restart=)
    # exiting is a restart, as when the dashboard machine is renamed (vms.py)
    restarting = restart and _supervised()
    if restarting:
        import signal, threading
        threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGTERM)).start()
        log.info("restarting to apply the new port / main machine")
    return jsonify({"status": "success", "data": {**_info(), "restart_needed": restart and not restarting, "restarting": restarting}})


def _supervised():
    return os.environ.get("XPC_SERVICE_NAME", "").startswith("com.homelab.") or bool(os.environ.get("INVOCATION_ID"))
