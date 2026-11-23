"""Share OrbStack machines over SSH through Cloudflare Tunnels.

Only machines that were shared explicitly get a public hostname (<name>.<domain>). Each
shared machine gets its own remotely managed tunnel (vm-<name>) whose connector runs inside
the machine and forwards to the machine's own localhost:22, so nothing depends on the Mac
reaching the machine network, and sharing or unsharing one machine leaves the others alone.
Unsharing deletes the tunnel and its DNS record, so access ends even if the machine is stopped.

Everything on Cloudflare's side goes through the API with the token in
~/.homelab_cloudflare.json (Account: Cloudflare Tunnel Edit, Zone: DNS Edit). State (which
machines are shared, their tunnel ids and the keys added) lives in ~/.homelab_shares.json.

Machines on other hosts (orbhost.current set) are shared the same way: state is keyed
'<host>:<name>' and the hostname is <name>-<host>.<domain>, since Universal SSL only
covers one level of subdomain.
"""
import base64
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request

from app.core import orbhost
from app.core.logger import log

DEFAULT_DOMAIN = "aikoschurmann.com"
TOKEN_FILE = os.path.expanduser("~/.homelab_cloudflare.json")  # never sent to the browser
STATE_FILE = os.path.expanduser("~/.homelab_shares.json")
REMOTE_DIR = "/etc/cloudflared/share"

_lock = threading.RLock()
_ids = {}  # cached zone/account ids


def _token():
    try:
        with open(TOKEN_FILE) as f:
            return (json.load(f).get("api_token") or "").strip()
    except (OSError, ValueError):
        return ""


def logged_in():
    return bool(_token())


def _token_file():
    try:
        with open(TOKEN_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_token_file(data):
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)


def domain():
    """The zone shared machines get their names under: env var, then the saved choice."""
    return os.environ.get("HOMELAB_SHARE_DOMAIN") or _token_file().get("domain") or DEFAULT_DOMAIN


def zones():
    """Zone names the saved token can see, for picking the domain."""
    return sorted(z["name"] for z in _cf("GET", "/zones?per_page=50&status=active") or [])


def set_domain(name):
    name = (name or "").strip().lower().rstrip(".")
    if os.environ.get("HOMELAB_SHARE_DOMAIN"):
        raise ValueError("HOMELAB_SHARE_DOMAIN is set in the dashboard's environment; it wins over this setting")
    if shares():
        raise ValueError("Stop sharing every machine first: their addresses are under the current domain")
    if name not in zones():
        raise ValueError(f"The Cloudflare token can't manage {name or 'that domain'}")
    data = _token_file()
    data["domain"] = name
    _write_token_file(data)
    _ids.clear()


def hostname(name):
    h = orbhost.host()
    d = domain()
    return f"{name}.{d}" if h is None else f"{name}-{h}.{d}"


def _tunnel_name(name):
    h = orbhost.host()
    return f"vm-{name}" if h is None else f"vm-{name}-{h}"


K = orbhost.key  # a machine's key in the state file and caches


# ---- state -----------------------------------------------------------------------

def _load():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"shares": {}}


def _save(state):
    fd = os.open(STATE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)


def shares():
    """name -> {"hostname", "since", "keys", "user", "tunnel_id"} for every shared machine."""
    return _load().get("shares", {})


def _fingerprint(key):
    """SHA256 fingerprint as ssh-keygen -l prints it."""
    try:
        blob = base64.b64decode(key.split()[1])
    except Exception:  # noqa: BLE001
        return ""
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def _key_info(key):
    parts = key.split(None, 2)
    return {"fp": _fingerprint(key), "type": parts[0].removeprefix("ssh-"), "comment": parts[2] if len(parts) > 2 else ""}


# sshd logs "Accepted publickey for <user> from … ssh2: <TYPE> SHA256:<fp>" for every login;
# syslog (Alpine, Debian's auth.log, Fedora's secure) or the journal on systemd machines.
# Not filtered by user: every key now has its own login user, and the fingerprint alone
# identifies the key, so one read covers them all.
LOGINS_SH = r"""
echo "Z $(date +%z)"
command -v docker >/dev/null && echo "D docker"
grep -h "Accepted publickey for " /var/log/messages /var/log/auth.log /var/log/secure 2>/dev/null | sed 's/^/S /'
command -v journalctl >/dev/null && journalctl -q --no-pager -o short-iso -g "Accepted publickey for " 2>/dev/null | sed 's/^/J /'
true
"""
_logins_cache = {}  # name -> (ts, {fp: last login epoch})
_has_docker = {}  # name -> bool, read along with the logins


def _last_logins(name, max_age=30):
    hit = _logins_cache.get(K(name))
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    out = {}
    _has_docker[K(name)] = False
    try:
        _, stdout, _ = orbhost.run(["-m", name, "-u", "root", "sh", "-c", LOGINS_SH], timeout=10)
        now = time.time()
        tz = None
        for line in stdout.splitlines():
            if line.startswith("D "):
                _has_docker[K(name)] = True
                continue
            if line.startswith("Z "):
                tz = datetime.strptime(line[2:].strip(), "%z").tzinfo
                continue
            fp = line.rsplit(" ", 1)[-1]
            if not fp.startswith("SHA256:"):
                continue
            try:
                if line.startswith("J "):
                    t = datetime.fromisoformat(line.split()[1]).timestamp()
                else:  # "Nov 21 12:15:55" carries no year
                    d = datetime.strptime(f"{time.localtime().tm_year} {' '.join(line.split()[1:4])}", "%Y %b %d %H:%M:%S").replace(tzinfo=tz)
                    if d.timestamp() > now + 86400:
                        d = d.replace(year=d.year - 1)
                    t = d.timestamp()
            except ValueError:
                continue
            out[fp] = max(out.get(fp, 0), t)
    except Exception as e:  # noqa: BLE001
        log.warning(f"last logins {name}: {e}")
    _logins_cache[K(name)] = (time.time(), out)
    return out


def share_info(name, running=False):
    """The share as the UI shows it. Last logins are read from the machine's sshd log, so
    only for a running machine (None = unknown)."""
    s = shares().get(K(name))
    if not s:
        return None
    user = s.get("user") or "root"
    logins = _last_logins(name) if running else None
    meta = s.get("key_meta") or {}
    keys = []
    for k in s.get("keys") or []:
        info = _key_info(k)
        m = meta.get(info["fp"]) or {}
        # keys added before per-person users existed have no stored user/level: they fall
        # back to the share's single login user and show no level.
        info.update(label=m.get("label") or "", added=m.get("added"),
                    user=m.get("user") or user, managed=bool(m.get("user")),
                    perms=perms_of(m) if m.get("user") else None, level=m.get("level"),
                    last_login=(logins or {}).get(info["fp"]) if logins is not None else None)
        keys.append(info)
    return {"hostname": s["hostname"], "since": s["since"], "user": user,
            "logins_known": logins is not None, "docker": _has_docker.get(K(name)), "keys": keys}


# ---- Cloudflare API --------------------------------------------------------------

def _cf(method, path, body=None):
    token = _token()
    if not token:
        raise RuntimeError("No Cloudflare API token saved (~/.homelab_cloudflare.json)")
    req = urllib.request.Request(f"https://api.cloudflare.com/client/v4{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            res = json.load(e)
        except ValueError:
            raise RuntimeError(f"Cloudflare {method} {path}: HTTP {e.code}") from None
    if not res.get("success"):
        msg = "; ".join(x.get("message", "") for x in res.get("errors") or []) or "request failed"
        raise RuntimeError(f"Cloudflare: {msg}")
    return res.get("result")


def _zone():
    """(zone id, account id) for the sharing domain."""
    if "zone" not in _ids:
        found = _cf("GET", f"/zones?name={urllib.parse.quote(domain())}")
        if not found:
            raise RuntimeError(f"The API token can't see the zone {domain()}")
        _ids["zone"] = (found[0]["id"], found[0]["account"]["id"])
    return _ids["zone"]


def _create_tunnel(name):
    """Create the machine's tunnel (or reuse one left from an earlier share); returns its id."""
    _, acct = _zone()
    tname = _tunnel_name(name)
    for t in _cf("GET", f"/accounts/{acct}/cfd_tunnel?is_deleted=false&name={urllib.parse.quote(tname)}") or []:
        return t["id"]
    t = _cf("POST", f"/accounts/{acct}/cfd_tunnel", {"name": tname, "config_src": "cloudflare"})
    log.info(f"created tunnel {tname}: {t['id']}")
    return t["id"]


def _tunnel_token(tid):
    _, acct = _zone()
    return _cf("GET", f"/accounts/{acct}/cfd_tunnel/{tid}/token")


def _set_ingress(tid, host):
    _, acct = _zone()
    _cf("PUT", f"/accounts/{acct}/cfd_tunnel/{tid}/configurations", {"config": {"ingress": [
        {"hostname": host, "service": "ssh://localhost:22"},
        {"service": "http_status:404"},
    ]}})


def _delete_tunnel(tid):
    _, acct = _zone()
    try:
        _cf("DELETE", f"/accounts/{acct}/cfd_tunnel/{tid}/connections")
    except Exception as e:  # noqa: BLE001
        log.warning(f"tunnel {tid} connections: {e}")
    _cf("DELETE", f"/accounts/{acct}/cfd_tunnel/{tid}")


def connected(tid, wait=0):
    """True once a connector for the tunnel is registered with Cloudflare."""
    _, acct = _zone()
    end = time.time() + wait
    while True:
        try:
            if (_cf("GET", f"/accounts/{acct}/cfd_tunnel/{tid}") or {}).get("connections"):
                return True
        except Exception:  # noqa: BLE001
            pass
        if time.time() >= end:
            return False
        time.sleep(3)


# ---- DNS -------------------------------------------------------------------------

def _route_dns(tid, host):
    """Point host at the tunnel. An existing CNAME at that name is only replaced if it points
    at a tunnel too; anything else at that name is left alone and the share fails."""
    zone, _ = _zone()
    target = f"{tid}.cfargotunnel.com"
    for rec in _cf("GET", f"/zones/{zone}/dns_records?name={urllib.parse.quote(host)}") or []:
        if rec["type"] == "CNAME" and rec["content"] == target:
            return
        if rec["type"] == "CNAME" and rec["content"].endswith(".cfargotunnel.com"):
            _cf("DELETE", f"/zones/{zone}/dns_records/{rec['id']}")
        else:
            raise RuntimeError(f"{host} already has a {rec['type']} record that isn't a tunnel; not touching it")
    _cf("POST", f"/zones/{zone}/dns_records", {"type": "CNAME", "name": host, "content": target, "proxied": True,
                                                 "comment": "homelab dashboard: shared machine"})


def _unroute_dns(host, tid):
    """Remove host's CNAME if it points at this tunnel. A failure is logged: the record would
    point at a deleted tunnel, so the machine is unshared either way."""
    try:
        zone, _ = _zone()
        for rec in _cf("GET", f"/zones/{zone}/dns_records?type=CNAME&name={urllib.parse.quote(host)}") or []:
            if rec["content"] == f"{tid}.cfargotunnel.com":
                _cf("DELETE", f"/zones/{zone}/dns_records/{rec['id']}")
                log.info(f"removed DNS record {host}")
    except Exception as e:  # noqa: BLE001
        log.warning(f"couldn't remove DNS record {host}: {e}")


# ---- machine side ----------------------------------------------------------------

# Installs and starts sshd (key-only) and unlocks the user's account, since sshd turns away
# locked accounts even with a valid key (Alpine creates users locked).
SSHD_SH = r"""
set -e
if ! command -v sshd >/dev/null 2>&1 && [ ! -x /usr/sbin/sshd ]; then
  if command -v apk >/dev/null; then apk add --no-cache openssh-server
  elif command -v apt-get >/dev/null; then DEBIAN_FRONTEND=noninteractive apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server
  elif command -v dnf >/dev/null; then dnf install -y -q openssh-server
  elif command -v pacman >/dev/null; then pacman -Sy --noconfirm openssh
  elif command -v zypper >/dev/null; then zypper -n install openssh-server
  else echo "no known package manager" >&2; exit 1; fi
fi
C=/etc/ssh/sshd_config
if ! grep -q '^# homelab-share' "$C"; then
  { printf '# homelab-share: keys only\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n\n'; cat "$C"; } > "$C.new" && mv "$C.new" "$C"
fi
U="$1"
if [ -n "$U" ] && grep -q "^$U:!" /etc/shadow; then sed -i "s/^$U:![^:]*:/$U:*:/" /etc/shadow; fi
ssh-keygen -A >/dev/null
if command -v rc-service >/dev/null; then rc-update add sshd default >/dev/null 2>&1 || true; rc-service sshd restart >/dev/null
elif command -v systemctl >/dev/null; then systemctl enable ssh >/dev/null 2>&1 || systemctl enable sshd >/dev/null 2>&1 || true; systemctl restart ssh 2>/dev/null || systemctl restart sshd
else pkill -x sshd || true; /usr/sbin/sshd; fi
"""

# Adds ($2 = add) or removes ($2 = del) the key lines on stdin for user $1.
KEYS_SH = r"""
set -e
H=$(getent passwd "$1" | cut -d: -f6); [ -n "$H" ] || { echo "no user $1" >&2; exit 1; }
mkdir -p "$H/.ssh"; F="$H/.ssh/authorized_keys"; touch "$F"
T=$(mktemp); cat > "$T"
if [ "$2" = add ]; then
  while IFS= read -r k; do [ -z "$k" ] || grep -qxF "$k" "$F" || printf '%s\n' "$k" >> "$F"; done < "$T"
else
  grep -vxF -f "$T" "$F" > "$F.new" || true; mv "$F.new" "$F"
fi
rm -f "$T"
chown -R "$1:" "$H/.ssh" 2>/dev/null || chown -R "$1" "$H/.ssh"; chmod 700 "$H/.ssh"; chmod 600 "$F"
"""

# ---- per-person permissions -----------------------------------------------------
# Each key gets its OWN login user on the machine, with its own permissions. The dashboard
# writes them to /etc/homelab-share/users/<user>.conf and share_policy.sh (installed in the
# machine as homelab-policy, re-applied at every boot) enforces them: sudo rules, docker
# group, egress firewall per uid, sshd Match block (forwarding, sftp-only, login wrapper),
# a cgroup per user for CPU/memory/process caps, account expiry, private homes and
# hidden processes. The accounts are key-only, so any sudo granted is NOPASSWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
SUDO_GROUPS = {
    "packages": {"label": "Install packages", "desc": "apk / apt / dnf as root"},
    "services": {"label": "Manage services", "desc": "rc-service, rc-update / systemctl"},
    "power": {"label": "Reboot & shut down", "desc": "reboot, poweroff"},
}
NET_MODES = {
    "full": "Everything, including your LAN, the tailnet and other machines",
    "internet": "Internet only: LAN, tailnet, the Mac and other machines are blocked",
    "none": "No network (localhost only)",
}
PERM_DEFAULTS = {"access": "shell", "root": "none", "sudo": [], "docker": False, "net": "internet",
                 "forward": False, "procs": False, "cpu": 0, "mem_mib": 0, "pids": 256, "expires": ""}
PRESETS = {
    "guest": {"label": "Guest", "desc": "Own shell, no root, internet only, private from everyone else.",
              "perms": {**PERM_DEFAULTS}},
    "files": {"label": "Files only", "desc": "SFTP into their home folder. No shell, no network.",
              "perms": {**PERM_DEFAULTS, "access": "sftp", "net": "none"}},
    "developer": {"label": "Developer", "desc": "Can install packages and run services. Root-capable in practice.",
                  "perms": {**PERM_DEFAULTS, "root": "some", "sudo": ["packages", "services"], "forward": True, "procs": True, "pids": 1024}},
    "admin": {"label": "Admin", "desc": "Full root and Docker. They can change every other setting here.",
              "perms": {**PERM_DEFAULTS, "root": "full", "docker": True, "net": "full", "forward": True, "procs": True, "pids": 0}},
}
# keys added before per-person permissions only carry a level
_LEGACY = {"guest": "guest", "admin": "admin", "owner": "admin"}
_USER_MARK = "homelab-share"  # GECOS prefix; marks a user as ours so we never touch or delete others
_RESERVED = {"root", "daemon", "bin", "sys", "sync", "nobody", "sshd", "wheel", "docker", "admin", "adm", "man", "lp", "mail", "news", "operator", "procview"}


def custom_presets():
    return _load().get("presets") or []


def save_preset(label, desc, perms, expires_days=0):
    """Save your own preset. Its expiry is relative (days after adding someone)."""
    label = (label or "").strip()[:30]
    if not label:
        raise ValueError("Give the preset a name")
    if label.lower() in {v["label"].lower() for v in PRESETS.values()}:
        raise ValueError(f"{label} is a built-in preset; pick another name")
    days = int(expires_days or 0)
    if not 0 <= days <= 3650:
        raise ValueError("Expiry must be 0 (never) to 3650 days")
    perms = {**clean_perms(perms), "expires": ""}
    pid = "c-" + re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    with _lock:
        state = _load()
        lst = [x for x in state.get("presets") or [] if x["id"] != pid]
        lst.append({"id": pid, "label": label, "desc": (desc or "").strip()[:120], "perms": perms, "expires_days": days, "custom": True})
        state["presets"] = lst
        _save(state)
    return pid


def delete_preset(pid):
    with _lock:
        state = _load()
        before = len(state.get("presets") or [])
        state["presets"] = [x for x in state.get("presets") or [] if x["id"] != pid]
        if len(state["presets"]) == before:
            raise ValueError("No such preset")
        _save(state)


def permission_schema():
    """What the UI offers: presets, sudo command groups and network modes."""
    return {"presets": [{"id": k, "label": v["label"], "desc": v["desc"], "perms": v["perms"]} for k, v in PRESETS.items()] + custom_presets(),
            "sudo": [{"id": k, **v} for k, v in SUDO_GROUPS.items()],
            "net": [{"id": k, "desc": v} for k, v in NET_MODES.items()],
            "defaults": PERM_DEFAULTS}


def clean_perms(p):
    """Validate permissions from the browser. Everything ends up in a shell conf file, so
    only known words, numbers and an ISO date get through."""
    p = {**PERM_DEFAULTS, **(p or {})}

    def num(v, lo, hi, kind):
        try:
            v = kind(v or 0)
        except (TypeError, ValueError):
            raise ValueError(f"not a number: {v!r}")
        if v and not lo <= v <= hi:
            raise ValueError(f"{v} is outside {lo}–{hi}")
        return v
    out = {
        "access": p["access"] if p["access"] in ("shell", "sftp") else "shell",
        "root": p["root"] if p["root"] in ("none", "some", "full") else "none",
        "sudo": [g for g in SUDO_GROUPS if g in (p.get("sudo") or [])],
        "docker": bool(p["docker"]), "net": p["net"] if p["net"] in NET_MODES else "internet",
        "forward": bool(p["forward"]), "procs": bool(p["procs"]),
        "cpu": round(num(p["cpu"], 0.1, 64, float), 2), "mem_mib": num(p["mem_mib"], 64, 1 << 20, int),
        "pids": num(p["pids"], 16, 1 << 22, int), "expires": (p.get("expires") or "").strip(),
    }
    if out["expires"]:
        try:
            datetime.strptime(out["expires"], "%Y-%m-%d")
        except ValueError:
            raise ValueError("Expiry must be a date like 2026-12-31")
    if out["root"] == "some" and not out["sudo"]:
        out["root"] = "none"
    if out["root"] != "some":
        out["sudo"] = []
    if out["access"] == "sftp":  # no shell: nothing to run as root or with docker
        out.update(root="none", sudo=[], docker=False, forward=False)
    return out


def perms_of(meta):
    """A key's permissions, translating the old guest/admin/owner levels."""
    if meta.get("perms"):
        return {**PERM_DEFAULTS, **meta["perms"]}
    return {**PRESETS[_LEGACY.get(meta.get("level"), "guest")]["perms"]}


def _conf(perms):
    p = clean_perms(perms)
    return (f"ACCESS={p['access']}\nROOT={p['root']}\nSUDO=\"{' '.join(p['sudo'])}\"\nDOCKER={int(p['docker'])}\n"
            f"NET={p['net']}\nFORWARD={int(p['forward'])}\nPROCS={int(p['procs'])}\n"
            f"CPU={p['cpu'] or 0}\nMEM={p['mem_mib'] or 0}\nPIDS={p['pids'] or 0}\nEXPIRES={p['expires']}\n")


def _derive_username(label, comment, taken):
    """A valid, unique unix username from the key's name. Falls back through label ->
    comment -> 'user', and appends a number on collision with another key's user."""
    base = re.sub(r"[^a-z0-9_-]+", "-", (label or comment or "user").lower())
    base = re.sub(r"^[^a-z]+", "", base).strip("-_")[:28] or "user"
    reserved = set(taken) | _RESERVED
    name, i = base, 2
    while name in reserved:
        name, i = f"{base[:26]}{i}", i + 1
    return name


def _clean_username(username, taken):
    """Validate and normalise a username the owner typed. Raises with a friendly message
    rather than silently changing it out from under them."""
    u = re.sub(r"[^a-z0-9_-]+", "-", username.lower()).strip("-_")
    u = re.sub(r"^[^a-z]+", "", u)[:32]
    if not u:
        raise ValueError("Username must contain a letter (a–z), and may use digits, - and _")
    if u in _RESERVED:
        raise ValueError(f"{u!r} is a reserved system name; pick another")
    if u in taken:
        raise ValueError(f"{u!r} is already a login on this machine; pick another")
    return u


# Installs homelab-policy (stdin = the script, $1 = base64 of the login wrapper) plus a boot
# service that re-applies it (cgroups, /proc options and the firewall don't survive a
# restart) and an hourly cron job that ends sessions of expired users.
POLICY_INSTALL_SH = r"""
set -e
mkdir -p /usr/local/sbin /usr/local/libexec /etc/homelab-share/users
cat > /usr/local/sbin/homelab-policy.new; chmod 755 /usr/local/sbin/homelab-policy.new; mv /usr/local/sbin/homelab-policy.new /usr/local/sbin/homelab-policy
echo "$1" | base64 -d > /usr/local/libexec/homelab-session; chmod 755 /usr/local/libexec/homelab-session
if command -v apk >/dev/null; then apk add --no-cache -q sudo iptables ip6tables openssh-sftp-server >/dev/null 2>&1 || true; fi
if command -v rc-service >/dev/null; then
  printf '%s\n' '#!/sbin/openrc-run' 'description="Per-person permissions for shared logins (homelab dashboard)"' \
    'depend() { need localmount; before sshd; after net; }' 'start() { ebegin "Applying share permissions"; /usr/local/sbin/homelab-policy apply; eend 0; }' > /etc/init.d/homelab-policy
  chmod +x /etc/init.d/homelab-policy; rc-update add homelab-policy default >/dev/null 2>&1 || true; rc-service --ifstopped homelab-policy start >/dev/null 2>&1 || true
elif command -v systemctl >/dev/null; then
  printf '%s\n' '[Unit]' 'Description=Per-person permissions for shared logins (homelab dashboard)' 'After=network.target' 'Before=ssh.service sshd.service' \
    '[Service]' 'Type=oneshot' 'ExecStart=/usr/local/sbin/homelab-policy apply' 'RemainAfterExit=yes' '[Install]' 'WantedBy=multi-user.target' > /etc/systemd/system/homelab-policy.service
  systemctl daemon-reload; systemctl enable --now homelab-policy >/dev/null 2>&1 || true
fi
if [ -d /etc/periodic/hourly ]; then printf '#!/bin/sh\nexec /usr/local/sbin/homelab-policy expire\n' > /etc/periodic/hourly/homelab-policy; chmod 755 /etc/periodic/hourly/homelab-policy
elif [ -d /etc/cron.hourly ]; then printf '#!/bin/sh\nexec /usr/local/sbin/homelab-policy expire\n' > /etc/cron.hourly/homelab-policy; chmod 755 /etc/cron.hourly/homelab-policy; fi
"""

# Creates managed login user $1 if needed (refusing a user that isn't ours), unlocks it
# (sshd turns away locked users, which Alpine creates by default) and writes its
# permissions (stdin) for homelab-policy.
USERSETUP_SH = r"""
set -e
U="$1"; MARK="homelab-share"
if id "$U" >/dev/null 2>&1; then
  g=$(getent passwd "$U" | cut -d: -f5)
  case "$g" in "$MARK"*) : ;; *) echo "user $U already exists on this machine and isn't dashboard-managed; pick another name" >&2; exit 2;; esac
else
  if command -v useradd >/dev/null 2>&1; then useradd -m -s /bin/sh -c "$MARK" "$U"
  else adduser -D -s /bin/sh -g "$MARK" "$U"; fi
fi
if grep -q "^$U:!" /etc/shadow 2>/dev/null; then sed -i "s/^$U:![^:]*:/$U:*:/" /etc/shadow; fi
chmod 700 "$(getent passwd "$U" | cut -d: -f6)"
mkdir -p /etc/homelab-share/users; umask 077; cat > "/etc/homelab-share/users/$U.conf"
/usr/local/sbin/homelab-policy apply
"""

# Removes a managed login user $1 (its home, permissions, and any live processes), then
# re-applies so its firewall chain, sshd block and cgroup go too. Refuses anything not ours.
DELUSER_SH = r"""
U="$1"; MARK="homelab-share"
rm -f "/etc/sudoers.d/90-share-$U" "/etc/homelab-share/users/$U.conf"
if id "$U" >/dev/null 2>&1; then
  g=$(getent passwd "$U" | cut -d: -f5)
  case "$g" in "$MARK"*)
    pkill -KILL -u "$U" 2>/dev/null || true
    if command -v deluser >/dev/null 2>&1; then deluser --remove-home "$U" 2>/dev/null || deluser "$U" 2>/dev/null || true
    elif command -v userdel >/dev/null 2>&1; then userdel -r "$U" 2>/dev/null || userdel "$U" 2>/dev/null || true; fi ;;
  *) echo "refusing to delete unmanaged user $U" >&2 ;;
  esac
fi
[ -x /usr/local/sbin/homelab-policy ] && /usr/local/sbin/homelab-policy apply
true
"""


def install_policy(name):
    """Put (or update) homelab-policy and its login wrapper in the machine."""
    with open(os.path.join(_HERE, "share_policy.sh")) as f:
        policy = f.read()
    with open(os.path.join(_HERE, "share_session.sh"), "rb") as f:
        wrapper = base64.b64encode(f.read()).decode()
    _in_machine(name, POLICY_INSTALL_SH, (wrapper,), policy, timeout=300)


# Writes stdin to path $1, readable by root only.
WRITE_SH = 'mkdir -p "$(dirname "$1")"; umask 077; cat > "$1"'

# Installs cloudflared in the machine and runs it as a service (OpenRC, systemd, or a plain
# background process) with the tunnel token in REMOTE_DIR. $1 = start | stop.
CONNECTOR_SH = r"""
set -e
D=/etc/cloudflared/share; B=/usr/local/bin/cloudflared
ARGS="tunnel --no-autoupdate run --token-file $D/token"
if [ "$1" = stop ]; then
  if [ -f /etc/init.d/homelab-share ]; then rc-service homelab-share stop >/dev/null 2>&1 || true; rc-update del homelab-share default >/dev/null 2>&1 || true; rm -f /etc/init.d/homelab-share
  elif [ -f /etc/systemd/system/homelab-share.service ]; then systemctl disable --now homelab-share >/dev/null 2>&1 || true; rm -f /etc/systemd/system/homelab-share.service; systemctl daemon-reload
  else pkill -f "share/token" || true; fi
  rm -rf "$D"; exit 0
fi
if [ ! -x "$B" ]; then
  case "$(uname -m)" in aarch64|arm64) A=arm64;; x86_64|amd64) A=amd64;; armv7*) A=arm;; *) echo "unsupported arch $(uname -m)" >&2; exit 1;; esac
  U="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$A"
  if command -v curl >/dev/null; then curl -fsSL -o "$B.tmp" "$U"; else wget -qO "$B.tmp" "$U"; fi
  chmod +x "$B.tmp"; mv "$B.tmp" "$B"
fi
if command -v rc-service >/dev/null; then
  printf '%s\n' '#!/sbin/openrc-run' \
    'description="Cloudflare Tunnel for public SSH (homelab dashboard)"' \
    'supervisor=supervise-daemon' \
    "command=$B" \
    "command_args=\"$ARGS\"" \
    'output_log=/var/log/homelab-share.log' \
    'error_log=/var/log/homelab-share.log' \
    'depend() { need net; }' > /etc/init.d/homelab-share
  chmod +x /etc/init.d/homelab-share
  rc-update add homelab-share default >/dev/null 2>&1 || true
  rc-service homelab-share restart >/dev/null
elif command -v systemctl >/dev/null; then
  printf '%s\n' '[Unit]' 'Description=Cloudflare Tunnel for public SSH (homelab dashboard)' 'After=network-online.target' \
    '[Service]' "ExecStart=$B $ARGS" 'Restart=always' 'RestartSec=5' \
    '[Install]' 'WantedBy=multi-user.target' > /etc/systemd/system/homelab-share.service
  systemctl daemon-reload; systemctl enable homelab-share >/dev/null 2>&1; systemctl restart homelab-share
else
  pkill -f "share/token" || true; nohup $B $ARGS >/var/log/homelab-share.log 2>&1 &
fi
"""


def _in_machine(name, script, args=(), stdin=None, timeout=600):
    code, out, err = orbhost.run(["-m", name, "-u", "root", "sh", "-c", script, "sh", *args], timeout=timeout, input=stdin)
    if code != 0:
        raise RuntimeError((err or out).strip()[-400:] or "command failed in machine")


def _start_connector(name, tid):
    _in_machine(name, WRITE_SH, (f"{REMOTE_DIR}/token",), _tunnel_token(tid), timeout=20)
    _in_machine(name, CONNECTOR_SH, ("start",), timeout=300)


def _clean_keys(keys):
    out = []
    for line in (keys or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("-----BEGIN"):
            raise ValueError("That's a private key. Never share it; send the .pub line instead")
        if not line.startswith(("ssh-", "ecdsa-", "sk-")) or len(line.split()) < 2:
            raise ValueError(f"Not an SSH public key: {line[:40]}…")
        out.append(line)
    return out


# ---- share / unshare -------------------------------------------------------------

def share(name, username, keys_text=""):
    """Share a machine, or add keys if it already is. Keys go to the machine's default user
    and are remembered, so unsharing can take them out again."""
    keys = _clean_keys(keys_text)
    user = username or "root"
    with _lock:
        state = _load()
        state.setdefault("shares", {})
        prev = state["shares"].get(K(name)) or {}
        _in_machine(name, SSHD_SH, (user,))
        install_policy(name)
        if keys:
            _in_machine(name, KEYS_SH, (user, "add"), "\n".join(keys) + "\n", timeout=30)
        host = hostname(name)
        tid = prev.get("tunnel_id")
        if not tid:
            tid = _create_tunnel(name)
            try:
                _set_ingress(tid, host)
                _start_connector(name, tid)
                _route_dns(tid, host)
            except Exception:
                try:
                    _in_machine(name, CONNECTOR_SH, ("stop",), timeout=60)
                finally:
                    try:
                        _delete_tunnel(tid)
                    except Exception as e:  # noqa: BLE001
                        log.warning(f"cleaning up tunnel {tid}: {e}")
                raise
            if not connected(tid, wait=30):
                log.warning(f"share {name}: tunnel {tid} hasn't connected yet")
        merged = list(dict.fromkeys((prev.get("keys") or []) + keys))
        meta = prev.get("key_meta") or {}
        for k in keys:
            meta.setdefault(_fingerprint(k), {"added": time.time()})
        state["shares"][K(name)] = {"hostname": host, "since": prev.get("since") or time.time(),
                                 "keys": merged, "key_meta": meta, "user": user, "tunnel_id": tid}
        _save(state)
    log.info(f"shared {name} as {host} ({len(merged)} keys)")
    return share_info(name)


def remove_key(name, fp):
    """Take one added key out of the machine and the share. Its dedicated login user (home,
    sudoers and all) goes with it; a legacy key with no user of its own is just removed from
    the share's shared user."""
    with _lock:
        state = _load()
        s = (state.get("shares") or {}).get(K(name))
        if not s:
            raise ValueError(f"{name} isn't shared")
        key = next((k for k in s.get("keys") or [] if _fingerprint(k) == fp), None)
        if not key:
            raise ValueError("No such key on this share")
        kuser = ((s.get("key_meta") or {}).get(fp) or {}).get("user")
        if kuser:
            _in_machine(name, DELUSER_SH, (kuser,), timeout=30)
        else:
            _in_machine(name, KEYS_SH, (s.get("user") or "root", "del"), key + "\n", timeout=30)
        s["keys"] = [k for k in s["keys"] if k != key]
        (s.get("key_meta") or {}).pop(fp, None)
        _save(state)
    log.info(f"removed key {fp} from {name}")


def add_key(name, key, label="", perms=None, username=""):
    """Add one public key to a shared machine as its own login user with the given
    permissions. `username` is the owner's choice of login name; blank derives one from
    the label. Returns {"user", "perms", "hostname"} so the UI can show how they connect."""
    keys = _clean_keys(key)
    if len(keys) != 1:
        raise ValueError("Paste exactly one public key")
    key, fp = keys[0], _fingerprint(keys[0])
    if not fp:
        raise ValueError("That key doesn't decode; check it was copied in full")
    perms = clean_perms(perms)
    with _lock:
        state = _load()
        s = (state.get("shares") or {}).get(K(name))
        if not s:
            raise ValueError(f"{name} isn't shared")
        if any(_fingerprint(k) == fp for k in s.get("keys") or []):
            raise ValueError("That key is already on this machine")
        meta = s.setdefault("key_meta", {})
        taken = {m.get("user") for m in meta.values() if m.get("user")} | {s.get("user")}
        username = (_clean_username(username, taken) if (username or "").strip()
                    else _derive_username(label, _key_info(key).get("comment"), taken))
        install_policy(name)
        _in_machine(name, USERSETUP_SH, (username,), _conf(perms), timeout=300)
        _in_machine(name, KEYS_SH, (username, "add"), key + "\n", timeout=30)
        s.setdefault("keys", []).append(key)
        meta[fp] = {"added": time.time(), "label": (label or "").strip()[:60], "perms": perms, "user": username}
        _save(state)
    _logins_cache.pop(K(name), None)
    log.info(f"added key {fp} to {name} as {username} ({perms})")
    return {"user": username, "perms": perms, "hostname": s["hostname"]}


def set_perms(name, fp, perms):
    """Change what one person may do. Applied right away; their open sessions keep their
    current cgroup and groups until they log in again, except network rules and sudo,
    which take effect immediately."""
    perms = clean_perms(perms)
    with _lock:
        state = _load()
        s = (state.get("shares") or {}).get(K(name))
        m = ((s or {}).get("key_meta") or {}).get(fp)
        if not m:
            raise ValueError("No such key on this share")
        if not m.get("user"):
            raise ValueError(f"This key logs in as {s.get('user')}, the machine's own user, whose permissions the dashboard doesn't manage")
        install_policy(name)
        _in_machine(name, USERSETUP_SH, (m["user"],), _conf(perms), timeout=300)
        m["perms"] = perms
        m.pop("level", None)
        _save(state)
    log.info(f"permissions of {m['user']} on {name}: {perms}")
    return perms


def sync_policy(name):
    """Reinstall homelab-policy and rewrite every managed user's permissions from the state
    file, e.g. after the policy script changed or for users added before it existed."""
    with _lock:
        s = (_load().get("shares") or {}).get(K(name))
        if not s:
            return
        install_policy(name)
        for m in (s.get("key_meta") or {}).values():
            if m.get("user"):
                _in_machine(name, USERSETUP_SH, (m["user"],), _conf(perms_of(m)), timeout=300)


def label_key(name, fp, label):
    """Give a key a name of your own (shown instead of the key's comment)."""
    with _lock:
        state = _load()
        s = (state.get("shares") or {}).get(K(name))
        if not s or not any(_fingerprint(k) == fp for k in s.get("keys") or []):
            raise ValueError("No such key on this share")
        s.setdefault("key_meta", {}).setdefault(fp, {})["label"] = label.strip()[:60]
        _save(state)


def unshare(name, machine_running=True):
    """Delete the tunnel and its DNS record; on a running machine also stop the connector
    and take the added keys out. A stopped machine is left as it is (`orb -m` would boot
    it): its connector can't log in to a deleted tunnel, and sharing again rewrites it."""
    with _lock:
        state = _load()
        s = (state.get("shares") or {}).pop(K(name), None)
        if not s:
            return False
        if s.get("tunnel_id"):
            _unroute_dns(s["hostname"], s["tunnel_id"])
            _delete_tunnel(s["tunnel_id"])  # raises (and keeps the share) if Cloudflare refuses
        _save(state)
        if machine_running:
            try:
                _in_machine(name, CONNECTOR_SH, ("stop",), timeout=60)
                meta = s.get("key_meta") or {}
                for kuser in {m.get("user") for m in meta.values() if m.get("user")}:
                    try:
                        _in_machine(name, DELUSER_SH, (kuser,), timeout=30)
                    except Exception as e:  # noqa: BLE001
                        log.warning(f"unshare {name}: removing {kuser}: {e}")
                legacy = [k for k in (s.get("keys") or []) if not (meta.get(_fingerprint(k)) or {}).get("user")]
                if legacy:
                    _in_machine(name, KEYS_SH, (s.get("user") or "root", "del"), "\n".join(legacy) + "\n", timeout=30)
            except Exception as e:  # noqa: BLE001
                log.warning(f"unshare {name}: {e}")
    log.info(f"unshared {name}")
    return True


def rename(old, new, machine_running=True):
    """Move a share to the machine's new name: new hostname and DNS record. The tunnel's
    config lives on Cloudflare, so the connector inside the machine needs no change."""
    with _lock:
        state = _load()
        s = (state.get("shares") or {}).get(K(old))
        if not s:
            return
        old_host, tid = s["hostname"], s["tunnel_id"]
        s["hostname"] = hostname(new)
        _set_ingress(tid, s["hostname"])
        _route_dns(tid, s["hostname"])
        state["shares"][K(new)] = state["shares"].pop(K(old))
        _save(state)
        _unroute_dns(old_host, tid)
