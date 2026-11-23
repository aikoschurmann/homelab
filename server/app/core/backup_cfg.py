"""What the nightly backup (~/Homelab-Backups/backup.sh) saves and where.

Kept in ~/.homelab_backup.json, which backup.sh reads with plutil:
  dest      folder the snapshots go to
  parts     which built-in parts run (jellyfin, vm_data, dashboard, server_config)
  folders   extra Mac folders, archived together as folders_<ts>.tar.gz
  copy_to   optional second folder every new snapshot is copied to (e.g. an external drive)
  hosts     [{"id", "folders": [...]}]: folders on other computers, sent by their agent (8+)
            as host_<id>_<ts>.tar.gz while backup.sh waits
  machines  [{"name", "folders": [...]}]: folders inside OrbStack machines, one archive per
            machine as machine_<name>_<ts>.tar.gz (a list, so plutil can index it)
backup.sh records how the last copy went in <dest>/.copy_status ("ok <ts>" / "failed <ts> <why>").
"""
import json
import os

CONFIG_FILE = os.path.expanduser("~/.homelab_backup.json")
DEFAULT_DEST = os.path.expanduser("~/Homelab-Backups/archive")
PARTS = {
    "jellyfin": "Jellyfin settings and library database (not the media)",
    "vm_data": "Containers in the dashboard machine: compose stacks and volumes",
    "dashboard": "The dashboard's code and databases",
    "server_config": "Shell, launchd jobs, dashboard state, Tor chat server, qBittorrent",
}
EXTRA = "folders"  # component name of the extra-folders archive
# display names; an archive backup.sh starts writing later just gets its file prefix tidied up
LABELS = {"jellyfin": "Jellyfin", "vm_data": "VM containers", "vm_apps": "VM apps", "dashboard": "Dashboard",
          "server_config": "Server config", EXTRA: "Extra folders"}


MACHINE = "machine_"  # prefix of a machine's archive: machine_<name>
HOST = "host_"        # and of another computer's: host_<id>


def label(component):
    for prefix in (MACHINE, HOST):
        if component.startswith(prefix):
            return component[len(prefix):]
    return LABELS.get(component) or component.replace("_", " ").capitalize()


def load():
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    return {"dest": cfg.get("dest") or DEFAULT_DEST,
            "parts": {k: bool((cfg.get("parts") or {}).get(k, True)) for k in PARTS},
            "folders": [x for x in cfg.get("folders") or [] if isinstance(x, str)],
            "copy_to": cfg.get("copy_to") or "",
            "machines": [{"name": m["name"], "folders": [f for f in m.get("folders") or [] if isinstance(f, str)]}
                         for m in cfg.get("machines") or [] if isinstance(m, dict) and m.get("name")],
            "hosts": [{"id": h["id"], "folders": [f for f in h.get("folders") or [] if isinstance(f, str)]}
                      for h in cfg.get("hosts") or [] if isinstance(h, dict) and h.get("id")]}


def dest():
    return load()["dest"]


def save(cfg):
    fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)


def copy_status():
    """{"ok": bool, "at": "<ts>", "why": str} of the last copy to copy_to, or None."""
    try:
        with open(os.path.join(dest(), ".copy_status")) as f:
            parts = f.read().strip().split(" ", 2)
    except OSError:
        return None
    if len(parts) < 2:
        return None
    return {"ok": parts[0] == "ok", "at": parts[1], "why": parts[2] if len(parts) > 2 else ""}
