"""Who may use the dashboard, and how.

Everyone is identified by Tailscale (no passwords): this Mac and the owner's own devices
are the owner (full access). Anyone else on the tailnet, someone a device was shared with
or another member, is refused unless the owner gave their Tailscale login a role here:

    viewer   sees everything, changes nothing (GET only; no terminal, no backup downloads)
    admin    full access, except changing who has access (the owner's alone)

Kept in $HOMELAB_HOME/access.json: {"people": {"login": "viewer" | "admin"}}.
"""
import json, os, subprocess, threading, time

from app.core import paths
from app.core.logger import log

FILE = paths.state('access')
ROLES = ('viewer', 'admin')
_lock = threading.Lock()
_whois = {}          # ip -> (time, {"login", "name"} | None)


def load():
    try:
        with open(FILE) as f:
            people = json.load(f).get('people') or {}
        return {k: v for k, v in people.items() if v in ROLES}
    except (OSError, ValueError, AttributeError):
        return {}


def set_role(login, role):
    with _lock:
        people = load()
        if role in ROLES:
            people[login] = role
        else:
            people.pop(login, None)
        tmp = FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({"people": people}, f, indent=1)
        os.replace(tmp, FILE)
    _whois.clear()


def whois(ip):
    """{"login", "name"} of the Tailscale user behind an address, cached for a minute."""
    hit = _whois.get(ip)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    who = None
    try:
        out = subprocess.run(['tailscale', 'whois', '--json', ip], capture_output=True, text=True, timeout=5).stdout
        u = (json.loads(out or '{}').get('UserProfile') or {})
        if u.get('LoginName'):
            who = {"login": u['LoginName'], "name": u.get('DisplayName') or u['LoginName']}
    except Exception as e:
        log.warning(f"tailscale whois {ip}: {e}")
    if len(_whois) > 500:
        _whois.clear()
    _whois[ip] = (time.time(), who)
    return who


def role_of(ip):
    """(role, who) for someone who isn't the owner, or (None, who) when they have no access."""
    who = whois(ip)
    if not who:
        return None, None
    return load().get(who['login']), who


# what a viewer may not do even with GET: open a shell, or take secrets home
VIEWER_BLOCKED = ('/api/term', '/terminal', '/api/backups/file/', '/api/hosts/install.sh', '/api/access')


def viewer_allowed(method, path):
    if method not in ('GET', 'HEAD', 'OPTIONS'):
        return False
    if '/download' in path and path.startswith('/api/backups/'):
        return False
    return not any(path.startswith(p) for p in VIEWER_BLOCKED) or path == '/api/access/me'
