from flask import Blueprint, jsonify, Response, stream_with_context
import json, time, subprocess

services_bp = Blueprint('services', __name__)

@services_bp.route('/history', methods=['GET'])
def service_history():
    from app.core.db import get_service_history
    data = get_service_history(hours=3)
    return jsonify({"status": "success", "data": data})

@services_bp.route('/metrics/<kind>/<service_id>', methods=['GET'])
def service_metrics(kind, service_id):
    """CPU and memory of one service over the last `hours`, averaged into <= 240 points."""
    import sqlite3
    from flask import request
    from app.core.db import DB_PATH
    if kind not in ('daemon', 'container'):
        return jsonify({"status": "error", "message": "kind must be daemon or container"})
    hours = min(max(request.args.get('hours', 1, type=float), 0.25), 168)
    bucket = max(10, int(hours * 3600 / 240))
    since = int(time.time() - hours * 3600)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        rows = conn.execute(
            'SELECT (timestamp / ?) * ? AS b, AVG(cpu), AVG(mem_mb), MAX(mem_mb) FROM service_metrics '
            'WHERE service_type = ? AND service_id = ? AND timestamp > ? GROUP BY b ORDER BY b',
            (bucket, bucket, kind, service_id, since)).fetchall()
        conn.close()
        return jsonify({"status": "success", "data": {
            "bucket_seconds": bucket,
            "points": [{"t": b, "cpu": round(cpu or 0, 2), "mem": round(mem or 0, 1), "mem_max": round(mx or 0, 1)} for b, cpu, mem, mx in rows],
        }})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@services_bp.route('/daemons/action/<daemon_id>/<action>', methods=['GET', 'POST'])
def daemon_action_stream(daemon_id, action):
    """SSE stream: fires the action and sends status events back."""
    if action not in ['start', 'stop', 'restart']:
        return jsonify({"status": "error", "message": "Invalid action"}), 400

    def generate():
        yield f"data: {json.dumps({'status': 'running', 'msg': f'{action.capitalize()}ing {daemon_id}...'})}\n\n"
        try:
            if daemon_id == 'jellyfin':
                if action in ['stop', 'restart']: subprocess.run(["killall", "-9", "jellyfin"], timeout=5)
                time.sleep(1)
                if action in ['start', 'restart']: subprocess.run(["open", "-a", "Jellyfin"], timeout=5)
            elif daemon_id == 'orbstack':
                if action in ['stop', 'restart']: subprocess.run(["killall", "-9", "OrbStack"], timeout=5)
                time.sleep(1)
                if action in ['start', 'restart']: subprocess.run(["open", "-a", "OrbStack"], timeout=5)
            elif daemon_id == 'qbittorrent':
                # a clean quit (SIGTERM) so torrent progress is saved; the app reopens in the background
                if action in ['stop', 'restart']:
                    subprocess.run(["pkill", "-TERM", "-f", "qBittorrent.app/Contents/MacOS/qbittorrent"], timeout=5)
                    for _ in range(20):
                        if subprocess.run(["pgrep", "-f", "qBittorrent.app/Contents/MacOS/qbittorrent"], capture_output=True).returncode != 0:
                            break
                        time.sleep(0.5)
                if action in ['start', 'restart']: subprocess.run(["open", "-g", "-a", "qBittorrent"], timeout=5)
            elif daemon_id == 'dashboard':
                yield f"data: {json.dumps({'status': 'done', 'msg': 'Restarting dashboard...'})}\n\n"
                import os, signal, threading
                threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGTERM)).start()
                return
            
            from app.services.alerts import notify_action
            notify_action('daemon', daemon_id, action)

            # Instantly update cache
            try:
                from app.api.system import fetch_host_daemons_data
                from app.core.cache import global_state
                new_daemons = fetch_host_daemons_data()
                with global_state.lock:
                    if 'daemons' in global_state.stats:
                        global_state.stats['daemons'] = new_daemons
            except Exception as e:
                pass
                
            yield f"data: {json.dumps({'status': 'done', 'msg': 'Done'})}\n\n"
        except Exception as e:
            from app.services.alerts import notify_action
            notify_action('daemon', daemon_id, action, ok=False, error=str(e))
            yield f"data: {json.dumps({'status': 'error', 'msg': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@services_bp.route('/containers/action/<container_id>/<action>', methods=['GET', 'POST'])
def container_action_stream(container_id, action):
    """SSE stream: fires docker action and streams status back."""
    if action not in ['start', 'stop', 'restart']:
        return jsonify({"status": "error", "message": "Invalid action"}), 400
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', container_id):
        return jsonify({"status": "error", "message": "Invalid container ID"}), 400

    def generate():
        yield f"data: {json.dumps({'status': 'running', 'msg': f'{action.capitalize()}ing {container_id}...'})}\n\n"
        try:
            from app.core.config import VM_CMD_PREFIX
            res = subprocess.run(VM_CMD_PREFIX + ["docker", action, container_id],
                                 capture_output=True, text=True, timeout=30)
            from app.services.alerts import notify_action
            notify_action('container', container_id, action, ok=res.returncode == 0,
                          error=res.stderr.strip() or 'Command failed')
            if res.returncode == 0:
                # Instantly update cache
                try:
                    from app.api.system import fetch_vm_containers_data
                    from app.core.cache import global_state
                    new_containers = fetch_vm_containers_data()
                    with global_state.lock:
                        if 'containers' in global_state.stats:
                            global_state.stats['containers'] = new_containers
                except Exception as e:
                    pass
                    
                yield f"data: {json.dumps({'status': 'done', 'msg': f'{container_id} {action}ed'})}\n\n"
            else:
                yield f"data: {json.dumps({'status': 'error', 'msg': res.stderr.strip() or 'Command failed'})}\n\n"
        except subprocess.TimeoutExpired:
            yield f"data: {json.dumps({'status': 'error', 'msg': 'Timed out after 30s'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'msg': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@services_bp.route('/uptime', methods=['GET'])
def service_uptime():
    from flask import request
    from app.core.db import get_service_uptime
    hours = min(max(request.args.get('hours', 24, type=float), 1), 168)
    buckets = min(max(request.args.get('buckets', 48, type=int), 6), 168)
    return jsonify({"status": "success", "data": get_service_uptime(hours, buckets)})


ANSI_RE = __import__('re').compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def _tail_file(path, lines):
    import collections, os
    if not os.path.exists(path):
        return None
    with open(path, 'r', errors='replace') as f:
        # only read the end of large files (dashboard logs are tens of MB)
        f.seek(max(0, os.path.getsize(path) - 512 * 1024))
        return ''.join(collections.deque(f, maxlen=lines))

def _daemon_log_sources(daemon_id):
    import glob, os
    home = os.path.expanduser('~')
    if daemon_id == 'dashboard':
        return ['/tmp/homelab-dashboard.out', '/tmp/homelab-dashboard.err']
    if daemon_id == 'jellyfin':
        files = sorted(glob.glob(f'{home}/Library/Application Support/jellyfin/log/log_*.log'))
        return files[-1:]
    if daemon_id == 'orbstack':
        return [f'{home}/.orbstack/log/vmgr.log']
    if daemon_id == 'qbittorrent':
        return [f'{home}/Library/Application Support/qBittorrent/logs/qbittorrent.log']
    return []

@services_bp.route('/logs/<kind>/<service_id>', methods=['GET'])
def service_logs(kind, service_id):
    import re
    from flask import request
    lines = min(max(request.args.get('lines', 200, type=int), 10), 2000)
    if not re.match(r'^[a-zA-Z0-9_.-]+$', service_id):
        return jsonify({"status": "error", "message": "Invalid service ID"}), 400
    try:
        if kind == 'container':
            from app.core.config import VM_CMD_PREFIX
            res = subprocess.run(VM_CMD_PREFIX + ["docker", "logs", "--tail", str(lines), "--timestamps", service_id],
                                 capture_output=True, text=True, timeout=10)
            if res.returncode != 0:
                return jsonify({"status": "error", "message": res.stderr.strip() or "docker logs failed"})
            # docker prefixes each line with an RFC3339 timestamp, so merged stdout/stderr sorts correctly
            text = '\n'.join(sorted((res.stdout + res.stderr).splitlines()))
            return jsonify({"status": "success", "source": f"docker logs {service_id}", "log": ANSI_RE.sub('', text)})
        if kind == 'daemon':
            sources = _daemon_log_sources(service_id)
            chunks = []
            for path in sources:
                content = _tail_file(path, lines)
                if content is not None:
                    chunks.append((path, content))
            if not chunks:
                return jsonify({"status": "success", "source": None, "log": "", "message": "No log file configured for this daemon."})
            text = '\n'.join(f"── {p} ──\n{c}" if len(chunks) > 1 else c for p, c in chunks)
            return jsonify({"status": "success", "source": ', '.join(p for p, _ in chunks), "log": ANSI_RE.sub('', text)})
        return jsonify({"status": "error", "message": "Unknown service type"}), 400
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "Timed out reading logs"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
