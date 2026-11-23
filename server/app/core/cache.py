import threading
from collections import deque

class StateCache:
    def __init__(self):
        self.lock = threading.Lock()
        
        self.stats = {}
        self.tmux_sessions = []
        
        self.bg = {
            'updates_host': '-',
            'updates_vm': '-',
            'logs_host': 'Fetching...',
            'logs_vm': 'Fetching...',
            'speedtest_running': False,
            'speedtest_result': None
        }
        
        MAX_HISTORY = 30
        self.system_history = {
            'cpu': deque(maxlen=MAX_HISTORY),
            'mem': deque(maxlen=MAX_HISTORY),
            'net': deque(maxlen=MAX_HISTORY)
        }
        
        self.storage = {
            "total": 0,
            "used": 0,
            "free": 0,
        }

    def get_full_state(self):
        with self.lock:
            if not self.stats:
                return None
                
            parsed = dict(self.stats)
            parsed['history'] = {
                'cpu': list(self.system_history['cpu']),
                'mem': list(self.system_history['mem']),
                'net': list(self.system_history['net'])
            }
            parsed['bg'] = dict(self.bg)
            return parsed

global_state = StateCache()
