from app.core.config import VM_CMD_PREFIX
from flask import Blueprint, jsonify, request
import subprocess
import json
import os
import shutil

from app.core.logger import log
from app.core.cache import global_state
from app.core import paths
from app.core import server_cfg

system_bp = Blueprint('system', __name__)

@system_bp.route('/stream')
def stats_stream():
    """Server-Sent Events endpoint for real-time stats (Proxy friendly fallback)"""
    def generate():
        import time, json
        from app.core.cache import global_state
        while True:
            stats = global_state.get_full_state()
            if stats:
                yield f"data: {json.dumps({'status': 'success', 'data': stats})}\n\n"
            time.sleep(1)
    from flask import Response
    return Response(generate(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@system_bp.route('/stats')
def stats():
    data = global_state.get_full_state()
    if not data:
        return jsonify({"status": "error", "message": "Warming up... Please wait."})
    return jsonify({"status": "success", "data": data})

@system_bp.route('/history')
def history():
    from app.core.db import get_historical_metrics
    hours = request.args.get('hours', type=float)
    span = request.args.get('span', default='24h', type=str)
    
    # Translate span to hours if hours not explicitly provided
    if hours is None:
        span_hours = {'1h': 1, '6h': 6, '24h': 24, '7d': 168, '30d': 720}
        hours = span_hours.get(span, 24)
        
    metric = request.args.get('metric', default='all', type=str)
    data = get_historical_metrics(hours=hours)
    
    if metric != 'all' and isinstance(data, dict):
        filtered_data = {}
        for node, records in data.items():
            filtered_data[node] = [{'ts': r['ts'], metric: r.get(metric)} for r in records if metric in r]
        data = filtered_data
    return jsonify({"status": "success", "data": data, "meta": {"span": span, "metric": metric}})

@system_bp.route('/storage')
def get_storage():
    with global_state.lock:
        return jsonify({
            "status": "success",
            "data": dict(global_state.storage)
        })

@system_bp.route('/storage/forecast')
def storage_forecast():
    from app.core.db import get_disk_forecast
    return jsonify({"status": "success", "data": get_disk_forecast('arrakis')})

@system_bp.route('/alerts/test', methods=['POST'])
def alerts_test():
    from app.services.alerts import send_alert, load_alert_prefs, channels
    prefs = load_alert_prefs()
    if not channels(prefs):
        return jsonify({"status": "error", "message": "No alert channel configured"})
    results = send_alert('Test alert', 'Alerts from your homelab dashboard are working.', prefs, kind='test')
    failed = [f"{c}: {e}" for c, e in results if e]
    if failed:
        return jsonify({"status": "error", "message": '; '.join(failed)})
    return jsonify({"status": "success", "channels": [c for c, _ in results]})

# ---- network tools (Settings → Tools): checks run from the Mac ----------------------------
import re as _re
import socket as _socket
import time as _time

_HOST_RE = _re.compile(r'^[A-Za-z0-9][A-Za-z0-9.\-:]{0,252}$')


def _tool_host():
    host = ((request.get_json(silent=True) or {}).get('host') or '').strip()
    return host if _HOST_RE.match(host) else None


# ---- where a check runs: "mac" (Arrakis itself), an OrbStack machine, or a cluster host over SSH ----
def _tool_from():
    w = ((request.get_json(silent=True) or {}).get('from') or request.args.get('from') or 'mac').strip()
    return w if w == 'mac' or _re.match(r'^[a-z0-9][a-z0-9-]{0,62}$', w) else None


def _remote(where, script, timeout=15):
    """Run a POSIX sh snippet on a machine (as root, so ping works) or a host over SSH -> stdout."""
    from app.core.tmux_target import run_on, remote_host, running_machines, online_hosts
    if where not in running_machines() and where not in online_hosts():
        raise RuntimeError(f"{where} isn't running or online")
    r = run_on(where, script, root=not remote_host(where), timeout=timeout)
    if r.returncode == 255 and remote_host(where):
        raise RuntimeError((r.stderr.strip().splitlines() or ['SSH failed'])[-1][:120])
    return r.stdout


@system_bp.route('/tools/sources')
def tool_sources():
    """Places a check can run from: Arrakis, its running machines, online cluster hosts."""
    from app.core.tmux_target import running_machines, online_hosts
    from app.api import hosts
    out = [{"id": "mac", "name": server_cfg.name(), "kind": "host", "os": "macOS"}]
    out += [{"id": m, "name": m, "kind": "machine", "os": "Linux"} for m in sorted(running_machines())]
    for hid in online_hosts():
        h = next((x for x in hosts._load() if x['id'] == hid), None)
        rep = hosts.host_report(hid) or {}
        if h:
            out.append({"id": hid, "name": h['name'], "kind": "host", "os": "macOS" if 'mac' in (rep.get('os') or '').lower() else "Linux"})
    return jsonify({"status": "success", "data": out})


def _parse_ping(out, err=''):
    loss = _re.search(r'([0-9.]+)% packet loss', out)
    rtt = _re.search(r'= ([0-9.]+)/([0-9.]+)/([0-9.]+)', out)
    sent = _re.search(r'(\d+) packets transmitted, (\d+) (?:packets )?received', out)
    if not rtt:
        lines = [l for l in (err + '\n' + out).strip().splitlines() if l.strip() and 'PING' not in l and 'statistics' not in l]
        msg = (lines or ['No answer'])[-1].replace('ping: ', '')
        if sent and sent.group(2) == '0':
            msg = 'No answer'
        return {"status": "error", "message": msg[:120]}
    return {"status": "success", "data": {"min_ms": float(rtt.group(1)), "avg_ms": float(rtt.group(2)), "max_ms": float(rtt.group(3)),
                                          "loss": float(loss.group(1)) if loss else 0,
                                          "sent": int(sent.group(1)) if sent else 4, "received": int(sent.group(2)) if sent else None}}


@system_bp.route('/tools/ping', methods=['POST'])
def tool_ping():
    host, where = _tool_host(), _tool_from()
    if not host or not where:
        return jsonify({"status": "error", "message": "Enter a host name or IP"})
    if where != 'mac':
        try:
            out = _remote(where, f'if [ "$(uname)" = Darwin ]; then ping -c 4 -i 0.3 -t 6 {host}; else ping -c 4 -i 0.3 -W 2 {host}; fi 2>&1')
        except Exception as e:
            return jsonify({"status": "error", "message": str(e) or 'No answer'})
        return jsonify(_parse_ping(out))
    try:
        r = subprocess.run(['ping', '-c', '4', '-i', '0.3', '-t', '6', host], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "No answer"})
    return jsonify(_parse_ping(r.stdout, r.stderr))


@system_bp.route('/tools/port', methods=['POST'])
def tool_port():
    host = _tool_host()
    try:
        port = int((request.get_json(silent=True) or {}).get('port'))
    except (TypeError, ValueError):
        port = 0
    if not host or not 0 < port < 65536:
        return jsonify({"status": "error", "message": "Enter a host and a port (1-65535)"})
    where = _tool_from()
    if where and where != 'mac':
        # python3 where there is one (times it); else nc, which only says open or not
        py = ("import socket,time,sys\nt=time.time()\ntry:\n socket.create_connection((sys.argv[1],int(sys.argv[2])),4);print('open',round((time.time()-t)*1000,1))\n"
              "except socket.timeout:print('closed timed-out')\nexcept ConnectionRefusedError:print('closed refused')\nexcept OSError as e:print('error',e.strerror or e)")
        script = (f'if command -v python3 >/dev/null; then python3 -c "{py}" {host} {port}; '
                  # busybox nc says "timed out" on a timeout and nothing on a refusal; /proc/uptime times it
                  f'else t0=$(cut -d" " -f1 /proc/uptime 2>/dev/null); o=$(nc -v -z -w 4 {host} {port} 2>&1); rc=$?; '
                  f't1=$(cut -d" " -f1 /proc/uptime 2>/dev/null); ms=$(awk "BEGIN{{print ($t1-$t0)*1000}}" 2>/dev/null); '
                  f'if [ $rc = 0 ]; then echo open $ms; '
                  f'else case "$o" in *"timed out"*) echo closed timed-out;; *"unreachable"*|*"No route"*) echo error No route to {host};; '
                  f'*"bad address"*|*"resolve"*) echo error Cannot resolve {host};; *) echo closed refused;; esac; fi; fi')
        try:
            out = (_remote(where, script).strip().splitlines() or ['error No answer'])[-1].split(' ', 1)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
        if out[0] == 'open':
            return jsonify({"status": "success", "data": {"open": True, "ms": float(out[1]) if len(out) > 1 else None}})
        if out[0] == 'closed':
            return jsonify({"status": "success", "data": {"open": False, "reason": out[1].replace('-', ' ')}})
        return jsonify({"status": "error", "message": out[-1]})
    t0 = _time.time()
    try:
        with _socket.create_connection((host, port), timeout=4):
            pass
        return jsonify({"status": "success", "data": {"open": True, "ms": round((_time.time() - t0) * 1000, 1)}})
    except _socket.timeout:
        return jsonify({"status": "success", "data": {"open": False, "reason": "timed out"}})
    except ConnectionRefusedError:
        return jsonify({"status": "success", "data": {"open": False, "reason": "refused"}})
    except OSError as e:
        return jsonify({"status": "error", "message": e.strerror or str(e)})


@system_bp.route('/tools/dns', methods=['POST'])
def tool_dns():
    host = _tool_host()
    if not host:
        return jsonify({"status": "error", "message": "Enter a host name"})
    where = _tool_from()
    if where and where != 'mac':
        script = (f't0=$(date +%s); if [ "$(uname)" = Darwin ]; then dscacheutil -q host -a name {host} | awk \'/address:/{{print $2}}\'; '
                  f'else getent ahosts {host} | awk \'{{print $1}}\'; fi')
        try:
            t0 = _time.time()
            addrs = list(dict.fromkeys(a for a in _remote(where, script).split() if a))
            ms = round((_time.time() - t0) * 1000, 1)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
        if not addrs:
            return jsonify({"status": "error", "message": "Not found"})
        # the round trip includes reaching the machine or host, so it's only a rough figure
        return jsonify({"status": "success", "data": {"addresses": addrs, "ms": None, "total_ms": ms}})
    t0 = _time.time()
    try:
        infos = _socket.getaddrinfo(host, None, proto=_socket.IPPROTO_TCP)
    except _socket.gaierror as e:
        return jsonify({"status": "error", "message": "Not found" if e.errno in (_socket.EAI_NONAME, getattr(_socket, 'EAI_NODATA', -5)) else str(e)})
    addrs = list(dict.fromkeys(i[4][0] for i in infos))
    return jsonify({"status": "success", "data": {"addresses": addrs, "ms": round((_time.time() - t0) * 1000, 1)}})


# finished speed tests, newest first, kept across restarts (last 30)
_SPEED_FILE = paths.state('speedtests')
def _speed_history():
    try:
        with open(_SPEED_FILE) as f:
            return json.load(f)
    except Exception:
        return []
def _speed_save(res):
    hist = [res] + _speed_history()
    tmp = _SPEED_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(hist[:30], f)
    os.replace(tmp, _SPEED_FILE)


# How Arrakis is connected: interface, LAN address, router, resolvers, public and tailnet IP
_net_info = {"at": 0, "data": None}
def _sh(args, timeout=3):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ''

_INFO_SH = r"""
if [ "$(uname)" = Darwin ]; then
  i=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}'); echo "iface=$i"
  echo "gw=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}')"
  echo "lan=$(ipconfig getifaddr $i 2>/dev/null)"
  echo "kind=$(networksetup -listallhardwareports 2>/dev/null | grep -B1 "Device: $i\$" | sed -n 's/Hardware Port: //p')"
  echo "dns=$(scutil --dns 2>/dev/null | sed '/resolver #2/q' | awk '/nameserver\[/{print $3}' | tr '\n' ' ')"
  ts=/Applications/Tailscale.app/Contents/MacOS/Tailscale; [ -x $ts ] || ts=tailscale
else
  set -- $(ip route get 1.1.1.1 2>/dev/null | head -1)
  while [ $# -gt 0 ]; do case $1 in via) echo "gw=$2";; dev) echo "iface=$2";; src) echo "lan=$2";; esac; shift; done
  echo "dns=$(awk '/^nameserver/{print $2}' /etc/resolv.conf | tr '\n' ' ')"
  ts=tailscale
fi
echo "ts=$($ts ip -4 2>/dev/null | head -1)"
echo "pub=$( (curl -s --max-time 3 https://api.ipify.org || wget -qO- -T 3 https://api.ipify.org) 2>/dev/null)"
"""
_remote_info = {}


@system_bp.route('/tools/info')
def tool_info():
    where = _tool_from() or 'mac'
    if where != 'mac':
        c = _remote_info.get(where)
        if c and _time.time() - c[0] < 300:
            return jsonify({"status": "success", "data": c[1]})
        try:
            kv = dict(l.split('=', 1) for l in _remote(where, _INFO_SH, timeout=20).splitlines() if '=' in l)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
        iface = kv.get('iface') or None
        from app.core.tmux_target import running_machines
        kind = kv.get('kind') or ('OrbStack network' if where in running_machines() else
                                  'Wi-Fi' if iface and iface.startswith('wl') else 'Ethernet' if iface else None)
        pub = kv.get('pub', '').strip()
        data = {"interface": iface, "kind": kind, "lan_ip": kv.get('lan') or None, "gateway": kv.get('gw') or None,
                "dns": kv.get('dns', '').split(), "public_ip": pub if _re.match(r'^[0-9a-f.:]+$', pub) else None,
                "tailscale_ip": kv.get('ts') or None}
        _remote_info[where] = (_time.time(), data)
        return jsonify({"status": "success", "data": data})
    if _net_info["data"] and _time.time() - _net_info["at"] < 300:
        return jsonify({"status": "success", "data": _net_info["data"]})
    rt = _sh(['route', '-n', 'get', 'default'])
    iface = (_re.search(r'interface: (\S+)', rt) or [None, None])[1]
    gateway = (_re.search(r'gateway: (\S+)', rt) or [None, None])[1]
    kind = None
    ports = _sh(['networksetup', '-listallhardwareports'])
    for block in ports.split('\n\n'):
        if iface and f'Device: {iface}' in block:
            kind = (_re.search(r'Hardware Port: (.+)', block) or [None, None])[1]
    lan = _sh(['ipconfig', 'getifaddr', iface]).strip() if iface else ''
    # resolver #1 is what lookups use first (MagicDNS when Tailscale is up)
    dns = []
    first = _sh(['scutil', '--dns']).split('resolver #2')[0]
    for m in _re.finditer(r'nameserver\[\d+\] : (\S+)', first):
        dns.append(m.group(1))
    public = _sh(['curl', '-s', '--max-time', '3', 'https://api.ipify.org']).strip()
    ts = ''
    for exe in ('/Applications/Tailscale.app/Contents/MacOS/Tailscale', '/opt/homebrew/bin/tailscale', '/usr/local/bin/tailscale'):
        if os.path.exists(exe):
            ts = _sh([exe, 'ip', '-4']).strip().splitlines()[:1]
            ts = ts[0] if ts else ''
            break
    data = {"interface": iface, "kind": kind, "lan_ip": lan or None, "gateway": gateway, "dns": dns,
            "public_ip": public if _re.match(r'^[0-9a-f.:]+$', public or '') else None, "tailscale_ip": ts or None}
    _net_info.update(at=_time.time(), data=data)
    return jsonify({"status": "success", "data": data})


_speed_running = set()   # sources with a test in progress ("mac" = Arrakis)


def _speed_parse(out, where):
    data = json.loads(out)
    return {"dl": round(data.get('dl_throughput', 0) / 125000, 1), "ul": round(data.get('ul_throughput', 0) / 125000, 1),
            "status": "success", "at": _time.time(), "from": where,
            "rpm": data.get('responsiveness') and round(data['responsiveness']),
            "idle_ms": data.get('base_rtt') and round(data['base_rtt'], 1),
            "interface": data.get('interface_name')}


@system_bp.route('/network/speedtest', methods=['GET', 'POST'])
def speedtest():
    """macOS networkQuality, on Arrakis or on a Mac in the cluster (over SSH). Results are kept per source."""
    from app.core.cache import global_state
    if request.method == 'GET':
        return jsonify({"status": "success", "data": {"result": global_state.bg.get('speedtest_result'), "running": sorted(_speed_running), "history": _speed_history()}})
    where = _tool_from() or 'mac'
    with global_state.lock:
        if where in _speed_running:
            return jsonify({"status": "error", "message": "Already running"})
        _speed_running.add(where)
        if where == 'mac':
            global_state.bg['speedtest_running'] = True

    def run_speedtest():
        try:
            if where == 'mac':
                out = subprocess.run(["networkQuality", "-c"], capture_output=True, text=True, timeout=120).stdout
            else:
                out = _remote(where, 'command -v networkQuality >/dev/null || { echo NOTMAC; exit 0; }; networkQuality -c', timeout=120)
                if out.strip() == 'NOTMAC':
                    raise RuntimeError("Speed tests need macOS (networkQuality)")
            res = _speed_parse(out, where)
            _speed_save(res)
        except Exception as e:
            res = {"status": "error", "message": str(e) or 'Parse failed', "from": where, "at": _time.time()}
        finally:
            with global_state.lock:
                _speed_running.discard(where)
                if where == 'mac':
                    global_state.bg['speedtest_running'] = False
        with global_state.lock:
            global_state.bg['speedtest_result'] = res

    import threading
    threading.Thread(target=run_speedtest, daemon=True).start()
    return jsonify({"status": "started"})

@system_bp.route('/host/ssh/<path:tty>', methods=['DELETE'])
def kill_ssh_host(tty):
    import re
    if not re.match(r'^[a-zA-Z0-9/]+$', tty): return jsonify({"status": "error"})
    try:
        subprocess.run(["pkill", "-9", "-t", tty])
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

@system_bp.route('/vm/ssh/<path:tty>', methods=['DELETE'])
def kill_ssh_vm(tty):
    import re
    if not re.match(r'^[a-zA-Z0-9/]+$', tty): return jsonify({"status": "error"})
    try:
        subprocess.run(VM_CMD_PREFIX + ["pkill", "-9", "-t", tty])
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

@system_bp.route('/host/command/<path:cmd>', methods=['POST'])
def command(cmd):
    try:
        allowed = ['restart', 'reboot', 'backup', 'update']
        if cmd not in allowed: return jsonify({"status": "error", "message": "Unauthorized command"})
        if cmd == 'reboot':
            # `arrakis reboot host` uses `sudo reboot`, which can't prompt for a password under launchd.
            # Ask macOS for a normal user-level restart instead (apps get the chance to quit cleanly).
            res = subprocess.run(["osascript", "-e", 'tell application "System Events" to restart'],
                                 capture_output=True, text=True, timeout=15)
            if res.returncode != 0:
                return jsonify({"status": "error", "message": res.stderr.strip() or "Restart request failed"})
            return jsonify({"status": "success"})
        import shlex
        res = subprocess.run(["zsh", "-c", f"source ~/.zshrc; arrakis {shlex.quote(cmd)}"], capture_output=True, text=True)
        if res.returncode != 0:
            return jsonify({"status": "error", "message": (res.stderr or res.stdout).strip()[-500:] or f"{cmd} failed", "stdout": res.stdout, "stderr": res.stderr})
        return jsonify({"status": "success", "stdout": res.stdout, "stderr": res.stderr})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@system_bp.route('/vm/command/<path:cmd>', methods=['POST'])
def vm_command(cmd):
    try:
        allowed = ['restart', 'reboot', 'update']
        if cmd not in allowed: return jsonify({"status": "error", "message": "Unauthorized command"})
        from app.core.config import VM_NAME
        if cmd in ('restart', 'reboot'):
            res = subprocess.run(["orb", "restart", VM_NAME], capture_output=True, text=True, timeout=120)
        else:
            # whichever package manager the machine's distro has (Alpine, Debian/Ubuntu, Fedora, Arch)
            script = ("if command -v apk >/dev/null; then apk update && apk upgrade; "
                      "elif command -v apt-get >/dev/null; then apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y upgrade; "
                      "elif command -v dnf >/dev/null; then dnf -y upgrade; "
                      "elif command -v pacman >/dev/null; then pacman -Syu --noconfirm; "
                      "else echo 'no known package manager' >&2; exit 1; fi")
            res = subprocess.run(["orb", "-m", VM_NAME, "-u", "root", "sh", "-c", script], capture_output=True, text=True, timeout=1800)
        if res.returncode != 0:
            return jsonify({"status": "error", "message": (res.stderr or res.stdout).strip()[-500:] or f"{cmd} failed", "stdout": res.stdout, "stderr": res.stderr})
        return jsonify({"status": "success", "stdout": res.stdout, "stderr": res.stderr})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

SECRET_PREFS = ('alerts_discord_webhook', 'alerts_ntfy_url', 'alerts_telegram_token', 'alerts_pushover_user',
                'alerts_pushover_token', 'alerts_email_password', 'alerts_webhook_url')


def _mask(url):
    """Recognisable but useless copy of a secret: a URL's host and the last 4 characters,
    or just the last 4 characters of a token or password."""
    if not url:
        return url
    if '://' not in url:
        return '••••' + url[-4:] if len(url) > 8 else '••••'
    from urllib.parse import urlparse
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}/…{url[-4:]}"


# two saves at once (the Overview and its widgets save separately) must not undo each other
import threading as _threading
_prefs_lock = _threading.Lock()


@system_bp.route('/prefs', methods=['GET', 'POST'])
def handle_prefs():
    prefs_file = paths.state('prefs')
    import json
    if request.method == 'POST':
        incoming = request.get_json(silent=True)
        if not isinstance(incoming, dict):
            return jsonify({"status": "error", "message": "Expected a JSON object"}), 400
        try:
            with _prefs_lock:
                prefs = {}
                if os.path.exists(prefs_file):
                    with open(prefs_file, 'r') as f:
                        prefs = json.load(f)
                for k in SECRET_PREFS:
                    # the browser only ever saw the masked value; sending it back means "unchanged"
                    if k in incoming and incoming[k] and incoming[k] == _mask(prefs.get(k)):
                        del incoming[k]
                prefs.update(incoming)
                # written whole, then swapped in, so a read never sees half a file
                tmp = prefs_file + '.tmp'
                with open(tmp, 'w') as f:
                    json.dump(prefs, f)
                os.replace(tmp, prefs_file)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    else:
        try:
            if os.path.exists(prefs_file):
                with open(prefs_file, 'r') as f:
                    prefs = json.load(f)
                    for k in SECRET_PREFS:
                        if prefs.get(k):
                            prefs[k] = _mask(prefs[k])
                    return jsonify({"status": "success", "data": prefs})
        except Exception:
            pass
        return jsonify({"status": "success", "data": {}})

@system_bp.route('/log_error')
def log_error():
    msg = request.args.get('msg', '')[:1000].replace('\n', ' ')
    log.error(f"BROWSER ERROR: {msg}")
    return "ok"

@system_bp.route('/host/info', methods=['GET'])
def host_info():
    from app.core.cache import global_state
    import platform
    with global_state.lock:
        details = global_state.stats.get("host", {}).get("details", {})
    return jsonify({
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.mac_ver()[0]}",
        "arch": platform.machine(),
        "uptime": details.get("Uptime", "Unknown"),
        "local_ip": details.get("Local IP", "Unknown"),
        "tailscale_ip": details.get("Tailscale IP", "Unknown")
    })

@system_bp.route('/vm/info', methods=['GET'])
def vm_info():
    from app.core.cache import global_state
    from app.core.config import VM_NAME
    with global_state.lock:
        details = global_state.stats.get("vm", {}).get("details", {})
    return jsonify({
        "hostname": VM_NAME,
        "os": "Linux (OrbStack)",
        "uptime": details.get("Uptime", "Unknown"),
        "local_ip": details.get("Local IP", "Unknown"),
        "tailscale_ip": details.get("Tailscale IP", "Unknown")
    })

@system_bp.route('/host/updates', methods=['GET'])
def updates_host():
    from app.core.cache import global_state
    with global_state.lock:
        updates = global_state.bg.get("updates_host", "0 pending")
    return jsonify({
        "status_text": updates,
        "is_fetching": "Fetching" in updates
    })

@system_bp.route('/vm/updates', methods=['GET'])
def updates_vm():
    from app.core.cache import global_state
    with global_state.lock:
        updates = global_state.bg.get("updates_vm", "0 pending")
    return jsonify({
        "status_text": updates if "pending" in str(updates) else f"{updates} pending",
        "is_fetching": "Fetching" in str(updates)
    })

@system_bp.route('/network/tailscale', methods=['GET'])
def get_tailscale():
    try:
        import subprocess, json
        ts = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=5)
        ts_data = json.loads(ts.stdout)
        ts_list = []
        for _peer_id, peer in ts_data.get('Peer', {}).items():
            dns = peer.get('DNSName', '')
            if not dns: continue
            name = dns.split('.')[0]
            if name == 'localhost':
                name = peer.get('HostName', '')
            state = 'active' if peer.get('Active') else 'idle' if peer.get('Online') else 'offline'
            ip = peer.get('TailscaleIPs', [''])[0]
            os_val = peer.get('OS', '')
            ts_list.append({"host": name, "ip": ip, "os": os_val, "state": state, "last_seen": peer.get('LastSeen', '')})
            
        # Add self (host)
        self_node = ts_data.get('Self', {})
        if self_node:
            name = self_node.get('DNSName', '').split('.')[0]
            if name == 'localhost' or not name: name = self_node.get('HostName', '')
            ts_list.insert(0, {"host": name, "ip": self_node.get('TailscaleIPs', [''])[0], "os": self_node.get('OS', ''), "state": "active", "last_seen": "now"})
            
        return jsonify({"status": "success", "data": ts_list})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@system_bp.route('/host/metrics', methods=['GET'])
def host_metrics():
    # Return a smaller, specific payload
    from app.core.cache import global_state
    with global_state.lock:
        stats = global_state.stats.get("host", {}).get("details", {})
    return jsonify({
        "cpu": stats.get("CPU Usage", "0%"),
        "memory": stats.get("Memory", "0G / 0G"),
        "disk": stats.get("Disk Space", "0G / 0G")
    })

@system_bp.route('/vm/metrics', methods=['GET'])
def vm_metrics():
    from app.core.cache import global_state
    with global_state.lock:
        stats = global_state.stats.get("vm", {}).get("details", {})
    return jsonify({
        "cpu": stats.get("CPU Usage", "0%"),
        "memory": stats.get("Memory", "0G / 0G"),
        "disk": stats.get("Disk Space", "0G / 0G")
    })

@system_bp.route('/latency', methods=['GET'])
def get_latency_history():
    from app.core.db import get_recent_latencies
    limit = request.args.get('limit', 5, type=float)
    data = get_recent_latencies(limit)
    return jsonify({"status": "success", "data": data})





def fetch_host_daemons_data():
    try:
        import psutil
        import time
        services = [
            {"id": "dashboard", "name": "Homelab Dashboard", "status": "stopped", "pid": None, "type": "python"},
            {"id": "tailscale", "name": "Tailscale", "status": "stopped", "pid": None, "type": "app"},
            {"id": "jellyfin", "name": "Jellyfin Media Server", "status": "stopped", "pid": None, "type": "app"},
            {"id": "orbstack", "name": "OrbStack VM Engine", "status": "stopped", "pid": None, "type": "app"},
            {"id": "qbittorrent", "name": "qBittorrent", "status": "stopped", "pid": None, "type": "app"}
        ]
        
        for p in psutil.process_iter(['name', 'cmdline', 'pid', 'create_time', 'memory_info']):
            try:
                cmd = ' '.join(p.info.get('cmdline') or [])
                name = p.info.get('name') or ''
                idx = -1
                if 'server.py' in cmd and 'Python' in cmd: idx = 0
                elif 'tailscaled' in name or 'Tailscale' in name: idx = 1
                elif 'jellyfin' in name.lower() or 'Jellyfin' in cmd: idx = 2
                elif 'OrbStack' in name: idx = 3
                elif 'qBittorrent.app/' in cmd or name.lower() == 'qbittorrent': idx = 4
                
                if idx >= 0:
                    services[idx]['status'] = 'running'
                    services[idx]['pid'] = p.info.get('pid')
                    
                    create_time = p.info.get('create_time')
                    if create_time:
                        services[idx]['uptime_seconds'] = int(time.time() - create_time)
                    
                    try:
                        mem_info = p.info.get('memory_info')
                        if mem_info and hasattr(mem_info, 'rss') and mem_info.rss:
                            services[idx]['mem_mb'] = round(mem_info.rss / (1024 * 1024), 1)
                        else:
                            services[idx]['mem_mb'] = 0.0
                    except Exception:
                        pass
                        
                    try:
                        services[idx]['cpu'] = p.cpu_percent(interval=None)
                    except Exception:
                        pass

                    # Root-owned daemons (e.g. tailscaled) deny psutil memory/cpu reads; ps can still see them
                    if not services[idx].get('mem_mb') or 'cpu' not in services[idx]:
                        try:
                            out = subprocess.run(["ps", "-o", "rss=,%cpu=", "-p", str(p.info['pid'])],
                                                 capture_output=True, text=True, timeout=2).stdout.split()
                            if len(out) == 2:
                                services[idx]['mem_mb'] = round(int(out[0]) / 1024, 1)
                                services[idx].setdefault('cpu', float(out[1]))
                        except Exception:
                            pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
                
        return services
    except Exception as e:
        from app.core.logger import log
        log.error(f"Error fetching host daemons: {e}")
        return []

@system_bp.route('/host/daemons', methods=['GET'])
def get_host_daemons():
    try:
        from app.core.cache import global_state
        data = global_state.stats.get('daemons', []) if global_state.stats else []
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})




def _parse_docker_uptime(status_str):
    """Parse Docker Status like 'Up 29 minutes (healthy)' -> seconds int."""
    import re as _re
    s = status_str.split('(')[0].replace('Up ', '').strip()
    # Docker words small amounts: "About an hour", "About a minute", "Less than a second"
    s = _re.sub(r'\b(an|a)\s+(week|day|hour|minute|second)', r'1 \2', s)
    total = 0
    for val, unit in _re.findall(r'(\d+)\s*(week|day|hour|minute|second)s?', s):
        v = int(val)
        if unit == 'week':   total += v * 604800
        elif unit == 'day':  total += v * 86400
        elif unit == 'hour': total += v * 3600
        elif unit == 'minute': total += v * 60
        elif unit == 'second': total += v
    return total


def fetch_vm_containers_data():
    if not shutil.which("orb"):
        return []
    try:
        import json
        import re as _re_mod
        import time
        from app.core.config import VM_CMD_PREFIX
        import subprocess
        
        # 1. Get docker ps
        cmd = VM_CMD_PREFIX + ["docker", "ps", "-a", "--format", "{{json .}}"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        
        # 2. Get docker stats for memory (running containers only)
        stats_cmd = VM_CMD_PREFIX + ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}"]
        stats_res = subprocess.run(stats_cmd, capture_output=True, text=True, timeout=5)
        
        stats_map = {}
        for s_line in stats_res.stdout.strip().split('\n'):
            if not s_line.strip(): continue
            parts = s_line.split('|')
            if len(parts) >= 3:
                name = parts[0]
                mem = parts[1].split(' / ')[0] # e.g. "11.41MiB"
                mem_val = 0.0
                if 'GiB' in mem: mem_val = float(mem.replace('GiB','').strip()) * 1024
                elif 'MiB' in mem: mem_val = float(mem.replace('MiB','').strip())
                elif 'KiB' in mem: mem_val = float(mem.replace('KiB','').strip()) / 1024
                
                cpu = parts[2].replace('%', '').strip()
                stats_map[name] = { "mem_mb": round(mem_val, 1), "cpu": cpu }
        
        # exact start times; `docker ps` only says "About an hour"
        started_at = {}
        try:
            from datetime import datetime
            ins = subprocess.run(VM_CMD_PREFIX + ["sh", "-c", "docker ps -q | xargs -r docker inspect -f '{{.Name}}|{{.State.StartedAt}}'"], capture_output=True, text=True, timeout=5)
            for l in ins.stdout.split('\n'):
                if '|' not in l: continue
                n, iso = l.split('|', 1)
                iso = iso.strip()
                m = _re_mod.match(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)', iso)
                if m:
                    tz = '+00:00' if m.group(3) == 'Z' else m.group(3)
                    started_at[n.lstrip('/')] = datetime.fromisoformat(m.group(1) + tz).timestamp()
        except Exception:
            pass

        services = []
        for line in res.stdout.strip().split('\n'):
            if not line.strip(): continue
            try:
                c = json.loads(line)
                is_running = c.get("State") == "running"
                name = c.get("Names")
                
                c_data = {
                    "id": name,
                    "name": name,
                    "status": "running" if is_running else "stopped",
                    "health": c.get("Status", "").split("(")[-1].strip(")") if "(health" in c.get("Status", "") else None,
                    "image": c.get("Image"),
                    "ports": c.get("Ports", "")
                }
                
                c_data["uptime_seconds"] = 0
                if is_running:
                    started = started_at.get(name)
                    c_data["uptime_seconds"] = int(time.time() - started) if started else _parse_docker_uptime(c.get("Status", ""))
                
                if name in stats_map:
                    c_data["mem_mb"] = stats_map[name]["mem_mb"]
                    c_data["cpu"] = stats_map[name]["cpu"]
                    
                services.append(c_data)
            except Exception: pass
        return services
    except Exception as e:
        from app.core.logger import log
        log.error(f"Error fetching VM containers: {e}")
        return []

@system_bp.route('/vm/containers', methods=['GET'])
def get_vm_containers():
    try:
        from app.core.cache import global_state
        data = global_state.stats.get('containers', []) if global_state.stats else []
        return jsonify({"status": "success", "data": data})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})



@system_bp.route('/retention', methods=['GET'])
def get_retention():
    """How long each kind of history is kept, with its current size."""
    from app.core import db
    days, rows = db.keep_days(), db.table_rows()
    return jsonify({"status": "success", "data": [
        {"id": k, "label": label, "days": days[k], "default": default, "max": most, **rows.get(k, {})}
        for k, (_t, label, default, most) in db.KEEP.items()]})


@system_bp.route('/retention', methods=['PATCH'])
def set_retention():
    """{kind: days}: keep that history this long. Older rows are deleted right away."""
    from app.core import db
    body = request.get_json(silent=True) or {}
    prefs_file = paths.state('prefs')
    try:
        with open(prefs_file) as f:
            prefs = json.load(f)
    except (OSError, ValueError):
        prefs = {}
    keep = prefs.get("data_keep") or {}
    for k, v in body.items():
        if k not in db.KEEP:
            return jsonify({"status": "error", "message": f"Unknown history {k}"})
        try:
            v = int(v)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": f"{k}: not a number"})
        if not 1 <= v <= db.KEEP[k][3]:
            return jsonify({"status": "error", "message": f"{db.KEEP[k][1]}: 1 to {db.KEEP[k][3]} days"})
        keep[k] = v
    prefs["data_keep"] = keep
    with open(prefs_file, 'w') as f:
        json.dump(prefs, f)
    db.cleanup_old_metrics()
    return jsonify({"status": "success"})


@system_bp.route('/endpoints', methods=['GET'])
def get_endpoints_config():
    """Catalog for the API endpoints page: every route, grouped, with its parameters.

    A param named in the path (`{name}`) fills the path; others go in the query
    string for GET/DELETE and in a JSON body otherwise.
    """
    from app.core.config import VM_NAME
    def ep(id, method, path, desc, *params):
        return {"id": id, "method": method, "path": path, "desc": desc,
                "params": [{"key": k, "placeholder": ph, "type": t, "value": v} for k, ph, t, v in params] or None}

    def p(key, placeholder='', type='text', value=''):
        return (key, placeholder, type, value)

    groups = [
        {"name": "This server", "endpoints": [
            ep("host-metrics", "GET", "/api/host/metrics", "Live CPU, memory, disk and network of the Mac"),
            ep("host-info", "GET", "/api/host/info", "Static machine and OS details"),
            ep("host-updates", "GET", "/api/host/updates", "Pending package updates on the Mac"),
            ep("host-daemons", "GET", "/api/host/daemons", "Daemons the dashboard watches on the Mac"),
            ep("host-ssh-kill", "DELETE", "/api/host/ssh/{tty}", "End an SSH session on the Mac", p("tty", "pts/0")),
            ep("host-command", "POST", "/api/host/command/{cmd}", "Run a pre-approved action on the Mac", p("cmd", "backup")),
        ]},
        {"name": "Machines", "endpoints": [
            ep("vms-list", "GET", "/api/vms", "Machines, the shared pool and host resources (cached)"),
            ep("vms-usage", "GET", "/api/vms/usage", "Latest CPU, memory and workload counts of every machine"),
            ep("vms-stats", "GET", "/api/vms/{name}/stats", "Latest usage of one machine", p("name", VM_NAME)),
            ep("vms-history", "GET", "/api/vms/{name}/history", "Last hour of usage samples", p("name", VM_NAME)),
            ep("vms-workloads", "GET", "/api/vms/{name}/workloads", "Containers, systemd services and listening ports", p("name", VM_NAME)),
            ep("vms-images", "GET", "/api/vms/images", "Distros, versions and architectures to create from"),
            ep("vms-create", "POST", "/api/vms", "Create a machine (runs in the background)", p("name", "dev"), p("distro", "ubuntu"), p("version", "noble")),
            ep("vms-action", "POST", "/api/vms/{name}/{action}", "Start, stop, restart or delete a machine", p("name", VM_NAME), p("action", "restart")),
            ep("vms-limits", "PATCH", "/api/vms/{name}/limits", "CPU, memory and disk limit (0 = none; applies after restart)", p("name", VM_NAME), p("cpu", "2", "number"), p("memory_mib", "4096", "number"), p("disk_gib", "32", "number")),
            ep("vms-isolation", "PATCH", "/api/vms/{name}/isolation", "Isolate from the Mac's files / network (refused off while shared; applies after restart)", p("name", VM_NAME), p("isolated", "true", "json"), p("isolate_network", "false", "json")),
            ep("vms-options", "PATCH", "/api/vms/{name}/options", "Shared folders, SSH agent forwarding and .orb.local web ports (applies after restart)", p("name", VM_NAME), p("mounts", '[{"source": "/Users/you/Projects", "dest": "/mnt/projects"}]', "json"), p("forward_ssh_agent", "false", "json"), p("http_port", "0 = automatic", "number"), p("https_port", "0 = automatic", "number")),
            ep("vms-system-get", "GET", "/api/vms/{name}/system", "Timezone and automatic updates inside a running machine", p("name", VM_NAME)),
            ep("vms-system-set", "PATCH", "/api/vms/{name}/system", "Set timezone / daily automatic updates inside the machine (applies at once)", p("name", VM_NAME), p("timezone", "Europe/Brussels"), p("autoupdate", "true", "json")),
            ep("vms-rename", "POST", "/api/vms/{name}/rename", "Rename a machine", p("name", "test"), p("new_name", "test2")),
            ep("vms-pool", "PATCH", "/api/vms/pool", "Resize the shared pool (applies after restart)", p("cpu", "10", "number"), p("memory_mib", "12288", "number")),
            ep("vms-pool-restart", "POST", "/api/vms/pool/restart", "Restart OrbStack so a new pool size applies"),
            ep("vms-ts-join", "POST", "/api/vms/{name}/tailscale/join", "Join a machine to the tailnet (background job)", p("name", "test")),
            ep("vms-ts-leave", "POST", "/api/vms/{name}/tailscale/leave", "Log a machine out of the tailnet", p("name", "test")),
            ep("vms-ts-key", "GET", "/api/vms/tailscale/key", "Whether a Tailscale auth key is stored (never the key)"),
            ep("vms-job-dismiss", "DELETE", "/api/vms/jobs/{name}", "Dismiss a finished or failed creation job", p("name", "dev")),
        ]},
        {"name": "Sharing", "endpoints": [
            ep("share-start", "PUT", "/api/vms/{name}/share", "Share a machine over SSH at <name>.<domain> (isolates it first; background job)", p("name", "test")),
            ep("share-stop", "DELETE", "/api/vms/{name}/share", "Stop sharing: removes the address and every added person", p("name", "test")),
            ep("share-key-add", "POST", "/api/vms/{name}/share/keys", "Add a person: their key, login name and permissions (perms = a preset's perms from GET /api/vms sharing.permissions)", p("name", "test"), p("key", "ssh-ed25519 AAAA… stilgar@laptop"), p("label", "Stilgar's laptop"), p("username", "stilgar"), p("perms", '{"root": "none", "net": "internet", "pids": 256}', "json")),
            ep("share-key-perms", "PUT", "/api/vms/{name}/share/keys/perms", "Change one person's permissions (applied in the machine at once)", p("name", "test"), p("fp", "SHA256:…"), p("perms", '{"access": "shell", "root": "some", "sudo": ["packages"], "docker": false, "net": "internet", "forward": false, "procs": false, "cpu": 1, "mem_mib": 512, "pids": 256, "expires": "2026-12-31"}', "json")),
            ep("share-key-label", "PATCH", "/api/vms/{name}/share/keys", "Rename a key", p("name", "test"), p("fp", "SHA256:…"), p("label", "Stilgar's laptop")),
            ep("share-key-remove", "DELETE", "/api/vms/{name}/share/keys", "Remove a person (their login user and home go too)", p("name", "test"), p("fp", "SHA256:…")),
        ]},
        {"name": "Hosts", "endpoints": [
            ep("hosts-list", "GET", "/api/hosts", "Other hosts in the cluster with their latest agent report"),
            ep("hosts-get", "GET", "/api/hosts/{hid}", "One host and its latest report", p("hid", "my-laptop")),
            ep("hosts-history", "GET", "/api/hosts/{hid}/history", "Last hour of a host's CPU and memory", p("hid", "my-laptop")),
            ep("hosts-install", "GET", "/api/hosts/{hid}/install", "The one-line install command for a host's agent", p("hid", "my-laptop")),
            ep("hosts-add", "POST", "/api/hosts", "Add a host (returns its install command)", p("name", "my-laptop")),
            ep("hosts-remove", "DELETE", "/api/hosts/{hid}", "Remove a host from the dashboard", p("hid", "my-laptop")),
        ]},
        {"name": "Services", "endpoints": [
            ep("vm-containers", "GET", "/api/vm/containers", "Docker containers on the dashboard machine"),
            ep("svc-uptime", "GET", "/api/services/uptime", "24 h availability per service", p("hours", "24", "number", "24"), p("buckets", "48", "number", "48")),
            ep("svc-metrics", "GET", "/api/services/metrics/{kind}/{service_id}", "CPU and memory history of one service", p("kind", "container", "text", "container"), p("service_id", "nginx"), p("hours", "1", "number", "1")),
            ep("svc-logs", "GET", "/api/services/logs/{kind}/{service_id}", "Recent log lines of one service", p("kind", "container", "text", "container"), p("service_id", "nginx"), p("lines", "200", "number", "50")),
            ep("svc-daemon-action", "POST", "/api/services/daemons/action/{daemon_id}/{action}", "Start, stop or restart a Mac daemon (event stream)", p("daemon_id", "jellyfin"), p("action", "restart")),
            ep("svc-container-action", "GET", "/api/services/containers/action/{container_id}/{action}", "Start, stop or restart a container (event stream)", p("container_id", "pihole"), p("action", "restart")),
        ]},
        {"name": "Tailscale", "endpoints": [
            ep("ts-status", "GET", "/api/tailscale", "Every device on the tailnet as this Mac sees it"),
            ep("ts-ping", "POST", "/api/tailscale/ping/{ip}", "Ping a device and report direct or relayed", p("ip", "100.64.0.1")),
            ep("net-speedtest", "GET", "/api/network/speedtest", "Latest speed test result"),
            ep("net-speedtest-run", "POST", "/api/network/speedtest", "Start a speed test"),
        ]},
        {"name": "Databases", "endpoints": [
            ep("db-list", "GET", "/api/databases", "SQLite databases with their tables and row counts"),
            ep("db-rows", "GET", "/api/databases/{db_id}/tables/{table}/rows", "Rows of one table, newest first (read-only)", p("db_id", "metrics.db", "text", "metrics.db"), p("table", "metrics", "text", "metrics"), p("limit", "50", "number", "5")),
            ep("db-query", "POST", "/api/databases/{db_id}/query", "Run one read-only SQL statement", p("db_id", "metrics.db", "text", "metrics.db"), p("sql", "SELECT COUNT(*) FROM metrics", "text", "SELECT COUNT(*) FROM metrics")),
        ]},
        {"name": "Tools", "endpoints": [
            ep("tool-ping", "POST", "/api/tools/ping", "Ping a host from the Mac", p("host", "1.1.1.1", "text", "1.1.1.1")),
            ep("tool-port", "POST", "/api/tools/port", "Is a TCP port open, as seen from the Mac", p("host", "localhost", "text", "localhost"), p("port", "5050", "number", "5050")),
            ep("tool-dns", "POST", "/api/tools/dns", "Resolve a name with the Mac's DNS", p("host", "github.com", "text", "github.com")),
        ]},
        {"name": "Backups", "endpoints": [
            ep("bk-details", "GET", "/api/backups/details", "Snapshots with their files, last and next run"),
            ep("bk-list", "GET", "/api/backups", "Snapshot names"),
            ep("bk-config", "GET", "/api/backups/config", "Backup schedule and retention"),
            ep("bk-config-set", "PATCH", "/api/backups/config", "Change the schedule", p("frequency", "daily"), p("hour", "4", "number", "4"), p("minute", "0", "number", "0"), p("retention", "4", "number", "4")),
            ep("bk-delete", "DELETE", "/api/backups/{timestamp}", "Delete a snapshot", p("timestamp", "2026-11-12_04-00-02")),
        ]},
        {"name": "Terminal", "endpoints": [
            ep("tmux-list", "GET", "/api/tmux/sessions", "tmux sessions on the Mac and every running machine"),
            ep("tmux-create", "POST", "/api/tmux/sessions", "Start a session (installs tmux in a machine that lacks it)", p("name", "work"), p("target", "mac or a machine name"), p("command", "(optional)")),
            ep("tmux-log", "GET", "/api/tmux/sessions/{session}/log", "Last 100 lines of a session", p("session", f"{VM_NAME}:work")),
            ep("tmux-rename", "PATCH", "/api/tmux/sessions/{session}", "Rename a session", p("session", f"{VM_NAME}:work"), p("new_name", "work2")),
            ep("tmux-kill", "DELETE", "/api/tmux/sessions/{session}", "End a session", p("session", f"{VM_NAME}:work")),
        ]},
        {"name": "Dashboard", "endpoints": [
            ep("stats", "GET", "/api/stats", "The live payload the dashboard streams"),
            ep("history", "GET", "/api/history", "Host and VM metric timeline", p("hours", "24", "number", "1")),
            ep("latency", "GET", "/api/latency", "Recent response times per endpoint", p("limit", "5", "number", "5")),
            ep("endpoints", "GET", "/api/endpoints", "This catalog"),
            ep("prefs", "GET", "/api/prefs", "Saved dashboard preferences"),
        ]},
    ]
    return jsonify({"status": "success", "data": _with_discovered(groups)})


# What each group is for (shown above its endpoints), and where routes nobody described go.
GROUP_DOCS = {
    "This server": "The Mac itself: live metrics, OS details, daemons and pre-approved commands.",
    "Machines": "OrbStack machines: create, start/stop, limits, isolation, folders and system settings.",
    "Sharing": "Public SSH access to machines and each person's permissions.",
    "Hosts": "Other computers reporting in through the agent.",
    "Services": "Containers and daemons, their logs and history.",
    "Tailscale": "The tailnet as this server sees it, and network tests.",
    "Databases": "Read-only look at the dashboard's SQLite files.",
    "Storage": "Drives and volumes on the Mac.",
    "Compute": "Compute pools and their jobs.",
    "Backups": "Backup snapshots and their schedule.",
    "Terminal": "tmux sessions on the Mac and in machines.",
    "Tools": "Small utilities like ping and port checks.",
    "Uptime": "Websites and services checked on a schedule, with certificate expiry.",
    "Hardware": "Temperatures, drive health (SMART) and UPS power, of this server and other hosts.",
    "Logs": "One search across every container's logs and the Mac apps' log files.",
    "Updates": "Outdated packages on the Mac, its machines and other hosts, and applying them.",
    "Apps": "Install apps from the catalogue into a machine; update, restart or remove Compose apps.",
    "Pi-hole": "Pi-hole's numbers for today and pausing its blocking.",
    "Dashboard": "The dashboard's own data: stats stream, history, preferences and this catalog.",
    "Internal": "Plumbing for the agent, live streams and the terminal. Not meant to be called by hand.",
}
_BP_GROUP = {"vms": "Machines", "hosts": "Hosts", "compute": "Compute", "storage": "Storage", "tailscale": "Tailscale",
             "databases": "Databases", "backups": "Backups", "tmux": "Terminal", "services": "Services",
             "uptime": "Uptime", "hardware": "Hardware", "logs": "Logs", "updates": "Updates", "apps": "Apps", "pihole": "Pi-hole"}


# Descriptions for routes whose view has no docstring (keyed "METHOD path").
ROUTE_DOCS = {
    "GET /api/vms/cloudflare/token": "Whether a Cloudflare API token is stored (never the token)",
    "PUT /api/vms/cloudflare/token": "Store the Cloudflare API token used for public SSH sharing",
    "DELETE /api/vms/cloudflare/token": "Forget the Cloudflare API token",
    "PUT /api/vms/tailscale/key": "Store the Tailscale auth key used to join machines",
    "DELETE /api/vms/tailscale/key": "Forget the Tailscale auth key",
    "PATCH /api/hosts/{hid}": "Change a host's settings, e.g. {\"orb_manage\": true} to manage its OrbStack",
    "GET /api/hosts/{hid}/actions": "Recent actions sent to a host and their results",
    "POST /api/hosts/{hid}/actions": "Ask a host's agent to run an action (restart, update, vm-start…)",
    "GET /api/hosts/{hid}/disk": "A host's disk usage",
    "GET /api/hosts/{hid}/machines": "OrbStack machines on that host (from its last inventory)",
    "GET /api/hosts/{hid}/storage": "Drives and volumes on that host (from its last inventory)",
    "GET /api/hosts/install.sh": "The agent install script hosts download",
    "POST /api/hosts/inventory": "From the agent: drives, volumes and OrbStack machines, every minute",
    "POST /api/hosts/report": "From the agent: one metrics report",
    "GET /api/services/history": "CPU and memory history of every service",
    "GET /api/network/tailscale": "Tailscale status for the network widgets",
    "POST /api/backups/{timestamp}/reveal": "Show a snapshot in Finder",
    "GET /api/backups/file/{name}": "Download one backup file",
    "POST /api/alerts/test": "Send a test alert to every configured channel",
    "GET /api/uptime": "Uptime checks with their last result, 24 h history and certificate expiry",
    "POST /api/uptime": "Add an uptime check (name, url, every, expect) and run it once",
    "PUT /api/uptime/{cid}": "Change an uptime check",
    "DELETE /api/uptime/{cid}": "Remove an uptime check and its history",
    "POST /api/uptime/{cid}/run": "Run an uptime check now",
    "GET /api/hardware": "This server's temperatures, drive health and power source",
    "GET /api/hardware/{hid}": "The same for another host, from its agent's last inventory",
    "GET /api/logs/sources": "Machines and Mac apps whose logs can be searched",
    "GET /api/logs/search": "Search logs: q, since (15m 1h 6h 24h 7d), problems=1, source (mac or a machine), regex=1",
    "GET /api/updates": "Outdated packages per computer, and update jobs in progress",
    "POST /api/updates/check": "Look for updates again now (all, or one target)",
    "POST /api/updates/{tid}/apply": "Upgrade a computer's packages (all, or the ones listed)",
    "POST /api/hosts/{hid}/wake": "Wake-on-LAN: send the magic packet to a host's learned MAC address",
    "GET /api/log_error": "Record a front-end error in the backend log",
    "POST /api/prefs": "Save dashboard preferences",
    "GET /api/stats_stream": "Live stats as Server-Sent Events",
    "GET /api/storage": "Disk usage per folder on the Mac",
    "GET /api/storage/forecast": "When the Mac's disk will be full at the current rate",
    "GET /api/term": "Terminal WebSocket (tmux attach)",
    "POST /api/vm/command/{cmd}": "Run a pre-approved action in the dashboard machine (reboot, update)",
    "GET /api/vm/info": "OS details of the dashboard machine",
    "GET /api/vm/metrics": "Live CPU, memory and disk of the dashboard machine",
    "DELETE /api/vm/ssh/{tty}": "End an SSH session in the dashboard machine",
    "GET /api/vm/updates": "Pending package updates in the dashboard machine",
    "GET /api/compute/pools": "Compute pools with their state and running jobs",
    "POST /api/compute/pools": "Create a pool",
    "GET /api/compute/pools/{name}": "One pool: its definition, computers and state",
    "PATCH /api/compute/pools/{name}": "Change a pool's definition",
    "DELETE /api/compute/pools/{name}": "Delete a pool (its folder goes to the trash)",
    "POST /api/compute/pools/{name}/{kind}": "Start, stop or restart a pool",
    "GET /api/compute/pools/{name}/file": "Read one file from the pool's folder",
    "PUT /api/compute/pools/{name}/file": "Write one file in the pool's folder",
    "DELETE /api/compute/pools/{name}/file": "Delete one file from the pool's folder",
    "GET /api/compute/pools/{name}/files": "Files in the pool's folder",
    "GET /api/compute/pools/{name}/jobs": "Runs of a pool, newest first",
    "POST /api/compute/pools/{name}/jobs": "Run a script on the pool",
    "DELETE /api/compute/pools/{name}/jobs/{jid}": "Delete a finished run",
    "POST /api/compute/pools/{name}/jobs/{jid}/stop": "Stop a running job",
    "POST /api/compute/ssh-check": "Check the dashboard can SSH into a computer",
    "GET /api/storage/disks": "Drives and volumes on the Mac",
    "POST /api/storage/disks/{did}/eject": "Eject an external drive",
    "POST /api/storage/volumes/{vid}/{action}": "Mount or unmount a volume",
}
# Plumbing the agent, the page itself or streams use; listed separately.
INTERNAL = {"POST /api/hosts/inventory", "POST /api/hosts/report", "POST /api/hosts/result", "GET /api/hosts/rpc",
            "POST /api/hosts/rpc/{jid}", "GET /api/hosts/install.sh", "GET /api/log_error", "GET /api/stream",
            "GET /api/stats_stream", "GET /api/term"}


def _with_discovered(groups):
    """Add every real /api route the hand-written catalog doesn't list, so the page can never
    fall behind the code. Descriptions come from the view's docstring. Routes mounted twice
    (vms under /api/hosts/<hid>/vms) are listed once."""
    from flask import current_app
    real = set()
    for rule in current_app.url_map.iter_rules():
        path = _re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"{\1}", rule.rule).rstrip("/") or "/"
        real |= {(m, path) for m in (rule.methods or set()) - {"HEAD", "OPTIONS"}}
    # a hand-written entry whose method/path doesn't exist lends its text to the real route
    lent = {}
    for g in groups:
        for e in list(g["endpoints"]):
            if (e["method"], e["path"]) not in real:
                g["endpoints"].remove(e)
                lent[e["path"]] = (g["name"], e)
    known = {(e["method"], e["path"]) for g in groups for e in g["endpoints"]}
    by_name = {g["name"]: g for g in groups}
    seen = set()
    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: r.rule):
        if not rule.rule.startswith("/api/") or rule.endpoint.startswith("host_vms."):
            continue
        path = _re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"{\1}", rule.rule).rstrip("/") or "/"
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            if (method, path) in known or (method, path) in seen:
                continue
            seen.add((method, path))
            view = current_app.view_functions.get(rule.endpoint)
            doc = ROUTE_DOCS.get(f"{method} {path}") or " ".join(((view.__doc__ if view else "") or "").strip().split("\n\n")[0].split())
            bp = rule.endpoint.split(".")[0]
            donor = lent.get(path)
            if donor:
                group = donor[0]
                doc = doc or donor[1]["desc"]
            elif f"{method} {path}" in INTERNAL:
                group = "Internal"
            elif bp == "vms" and ("/share" in path or "/sharing/" in path or "/cloudflare/" in path):
                group = "Sharing"
            elif bp in _BP_GROUP:
                group = _BP_GROUP[bp]
            elif path.startswith("/api/host/"):
                group = "This server"
            elif path.startswith(("/api/tools", "/api/network")):
                group = "Tools"
            else:
                group = "Dashboard"
            g = by_name.get(group)
            if not g:
                g = by_name[group] = {"name": group, "endpoints": []}
                groups.append(g)
            params = (donor[1]["params"] if donor and donor[1].get("params") else
                      [{"key": k, "placeholder": "", "type": "text", "value": ""} for k in _re.findall(r"\{(\w+)\}", path)])
            g["endpoints"].append({"id": f"{method.lower()}-{rule.endpoint}".replace(".", "-").replace("_", "-"), "method": method,
                                   "path": path, "desc": doc[:160], "params": params or None, "auto": True})
    groups.sort(key=lambda g: g["name"] == "Internal")
    for g in groups:
        g["doc"] = GROUP_DOCS.get(g["name"], "")
    return [g for g in groups if g["endpoints"]]
