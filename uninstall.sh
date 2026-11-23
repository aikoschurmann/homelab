#!/bin/bash
# Stop and remove the dashboard service. Keeps the checkout and $HOMELAB_HOME (your
# settings, keys and history) unless you pass --purge.
set -euo pipefail
HOMELAB_HOME=${HOMELAB_HOME:-$HOME/.config/homelab}
if [ "$(uname)" = Darwin ]; then
    for job in com.homelab.dashboard com.homelab.backup; do
        launchctl bootout "gui/$(id -u)/$job" 2>/dev/null || true
        rm -f "$HOME/Library/LaunchAgents/$job.plist"
    done
elif command -v systemctl >/dev/null; then
    systemctl --user disable --now homelab-dashboard 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/homelab-dashboard.service"
    systemctl --user daemon-reload
fi
if [ "${1:-}" = --purge ]; then
    rm -rf "$HOMELAB_HOME"
    echo "Removed the service and $HOMELAB_HOME"
else
    echo "Removed the service. Settings and history are still in $HOMELAB_HOME (--purge deletes them)."
fi
