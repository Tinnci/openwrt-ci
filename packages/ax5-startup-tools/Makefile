include $(TOPDIR)/rules.mk
PKG_NAME:=ax5-startup-tools
PKG_RELEASE:=1
PKG_LICENSE:=MIT
include $(INCLUDE_DIR)/package.mk

define Package/ax5-startup-tools
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=AX5 read-only CRC-checked boot environment reader
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/* $(PKG_BUILD_DIR)/
endef

define Build/Compile
	$(TARGET_CC) $(TARGET_CFLAGS) $(TARGET_CPPFLAGS) -std=c99 -Wall -Wextra -Werror \
		-o $(PKG_BUILD_DIR)/ax5-bootenv-read $(PKG_BUILD_DIR)/bootenv-read.c $(TARGET_LDFLAGS)
endef

define Package/ax5-startup-tools/install
	$(INSTALL_DIR) $(1)/usr/sbin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/ax5-bootenv-read $(1)/usr/sbin/
endef
$(eval $(call BuildPackage,ax5-startup-tools))
