#!/bin/sh
# Refuse in-place firmware upgrades over an old external upper filesystem.
ax5_extroot_upgrade_check() {
 [ "$(cat /tmp/sysinfo/board_name)" = redmi,ax5-jdcloud ] || return 0
 [ -f /etc/config/ax5_extroot ] || return 0
 if ! awk '$2=="/overlay" && $3=="f2fs" {ok=1} END {exit !ok}' /proc/mounts ||
    [ "$(uci -q get ax5_extroot.boot.enabled)" != 0 ] ||
    [ "$(uci -q get fstab.@mount[0].enabled)" != 0 ]; then
  echo 'AX5 extroot: run ax5-extroot-select internal and reboot before sysupgrade.' >&2
  echo 'After upgrading, rebuild the LVM upper from the new internal system before re-enabling it.' >&2
  return 1
 fi
 return 0
}
