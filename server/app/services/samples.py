"""Extra per-host history for the Metrics page: temperatures, network rate and Wi-Fi.

One narrow table, `samples (timestamp, node, key, value)`, at most one row per node and key
a minute. Keys:
    temp_cpu, temp_ssd   °C
    net_rx, net_tx       bytes/s, from the byte counters' change since the last row
    wifi_signal          % (NetworkManager's scale; dBm from macOS or the kernel converted:
                         2 × (dBm + 100), clamped to 0–100)
    wifi_rate            Mbit/s (the link's transmit rate)

This server is sampled here every minute; other hosts' agents send byte counters with every
report (agent 19) and temperatures / Wi-Fi with their inventory once a minute.
"""
import re, subprocess, threading, time

from app.core.logger import log

EVERY = 60
_lock = threading.Lock()
_net = {}       # node -> (t, rx, tx) of the last stored rate
_last = {}      # (node, key) -> time of the last row
wifi_info = {}  # node -> {"ssid", "signal", "rate", "at"}: the latest reading, for labels


def _insert(node, values, t=None):
    from app.core.db import get_writer
    t = int(t or time.time())
    for k, v in values.items():
        if v is not None:
            get_writer().execute('INSERT INTO samples (timestamp, node, key, value) VALUES (?, ?, ?, ?)', (t, node, k, float(v)))


def record(node, values, every=EVERY):
    """Store values ({key: number}) unless this node's same keys were stored under a minute ago."""
    now = time.time()
    keep = {}
    with _lock:
        for k, v in values.items():
            if v is None or now - _last.get((node, k), 0) < every - 2:
                continue
            _last[(node, k)] = now
            keep[k] = v
    if keep:
        try:
            _insert(node, keep, now)
        except Exception as e:  # noqa: BLE001
            log.warning(f"samples {node}: {e}")


def net_counters(node, rx, tx):
    """Cumulative byte counters; stores the average rate over each minute."""
    if rx is None or tx is None:
        return
    now = time.time()
    with _lock:
        prev = _net.get(node)
        if prev and now - prev[0] < EVERY - 2:
            return
        _net[node] = (now, rx, tx)
    if not prev:
        return
    dt = now - prev[0]
    # counters reset (reboot, interface back up): skip this minute
    if dt <= 0 or dt > EVERY * 10 or rx < prev[1] or tx < prev[2]:
        return
    try:
        _insert(node, {"net_rx": (rx - prev[1]) / dt, "net_tx": (tx - prev[2]) / dt}, now)
    except Exception as e:  # noqa: BLE001
        log.warning(f"samples net {node}: {e}")


# ---- Wi-Fi ---------------------------------------------------------------------------------
def pct(dbm):
    return None if dbm is None else max(0, min(100, 2 * (dbm + 100)))


def parse_mac_wifi(text):
    """system_profiler SPAirPortDataType: the "Current Network Information" block."""
    if not text or 'Current Network Information' not in text:
        return None
    block = text.split('Current Network Information:', 1)[1].split('Other Local Wi-Fi Networks', 1)[0]
    m_ssid = re.search(r'^\s*(.+?):\s*$', block, re.M)
    m_sig = re.search(r'Signal / Noise:\s*(-?\d+)\s*dBm', block)
    m_rate = re.search(r'Transmit Rate:\s*(\d+)', block)
    if not m_sig and not m_rate:
        return None
    dbm = int(m_sig.group(1)) if m_sig else None
    ssid = m_ssid.group(1).strip() if m_ssid else None
    # macOS hides the name from processes without Location access
    if ssid and ssid.startswith('<'):
        ssid = None
    return {"ssid": ssid, "dbm": dbm, "signal": pct(dbm),
            "rate": int(m_rate.group(1)) if m_rate else None}


def parse_linux_wifi(text):
    """/proc/net/wireless rows, "nmcli *:<signal %>:<rate>:<ssid>" when NetworkManager runs,
    then "iface <name>" and `iw dev <name> link` for each interface."""
    if not text:
        return None
    m = re.search(r'^nmcli \*:(\d+):(\d+)[^:]*:(.*)$', text, re.M)
    if m:
        return {"ssid": m.group(3).strip() or None, "dbm": None, "signal": int(m.group(1)), "rate": int(m.group(2))}
    dbm = None
    m_isig = re.search(r'signal:\s*(-?\d+)\s*dBm', text)
    if m_isig:
        dbm = int(m_isig.group(1))
    else:
        for line in text.splitlines():
            m = re.match(r'\s*(\w+):\s+\d+\s+[-\d.]+\s+(-?\d+)\.?', line)
            # some drivers (e.g. a Pi's) report nonsense here; only a plausible level counts
            if m and -100 <= int(m.group(2)) <= -20:
                dbm = int(m.group(2))
                break
    m_ssid = re.search(r'SSID:\s*(.+)', text)
    m_rate = re.search(r'tx bitrate:\s*([\d.]+)\s*MBit', text)
    if dbm is None and not m_rate:
        return None
    return {"ssid": m_ssid.group(1).strip() if m_ssid else None, "dbm": dbm, "signal": pct(dbm),
            "rate": round(float(m_rate.group(1))) if m_rate else None}


def _wifi(node, w):
    if not w:
        return
    with _lock:
        wifi_info[node] = {**w, "at": int(time.time())}
    record(node, {"wifi_signal": w.get("signal"), "wifi_rate": w.get("rate")})


# ---- other hosts ---------------------------------------------------------------------------
def from_inventory(node, sections):
    """Temperatures and Wi-Fi from an agent's inventory (once a minute)."""
    try:
        from app.services.hardware import summarize_temps
        pairs = []
        for line in (sections.get('temps') or '').splitlines():
            bits = line.strip().rsplit(None, 1)
            if len(bits) != 2:
                continue
            try:
                c = float(bits[1])
            except ValueError:
                continue
            pairs.append((bits[0], c / 1000 if c > 1000 else c))
        t = summarize_temps(pairs)
        if t:
            record(node, {"temp_cpu": t.get("cpu"), "temp_ssd": t.get("ssd")})
        w = sections.get('wifi')
        if w is not None:
            _wifi(node, parse_mac_wifi(w) if 'Current Network Information' in w or 'Wi-Fi' in w else parse_linux_wifi(w))
    except Exception as e:  # noqa: BLE001
        log.warning(f"samples inventory {node}: {e}")


# ---- this server ---------------------------------------------------------------------------
def _local_net():
    import psutil
    rx = tx = 0
    for name, c in psutil.net_io_counters(pernic=True).items():
        # the physical interfaces (en*): not loopback, bridges or the Tailscale tunnel,
        # whose traffic already passes through them
        if name.startswith('en'):
            rx += c.bytes_recv
            tx += c.bytes_sent
    return rx, tx


def _local_wifi():
    try:
        out = subprocess.run(['system_profiler', 'SPAirPortDataType'], capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001
        return None
    return parse_mac_wifi(out)


def local_loop():
    from app.services import hardware
    while True:
        try:
            net_counters('arrakis', *_local_net())
            t = (hardware.local() or {}).get('temps') or {}
            record('arrakis', {"temp_cpu": t.get('cpu'), "temp_ssd": t.get('ssd')})
            _wifi('arrakis', _local_wifi())
        except Exception as e:  # noqa: BLE001
            log.warning(f"samples local: {e}")
        time.sleep(EVERY / 2)


def start():
    threading.Thread(target=local_loop, daemon=True).start()
