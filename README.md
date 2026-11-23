# Homelab dashboard

A dashboard for one home server and the computers around it: its OrbStack machines and
containers, other hosts reporting in through a small agent, Tailscale, Cloudflare Tunnels,
backups, databases and a browser terminal.

The server it runs on is named on first visit (it defaults to the computer's hostname).

## Install

```sh
git clone <this repo> ~/homelab && cd ~/homelab
./install.sh            # venv, web build, and a launchd (macOS) / systemd --user (Linux) service
```

Then open `http://localhost:5050`. The first visit shows the setup screen, where you name the
server, pick its port and, with OrbStack, choose its main machine.

You need Python 3.10+ and Node 20+. Optional tools light up their pages when they're installed:
OrbStack, Tailscale, cloudflared, Docker, tmux.

| | |
|---|---|
| Update | `git pull && ./install.sh` |
| Run by hand | `./install.sh --no-service && ./run.sh` |
| Remove | `./uninstall.sh` (keeps your settings; `--purge` deletes them) |
| Logs | `~/.config/homelab/logs/dashboard.{out,err}` |

Access is limited to this computer and your own Tailscale devices. Nothing listens for the
open internet unless you share something through a Cloudflare Tunnel.

## Layout

```
server/     Flask API + pollers (app/api, app/core, app/services); serves server/static
web/        Svelte 5 app; `npm run build` writes to server/static
scripts/    backup.sh (the nightly backup the Backups page schedules)
```

Development: run `./run.sh` and `cd web && npx vite build --watch` (or `npm run dev`).

## State

Nothing the server writes goes into the checkout. It all lives in `$HOMELAB_HOME`, which
defaults to `~/.config/homelab`:

```
server.json        name, port, setup done
*.json             prefs, hosts, storage, backup config, terminal presets, shares
secrets/           Cloudflare token, Tailscale auth key (0600, never sent to the browser)
data/metrics.db    history (other .db files here show up on the Databases page)
logs/              dashboard and backup logs
```

Older installs that kept `~/.homelab_*.json` and `~/.databases/metrics.db` are picked up on
first start. The files are copied, and the originals are left alone.

Set `HOMELAB_HOME` to run a second, separate instance:

```sh
HOMELAB_HOME=/tmp/test HOMELAB_PORT=5099 ./run.sh
```
