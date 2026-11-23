from flask import Blueprint, jsonify, request
import subprocess
import os
import glob
import re
import plistlib
import time

from app.core.logger import log

backups_bp = Blueprint('backups', __name__)

from app.core import backup_cfg
from app.core import paths
from app.core import server_cfg
PLIST_PATH = os.path.expanduser('~/Library/LaunchAgents/com.homelab.backup.plist')

@backups_bp.route('/config', methods=['GET'])
def get_backups():
    try:
        try:
            with open(PLIST_PATH, 'rb') as f:
                plist = plistlib.load(f)
        except OSError:
            plist = {}             # no schedule yet: the defaults below
        day = 0
        hour = 4
        minute = 0
        freq = 'daily'

        if 'StartInterval' in plist:
            freq = 'hourly'
            hour = plist['StartInterval'] // 3600
        else:
            interval = plist.get('StartCalendarInterval', {})
            freq = 'weekly' if 'Weekday' in interval else 'daily'
            day = interval.get('Weekday', 0)
            hour = interval.get('Hour', 4)
            minute = interval.get('Minute', 0)

        # [backup.sh, N] from older installs, [/bin/bash, backup.sh, N] now: N is the last argument
        args = plist.get('ProgramArguments', [])
        retention = int(args[-1]) if len(args) > 1 and str(args[-1]).isdigit() else 4
        return jsonify({
            "status": "success",
            "data": {
                "hour": hour,
                "minute": minute,
                "frequency": freq,
                "day": day,
                "retention": retention
            }
        })
    except Exception as e:
        log.error(f"Failed to get backups config: {e}")
        return jsonify({"status": "error", "message": str(e)})

@backups_bp.route('', methods=['GET'])
def list_backups():
    try:
        if not os.path.exists(backup_cfg.dest()):
            return jsonify({"status": "success", "data": []})
        
        files = glob.glob(os.path.join(backup_cfg.dest(), '*.tar.gz'))
        timestamps = set()
        for f in files:
            name = os.path.basename(f)
            match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})', name)
            if match:
                timestamps.add(match.group(1))
                
        sorted_ts = sorted(list(timestamps), reverse=True)
        return jsonify({"status": "success", "data": sorted_ts})
    except Exception as e:
        log.error(f"Failed to list backups: {e}")
        return jsonify({"status": "error", "message": str(e)})

TS_RE = r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}'

def _next_run(cfg, now):
    """Next launchd fire time for the current schedule (hourly runs are relative to load, so approximate)."""
    import datetime as dt
    if cfg['frequency'] == 'hourly':
        return None
    cand = now.replace(hour=cfg['hour'], minute=cfg['minute'], second=0, microsecond=0)
    if cfg['frequency'] == 'weekly':
        # launchd: 0 and 7 are Sunday; Python: Monday=0
        target = (cfg['day'] - 1) % 7
        cand += dt.timedelta(days=(target - cand.weekday()) % 7)
        if cand <= now: cand += dt.timedelta(days=7)
    elif cand <= now:
        cand += dt.timedelta(days=1)
    return cand

@backups_bp.route('/details', methods=['GET'])
def backup_details():
    import datetime as dt
    try:
        snaps = {}
        for f in glob.glob(os.path.join(backup_cfg.dest(), '*.tar.gz')):
            name = os.path.basename(f)
            m = re.match(rf'(.+)_({TS_RE})\.tar\.gz$', name)
            if not m: continue
            snap = snaps.setdefault(m.group(2), {"timestamp": m.group(2), "files": [], "size_bytes": 0})
            size = os.path.getsize(f)
            snap["files"].append({"name": name, "component": m.group(1), "label": backup_cfg.label(m.group(1)), "size_bytes": size})
            snap["size_bytes"] += size
        ordered = sorted(snaps.values(), key=lambda s: s["timestamp"], reverse=True)
        for s in ordered:
            s["files"].sort(key=lambda f: -f["size_bytes"])
            s["created"] = int(dt.datetime.strptime(s["timestamp"], '%Y-%m-%d_%H-%M-%S').timestamp())
            # an empty placeholder means that component was skipped (e.g. VM was down)
            s["incomplete"] = any(f["size_bytes"] == 0 for f in s["files"])

        next_run = None
        cfg_res = get_backups().get_json()
        if cfg_res.get('status') == 'success':
            nr = _next_run(cfg_res['data'], dt.datetime.now())
            next_run = int(nr.timestamp()) if nr else None

        running = os.path.exists('/tmp/homelab_backup.lock')
        return jsonify({"status": "success", "data": {
            "snapshots": ordered,
            "last_success": ordered[0]["created"] if ordered else None,
            "next_run": next_run,
            "running": running,
            "total_bytes": sum(s["size_bytes"] for s in ordered),
        }})
    except Exception as e:
        log.error(f"Failed to read backup details: {e}")
        return jsonify({"status": "error", "message": str(e)})

@backups_bp.route('/file/<name>', methods=['GET'])
def download_backup_file(name):
    from flask import send_from_directory
    if not re.fullmatch(rf'[A-Za-z0-9_.-]+_{TS_RE}\.tar\.gz', name):
        return jsonify({"status": "error", "message": "Invalid file name"}), 400
    return send_from_directory(backup_cfg.dest(), name, as_attachment=True)

@backups_bp.route('/<timestamp>/reveal', methods=['POST'])
def reveal_backup(timestamp):
    if not re.fullmatch(TS_RE, timestamp):
        return jsonify({"status": "error", "message": "Invalid backup timestamp"}), 400
    files = sorted(glob.glob(os.path.join(backup_cfg.dest(), f'*{timestamp}.tar.gz')))
    if not files:
        return jsonify({"status": "error", "message": "Backup not found"}), 404
    subprocess.run(['open', '-R', files[0]], timeout=5)
    return jsonify({"status": "success"})

@backups_bp.route('/<timestamp>', methods=['DELETE'])
def delete_backup(timestamp):
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}', timestamp):
            return jsonify({"status": "error", "message": "Invalid backup timestamp"}), 400
        files = glob.glob(os.path.join(backup_cfg.dest(), f'*{timestamp}.tar.gz'))
        for f in files:
            os.remove(f)
        return jsonify({"status": "success"})
    except Exception as e:
        log.error(f"Failed to delete backup: {e}")
        return jsonify({"status": "error", "message": str(e)})

@backups_bp.route('/config', methods=['PATCH'])
def config_backups():
    try:
        data = request.json
        hour = int(data.get('hour', 4))
        minute = int(data.get('minute', 0))
        freq = data.get('frequency', 'daily')
        day = int(data.get('day', 0))
        retention = int(data.get('retention', 4))
        if freq not in ('hourly', 'daily', 'weekly') or not (0 <= minute <= 59 and 0 <= day <= 7 and 1 <= retention <= 365) \
                or not (1 <= hour <= 168 if freq == 'hourly' else 0 <= hour <= 23):
            return jsonify({"status": "error", "message": "Invalid backup schedule"}), 400
        
        try:
            with open(PLIST_PATH, 'rb') as f:
                plist = plistlib.load(f)
        except OSError:
            plist = {'Label': 'com.homelab.backup'}
            
        if freq == 'hourly':
            if 'StartCalendarInterval' in plist:
                del plist['StartCalendarInterval']
            plist['StartInterval'] = max(1, hour) * 3600
        else:
            if 'StartInterval' in plist:
                del plist['StartInterval']
            interval = {'Hour': hour, 'Minute': minute}
            if freq == 'weekly':
                interval['Weekday'] = day
            plist['StartCalendarInterval'] = interval
            
        plist['ProgramArguments'] = ['/bin/bash', os.path.join(paths.SCRIPTS, 'backup.sh'), str(retention)]
        plist['EnvironmentVariables'] = {'HOMELAB_HOME': paths.HOME}
        plist['StandardOutPath'] = LOG_FILE
        plist['StandardErrorPath'] = os.path.join(paths.LOGS, 'backup.err')
        
        with open(PLIST_PATH, 'wb') as f:
            plistlib.dump(plist, f)
            
        subprocess.run(['launchctl', 'unload', PLIST_PATH])
        subprocess.run(['launchctl', 'load', PLIST_PATH])
        
        # Cleanup delegated to backup.sh entirely
                
        
        
        return jsonify({"status": "success"})
    except Exception as e:
        log.error(f"Failed to configure backups: {e}")
        return jsonify({"status": "error", "message": str(e)})


@backups_bp.route('/settings', methods=['GET'])
def get_backup_settings():
    """What the backup saves and where: destination, built-in parts, extra folders, second copy."""
    cfg = backup_cfg.load()
    return jsonify({"status": "success", "data": {**cfg, "part_info": backup_cfg.PARTS, "part_labels": {k: backup_cfg.label(k) for k in backup_cfg.PARTS},
                    "default_dest": backup_cfg.DEFAULT_DEST, "copy_status": backup_cfg.copy_status() if cfg["copy_to"] else None}})


MACHINE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]*$')


def _orb_machines():
    res = subprocess.run(['orb', 'list', '-f', 'json'], capture_output=True, text=True, timeout=10)
    import json as _json
    return {m["name"]: m for m in _json.loads(res.stdout or '[]')}


def _clean_machines(raw):
    """[{name, folders}] -> checked: real machines, absolute folders, none empty."""
    known, out = _orb_machines(), []
    for m in raw or []:
        name = str((m or {}).get('name') or '')
        if not MACHINE_RE.match(name) or name not in known:
            raise ValueError(f"No machine called {name or '(none)'}")
        folders = []
        for f in m.get('folders') or []:
            f = os.path.normpath(str(f).strip())
            if not f.startswith('/') or f == '/' or '..' in f.split('/'):
                raise ValueError(f"Pick a specific folder inside {name}, not {f or 'nothing'}")
            folders.append(f)
        if folders:
            out.append({"name": name, "folders": list(dict.fromkeys(folders))})
    return out


def _clean_folders(folders, where):
    out = []
    for f in folders or []:
        f = os.path.normpath(str(f).strip())
        if not f.startswith('/') or f == '/' or '..' in f.split('/'):
            raise ValueError(f"Pick a specific folder on {where}, not {f or 'nothing'}")
        out.append(f)
    return list(dict.fromkeys(out))


def _clean_hosts(raw):
    from app.api.hosts import _find
    out = []
    for h in raw or []:
        hid = str((h or {}).get('id') or '')
        if not _find(hid):
            raise ValueError(f"No computer called {hid or '(none)'}")
        folders = _clean_folders(h.get('folders'), hid)
        if folders:
            out.append({"id": hid, "folders": folders})
    return out


def _queue(hid, verb, target=''):
    """Queue an agent action through the hosts API -> (action, error message)."""
    from app.api.hosts import queue_action
    res = queue_action(hid, body={"verb": verb, "target": target})
    resp = res[0] if isinstance(res, tuple) else res
    j = resp.get_json()
    return (j.get('data'), None) if j.get('status') == 'success' else (None, j.get('message'))


def _wait(hid, aid, seconds):
    import time
    from app.api.hosts import action
    end = time.time() + seconds
    while True:
        a = action(hid, aid)
        if not a or a['state'] not in ('queued', 'sent') or time.time() > end:
            return a
        time.sleep(1)


# What each computer last said it has: the list arrives in seconds; sizes are measured
# separately (du on a big home folder can take minutes) and fill in when they're done.
_host_folders = {}          # host id -> {"at", "folders": [{path, bytes}], "sizes_at", "measuring"}
FOLDERS_FRESH = 600         # reuse a list this long before asking again
SIZES_FRESH = 3600          # and measure again after this


def _parse_folders(text):
    out = []
    for line in (text or '').splitlines():
        path, _, kb = line.partition('\t')
        if path.startswith('/'):
            out.append({"path": path, "bytes": int(kb) * 1024 if kb.strip().isdigit() else None})
    return out


def _measure(app, hid):
    with app.app_context():
        c = _host_folders[hid]
        try:
            a, err = _queue(hid, 'backup-sizes')
            a = _wait(hid, a['id'], 900) if a else None
            if a and a['state'] == 'done' and a['output'] != 'no access':
                sizes = {f["path"]: f["bytes"] for f in _parse_folders(a['output'])}
                c["folders"] = [{**f, "bytes": sizes.get(f["path"], f["bytes"])} for f in c["folders"]]
                c["sizes_at"] = time.time()
        finally:
            c["measuring"] = False


@backups_bp.route('/hosts/<hid>/folders', methods=['GET'])
def host_folders(hid):
    """Folders worth offering for another computer. Answers from what it said last when that's
    recent, else asks it (a few seconds); sizes come in later, "measuring" says they're on the way."""
    from flask import current_app
    from app.api.hosts import _find, agent_version, BACKUP_FROM, VERB_FROM
    import threading
    h = _find(hid)
    if not h:
        return jsonify({"status": "error", "message": "No such computer"})
    if agent_version(hid) < BACKUP_FROM:
        return jsonify({"status": "success", "data": {"agent_ok": False, "folders": [], "measuring": False}})
    c = _host_folders.get(hid)
    if not c or time.time() - c["at"] > FOLDERS_FRESH or request.args.get('refresh') == '1':
        a, err = _queue(hid, 'backup-folders')
        if err:
            return jsonify({"status": "error", "message": err})
        a = _wait(hid, a['id'], 20)
        if not a or a['state'] != 'done':
            if c:  # still show what it said before
                return jsonify({"status": "success", "data": {"agent_ok": True, "folders": c["folders"], "measuring": False, "stale": True}})
            return jsonify({"status": "error", "message": (a or {}).get('output') or f"{h['name']} didn't answer; is it awake?"})
        known = {f["path"]: f["bytes"] for f in (c or {}).get("folders", [])}
        folders = [{**f, "bytes": f["bytes"] if f["bytes"] is not None else known.get(f["path"])} for f in _parse_folders(a['output'])]
        c = _host_folders[hid] = {"at": time.time(), "folders": folders, "sizes_at": (c or {}).get("sizes_at"), "measuring": (c or {}).get("measuring", False)}
    if (not c["measuring"] and agent_version(hid) >= VERB_FROM['backup-sizes']
            and (not c["sizes_at"] or time.time() - c["sizes_at"] > SIZES_FRESH)):
        c["measuring"] = True
        threading.Thread(target=_measure, args=(current_app._get_current_object(), hid), daemon=True).start()
    return jsonify({"status": "success", "data": {"agent_ok": True, "folders": c["folders"], "measuring": c["measuring"]}})


@backups_bp.route('/hosts/run', methods=['POST'])
def run_host_backups():
    """Called by backup.sh on the Mac: every computer with folders chosen packs and uploads
    them for snapshot <ts>; waits for all of them. A part that didn't arrive is left as an
    empty file, which the Backups page shows as failed. Prints one line per computer."""
    from app.api.hosts import _find, agent_version, BACKUP_FROM, BACKUP_TTL
    import threading
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return "only backup.sh on this Mac can start this\n", 403
    ts = request.args.get('ts', '')
    if not re.fullmatch(TS_RE, ts):
        return "bad timestamp\n", 400
    cfg = backup_cfg.load()
    lines = []

    def one(plan):
        hid = plan["id"]
        h = _find(hid) or {"name": hid}
        out = os.path.join(cfg["dest"], f"{backup_cfg.HOST}{hid}_{ts}.tar.gz")
        why = None
        if agent_version(hid) < BACKUP_FROM:
            why = "its agent is too old (update it from the computer's ⋯ menu)"
        else:
            a, why = _queue(hid, 'backup', ts)
            if a:
                a = _wait(hid, a['id'], BACKUP_TTL)
                if not a or a['state'] != 'done':
                    why = {'expired': "it didn't answer (asleep or offline?)"}.get((a or {}).get('state')) or (a or {}).get('output') or 'no answer'
        if why or not os.path.exists(out):
            open(out, 'w').close()
            lines.append(f"ERROR: {h['name']} backup failed: {why or 'nothing arrived'}")
        else:
            lines.append(f"{h['name']}: {os.path.getsize(out)} bytes")
            # the agent says what it couldn't read (macOS without Full Disk Access)
            for note in (a or {}).get('output', '').splitlines():
                if note.startswith('skipped'):
                    lines.append(f"WARNING: {h['name']} {note}")

    from flask import current_app
    app = current_app._get_current_object()

    def run(plan):
        # the hosts API answers with Flask responses, which need the app around
        with app.app_context():
            try:
                one(plan)
            except Exception as e:  # noqa: BLE001
                log.warning(f"host backup {plan['id']}: {e}")
                lines.append(f"ERROR: {plan['id']} backup failed: {e}")

    threads = [threading.Thread(target=run, args=(p,)) for p in cfg["hosts"]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return '\n'.join(lines) + '\n', 200, {'Content-Type': 'text/plain'}


# folders worth offering for a machine, with their size so the choice is informed
SUGGEST_SH = r"""
for d in /home /root /etc /opt /srv /var/www /var/lib/docker/volumes; do
  [ -d "$d" ] && printf '%s\t%s\n' "$d" "$(du -sk "$d" 2>/dev/null | cut -f1)"
done
"""


@backups_bp.route('/machines/<name>/folders', methods=['GET'])
def machine_folders(name):
    if not MACHINE_RE.match(name):
        return jsonify({"status": "error", "message": "bad machine name"})
    try:
        m = _orb_machines().get(name)
        if not m:
            return jsonify({"status": "error", "message": f"No machine called {name}"})
        if m.get('state') != 'running':
            return jsonify({"status": "success", "data": {"running": False, "folders": []}})
        res = subprocess.run(['orb', '-m', name, '-u', 'root', 'sh', '-c', SUGGEST_SH], capture_output=True, text=True, timeout=60)
        folders = []
        for line in res.stdout.splitlines():
            path, _, kb = line.partition('\t')
            folders.append({"path": path, "bytes": int(kb or 0) * 1024})
        return jsonify({"status": "success", "data": {"running": True, "folders": folders}})
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "The machine took too long to answer"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


def _folder(path, what, must_exist=True):
    path = os.path.normpath(os.path.expanduser((path or "").strip()))
    if not path.startswith("/") or path in ("/", "/Users", "/Volumes", os.path.expanduser("~")):
        raise ValueError(f"Pick a specific folder for the {what}, not {path or 'nothing'}")
    if must_exist and not os.path.isdir(path):
        raise ValueError(f"{path} isn't a folder on this Mac")
    return path


@backups_bp.route('/settings', methods=['PATCH'])
def set_backup_settings():
    """Change what the backup saves and where: dest, parts {name: bool}, folders [...], copy_to."""
    body = request.get_json(silent=True) or {}
    cfg = backup_cfg.load()
    try:
        if 'dest' in body:
            d = _folder(body['dest'], "backups", must_exist=False)
            if not os.path.isdir(os.path.dirname(d)):
                raise ValueError(f"{os.path.dirname(d)} doesn't exist")
            cfg['dest'] = d
        if 'parts' in body:
            cfg['parts'] = {k: bool((body['parts'] or {}).get(k, cfg['parts'][k])) for k in backup_cfg.PARTS}
        if 'folders' in body:
            folders = [_folder(x, "extra folder") for x in body['folders'] or []]
            if any(f == cfg['dest'] or f.startswith(cfg['dest'] + '/') or cfg['dest'].startswith(f + '/') for f in folders):
                raise ValueError("A folder can't contain (or be inside) the backup folder itself")
            cfg['folders'] = list(dict.fromkeys(folders))
        if 'copy_to' in body:
            c = (body['copy_to'] or '').strip()
            cfg['copy_to'] = _folder(c, "second copy", must_exist=False) if c else ""
            if cfg['copy_to'] and os.path.normpath(cfg['copy_to']) == cfg['dest']:
                raise ValueError("The second copy needs a different folder than the backups")
        if 'machines' in body:
            cfg['machines'] = _clean_machines(body['machines'])
        if 'hosts' in body:
            cfg['hosts'] = _clean_hosts(body['hosts'])
        if not any(cfg['parts'].values()) and not cfg['folders'] and not cfg['machines'] and not cfg['hosts']:
            raise ValueError("Nothing would be backed up; keep at least one part or folder")
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)})
    backup_cfg.save(cfg)
    log.info(f"backup settings: {cfg}")
    return jsonify({"status": "success", "data": cfg})


# ---- run history ----------------------------------------------------------------------
# backup.sh appends every run to $HOMELAB_HOME/logs/backup.out; a run starts with
# "Starting Homelab Backup (<ts>)...". When it ended is the newest file it wrote.

LOG_FILE = os.path.join(paths.LOGS, 'backup.out')
RUN_RE = re.compile(rf'^Starting Homelab Backup \(({TS_RE})\)')


@backups_bp.route('/runs', methods=['GET'])
def backup_runs():
    import datetime as dt
    try:
        with open(LOG_FILE, errors='replace') as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    runs, cur = [], None
    for line in lines:
        m = RUN_RE.match(line)
        if m:
            cur = {"timestamp": m.group(1), "log": []}
            runs.append(cur)
        elif cur is not None:
            cur["log"].append(line)
    running = os.path.exists('/tmp/homelab_backup.lock')
    out = []
    for i, r in enumerate(reversed(runs[-30:])):
        log_lines = r["log"]
        started = int(dt.datetime.strptime(r["timestamp"], '%Y-%m-%d_%H-%M-%S').timestamp())
        files = glob.glob(os.path.join(backup_cfg.dest(), f'*_{r["timestamp"]}.tar.gz'))
        ended = max((os.path.getmtime(f) for f in files), default=None)
        done = any(l.startswith('Backup complete') for l in log_lines)
        problems = [l for l in log_lines if l.startswith(('ERROR', 'WARNING')) or ' failed' in l]
        out.append({
            "timestamp": r["timestamp"], "started": started,
            "seconds": round(ended - started) if ended and done else None,
            "state": "running" if i == 0 and running and not done else "failed" if problems or not done else "ok",
            "problems": problems, "log": log_lines,
            "kept": bool(files),  # still on disk, or pruned by retention
        })
    # "Back up now" runs aren't logged to backup.out; their snapshots still count as runs
    logged = {r["timestamp"] for r in out}
    stamps = {}
    for f in glob.glob(os.path.join(backup_cfg.dest(), '*.tar.gz')):
        m = re.match(rf'.+_({TS_RE})\.tar\.gz$', os.path.basename(f))
        if m and m.group(1) not in logged:
            stamps.setdefault(m.group(1), []).append(f)
    for ts, files in stamps.items():
        started = int(dt.datetime.strptime(ts, '%Y-%m-%d_%H-%M-%S').timestamp())
        empty = [os.path.basename(f).rsplit('_', 2)[0] for f in files if os.path.getsize(f) == 0]
        out.append({"timestamp": ts, "started": started, "seconds": round(max(os.path.getmtime(f) for f in files) - started),
                    "state": "failed" if empty else "ok", "problems": [f"{p} came out empty" for p in empty],
                    "log": None, "manual": True, "kept": True})
    out.sort(key=lambda r: r["timestamp"], reverse=True)
    return jsonify({"status": "success", "data": out})


# ---- what is covered -----------------------------------------------------------------

VM_EXCLUDED = ["Pi-hole's query log (pihole-FTL.db)", "Pi-hole's downloaded blocklists"]


@backups_bp.route('/coverage', methods=['GET'])
def backup_coverage():
    """Everything the homelab runs, and whether the nightly backup saves it."""
    import json as _json
    from app.core.config import VM_NAME
    cfg = backup_cfg.load()
    latest = {}  # component -> (timestamp, size) of its newest non-empty archive
    for f in glob.glob(os.path.join(cfg["dest"], '*.tar.gz')):
        m = re.match(rf'(.+)_({TS_RE})\.tar\.gz$', os.path.basename(f))
        if m and os.path.getsize(f) > 0 and m.group(2) > latest.get(m.group(1), ("",))[0]:
            latest[m.group(1)] = (m.group(2), os.path.getsize(f))
    part = lambda k: {"on": cfg["parts"].get(k, True), "last": latest.get(k, (None, None))[0], "size": latest.get(k, (None, None))[1]}

    groups = [{"id": "arrakis", "name": server_cfg.name(), "kind": "mac", "editable": True, "items": [
        {"id": "jellyfin", "name": "Jellyfin", "what": backup_cfg.PARTS["jellyfin"], **part("jellyfin")},
        {"id": "dashboard", "name": "Dashboard", "what": backup_cfg.PARTS["dashboard"], **part("dashboard")},
        {"id": "server_config", "name": "Server config", "what": backup_cfg.PARTS["server_config"], **part("server_config")},
        *([{"id": "folders", "name": "Extra folders", "what": ", ".join(cfg["folders"]), **part("folders")}] if cfg["folders"] else []),
    ]}]
    try:
        res = subprocess.run(['orb', 'list', '-f', 'json'], capture_output=True, text=True, timeout=10)
        machines = [m["name"] for m in _json.loads(res.stdout or '[]')]
    except Exception:  # noqa: BLE001
        machines = []
    own = {m["name"]: m["folders"] for m in cfg["machines"]}
    for m in machines:
        items = []
        if m == VM_NAME:
            items.append({"id": "vm_data", "name": "Containers", "what": "Compose stacks in /opt/stacks and every Docker volume",
                          "excluded": VM_EXCLUDED, **part("vm_data")})
        if own.get(m):
            items.append({"id": backup_cfg.MACHINE + m, "name": ", ".join(own[m]), "what": "Folders in the machine",
                          "on": True, "last": latest.get(backup_cfg.MACHINE + m, (None, None))[0],
                          "size": latest.get(backup_cfg.MACHINE + m, (None, None))[1]})
        groups.append({"id": "vm-" + m, "name": m, "kind": "machine", "editable": True, "folders": own.get(m, []),
                       "containers": m == VM_NAME, "containers_on": cfg["parts"].get("vm_data", True) if m == VM_NAME else None,
                       "items": items})
    try:
        from app.api.hosts import _load as hosts
        for h in hosts():
            from app.api.hosts import agent_version, BACKUP_FROM
            plan = next((x["folders"] for x in cfg["hosts"] if x["id"] == h["id"]), [])
            comp = backup_cfg.HOST + h["id"]
            items = [{"id": comp, "name": ", ".join(plan), "what": "Folders on the computer", "on": True,
                      "last": latest.get(comp, (None, None))[0], "size": latest.get(comp, (None, None))[1]}] if plan else []
            from app.api.hosts import _latest
            rep = _latest.get(h["id"]) or {}
            mac = (rep.get("os") or "").startswith("macOS")
            groups.append({"id": h["id"], "name": h.get("name") or h["id"], "kind": "host", "folders": plan, "mac": mac, "fda": rep.get("fda"),
                           "editable": agent_version(h["id"]) >= BACKUP_FROM, "items": items})
    except Exception as e:  # noqa: BLE001
        log.warning(f"coverage hosts: {e}")
    return jsonify({"status": "success", "data": {
        "groups": groups, "dest": cfg["dest"], "copy_to": cfg["copy_to"], "copy": backup_cfg.copy_status()}})


# ---- browse and restore (app/services/restore.py) -------------------------------------------
@backups_bp.route('/<timestamp>/parts/<part>/files', methods=['GET'])
def snapshot_files(timestamp, part):
    from app.services import restore
    path = restore.archive(timestamp, part)
    if not path:
        return jsonify({"status": "error", "message": "That part of the snapshot isn't there"}), 404
    prefix = request.args.get('path', '')
    try:
        entries = restore.listing(path, prefix)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Could not read the archive: {e}"}), 500
    if entries is None:
        return jsonify({"status": "error", "message": "No such folder in this archive"}), 404
    t = restore.target(part)
    return jsonify({"status": "success", "data": {"path": restore._clean(prefix), "entries": entries,
        "target": {k: t.get(k) for k in ('where', 'label', 'root', 'why')}}})


@backups_bp.route('/<timestamp>/parts/<part>/download', methods=['GET'])
def snapshot_file_download(timestamp, part):
    from flask import Response
    from app.services import restore
    path = restore.archive(timestamp, part)
    member = request.args.get('path', '')
    if not path or not member:
        return jsonify({"status": "error", "message": "Not found"}), 404
    tf, f, size = restore.open_file(path, member)
    if not f:
        return jsonify({"status": "error", "message": "Only single files can be downloaded; restore a folder as a copy"}), 404
    def stream():
        try:
            while True:
                chunk = f.read(1 << 16)
                if not chunk:
                    break
                yield chunk
        finally:
            tf.close()
    name = os.path.basename(member.rstrip('/')).replace('"', '')
    return Response(stream(), mimetype='application/octet-stream', headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Content-Length": str(size)})


@backups_bp.route('/<timestamp>/restore', methods=['POST'])
def snapshot_restore(timestamp):
    from app.services import restore
    body = request.get_json(silent=True) or {}
    paths = body.get('paths') or ['']
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        return jsonify({"status": "error", "message": "paths must be a list of strings"}), 400
    j, err = restore.start(timestamp, body.get('part', ''), paths, body.get('mode', 'copy'))
    if err:
        return jsonify({"status": "error", "message": err}), 400
    return jsonify({"status": "success", "data": j})


@backups_bp.route('/restores/<jid>', methods=['GET'])
def restore_job(jid):
    from app.services import restore
    j = restore.job(jid)
    if not j:
        return jsonify({"status": "error", "message": "No such restore"}), 404
    return jsonify({"status": "success", "data": j})
