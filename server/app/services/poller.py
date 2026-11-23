import re, time, sys, subprocess, threading, os, json, html, psutil
from app.core.logger import log
from app.core.config import VM_CMD_PREFIX
from app.core.cache import global_state
from app.services.arrakis_parser import parse_arrakis_native

def poll_metrics_loop():
    last_net = psutil.net_io_counters()
    last_time = time.time()
    while True:
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            now_net = psutil.net_io_counters()
            now_time = time.time()
            dt = now_time - last_time
            mbps = 0.0
            if dt > 0:
                mbps = ((now_net.bytes_sent - last_net.bytes_sent) + (now_net.bytes_recv - last_net.bytes_recv)) * 8 / 1_000_000 / dt
            last_net, last_time = now_net, now_time
            
            used_mem = psutil.virtual_memory().used
            
            with global_state.lock:
                global_state.system_history['cpu'].append(cpu)
                global_state.system_history['mem'].append(mem)
                if 'net' not in global_state.system_history:
                    from collections import deque
                    global_state.system_history['net'] = deque(maxlen=30)
                global_state.system_history['net'].append(mbps)
                if global_state.stats and "host" in global_state.stats:
                    global_state.stats["host"]["details"]["CPU Usage"] = f"{cpu:.1f}%"
                    global_state.stats["host"]["details"]["Memory"] = f"{used_mem / (1024**3):.2f}G / {psutil.virtual_memory().total / (1024**3):.2f}G"
            try:
                usage = psutil.disk_usage('/System/Volumes/Data')
                with global_state.lock:
                    global_state.storage['total'] = usage.total
                    global_state.storage['used'] = usage.used
                    global_state.storage['free'] = usage.free
            except Exception as e: log.warning(f"Storage poll error: {e}")
        except Exception as e: log.error(f"Metric loop error: {e}")
        time.sleep(2)

def refresh_tmux_cache():
    from app.core.tmux_target import list_sessions
    sessions = list_sessions()
    with global_state.lock:
        global_state.tmux_sessions = sessions

def poll_tmux_loop():
    while True:
        try: refresh_tmux_cache()
        except Exception as e: log.error(f"Tmux loop error: {e}")
        time.sleep(5)

def poll_services_loop():
    while True:
        try:
            try:
                vm_script = 'echo "CPU:$(top -bn1 | awk -F, \'/Cpu\\(s\\):/ {for(i=1;i<=NF;i++) if($i ~ /id/) {split($i,a," "); print 100-a[1]"%"}}\')"\necho "MEM:$(free -m | awk \'/^Mem:/ {printf "%.2fG / %.2fG", $3/1000, $2/1000}\')"'
                vm_out = subprocess.run(VM_CMD_PREFIX + ["sh", "-c", vm_script], capture_output=True, text=True, timeout=5)
                if vm_out.returncode == 0:
                    for line in vm_out.stdout.strip().split('\n'):
                        if line.startswith('CPU:'):
                            with global_state.lock:
                                if global_state.stats and "vm" in global_state.stats: global_state.stats["vm"]["details"]["CPU Usage"] = line[4:]
                        elif line.startswith('MEM:'):
                            with global_state.lock:
                                if global_state.stats and "vm" in global_state.stats: global_state.stats["vm"]["details"]["Memory"] = line[4:]
            except: pass

            parsed = parse_arrakis_native()
            
            # Host SSH
            try:
                who = subprocess.run(["w", "-h"], capture_output=True, text=True, timeout=5).stdout.strip().split('\n')
                ssh_list = []
                for line in who:
                    if line.strip():
                        p = line.split()
                        if len(p) >= 3:
                            ssh_list.append({"user": p[0], "tty": p[1], "ip": (p[2] if p[2] != '-' else "localhost").strip('()'), "is_dash": 'agy' in line or 'server.py' in line or 'main.py' in line})
            except: ssh_list = []
                
            # VM SSH
            try:
                who_vm = subprocess.run(VM_CMD_PREFIX + ["w", "-h"], capture_output=True, text=True, timeout=5).stdout.strip().split('\n')
                vm_ssh_list = []
                for line in who_vm:
                    if line.strip():
                        p = line.split()
                        if len(p) >= 3:
                            vm_ssh_list.append({"user": p[0], "tty": p[1], "ip": (p[2] if p[2] != '-' else "localhost").strip('()'), "is_dash": 'agy' in line or 'server.py' in line})
            except: vm_ssh_list = []
                
            # Tailscale
            try:
                ts_raw = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=5)
                ts_data = json.loads(ts_raw.stdout)
                ts_list = []
                self_node = ts_data.get('Self', {})
                if self_node:
                    sname = self_node.get('DNSName', '').split('.')[0] or self_node.get('HostName', '')
                    ts_list.append({"ip": self_node.get('TailscaleIPs', [''])[0], "host": sname, "os": self_node.get('OS', ''), "state": "active"})
                for peer_id, peer in ts_data.get('Peer', {}).items():
                    dns = peer.get('DNSName', '')
                    if not dns: continue
                    name = dns.split('.')[0]
                    if name == 'localhost': name = peer.get('HostName', '')
                    state = 'active' if peer.get('Active') else 'idle' if peer.get('Online') else 'offline'
                    # Tailscale only fills LastSeen for peers that are offline; zero-time otherwise
                    last_seen = peer.get('LastSeen', '')
                    if last_seen.startswith('0001-'): last_seen = ''
                    ts_list.append({"ip": peer.get('TailscaleIPs', [''])[0], "host": name, "os": peer.get('OS', ''), "state": state, "last_seen": last_seen})
            except: ts_list = []
                
            parsed['connections'] = {"host_ssh": ssh_list, "vm_ssh": vm_ssh_list, "tailscale": ts_list}
            
            try:
                from app.api.system import fetch_host_daemons_data
                parsed['daemons'] = fetch_host_daemons_data()
            except: parsed['daemons'] = []
            
            try:
                from app.api.system import fetch_vm_containers_data
                parsed['containers'] = fetch_vm_containers_data()
            except: parsed['containers'] = []
            
            with global_state.lock:
                if global_state.stats and "host" in global_state.stats:
                    old_host = global_state.stats["host"].get("details", {})
                    if "CPU Usage" in old_host: parsed["host"]["details"]["CPU Usage"] = old_host["CPU Usage"]
                    if "Memory" in old_host: parsed["host"]["details"]["Memory"] = old_host["Memory"]
                if global_state.stats and "vm" in global_state.stats:
                    old_vm = global_state.stats["vm"].get("details", {})
                    if "CPU Usage" in old_vm: parsed["vm"]["details"]["CPU Usage"] = old_vm["CPU Usage"]
                    if "Memory" in old_vm: parsed["vm"]["details"]["Memory"] = old_vm["Memory"]
                global_state.stats = parsed
                
        except Exception as e: log.error(f"Services loop error: {e}")
        time.sleep(10)

def poll_background_loop():
    while True:
        try:
            # brew refreshes its index first and can take well over 5 s
            brew = subprocess.run(['/opt/homebrew/bin/brew', 'outdated', '--quiet'], capture_output=True, text=True, timeout=60)
            if brew.returncode == 0:
                with global_state.lock: global_state.bg['updates_host'] = str(len([l for l in brew.stdout.split('\n') if l.strip()]))
            apt = subprocess.run(VM_CMD_PREFIX + ["sh", "-c", "if command -v apk >/dev/null; then apk list --upgradable 2>/dev/null | grep -c .; "
                                                  "else apt list --upgradable 2>/dev/null | grep -c -v Listing; fi; true"], capture_output=True, text=True, timeout=30)
            if apt.returncode == 0:
                with global_state.lock: global_state.bg['updates_vm'] = apt.stdout.strip()
            
            try:
                cmd = VM_CMD_PREFIX + ["docker", "ps", "--format", "{{.Names}}"]
                c_names = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                formatted_errors = []
                if c_names.returncode == 0:
                    for name in c_names.stdout.strip().split('\n'):
                        if not name or name == 'watchtower': continue
                        l_cmd = VM_CMD_PREFIX + ["docker", "logs", "--tail", "200", name]
                        l_out = subprocess.run(l_cmd, capture_output=True, text=True, timeout=5)
                        for line in (l_out.stdout + "\n" + l_out.stderr).split('\n'):
                            if re.search(r'(error|fail|fatal|warn|exception|panic)', line, re.IGNORECASE):
                                clean = html.escape(re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', line).strip())
                                formatted_errors.append(f"<span style=\'color:#7dc4e4;\'>[{html.escape(name)}]</span> <span style=\'color:var(--text-secondary);\'>{clean}</span>")
                with global_state.lock:
                    global_state.bg['logs_vm'] = '<br>'.join(formatted_errors[-20:]) if formatted_errors else "<span style='color:#a6da95;'>No recent container errors found.</span>"
            except: pass
        except Exception as e: log.error(f"Background loop error: {e}")
        time.sleep(300)

from app.core.db import init_db, insert_metrics, cleanup_old_metrics, insert_service_metric, insert_disk_metric

def poll_db_loop():
    prefs_file = os.path.expanduser('~/.homelab_prefs.json')
    last_cleanup = 0
    last_disk = 0
    DISK_SAMPLE_SECONDS = 600
    while True:
        try:
            with global_state.lock:
                stats = dict(global_state.stats) if global_state.stats else None
                history_net = list(global_state.system_history['net']) if 'net' in global_state.system_history else []
                
            if stats:
                host = stats.get('host', {})
                try: h_cpu = float(str(host.get('details', {}).get('CPU Usage', '0')).replace('%', ''))
                except: h_cpu = 0.0
                try: h_mem = float(host.get('details', {}).get('Memory', '0G / 0G').split(' / ')[0].replace('G', ''))
                except: h_mem = 0.0
                try: h_net = history_net[-1] if history_net else 0.0
                except: h_net = 0.0
                insert_metrics('arrakis', h_cpu, h_mem, h_net)
                
                vm = stats.get('vm', {})
                try: v_cpu = float(str(vm.get('details', {}).get('CPU Usage', '0')).replace('%', ''))
                except: v_cpu = 0.0
                try: v_mem = float(vm.get('details', {}).get('Memory', '0G / 0G').split(' / ')[0].replace('G', ''))
                except: v_mem = 0.0
                insert_metrics('sietch', v_cpu, v_mem, 0.0)
                
                try:
                    for d in stats.get('daemons', []):
                        insert_service_metric('daemon', d['id'], float(d.get('mem_mb') or 0), float(d.get('cpu') or 0), d.get('status'))
                except: pass

                try:
                    for c in stats.get('containers', []):
                        insert_service_metric('container', c['id'], float(c.get('mem_mb') or 0), float(c.get('cpu') or 0), c.get('status'))
                except: pass

                # VM shares the host disk (see arrakis_parser), so one series covers both cards
                if time.time() - last_disk >= DISK_SAMPLE_SECONDS:
                    m = re.match(r'([0-9.]+)G / ([0-9.]+)G', host.get('details', {}).get('Disk Space', ''))
                    if m:
                        insert_disk_metric('arrakis', float(m.group(1)) * 1e9, float(m.group(2)) * 1e9)
                        last_disk = time.time()
                        
        except Exception as e: log.error(f"DB metric loop error: {e}")
        
        interval = 10
        try:
            if os.path.exists(prefs_file):
                with open(prefs_file, 'r') as f:
                    interval = int(json.load(f).get('db_poll_interval', 10))
        except: pass
        
        now = time.time()
        if now - last_cleanup > 3600:
            cleanup_old_metrics()
            last_cleanup = now
            
        time.sleep(interval)

def start_all_pollers():
    log.info("Starting background pollers...")
    init_db()
    threading.Thread(target=poll_metrics_loop, daemon=True).start()
    threading.Thread(target=poll_tmux_loop, daemon=True).start()
    threading.Thread(target=poll_services_loop, daemon=True).start()
    threading.Thread(target=poll_background_loop, daemon=True).start()
    threading.Thread(target=docker_events_loop, daemon=True).start()
    threading.Thread(target=poll_db_loop, daemon=True).start()
    from app.services.alerts import alerts_loop
    threading.Thread(target=alerts_loop, daemon=True).start()

def docker_events_loop():
    last_update = 0
    while True:
        try:
            with subprocess.Popen(VM_CMD_PREFIX + ["docker", "events", "--format", "{{json .}}"], stdout=subprocess.PIPE, text=True) as p:
                for line in p.stdout:
                    if 'exec_' in line or 'health_status' in line: continue
                    # Debounce
                    now = time.time()
                    if now - last_update < 5:
                        continue
                    last_update = now
                    time.sleep(1) # Settle
                    
                    try:
                        from app.api.system import fetch_vm_containers_data
                        new_containers = fetch_vm_containers_data()
                        with global_state.lock:
                            if global_state.stats:
                                global_state.stats['containers'] = new_containers
                    except Exception as e: log.error(f"Instant update error: {e}")
        except Exception as e: log.error(f"Docker events stream error: {e}")
        time.sleep(5)
