import json
import time
from app.core.cache import global_state
from app.core.logger import log

def register_stats_websocket(sock):
    @sock.route('/api/stats_stream')
    def stats_ws(ws):
        log.info("Client connected to stats WebSocket stream")
        try:
            while True:
                # Send the latest stats
                stats = global_state.get_full_state()
                if stats:
                    ws.send(json.dumps({"status": "success", "data": stats}))
                
                # We can sleep for 1 second instead of pushing on every tiny update to avoid overwhelming the frontend
                time.sleep(1)
        except Exception as e:
            log.info(f"Stats WebSocket disconnected: {e}")
