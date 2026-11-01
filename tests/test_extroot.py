from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UpgradeGuardTests(unittest.TestCase):
    def check(self, filesystem, selector, fstab, configured=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'board').write_text('redmi,ax5-jdcloud\n')
            (root / 'mounts').write_text(f'/dev/test /overlay {filesystem} rw 0 0\n')
            if configured:
                (root / 'config').write_text('configured\n')
            binary = root / 'uci'
            binary.write_text('#!/bin/sh\ncase "$*" in\n'
                              f' *ax5_extroot*) echo {selector};;\n'
                              f' *fstab*) echo {fstab};;\nesac\n')
            binary.chmod(0o755)
            source = (ROOT / 'runtime/lib/upgrade/ax5-extroot-check.sh').read_text()
            for old, new in [('/tmp/sysinfo/board_name', 'board'),
                             ('/proc/mounts', 'mounts'),
                             ('/etc/config/ax5_extroot', 'config')]:
                source = source.replace(old, str(root / new))
            script = root / 'check.sh'
            script.write_text(source + '\nax5_extroot_upgrade_check\n')
            return subprocess.run(['sh', str(script)], capture_output=True, text=True,
                                  env={**os.environ, 'PATH': f'{root}:' + os.environ['PATH']})

    def test_active_external_overlay_refuses_upgrade(self):
        result = self.check('ext4', 1, 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('reboot before sysupgrade', result.stderr)

    def test_internal_recovery_with_both_selectors_disabled_allows_upgrade(self):
        self.assertEqual(self.check('f2fs', 0, 0).returncode, 0)

    def test_internal_root_with_either_selector_enabled_refuses_upgrade(self):
        for selector, fstab in [(1, 0), (0, 1), (1, 1)]:
            with self.subTest(selector=selector, fstab=fstab):
                self.assertNotEqual(self.check('f2fs', selector, fstab).returncode, 0)

    def test_unconfigured_device_keeps_standard_upgrade(self):
        self.assertEqual(self.check('ext4', 1, 1, configured=False).returncode, 0)
