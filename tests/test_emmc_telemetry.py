import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/collect-emmc-telemetry.sh"


class EmmcTelemetryTests(unittest.TestCase):
    def test_selected_registers_both_orders_and_no_serial(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                card = root / "sys/class/mmc_host/mmc0/mmc0:0001"
                debug_card = root / "debug/mmc0/mmc0:0001"
                card.mkdir(parents=True)
                debug_card.mkdir(parents=True)
                (card / "rev").write_text("0x8\n")
                (card / "name").write_text("SLD64G\n")
                (card / "serial").write_text("PRIVATE_SERIAL\n")
                (card / "cid").write_text("PRIVATE_CID\n")
                node = root / "sys/firmware/devicetree/base/soc@0/mmc@7804000"
                node.mkdir(parents=True)
                (node / "bus-width").write_bytes((8).to_bytes(4, "big"))
                (node / "max-frequency").write_bytes((192000000).to_bytes(4, "big"))
                (node / "mmc-hs400-1_8v").touch()
                data = bytearray(512)
                for index, value in {184: 1, 192: 8, 196: 0x57, 267: 1, 268: 4, 269: 1}.items():
                    data[index] = value
                hex_data = (data[::-1] if reverse else data).hex()
                (debug_card / "ext_csd").write_text(" \t\r\n".join(
                    hex_data[i:i + 64] for i in range(0, len(hex_data), 64)
                ) + "\n")
                (root / "debug/mmc0/ios").write_text("timing spec: 9 (mmc HS200)\n")
                (root / "debug/mmc0/err_stats").write_text("CRC Errors: 0\n")
                # Avoid reading the host machine's real kernel messages.
                bin_dir = root / "bin"
                bin_dir.mkdir()
                dmesg = bin_dir / "dmesg"
                dmesg.write_text(
                    '#!/bin/sh\nprintf "%s\\n" "mmc0: retrying without HS400" '
                    '"mmc0: serial PRIVATE_SERIAL" '
                    '"mmcblk0: filesystem 00000000-1111-2222-3333-444444444444" '
                    '"unrelated private message"\n'
                )
                dmesg.chmod(0o755)
                result = subprocess.run(["sh", str(SCRIPT)], env={
                    **os.environ, "AX5_SYSFS_ROOT": str(root / "sys"),
                    "AX5_DEBUGFS_ROOT": str(root / "debug"),
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                }, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                for expected in ("name=SLD64G", "byte_196=0x57", "byte_268=0x04",
                                 "mmc HS200", "CRC Errors: 0", "retrying without HS400",
                                 "bus-width=8", "max-frequency=192000000",
                                 "mmc-hs400-1_8v=present",
                                 "mmc-hs400-enhanced-strobe=absent"):
                    self.assertIn(expected, result.stdout)
                for private in ("PRIVATE_SERIAL", "PRIVATE_CID", "unrelated private",
                                "00000000-1111-2222-3333-444444444444"):
                    self.assertNotIn(private, result.stdout)
                self.assertEqual((card / "serial").read_text(), "PRIVATE_SERIAL\n")

    def test_missing_interfaces_do_not_fail_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dmesg = root / "dmesg"
            dmesg.write_text("#!/bin/sh\nexit 1\n")
            dmesg.chmod(0o755)
            result = subprocess.run(["sh", str(SCRIPT)], env={
                **os.environ, "AX5_SYSFS_ROOT": str(root / "missing"),
                "AX5_DEBUGFS_ROOT": str(root / "missing"),
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
            }, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("unavailable_or_unrecognized_format", result.stdout)
            self.assertIn("unavailable (permissions", result.stdout)


if __name__ == "__main__":
    unittest.main()
