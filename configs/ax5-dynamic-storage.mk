# Included by OpenWrt's kernel-module package discovery.
# Linear/error/striped targets are part of dm-mod; crypt/mirror are in kmod-dm.
define KernelPackage/ax5-dynamic-storage
  SUBMENU:=Block Devices
  TITLE:=AX5 logical partitions, snapshots and verified storage
  DEPENDS:=+kmod-dm +kmod-lib-crc32c +kmod-reed-solomon +kmod-crypto-sha256 +kmod-crypto-xts +kmod-lib-xor
  KCONFIG:= \
	CONFIG_DM_UEVENT=y \
	CONFIG_DM_ZERO \
	CONFIG_DM_SNAPSHOT \
	CONFIG_DM_BUFIO \
	CONFIG_DM_BIO_PRISON \
	CONFIG_DM_PERSISTENT_DATA \
	CONFIG_DM_THIN_PROVISIONING \
	CONFIG_DM_VERITY \
	CONFIG_DM_VERITY_FEC=y \
	CONFIG_DM_INTEGRITY \
	CONFIG_DM_DEBUG_BLOCK_MANAGER_LOCKING=n \
	CONFIG_DM_DEBUG_BLOCK_STACK_TRACING=n \
	CONFIG_DM_UNSTRIPED=n \
	CONFIG_DM_CACHE=n \
	CONFIG_DM_WRITECACHE=n \
	CONFIG_DM_EBS=n \
	CONFIG_DM_ERA=n \
	CONFIG_DM_CLONE=n \
	CONFIG_DM_RAID=n \
	CONFIG_DM_DUST=n \
	CONFIG_DM_FLAKEY=n \
	CONFIG_DM_VERITY_VERIFY_ROOTHASH_SIG=n \
	CONFIG_DM_SWITCH=n \
	CONFIG_DM_ZONED=n \
	CONFIG_DM_VDO=n \
	CONFIG_BLK_DEV_INTEGRITY=y \
	CONFIG_ASYNC_CORE \
	CONFIG_ASYNC_XOR
  FILES:= \
	$(LINUX_DIR)/drivers/md/dm-zero.ko \
	$(LINUX_DIR)/drivers/md/dm-snapshot.ko \
	$(LINUX_DIR)/drivers/md/dm-bufio.ko \
	$(LINUX_DIR)/drivers/md/dm-bio-prison.ko \
	$(LINUX_DIR)/drivers/md/dm-persistent-data.ko \
	$(LINUX_DIR)/drivers/md/dm-thin-pool.ko \
	$(LINUX_DIR)/drivers/md/dm-verity.ko \
	$(LINUX_DIR)/drivers/md/dm-integrity.ko \
	$(LINUX_DIR)/crypto/async_tx/async_tx.ko \
	$(LINUX_DIR)/crypto/async_tx/async_xor.ko
  AUTOLOAD:=$(call AutoProbe,dm-zero dm-snapshot dm-thin-pool dm-verity dm-integrity)
endef

$(eval $(call KernelPackage,ax5-dynamic-storage))
