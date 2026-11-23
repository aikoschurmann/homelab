"""Browsing and restoring backup snapshots.

A snapshot is one .tar.gz per part (scripts/backup.sh). Each part's paths are relative to a
root on a known computer, so a file can go back where it came from:

    jellyfin_<ts>         Mac   ~/Library/Application Support
    server_config_<ts>    Mac   ~
    folders_<ts>          Mac   /
    vm_data_<ts>          the dashboard VM   /   (Docker volumes: their containers stop meanwhile)
    machine_<name>_<ts>   that machine       /
    dashboard_<ts>        copy only (the running dashboard, and two folders both named "homelab")
    host_<id>_<ts>        copy only (it came from another computer)

"A copy" always works: the chosen files go to ~/Homelab-Restores/<ts>/<part>/ on the Mac.
"""
import os, re, subprocess, tarfile, threading, time, uuid

from app.core import backup_cfg
from app.core.logger import log

TS_RE = r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}'
COPY_ROOT = os.path.expanduser('~/Homelab-Restores')

_index = {}          # archive path -> (mtime, {dir: {name: entry}})
_index_lock = threading.Lock()
_jobs = {}           # id -> job
_jobs_lock = threading.Lock()


def archive(ts, part):
    """Path of one part's archive in a snapshot, or None."""
    if not re.fullmatch(TS_RE, ts or '') or not re.fullmatch(r'[A-Za-z0-9_.-]+', part or ''):
        return None
    p = os.path.join(backup_cfg.dest(), f"{part}_{ts}.tar.gz")
    return p if os.path.isfile(p) and os.path.getsize(p) > 0 else None


def target(part):
    """Where a part's paths belong: {"where": 'mac'|'machine', "root", "machine"?, "why"?}."""
    from app.core.config import VM_NAME
    home = os.path.expanduser('~')
    if part == 'jellyfin':
        return {"where": 'mac', "root": os.path.join(home, 'Library', 'Application Support'), "label": "the Mac"}
    if part == 'server_config':
        return {"where": 'mac', "root": home, "label": "the Mac"}
    if part == 'folders':
        return {"where": 'mac', "root": '/', "label": "the Mac"}
    if part == 'vm_data':
        return {"where": 'machine', "machine": VM_NAME, "root": '/', "label": VM_NAME}
    if part.startswith('machine_'):
        return {"where": 'machine', "machine": part[len('machine_'):], "root": '/', "label": part[len('machine_'):]}
    if part == 'dashboard':
        return {"where": None, "why": "The dashboard is running from these files; restore a copy and move what you need."}
    if part.startswith('host_'):
        return {"where": None, "why": "This came from another computer; restore a copy here, or download it."}
    return {"where": None, "why": "Unknown part"}


# ---- browsing -------------------------------------------------------------------------------
def _clean(name):
    """An archive path without a leading './' or '/' (hidden files keep their dot)."""
    name = (name or '').strip()
    while name.startswith('./'):
        name = name[2:]
    return name.lstrip('/').rstrip('/') if name != '.' else ''


def index(path):
    """{dir: {child name: {"name", "dir", "size", "mtime"}}} for an archive, built once."""
    mtime = os.path.getmtime(path)
    with _index_lock:
        hit = _index.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
    tree = {'': {}}
    with tarfile.open(path, 'r:gz') as tf:
        for m in tf:
            name = _clean(m.name)
            if not name:
                continue
            parts = name.split('/')
            # make every parent folder exist, even when the archive has no entry for it
            for i in range(len(parts) - 1):
                parent, child = '/'.join(parts[:i]), parts[i]
                d = tree.setdefault(parent, {})
                d.setdefault(child, {"name": child, "dir": True, "size": 0, "mtime": None})
                tree.setdefault('/'.join(parts[:i + 1]), {})
            parent = '/'.join(parts[:-1])
            e = tree.setdefault(parent, {}).setdefault(parts[-1], {"name": parts[-1], "dir": m.isdir(), "size": 0, "mtime": None})
            e.update(dir=m.isdir() or e["dir"], mtime=int(m.mtime))
            if m.isfile():
                e["size"] = m.size
            if m.isdir():
                tree.setdefault(name, {})
    # folder sizes: everything under them
    def total(d):
        s = 0
        for e in tree.get(d, {}).values():
            if e["dir"]:
                e["size"] = total(f"{d}/{e['name']}" if d else e['name'])
            s += e["size"]
        return s
    total('')
    with _index_lock:
        if len(_index) > 8:
            _index.pop(next(iter(_index)))
        _index[path] = (mtime, tree)
    return tree


def listing(path, prefix=''):
    tree = index(path)
    prefix = _clean(prefix)
    if prefix not in tree:
        return None
    entries = sorted(tree[prefix].values(), key=lambda e: (not e["dir"], e["name"].lower()))
    return entries


def _selected(name, paths):
    name = _clean(name)
    return any(not p or name == p or name.startswith(p + '/') for p in paths)


def open_file(path, member):
    """(file object, size) of one regular file in an archive, for a download."""
    tf = tarfile.open(path, 'r:gz')
    for m in tf:
        if _clean(m.name) == _clean(member) and m.isfile():
            return tf, tf.extractfile(m), m.size
    tf.close()
    return None, None, None


# ---- restoring -------------------------------------------------------------------------------
def _job(**kw):
    j = {"id": uuid.uuid4().hex[:10], "state": "running", "started": int(time.time()), "log": [], **kw}
    with _jobs_lock:
        _jobs[j["id"]] = j
        if len(_jobs) > 50:
            _jobs.pop(next(iter(_jobs)))
    return j


def job(jid):
    with _jobs_lock:
        return dict(_jobs[jid]) if jid in _jobs else None


def jobs():
    with _jobs_lock:
        return [dict(j) for j in _jobs.values()]


def _volumes(paths):
    """Docker volume names a selection touches (paths under var/lib/docker/volumes/<name>)."""
    vols = set()
    for p in paths:
        m = re.match(r'var/lib/docker/volumes/([^/]+)', p)
        if m:
            vols.add(m.group(1))
        elif p in ('', 'var', 'var/lib', 'var/lib/docker', 'var/lib/docker/volumes'):
            vols.add('*')
    return vols


def _run_restore(j, path, part, paths, mode):
    def say(msg):
        j["log"].append(msg)
        log.info(f"restore {j['id']}: {msg}")
    stopped, machine = [], None
    try:
        n = 0
        if mode == 'copy':
            dest = os.path.join(COPY_ROOT, j["ts"], part)
            os.makedirs(dest, exist_ok=True)
            say(f"Restoring a copy into {dest.replace(os.path.expanduser('~'), '~')}")
            with tarfile.open(path, 'r:gz') as tf:
                for m in tf:
                    if _selected(m.name, paths):
                        tf.extract(m, dest, filter='tar')
                        n += 1
            j["dest"] = dest
        else:
            t = target(part)
            if t["where"] == 'mac':
                say(f"Restoring into {t['root'].replace(os.path.expanduser('~'), '~')} on the Mac")
                with tarfile.open(path, 'r:gz') as tf:
                    for m in tf:
                        if _selected(m.name, paths):
                            tf.extract(m, t["root"], filter='tar')
                            n += 1
            elif t["where"] == 'machine':
                machine = t["machine"]
                if subprocess.run(['orb', '-m', machine, 'true'], capture_output=True, timeout=30).returncode != 0:
                    raise RuntimeError(f"{machine} isn't running; start it first")
                vols = _volumes(paths)
                if vols:
                    ids = []
                    for f in ([[]] if '*' in vols else [['--filter', f'volume={v}'] for v in sorted(vols)]):
                        out = subprocess.run(['orb', '-m', machine, '-u', 'root', 'docker', 'ps', '-q', *f],
                                             capture_output=True, text=True, timeout=30).stdout.split()
                        ids += [i for i in out if i not in ids]
                    if ids:
                        names = subprocess.run(['orb', '-m', machine, '-u', 'root', 'docker', 'inspect', '-f', '{{.Name}}', *ids],
                                               capture_output=True, text=True, timeout=30).stdout.split()
                        say(f"Stopping {', '.join(n.lstrip('/') for n in names)} while their data is restored")
                        subprocess.run(['orb', '-m', machine, '-u', 'root', 'docker', 'stop', *ids], capture_output=True, timeout=180)
                        stopped = ids
                say(f"Restoring into {machine}")
                # only the chosen members, streamed straight into the machine's own tar
                p = subprocess.Popen(['orb', '-m', machine, '-u', 'root', 'tar', '-xpf', '-', '-C', t['root']],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                with tarfile.open(path, 'r:gz') as src, tarfile.open(fileobj=p.stdin, mode='w|') as dst:
                    for m in src:
                        if _selected(m.name, paths):
                            dst.addfile(m, src.extractfile(m) if m.isfile() else None)
                            n += 1
                p.stdin.close()
                err = p.stderr.read().decode(errors='replace')
                if p.wait(timeout=600) != 0:
                    raise RuntimeError(err.strip()[-300:] or 'tar failed inside the machine')
            else:
                raise RuntimeError(t.get("why") or "This part can only be restored as a copy")
        j.update(state="done", files=n)
        say(f"Restored {n} item{'s' if n != 1 else ''}")
    except Exception as e:
        j.update(state="failed", error=str(e))
        say(f"Failed: {e}")
    finally:
        if stopped:
            r = subprocess.run(['orb', '-m', machine, '-u', 'root', 'docker', 'start', *stopped], capture_output=True, text=True, timeout=180)
            say("Started the containers again" if r.returncode == 0 else f"Could not start the containers again: {r.stderr.strip()[-200:]}")
        j["finished"] = int(time.time())
        try:
            from app.services.alerts import load_alert_prefs, send_alert, channels
            prefs = load_alert_prefs()
            if prefs['enabled'] and prefs['notify_actions'] and channels(prefs):
                what = f"{backup_cfg.label(part)} from the {j['ts'][:10]} snapshot"
                if j["state"] == 'done':
                    send_alert('Restore finished', f"{what}: {j.get('files', 0)} items {'copied to ' + j['dest'] if mode == 'copy' else 'put back'}.", prefs, 'info')
                else:
                    send_alert('Restore failed', f"{what}: {j.get('error')}", prefs, 'alert')
        except Exception:
            pass


def start(ts, part, paths, mode):
    path = archive(ts, part)
    if not path:
        return None, "That part of the snapshot isn't there"
    if mode not in ('copy', 'original'):
        return None, "mode must be copy or original"
    if mode == 'original' and not target(part).get("where"):
        return None, target(part).get("why")
    paths = [_clean(p) for p in (paths or [''])]
    j = _job(ts=ts, part=part, paths=paths, mode=mode)
    threading.Thread(target=_run_restore, args=(j, path, part, paths, mode), daemon=True).start()
    return j, None
