#!/bin/sh
# Audit Cargo's actual outputs, even when host and target share a CPU ISA.
set -eu
build=$1
target=$2
profile=$3
host_count=0
for output in "$build/target/$profile/build"/devicemapper-sys-*/output; do
	[ -f "$output" ] || continue
	host_count=$((host_count + 1))
	if grep -Eq '^cargo(::|:)rustc-link-(lib|search)=' "$output"; then
		echo "Host devicemapper-sys emitted native link metadata: $output" >&2
		exit 1
	fi
done
[ "$host_count" -gt 0 ] || { echo 'Missing host devicemapper-sys audit output' >&2; exit 1; }
target_count=0
for output in "$build/target/$target/$profile/build"/devicemapper-sys-*/output; do
	[ -f "$output" ] || continue
	target_count=$((target_count + 1))
	grep -Eq '^cargo(::|:)rustc-link-lib=devmapper$' "$output" || {
		echo "Target devicemapper linkage missing: $output" >&2
		exit 1
	}
done
[ "$target_count" -gt 0 ] || { echo 'Missing target devicemapper-sys audit output' >&2; exit 1; }
echo 'Verified host bindings without native linkage and target devmapper linkage'
