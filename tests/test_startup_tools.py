import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]


class BootEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.temp.name) / 'reader'
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                        str(ROOT / 'packages/ax5-startup-tools/src/bootenv-read.c'),
                        '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def inspect(self, payload, corrupt=False, truncate=False):
        data = payload.ljust(262140, b'\0')
        encoded = struct.pack('<I', zlib.crc32(data)) + data
        if corrupt:
            encoded = encoded[:-1] + b'\x01'
        if truncate:
            encoded = encoded[:-1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'environment'
            path.write_bytes(encoded)
            result = subprocess.run([str(self.binary), '--file', str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(path.read_bytes(), encoded)
            return result

    def test_crc_checked_whitelist_without_credentials(self):
        result = self.inspect(b'bootcmd=bootipq\0bootdelay=2\0ipaddr=192.168.1.1\0'
                              b'password=PRIVATE_SECRET\0ethaddr=PRIVATE_MAC\0\0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('environment_crc=valid', result.stdout)
        self.assertIn('bootcmd=bootipq', result.stdout)
        self.assertNotIn('PRIVATE', result.stdout)

    def test_bad_crc_and_truncated_files_fail_closed(self):
        for options in ({'corrupt': True}, {'truncate': True}):
            result = self.inspect(b'bootcmd=bootipq\0\0', **options)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('bootcmd=', result.stdout)

    def test_custom_values_are_redacted_not_executed_or_dumped(self):
        result = self.inspect(b'bootcmd=run secret=PRIVATE_SECRET\0ipaddr=PRIVATE_SECRET\0\0')
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('PRIVATE_SECRET', result.stdout)
        self.assertIn('custom (redacted)', result.stdout)

    def test_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_bytes(bytes(262144))
            link = Path(directory) / 'link'
            link.symlink_to(target)
            result = subprocess.run([str(self.binary), '--file', str(link)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)


class StartupWorkerTests(unittest.TestCase):
    def run_worker(self, mounted=True, symlink=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        data = root / 'data'
        data.mkdir()
        pstore = root / 'pstore'
        pstore.mkdir()
        (pstore / 'console-ramoops-0').write_bytes(b'x' * 1100000)
        (root / 'bootid').write_text('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n')
        (root / 'mounts').write_text(
            f'/dev/mmcblk0p18 {data} ext4 rw,noatime 0 0\n' if mounted else '')
        private = data / '.ax5-diagnostics'
        outside = root / 'outside'
        outside.mkdir()
        if symlink:
            private.symlink_to(outside, target_is_directory=True)
        else:
            private.mkdir()
            for i in range(7):
                (private / f'boot-00000000-0000-0000-0000-{i:012x}').mkdir()
        binary = root / 'bin'
        binary.mkdir()
        for name, body in {
            'sleep': 'exit 0', 'logger': 'exit 0', 'mount': 'exit 0',
            'stat': 'echo 0', 'ax5-boot-health': 'echo safe-health-report',
            'timeout': 'shift; exec "$@"',
        }.items():
            path = binary / name
            path.write_text('#!/bin/sh\n' + body + '\n')
            path.chmod(0o755)
        script = (ROOT / 'runtime/usr/sbin/ax5-startup-worker').read_text()
        for before, after in [
            ('/tmp/ax5-startup.lock', str(root / 'lock')),
            ('/tmp/ax5-startup', str(root / 'tmp')),
            ('/proc/sys/kernel/random/boot_id', str(root / 'bootid')),
            ('/proc/mounts', str(root / 'mounts')),
            ('/sys/fs/pstore', str(pstore)), ('/mnt/mmcblk0p18', str(data)),
        ]:
            script = script.replace(before, after)
        path = root / 'worker'
        path.write_text(script)
        result = subprocess.run(['sh', str(path)], env={
            **os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'],
        }, capture_output=True, text=True, timeout=10)
        return result, root, private, outside

    def test_bounded_archive_preserves_pstore_and_rotates(self):
        result, root, private, _ = self.run_worker()
        self.assertEqual(result.returncode, 0, result.stderr)
        dest = private / 'boot-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        self.assertEqual((dest / 'console-ramoops-0').stat().st_size, 1048576)
        self.assertEqual((dest / 'health.txt').read_text(), 'safe-health-report\n')
        self.assertEqual(len(list(private.glob('boot-*'))), 5)
        self.assertEqual((root / 'pstore/console-ramoops-0').stat().st_size, 1100000)
        self.assertFalse((root / 'lock').exists())

    def test_unmounted_data_does_not_archive_to_overlay(self):
        result, root, private, _ = self.run_worker(mounted=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(private.glob('boot-*'))), 7)
        self.assertTrue(list((root / 'tmp').glob('boot-*.txt')))

    def test_symlink_archive_directory_is_rejected(self):
        result, _, _, outside = self.run_worker(symlink=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])


class DiagnosticDependencyTests(unittest.TestCase):
    def test_failed_od_cannot_turn_into_zero_frequency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            node = root / 'sys/firmware/devicetree/base/soc@0/mmc@7804000'
            node.mkdir(parents=True)
            (node / 'max-frequency').write_bytes((192000000).to_bytes(4, 'big'))
            (node / 'bus-width').write_bytes((4).to_bytes(4, 'big'))
            binary = root / 'bin'
            binary.mkdir()
            for name in ('od', 'dmesg'):
                p = binary / name
                p.write_text('#!/bin/sh\nexit 1\n')
                p.chmod(0o755)
            result = subprocess.run(['sh', str(ROOT / 'scripts/collect-emmc-telemetry.sh')],
                env={**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'],
                     'AX5_SYSFS_ROOT': str(root / 'sys'), 'AX5_DEBUGFS_ROOT': str(root / 'debug')},
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('max-frequency=unavailable', result.stdout)
            self.assertNotIn('max-frequency=0', result.stdout)


class LvmStartupTests(unittest.TestCase):
    def test_ax5_preinit_is_opt_in_and_closes_watchdog_child_fd(self):
        import sys
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ('preinit', 'init', 'hotplug'):
                    dest = root / 'utils/lvm2/files' / ('lvm2.' + name)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / 'tests/fixtures' / dest.name, dest)
                subprocess.run(['git', '-C', str(root), 'apply',
                    str(ROOT / 'patches/feeds/0002-ax5-lvm-explicit-activation.patch')], check=True)
                (root / 'board').write_text('redmi,ax5-jdcloud\n')
                (root / 'cmdline').write_text('root=PARTUUID=example' + (' ax5.lvm_root=1' if enabled else ''))
                lvm = root / 'lvm'
                lvm.write_text(f'#!{sys.executable}\nimport os\n'
                    'opened=True\ntry: os.fstat(3)\nexcept OSError: opened=False\n'
                    f'with open({str(root / "calls")!r}, "a") as f: f.write(str(opened)+"\\n")\n')
                lvm.chmod(0o755)
                script = (root / 'utils/lvm2/files/lvm2.preinit').read_text()
                for a, b in [('/tmp/sysinfo/board_name', str(root / 'board')),
                             ('/proc/cmdline', str(root / 'cmdline')), ('/sbin/lvm', str(lvm)),
                             ('/tmp/lvm/cache', str(root / 'cache')), ('/dev/kmsg', str(root / 'kmsg'))]:
                    script = script.replace(a, b)
                run = root / 'run.sh'
                run.write_text(script + '\nexec 3>"' + str(root / 'watchdog') + '"\ndo_startlvm\n')
                result = subprocess.run(['sh', str(run)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = root / 'calls'
                if enabled:
                    self.assertEqual(calls.read_text().splitlines(), ['False', 'False'])
                else:
                    self.assertFalse(calls.exists())

if __name__ == '__main__':
    unittest.main()
