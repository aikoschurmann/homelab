"""Hardware health: temperatures, drive health (SMART) and UPS / power.

This server (a Mac) is read here; other hosts send the same raw material in their agent's
inventory (see hosts.py), which `from_inventory` turns into the same shape:

    {"temps": {"cpu": °C, "ssd": °C, "sensors": [{"name", "c"}]} | None,
     "drives": [{"name", "model", "health": ok|failing|unknown, "detail", "temp", "hours", "wear"}],
     "power": {"source": "ac"|"ups"|"battery", "ups": [{"name", "pct", "state", "remaining"}]} | None,
     "thermal": "nominal" | "<warning>" | None}
"""
import json, os, plistlib, re, shutil, subprocess, threading, time

from app.core import paths
from app.core.logger import log

TEMP_WARN = {"cpu": 95, "ssd": 70}    # °C: alert above these
_cache = {"at": 0, "data": None}
_lock = threading.Lock()

SRC = os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'hidtemps.c')
BIN = os.path.join(paths.DATA, 'bin', 'hidtemps')


def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ''


# ---- temperatures -----------------------------------------------------------------------
def _helper():
    """Path of the compiled sensor reader, building it when missing or older than its source."""
    src = os.path.abspath(SRC)
    try:
        if os.path.exists(BIN) and os.path.getmtime(BIN) >= os.path.getmtime(src):
            return BIN
        if not shutil.which('clang'):
            return None
        os.makedirs(os.path.dirname(BIN), exist_ok=True)
        r = subprocess.run(['clang', '-O2', '-framework', 'IOKit', '-framework', 'CoreFoundation', src, '-o', BIN],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            log.warning(f"hidtemps build failed: {r.stderr[-300:]}")
            return None
        return BIN
    except Exception as e:
        log.warning(f"hidtemps: {e}")
        return None


def summarize_temps(pairs):
    """[(name, °C)] -> {"cpu", "ssd", "sensors"}: CPU = hottest die/core sensor, SSD = hottest NAND/NVMe."""
    pairs = [(n, c) for n, c in pairs if c is not None and -20 < c < 150]
    if not pairs:
        return None
    low = lambda n: n.lower()
    cpu = [c for n, c in pairs if re.search(r'tdie|tdev|cpu|core|package|tctl|x86_pkg|soc', low(n)) and 'tcal' not in low(n)]
    ssd = [c for n, c in pairs if re.search(r'nand|nvme|ssd|composite', low(n))]
    return {"cpu": round(max(cpu), 1) if cpu else None, "ssd": round(max(ssd), 1) if ssd else None,
            "sensors": [{"name": n, "c": round(c, 1)} for n, c in sorted(pairs)]}


def _mac_temps():
    b = _helper()
    if not b:
        return None
    pairs = []
    for line in _run([b], timeout=5).splitlines():
        name, _, c = line.rpartition('\t')
        try:
            pairs.append((name.strip(), float(c)))
        except ValueError:
            pass
    return summarize_temps(pairs)


def _mac_thermal():
    out = _run(['pmset', '-g', 'therm'])
    m = re.search(r'thermal warning level.*?(\d+)', out, re.I)
    if 'No thermal warning level has been recorded' in out or (m and m.group(1) == '0'):
        return 'nominal'
    return 'warning' if m else None


# ---- drives -------------------------------------------------------------------------------
def _smartctl(dev, sat=False):
    """smartctl's JSON for a device, or None (not installed, no permission, unsupported)."""
    exe = shutil.which('smartctl') or next((p for p in ('/opt/homebrew/sbin/smartctl', '/usr/local/sbin/smartctl') if os.path.exists(p)), None)
    if not exe:
        return None
    try:
        args = [exe, '-j', '-H', '-A', '-i'] + (['-d', 'sat'] if sat else []) + [dev]
        out = subprocess.run(args, capture_output=True, text=True, timeout=15).stdout
        j = json.loads(out)
        return j if j.get('smart_status') or j.get('temperature') else None
    except Exception:
        return None


def from_smartctl(j):
    """The fields we show, from smartctl -j output (ATA or NVMe)."""
    out = {}
    st = (j.get('smart_status') or {}).get('passed')
    if st is not None:
        out['health'] = 'ok' if st else 'failing'
    t = (j.get('temperature') or {}).get('current')
    if t is not None:
        out['temp'] = t
    h = (j.get('power_on_time') or {}).get('hours')
    if h is not None:
        out['hours'] = h
    nv = j.get('nvme_smart_health_information_log') or {}
    if 'percentage_used' in nv:
        out['wear'] = nv['percentage_used']
    for a in (j.get('ata_smart_attributes') or {}).get('table') or []:
        if a.get('id') in (5, 197, 198) and (a.get('raw') or {}).get('value'):
            out.setdefault('detail', [])
            out['detail'].append(f"{a['raw']['value']} {a.get('name', '').replace('_', ' ').lower()}")
            if a['id'] in (5, 197) and a['raw']['value'] > 0 and out.get('health') == 'ok':
                out['health'] = 'warn'
    if isinstance(out.get('detail'), list):
        out['detail'] = ', '.join(out['detail'])
    if j.get('model_name'):
        out['model'] = j['model_name']
    return out


def mac_drive_health(info):
    """One drive from `diskutil info -plist` (+ smartctl when installed)."""
    d = {"name": info.get('MediaName') or info.get('IORegistryEntryName') or info.get('DeviceIdentifier'),
         "dev": info.get('DeviceIdentifier'), "internal": bool(info.get('Internal')),
         "bus": info.get('BusProtocol'), "health": "unknown", "detail": None}
    s = (info.get('SMARTStatus') or '').lower()
    if s == 'verified':
        d['health'] = 'ok'
    elif s == 'failing':
        d['health'], d['detail'] = 'failing', 'macOS reports the drive is failing'
    else:
        d['detail'] = 'Health not reported over ' + (info.get('BusProtocol') or 'this connection')
    return d


def _mac_drives():
    try:
        pl = plistlib.loads(subprocess.run(['diskutil', 'list', '-plist', 'physical'], capture_output=True, timeout=10).stdout)
    except Exception:
        return []
    drives = []
    for disk in pl.get('WholeDisks') or []:
        try:
            info = plistlib.loads(subprocess.run(['diskutil', 'info', '-plist', disk], capture_output=True, timeout=10).stdout)
        except Exception:
            continue
        if info.get('VirtualOrPhysical') == 'Virtual':
            continue
        d = mac_drive_health(info)
        j = _smartctl(f"/dev/{disk}") or (None if d['internal'] else _smartctl(f"/dev/{disk}", sat=True))
        if j:
            sm = from_smartctl(j)
            if d['health'] == 'unknown' or sm.get('health') in ('failing', 'warn'):
                d['health'] = sm.get('health', d['health'])
                d['detail'] = sm.get('detail')
            d.update({k: sm[k] for k in ('temp', 'hours', 'wear') if k in sm})
            if sm.get('detail'):
                d['detail'] = sm['detail']
        drives.append(d)
    return drives


# ---- power ---------------------------------------------------------------------------------
def parse_pmset_ps(out):
    """`pmset -g ps` -> {"source", "ups": [...]}; a UPS plugged in over USB shows here."""
    m = re.search(r"Now drawing from '([^']+)'", out)
    src = (m.group(1) if m else '').lower()
    source = 'ups' if 'ups' in src else 'battery' if 'battery' in src else 'ac' if src else None
    ups = []
    for line in out.splitlines():
        m = re.match(r'\s*-(.+?)\s+\(id=\d+\)\s+(\d+)%;\s*([^;]+);?\s*([^\t]*)', line)
        if not m or 'InternalBattery' in m.group(1):
            continue
        rem = re.search(r'(\d+:\d+) remaining', m.group(4))
        ups.append({"name": m.group(1).strip(), "pct": int(m.group(2)), "state": m.group(3).strip(),
                    "remaining": rem.group(1) if rem else None})
    return {"source": source, "ups": ups}


# ---- this server ---------------------------------------------------------------------------
def local():
    """This server's hardware health, read at most every 30 s."""
    with _lock:
        if _cache['data'] and time.time() - _cache['at'] < 30:
            return _cache['data']
    data = {"temps": _mac_temps(), "drives": _mac_drives(), "power": parse_pmset_ps(_run(['pmset', '-g', 'ps'])),
            "thermal": _mac_thermal(), "smartctl": bool(shutil.which('smartctl') or os.path.exists('/opt/homebrew/sbin/smartctl')),
            "at": int(time.time())}
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data


# ---- another host, from its agent's inventory sections --------------------------------------
def from_inventory(sections):
    """The same shape from an agent's inventory: Linux sends #@temps / #@smart <dev> / #@upsc <name>;
    a Mac's #@diskutil info sections carry SMARTStatus, and #@pmset ps its power source."""
    data = {"temps": None, "drives": [], "power": None, "thermal": None}
    pairs = []
    for line in (sections.get('temps') or '').splitlines():
        name, _, v = line.rpartition(' ')
        try:
            c = float(v)
            pairs.append((name.strip() or 'sensor', c / 1000 if c > 1000 else c))
        except ValueError:
            pass
    data['temps'] = summarize_temps(pairs)
    for key, body in sections.items():
        if key.startswith('smart '):
            try:
                j = json.loads(body)
            except ValueError:
                continue
            sm = from_smartctl(j)
            data['drives'].append({"name": sm.get('model') or key[6:], "dev": key[6:], "health": sm.get('health', 'unknown'),
                                   "detail": sm.get('detail'), **{k: sm[k] for k in ('temp', 'hours', 'wear') if k in sm}})
        elif key.startswith('diskutil info -plist '):
            try:
                info = plistlib.loads(body.encode())
            except Exception:
                continue
            if info.get('WholeDisk') and info.get('VirtualOrPhysical') != 'Virtual':
                data['drives'].append(mac_drive_health(info))
    ups = []
    for key, body in sections.items():
        if key.startswith('upsc '):
            kv = dict(l.split(': ', 1) for l in body.splitlines() if ': ' in l)
            status = kv.get('ups.status', '')
            secs = int(float(kv['battery.runtime'])) if kv.get('battery.runtime', '').replace('.', '').isdigit() else None
            ups.append({"name": kv.get('device.model') or kv.get('ups.model') or key[5:],
                        "pct": int(float(kv['battery.charge'])) if kv.get('battery.charge') else None,
                        "state": 'on battery' if 'OB' in status.split() else 'charging' if 'CHRG' in status.split() else 'on mains',
                        "remaining": f"{secs // 3600}:{secs % 3600 // 60:02d}" if secs else None,
                        "low": 'LB' in status.split()})
    if 'pmset ps' in sections:
        data['power'] = parse_pmset_ps(sections['pmset ps'])
    elif ups:
        data['power'] = {"source": 'ups' if any(u['state'] == 'on battery' for u in ups) else 'ac', "ups": ups}
    return data


# ---- alert conditions ----------------------------------------------------------------------
def problems_of(label, hw):
    out = {}
    if not hw:
        return out
    t = hw.get('temps') or {}
    for k, limit in TEMP_WARN.items():
        if t.get(k) is not None and t[k] >= limit:
            out[f"temp:{label} {k}"] = f"{label}: {'CPU' if k == 'cpu' else 'SSD'} is at {t[k]:.0f} °C"
    for d in hw.get('drives') or []:
        if d.get('health') in ('failing', 'warn'):
            out[f"smart:{label} {d.get('dev') or d.get('name')}"] = \
                f"{label}: drive {d.get('name')} {'is failing' if d['health'] == 'failing' else 'has bad sectors'}{' (' + d['detail'] + ')' if d.get('detail') else ''}"
    p = hw.get('power') or {}
    if p.get('source') == 'ups':
        u = (p.get('ups') or [{}])[0]
        out[f"ups:{label}"] = f"{label} is running on UPS battery{' at ' + str(u['pct']) + '%' if u.get('pct') is not None else ''}" \
                              f"{', about ' + u['remaining'] + ' left' if u.get('remaining') else ''}. The power may be out."
    return out
