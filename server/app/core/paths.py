"""Where the dashboard keeps its state, and where the code lives.

Everything this server writes sits under one folder, HOMELAB_HOME (default
~/.config/homelab), so an install can be moved, backed up or wiped as a unit:

  server.json         this server's identity (name, port, setup done) - see server_cfg
  *.json              prefs, hosts, storage, backup config, terminal presets, ...
  secrets/*.json      Cloudflare token, Tailscale auth key (0600, never sent to the browser)
  data/               metrics.db and any other SQLite files shown on the Databases page
  cache/              throwaway (database snapshots)
  logs/               dashboard.out/.err, backup.out/.err

Older installs kept these as ~/.homelab_<name>.json and ~/.databases/metrics.db; the first
call to state()/secret() for a file copies the old one in (the original is left in place).
"""
import os
import shutil
import sqlite3

HOME = os.path.abspath(os.path.expanduser(os.environ.get("HOMELAB_HOME") or "~/.config/homelab"))
DATA = os.path.join(HOME, "data")
CACHE = os.path.join(HOME, "cache")
SECRETS = os.path.join(HOME, "secrets")
LOGS = os.path.join(HOME, "logs")

# the repo checkout: server/app/core/paths.py -> <repo>
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRIPTS = os.path.join(REPO, "scripts")

for _d, _mode in ((HOME, 0o700), (DATA, 0o700), (CACHE, 0o700), (SECRETS, 0o700), (LOGS, 0o700)):
    os.makedirs(_d, mode=_mode, exist_ok=True)

LEGACY_HOME = os.path.expanduser("~")


def _adopt(new, legacy):
    if not os.path.exists(new) and os.path.exists(legacy):
        shutil.copy2(legacy, new)
    return new


def state(name):
    """Path of a JSON state file, e.g. state('prefs') -> $HOMELAB_HOME/prefs.json."""
    return _adopt(os.path.join(HOME, f"{name}.json"), os.path.join(LEGACY_HOME, f".homelab_{name}.json"))


def secret(name):
    """Like state(), but in secrets/ and kept 0600."""
    path = _adopt(os.path.join(SECRETS, f"{name}.json"), os.path.join(LEGACY_HOME, f".homelab_{name}.json"))
    if os.path.exists(path):
        os.chmod(path, 0o600)
    return path


def metrics_db():
    """The dashboard's own SQLite database. An old ~/.databases/metrics.db is copied in once
    with SQLite's backup API, so a live WAL is carried over consistently."""
    path = os.path.join(DATA, "metrics.db")
    legacy = os.path.join(LEGACY_HOME, ".databases", "metrics.db")
    if not os.path.exists(path) and os.path.exists(legacy):
        src = sqlite3.connect(f"file:{legacy}?mode=ro", uri=True)
        dst = sqlite3.connect(path + ".part")
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        os.replace(path + ".part", path)
    return path
