import os
import pty
import json
import struct
import fcntl
import termios
import threading
import subprocess
import codecs
import select

from app.core.logger import log

def register_websocket(sock):
    @sock.route('/api/term')
    def terminal_ws(ws):
        from flask import request
        import re
        session_name = request.args.get('session', 'main')
        if not re.fullmatch(r'(?:[a-z0-9][a-z0-9-]{0,62}:)?[a-zA-Z0-9][a-zA-Z0-9_.-]*', session_name):
            ws.send("\r\n\x1b[31m[Invalid session name]\x1b[0m\r\n")
            return

        from app.core.tmux_target import split, tmux_cmd, new_session_args
        where, real_session = split(session_name)
        if where and not session_name.startswith(('dexec:', 'dlogs:')):
            # tmux on the Mac or inside any OrbStack machine; created if it isn't running
            subprocess.run(tmux_cmd(where) + ["-u"] + new_session_args(where, real_session), capture_output=True)
            # one tmux call (it may go over SSH): mouse mode if asked, and a quiet status bar that fits
            # the dashboard. Both are set on this session only; the global config is left alone.
            t = f"={real_session}:"
            opts = [("status-style", "bg=default,fg=colour244"), ("window-status-current-style", "fg=colour223,bold"),
                    ("status-left", ""), ("status-right", "#[fg=colour240]#h  %H:%M ")]
            if request.args.get('mouse') == '1':
                opts.append(("mouse", "on"))
            args = []
            for opt, val in opts:
                args += ([";"] if args else []) + ["set-option", "-t", t, opt, val]
            subprocess.run(tmux_cmd(where) + args, capture_output=True)
            # no -d: the dashboard page and a popped-out window can be attached at once
            cmd = tmux_cmd(where, tty=True) + ["-u", "attach-session", "-t", f"={real_session}"]
        elif session_name.startswith('dexec:'):
            from app.core.config import VM_CMD_PREFIX
            real_session = None
            container = session_name[6:]
            cmd = VM_CMD_PREFIX + ["docker", "exec", "-it", "--", container, "/bin/sh"]
        elif session_name.startswith('dlogs:'):
            from app.core.config import VM_CMD_PREFIX
            real_session = None
            container = session_name[6:]
            cmd = VM_CMD_PREFIX + ["docker", "logs", "-f", "--tail", "100", "--", container]
        else:
            real_session = session_name
            tmux_base = ["tmux", "-u"]
            subprocess.run(tmux_base + ["new-session", "-d", "-s", real_session], capture_output=True)
            cmd = tmux_base + ["attach-session", "-d", "-t", real_session]
        master, slave = pty.openpty()
        fcntl.fcntl(master, fcntl.F_SETFL, os.O_NONBLOCK)

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["LANG"] = "en_US.UTF-8"

        def preexec():
            os.setsid()

        try:
            p = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave,
                                 close_fds=True, env=env, preexec_fn=preexec)
        except Exception as e:
            log.error(f"Process Start Error: {e}")
            ws.send(f"\r\n\x1b[31m[Process Start Error: {str(e)}]\x1b[0m\r\n")
            os.close(master)
            os.close(slave)
            return
            
        os.close(slave)
        ws_closed = False

        def ws_to_pty():
            nonlocal ws_closed
            try:
                while True:
                    data = ws.receive()
                    if not data:
                        break
                    try:
                        msg = json.loads(data)
                        if msg.get('type') == 'input':
                            os.write(master, msg['data'].encode('utf-8'))
                        elif msg.get('type') == 'resize':
                            winsize = struct.pack("HHHH", msg.get('rows', 24), msg.get('cols', 80), 0, 0)
                            fcntl.ioctl(master, termios.TIOCSWINSZ, winsize)
                    except Exception:
                        os.write(master, data.encode() if isinstance(data, str) else data)
            except Exception:
                pass
            finally:
                ws_closed = True

        t = threading.Thread(target=ws_to_pty, daemon=True)
        t.start()

        decoder = codecs.getincrementaldecoder('utf-8')('replace')

        try:
            while not ws_closed:
                r, _, _ = select.select([master], [], [], 0.1)
                if master in r:
                    try:
                        out = os.read(master, 1024)
                        if not out: break  
                        text = decoder.decode(out, final=False)
                        if text:
                            ws.send(text)
                    except OSError:
                        break
                elif p.poll() is not None:
                    try:
                        while True:
                            out = os.read(master, 1024)
                            if not out: break
                            text = decoder.decode(out, final=True)
                            if text: ws.send(text)
                    except OSError:
                        pass
                    break
        except Exception as e:
            log.error(f"Terminal loop error: {e}")
        finally:
            try:
                os.close(master)
            except Exception: pass
            try:
                p.wait(timeout=1)
            except Exception:
                p.kill()
