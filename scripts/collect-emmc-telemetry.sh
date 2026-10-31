#!/bin/sh
# Read-only AX5 eMMC report. No mounts, mode changes, benchmarks or uploads.
set -eu

# Alternate roots support offline tests; real devices use the defaults.
sysfs=${AX5_SYSFS_ROOT:-/sys}
debugfs=${AX5_DEBUGFS_ROOT:-/sys/kernel/debug}
card="$sysfs/class/mmc_host/mmc0/mmc0:0001"
host="$debugfs/mmc0"

field() {
	printf '%s=' "$1"
	if [ -r "$2" ]; then
		tr '\000\n' '  ' < "$2"
		printf '\n'
	else
		printf 'unavailable\n'
	fi
}

printf '[identity]\n'
printf 'kernel_release=%s\n' "$(uname -r)"
field model "$sysfs/firmware/devicetree/base/model"
for name in name manfid rev life_time pre_eol_info cmdq_en; do
	field "$name" "$card/$name"
done
field sectors_512_bytes "$sysfs/class/block/mmcblk0/size"
# Deliberately omit CID, serial, private credentials and raw vendor EXT_CSD data.

printf '\n[device_tree_request]\n'
if [ -d "$sysfs/firmware/devicetree/base" ]; then
	find "$sysfs/firmware/devicetree/base" -type d -name 'mmc@*' | while IFS= read -r node; do
		printf 'controller=%s\n' "${node##*/}"
		for property in bus-width max-frequency; do
			printf '%s=' "$property"
			if [ -r "$node/$property" ]; then
				od -An -tu1 "$node/$property" |
					awk '{for (i=1;i<=NF;i++) v=v*256+$i} END {printf "%.0f\n",v}'
			else
				printf 'unspecified\n'
			fi
		done
		for property in non-removable mmc-hs200-1_8v mmc-hs400-1_8v mmc-hs400-enhanced-strobe; do
			if [ -e "$node/$property" ]; then
				printf '%s=present\n' "$property"
			else
				printf '%s=absent\n' "$property"
			fi
		done
	done
else
	printf 'unavailable\n'
fi

printf '\n[host_capabilities]\n'
field caps "$host/caps"
field caps2 "$host/caps2"
printf '\n[actual_link]\n'
if [ -r "$host/ios" ]; then cat "$host/ios"; else printf 'unavailable\n'; fi
printf '\n[error_counters]\n'
if [ -r "$host/err_stats" ]; then cat "$host/err_stats"; else printf 'unavailable\n'; fi

printf '\n[ext_csd_selected_bytes]\n'
hex=
if [ -r "$host/mmc0:0001/ext_csd" ]; then
	# Some BusyBox tr builds lack character-class support.
	hex=$(tr -d ' \t\r\n' < "$host/mmc0:0001/ext_csd")
fi
valid=yes
case "$hex" in ''|*[!0-9a-fA-F]*) valid=no ;; esac
[ "${#hex}" -eq 1024 ] || valid=no
if [ "$valid" = yes ] && [ -r "$card/rev" ]; then
	revision=$(cat "$card/rev")
	case "$revision" in 0x[0-9a-fA-F]|0x[0-9a-fA-F][0-9a-fA-F]) ;; *) valid=no ;; esac
else
	valid=no
fi
if [ "$valid" = yes ]; then
	expected=$(printf '%02x' "$revision")
	# Debugfs representations differ between kernel versions. Check the order.
	forward=$(printf '%s' "$hex" | awk '{print tolower(substr($0, 385, 2))}')
	reverse=$(printf '%s' "$hex" | awk '{print tolower(substr($0, 639, 2))}')
	if [ "$forward" = "$expected" ]; then
		order=forward
	elif [ "$reverse" = "$expected" ]; then
		order=reverse
	else
		valid=no
	fi
fi
if [ "$valid" = yes ]; then
	for index in 184 192 196 267 268 269; do
		byte=$(printf '%s' "$hex" | awk -v i="$index" -v order="$order" \
			'{p = order == "forward" ? 2*i+1 : 1023-2*i; print tolower(substr($0,p,2))}')
		printf 'byte_%s=0x%s\n' "$index" "$byte"
	done
	printf 'note=capability bytes describe the chip, not verified PCB wiring\n'
else
	printf 'unavailable_or_unrecognized_format\n'
fi

printf '\n[mmc_kernel_messages]\n'
if messages=$(dmesg 2>/dev/null); then
	printf '%s\n' "$messages" |
		grep -Ei 'mmc0|mmcblk0|sdhci|HS400|HS200' |
		grep -Eiv 'cid|serial|[[:xdigit:]]{32}|[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}' || true
else
	printf 'unavailable (permissions or kernel log interface)\n'
fi

printf '\n[io_queue]\n'
for name in scheduler read_ahead_kb nr_requests; do
 field "$name" "$sysfs/class/block/mmcblk0/queue/$name"
done
printf '\n[cpu_irq_distribution]\n'
grep -E 'CPU|mmc|sdhci|nss|edma' /proc/interrupts || true
printf '\n[memory_pressure]\n'
for name in memory io cpu; do
 if [ -r "/proc/pressure/$name" ]; then
  printf '%s\n' "$name"
  cat "/proc/pressure/$name"
 fi
done
