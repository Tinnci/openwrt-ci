#!/bin/sh
# Bounded, opt-in file I/O benchmark. Results on stdout; no raw-device writes.
set -eu
mountpoint=${1:-/mnt/mmcblk0p18}
[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }
[ "$(awk -v p="$mountpoint" '$1=="/dev/mmcblk0p18" && $2==p && $3=="ext4" {print "yes"}' /proc/mounts)" = yes ] || {
 echo 'Expected existing ext4 data partition mounted at the supplied path' >&2; exit 1;
}
command -v fio >/dev/null
available=$(df -Pk "$mountpoint" | awk 'END {print $4}')
[ "$available" -gt 1572864 ] || { echo 'Need at least 1.5 GiB free' >&2; exit 1; }
work=$(mktemp -d "$mountpoint/.ax5-bench.XXXXXX")
cleanup() { rm -f "$work/io"; rmdir "$work"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# One 512 MiB write pass, CRC verification and direct sequential/random reads.
# No time-based writes: the total write volume is bounded.
fio --name=write-verify --filename="$work/io" --size=512M --rw=write \
 --bs=1M --ioengine=sync --direct=1 --end_fsync=1 --verify=crc32c \
 --do_verify=1 --verify_fatal=1 --group_reporting=1
fio --name=seq-read --filename="$work/io" --size=512M --rw=read \
 --bs=1M --ioengine=sync --direct=1 --readonly --group_reporting=1
fio --name=rand-read --filename="$work/io" --size=512M --rw=randread \
 --bs=4k --ioengine=sync --direct=1 --readonly --runtime=15 \
 --time_based=1 --group_reporting=1
