"""Drives on Arrakis: every physical disk and its volumes.

build_disks() also builds other Macs' drives, from the same diskutil plists their agent
reports (app/api/hosts.py); Linux hosts' drives come from lsblk there.

Listing and info come from `diskutil -plist` (read-only). The only actions are mount,
unmount and eject. Nothing here can erase, format or rename a drive, by design.
Drives the user marked as never-to-be-erased are listed in ~/.homelab_storage.json
(model name + exact size) and shown as Protected.
"""
from flask import Blueprint, jsonify, request
import json
import os
import plistlib
import re
import subprocess
import threading
import time

from app.core.logger import log

storage_bp = Blueprint('storage', __name__)

STORE = os.path.expanduser('~/.homelab_storage.json')
# APFS volumes that are plumbing, not something to show
HIDDEN_ROLES = {'Preboot', 'Recovery', 'Update', 'VM', 'xART', 'Hardware'}
_lock = threading.Lock()
_cache = {"at": 0, "data": None}


def _plist(args, timeout=15):
    res = subprocess.run(['diskutil', *args], capture_output=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).decode(errors='replace').strip() or 'diskutil failed')
    return plistlib.loads(res.stdout)


def _run(args, timeout=120):
    res = subprocess.run(['diskutil', *args], capture_output=True, text=True, timeout=timeout)
    out = (res.stdout + res.stderr).strip()
    if res.returncode != 0:
        raise RuntimeError(out.splitlines()[-1] if out else 'diskutil failed')
    return out


# ---- protection --------------------------------------------------------------------------

def _load():
    try:
        with open(STORE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"protected": []}


def _fingerprint(info):
    return f"{info.get('MediaName', '').strip()}|{info.get('Size') or info.get('TotalSize')}"


# ---- listing -----------------------------------------------------------------------------

def _volume(info, role=None):
    mp = info.get('MountPoint') or ''
    # sizes from diskutil, not statvfs: a hung volume must not hang this listing
    total = info.get('TotalSize') or info.get('Size')
    free = info.get('APFSContainerFree') if info.get('FilesystemType') == 'apfs' else info.get('FreeSpace')
    if free is None:
        free = info.get('FreeSpace')
    used = (total - free) if (mp and total and free is not None) else None
    if not mp:
        free = None
    return {
        "id": info.get('DeviceIdentifier'),
        "name": info.get('VolumeName') or '',
        "format": info.get('FilesystemName') or info.get('Content') or '',
        "size": info.get('TotalSize') or info.get('Size'),
        "mounted": bool(mp),
        "mount_point": mp or None,
        "writable": bool(info.get('WritableVolume')),
        "used": used, "free": free,
        "role": role,
    }


def protected_set():
    return set(_load().get('protected', []))


def _build():
    boot = os.stat('/').st_dev
    return build_disks(_plist, lambda mp: _same_dev(mp, boot))


def build_disks(_plist, is_boot):
    """_plist(args) -> parsed `diskutil <args>` output; is_boot(mount point) -> on the system volume."""
    listing = _plist(['list', '-plist', 'physical'])
    # mounted disk images aren't "physical"; list them too, as images
    everything = _plist(['list', '-plist'])
    images = [d for d in everything.get('WholeDisks', []) if d not in listing.get('WholeDisks', [])
              and _plist(['info', '-plist', d]).get('BusProtocol') == 'Disk Image']
    listing['WholeDisks'] = listing.get('WholeDisks', []) + images
    listing['AllDisksAndPartitions'] = everything.get('AllDisksAndPartitions', [])
    apfs = {}
    try:
        for c in _plist(['apfs', 'list', '-plist']).get('Containers', []):
            for store in c.get('PhysicalStores', []):
                apfs[store['DeviceIdentifier']] = c
    except Exception as e:  # noqa: BLE001
        log.warning(f"apfs list: {e}")
    protected = protected_set()

    disks = []
    for whole in listing.get('WholeDisks', []):
        info = _plist(['info', '-plist', whole])
        if info.get('VirtualOrPhysical') == 'Virtual' and info.get('BusProtocol') != 'Disk Image':
            continue
        vols = []
        for part in next((d for d in listing['AllDisksAndPartitions'] if d['DeviceIdentifier'] == whole), {}).get('Partitions', []):
            pid = part['DeviceIdentifier']
            if pid in apfs:
                # an APFS container: show its real volumes, the system's as one "Macintosh HD"
                for v in apfs[pid].get('Volumes', []):
                    roles = set(v.get('Roles') or [])
                    if roles & HIDDEN_ROLES or 'System' in roles:
                        continue
                    vi = _plist(['info', '-plist', v['DeviceIdentifier']])
                    vol = _volume(vi, 'Data' if 'Data' in roles else None)
                    if 'Data' in roles:
                        vol["name"] = 'Macintosh HD'
                    vols.append(vol)
            elif part.get('Content') not in ('EFI', 'Apple_APFS_ISC', 'Apple_APFS_Recovery', 'Apple_Boot'):
                vols.append(_volume(_plist(['info', '-plist', pid])))
        system = any(v["mount_point"] and is_boot(v["mount_point"]) for v in vols) or info.get('Internal', False)
        fp = _fingerprint(info)
        disks.append({
            "id": whole,
            "name": (info.get('MediaName') or whole).strip(),
            "size": info.get('Size') or info.get('TotalSize'),
            "internal": bool(info.get('Internal')),
            "protocol": info.get('BusProtocol') or '',
            "ssd": bool(info.get('SolidState')),
            "removable": bool(info.get('Removable') or info.get('Ejectable')),
            "ejectable": bool(info.get('Ejectable')) and not info.get('Internal'),
            "smart": info.get('SMARTStatus') or 'Not Supported',
            "image": info.get('BusProtocol') == 'Disk Image',
            "system": bool(system),
            "protected": fp in protected,
            "fingerprint": fp,
            "volumes": vols,
        })
    disks.sort(key=lambda d: (not d["internal"], d["image"], d["id"]))
    return disks


def _same_dev(path, dev):
    try:
        return os.stat(path).st_dev == dev
    except OSError:
        return False


def _disks(max_age=10):
    with _lock:
        if _cache["data"] is None or time.time() - _cache["at"] > max_age:
            _cache["data"], _cache["at"] = _build(), time.time()
        return _cache["data"]


def _invalidate():
    with _lock:
        _cache["at"] = 0


def _find_disk(did):
    return next((d for d in _disks(0) if d["id"] == did), None)


def _find_volume(vid):
    for d in _disks(0):
        for v in d["volumes"]:
            if v["id"] == vid:
                return d, v
    return None, None


def _err(msg, code=400):
    return jsonify({"status": "error", "message": msg}), code


# ---- routes ------------------------------------------------------------------------------

@storage_bp.route('/disks', methods=['GET'])
def list_disks():
    try:
        return jsonify({"status": "success", "data": _disks()})
    except Exception as e:  # noqa: BLE001
        return _err(str(e), 500)


@storage_bp.route('/volumes/<vid>/<action>', methods=['POST'])
def volume_action(vid, action):
    d, v = _find_volume(vid)
    if not v:
        return _err('No such volume', 404)
    if d["system"] and action == 'unmount':
        return _err("That's the system drive")
    try:
        if action == 'mount':
            _run(['mount', vid])
        elif action == 'unmount':
            _run(['unmount', vid])
        else:
            return _err('Unknown action', 404)
    except RuntimeError as e:
        return _err(str(e))
    finally:
        _invalidate()
    return jsonify({"status": "success"})


@storage_bp.route('/disks/<did>/eject', methods=['POST'])
def eject(did):
    d = _find_disk(did)
    if not d:
        return _err('No such drive', 404)
    if d["internal"] or d["system"]:
        return _err("The internal drive can't be ejected")
    try:
        _run(['eject', did])
    except RuntimeError as e:
        return _err(str(e))
    finally:
        _invalidate()
    return jsonify({"status": "success"})
