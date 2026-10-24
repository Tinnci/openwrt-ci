import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "ax5_build", Path(__file__).resolve().parents[1] / "scripts/ax5-build.py"
)
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = build.load_lock()
        self.config = build.SEED.read_text() + "\nCONFIG_KERNEL_IPQ_MEM_PROFILE=512\n"
        (self.root / ".config").write_text(self.config)
        kernel = self.root / "target/linux/generic/kernel-6.12"
        kernel.parent.mkdir(parents=True)
        kernel.write_text("LINUX_VERSION-6.12 = .108\n")
        self.kernel_config = self.root / (
            "build_dir/target-aarch64_cortex-a53_musl/"
            "linux-qualcommax_ipq60xx/linux-6.12.108/.config"
        )
        self.kernel_config.parent.mkdir(parents=True)
        self.kernel_config.write_text(
            "CONFIG_MODULES=y\nCONFIG_MMC=y\nCONFIG_NFSD_V4=y\n" +
            "".join(f"CONFIG_{symbol}=m\n" for symbol in build.KERNEL_MODULES.values())
        )
        self.git_patch = patch.object(build, "git", side_effect=self.fake_git)
        self.git_patch.start()
        self.addCleanup(self.git_patch.stop)

    def fake_git(self, root, *args):
        if Path(root) == self.root:
            return self.lock["source"]["commit"]
        return next(f["commit"] for f in self.lock["feeds"] if f["name"] == Path(root).name)

    def make_outputs(self):
        target = self.root / build.TARGET
        target.mkdir(parents=True)
        (target / f"libwrt-{build.DEVICE}-squashfs-sysupgrade.bin").write_bytes(b"firmware")
        (target / f"libwrt-{build.DEVICE}-squashfs-factory.bin").write_bytes(b"not for release")
        (target / f"libwrt-{build.DEVICE}.manifest").write_text(
            "".join(f"{name} - 1\n" for name in sorted(
                set(build.REQUIRED) | {
                    name for name, value in build.requested_modules().items() if value == "y"
                }
            ))
        )
        (target / "feeds.buildinfo").write_text("locked feeds\n")
        packages = self.root / "bin/packages/aarch64_cortex-a53/base"
        packages.mkdir(parents=True)
        (packages / "samba4-server-1.apk").write_bytes(b"samba")
        kernel_packages = target / "packages"
        kernel_packages.mkdir()
        for name in ("kernel", *build.requested_modules()):
            (kernel_packages / f"{name}-6.12.108-r1.apk").write_bytes(b"module")
        provenance = self.root / "provenance"
        provenance.mkdir()
        (provenance / "build.json").write_text("{}")
        return target

    def test_seed_has_unique_symbols_and_required_packages(self):
        lines = [line.split("=", 1)[0] for line in build.SEED.read_text().splitlines()
                 if line.startswith("CONFIG_")]
        self.assertEqual(len(lines), len(set(lines)))
        self.assertTrue(all(f"CONFIG_PACKAGE_{name}=y" in self.config for name in build.REQUIRED))

    def test_prepare_locks_all_feeds(self):
        build.prepare(self.root)
        feeds = (self.root / "feeds.conf.default").read_text()
        for feed in self.lock["feeds"]:
            self.assertIn(f"{feed['url']}^{feed['commit']}", feeds)
        self.assertEqual((self.root / ".config").read_text(), build.SEED.read_text())

    def test_prepare_rejects_feed_override(self):
        (self.root / "feeds.conf").touch()
        with self.assertRaisesRegex(ValueError, "override"):
            build.prepare(self.root)

    def test_verify(self):
        build.verify(self.root)

    def test_verify_rejects_optional_only_service(self):
        (self.root / ".config").write_text(
            self.config.replace("CONFIG_PACKAGE_minidlna=y", "CONFIG_PACKAGE_minidlna=m")
        )
        with self.assertRaisesRegex(ValueError, "minidlna"):
            build.verify(self.root)

    def test_verify_rejects_wrong_kernel(self):
        (self.root / "target/linux/generic/kernel-6.12").write_text("LINUX_VERSION-6.12 = .55\n")
        with self.assertRaisesRegex(ValueError, "kernel"):
            build.verify(self.root)

    def test_verify_rejects_wrong_source(self):
        with patch.object(build, "git", return_value="0" * 40):
            with self.assertRaisesRegex(ValueError, "Source HEAD"):
                build.verify(self.root)

    def test_verify_rejects_wrong_feed(self):
        def wrong_feed(root, *args):
            return self.lock["source"]["commit"] if Path(root) == self.root else "0" * 40
        with patch.object(build, "git", side_effect=wrong_feed):
            with self.assertRaisesRegex(ValueError, "Feed revision"):
                build.verify(self.root)

    def test_verify_rejects_multi_profile(self):
        (self.root / ".config").write_text(self.config + "CONFIG_TARGET_MULTI_PROFILE=y\n")
        with self.assertRaisesRegex(ValueError, "single AX5"):
            build.verify(self.root)

    def test_verify_rejects_conflicting_avahi(self):
        (self.root / ".config").write_text(self.config + "CONFIG_PACKAGE_avahi-nodbus-daemon=y\n")
        with self.assertRaisesRegex(ValueError, "D-Bus variant"):
            build.verify(self.root)

    def test_verify_rejects_dropped_personal_tool(self):
        (self.root / ".config").write_text(self.config.replace("CONFIG_PACKAGE_btop=y\n", ""))
        with self.assertRaisesRegex(ValueError, "btop"):
            build.verify(self.root)

    def test_verify_rejects_dropped_optional_module(self):
        (self.root / ".config").write_text(
            self.config.replace("CONFIG_PACKAGE_kmod-fs-cifs=m\n", "")
        )
        with self.assertRaisesRegex(ValueError, "kmod-fs-cifs"):
            build.verify(self.root)

    def test_verify_accepts_optional_module_promoted_by_dependency(self):
        (self.root / ".config").write_text(
            self.config.replace("CONFIG_PACKAGE_kmod-fs-cifs=m", "CONFIG_PACKAGE_kmod-fs-cifs=y")
        )
        build.verify(self.root)

    def test_kernel_audit_rejects_disabled_feature(self):
        self.kernel_config.write_text(
            self.kernel_config.read_text().replace("CONFIG_NFSD=m\n", "")
        )
        with self.assertRaisesRegex(ValueError, "CONFIG_NFSD"):
            build.audit_kernel(self.root)
        self.assertTrue((self.root / "provenance/kernel.config").exists())

    def test_kernel_audit_requires_real_config(self):
        self.kernel_config.unlink()
        with self.assertRaisesRegex(ValueError, "compiled Linux"):
            build.audit_kernel(self.root)

    def test_customize_real_script(self):
        path = self.root / "package/base-files/files/bin/config_generate"
        path.parent.mkdir(parents=True)
        path.write_text("ipaddr=192.168.1.1\n")
        subprocess.run(["bash", str(build.REPO / "scripts/customize-ax5.sh")],
                       cwd=self.root, check=True)
        self.assertEqual(path.read_text(), "ipaddr=192.168.3.1\n")
        safety = self.root / "files/etc/uci-defaults/99-ax5-storage-safety"
        subprocess.run(["sh", "-n", str(safety)], check=True)
        self.assertTrue(safety.stat().st_mode & 0o111)
        self.assertIn("allow-interfaces=br-lan",
                      (self.root / "files/etc/avahi/avahi-daemon.conf").read_text())

    def test_customize_rejects_unknown_layout(self):
        result = subprocess.run(["bash", str(build.REPO / "scripts/customize-ax5.sh")],
                                cwd=self.root, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_bundle_includes_both_package_locations_and_checksums(self):
        self.make_outputs()
        build.bundle(self.root)
        out = self.root / "dist"
        self.assertFalse(list(out.glob("*factory*")))
        self.assertTrue((out / "feeds.buildinfo").exists())
        with tarfile.open(out / "Packages.tar.gz") as archive:
            names = archive.getnames()
        self.assertEqual(len(names), 2 + len(build.requested_modules()))
        self.assertTrue(any("/targets/" in "/" + name for name in names))
        with tarfile.open(out / "Provenance.tar.gz") as archive:
            self.assertIn("provenance/kernel.config", archive.getnames())
            self.assertIn("provenance/kernel-audit.json", archive.getnames())
        for line in (out / "SHA256SUMS").read_text().splitlines():
            digest, filename = line.split("  ")
            self.assertEqual(digest, hashlib.sha256((out / filename).read_bytes()).hexdigest())

    def test_bundle_requires_matching_modules(self):
        target = self.make_outputs()
        next((target / "packages").glob("kmod-fs-nfsd-*.apk")).unlink()
        with self.assertRaisesRegex(ValueError, "kmod-fs-nfsd APK"):
            build.bundle(self.root)

    def test_bundle_requires_optional_module_apk(self):
        target = self.make_outputs()
        next((target / "packages").glob("kmod-fs-cifs-*.apk")).unlink()
        with self.assertRaisesRegex(ValueError, "kmod-fs-cifs APK"):
            build.bundle(self.root)

    def test_bundle_rejects_missing_service_in_image(self):
        target = self.make_outputs()
        manifest = next(target.glob("*.manifest"))
        manifest.write_text("luci - 1\n")
        with self.assertRaisesRegex(ValueError, "missing from firmware"):
            build.bundle(self.root)

    def test_lock_rejects_floating_revision(self):
        lock = json.loads(build.LOCK_PATH.read_text())
        lock["feeds"][0]["commit"] = "main"
        path = self.root / "invalid-lock.json"
        path.write_text(json.dumps(lock))
        with patch.object(build, "LOCK_PATH", path):
            with self.assertRaisesRegex(ValueError, "full commit"):
                build.load_lock()


if __name__ == "__main__":
    unittest.main()
