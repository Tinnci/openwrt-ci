#!/usr/bin/env bash
set -euo pipefail
root=/work/storage-tools/thin-package
mkdir -p "$root/usr/sbin" "$root/usr/share/licenses/thin-provisioning-tools" /host/storage-tools/packages /host/storage-tools/keys
install -m755 /work/storage-tools/thin-provisioning-tools/target/aarch64-unknown-linux-musl/release/pdata_tools "$root/usr/sbin/"
for tool in thin_check thin_dump thin_restore thin_repair thin_metadata_size thin_ls thin_delta thin_rmap thin_metadata_pack thin_metadata_unpack thin_migrate thin_trim; do ln -sf pdata_tools "$root/usr/sbin/$tool"; done
cp /work/storage-tools/thin-provisioning-tools/COPYING "$root/usr/share/licenses/thin-provisioning-tools/"
install -m755 /host/storage-tools/ax5-thin-backup "$root/usr/sbin/"
cd /work/openwrt
staging_dir/host/bin/fakeroot sh -c 'chown -R 0:0 /work/storage-tools/thin-package; exec /work/openwrt/staging_dir/host/bin/apk mkpkg "$@"' sh --sign-key private-key.pem --info 'name:thin-provisioning-tools' --info 'version:1.3.4-r3' --info 'description:Thin provisioning metadata tools for AX5' --info 'arch:aarch64_cortex-a53' --info 'license:GPL-3.0-only' --info 'origin:local/ax5-storage-tools' --info 'url:https://github.com/jthornber/thin-provisioning-tools' --info 'depends:libc libgcc libudev-zero' --files "$root" --output /host/storage-tools/packages/thin-provisioning-tools-1.3.4-r3.apk
for name in lvm2-2.03.33-r3.apk lvm2-monitor-2.03.33-r4.apk libdevmapper-event-1.02.207.apk libudev-zero-1.0.4-r1.apk libevdev-1.13.4-r1.apk; do cp "bin/packages/aarch64_cortex-a53/packages/$name" /host/storage-tools/packages/; done
cp public-key.pem /host/storage-tools/keys/
for f in /host/storage-tools/packages/*.apk; do
 staging_dir/host/bin/apk adbsign --allow-untrusted --reset-signatures --sign-key private-key.pem "$f"
 staging_dir/host/bin/apk verify --keys-dir /host/storage-tools/keys "$f"
done
sha256sum /host/storage-tools/packages/*.apk > /host/storage-tools/packages/SHA256SUMS
