# SPDX-License-Identifier: GPL-2.0-only
#
# AX5 lab build: thin provisioning tools (thin_check / thin_dump / thin_repair ...)
# The whole toolset ships as a single multi-call binary, pdata_tools.

include $(TOPDIR)/rules.mk

PKG_NAME:=thin-provisioning-tools
PKG_VERSION:=1.3.4
PKG_RELEASE:=2

PKG_SOURCE:=$(PKG_NAME)-$(PKG_VERSION).tar.gz
PKG_SOURCE_URL:=https://codeload.github.com/jthornber/thin-provisioning-tools/tar.gz/v$(PKG_VERSION)?
PKG_HASH:=e09caa006ee6ff1e0b32dea934e6cb5d96412cd31163d82bd7ccdc1ac06304d5

PKG_LICENSE:=GPL-3.0-only
PKG_LICENSE_FILES:=COPYING
PKG_MAINTAINER:=AX5 build maintainers

PKG_BUILD_DEPENDS:=rust/host
PKG_BUILD_PARALLEL:=1

include $(INCLUDE_DIR)/package.mk
include $(TOPDIR)/feeds/packages/lang/rust/rust-package.mk

# bindgen must parse target musl headers, not the runner's host libc headers.
CARGO_PKG_VARS += \
	BINDGEN_EXTRA_CLANG_ARGS="--target=$(RUSTC_TARGET_ARCH) -isystem $(TOOLCHAIN_DIR)/include -isystem $(STAGING_DIR)/usr/include"

define Package/thin-provisioning-tools
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=Thin provisioning tools for device-mapper thin pools
  URL:=https://github.com/jthornber/thin-provisioning-tools
  DEPENDS:=$(RUST_ARCH_DEPENDS) +libdevmapper +libudev
endef

define Package/thin-provisioning-tools/description
  Userspace tools for device-mapper thin provisioning: thin_check, thin_dump,
  thin_repair, thin_restore, thin_ls and thin_metadata_size. Required to
  validate, back up and restore thin pool metadata.
endef

define Package/thin-provisioning-tools/install
	$(INSTALL_DIR) $(1)/usr/sbin
	$(INSTALL_BIN) $(PKG_INSTALL_DIR)/bin/pdata_tools $(1)/usr/sbin/pdata_tools
	for tool in thin_check thin_dump thin_repair thin_restore thin_ls thin_metadata_size; do \
		$(LN) pdata_tools $(1)/usr/sbin/$$$$tool; \
	done
endef

$(eval $(call BuildPackage,thin-provisioning-tools))
