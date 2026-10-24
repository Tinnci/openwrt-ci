# AX5 dynamic storage capabilities

The image preinstalls Device Mapper, loop, LVM2 (`lvm` and `dmsetup`),
cryptsetup, veritysetup and integritysetup. A local kernel-module definition
adds snapshot, thin provisioning, zero, verity with FEC, integrity and their
supporting modules to the locked OpenWrt tree. Linear/error/striped targets
are provided by dm-mod; encryption and mirroring by kmod-dm.

Preparation removes the locked package's conflicting snapshot/zero/uevent
overrides with strict context checks. The full compiled kernel configuration
is audited, not only the package selections. The local module definition is
included in provenance.

This supplies the Linux mapping primitives used by Android-style `super`
logical partitions. It does not supply Android liblp metadata tools,
first-stage init, AVB policy, snapuserd/dm-user or Virtual A/B orchestration.
It does not make U-Boot understand logical volumes or automatically recover
from a failed eMMC initialization.

No GPT, filesystem, existing data or boot selection is changed by these
settings. LVM2 upstream packages include discovery/activation hooks: existing
LVM metadata on attached disks may therefore be activated. Do not attach
untrusted storage, and test activation policy before deploying.

RAID, multipath, cache, debug and fault-injection targets are not prerequisites
for super partitions and are intentionally not enabled by this profile.
Real super/Virtual A/B integration remains a separate boot and userspace task.
