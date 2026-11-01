# AX5 thin-pool tooling

Optional userspace add-on for the validated AX5 JDCloud firmware. This directory is not automatically applied by the base firmware workflow. It does not convert p18, change GPT, or activate arbitrary volume groups.

Validated on the lab board: LVM2 2.03.33, thin-provisioning-tools 1.3.4, Linux 6.12.108, 4-bit HS200. The thin tool source is pinned to upstream commit `b4db8332a7586985149b9545bb2592d4b274c99e`, Cargo.lock SHA256 `41798bf4e197b66e34be79af4829285c085b6b69279f0f536aea0cd86337b03c`. Rust 1.99.1 compiled the ARM64/musl tools using the matching OpenWrt GCC 14.3 toolchain.

## Files and build

- `lvm2-monitoring.patch`: apply with `patch -p1` in the locked packages feed. Enables dmeventd/cmdlib and adds the event library plus a procd monitor package. The plugin payload includes its real `device-mapper/` directory and versioned libraries, not just symlinks.
- `build-thin.sh`: compile the pinned thin tools in the existing native container with the OpenWrt workspace at `/work/openwrt` and the upstream source at `/work/storage-tools/thin-provisioning-tools`. The isolated Rustup/Cargo homes live under `/work/storage-tools`; install the Rust 1.99.1 minimal toolchain plus target `aarch64-unknown-linux-musl` there first.
- `package-thin.sh`: package the compiled tools and backup helper. Run only in the matching disposable SDK; `/host/storage-tools` is a dedicated export directory. It signs the local build output, verifies each APK separately, and exports only public signing material. The device installs with a scoped `--keys-dir`; signature checks are not disabled on the router.
- `ax5-thin-safe.profile`: per-pool 70% threshold, 20% extension. Attach using `--metadataprofile ax5-thin-safe`, ensure dmeventd runs, and retain free VG extents. Do not allocate the whole VG to the pool.
- `ax5-thin-backup`: install in `/usr/sbin`. Usage `ax5-thin-backup VG POOL [LABEL]`; an active pool is required. It does not activate a pool or overwrite an existing backup directory.

Build `libudev-zero`, `lvm2`, `libdevmapper-event`, and `lvm2-monitor` in the same SDK before building the thin tools. Use a case-sensitive native Linux ext4 build volume. Do not substitute packages from a different snapshot or install newly generated kernel packages to satisfy this userspace add-on.

## Backup and restore

The helper writes root-only directories under `/mnt/mmcblk0p18/.lvm-backups/`, including VG configuration, raw and normalized XML, geometry, restore notes, and checksums. It reserves and releases a metadata snapshot; if data or metadata geometry changes during the capture it fails rather than accepting inconsistent geometry. Retry with a new label once the pool geometry is stable.

On this kernel/tool combination the raw snapshot XML can report `nr_data_blocks="0"`. The helper records actual pool geometry and replaces only that zero header field, preserving mappings and the original XML for audit. This is required for a usable restore: the upstream restore option alone did not fix the zero-count case because the in-memory data space map was initialized before final superblock overrides.

Restore metadata into a NEW file/device of at least `metadata_bytes` from `layout.json`, run `thin_restore -i metadata.xml -o NEW_METADATA`, then `thin_check NEW_METADATA`. The VG config alone cannot reconstruct thin mappings. Metadata backup does not replace a consistent backup of user data. Copy the complete directory and SHA256SUMS to another device, then verify checksums there.

## Verified behavior and limits

A file-backed test pool crossed 70% usage and dmeventd extended it from 64MiB to 80MiB. The backup XML was restored and checked; copied data plus recovered metadata were mapped as a separate read-only thin filesystem, and both test-file hashes matched. The backup helper itself was included in the end-to-end test. All test VG/LV/mapper/loop devices were removed afterwards. Physical GPT, ART and U-Boot remain outside these tests.

For the recovery mapping, the thin-pool target must be created as a normal device-mapper table with the `read_only` feature; the kernel rejects the outer `--readonly` flag on a thin-pool table. The recovered thin LV and filesystem are read-only.

Keep anonymous mounts disabled (`fstab.@global[0].anon_mount=0`) and keep automatic foreign VG activation disabled. Current data remains ext4 mounted by UUID. No backup schedule is installed for a nonexistent production pool; choose a schedule and data destination when a real pool is explicitly provisioned. Next firmware upgrades must include or reinstall these compatible add-on packages; preserving configuration alone does not reinstall binaries.
