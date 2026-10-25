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

## Configuration preflight

Both the check and full-build workflows prepare the locked, patched Linux
source before starting the full package download/build. They merge the target
config and package Kconfig overrides using OpenWrt's own scripts, then run
Linux `listnewconfig`: any unanswered option fails the check instead of being
silently defaulted. A resolved `olddefconfig` is audited separately as
`kernel-preflight.config` / `kernel-preflight-audit.json`.

This configuration-only step uses the runner's ARM64-capable Clang. Its
Clang-only LTO/CFI/randstruct choices are explicitly disabled to match the
GCC build profile. It is not a replacement for the final OpenWrt GCC kernel
build or its independent `kernel.config` audit.

Custom module dependency names are checked against the real generated
`tmp/.packageinfo`; unknown names fail immediately. AES is built into the
locked generic Linux configuration (`CONFIG_CRYPTO_AES=y`), not supplied by
a nonexistent `kmod-crypto-aes`. FEC uses upstream `kmod-reed-solomon`.
Newly exposed DM debug/unused targets are explicitly disabled.

Checks run on main and experiment-branch pushes as well as pull requests and
manual dispatch. The full build also executes the preflight inline, so a
manual full build cannot skip it.
