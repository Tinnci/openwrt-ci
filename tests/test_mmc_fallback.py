"""Compile and execute patched kernel excerpts with simulated MMC operations.

This verifies control flow and fault handling, not a kernel build or hardware.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
PATCH = ROOT / "patches/kernel/9999-mmc-core-retry-ax5-hs400-init-with-hs200.patch"


class MmcFallbackTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cc"), "C compiler required for MMC fault injection")
    def test_patched_initialization_fault_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "drivers/mmc/core/mmc.c"
            source.parent.mkdir(parents=True)
            source.write_bytes((FIXTURES / "mmc-init-card.c").read_bytes())
            for options in (["--check"], []):
                result = subprocess.run(
                    ["git", "-C", str(root), "apply", *options, str(PATCH)],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            code = source.read_text()
            discovery = """
    (void)cid; (void)rocr; (void)ocr;
    attempts++;
    if (discovery_error) { err = discovery_error; goto err; }
    card = oldcard ? oldcard : &storage;
    card->host = host;
    card->ext_csd.rev = 8;
    card->mmc_avail_type = EXT_CSD_CARD_TYPE_HS;
    if (card_hs200 && (host->caps2 & MMC_CAP2_HS200))
        card->mmc_avail_type |= EXT_CSD_CARD_TYPE_HS200;
    if (host->caps2 & MMC_CAP2_HS400)
        card->mmc_avail_type |= EXT_CSD_CARD_TYPE_HS400;
    if (host->caps2 & MMC_CAP2_HS400_ES)
        card->mmc_avail_type |= EXT_CSD_CARD_TYPE_HS400ES;
    host->ios.bus_width = (host->caps & MMC_CAP_8_BIT_DATA) ? width : 2;
    host->ios.timing = LEGACY;
"""
            code = code.replace(
                "/* TEST_DISCOVERY: original discovery and EXT_CSD parsing omitted. */",
                discovery,
            ).replace(
                "/* TEST_FEATURES: original non-timing feature setup omitted. */",
                "if (feature_error) { err = feature_error; goto free_card; }",
            )
            (root / "mmc-patched.c").write_text(code)
            shutil.copyfile(FIXTURES / "mmc-fallback-harness.c", root / "harness.c")
            compile_result = subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                 str(root / "harness.c"), "-o", str(root / "harness")],
                capture_output=True, text=True,
            )
            self.assertEqual(compile_result.returncode, 0,
                             compile_result.stdout + compile_result.stderr)
            result = subprocess.run(
                [str(root / "harness")], capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("16 MMC fault-injection scenarios passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
