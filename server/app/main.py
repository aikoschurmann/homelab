import os
from flask import Flask, jsonify, request
from flask_sock import Sock

from app.core.logger import log
from app.services.poller import start_all_pollers

def create_app():
    app = Flask(__name__, static_folder='../static')
    app.url_map.strict_slashes = False  # avoid 308 round-trips for /api/databases vs /api/databases/
    sock = Sock(app)

    import logging
    logging.getLogger('werkzeug').setLevel(logging.WARNING)  # per-request access log grew /tmp logs to ~30MB

    import time
    from app.core.db import insert_latency
    
    @app.before_request
    def start_timer():
        request.start_time = time.perf_counter()

    @app.after_request
    def record_latency(response):
        if request.path.startswith('/api/'):
            latency_ms = round((time.perf_counter() - getattr(request, 'start_time', time.perf_counter())) * 1000, 2)
            
            if request.url_rule:
                rule = request.url_rule.rule
                import re
                rule = re.sub(r'<[^>]*:([^>]+)>', r'{\1}', rule)
                rule = re.sub(r'<([^>]+)>', r'{\1}', rule)
                ep_id = f"{request.method} {rule}"
            else:
                ep_id = f"{request.method} {request.path}"
                
            insert_latency(ep_id, latency_ms, response.status_code)
            response.headers['X-Response-Time'] = str(latency_ms)
        return response

    import ipaddress
    from urllib.parse import urlparse

    # Uses the real socket peer only: X-Forwarded-For is client-controlled and
    # there is no reverse proxy in front of this server.
    LOOPBACK = [ipaddress.ip_network(n) for n in ('127.0.0.0/8', '::1/128')]
    TAILNET = ipaddress.ip_network('100.64.0.0/10')

    import subprocess, threading, json as _json
    _peer_cache = {}            # (ip, port) -> (time, allowed)
    _ts = {"at": 0, "mine": set()}
    _ts_lock = threading.Lock()

    def _loopback_allowed(ip, port):
        """OrbStack proxies containers' and machines' traffic to the Mac (host.docker.internal,
        host.orb.internal) through 127.0.0.1, so loopback alone proves nothing. Refuse
        connections opened by OrbStack's helper; everything else really is on the Mac."""
        key = (ip, port)
        hit = _peer_cache.get(key)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        allowed = False
        try:
            out = subprocess.run(['lsof', '-nP', f'-iTCP@{ip}:{port}', '-sTCP:ESTABLISHED', '-Fpc'],
                                 capture_output=True, text=True, timeout=3).stdout
            me, pid, owners = str(os.getpid()), None, []
            for line in out.splitlines():
                if line.startswith('p'):
                    pid = line[1:]
                elif line.startswith('c') and pid != me:
                    owners.append(line[1:])
            allowed = bool(owners) and not any(o.lower().startswith('orbstack') for o in owners)
        except Exception as e:
            log.warning(f"Could not identify loopback peer {ip}:{port}: {e}")
        if len(_peer_cache) > 2000:
            _peer_cache.clear()
        _peer_cache[key] = (time.time(), allowed)
        return allowed

    def _my_tailnet_ips(refresh=False):
        """Tailscale IPs of this tailnet owner's own devices (and tagged ones). Devices of
        people a node was shared with are reachable too, but must not get this dashboard."""
        with _ts_lock:
            age = time.time() - _ts["at"]
            if age > 60 or (refresh and age > 10):
                try:
                    st = _json.loads(subprocess.run(['tailscale', 'status', '--json'], capture_output=True,
                                                    text=True, timeout=5).stdout)
                    me = st['Self']['UserID']
                    mine = set(st['Self'].get('TailscaleIPs') or [])
                    for p in (st.get('Peer') or {}).values():
                        if not p.get('ShareeNode') and (p.get('UserID') == me or p.get('Tags')):
                            mine.update(p.get('TailscaleIPs') or [])
                    _ts.update(at=time.time(), mine=mine)
                except Exception as e:
                    log.warning(f"tailscale status for access check failed: {e}")
                    _ts["at"] = time.time() - 50  # retry soon, keep the last good list
            return _ts["mine"]

    from app.core import access

    def _caller(ip, port):
        """('owner', None) for this Mac and the owner's devices, (role, who) for someone given
        access in Settings → Access, or None."""
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None
        if addr.version == 6 and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        if any(addr in net for net in LOOPBACK):
            return ('owner', None) if _loopback_allowed(ip, port) else None
        if addr in TAILNET:
            # a device that joined in the last minute isn't in the cached list yet
            if str(addr) in _my_tailnet_ips() or str(addr) in _my_tailnet_ips(refresh=True):
                return ('owner', None)
            role, who = access.role_of(str(addr))
            return (role, who) if role else None
        return None

    @app.before_request
    def restrict_ips():
        from flask import g
        ip = request.remote_addr
        c = _caller(ip, request.environ.get('REMOTE_PORT')) if ip else None
        if not c:
            log.warning(f"Blocked request from {ip}")
            return jsonify({"status": "error", "message": "Access denied. Network not trusted."}), 403
        g.role, g.who = c
        if g.role == 'viewer' and not access.viewer_allowed(request.method, request.path):
            return jsonify({"status": "error", "message": "You have read-only access to this dashboard."}), 403

    def _same_origin(origin):
        o, h = urlparse(origin), urlparse('//' + request.host)
        default = 443 if request.scheme == 'https' else 80
        try:
            return bool(o.hostname) and o.hostname == h.hostname and (o.port or default) == (h.port or default)
        except ValueError:
            return False

    @app.before_request
    def block_cross_site():
        # Stops other websites open in a trusted browser from driving the API
        # (CSRF) or opening the terminal WebSocket (cross-site WS hijacking).
        # Requests without these headers (curl, scripts) are unaffected.
        if request.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
            log.warning(f"Blocked cross-site request to {request.path}")
            return jsonify({"status": "error", "message": "Cross-site request blocked."}), 403
        origin = request.headers.get('Origin')
        if origin and not _same_origin(origin):
            log.warning(f"Blocked request with foreign Origin {origin} to {request.path}")
            return jsonify({"status": "error", "message": "Cross-origin request blocked."}), 403

    # Register routes
    from app.api.system import system_bp
    from app.api.tmux import tmux_bp
    from app.api.backups import backups_bp
    from app.api.databases import databases_bp
    from app.api.services import services_bp
    from app.api.vms import vms_bp
    from app.api.tailscale import tailscale_bp
    from app.api.cloudflare import cloudflare_bp
    from app.api.hosts import hosts_bp
    from app.api.storage import storage_bp
    from app.api.compute import compute_bp
    from app.api.server import server_bp
    from app.api.uptime import uptime_bp
    from app.api.hardware import hardware_bp
    from app.api.logs import logs_bp
    from app.api.updates import updates_bp
    from app.api.access import access_bp
    from app.api.apps import apps_bp
    from app.api.pihole import pihole_bp

    app.register_blueprint(system_bp, url_prefix='/api')
    app.register_blueprint(tmux_bp, url_prefix='/api/tmux')
    app.register_blueprint(backups_bp, url_prefix='/api/backups')
    app.register_blueprint(databases_bp, url_prefix='/api/databases')
    app.register_blueprint(services_bp, url_prefix='/api/services')
    app.register_blueprint(vms_bp, url_prefix='/api/vms')
    # the same machine API for another host's OrbStack, through its agent
    app.register_blueprint(vms_bp, url_prefix='/api/hosts/<hid>/vms', name='host_vms')
    app.register_blueprint(tailscale_bp, url_prefix='/api/tailscale')
    app.register_blueprint(cloudflare_bp, url_prefix='/api/cloudflare')
    app.register_blueprint(hosts_bp, url_prefix='/api/hosts')
    app.register_blueprint(storage_bp, url_prefix='/api/storage')
    app.register_blueprint(compute_bp, url_prefix='/api/compute')
    app.register_blueprint(server_bp, url_prefix='/api/server')
    app.register_blueprint(uptime_bp, url_prefix='/api/uptime')
    app.register_blueprint(hardware_bp, url_prefix='/api/hardware')
    app.register_blueprint(logs_bp, url_prefix='/api/logs')
    app.register_blueprint(updates_bp, url_prefix='/api/updates')
    app.register_blueprint(access_bp, url_prefix='/api/access')
    app.register_blueprint(apps_bp, url_prefix='/api/apps')
    app.register_blueprint(pihole_bp, url_prefix='/api/pihole')

    # Register websocket
    from app.websocket.terminal import register_websocket
    from app.websocket.stats import register_stats_websocket
    register_websocket(sock)
    register_stats_websocket(sock)

    @app.route('/')
    def index():
        from flask import make_response
        response = make_response(app.send_static_file('index.html'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        return response

    @app.route('/terminal')
    def terminal():
        return app.send_static_file('terminal.html')

    start_all_pollers()
    log.info("Application initialized.")
    return app
