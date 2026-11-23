"""Where a tmux session lives, from its name.

Session names are "<where>:<session>": "mac" is the Mac, a registered host id is
that host over SSH ("giedi-pi:work"), anything else is an OrbStack machine by name
("sietch:work"). "vm:" is kept as an alias for the dashboard's own machine, for older links.
"""
import getpass
import json
import re
import subprocess
import sys
import time

from app.core.config import VM_NAME

TMUX_MAC = "/opt/homebrew/bin/tmux"
SESSION_RE = re.compile(r'^[a-zA-Z0-9_-]+$')
MACHINE_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')
# the pane fields are the active pane of the session's active window
LIST_FMT = "#{session_name}|#{session_windows}|#{session_created}|#{session_attached}|#{session_activity}|#{pane_current_command}|#{pane_current_path}"

_machines = {"at": 0, "running": []}


def running_machines(max_age=30):
    """Names of running OrbStack machines (cached briefly)."""
    if time.time() - _machines["at"] > max_age:
        try:
            out = subprocess.run(["orb", "list", "-f", "json"], capture_output=True, text=True, timeout=10).stdout
            _machines.update(at=time.time(), running=[m["name"] for m in json.loads(out or "[]") if m.get("state") == "running"])
        except Exception:
            _machines["at"] = time.time()
    return _machines["running"]


# Remote hosts are reached over Tailscale with the Mac's SSH key. The host key is trusted on
# first use (the Tailscale tunnel already authenticates the peer) and pinned in known_hosts.
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=30"]
# ssh joins its remote arguments into one shell string, so quote them first
_SSH_WRAP = ("import os,shlex,sys; i=sys.argv.index('--'); "
             "os.execvp('ssh', ['ssh'] + sys.argv[1:i] + [shlex.join(sys.argv[i+1:])])")


def remote_host(where):
    """(user@ip) for a registered, online host that isn't also an OrbStack machine name; else None."""
    from app.api import hosts
    if where == 'mac' or where in running_machines():
        return None
    h = next((h for h in hosts._load() if h['id'] == where), None)
    if not h:
        return None
    with hosts._lock:
        r = hosts._latest.get(where)
    ip = r and r.get('ip')
    return f"{h.get('ssh_user') or getpass.getuser()}@{ip}" if ip else None


def online_hosts():
    from app.api import hosts
    now = time.time()
    with hosts._lock:
        return [hid for hid, r in hosts._latest.items() if now - r['at'] < hosts.ONLINE_WITHIN and r.get('ip')]


def ssh_cmd(dest, tty=False):
    return [sys.executable, "-c", _SSH_WRAP] + SSH_OPTS + (["-tt"] if tty else []) + [dest, "--"]


def run_on(where, script, root=False, timeout=10):
    """Run a shell snippet on a machine or remote host."""
    dest = remote_host(where)
    if dest:
        cmd = ssh_cmd(dest) + (["sudo", "-n", "sh", "-c", script] if root else ["sh", "-c", script])
    else:
        cmd = ["orb", "-m", where] + (["-u", "root"] if root else []) + ["sh", "-c", script]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def split(name):
    """'casaos:work' -> ('casaos', 'work'); 'vm:x' -> (VM_NAME, 'x'); bad names -> (None, None)."""
    where, sep, session = name.partition(':')
    if not sep or not SESSION_RE.match(session):
        return None, None
    if where == 'vm':
        where = VM_NAME
    if where != 'mac' and not MACHINE_RE.match(where):
        return None, None
    return where, session


def tmux_cmd(where, tty=False):
    """The command prefix that runs tmux on the Mac, inside a machine or on a remote host.
    tty=True for an interactive attach (ssh needs a terminal then)."""
    if where == 'mac':
        return [TMUX_MAC]
    dest = remote_host(where)
    if dest:
        return ssh_cmd(dest, tty) + ["tmux"]
    return ["orb", "-m", where, "tmux"]


_homes = {}


def home(where):
    """Home directory for new sessions (otherwise they start in the dashboard's folder,
    which OrbStack mounts into every machine)."""
    import os
    if where == 'mac':
        return os.path.expanduser('~')
    if where not in _homes:
        try:
            out = run_on(where, "echo $HOME").stdout.strip()
            _homes[where] = out or "/"
        except Exception:
            return "/"
    return _homes[where]


def start_dir(where, cwd=None):
    """A session's starting folder: the given one (~ is that machine's home), else home."""
    cwd = (cwd or '').strip()
    if not cwd:
        return home(where)
    if cwd == '~' or cwd.startswith('~/'):
        cwd = home(where).rstrip('/') + cwd[1:]
    return cwd


def new_session_args(where, session, cwd=None):
    return ["new-session", "-d", "-s", session, "-c", start_dir(where, cwd)]


def has_tmux(where):
    if where == 'mac':
        return True
    return run_on(where, "command -v tmux").returncode == 0


INSTALL_TMUX = "command -v tmux >/dev/null || { if command -v apk >/dev/null; then apk add --no-cache tmux; elif command -v apt-get >/dev/null; then apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tmux; elif command -v dnf >/dev/null; then dnf install -y tmux; elif command -v pacman >/dev/null; then pacman -Sy --noconfirm tmux; else exit 3; fi; }"


def ensure_tmux(where):
    """Install tmux in a machine that lacks it. Returns (ok, message)."""
    if has_tmux(where):
        return True, None
    res = run_on(where, INSTALL_TMUX, root=True, timeout=300)
    if res.returncode != 0 and remote_host(where) and 'password' in res.stderr:
        return False, f"tmux isn't installed on {where}, and installing it needs your sudo password there. Run `sudo apt install tmux` on {where} once."
    if res.returncode != 0:
        return False, f"tmux isn't installed on {where} and installing it failed: {(res.stderr or res.stdout).strip()[-200:]}"
    return True, f"Installed tmux on {where}"


def list_sessions():
    """Sessions on the Mac, on every running machine and on every online remote host."""
    sessions = []
    for where in ['mac'] + running_machines() + [h for h in online_hosts() if h not in running_machines()]:
        try:
            res = subprocess.run(tmux_cmd(where) + ["ls", "-F", LIST_FMT], capture_output=True, text=True, timeout=5)
        except Exception:
            continue
        if res.returncode != 0:
            continue
        for line in res.stdout.strip().split('\n'):
            p = line.split('|')
            if len(p) >= 4:
                sessions.append({"name": f"{where}:{p[0]}", "where": where, "windows": int(p[1]), "created": int(p[2]),
                                 "attached": int(p[3]) > 0, "is_vm": where != 'mac',
                                 "activity": int(p[4]) if len(p) > 4 and p[4].isdigit() else None,
                                 "command": p[5] if len(p) > 5 else None, "path": '|'.join(p[6:]) if len(p) > 6 else None})
    return sessions
