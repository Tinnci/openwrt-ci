# AX5 ordinary-LV overlay

The lab migration keeps p1-p17 and GPT unchanged. SquashFS remains the lower
filesystem; a fully allocated 4 GiB ext4 LV, ax5data/overlay, provides its writable
upper and work directories. APK files and the APK database move together.
The existing 48 GiB virtual data LV stays in the thin pool. The VG has about
43.85 GiB initially free after the ordinary overlay allocation. These numbers
share one PV and are not additive virtual/physical capacities.

## Early boot integration

The locked fstools already mounts the internal F2FS overlay at /tmp/overlay,
loads its modules-boot.d, and selects its upper/sbin/block executable before
performing extroot. Therefore the identified lab can bootstrap this change
from an installed, locally signed block-mount APK without changing the FIT,
SquashFS image, GPT or U-Boot. Future firmware includes the same patch/helper.

The block patch is inert without an explicit internal ax5_extroot config. With
that config present it requires regular, root-owned, non-writable-by-others
config/helper files, then runs the helper in a separate process group with an
internal 18-second deadline. It does not require a BusyBox timeout applet.
Failure returns to the original internal overlay. No formatting or automatic
migration is performed during boot.

The helper validates board, ART hash, p18 geometry, VG UUID, LV UUID, ordinary
linear segment type and filesystem UUID. It activates only ax5data/overlay.
It supplies /dev/dm-N from verified sysfs major/minor values before early block
probing; userspace device discovery has not run yet. Inherited descriptors are
closed in child LVM invocations, leaving mount_root's descriptors intact.
Late ax5-data recreates LVM nodes for early-activated devices, then activates
the separate data LV and its monitored thin pool. Global activation stays off.

## Migration and recovery

The original upper and .fs_state were archived with GNU tar 1.35, numeric
owners, POSIX ACLs, all xattrs, hardlinks, symlinks and whiteout devices. A
bounded freeze/thaw runner quiesced F2FS during archive capture; the archive
was hashed and copied privately to Mac and T5 before boot changes. The new
filesystem has its own empty work directory. Content and metadata were compared
on the device, including 77 xattrs and 62 device/whiteout entries.

Use `ax5-extroot-select status` to inspect the active overlay and next boot
selector. `ax5-extroot-select internal` disables the internal bootstrap and
its extroot fstab entry; reboot to use the retained F2FS system.
`ax5-extroot-select lvm` enables both for the next boot. The selector lives on
the INTERNAL overlay, so editing the active LV's UCI copy alone does not change
boot selection. The helper mounts the verified internal filesystem only while
updating or reading the selector and validates its backing offset and UUID.

The internal upper is a recovery snapshot, not a continuously synchronized
copy. Packages and configuration changed on the new LV are not automatically
present after fallback. No full factory-reset erasure of p18 is implied:
resetting the internal system does not securely erase retained LVM data.
Keep the private archive and off-device backups; same-device snapshots and
metadata exports alone do not protect against eMMC failure.

## Firmware upgrade boundary

The image checker refuses sysupgrade while the LVM overlay is active or its
internal selector is enabled. Select internal and reboot first. This avoids
booting a new kernel/base image beneath an old upper containing incompatible
kernel modules, package state or binaries. Standard eMMC upgrade still targets
p16/p17 and preserves p18. After upgrading, rebuild the LV upper from the new
internal system and reinstall matching packages before re-enabling LVM extroot.
Do not merely re-enable a stale external upper after a firmware change.

The custom block-mount version is pinned on the lab installation. Do not replace
it from an unrelated rolling package feed: the early activation support would
be lost. Future source builds include the patch and record its provenance.
A live destructive firmware upgrade is not part of overlay migration testing.
