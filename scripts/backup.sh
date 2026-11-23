#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
# What to back up and where: ~/.homelab_backup.json, edited from the dashboard (Backups → Settings)
CFG="$HOME/.homelab_backup.json"
cfg() { [ -f "$CFG" ] && plutil -extract "$1" raw -o - "$CFG" 2>/dev/null; }
part_on() { [ "$(cfg "parts.$1")" != false ]; }
BACKUP_DIR=$(cfg dest); BACKUP_DIR=${BACKUP_DIR:-$HOME/Homelab-Backups/archive}
COPY_TO=$(cfg copy_to)
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
# archives hold secrets (Tor onion keys, pihole .env, Tailscale auth key)
umask 077
mkdir -p "$BACKUP_DIR"

# The dashboard VM; renaming it from the dashboard rewrites ~/.homelab_vm.json
VM=${HOMELAB_VM_NAME:-$(sed -n 's/.*"vm_name" *: *"\([^"]*\)".*/\1/p' ~/.homelab_vm.json 2>/dev/null)}
VM=${VM:-sietch}

# --- Lock file: prevent multiple instances running at once ---
LOCKFILE="/tmp/homelab_backup.lock"
if [ -e "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null)
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "Backup already running (PID $LOCK_PID), exiting."
        exit 0
    fi
fi
echo $$ > "$LOCKFILE"
PAUSED=""
cleanup() {
    # never leave a container paused if the script dies mid-backup
    [ -n "$PAUSED" ] && orb -m "$VM" -u root docker unpause $PAUSED >/dev/null 2>&1
    rm -f "$LOCKFILE"
}
trap cleanup EXIT

FAILED=0
# A failed component is left as an empty file, which the Backups page shows as "Incomplete".
fail() {
    echo "ERROR: $1 backup failed"
    : > "$2"
    FAILED=1
}

echo "Starting Homelab Backup ($TIMESTAMP)..."

# 1. Backup Jellyfin (macOS) — exclude cache (transcodes, etc.)
if part_on jellyfin; then
echo "Backing up Jellyfin (macOS)..."
OUT="$BACKUP_DIR/jellyfin_$TIMESTAMP.tar.gz"
tar -czf "$OUT" \
    --exclude="Jellyfin/cache" \
    -C "/Users/muadhib/Library/Application Support" Jellyfin || fail Jellyfin "$OUT"

# Also clear the transcode cache to prevent runaway growth
echo "Clearing Jellyfin transcode cache..."
rm -rf "/Users/muadhib/Library/Application Support/Jellyfin/cache/transcodes"/*
fi

# 2. Backup the dashboard VM's containers: compose stacks + Docker volumes
#    (Tor onion keys, Conduit DB, pihole config, Portainer). Streamed to the Mac.
#    Pi-hole's query log and downloaded blocklists are left out (large, rebuilt on their own).
if part_on vm_data; then
echo "Backing up containers in $VM (VM)..."
OUT="$BACKUP_DIR/vm_data_$TIMESTAMP.tar.gz"
if orb -m "$VM" true 2>/dev/null; then
    # pause Conduit so its database is copied in a consistent state (a few seconds)
    if orb -m "$VM" -u root docker pause conduit >/dev/null 2>&1; then PAUSED=conduit; fi
    orb -m "$VM" -u root sh -c 'cd / && tar -czf - \
        --exclude="var/lib/docker/volumes/pihole_etc/_data/pihole-FTL.db*" \
        --exclude="var/lib/docker/volumes/pihole_etc/_data/listsCache" \
        --exclude="var/lib/docker/volumes/pihole_etc/_data/gravity_old.db" \
        --exclude="var/lib/docker/volumes/pihole_etc/_data/gravity_backups" \
        opt/stacks var/lib/docker/volumes' > "$OUT" || fail "VM containers" "$OUT"
    if [ -n "$PAUSED" ]; then orb -m "$VM" -u root docker unpause $PAUSED >/dev/null; PAUSED=""; fi
else
    echo "WARNING: machine $VM is not reachable."
    fail "VM containers" "$OUT"
fi
fi

# 2b. Folders inside other machines, chosen per machine in the dashboard:
#     machines.<i>.name / machines.<i>.folders.<j>; one archive each, machine_<name>_<ts>.tar.gz
M=$(cfg machines); M=${M:-0}
i=0; while [ "$i" -lt "$M" ] 2>/dev/null; do
    NAME=$(cfg "machines.$i.name"); NF=$(cfg "machines.$i.folders"); NF=${NF:-0}
    i=$((i + 1))
    [ -n "$NAME" ] || continue
    OUT="$BACKUP_DIR/machine_${NAME}_$TIMESTAMP.tar.gz"
    LIST=(); j=0; while [ "$j" -lt "$NF" ]; do d=$(cfg "machines.$((i - 1)).folders.$j"); LIST+=("${d#/}"); j=$((j + 1)); done
    echo "Backing up folders in $NAME (machine)..."
    if ! orb -m "$NAME" true 2>/dev/null; then
        echo "WARNING: machine $NAME is not running."
        fail "$NAME" "$OUT"; continue
    fi
    # only the folders that exist; none left fails the part instead of writing an empty archive
    orb -m "$NAME" -u root sh -c 'cd / && n=$#; for d; do [ -e "$d" ] && set -- "$@" "$d"; done; shift $n; [ $# -gt 0 ] && exec tar -czf - "$@"' \
        sh "${LIST[@]}" > "$OUT" || fail "$NAME" "$OUT"
done

# 2c. Folders on other computers: the dashboard asks each one's agent to pack and upload
#     them into this snapshot as host_<id>_<ts>.tar.gz, and answers once all are in.
if [ "$(cfg hosts)" -gt 0 ] 2>/dev/null; then
    echo "Collecting folders from other computers..."
    if ! curl -fsS -m 11000 -X POST "http://127.0.0.1:5050/api/backups/hosts/run?ts=$TIMESTAMP"; then
        echo "ERROR: other computers backup failed: the dashboard didn't answer"; FAILED=1
    fi
fi

# 3. Backup Dashboard (macOS) — exclude venv and __pycache__
if part_on dashboard; then
echo "Backing up Dashboard (macOS)..."
OUT="$BACKUP_DIR/dashboard_$TIMESTAMP.tar.gz"
tar -czf "$OUT" \
    --exclude="Homelab-Dashboard/venv" \
    --exclude="Homelab-Dashboard/__pycache__" \
    -C "/Users/muadhib" Homelab-Dashboard || fail Dashboard "$OUT"
fi

# 4. Backup Server Configurations (macOS): shell, launchd jobs, dashboard state
#    (hosts, prefs, storage, VM name, Tailscale key), torchatserver compose, qBittorrent
if part_on server_config; then
echo "Backing up Server Configurations..."
OUT="$BACKUP_DIR/server_config_$TIMESTAMP.tar.gz"
cd /Users/muadhib && tar -czf "$OUT" \
    .zshrc Library/LaunchAgents Homelab-Backups/backup.sh \
    $(ls -d .homelab_*.json 2>/dev/null) \
    torchatserver .config/qBittorrent \
    "Library/Application Support/qBittorrent/BT_backup" || fail "Server config" "$OUT"
fi

# 4b. Extra folders chosen in the dashboard, together in one archive (absolute paths kept)
N=$(cfg folders); N=${N:-0}
if [ "$N" -gt 0 ] 2>/dev/null; then
    echo "Backing up $N extra folder(s)..."
    OUT="$BACKUP_DIR/folders_$TIMESTAMP.tar.gz"
    LIST=()
    i=0; while [ $i -lt "$N" ]; do d=$(cfg "folders.$i"); [ -d "$d" ] && LIST+=("${d#/}"); i=$((i + 1)); done
    if [ ${#LIST[@]} -gt 0 ]; then tar -czf "$OUT" -C / "${LIST[@]}" || fail "Extra folders" "$OUT"
    else fail "Extra folders (none exist)" "$OUT"; fi
fi

# 5. Cleanup old backups (keep last N complete sets)
RETENTION=${1:-3}
echo "Cleaning up old backups (keeping last $RETENTION)..."
# whole snapshots: every file whose timestamp is older than the Nth newest snapshot
ls -1 "$BACKUP_DIR" | sed -n 's/.*_\([0-9-]*_[0-9-]*\)\.tar\.gz$/\1/p' | sort -ru | tail -n +$((RETENTION + 1)) |
    while read -r ts; do rm -f "$BACKUP_DIR"/*_"$ts".tar.gz; done

# 6. Second copy (e.g. an external drive): this snapshot's files, then the same retention there.
#    Done by the Mac itself; OrbStack never touches that folder.
if [ -n "$COPY_TO" ]; then
    # only the folder itself is created: a missing drive must fail, not fill the boot disk
    if [ -d "$COPY_TO" ] || { [ -d "$(dirname "$COPY_TO")" ] && mkdir "$COPY_TO" 2>/dev/null; }; then
        echo "Copying to $COPY_TO..."
        if cp "$BACKUP_DIR"/*_"$TIMESTAMP".tar.gz "$COPY_TO"/; then
            ls -1 "$COPY_TO" | sed -n 's/.*_\([0-9-]*_[0-9-]*\)\.tar\.gz$/\1/p' | sort -ru | tail -n +$((RETENTION + 1)) |
                while read -r ts; do rm -f "$COPY_TO"/*_"$ts".tar.gz; done
            echo "ok $TIMESTAMP" > "$BACKUP_DIR/.copy_status"
        else
            echo "failed $TIMESTAMP copying failed" > "$BACKUP_DIR/.copy_status"; FAILED=1
        fi
    else
        echo "failed $TIMESTAMP $COPY_TO isn't available (drive not connected?)" > "$BACKUP_DIR/.copy_status"; FAILED=1
    fi
fi

echo "Backup complete! Archive size: $(du -sh "$BACKUP_DIR" | cut -f1)"
exit $FAILED
