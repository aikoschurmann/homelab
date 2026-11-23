from flask import Blueprint, jsonify, request
import subprocess
import re
import uuid
import shlex

from app.core.logger import log
from app.core.cache import global_state
from app.services.poller import refresh_tmux_cache
from app.core.config import VM_CMD_PREFIX
from app.core import paths

tmux_bp = Blueprint('tmux', __name__)

@tmux_bp.route('/sessions')
def tmux_sessions():
    with global_state.lock:
        sessions = list(global_state.tmux_sessions)
    return jsonify({"status": "success", "sessions": sessions})

def _target(session):
    from app.core.tmux_target import split
    where, real = split(session)
    if not where:
        raise ValueError("Invalid session name; expected <mac|machine>:<name>")
    return where, real


@tmux_bp.route('/sessions', methods=['POST'])
def tmux_create():
    return jsonify(_start(request.json or {}))


def _start(data):
    """Start a session from {name, target, command, cwd, reuse}; returns the JSON reply."""
    from app.core.tmux_target import tmux_cmd, ensure_tmux, running_machines, remote_host, new_session_args, MACHINE_RE
    from app.core.config import VM_NAME
    try:
        name = (data.get('name') or '').strip()
        target = data.get('target', 'mac')
        if target == 'vm':
            target = VM_NAME
        command = (data.get('command') or '').strip()
        cwd = (data.get('cwd') or '').strip()
        if any(ord(c) < 32 for c in cwd + command):
            return {"status": "error", "message": "Control characters aren't allowed"}
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            return {"status": "error", "message": "Invalid name format"}
        if target != 'mac' and (not MACHINE_RE.match(target) or (target not in running_machines(max_age=0) and not remote_host(target))):
            return {"status": "error", "message": f"{target} isn't a running machine or an online host"}
        note = None
        if target != 'mac':
            ok, note = ensure_tmux(target)
            if not ok:
                return {"status": "error", "message": note}
        # reuse: open the session if it's already running (the one-click shells)
        if data.get('reuse') and subprocess.run(tmux_cmd(target) + ["has-session", "-t", f"={name}"], capture_output=True, timeout=10).returncode == 0:
            return {"status": "success", "session": f"{target}:{name}", "reused": True}
        cmd = tmux_cmd(target) + new_session_args(target, name, cwd) + ([command] if command else [])
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if res.returncode != 0:
            return {"status": "error", "message": res.stderr.strip() or "tmux failed"}
        refresh_tmux_cache()
        return {"status": "success", "session": f"{target}:{name}", "message": note}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@tmux_bp.route('/sessions/<session>', methods=['PATCH'])
def tmux_rename(session):
    from app.core.tmux_target import tmux_cmd
    try:
        new_name = (request.json or {}).get('new_name', '').strip()
        if not re.match(r'^[a-zA-Z0-9_-]+$', new_name):
            return jsonify({"status": "error", "message": "Invalid session name"})
        where, real = _target(session)
        result = subprocess.run(tmux_cmd(where) + ["rename-session", "-t", real, new_name], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return jsonify({"status": "error", "message": result.stderr.strip()})
        refresh_tmux_cache()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@tmux_bp.route('/sessions/<session>/log', methods=['GET'])
def tmux_log(session):
    from app.core.tmux_target import tmux_cmd
    try:
        where, real = _target(session)
        result = subprocess.run(tmux_cmd(where) + ["capture-pane", "-pt", real, "-S", "-100"], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return jsonify({"status": "error", "message": "Session not found"})
        return jsonify({"status": "success", "log": result.stdout})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@tmux_bp.route('/sessions/<session>', methods=['DELETE'])
def tmux_kill(session):
    from app.core.tmux_target import tmux_cmd
    try:
        where, real = _target(session)
        subprocess.run(tmux_cmd(where) + ["kill-session", "-t", real], capture_output=True, timeout=10)
        refresh_tmux_cache()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ---- windows and panes ---------------------------------------------------------------------
PANE_FMT = "#{window_index}|#{window_active}|#{window_zoomed_flag}|#{pane_index}|#{pane_active}|#{pane_current_command}|#{window_name}"


@tmux_bp.route('/sessions/<session>/windows')
def tmux_windows(session):
    """The session's windows, each with its panes (one tmux call: it may go over SSH)."""
    from app.core.tmux_target import tmux_cmd
    try:
        where, real = _target(session)
        res = subprocess.run(tmux_cmd(where) + ["list-panes", "-s", "-t", f"={real}", "-F", PANE_FMT], capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            return jsonify({"status": "error", "message": "Session not found"})
        windows = {}
        for line in res.stdout.strip().split('\n'):
            p = line.split('|', 6)
            if len(p) < 7:
                continue
            w = windows.setdefault(int(p[0]), {"index": int(p[0]), "active": p[1] == '1', "zoomed": p[2] == '1', "name": p[6], "panes": []})
            w["panes"].append({"index": int(p[3]), "active": p[4] == '1', "command": p[5]})
        return jsonify({"status": "success", "windows": sorted(windows.values(), key=lambda w: w["index"])})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@tmux_bp.route('/sessions/<session>/act', methods=['POST'])
def tmux_act(session):
    """One window or pane action: new, select, close, rename, split, zoom, pane, kill-pane."""
    from app.core.tmux_target import tmux_cmd
    try:
        where, real = _target(session)
        d = request.json or {}
        action = d.get('action')
        win = f"={real}:{int(d['window'])}" if d.get('window') is not None else f"={real}:"
        pane = f"{win}.{int(d['pane'])}" if d.get('pane') is not None else win
        here = "#{pane_current_path}"
        if action == 'new':
            args = ["new-window", "-t", f"={real}:", "-c", here]
        elif action == 'select':
            args = ["select-window", "-t", win]
        elif action == 'close':
            args = ["kill-window", "-t", win]
        elif action == 'rename':
            name = (d.get('name') or '').strip()
            if not name or len(name) > 40 or any(ord(c) < 32 for c in name):
                return jsonify({"status": "error", "message": "Invalid window name"})
            args = ["rename-window", "-t", win, name]
        elif action == 'split':
            args = ["split-window", "-t", pane, "-c", here] + (["-h"] if d.get('dir') == 'right' else ["-v"])
        elif action == 'zoom':
            args = ["resize-pane", "-Z", "-t", pane]
        elif action == 'pane':
            args = ["select-pane", "-t", pane]
        elif action == 'kill-pane':
            args = ["kill-pane", "-t", pane]
        else:
            return jsonify({"status": "error", "message": "Unknown action"})
        res = subprocess.run(tmux_cmd(where) + args, capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            return jsonify({"status": "error", "message": res.stderr.strip() or "tmux failed"})
        if action in ('new', 'close'):
            refresh_tmux_cache()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@tmux_bp.route('/sessions/<session>/send', methods=['POST'])
def tmux_send(session):
    """Type a line into the session's active pane without attaching to it."""
    from app.core.tmux_target import tmux_cmd
    try:
        where, real = _target(session)
        d = request.json or {}
        text = d.get('text') or ''
        if '\n' in text or '\r' in text or len(text) > 4000:
            return jsonify({"status": "error", "message": "One line at a time"})
        base = tmux_cmd(where) + ["send-keys", "-t", f"={real}:"]
        if text:
            res = subprocess.run(base + ["-l", "--", text], capture_output=True, text=True, timeout=10)
            if res.returncode != 0:
                return jsonify({"status": "error", "message": res.stderr.strip() or "tmux failed"})
        if d.get('enter', True):
            subprocess.run(base + ["Enter"], capture_output=True, timeout=10)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@tmux_bp.route('/sessions/<session>/scrollback')
def tmux_scrollback(session):
    """The active pane's whole history as a text file."""
    from flask import Response
    from app.core.tmux_target import tmux_cmd
    where, real = _target(session)
    res = subprocess.run(tmux_cmd(where) + ["capture-pane", "-p", "-J", "-S", "-", "-t", f"={real}:"], capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        return jsonify({"status": "error", "message": "Session not found"}), 404
    fname = f"{where}-{real}.txt"
    return Response(res.stdout.rstrip() + "\n", mimetype="text/plain",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---- saved commands ----------------------------------------------------------------------------
import os
import json
PRESETS = paths.state('terminal_presets')


def _load_presets():
    try:
        with open(PRESETS) as f:
            return json.load(f)
    except Exception:
        return []


@tmux_bp.route('/presets')
def presets_get():
    return jsonify({"status": "success", "presets": _load_presets()})


def _save_presets(items):
    tmp = PRESETS + '.tmp'
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
        json.dump(items, f, indent=2)
    os.replace(tmp, PRESETS)


@tmux_bp.route('/presets', methods=['PUT'])
def presets_put():
    """Replace the whole list (add, edit, delete and reorder all come through here).
    Run history is kept by id, so the browser can't rewrite it."""
    items = (request.json or {}).get('presets')
    if not isinstance(items, list) or len(items) > 100:
        return jsonify({"status": "error", "message": "Expected a list of saved commands"})
    old = {p.get('id'): p for p in _load_presets()}
    clean = []
    for p in items:
        name = str(p.get('name') or '').strip()
        label = str(p.get('label') or name).strip()[:60]
        target = str(p.get('target') or 'mac').strip()
        command, cwd, notes = str(p.get('command') or '').strip(), str(p.get('cwd') or '').strip(), str(p.get('notes') or '').strip()
        if not re.match(r'^[a-zA-Z0-9_-]+$', name) or not re.match(r'^[a-z0-9][a-z0-9-]{0,62}$', target):
            return jsonify({"status": "error", "message": f"Invalid saved command {label or name!r}"})
        if any(ord(c) < 32 for c in label + command + cwd + notes):
            return jsonify({"status": "error", "message": "Control characters aren't allowed"})
        pid = str(p.get('id') or uuid.uuid4().hex[:8])
        prev = old.get(pid, {})
        clean.append({"id": pid, "label": label, "name": name, "target": target, "command": command[:500], "cwd": cwd[:300],
                      "notes": notes[:300],
                      # if it's already running: open it ("reuse") or end it and start again ("restart")
                      "mode": p.get('mode') if p.get('mode') in ('reuse', 'restart') else 'reuse',
                      # after starting: open the terminal in its own window, or just the session's page
                      "open_window": bool(p.get('open_window')),
                      "runs": int(prev.get('runs') or 0), "last_run": prev.get('last_run')})
    _save_presets(clean)
    return jsonify({"status": "success", "presets": clean})


@tmux_bp.route('/presets/<pid>/run', methods=['POST'])
def presets_run(pid):
    import time
    from app.core.tmux_target import tmux_cmd
    items = _load_presets()
    p = next((x for x in items if x.get('id') == pid), None)
    if not p:
        return jsonify({"status": "error", "message": "That saved command is gone"})
    restarted = False
    if p.get('mode') == 'restart':
        try:
            restarted = subprocess.run(tmux_cmd(p['target']) + ["kill-session", "-t", f"={p['name']}"], capture_output=True, timeout=10).returncode == 0
        except Exception:
            pass
    res = _start({"name": p['name'], "target": p['target'], "command": p.get('command'), "cwd": p.get('cwd'), "reuse": True})
    if res.get('status') == 'success' and not res.get('reused'):
        p['runs'] = int(p.get('runs') or 0) + 1
        p['last_run'] = int(time.time())
        _save_presets(items)
    res['restarted'] = restarted
    return jsonify(res)
