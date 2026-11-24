"""This server's identity: what it is called, which port it serves on, and whether the
first-run setup has been done. Stored in $HOMELAB_HOME/server.json.

  name        shown everywhere the UI talks about "this server" (default: the hostname)
  port        HTTP port (HOMELAB_PORT overrides; a change applies on restart)
  setup_done  false until the setup screen is finished; installs that predate this file
              (they already have prefs) count as set up
"""
import json
import os
import platform
import shutil
import socket
import threading

from app.core import paths

FILE = os.path.join(paths.HOME, "server.json")
DEFAULT_PORT = 5050
_lock = threading.Lock()


def _default_name():
    host = socket.gethostname().split(".")[0] or "homelab"
    return host[:1].upper() + host[1:]


def load():
    try:
        with open(FILE) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    existing_install = os.path.exists(os.path.join(paths.HOME, "prefs.json")) or \
        (paths.ADOPT_LEGACY and os.path.exists(os.path.join(paths.LEGACY_HOME, ".homelab_prefs.json")))
    return {
        "name": (cfg.get("name") or "").strip() or _default_name(),
        "port": int(cfg.get("port") or DEFAULT_PORT),
        "setup_done": bool(cfg.get("setup_done", existing_install)),
    }


def save(**changes):
    with _lock:
        cfg = load()
        cfg.update({k: v for k, v in changes.items() if v is not None})
        tmp = FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, FILE)
        return cfg


def name():
    return load()["name"]


def port():
    return int(os.environ.get("HOMELAB_PORT") or load()["port"])


def features():
    """What this machine has, so the UI can leave out pages for tools that aren't installed."""
    return {
        "orbstack": bool(shutil.which("orb")),
        "tailscale": bool(shutil.which("tailscale")) or os.path.exists("/Applications/Tailscale.app"),
        "cloudflared": bool(shutil.which("cloudflared")),
        "docker": bool(shutil.which("docker")),
        "tmux": bool(shutil.which("tmux")),
        "launchd": platform.system() == "Darwin",
        "systemd": os.path.isdir("/run/systemd/system"),
    }
