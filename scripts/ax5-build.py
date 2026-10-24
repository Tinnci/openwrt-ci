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
DEVICE = "redmi_ax5-jdcloud"
TARGET = Path("bin/targets/qualcommax/ipq60xx")
REQUIRED = (
    "luci", "samba4-server", "samba4-admin", "samba4-client", "luci-app-samba4",
    "avahi-dbus-daemon", "wsdd2", "minidlna", "luci-app-minidlna",
    "nfs-kernel-server", "nfs-utils", "kmod-fs-nfsd", "rpcbind",
    "kmod-qca-nss-ecm", "kmod-qca-nss-drv-bridge-mgr", "kmod-qca-nss-drv-vlan-mgr",
    "block-mount", "openssh-sftp-server",
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
}


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


def prepare(root):
    lock = load_lock()
    if git(root, "rev-parse", "HEAD") != lock["source"]["commit"]:
        raise ValueError("Source HEAD does not match lock file")
    if (root / "feeds.conf").exists():
        raise ValueError("feeds.conf would override the locked feeds")
    # ^commit is the OpenWrt feeds script's immutable revision syntax.
    (root / "feeds.conf.default").write_text("".join(
        f"src-git {feed['name']} {feed['url']}^{feed['commit']}\n"
        for feed in lock["feeds"]
    ))
    shutil.copyfile(SEED, root / ".config")


def config_values(text):
    return dict(line.split("=", 1) for line in text.splitlines()
                if line.startswith("CONFIG_") and "=" in line)


def verify(root):
    lock = load_lock()
    if git(root, "rev-parse", "HEAD") != lock["source"]["commit"]:
        raise ValueError("Source HEAD does not match lock file")
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
    for feed in lock["feeds"]:
        if git(root / "feeds" / feed["name"], "rev-parse", "HEAD") != feed["commit"]:
            raise ValueError(f"Feed revision mismatch: {feed['name']}")


def snapshot(root):
    verify(root)
    out = root / "provenance"
    out.mkdir(exist_ok=True)
    shutil.copyfile(root / ".config", out / "build.config")
    shutil.copyfile(root / "feeds.conf.default", out / "feeds.conf")
    shutil.copyfile(LOCK_PATH, out / LOCK_PATH.name)
    subprocess.run(
        ["bash", "-c", "./scripts/diffconfig.sh > provenance/diffconfig"],
        cwd=root, check=True,
    )
    metadata = {
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


def audit_kernel(root):
    version = load_lock()["source"]["kernel"]
    configs = list(root.glob(
        f"build_dir/target-*/linux-qualcommax_ipq60xx/linux-{version}/.config"
    ))
    if len(configs) != 1:
        raise ValueError(f"Expected one compiled Linux {version} config, found {len(configs)}")
    kernel = config_values(configs[0].read_text())
    # NFSv4 kernel support does not by itself configure an NFSv4 userspace export.
    expected = {"CONFIG_MODULES", "CONFIG_MMC", "CONFIG_NFSD_V4"}
    expected.update(
        f"CONFIG_{symbol}" for module, symbol in KERNEL_MODULES.items()
        if f"kmod-{module}" in requested_modules()
    )
    out = root / "provenance"
    out.mkdir(exist_ok=True)
    shutil.copyfile(configs[0], out / "kernel.config")
    report = {key: kernel.get(key, "n") for key in sorted(expected)}
    (out / "kernel-audit.json").write_text(json.dumps({
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
    out = root / "dist"
    out.mkdir(exist_ok=False)
    # Do not publish factory images for this unvalidated upgrade migration.
    for path in [images[0], manifest, *target.glob("*.buildinfo")]:
        shutil.copyfile(path, out / path.name)
    shutil.copytree(root / "provenance", out / "provenance")
    with tarfile.open(out / "Packages.tar.gz", "w:gz") as archive:
        for apk in apks:
            archive.add(apk, arcname=apk.relative_to(root / "bin"))
    with tarfile.open(out / "Provenance.tar.gz", "w:gz") as archive:
        archive.add(out / "provenance", arcname="provenance")
    shutil.rmtree(out / "provenance")
    source = load_lock()["source"]
    (out / "RELEASE.md").write_text(
        f"# AX5 JDCloud test build\n\n"
        f"- Source: {source['url']} @ `{source['commit']}` ({source['branch']})\n"
        f"- Kernel: {source['kernel']}\n"
        "- Default LAN address: 192.168.3.1\n"
        "- Configure credentials and storage services before use.\n"
        "- DLNA and NFS are installed but disabled on first boot.\n\n"
        "**Upgrade compatibility from the old mmc_do_upgrade firmware is NOT validated.**\n"
        "Back up configuration and all shared/Time Machine data off the router first.\n"
        "Keeping settings does not guarantee /overlay data or mounts survive.\n"
        "Only the sysupgrade image is supplied; do not substitute a factory image.\n\n"
        "Packages.tar.gz contains packages from this build, including kernel modules.\n"
        "Do not mix them with rolling snapshot feeds or another firmware build.\n"
        "Provenance.tar.gz includes resolved OpenWrt/Linux configs, a kernel audit,\n"
        "and source/feed revisions. Optional module APKs are not preinstalled.\n"
    )
    sums = []
    for path in sorted(out.iterdir()):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        sums.append(f"{digest}  {path.name}\n")
    (out / "SHA256SUMS").write_text("".join(sums))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("clone", "prepare", "verify", "snapshot", "bundle"))
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    globals()[args.command](args.source.resolve())


if __name__ == "__main__":
    main()
