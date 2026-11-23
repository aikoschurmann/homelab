#!/bin/sh
# homelab-session: sshd ForceCommand for dashboard-managed users. Moves the session into
# the user's own capped cgroup first (fails closed), then runs what was asked for.
sudo -n /usr/local/sbin/homelab-policy enter $$ || { echo "session setup failed; ask the machine's owner" >&2; exit 1; }
sh=$(getent passwd "$(id -un)" | cut -d: -f7)
case "${SSH_ORIGINAL_COMMAND:-}" in
  "") exec "$sh" -l ;;
  internal-sftp|*/sftp-server)
    for s in /usr/lib/ssh/sftp-server /usr/lib/openssh/sftp-server /usr/libexec/openssh/sftp-server /usr/libexec/sftp-server; do [ -x "$s" ] && exec "$s"; done
    echo "no sftp-server on this machine" >&2; exit 1 ;;
  *) exec "$sh" -c "$SSH_ORIGINAL_COMMAND" ;;
esac
