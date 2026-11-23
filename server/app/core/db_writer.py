import sqlite3, queue, threading, time
from app.core.logger import log

class DBWriter:
    def __init__(self, db_path):
        self.db_path = db_path
        self.q = queue.Queue()
        self.thread = threading.Thread(target=self._writer_loop, daemon=True)
        self.thread.start()
        
    def execute(self, sql, params=()):
        self.q.put((sql, params))
        
    def _writer_loop(self):
        conn = None
        while True:
            try:
                if not conn:
                    conn = sqlite3.connect(self.db_path, timeout=10)
                    conn.execute('PRAGMA synchronous=NORMAL')  # safe with WAL, far fewer fsyncs
                items = []
                # block for first item
                item = self.q.get(block=True)
                items.append(item)
                # drain queue
                while not self.q.empty():
                    try:
                        items.append(self.q.get_nowait())
                    except queue.Empty:
                        break
                
                c = conn.cursor()
                for sql, params in items:
                    c.execute(sql, params)
                conn.commit()
                
                for _ in items:
                    self.q.task_done()
                    
            except Exception as e:
                log.error(f"DBWriter error: {e}")
                if conn:
                    try:
                        conn.close()
                    except: pass
                    conn = None
                time.sleep(1)

