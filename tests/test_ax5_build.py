from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
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
        # Fixtures must not write fake firmware metadata to the real CI summary.
        self.env_patch = patch.dict(
            os.environ,
            {key: value for key, value in os.environ.items()
             if not key.startswith("GITHUB_") and key != "AX5_EMMC_MODE"},
            clear=True,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = build.load_lock()
        block = self.root / "package/kernel/linux/modules/block.mk"
        block.parent.mkdir(parents=True)
        block.write_text("\n".join(
            f"CONFIG_{symbol}=n" for symbol in ("DM_SNAPSHOT", "DM_ZERO", "DM_UEVENT")
        ) + "\n")
        self.dts = self.root / (
            "target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/"
            "ipq6000-ax5-jdcloud.dts"
        )
        self.dts.parent.mkdir(parents=True)
        self.original_dts = (Path(__file__).parent / "fixtures" / self.dts.name).read_text()
        self.prepared_dts = self.original_dts.replace(
            '&sdhc {\n\tstatus = "okay";\n',
            '&sdhc {\n\tstatus = "okay";\n\tbus-width = <4>;\n\tnon-removable;\n',
        )
        self.dts.write_text(self.prepared_dts)
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
            "CONFIG_SWAP=y\nCONFIG_ZSMALLOC=m\nCONFIG_ZRAM_BACKEND_LZO=y\n" +
            "".join(f"CONFIG_{symbol}=y\n" for symbol in build.STORAGE_SYMBOLS) +
            "".join(f"CONFIG_{symbol}=m\n" for symbol in build.KERNEL_MODULES.values())
        )
        self.git_patch = patch.object(build, "git", side_effect=self.fake_git)
        self.git_patch.start()
        self.addCleanup(self.git_patch.stop)

    def fake_git(self, root, *args):
        if Path(root) == self.root:
            return self.lock["source"]["commit"]
        if Path(root) == build.REPO:
            return "a" * 40
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

    def test_identity_is_stable_and_distinguishes_retries(self):
        with patch.dict("os.environ", {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}):
            first = build.build_identity()
            self.assertEqual(first, build.build_identity())
        self.assertEqual(first["build_id"],
                         "libwrt-ax5-jdcloud-k6.12.108-s3a3d0b085955-caaaaaaaaaaaa-r123-a1")
        with patch.dict("os.environ", {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}):
            self.assertNotEqual(first["build_id"], build.build_identity()["build_id"])

    def test_identity_marks_local_builds(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(build.build_identity()["build_id"].endswith("-local"))

    def test_identity_rejects_unsafe_run_values(self):
        for run_id, attempt in (("../bad", "1"), ("123", "1\nunsafe"), ("", "1")):
            with self.subTest(run_id=run_id, attempt=attempt):
                with patch.dict("os.environ", {
                    "GITHUB_RUN_ID": run_id, "GITHUB_RUN_ATTEMPT": attempt,
                }):
                    with self.assertRaisesRegex(ValueError, "numeric GitHub"):
                        build.build_identity()

    def test_identity_exports_workflow_outputs(self):
        output = self.root / "github-output"
        with patch.dict("os.environ", {"GITHUB_OUTPUT": str(output)}):
            with redirect_stdout(io.StringIO()) as stdout:
                build.identity()
        values = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(values, build.build_identity())
        self.assertEqual(json.loads(stdout.getvalue()), values)

    def test_prepare_locks_all_feeds(self):
        (self.root / ".config").unlink()
        self.dts.write_text(self.original_dts)
        build.prepare(self.root)
        feeds = (self.root / "feeds.conf.default").read_text()
        for feed in self.lock["feeds"]:
            self.assertIn(f"{feed['url']}^{feed['commit']}", feeds)
        self.assertFalse((self.root / ".config").exists())
        self.assertEqual(self.dts.read_text(), self.original_dts.replace(
            '&sdhc {\n\tstatus = "okay";\n',
            '&sdhc {\n\tstatus = "okay";\n\tbus-width = <4>;\n\tnon-removable;\n',
        ))
        kernel_patch = self.root / "target/linux/qualcommax/patches-6.12" / build.KERNEL_PATCH.name
        self.assertEqual(kernel_patch.read_bytes(), build.KERNEL_PATCH.read_bytes())

    def test_prepare_rejects_existing_kernel_patch(self):
        (self.root / ".config").unlink()
        kernel_patch = self.root / "target/linux/qualcommax/patches-6.12" / build.KERNEL_PATCH.name
        kernel_patch.parent.mkdir(parents=True)
        kernel_patch.write_text("existing patch\n")
        with self.assertRaisesRegex(ValueError, "already exists"):
            build.prepare(self.root)
        self.assertEqual(self.dts.read_text(), self.prepared_dts)
        self.assertEqual(kernel_patch.read_text(), "existing patch\n")

    def test_hs400_profile_is_explicit_and_has_distinct_identity(self):
        stable = build.build_identity()
        self.assertEqual(stable["emmc_mode"], "hs200")
        self.assertNotIn("-hs400-", stable["build_id"])
        (self.root / ".config").unlink()
        self.dts.write_text(self.original_dts)
        with patch.dict(os.environ, {"AX5_EMMC_MODE": "hs400"}):
            build.prepare(self.root)
            experimental = build.build_identity()
        self.assertIn("\tbus-width = <8>;", self.dts.read_text())
        self.assertIn("\tmmc-hs400-1_8v;", self.dts.read_text())
        self.assertNotIn("/delete-property/ mmc-hs400", self.dts.read_text())
        self.assertNotIn("mmc-hs400-enhanced-strobe", self.dts.read_text())
        self.assertEqual(experimental["emmc_mode"], "hs400")
        self.assertIn("-hs400-", experimental["build_id"])
        self.assertNotEqual(experimental["firmware_artifact"], stable["firmware_artifact"])

    def test_emmc_profile_rejects_unknown_values(self):
        with patch.dict(os.environ, {"AX5_EMMC_MODE": "unsafe"}):
            with self.assertRaisesRegex(ValueError, "AX5_EMMC_MODE"):
                build.prepare(self.root)

    def test_verify_rejects_mislabeled_emmc_profile(self):
        with patch.dict(os.environ, {"AX5_EMMC_MODE": "hs400"}):
            with self.assertRaisesRegex(ValueError, "eMMC device tree"):
                build.verify(self.root)

    def test_prepare_rejects_changed_device_tree_context(self):
        (self.root / ".config").unlink()
        changed = self.original_dts.replace("mmc-hs200-1_8v", "mmc-hs400-1_8v")
        self.dts.write_text(changed)
        with self.assertRaises(subprocess.CalledProcessError):
            build.prepare(self.root)
        self.assertEqual(self.dts.read_text(), changed)
        self.assertFalse((self.root / "feeds.conf.default").exists())

    def test_prepare_rejects_early_config(self):
        with self.assertRaisesRegex(ValueError, "silently rewrite"):
            build.prepare(self.root)

    def test_configure_restores_seed_after_feed_refresh(self):
        (self.root / ".config").write_text("CONFIG_PACKAGE_luci=y\n")

        def resolve(*args, **kwargs):
            self.assertEqual((self.root / ".config").read_text(), build.SEED.read_text())
            self.assertEqual(args[0], ["make", "defconfig", "RECURSIVE_DEP_IS_ERROR=1"])
            self.assertEqual(kwargs["cwd"], self.root)

        with patch.object(build.subprocess, "run", side_effect=resolve):
            with patch.object(build, "snapshot") as snapshot:
                build.configure(self.root)
        snapshot.assert_called_once_with(self.root)

    def test_configure_stops_on_kconfig_error(self):
        with patch.object(build.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "make")):
            with patch.object(build, "snapshot") as snapshot:
                with self.assertRaises(subprocess.CalledProcessError):
                    build.configure(self.root)
        snapshot.assert_not_called()

    def test_patch_feeds_fixes_the_virtual_dependency(self):
        recipe = self.root / "feeds/luci/applications/luci-app-weechat/Makefile"
        recipe.parent.mkdir(parents=True)
        recipe.write_text(
            '# This is free software, licensed under the Apache License, Version 2.0 .\n\n'
            'include $(TOPDIR)/rules.mk\n\n'
            'LUCI_TITLE:=LuCI support for WeeChat IRC client\n'
            'LUCI_DEPENDS:=+luci-base +weechat +rpcd-mod-ucode\n\n'
            'PKG_LICENSE:=Apache-2.0\n'
            'PKG_MAINTAINER:=Josef Schlehofer <pepe.schlehofer@gmail.com>\n'
        )
        build.patch_feeds(self.root)
        self.assertIn("+weechat-minimal", recipe.read_text())
        self.assertNotIn("+weechat ", recipe.read_text())

    def test_patch_feeds_rejects_changed_context(self):
        recipe = self.root / "feeds/luci/applications/luci-app-weechat/Makefile"
        recipe.parent.mkdir(parents=True)
        recipe.write_text("unexpected upstream content\n")
        with self.assertRaises(subprocess.CalledProcessError):
            build.patch_feeds(self.root)
        self.assertEqual(recipe.read_text(), "unexpected upstream content\n")

    def test_snapshot_records_feed_patch(self):
        (self.root / "feeds.conf.default").write_text("locked feeds\n")
        script = self.root / "scripts/diffconfig.sh"
        script.parent.mkdir()
        script.write_text("printf 'CONFIG_PACKAGE_luci=y\\n'\n")
        script.chmod(0o755)
        build.snapshot(self.root)
        metadata = json.loads((self.root / "provenance/build.json").read_text())
        self.assertEqual(metadata["feed_patches"][build.FEED_PATCH.name],
                         hashlib.sha256(build.FEED_PATCH.read_bytes()).hexdigest())
        self.assertEqual((self.root / "provenance" / build.FEED_PATCH.name).read_bytes(),
                         build.FEED_PATCH.read_bytes())
        self.assertEqual(metadata["source_patches"][build.SOURCE_PATCH.name],
                         hashlib.sha256(build.SOURCE_PATCH.read_bytes()).hexdigest())
        self.assertEqual((self.root / "provenance" / build.SOURCE_PATCH.name).read_bytes(),
                         build.SOURCE_PATCH.read_bytes())
        self.assertEqual(metadata["kernel_patches"][build.KERNEL_PATCH.name],
                         hashlib.sha256(build.KERNEL_PATCH.read_bytes()).hexdigest())
        self.assertEqual((self.root / "provenance" / build.KERNEL_PATCH.name).read_bytes(),
                         build.KERNEL_PATCH.read_bytes())
        self.assertNotIn(build.HS400_PATCH.name, metadata["source_patches"])
        subprocess.run(["git", "-C", str(self.root), "apply", str(build.HS400_PATCH)],
                       check=True)
        with patch.dict(os.environ, {"AX5_EMMC_MODE": "hs400"}):
            build.snapshot(self.root)
        experimental = json.loads((self.root / "provenance/build.json").read_text())
        self.assertEqual(experimental["emmc_mode"], "hs400")
        self.assertEqual(experimental["source_patches"][build.HS400_PATCH.name],
                         hashlib.sha256(build.HS400_PATCH.read_bytes()).hexdigest())
        self.assertEqual((self.root / "provenance" / build.HS400_PATCH.name).read_bytes(),
                         build.HS400_PATCH.read_bytes())

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
            self.config.replace("CONFIG_PACKAGE_kmod-fs-btrfs=m\n", "")
        )
        with self.assertRaisesRegex(ValueError, "kmod-fs-btrfs"):
            build.verify(self.root)

    def test_verify_accepts_optional_module_promoted_by_dependency(self):
        (self.root / ".config").write_text(
            self.config.replace("CONFIG_PACKAGE_kmod-fs-btrfs=m", "CONFIG_PACKAGE_kmod-fs-btrfs=y")
        )
        build.verify(self.root)

    def test_cifs_and_zram_must_be_preinstalled(self):
        for package in ("kmod-fs-cifs", "kmod-zram", "zram-swap"):
            with self.subTest(package=package):
                self.assertIn(f"CONFIG_PACKAGE_{package}=y\n", self.config)
                (self.root / ".config").write_text(self.config.replace(
                    f"CONFIG_PACKAGE_{package}=y", f"CONFIG_PACKAGE_{package}=m"
                ))
                with self.assertRaisesRegex(ValueError, package):
                    build.verify(self.root)

    def test_storage_module_install_rejects_changed_overrides(self):
        build.install_storage_modules(self.root)
        block = self.root / "package/kernel/linux/modules/block.mk"
        self.assertNotIn("=n", block.read_text())
        self.assertEqual(block.with_name(build.STORAGE_MODULES.name).read_bytes(),
                         build.STORAGE_MODULES.read_bytes())
        with self.assertRaisesRegex(ValueError, "Unexpected locked"):
            build.install_storage_modules(self.root)

    def test_kernel_audit_requires_dynamic_storage(self):
        original = self.kernel_config.read_text()
        for symbol in build.STORAGE_SYMBOLS:
            with self.subTest(symbol=symbol):
                self.kernel_config.write_text("\n".join(
                    line for line in original.splitlines()
                    if not line.startswith(f"CONFIG_{symbol}=")
                ))
                with self.assertRaisesRegex(ValueError, symbol):
                    build.audit_kernel(self.root)

    def test_kernel_audit_requires_swap_and_zram_support(self):
        original = self.kernel_config.read_text()
        for symbol in ("SWAP", "ZRAM", "ZSMALLOC", "ZRAM_BACKEND_LZO", "CIFS"):
            with self.subTest(symbol=symbol):
                self.kernel_config.write_text("\n".join(
                    line for line in original.splitlines()
                    if not line.startswith(f"CONFIG_{symbol}=")
                ))
                with self.assertRaisesRegex(ValueError, f"CONFIG_{symbol}"):
                    build.audit_kernel(self.root)

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
        zram = self.root / "files/etc/uci-defaults/98-ax5-zram"
        subprocess.run(["sh", "-n", str(zram)], check=True)
        self.assertTrue(zram.stat().st_mode & 0o111)
        # Exercise the generated first-boot script without touching host services.
        uci = self.root / "uci"
        uci.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$UCI_LOG"\n')
        uci.chmod(0o755)
        init = self.root / "zram-init"
        init.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$INIT_LOG"\n')
        init.chmod(0o755)
        script = zram.read_text().replace("/etc/init.d/zram", str(init))
        subprocess.run(["sh", "-c", script], check=True, env={
            **os.environ, "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
            "UCI_LOG": str(self.root / "uci.log"), "INIT_LOG": str(self.root / "init.log"),
        })
        self.assertEqual((self.root / "uci.log").read_text().splitlines(), [
            "set system.@system[0].zram_size_mb=128",
            "set system.@system[0].zram_comp_algo=lzo",
            "set system.@system[0].zram_priority=100",
            "commit system",
        ])
        self.assertEqual((self.root / "init.log").read_text(), "enable\n")
        report = self.root / "files/usr/sbin/ax5-emmc-report"
        self.assertEqual(report.read_bytes(),
                         (build.REPO / "scripts/collect-emmc-telemetry.sh").read_bytes())
        self.assertTrue(report.stat().st_mode & 0o111)

    def test_customize_rejects_unknown_layout(self):
        result = subprocess.run(["bash", str(build.REPO / "scripts/customize-ax5.sh")],
                                cwd=self.root, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_bundle_includes_both_package_locations_and_checksums(self):
        self.make_outputs()
        build.bundle(self.root)
        out = self.root / "dist"
        build_id = build.build_identity()["build_id"]
        self.assertFalse(list(out.glob("*factory*")))
        self.assertTrue((out / f"{build_id}-feeds.buildinfo").exists())
        self.assertTrue(all(path.name.startswith(build_id) for path in out.iterdir()))
        with tarfile.open(out / f"{build_id}-packages.tar.gz") as archive:
            names = archive.getnames()
        self.assertEqual(len(names), 2 + len(build.requested_modules()))
        self.assertTrue(any("/targets/" in "/" + name for name in names))
        self.assertIn("packages/aarch64_cortex-a53/base/samba4-server-1.apk", names)
        with tarfile.open(out / f"{build_id}-provenance.tar.gz") as archive:
            self.assertIn("provenance/kernel.config", archive.getnames())
            self.assertIn("provenance/kernel-audit.json", archive.getnames())
        checksums = (out / f"{build_id}-sha256sums.txt").read_text().splitlines()
        self.assertEqual(len(checksums), len(list(out.iterdir())) - 1)
        for line in checksums:
            digest, filename = line.split("  ")
            self.assertEqual(digest, hashlib.sha256((out / filename).read_bytes()).hexdigest())
        metadata = json.loads((out / f"{build_id}-build.json").read_text())
        self.assertEqual(metadata["build_id"], build_id)
        original = self.root / build.TARGET / metadata["original_firmware"]
        self.assertEqual((out / metadata["files"]["firmware"]).read_bytes(), original.read_bytes())
        self.assertTrue(all((out / name).is_file() for name in metadata["files"].values()))

    def test_bundle_writes_workflow_summary(self):
        self.make_outputs()
        summary = self.root / "summary.md"
        with patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary)}):
            build.bundle(self.root)
        text = summary.read_text()
        self.assertIn(build.build_identity()["build_id"], text)
        self.assertIn("sha256sum --check", text)
        self.assertIn("Not validated for flashing", text)

    def test_bundle_requires_matching_modules(self):
        target = self.make_outputs()
        next((target / "packages").glob("kmod-fs-nfsd-*.apk")).unlink()
        with self.assertRaisesRegex(ValueError, "kmod-fs-nfsd APK"):
            build.bundle(self.root)

    def test_bundle_requires_optional_module_apk(self):
        target = self.make_outputs()
        next((target / "packages").glob("kmod-fs-btrfs-*.apk")).unlink()
        with self.assertRaisesRegex(ValueError, "kmod-fs-btrfs APK"):
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
