# AX5 JDCloud lab data LVM (2026-11-01)

This is an explicit migration of the identified lab device, not a first-boot
formatter. No build/defaults script runs pvcreate or changes the GPT.

| Area | Layout | Policy |
|---|---|---|
| p1-p15 | Existing boot chain, environment, ART | Preserve |
| p16 | 6 MiB HLOS/FIT | Preserve; U-Boot still boots physical partitions |
| p17 | 1 GiB rootfs and F2FS overlay | Preserve |
| p18 | Existing 56.10 GiB partition becomes the only PV in ax5data | No GPT changes |
| ax5data/pool | 8 GiB thin pool, 64 KiB chunks, 128 MiB metadata plus spare | ax5-thin-safe profile; monitored |
| ax5data/data | 48 GiB virtual ext4 | Existing mount path /mnt/mmcblk0p18 and filesystem UUID preserved |
| VG free | About 47.85 GiB initially | Pool growth or additional explicitly managed LVs |

The 48 GiB virtual size is not additional physical capacity. Additional volumes
and snapshots share the same finite PV. Keep free extents for autoextension
(70% threshold, 20% increments) and track both pool data and metadata. A thin
snapshot is not an independent backup. No extra swap LV is added; zram remains.
The ext4 reserved-block percentage is reduced from 5% to 1% on the migrated
filesystem; U-Boot and the root filesystem do not depend on this data VG.

## Consistent migration and recovery

Samba and data writers were stopped, and p18 was unmounted and remounted read
only. Matching e2image 1.47.3 created a full-data qcow2 image, including ext4
metadata and allocated file blocks. The image is held privately on Mac and T5.
Its SHA256 is f22ab03df4bb09c2e20da0b92da4e8efe1eba640436aa79741cdbfdecd9109ea.
The restored raw filesystem passed e2fsck and all 9,229 regular-file SHA256
checks against the original read-only source. A separate copy was shrunk to
48 GiB, checked again, and copied into the newly created thin LV; all 9,229
file checks passed there too. Original backups were never modified.

Full recovery instructions and exact sector geometry are in the private local
migration report. Recovery restores the original image to p18 after stopping
services, unmounting data, deactivating the VG and checking device identity.
Never restore to the whole eMMC or change p1-p17. The backup contains user data
and must not become a public repository/Release asset.

## Boot integration

`ax5-data` starts at 16, after dmeventd at 12 and before normal block mounts.
Activation is opt-in via ax5_storage.settings.data_lvm=1 and requires p18's
fixed sector geometry and configured VG UUID. It activates ax5data/data only;
global auto_activate remains 0. fstab mounts the existing filesystem UUID with
rw,noatime. ax5-data-ready validates the filesystem UUID, actual block-device
identity and underlying p18/VG UUID before diagnostic or metadata-backup writes.
It handles OpenWrt's separate /dev/mapper nodes and /dev/dm-N names.
Child LVM calls close inherited watchdog fd3 and the observed rc/procd pipe
fd13, leaving the parent descriptors intact.

`ax5-thin-backup` saves normalized thin mappings, raw export, pool geometry and
vgcfgbackup; copy these off-device along with a separate consistent data backup.
Metadata archives on the data LV alone do not protect against loss of the PV.

## Root filesystem capacity

The migrated data LV does not enlarge the current F2FS root overlay.
See [ax5-rootfs-layout.md](ax5-rootfs-layout.md) for measured APK capacity
and a proposed ordinary-LV overlay that requires separate preinit integration.

## Future firmware upgrades

Use only an image containing compatible DM-thin kernel modules, LVM2,
thin_check/restore, working dmeventd plugins and this explicit activation unit.
The corrected recipe installs versioned event libraries and /usr/lib/device-mapper
plugins, and starts dmeventd early. Preserve fstab, ax5_storage and the monitoring
profile. Build a new image from the corrected source before upgrading this
migrated installation: older Actions run 41279860398 predates these fixes.
Do not automatically flash it. Standard sysupgrade must preserve p18 and pass
its image validation; the data LV does not replace p16/p17.
