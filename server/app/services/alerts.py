import json, os, re, threading, time, urllib.request
from app.core.logger import log
from app.core.cache import global_state
from app.core import paths
from app.core import server_cfg

PREFS_FILE = paths.state('prefs')
CHECK_SECONDS = 15


def load_alert_prefs():
    try:
        with open(PREFS_FILE) as f:
            prefs = json.load(f)
    except Exception:
        prefs = {}
    return {
        "enabled": bool(prefs.get('alerts_enabled', False)),
        "discord_webhook": (prefs.get('alerts_discord_webhook') or '').strip(),
        "ntfy_url": (prefs.get('alerts_ntfy_url') or '').strip(),
        "telegram_token": (prefs.get('alerts_telegram_token') or '').strip(),
        "telegram_chat": str(prefs.get('alerts_telegram_chat') or '').strip(),
        "pushover_user": (prefs.get('alerts_pushover_user') or '').strip(),
        "pushover_token": (prefs.get('alerts_pushover_token') or '').strip(),
        "webhook_url": (prefs.get('alerts_webhook_url') or '').strip(),
        "email_host": (prefs.get('alerts_email_host') or '').strip(),
        "email_port": int(prefs.get('alerts_email_port') or 587),
        "email_user": (prefs.get('alerts_email_user') or '').strip(),
        "email_password": prefs.get('alerts_email_password') or '',
        "email_to": (prefs.get('alerts_email_to') or '').strip(),
        "disk_threshold": int(prefs.get('alerts_disk_threshold', 90)),
        # which kinds of problem to report (category -> on); missing = on
        "kinds": {k: bool((prefs.get('alerts_kinds') or {}).get(k, True)) for k in CATEGORY_LABEL},
        "repeat_hours": float(prefs.get('alerts_repeat_hours', 6)),      # 0 = never repeat
        "host_grace": int(prefs.get('alerts_host_grace', 60)),           # seconds without a report
        "notify_resolved": bool(prefs.get('alerts_notify_resolved', True)),
        "notify_actions": bool(prefs.get('alerts_notify_actions', True)),
        "quiet": prefs.get('alerts_quiet') or None,                      # [start_hour, end_hour] local time
    }


def _in_quiet_hours(prefs, now=None):
    q = prefs.get('quiet')
    if not q or len(q) != 2 or q[0] == q[1]:
        return False
    h = time.localtime(now).tm_hour
    start, end = int(q[0]), int(q[1])
    return start <= h < end if start < end else (h >= start or h < end)


# Discord embed colour per kind
KIND_COLOUR = {
    'alert':    0xE74C3C,
    'warning':  0xF39C12,
    'resolved': 0x2ECC71,
    'info':     0x3498DB,
    'test':     0x5865F2,
}
CATEGORY_LABEL = {
    'daemon': 'Host daemon', 'container': 'Container', 'health': 'Health check', 'disk': 'Disk',
    'host': 'Host', 'machine': 'Machine', 'drive': 'Drive', 'backup': 'Backup',
}

# Shared between the polling loop and dashboard actions so a condition is only reported once
_state_lock = threading.Lock()
_active = {}      # key -> last notified time
_first_seen = {}  # key -> when the condition started


def _fmt_duration(seconds):
    seconds = int(seconds)
    if seconds < 60: return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60: return f"{m}m {s}s"
    h, m = divmod(m, 60)
    if h < 24: return f"{h}h {m}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def _discord_payload(title, body, kind, key, since):
    colour = KIND_COLOUR.get(kind, KIND_COLOUR['alert'])
    now = time.time()
    fields = []
    if key and ':' in key:
        category, target = key.split(':', 1)
        fields.append({"name": "Type", "value": CATEGORY_LABEL.get(category, category.title()), "inline": True})
        fields.append({"name": "Target", "value": f"`{target}`", "inline": True})
    fields.append({"name": "Host", "value": "`arrakis`", "inline": True})
    if since:
        if kind == 'resolved' or (kind == 'info' and key):
            fields.append({"name": "Downtime", "value": _fmt_duration(now - since), "inline": True})
        else:
            fields.append({"name": "First seen", "value": f"<t:{int(since)}:R>", "inline": True})
    embed = {
        "title": title,
        "description": body,
        "color": colour,
        "fields": fields,
        "footer": {"text": f"{server_cfg.name()} Homelab Dashboard"},
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)),
    }
    return {"username": server_cfg.name(), "embeds": [embed], "allowed_mentions": {"parse": []}}


def channels(prefs):
    """The channels that are filled in enough to send."""
    return [c for c, ok in (
        ('discord', prefs['discord_webhook']),
        ('ntfy', prefs['ntfy_url']),
        ('telegram', prefs['telegram_token'] and prefs['telegram_chat']),
        ('pushover', prefs['pushover_user'] and prefs['pushover_token']),
        ('email', prefs['email_host'] and prefs['email_to']),
        ('webhook', prefs['webhook_url']),
    ) if ok]


def _post_json(url, payload, timeout=10):
    req = urllib.request.Request(url, method='POST', data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json', 'User-Agent': 'homelab-dashboard'})
    urllib.request.urlopen(req, timeout=timeout).close()


def _send_telegram(prefs, title, body, kind):
    icon = {'alert': '🔴', 'warning': '🟠', 'resolved': '🟢', 'info': '🔵', 'test': '🔔'}.get(kind, '')
    _post_json(f"https://api.telegram.org/bot{prefs['telegram_token']}/sendMessage",
               {"chat_id": prefs['telegram_chat'], "text": f"{icon} {title}\n{body}".strip(), "disable_web_page_preview": True})


def _send_pushover(prefs, title, body, kind):
    from urllib.parse import urlencode
    data = urlencode({"token": prefs['pushover_token'], "user": prefs['pushover_user'], "title": title,
                      "message": body or title, "priority": 1 if kind == 'alert' else 0}).encode()
    urllib.request.urlopen(urllib.request.Request('https://api.pushover.net/1/messages.json', data=data, method='POST'), timeout=10).close()


def _send_email(prefs, title, body, kind):
    import smtplib, ssl
    from email.message import EmailMessage
    msg = EmailMessage()
    msg['Subject'] = f"[{server_cfg.name()}] {title}"
    msg['From'] = prefs['email_user'] or f"homelab@{server_cfg.name().lower()}"
    msg['To'] = prefs['email_to']
    msg.set_content(f"{body}\n\n— {server_cfg.name()} homelab dashboard")
    port = prefs['email_port']
    ctx = ssl.create_default_context()
    if port == 465:
        smtp = smtplib.SMTP_SSL(prefs['email_host'], port, timeout=15, context=ctx)
    else:
        smtp = smtplib.SMTP(prefs['email_host'], port, timeout=15)
        smtp.ehlo()
        if smtp.has_extn('starttls'):
            smtp.starttls(context=ctx); smtp.ehlo()
    try:
        if prefs['email_user'] and prefs['email_password']:
            smtp.login(prefs['email_user'], prefs['email_password'])
        smtp.send_message(msg)
    finally:
        try: smtp.quit()
        except Exception: pass


def _send_webhook(prefs, title, body, kind, key, since):
    _post_json(prefs['webhook_url'], {"title": title, "body": body, "kind": kind, "key": key, "since": since,
                                      "server": server_cfg.name(), "at": int(time.time())})


def send_alert(title, body, prefs=None, kind='alert', key=None, since=None):
    """Push to every configured channel. Returns a list of (channel, error-or-None).
    kind: alert | warning | resolved | info | test; key: 'category:target'; since: unix time the problem began."""
    prefs = prefs or load_alert_prefs()
    results = []
    if prefs['discord_webhook']:
        try:
            req = urllib.request.Request(prefs['discord_webhook'], method='POST',
                                         data=json.dumps(_discord_payload(title, body, kind, key, since)).encode(),
                                         headers={'Content-Type': 'application/json', 'User-Agent': 'arrakis-dashboard'})
            urllib.request.urlopen(req, timeout=10).close()
            results.append(('discord', None))
        except Exception as e:
            results.append(('discord', str(e)))
    if prefs['ntfy_url']:
        try:
            req = urllib.request.Request(prefs['ntfy_url'], method='POST', data=body.encode(),
                                         headers={'Title': title.encode('ascii', 'ignore').decode(),
                                                  'Priority': 'high' if kind == 'alert' else 'default'})
            urllib.request.urlopen(req, timeout=10).close()
            results.append(('ntfy', None))
        except Exception as e:
            results.append(('ntfy', str(e)))
    for name, fn in (('telegram', lambda: _send_telegram(prefs, title, body, kind)),
                     ('pushover', lambda: _send_pushover(prefs, title, body, kind)),
                     ('email', lambda: _send_email(prefs, title, body, kind)),
                     ('webhook', lambda: _send_webhook(prefs, title, body, kind, key, since))):
        if name not in channels(prefs):
            continue
        try:
            fn(); results.append((name, None))
        except Exception as e:
            # never echo the Telegram bot token, which sits in the URL
            results.append((name, str(e).replace(prefs['telegram_token'], '…') if prefs['telegram_token'] else str(e)))
    for channel, err in results:
        if err: log.warning(f"Alert via {channel} failed: {err}")
    return results


def current_problems(stats, disk_threshold):
    """Map of condition-key -> human message for everything currently wrong."""
    problems = {}
    for d in stats.get('daemons', []):
        if d.get('status') != 'running':
            problems[f"daemon:{d['id']}"] = f"Host daemon {d.get('name', d['id'])} is not running"
    for c in stats.get('containers', []):
        if c.get('status') != 'running':
            problems[f"container:{c['id']}"] = f"Container {c['id']} is stopped"
        elif c.get('health') == 'unhealthy':
            problems[f"health:{c['id']}"] = f"Container {c['id']} is unhealthy"
    m = re.match(r'([0-9.]+)G / ([0-9.]+)G', stats.get('host', {}).get('details', {}).get('Disk Space', ''))
    if m and float(m.group(2)) > 0:
        pct = 100 * float(m.group(1)) / float(m.group(2))
        if pct >= disk_threshold:
            problems['disk:arrakis'] = f"Disk is {pct:.0f}% full ({m.group(1)}G of {m.group(2)}G)"
    return problems


HOST_OFFLINE_AFTER = 60           # seconds without an agent report
_seen_drives = {}                 # fingerprint -> name of external drives seen since startup


def _host_problems(disk_threshold, grace=None):
    from app.api import hosts
    problems = {}
    now = time.time()
    for h in hosts._load():
        with hosts._lock:
            r = hosts._latest.get(h['id'])
        if not r or now - r['at'] > (grace or HOST_OFFLINE_AFTER):
            ago = f" (last report {_fmt_duration(now - r['at'])} ago)" if r else ""
            problems[f"host:{h['name']}"] = f"Host {h['name']} is offline{ago}"
        elif r.get('disk_total'):
            pct = 100 * r.get('disk_used', 0) / r['disk_total']
            if pct >= disk_threshold:
                problems[f"disk:{h['name']}"] = f"Disk on {h['name']} is {pct:.0f}% full"
    return problems


def _machine_problems():
    # the dashboard VM runs every container; when it is down the container checks see nothing
    from app.api import vms
    from app.core.config import VM_NAME
    machines, _ = vms._get_list(max_age=60)
    m = next((m for m in machines if m['name'] == VM_NAME), None)
    if m is None:
        return {f"machine:{VM_NAME}": f"Machine {VM_NAME} (runs the containers) no longer exists"}
    if m['state'] != 'running':
        return {f"machine:{VM_NAME}": f"Machine {VM_NAME} (runs the containers) is {m['state']}"}
    return {}


def _drive_problems(disk_threshold):
    from app.api import storage
    problems = {}
    present = set()
    for d in storage._disks(max_age=60):
        if d['internal'] or d['image']:
            continue
        name = next((v['name'] for v in d['volumes'] if v['name']), d['name'])
        _seen_drives[d['fingerprint']] = name
        present.add(d['fingerprint'])
        for v in d['volumes']:
            label = v['name'] or name
            if not v['mounted']:
                problems[f"drive:{label}"] = f"Drive {label} is attached but not mounted"
            elif v['used'] is not None and v['size']:
                pct = 100 * v['used'] / v['size']
                if pct >= disk_threshold:
                    problems[f"disk:{label}"] = f"Drive {label} is {pct:.0f}% full"
    for fp, name in _seen_drives.items():
        if fp not in present:
            problems[f"drive:{name}"] = f"Drive {name} was disconnected"
    return problems


BACKUP_PLIST = os.path.expanduser('~/Library/LaunchAgents/com.homelab.backup.plist')


def _backup_problems():
    import glob, plistlib
    from app.core import backup_cfg
    cfg = backup_cfg.load()
    snaps = {}
    for f in glob.glob(os.path.join(cfg['dest'], '*.tar.gz')):
        m = re.search(r'_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.tar\.gz$', f)
        if m:
            snaps.setdefault(m.group(1), []).append(f)
    try:
        with open(BACKUP_PLIST, 'rb') as fh:
            plist = plistlib.load(fh)
    except OSError:
        return {}  # no schedule, nothing expected
    if 'StartInterval' in plist:
        max_age = 2 * plist['StartInterval'] + 3600
    elif 'Weekday' in plist.get('StartCalendarInterval', {}):
        max_age = 8 * 86400
    else:
        max_age = 36 * 3600
    if not snaps:
        return {"backup:snapshots": "There are no backups"}
    latest = max(snaps)
    if os.path.exists('/tmp/homelab_backup.lock'):
        return {}  # one is running right now
    problems = {}
    age = time.time() - time.mktime(time.strptime(latest, '%Y-%m-%d_%H-%M-%S'))
    if age > max_age:
        problems["backup:snapshots"] = f"No backup in {_fmt_duration(age)}"
    empty = [os.path.basename(f).rsplit('_', 2)[0] for f in snaps[latest] if os.path.getsize(f) == 0]
    if empty:
        problems["backup:latest"] = f"Backup {latest} is incomplete: {', '.join(empty)} failed"
    cs = backup_cfg.copy_status() if cfg['copy_to'] else None
    if cs and not cs['ok']:
        problems["backup:copy"] = f"Backup copy to {cfg['copy_to']} failed: {cs['why'] or 'unknown error'}"
    return problems


def all_problems(stats, disk_threshold, host_grace=None):
    problems = current_problems(stats, disk_threshold)
    for check in (lambda: _host_problems(disk_threshold, host_grace), _machine_problems,
                  lambda: _drive_problems(disk_threshold), _backup_problems):
        try:
            problems.update(check())
        except Exception as e:
            log.warning(f"Alert check failed: {e}")
    return problems


ALERT_TITLES = {
    'daemon': 'Daemon down', 'container': 'Container stopped', 'health': 'Container unhealthy', 'disk': 'Disk almost full',
    'host': 'Host offline', 'machine': 'Machine down', 'drive': 'Drive problem', 'backup': 'Backup problem',
}


def _alerts_active(prefs):
    return prefs['enabled'] and bool(channels(prefs))


def notify_action(category, target, action, ok=True, error=None):
    """Report a start/stop/restart done from the dashboard right away (in the background)."""
    prefs = load_alert_prefs()
    if not _alerts_active(prefs) or not prefs['notify_actions'] or _in_quiet_hours(prefs):
        return
    key = f"{category}:{target}"
    label = CATEGORY_LABEL.get(category, category.title())
    now = time.time()
    with _state_lock:
        if not ok:
            args = (f"{label} {action} failed", f"Could not {action} **{target}**: {error or 'unknown error'}",
                    prefs, 'alert', key, None)
        elif action == 'stop':
            _first_seen[key] = now
            _active[key] = now
            args = (f"{label} stopped", f"**{target}** was stopped from the dashboard", prefs, 'warning', key, None)
        elif action == 'start':
            since = _first_seen.pop(key, None)
            _active.pop(key, None)
            args = (f"{label} started", f"**{target}** was started from the dashboard", prefs, 'resolved', key, since)
        else:
            for k in (key, f"health:{target}"):
                _first_seen.pop(k, None)
                _active.pop(k, None)
            args = (f"{label} restarted", f"**{target}** was restarted from the dashboard", prefs, 'info', None, None)
    threading.Thread(target=send_alert, args=args, daemon=True).start()


ALERT_TITLES = {
    'daemon': 'Daemon down', 'container': 'Container stopped', 'health': 'Container unhealthy', 'disk': 'Disk almost full',
    'host': 'Host offline', 'machine': 'Machine down', 'drive': 'Drive problem', 'backup': 'Backup problem',
}


def alerts_loop():
    time.sleep(60)  # let the pollers fill state so startup isn't reported as an outage
    while True:
        try:
            prefs = load_alert_prefs()
            with global_state.lock:
                stats = dict(global_state.stats) if global_state.stats else None
            if stats and _alerts_active(prefs):
                problems = all_problems(stats, prefs['disk_threshold'], prefs['host_grace'])
                problems = {k: v for k, v in problems.items() if prefs['kinds'].get(k.split(':', 1)[0], True)}
                now = time.time()
                quiet = _in_quiet_hours(prefs, now)
                repeat = prefs['repeat_hours'] * 3600
                outgoing = []
                with _state_lock:
                    for key, msg in problems.items():
                        _first_seen.setdefault(key, now)
                        # in quiet hours nothing is sent or marked, so it goes out once they end if still true
                        if quiet:
                            continue
                        if key not in _active or (repeat and now - _active[key] > repeat):
                            category = key.split(':', 1)[0]
                            outgoing.append((ALERT_TITLES.get(category, f'{server_cfg.name()} alert'), msg, prefs,
                                             'warning' if category == 'disk' else 'alert', key, _first_seen[key]))
                            _active[key] = now
                    for key in [k for k in _active if k not in problems]:
                        target = key.split(':', 1)[1]
                        if prefs['notify_resolved'] and not quiet:
                            outgoing.append(('Resolved', f"**{target}** is back to normal", prefs,
                                             'resolved', key, _first_seen.get(key)))
                        del _active[key]
                    for key in [k for k in _first_seen if k not in problems]:
                        del _first_seen[key]
                for args in outgoing:
                    results = send_alert(*args)
                    # nothing got through (e.g. DNS down): retry on the next check, not in 6 h
                    if results and all(err for _, err in results) and args[3] != 'resolved':
                        with _state_lock:
                            _active.pop(args[4], None)
        except Exception as e:
            log.error(f"Alerts loop error: {e}")
        time.sleep(CHECK_SECONDS)
