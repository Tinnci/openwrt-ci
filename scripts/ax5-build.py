#!/usr/bin/env python3
"""AX5 build preparation, validation and packaging; standard library only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

REPO = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO / "configs/ax5-build.lock.json"
SEED = REPO / "configs/ipq60xx-custom-wifi.config"
FEED_PATCH = REPO / "patches/feeds/0001-luci-weechat-select-concrete-provider.patch"
SOURCE_PATCH = REPO / "patches/source/0001-ax5-jdcloud-describe-fixed-emmc-bus.patch"
KERNEL_PATCH = REPO / "patches/kernel/9999-mmc-core-retry-ax5-hs400-init-with-hs200.patch"
HS400_PATCH = REPO / "patches/source/0002-ax5-jdcloud-experimental-hs400.patch"
STORAGE_MODULES = REPO / "configs/ax5-dynamic-storage.mk"
DEVICE = "redmi_ax5-jdcloud"
TARGET = Path("bin/targets/qualcommax/ipq60xx")
DTS_PATH = Path(
    "target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq6000-ax5-jdcloud.dts"
)
REQUIRED = (
    "luci", "samba4-server", "samba4-admin", "samba4-client", "luci-app-samba4",
    "avahi-dbus-daemon", "wsdd2", "minidlna", "luci-app-minidlna",
    "nfs-kernel-server", "nfs-utils", "kmod-fs-nfsd", "rpcbind",
    "kmod-qca-nss-ecm", "kmod-qca-nss-drv-bridge-mgr", "kmod-qca-nss-drv-vlan-mgr",
    "block-mount", "openssh-sftp-server",
    "zram-swap", "lvm2", "cryptsetup", "veritysetup", "integritysetup", "losetup",
)
# Check the real Linux configuration, not just OpenWrt's package selections.
KERNEL_MODULES = {
    "fs-ext4": "EXT4_FS", "fs-exfat": "EXFAT_FS", "fs-vfat": "VFAT_FS",
    "fs-ntfs3": "NTFS3_FS", "fs-nfsd": "NFSD", "fuse": "FUSE_FS",
    "usb-storage": "USB_STORAGE", "usb-storage-uas": "USB_UAS",
    "nls-utf8": "NLS_UTF8", "tun": "TUN", "wireguard": "WIREGUARD",
    "inet-diag": "INET_DIAG", "netlink-diag": "NETLINK_DIAG",
    "sched-cake": "NET_SCH_CAKE", "fs-cifs": "CIFS", "fs-btrfs": "BTRFS_FS",
    "fs-xfs": "XFS_FS", "loop": "BLK_DEV_LOOP", "veth": "VETH",
    "zram": "ZRAM", "dm": "BLK_DEV_DM",
    "ax5-dynamic-storage": "DM_THIN_PROVISIONING",
}
STORAGE_SYMBOLS = {
    "DM_SNAPSHOT", "DM_THIN_PROVISIONING", "DM_BUFIO", "DM_BIO_PRISON",
    "DM_PERSISTENT_DATA", "DM_VERITY", "DM_VERITY_FEC", "DM_INTEGRITY",
    "DM_CRYPT", "DM_MIRROR", "DM_ZERO", "DM_UEVENT", "CRYPTO_AES",
}


def install_storage_modules(root):
    """Extend the locked package, including its explicit snapshot/zero overrides."""
    path = root / "package/kernel/linux/modules/block.mk"
    text = path.read_text()
    for symbol in ("DM_SNAPSHOT", "DM_ZERO", "DM_UEVENT"):
        old = f"CONFIG_{symbol}=n"
        if text.count(old) != 1:
            raise ValueError(f"Unexpected locked block.mk override: {symbol}")
        text = text.replace(old, f"CONFIG_{symbol}")
    path.write_text(text)
    shutil.copyfile(STORAGE_MODULES, path.with_name("ax5-dynamic-storage.mk"))


def requested_modules():
    return {
        key.removeprefix("CONFIG_PACKAGE_"): value
        for key, value in config_values(SEED.read_text()).items()
        if key.startswith("CONFIG_PACKAGE_kmod-") and value in ("y", "m")
    }


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def load_lock():
    lock = json.loads(LOCK_PATH.read_text())
    for entry in [lock["source"], *lock["feeds"]]:
        if not re.fullmatch(r"[0-9a-f]{40}", entry["commit"]):
            raise ValueError("Every source/feed must have a full commit SHA")
        if not entry["url"].startswith("https://github.com/"):
            raise ValueError("Only HTTPS GitHub sources are supported")
    names = [feed["name"] for feed in lock["feeds"]]
    if len(names) != len(set(names)) or any(
        not re.fullmatch(r"[a-z_]+", name) for name in names
    ):
        raise ValueError("Feed names must be unique identifiers")
    return lock


def clone(root):
    source = load_lock()["source"]
    root.mkdir(parents=True, exist_ok=False)
    subprocess.run(["git", "init", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", source["url"]], check=True)
    subprocess.run(["git", "-C", str(root), "fetch", "--depth=1", "origin", source["commit"]], check=True)
    subprocess.run(["git", "-C", str(root), "checkout", "--detach", "FETCH_HEAD"], check=True)


def emmc_mode():
    mode = os.environ.get("AX5_EMMC_MODE", "hs200")
    if mode not in ("hs200", "hs400"):
        raise ValueError("AX5_EMMC_MODE must be hs200 or hs400")
    return mode


def prepare(root):
    mode = emmc_mode()
    lock = load_lock()
    if git(root, "rev-parse", "HEAD") != lock["source"]["commit"]:
        raise ValueError("Source HEAD does not match lock file")
    if (root / "feeds.conf").exists():
        raise ValueError("feeds.conf would override the locked feeds")
    if (root / ".config").exists():
        raise ValueError("Prepare requires no .config: feeds update would silently rewrite it")
    kernel_patch = root / "target/linux/qualcommax/patches-6.12" / KERNEL_PATCH.name
    if kernel_patch.exists():
        raise ValueError("Kernel fallback patch already exists; prepare requires fresh source")
    # Only patch the JDCloud board, not the shared Xiaomi hardware description.
    command = ["git", "-C", str(root), "apply"]
    subprocess.run([*command, "--check", str(SOURCE_PATCH)], check=True)
    subprocess.run([*command, str(SOURCE_PATCH)], check=True)
    if mode == "hs400":
        subprocess.run([*command, "--check", str(HS400_PATCH)], check=True)
        subprocess.run([*command, str(HS400_PATCH)], check=True)
    kernel_patch.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KERNEL_PATCH, kernel_patch)
    # ^commit is the OpenWrt feeds script's immutable revision syntax.
    (root / "feeds.conf.default").write_text("".join(
        f"src-git {feed['name']} {feed['url']}^{feed['commit']}\n"
        for feed in lock["feeds"]
    ))


def verify_revisions(root):
    lock = load_lock()
    if git(root, "rev-parse", "HEAD") != lock["source"]["commit"]:
        raise ValueError("Source HEAD does not match lock file")
    for feed in lock["feeds"]:
        if git(root / "feeds" / feed["name"], "rev-parse", "HEAD") != feed["commit"]:
            raise ValueError(f"Feed revision mismatch: {feed['name']}")


def patch_feeds(root):
    verify_revisions(root)
    command = ["git", "-C", str(root / "feeds/luci"), "apply"]
    # Fail on changed context instead of silently skipping or patching another version.
    subprocess.run([*command, "--check", str(FEED_PATCH)], check=True)
    subprocess.run([*command, str(FEED_PATCH)], check=True)


def configure(root):
    verify_revisions(root)
    install_storage_modules(root)
    # feeds update refreshes any existing .config before packages are installed.
    # Restore the seed only after feed update, patching and installation are complete.
    shutil.copyfile(SEED, root / ".config")
    subprocess.run(["make", "defconfig", "RECURSIVE_DEP_IS_ERROR=1"], cwd=root, check=True)
    verify_storage_dependencies(root)
    snapshot(root)


def verify_storage_dependencies(root):
    available = set(re.findall(
        r"(?m)^Package: (\S+)$", (root / "tmp/.packageinfo").read_text()
    ))
    dependencies = re.search(r"(?m)^  DEPENDS:=(.*)$", STORAGE_MODULES.read_text())[1]
    required = {item.removeprefix("+") for item in dependencies.split()}
    missing = sorted(required - available)
    if missing:
        raise ValueError("Unknown dynamic-storage dependencies: " + ", ".join(missing))


def kernel_preflight(root):
    """Resolve actual patched Linux Kconfig before downloading/building all packages.

    Uses the distro ARM64 compiler for configuration only. The final build still
    uses the locked OpenWrt toolchain and is audited independently.
    """
    subprocess.run(["make", "target/linux/prepare", "V=s"], cwd=root,
                   stdin=subprocess.DEVNULL, check=True)
    version = load_lock()["source"]["kernel"]
    kernels = list(root.glob(
        f"build_dir/target-*/linux-qualcommax_ipq60xx/linux-{version}"
    ))
    if len(kernels) != 1:
        raise ValueError("Expected exactly one prepared Linux source tree")
    out = root / "provenance"
    out.mkdir(exist_ok=True)
    target = subprocess.check_output([
        "perl", str(root / "scripts/kconfig.pl"), "+", "+",
        str(root / "target/linux/generic/config-6.12"),
        str(root / "target/linux/qualcommax/config-6.12"),
        str(root / "target/linux/qualcommax/ipq60xx/config-default"),
    ], text=True)
    target += "".join(
        line.replace("CONFIG_KERNEL_", "CONFIG_", 1) + "\n"
        for line in (root / ".config").read_text().splitlines()
        if re.match(r"^(# )?CONFIG_KERNEL_", line)
    )
    base = out / "kernel-preflight.target"
    base.write_text(target + "\n# CONFIG_KALLSYMS_EXTRA_PASS is not set\n"
                    "# CONFIG_KALLSYMS_ALL is not set\nCONFIG_KALLSYMS_UNCOMPRESSED=y\n")
    override = out / "kernel-preflight.override"
    override.write_text(subprocess.check_output([
        "perl", str(root / "scripts/package-metadata.pl"), "kconfig",
        str(root / "tmp/.packageinfo"), str(root / ".config"), "6.12",
    ], text=True))
    config = out / "kernel-preflight.config"
    merged = subprocess.check_output([
        "perl", str(root / "scripts/kconfig.pl"), "m+", "+",
        str(base), "/dev/null", str(override),
    ], text=True)
    config.write_text("\n".join(
        line for line in merged.splitlines() if "INITRAMFS" not in line
    ) + '\nCONFIG_INITRAMFS_SOURCE=""\n# CONFIG_INITRAMFS_FORCE is not set\n'
        '# CONFIG_INITRAMFS_PRESERVE_MTIME is not set\n'
        # Clang exposes choices absent with the final GCC toolchain. Match the
        # non-LTO/non-CFI/non-randstruct profile, without hiding storage options.
        '# CONFIG_LTO_CLANG_FULL is not set\n# CONFIG_LTO_CLANG_THIN is not set\n'
        '# CONFIG_CFI_CLANG is not set\n# CONFIG_RANDSTRUCT_FULL is not set\n')
    command = ["make", "-C", str(kernels[0]), f"O={root / 'build_dir/kernel-preflight'}",
               "ARCH=arm64", "LLVM=1", "CC=clang", "LD=ld.lld",
               f"KCONFIG_CONFIG={config}"]
    new = subprocess.check_output([*command, "listnewconfig"], text=True,
                                  stdin=subprocess.DEVNULL)
    (out / "kernel-preflight.new-symbols").write_text(new)
    symbols = re.findall(r"(?m)^CONFIG_[A-Z0-9_]+", new)
    if symbols:
        raise ValueError("Unspecified Linux Kconfig options: " + ", ".join(symbols))
    subprocess.run([*command, "olddefconfig"], stdin=subprocess.DEVNULL, check=True)
    audit_kernel(root, config, "kernel-preflight")


def config_values(text):
    return dict(line.split("=", 1) for line in text.splitlines()
                if line.startswith("CONFIG_") and "=" in line)


def build_identity():
    source = load_lock()["source"]
    ci_commit = git(REPO, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", ci_commit):
        raise ValueError("Expected a full CI commit SHA")
    if not re.fullmatch(r"\d+\.\d+\.\d+", source["kernel"]):
        raise ValueError("Expected a numeric kernel version for artifact names")
    run_id = os.environ.get("GITHUB_RUN_ID")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    if run_id is not None and (
        not re.fullmatch(r"[1-9]\d*", run_id) or not re.fullmatch(r"[1-9]\d*", attempt)
    ):
        raise ValueError("Expected numeric GitHub run ID and attempt")
    run = f"r{run_id}-a{attempt}" if run_id else "local"
    build_id = (
        f"libwrt-ax5-jdcloud-k{source['kernel']}"
        f"{'-hs400' if emmc_mode() == 'hs400' else ''}"
        f"-s{source['commit'][:12]}-c{ci_commit[:12]}-{run}"
    )
    return {
        "build_id": build_id,
        "kernel": source["kernel"],
        "emmc_mode": emmc_mode(),
        "firmware_artifact": f"{build_id}-firmware",
        "diagnostics_artifact": f"{build_id}-diagnostics",
        "config_artifact": f"{build_id}-config",
    }


def identity():
    """Export the same naming metadata used by packaging and both workflows."""
    metadata = build_identity()
    print(json.dumps(metadata, indent=2))
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            for key, value in metadata.items():
                stream.write(f"{key}={value}\n")


def verify(root):
    lock = load_lock()
    verify_revisions(root)
    # Refuse to label one device-tree profile as another in provenance/artifacts.
    dts = (root / DTS_PATH).read_text()
    sdhc = re.search(r"&sdhc\s*\{(.*?)\};", dts, re.S)
    node = sdhc[1] if sdhc else ""
    width = re.search(r"\bbus-width\s*=\s*<(\d+)>\s*;", node)
    hs400 = bool(re.search(r"(?m)^\s*mmc-hs400-1_8v\s*;", node))
    experimental = emmc_mode() == "hs400"
    if not width or width[1] != ("8" if experimental else "4") or hs400 != experimental:
        raise ValueError("eMMC device tree does not match AX5_EMMC_MODE")
    config = config_values((root / ".config").read_text())
    # Kconfig silently drops unavailable symbols. Check every requested boolean,
    # not just the small set of packages required for artifact validation.
    expected = {
        **{key: value for key, value in config_values(SEED.read_text()).items()
           if value == "y"},
        "CONFIG_TARGET_qualcommax_ipq60xx": "y",
        f"CONFIG_TARGET_qualcommax_ipq60xx_DEVICE_{DEVICE}": "y",
        "CONFIG_TARGET_ROOTFS_SQUASHFS": "y",
        "CONFIG_KERNEL_IPQ_MEM_PROFILE": "512",
        **{f"CONFIG_PACKAGE_{package}": "y" for package in REQUIRED},
    }
    missing = [key for key, value in expected.items() if config.get(key) != value]
    missing.extend(
        f"CONFIG_PACKAGE_{package}" for package, value in requested_modules().items()
        if value == "m" and config.get(f"CONFIG_PACKAGE_{package}") not in ("y", "m")
    )
    if missing:
        raise ValueError("Required selections lost after defconfig: " + ", ".join(missing))
    if config.get("CONFIG_TARGET_MULTI_PROFILE") == "y":
        raise ValueError("Expected a single AX5 JDCloud device profile")
    if config.get("CONFIG_PACKAGE_avahi-nodbus-daemon") in ("y", "m"):
        raise ValueError("Samba Avahi support requires only the D-Bus variant")
    version = (root / "target/linux/generic/kernel-6.12").read_text()
    suffix = re.search(r"^LINUX_VERSION-6\.12\s*=\s*(\.\d+)\s*$", version, re.M)
    if not suffix or "6.12" + suffix[1] != lock["source"]["kernel"]:
        raise ValueError("Unexpected kernel version")


def snapshot(root):
    verify(root)
    out = root / "provenance"
    out.mkdir(exist_ok=True)
    shutil.copyfile(root / ".config", out / "build.config")
    shutil.copyfile(root / "feeds.conf.default", out / "feeds.conf")
    shutil.copyfile(LOCK_PATH, out / LOCK_PATH.name)
    shutil.copyfile(FEED_PATCH, out / FEED_PATCH.name)
    shutil.copyfile(SOURCE_PATCH, out / SOURCE_PATCH.name)
    shutil.copyfile(KERNEL_PATCH, out / KERNEL_PATCH.name)
    shutil.copyfile(STORAGE_MODULES, out / STORAGE_MODULES.name)
    if emmc_mode() == "hs400":
        shutil.copyfile(HS400_PATCH, out / HS400_PATCH.name)
    subprocess.run(
        ["bash", "-c", "./scripts/diffconfig.sh > provenance/diffconfig"],
        cwd=root, check=True,
    )
    metadata = {
        **build_identity(),
        "storage_modules": {
            STORAGE_MODULES.name: hashlib.sha256(STORAGE_MODULES.read_bytes()).hexdigest(),
        },
        "feed_patches": {FEED_PATCH.name: hashlib.sha256(FEED_PATCH.read_bytes()).hexdigest()},
        "source_patches": {
            SOURCE_PATCH.name: hashlib.sha256(SOURCE_PATCH.read_bytes()).hexdigest(),
            **({HS400_PATCH.name: hashlib.sha256(HS400_PATCH.read_bytes()).hexdigest()}
               if emmc_mode() == "hs400" else {}),
        },
        "kernel_patches": {
            KERNEL_PATCH.name: hashlib.sha256(KERNEL_PATCH.read_bytes()).hexdigest(),
        },
        "source": git(root, "rev-parse", "HEAD"),
        "ci_commit": git(REPO, "rev-parse", "HEAD"),
        "run_url": (
            f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
            f"{os.environ['GITHUB_RUN_ID']}"
        ) if "GITHUB_RUN_ID" in os.environ else None,
        "feeds": {f["name"]: git(root / "feeds" / f["name"], "rev-parse", "HEAD")
                  for f in load_lock()["feeds"]},
    }
    (out / "build.json").write_text(json.dumps(metadata, indent=2) + "\n")


def audit_kernel(root, config_path=None, prefix="kernel"):
    version = load_lock()["source"]["kernel"]
    configs = [config_path] if config_path is not None else list(root.glob(
        f"build_dir/target-*/linux-qualcommax_ipq60xx/linux-{version}/.config"
    ))
    if len(configs) != 1:
        raise ValueError(f"Expected one compiled Linux {version} config, found {len(configs)}")
    kernel = config_values(configs[0].read_text())
    # NFSv4 kernel support does not by itself configure an NFSv4 userspace export.
    expected = {"CONFIG_MODULES", "CONFIG_MMC", "CONFIG_NFSD_V4"}
    expected.update(f"CONFIG_{symbol}" for symbol in STORAGE_SYMBOLS)
    expected.update(
        f"CONFIG_{symbol}" for module, symbol in KERNEL_MODULES.items()
        if f"kmod-{module}" in requested_modules()
    )
    if "kmod-zram" in requested_modules():
        expected.update({"CONFIG_SWAP", "CONFIG_ZSMALLOC", "CONFIG_ZRAM_BACKEND_LZO"})
    out = root / "provenance"
    out.mkdir(exist_ok=True)
    if configs[0] != out / f"{prefix}.config":
        shutil.copyfile(configs[0], out / f"{prefix}.config")
    report = {key: kernel.get(key, "n") for key in sorted(expected)}
    (out / f"{prefix}-audit.json").write_text(json.dumps({
        "kernel": version, "symbols": report, "packages": requested_modules(),
    }, indent=2) + "\n")
    missing = [key for key, value in report.items() if value not in ("y", "m")]
    if missing:
        raise ValueError("Required Linux features disabled: " + ", ".join(missing))


def bundle(root):
    verify(root)
    audit_kernel(root)
    target = root / TARGET
    images = list(target.glob(f"*{DEVICE}*sysupgrade.bin"))
    if len(images) != 1:
        raise ValueError(f"Expected one AX5 JDCloud sysupgrade image, found {len(images)}")
    manifests = list(target.glob(f"*{DEVICE}*.manifest"))
    if len(manifests) != 1:
        raise ValueError("Missing or ambiguous AX5 package manifest")
    manifest = manifests[0]
    packages = [line.split()[0] for line in manifest.read_text().splitlines() if line.strip()]
    installed_modules = {name for name, value in requested_modules().items() if value == "y"}
    absent = sorted((set(REQUIRED) | installed_modules) - set(packages))
    if absent:
        raise ValueError("Packages missing from firmware manifest: " + ", ".join(absent))
    apks = sorted(set((root / "bin/packages").glob("*/*/*.apk")) |
                  set((target / "packages").glob("*.apk")))
    if not apks:
        raise ValueError("No matching APK packages produced")
    for package in ("kernel", *requested_modules()):
        if not any(apk.name.startswith(package + "-") for apk in apks):
            raise ValueError(f"Missing matching {package} APK")
    metadata = build_identity()
    build_id = metadata["build_id"]
    out = root / "dist"
    out.mkdir(exist_ok=False)
    # Do not publish factory images for this unvalidated upgrade migration.
    files = {
        "firmware": f"{build_id}-squashfs-sysupgrade.bin",
        "manifest": f"{build_id}.manifest",
        "packages": f"{build_id}-packages.tar.gz",
        "provenance": f"{build_id}-provenance.tar.gz",
        "checksums": f"{build_id}-sha256sums.txt",
        "release_notes": f"{build_id}-release.md",
    }
    shutil.copyfile(images[0], out / files["firmware"])
    shutil.copyfile(manifest, out / files["manifest"])
    for path in target.glob("*.buildinfo"):
        shutil.copyfile(path, out / f"{build_id}-{path.name}")
    (out / f"{build_id}-build.json").write_text(json.dumps({
        **metadata, "source": load_lock()["source"],
        "ci_commit": git(REPO, "rev-parse", "HEAD"),
        "original_firmware": images[0].name, "files": files,
    }, indent=2) + "\n")
    shutil.copytree(root / "provenance", out / "provenance")
    with tarfile.open(out / files["packages"], "w:gz") as archive:
        for apk in apks:
            # Keep APK basenames and repository paths unchanged for installation.
            archive.add(apk, arcname=apk.relative_to(root / "bin"))
    with tarfile.open(out / files["provenance"], "w:gz") as archive:
        archive.add(out / "provenance", arcname="provenance")
    shutil.rmtree(out / "provenance")
    source = load_lock()["source"]
    (out / files["release_notes"]).write_text(
        f"# AX5 JDCloud test build\n\n"
        f"- Build ID: `{build_id}`\n"
        f"- Source: {source['url']} @ `{source['commit']}` ({source['branch']})\n"
        f"- Kernel: {source['kernel']}\n"
        "- Default LAN address: 192.168.3.1\n"
        "- Configure credentials and storage services before use.\n"
        "- DLNA and NFS are installed but disabled on first boot.\n\n"
        "**Upgrade compatibility from the old mmc_do_upgrade firmware is NOT validated.**\n"
        "Back up configuration and all shared/Time Machine data off the router first.\n"
        "Keeping settings does not guarantee /overlay data or mounts survive.\n"
        "Only the sysupgrade image is supplied; do not substitute a factory image.\n\n"
        f"`{files['packages']}` contains packages from this build, including kernel modules.\n"
        "Do not mix them with rolling snapshot feeds or another firmware build.\n"
        f"`{files['provenance']}` includes resolved OpenWrt/Linux configs, a kernel audit,\n"
        "and source/feed revisions. Optional module APKs are not preinstalled.\n"
    )
    sums = []
    for path in sorted(out.iterdir()):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        sums.append(f"{digest}  {path.name}\n")
    (out / files["checksums"]).write_text("".join(sums))
    if "GITHUB_STEP_SUMMARY" in os.environ:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(
                f"## AX5 JDCloud — packaged test build\n\n"
                f"Build ID: `{build_id}`\n\n"
                "**Not validated for flashing from the old mmc_do_upgrade firmware.**\n\n"
                "| File | Bytes |\n| --- | ---: |\n"
            )
            for path in sorted(out.iterdir()):
                stream.write(f"| `{path.name}` | {path.stat().st_size} |\n")
            stream.write(
                f"\nVerify after extraction: `sha256sum --check {files['checksums']}`\n"
                "\nArtifact upload and optional publication are separate workflow steps.\n"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=(
            "identity", "clone", "prepare", "patch-feeds", "configure", "kernel-preflight",
            "verify", "snapshot", "bundle"
        )
    )
    parser.add_argument("source", type=Path, nargs="?")
    args = parser.parse_args()
    if args.command == "identity":
        if args.source is not None:
            parser.error("identity does not take a source directory")
        identity()
    else:
        if args.source is None:
            parser.error("source directory is required")
        globals()[args.command.replace("-", "_")](args.source.resolve())


if __name__ == "__main__":
    main()
