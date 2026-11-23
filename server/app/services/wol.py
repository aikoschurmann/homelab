"""Wake-on-LAN for other hosts.

While a host is online and Tailscale reaches it directly on the LAN, its LAN address is
looked up in this Mac's ARP table and the hardware (MAC) address is remembered in the hosts
store. Waking sends the magic packet (6 x 0xFF, then the MAC 16 times) as a UDP broadcast
on ports 9 and 7, to the whole network and to the host's own subnet.
"""
import ipaddress, json, re, socket, subprocess, threading, time

from app.core.logger import log

EVERY = 300


def _peers():
    st = json.loads(subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=5).stdout or '{}')
    out = {}
    for p in (st.get('Peer') or {}).values():
        for ip in p.get('TailscaleIPs') or []:
            out[ip] = p
    return out


def _arp(ip):
    out = subprocess.run(['arp', '-n', ip], capture_output=True, text=True, timeout=5).stdout
    m = re.search(r' at ([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5}) ', out, re.I)
    return ':'.join(x.zfill(2) for x in m.group(1).lower().split(':')) if m else None


def learn():
    """Remember LAN address and MAC of every online host that is directly on the LAN."""
    from app.api import hosts as H
    try:
        peers = _peers()
    except Exception as e:
        log.warning(f"wol: tailscale status: {e}")
        return
    with H._lock:
        rows = H._load()
        changed = False
        for h in rows:
            r = H._latest.get(h['id']) or {}
            p = peers.get(r.get('ip') or '')
            cur = (p or {}).get('CurAddr') or ''
            ip = cur.rsplit(':', 1)[0].strip('[]')
            try:
                if not ip or not ipaddress.ip_address(ip).is_private:
                    continue
            except ValueError:
                continue
            mac = _arp(ip)
            if mac and (h.get('mac') != mac or h.get('lan_ip') != ip):
                h.update(mac=mac, lan_ip=ip)
                changed = True
        if changed:
            H._save(rows)


def loop():
    time.sleep(30)
    while True:
        try:
            learn()
        except Exception as e:
            log.warning(f"wol learn: {e}")
        time.sleep(EVERY)


def start():
    threading.Thread(target=loop, daemon=True, name='wol').start()


def wake(mac, lan_ip=None):
    raw = bytes.fromhex(mac.replace(':', '').replace('-', ''))
    if len(raw) != 6:
        raise ValueError('bad MAC address')
    packet = b'\xff' * 6 + raw * 16
    targets = ['255.255.255.255']
    if lan_ip:
        try:
            targets.append(str(ipaddress.ip_network(f"{lan_ip}/24", strict=False).broadcast_address))
        except ValueError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for t in targets:
            for port in (9, 7):
                s.sendto(packet, (t, port))
    return targets
