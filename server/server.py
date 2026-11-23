import socket
import sys
import time

from app.core import server_cfg

HOST, PORT = '0.0.0.0', server_cfg.port()


def port_in_use():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, PORT))
            return False
        except OSError:
            return True


if __name__ == '__main__':
    # launchd (KeepAlive) respawns us whenever we exit. If another instance
    # already owns the port, bail out *before* create_app() starts the pollers,
    # and wait so launchd doesn't spin (this previously looped ~80k times).
    if port_in_use():
        print(f"Port {PORT} already in use; another dashboard instance is running.", file=sys.stderr)
        time.sleep(60)
        sys.exit(1)

    from app.main import create_app
    app = create_app()
    # Disable reloader so background threads don't run twice
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)
