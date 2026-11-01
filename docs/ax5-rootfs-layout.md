# Root filesystem and APK capacity on the AX5 lab

Observed on 2026-11-01 after the p18 LVM migration:

| Mount | Filesystem | Capacity / available |
|---|---|---|
| /rom | SquashFS, read-only | 41.8 MiB / 0 (normal for a read-only image) |
| /overlay | F2FS on loop0, inside p17 | 980.4 MiB / about 894.2 MiB |
| / | OverlayFS merging /rom with /overlay | Writable capacity comes from /overlay |
| /mnt/mmcblk0p18 | ext4 on ax5data/data thin LV | 48 GiB virtual; df about 46.9 GiB / 46.2 GiB available |

The device is not using EROFS. Normal `apk add` installs into the merged root
and consumes writable overlay space. The large data mount does not enlarge
that space. Package installation can therefore still run out of room at the
current approximately 1 GiB overlay limit. /tmp is RAM-backed and can impose
an additional temporary-space limit. Kernel packages also need matching
kernel ABI; more disk capacity does not remove that requirement.

EROFS is another read-only image filesystem. Switching the lower image from
SquashFS to EROFS alone would not redirect APK writes to p18 or eliminate the
writable overlay capacity limit. Keep SquashFS until a separate image/upgrade
compatibility and performance evaluation justifies a change.

## Suggested next layout (not deployed)

Keep GPT and p1-p17 unchanged, retaining the boot chain, 6 MiB HLOS and current
p17 system/overlay as a recovery path. Within the existing ax5data VG:

- Create a **4 GiB ordinary, fully allocated LV** with ext4 for an expanded
  root overlay. Its allocation is independent of thin pool exhaustion.
- Keep the existing **48 GiB virtual data LV** in the thin pool for shared
  files, workspace and application data. Do not interpret virtual capacity as
  additional physical storage. Additional thin LVs/snapshots consume the same
  pool and need an explicit capacity budget.
- Keep free VG extents for pool autoextension and maintenance. With one 4 GiB
  ordinary overlay and the existing 48 GiB data volume, their combined maximum
  data allocation remains below the roughly 56.1 GiB PV, allowing metadata and
  some headroom. Initially the 8 GiB pool leaves about 43.85 GiB VG free after
  allocating that proposed overlay LV.
- Keep zram for swap, and place large downloads, caches and service databases
  on the data LV where the application supports a configurable data path.

A 4 GiB overlay is a practical initial budget for this router, not unlimited
package storage. It can be grown later with free VG extents and filesystem
support. A normal LV for the root overlay is preferable here to making boot
and package writes depend on available thin pool data/metadata space.

This requires explicit **preinit/extroot integration**, not merely a late
fstab mount. The current ax5-data START=16 runs after the root overlay has
already been chosen, so it cannot supply the root overlay during that boot.
The required DM modules, LVM userspace and dependencies must be accessible
from the base image early enough, activate only the intended PV/VG/LV, and
then hand off to the normal mount_root/extroot sequence. Test fallback boot,
configuration consistency, missing-LV behavior and sysupgrade before making
it the default. Keep installed package files and the APK database together;
do not move only /usr or symlink APK internals into the data directory.

No overlay migration, EROFS conversion or GPT resize is performed by this
commit. The existing data migration remains independently bootable.

References:
- https://openwrt.org/docs/guide-user/additional-software/extroot_configuration
- https://docs.kernel.org/filesystems/erofs.html
