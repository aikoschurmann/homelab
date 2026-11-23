"""SQLite databases inside OrbStack machines, on Arrakis and on hosts the dashboard manages.

Machines often have no sqlite3 or python, so nothing is queried in place. Discovery runs a
small shell script as root in each running machine (`orb -m <name> -u root sh -c …`): it
finds files starting with the SQLite header and which container mounts each one. Opening
one copies the file (and its WAL) to the Mac as a snapshot, which is then browsed like any
local database. The live file is only ever read.

On Arrakis the copy streams straight to disk; from another host it comes through the
agent's text channel as base64, so it is capped at REMOTE_MAX.
"""
import base64
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import threading
import time

from app.core import orbhost
from app.core.logger import log

SNAP_DIR = os.path.expanduser("~/.cache/homelab-dbsnap")
DISCOVER_SECONDS = 300
REMOTE_MAX = 40 * 2 ** 20

# Prints "F<TAB>path<TAB>size<TAB>mtime<TAB>wal size" per SQLite file, then
# "M<TAB>container<TAB>mount source" per container mount.
DISCOVER_SH = r"""
for d in /var/lib /srv /opt /home /root /data; do [ -d "$d" ] && echo "$d"; done | while read d; do
  find "$d" -xdev -type f \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) -size +8k 2>/dev/null
done | grep -v -e '^/var/lib/docker/\(containerd\|overlay2\|image\|buildkit\|network\)/' -e '^/var/lib/\(dpkg\|apt\|containerd\)/' | while IFS= read -r f; do
  [ "$(head -c 15 "$f" 2>/dev/null)" = "SQLite format 3" ] || continue
  w=0; [ -f "$f-wal" ] && w=$(stat -c %s "$f-wal")
  printf 'F\t%s\t%s\t%s\n' "$f" "$(stat -c '%s	%Y' "$f")" "$w"
done
if command -v docker >/dev/null 2>&1; then
  docker ps -a --format '{{.Names}}' 2>/dev/null | while read c; do
    docker inspect -f '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$c" 2>/dev/null | while read m; do [ -n "$m" ] && printf 'M\t%s\t%s\n' "$c" "$m"; done
  done
fi
"""

# tar of the file and its WAL, from inside the file's folder
TAR_SH = 'cd "$(dirname "$1")" && b="$(basename "$1")" && if [ -f "$b-wal" ]; then tar -cf - "$b" "$b-wal"; else tar -cf - "$b"; fi'

_lock = threading.Lock()
_found = {"at": 0, "dbs": []}
_snap_locks = {}


def _hosts():
    """(host id or None for Arrakis, label) for every host whose OrbStack we can reach."""
    out = [(None, "Arrakis")]
    try:
        from app.api.hosts import _find
        for hid in orbhost.managed():
            out.append((hid, (_find(hid) or {}).get("name") or hid))
    except Exception as e:  # noqa: BLE001
        log.warning(f"db discovery hosts: {e}")
    return out


def _orb(hid, args, timeout=30, input=None):
    tok = orbhost.current.set(hid)
    try:
        return orbhost.run(args, timeout=timeout, input=input)
    finally:
        orbhost.current.reset(tok)


def _running(hid):
    code, out, err = _orb(hid, ["list", "-f", "json"], timeout=15)
    if code != 0:
        raise RuntimeError(err or "orb list failed")
    return [m["name"] for m in json.loads(out or "[]") if m.get("state") == "running"]


def _label(path, used_by):
    base = os.path.basename(path)
    name = base.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
    return f"{used_by.title() if used_by else ''} {name}".strip() if used_by and used_by.lower() not in name.lower() else name[:1].upper() + name[1:]


def _discover_machine(hid, host_label, machine):
    code, out, err = _orb(hid, ["-m", machine, "-u", "root", "sh", "-c", DISCOVER_SH], timeout=60)
    if code != 0 and not out:
        raise RuntimeError(err.strip() or f"discovery failed in {machine}")
    files, mounts = [], []
    for line in out.splitlines():
        p = line.split("\t")
        if p[0] == "F" and len(p) >= 5:
            files.append({"path": p[1], "size": int(p[2] or 0), "mtime": int(p[3] or 0), "wal": int(p[4] or 0)})
        elif p[0] == "M" and len(p) >= 3:
            mounts.append((p[1], p[2].rstrip("/")))
    dbs = []
    for f in files:
        # the container whose mount holds the file (the longest matching mount wins)
        hits = [(len(src), c) for c, src in mounts if f["path"].startswith(src + "/")]
        used_by = max(hits)[1] if hits else None
        dbs.append({**f, "host": hid, "host_name": host_label, "machine": machine, "used_by": used_by,
                    "name": _label(f["path"], used_by)})
    return dbs


def discover(force=False):
    """Every SQLite file in every running machine, cached for a few minutes."""
    with _lock:
        if not force and _found["at"] and time.time() - _found["at"] < DISCOVER_SECONDS:
            return _found["dbs"]
    dbs, ids = [], set()
    for hid, label in _hosts():
        try:
            machines = _running(hid)
        except Exception as e:  # noqa: BLE001
            log.warning(f"db discovery on {label}: {e}")
            continue
        for m in machines:
            try:
                found = _discover_machine(hid, label, m)
            except Exception as e:  # noqa: BLE001
                log.warning(f"db discovery in {m} on {label}: {e}")
                continue
            for d in sorted(found, key=lambda x: x["path"]):
                base = f"{hid + '~' if hid else ''}{m}:{os.path.basename(d['path'])}"
                did, n = base, 2
                while did in ids:
                    did, n = f"{base}-{n}", n + 1
                ids.add(did)
                d["id"] = did
                dbs.append(d)
    with _lock:
        _found.update(at=time.time(), dbs=dbs)
    return dbs


def find(db_id):
    return next((d for d in discover() if d["id"] == db_id), None)


# ---- snapshots ---------------------------------------------------------------------

def _snap_path(d):
    key = hashlib.sha1(f"{d['host']}|{d['machine']}|{d['path']}".encode()).hexdigest()[:16]
    return os.path.join(SNAP_DIR, key, os.path.basename(d["path"]))


def snapshot_info(d):
    p = _snap_path(d)
    try:
        return {"path": p, "at": os.path.getmtime(p), "size": os.path.getsize(p)}
    except OSError:
        return None


def take_snapshot(d):
    """Copy the live file (and WAL) into the snapshot folder, then fold the WAL into the
    copy so it opens read-only like any single-file database."""
    dest = _snap_path(d)
    with _lock:
        lk = _snap_locks.setdefault(dest, threading.Lock())
    with lk:
        folder = os.path.dirname(dest)
        tmp = folder + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, mode=0o700)
        os.chmod(SNAP_DIR, 0o700)
        args = ["-m", d["machine"], "-u", "root", "sh", "-c", TAR_SH, "tar", d["path"]]
        try:
            if d["host"] is None:
                tar_file = os.path.join(tmp, "snap.tar")
                with open(tar_file, "wb") as out:
                    res = subprocess.run(["orb", *args], stdout=out, stderr=subprocess.PIPE, timeout=300)
                if res.returncode != 0:
                    raise RuntimeError(res.stderr.decode(errors="replace").strip() or "copy failed")
                with tarfile.open(tar_file) as t:
                    t.extractall(tmp, filter="data")
                os.remove(tar_file)
            else:
                if d["size"] + d["wal"] > REMOTE_MAX:
                    raise RuntimeError(f"Too big to copy through {d['host_name']}'s agent ({(d['size'] + d['wal']) // 2 ** 20} MB; the limit is {REMOTE_MAX // 2 ** 20} MB)")
                code, out, err = _orb(d["host"], ["-m", d["machine"], "-u", "root", "sh", "-c", f"( {TAR_SH} ) | base64", "tar", d["path"]], timeout=300)
                if code != 0:
                    raise RuntimeError(err.strip() or "copy failed")
                with tarfile.open(fileobj=io.BytesIO(base64.b64decode(out))) as t:
                    t.extractall(tmp, filter="data")
            copy = os.path.join(tmp, os.path.basename(d["path"]))
            conn = sqlite3.connect(copy, timeout=5)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("PRAGMA journal_mode=DELETE")
            finally:
                conn.close()
            for extra in ("-wal", "-shm"):
                if os.path.exists(copy + extra):
                    os.remove(copy + extra)
            shutil.rmtree(folder, ignore_errors=True)
            os.rename(tmp, folder)
            os.utime(dest)  # tar kept the live file's time; the snapshot's age is when we copied it
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    log.info(f"db snapshot {d['id']}: {os.path.getsize(dest)} bytes")
    return snapshot_info(d)
