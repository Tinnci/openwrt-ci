#!/usr/bin/env bash
set -euo pipefail
export CARGO_HOME=/work/storage-tools/cargo RUSTUP_HOME=/work/storage-tools/rustup
export PATH=$CARGO_HOME/bin:$PATH
stage=/work/openwrt/staging_dir/target-aarch64_cortex-a53_musl
export STAGING_DIR=$stage
tc=/work/openwrt/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.3.0_musl
mkdir -p /work/storage-tools/pkgconfig
ln -sf "$stage/usr/lib/pkgconfig/libdevmapper.pc" /work/storage-tools/pkgconfig/devmapper.pc
export PKG_CONFIG_ALLOW_CROSS=1 PKG_CONFIG_SYSROOT_DIR=$stage
export PKG_CONFIG_LIBDIR=/work/storage-tools/pkgconfig:$stage/usr/lib/pkgconfig
export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=$tc/bin/aarch64-openwrt-linux-musl-gcc
export CC_aarch64_unknown_linux_musl=$tc/bin/aarch64-openwrt-linux-musl-gcc
export AR_aarch64_unknown_linux_musl=$tc/bin/aarch64-openwrt-linux-musl-ar
export BINDGEN_EXTRA_CLANG_ARGS="--target=aarch64-unknown-linux-musl -isystem $tc/include -isystem $stage/usr/include"
export RUSTFLAGS="-C target-feature=-crt-static -C target-cpu=cortex-a53 -C strip=symbols -L native=$stage/usr/lib -L native=$tc/lib"
cd /work/storage-tools/thin-provisioning-tools
cargo build --release --locked --target aarch64-unknown-linux-musl -j3
file target/aarch64-unknown-linux-musl/release/pdata_tools
