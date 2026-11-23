#!/bin/sh
# homelab-policy: enforces the dashboard's per-person permissions on a shared machine.
# Installed by the dashboard as /usr/local/sbin/homelab-policy, runs as root.
#
# Each managed login user has /etc/homelab-share/users/<user>.conf (written by the
# dashboard, shell variables, all optional):
#   ACCESS=shell|sftp        sftp = file transfer only, no shell
#   ROOT=none|some|full      some = only the command groups in SUDO
#   SUDO="packages services power"
#   DOCKER=0|1               docker group (root-equivalent)
#   NET=full|internet|none   internet = no LAN / tailnet / host / other machines
#   FORWARD=0|1              SSH port forwarding
#   PROCS=0|1                may see other users' processes
#   CPU=<cores, may be fractional, 0 = no cap>  MEM=<MiB, 0 = no cap>  PIDS=<0 = no cap>
#   EXPIRES=YYYY-MM-DD       no new logins after this day; running sessions are ended
#
#   homelab-policy apply     make the machine match the confs (boot + after every change)
#   homelab-policy expire    end sessions of users past EXPIRES (hourly from cron)
#   homelab-policy enter PID (via sudo, from the login wrapper) put PID in the caller's cgroup
#   homelab-policy usage     per-user CPU seconds / memory bytes / tasks, for the dashboard
set -u
D=/etc/homelab-share/users
CG=/sys/fs/cgroup
SSHC=/etc/ssh/sshd_config
WRAP=/usr/local/libexec/homelab-session
MARK="homelab-share"
PRIVATE4="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16 0.0.0.0/8 224.0.0.0/4"
PRIVATE6="fc00::/7 fe80::/10"

managed() { getent passwd "$1" | cut -d: -f5 | grep -q "^$MARK"; }
users() { for f in "$D"/*.conf; do [ -f "$f" ] && basename "$f" .conf; done; }
load() {  # reset to the most restrictive defaults, then read the user's conf
  ACCESS=shell ROOT=none SUDO="" DOCKER=0 NET=internet FORWARD=0 PROCS=0 CPU=0 MEM=0 PIDS=0 EXPIRES=""
  . "$D/$1.conf"
}
bin() { for b in "$@"; do p=$(command -v "$b" 2>/dev/null) && [ -n "$p" ] && printf '%s, ' "$p"; done; }
sudo_cmds() {  # absolute paths for the chosen command groups, as one sudoers list
  out=""
  for g in $SUDO; do case $g in
    packages) out="$out$(bin apk apt apt-get dpkg dnf yum pacman zypper)";;
    services) out="$out$(bin rc-service rc-update rc-status systemctl journalctl)";;
    power)    out="$out$(bin reboot poweroff halt shutdown)";;
  esac; done
  printf '%s' "${out%, }"
}
setgroup() {  # setgroup <user> <group> <0|1>: exact membership of one supplementary group
  if [ "$3" = 1 ]; then
    getent group "$2" >/dev/null || addgroup -S "$2" 2>/dev/null || groupadd -r "$2" 2>/dev/null || true
    id -nG "$1" | tr ' ' '\n' | grep -qx "$2" || adduser "$1" "$2" 2>/dev/null || usermod -aG "$2" "$1" 2>/dev/null || true
  elif id -nG "$1" | tr ' ' '\n' | grep -qx "$2"; then
    delgroup "$1" "$2" 2>/dev/null || gpasswd -d "$1" "$2" >/dev/null 2>&1 || true
  fi
}
need() {  # install a package if its command is missing
  command -v "$1" >/dev/null 2>&1 && return
  if command -v apk >/dev/null; then apk add --no-cache -q "$2" >/dev/null 2>&1
  elif command -v apt-get >/dev/null; then DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$2" >/dev/null 2>&1
  elif command -v dnf >/dev/null; then dnf install -y -q "$2" >/dev/null 2>&1
  elif command -v pacman >/dev/null; then pacman -S --noconfirm "$2" >/dev/null 2>&1; fi
}

# ---- machine-wide -------------------------------------------------------------------
base() {
  mkdir -p "$D"; chmod 700 /etc/homelab-share "$D"
  getent group procview >/dev/null || addgroup -S procview 2>/dev/null || groupadd -r procview
  gid=$(getent group procview | cut -d: -f3)
  # every regular user's home is private (the machine owner's included)
  for h in /home/*; do [ -d "$h" ] && chmod 700 "$h"; done
  # logs carry everyone's logins
  for l in /var/log/messages /var/log/auth.log /var/log/secure /var/log/homelab-share.log; do [ -f "$l" ] && chmod 600 "$l"; done
  # users only see their own processes, unless in procview. OrbStack also mounts a second
  # proc under /dev/.lxc, which would show everything, so both get the option.
  for p in /proc /dev/.lxc/proc; do
    grep -q " $p proc " /proc/mounts && mount -o remount,hidepid=invisible,gid="$gid" "$p" 2>/dev/null
  done
  # the machine's own users (not ours) keep the full view
  for u in $(awk -F: '$3>=1000 && $3<60000 {print $1}' /etc/passwd); do managed "$u" || setgroup "$u" procview 1; done
  cgroups_base
  need sudo sudo
  printf '%s\n' "# $MARK: lets every login enter its own cgroup" "ALL ALL=(root) NOPASSWD: /usr/local/sbin/homelab-policy enter *" > /etc/sudoers.d/89-homelab-enter
  chmod 440 /etc/sudoers.d/89-homelab-enter
}

cgroups_base() {
  [ -f $CG/cgroup.controllers ] || return 0
  if ! grep -qw memory $CG/cgroup.subtree_control; then
    # controllers can only be handed down from a cgroup with no processes in it
    mkdir -p $CG/init
    for p in $(cat $CG/cgroup.procs); do echo "$p" > $CG/init/cgroup.procs 2>/dev/null; done
    echo "+cpu +memory +pids" > $CG/cgroup.subtree_control 2>/dev/null
  fi
  mkdir -p $CG/share
  echo "+cpu +memory +pids" > $CG/share/cgroup.subtree_control 2>/dev/null
  return 0
}

# ---- per user -----------------------------------------------------------------------
apply_user() {
  u=$1; managed "$u" || { echo "skipping $u: not dashboard-managed" >&2; return; }
  load "$u"
  # login shell: none at all for file-transfer-only users
  sh=/bin/sh; [ -x /bin/bash ] && sh=/bin/bash
  [ "$ACCESS" = sftp ] && sh=/sbin/nologin
  [ -x "$sh" ] || sh=/bin/false
  if command -v usermod >/dev/null; then usermod -s "$sh" "$u"; else sed -i "s#^\($u:[^:]*:[^:]*:[^:]*:[^:]*:[^:]*:\).*#\1$sh#" /etc/passwd; fi
  # sudo
  sf=/etc/sudoers.d/90-share-$u; rule=""
  case $ROOT in
    full) rule="$u ALL=(ALL) NOPASSWD: ALL";;
    some) c=$(sudo_cmds); [ -n "$c" ] && rule="$u ALL=(root) NOPASSWD: $c";;
  esac
  if [ -n "$rule" ]; then
    t=$(mktemp); printf '# %s: %s %s\n%s\n' "$MARK" "$ROOT" "$SUDO" "$rule" > "$t"
    if visudo -cf "$t" >/dev/null 2>&1; then install -m 440 -o root -g root "$t" "$sf"; else echo "sudoers for $u failed validation" >&2; rm -f "$sf"; fi
    rm -f "$t"
  else rm -f "$sf"; fi
  # groups: exactly these, and never wheel (sudo comes from the file above)
  setgroup "$u" wheel 0
  setgroup "$u" docker "$DOCKER"
  setgroup "$u" procview "$PROCS"
  # account expiry (shadow field 8, days since 1970); sshd refuses expired accounts
  days=""; [ -n "$EXPIRES" ] && days=$(( $(date -d "$EXPIRES" +%s 2>/dev/null || date -D %Y-%m-%d -d "$EXPIRES" +%s) / 86400 + 1 ))
  awk -F: -v OFS=: -v u="$u" -v d="$days" '$1==u{$8=d}1' /etc/shadow > /etc/shadow.hs && cat /etc/shadow.hs > /etc/shadow; rm -f /etc/shadow.hs
  # resource caps
  if [ -d $CG/share ]; then
    c=$CG/share/$u; mkdir -p "$c"
    if [ "$CPU" != 0 ]; then echo "$(awk -v c="$CPU" 'BEGIN{printf "%d", c*100000}') 100000" > "$c/cpu.max"; else echo "max 100000" > "$c/cpu.max"; fi
    if [ "$MEM" != 0 ]; then echo $((MEM * 1048576)) > "$c/memory.max"; [ -f "$c/memory.swap.max" ] && echo 0 > "$c/memory.swap.max"
    else echo max > "$c/memory.max"; [ -f "$c/memory.swap.max" ] && echo max > "$c/memory.swap.max"; fi
    if [ "$PIDS" != 0 ]; then echo "$PIDS" > "$c/pids.max"; else echo max > "$c/pids.max"; fi
  fi
}

sshd_block() {  # one Match block per user, kept at the very end of sshd_config
  t=$(mktemp)
  sed '/^# >>> homelab-share users/,/^# <<< homelab-share users/d' "$SSHC" > "$t"
  {
    echo "# >>> homelab-share users (generated by homelab-policy; edits are overwritten)"
    for u in $(users); do
      managed "$u" || continue; load "$u"
      fw=no; [ "$FORWARD" = 1 ] && fw=yes
      echo "Match User $u"
      if [ "$ACCESS" = sftp ]; then echo "    ForceCommand internal-sftp"; echo "    PermitTTY no"
      else echo "    ForceCommand $WRAP"; fi
      echo "    AllowTcpForwarding $fw"; echo "    AllowStreamLocalForwarding no"; echo "    AllowAgentForwarding no"
      echo "    X11Forwarding no"; echo "    PermitTunnel no"; echo "    PermitUserRC no"
    done
    echo "# <<< homelab-share users"
  } >> "$t"
  if cmp -s "$t" "$SSHC"; then rm -f "$t"; return; fi
  sshd=$(command -v sshd || echo /usr/sbin/sshd)
  if "$sshd" -t -f "$t" 2>/dev/null; then cat "$t" > "$SSHC"; rm -f "$t"
    if command -v rc-service >/dev/null; then rc-service sshd reload >/dev/null 2>&1 || rc-service sshd restart >/dev/null 2>&1
    elif command -v systemctl >/dev/null; then systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null; fi
  else echo "generated sshd_config failed validation; left unchanged" >&2; rm -f "$t"; return 1; fi
}

firewall() {  # per-user egress chains, rebuilt from scratch every time
  need iptables iptables
  dns=$(awk '/^nameserver/ {print $2}' /etc/resolv.conf)
  for fam in 4 6; do
    if [ $fam = 4 ]; then ipt=iptables; priv=$PRIVATE4; else ipt=ip6tables; priv=$PRIVATE6; fi
    command -v $ipt >/dev/null || continue
    $ipt -w -S OUTPUT 2>/dev/null | grep -- '-j hs-' | sed 's/^-A/-D/' | while read -r r; do eval "$ipt -w $r"; done
    $ipt -w -S 2>/dev/null | awk '/^-N hs-/ {print $2}' | while read -r c; do $ipt -w -F "$c"; $ipt -w -X "$c"; done
    for u in $(users); do
      managed "$u" || continue; load "$u"
      [ "$NET" = full ] && continue
      uid=$(id -u "$u"); c="hs-$uid"
      $ipt -w -N "$c"; $ipt -w -I OUTPUT 1 -m owner --uid-owner "$uid" -j "$c"
      $ipt -w -A "$c" -o lo -j ACCEPT
      if [ "$NET" = internet ]; then
        for n in $dns; do case $n in *:*) [ $fam = 6 ] || continue;; *) [ $fam = 4 ] || continue;; esac
          $ipt -w -A "$c" -d "$n" -p udp --dport 53 -j ACCEPT; $ipt -w -A "$c" -d "$n" -p tcp --dport 53 -j ACCEPT; done
        for n in $priv; do $ipt -w -A "$c" -d "$n" -j REJECT; done
        $ipt -w -A "$c" -j ACCEPT
      else
        $ipt -w -A "$c" -j REJECT
      fi
    done
  done
}

cleanup() {  # sudoers files and cgroups of users that no longer have a conf
  for f in /etc/sudoers.d/90-share-*; do [ -f "$f" ] || continue; u=${f#/etc/sudoers.d/90-share-}; [ -f "$D/$u.conf" ] || rm -f "$f"; done
  [ -d $CG/share ] || return 0
  for c in $CG/share/*/; do [ -d "$c" ] || continue; u=$(basename "$c"); [ -f "$D/$u.conf" ] || rmdir "$c" 2>/dev/null; done
  return 0
}

expire() {
  today=$(( $(date +%s) / 86400 ))
  for u in $(users); do load "$u"; [ -n "$EXPIRES" ] || continue
    days=$(( $(date -d "$EXPIRES" +%s 2>/dev/null || date -D %Y-%m-%d -d "$EXPIRES" +%s) / 86400 + 1 ))
    [ "$today" -ge "$days" ] && pkill -KILL -u "$u" 2>/dev/null
  done
  return 0
}

case "${1:-}" in
  apply)
    base
    for u in $(users); do apply_user "$u"; done
    cleanup; firewall; sshd_block; expire
    ;;
  expire) expire ;;
  enter)
    # Called through sudo by the login wrapper. Only ever moves one of the CALLER's own
    # processes into the caller's own (capped) cgroup, so it can't be used to escape one.
    u=${SUDO_USER:-}; p=${2:-}
    [ -n "$u" ] && [ -f "$D/$u.conf" ] || exit 0
    case $p in ''|*[!0-9]*) exit 1;; esac
    [ "$(stat -c %u /proc/"$p" 2>/dev/null)" = "${SUDO_UID:-x}" ] || exit 1
    [ -d $CG/share ] || exit 0
    mkdir -p "$CG/share/$u"
    echo "$p" > "$CG/share/$u/cgroup.procs"
    ;;
  usage)
    for u in $(users); do c=$CG/share/$u
      cpu=$(awk '/^usage_usec/ {print $2}' "$c/cpu.stat" 2>/dev/null); mem=$(cat "$c/memory.current" 2>/dev/null); n=$(cat "$c/pids.current" 2>/dev/null)
      echo "$u ${cpu:-0} ${mem:-0} ${n:-0}"
    done ;;
  *) echo "usage: homelab-policy apply|expire|enter PID|usage" >&2; exit 2 ;;
esac
