"""Reject the host/target metadata mixup that broke the x86 CI runner."""
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'packages/thin-provisioning-tools/files/check-linkage.sh'


class ThinLinkageTests(unittest.TestCase):
    def check_outputs(self, host, target, expected):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for prefix, text in [('release', host), ('aarch64-unknown-linux-musl/release', target)]:
                if text is None:
                    continue
                out = root / 'target' / prefix / 'build/devicemapper-sys-fixture/output'
                out.parent.mkdir(parents=True)
                out.write_text(text)
            result = subprocess.run(['sh', str(SCRIPT), str(root), 'aarch64-unknown-linux-musl', 'release'], capture_output=True)
            self.assertEqual(result.returncode, expected, result.stderr.decode())

    def test_target_only_linkage(self):
        self.check_outputs('cargo:rerun-if-changed=dm.h\n', 'cargo:rustc-link-lib=devmapper\n', 0)

    def test_host_target_search_path_leak(self):
        self.check_outputs('cargo:rustc-link-search=native=/target/usr/lib\n', 'cargo:rustc-link-lib=devmapper\n', 1)

    def test_host_link_library_leak(self):
        self.check_outputs('cargo::rustc-link-lib=devmapper\n', 'cargo:rustc-link-lib=devmapper\n', 1)

    def test_target_linkage_disabled(self):
        self.check_outputs('', '', 1)

    def test_missing_host_or_target_evidence(self):
        self.check_outputs(None, 'cargo:rustc-link-lib=devmapper\n', 1)
        self.check_outputs('', None, 1)
