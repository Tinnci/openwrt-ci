"""Compile the patched NSS accounting excerpt with multi-peer report deltas."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches/source/0003-ath11k-nss-reset-per-peer-tx-drops.patch"
NSS_PATCH = Path(
    "package/kernel/mac80211/patches/nss/ath11k/"
    "199-002-ath11k_nss-add-nss-driver-interface.patch"
)


class NssStatsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cc"), "C compiler required for NSS regression")
    def test_per_peer_drop_deltas(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / NSS_PATCH
            target.parent.mkdir(parents=True)
            target.write_bytes((ROOT / "tests/fixtures/ath11k-nss-peer-stats.patch").read_bytes())
            subprocess.run(["git", "-C", str(root), "apply", "--check", str(PATCH)],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root), "apply", str(PATCH)],
                           check=True, capture_output=True)
            # Exercise the actual patched sum and update, inside the peer loop.
            code = "".join(line[1:] for line in target.read_text().splitlines(True)
                           if line.startswith("+") and not line.startswith("+++"))
            start = code.index("\t\tpeer->nss.nss_stats->tx_retries += pstats->tx.retries;")
            end = code.index("\t\tATH11K_NSS_TXRX_NETDEV_STATS(tx,", start)
            accounting = code[start:end]
            harness = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#define NSS_WIFILI_TQM_RR_MAX 3
struct counters { uint64_t tx_retries, tx_failed; };
struct peer { struct { struct counters *nss_stats; } nss; };
struct report {
    struct { unsigned retries; struct { uint32_t drop_stats[3]; } dropped; } tx;
};
static void update(struct peer peers[3], struct report reports[3])
{
    uint64_t tx_dropped = 0;
    for (int i = 0; i < 3; i++) {
        struct peer *peer = &peers[i];
        struct report *pstats = &reports[i];
        int j;
ACCOUNTING
    }
}
int main(void)
{
    struct counters counts[3] = {0};
    struct peer peers[3];
    struct report reports[3] = {0};
    for (int i = 0; i < 3; i++) peers[i].nss.nss_stats = &counts[i];
    reports[0].tx.dropped.drop_stats[0] = 4;
    reports[0].tx.dropped.drop_stats[2] = 3;
    reports[0].tx.retries = 5;
    reports[2].tx.dropped.drop_stats[1] = 2;
    update(peers, reports);
    assert(counts[0].tx_failed == 7);
    assert(counts[1].tx_failed == 0);
    assert(counts[2].tx_failed == 2);
    assert(counts[0].tx_retries == 5);
    update(peers, reports);
    assert(counts[0].tx_failed == 14);
    assert(counts[1].tx_failed == 0);
    assert(counts[2].tx_failed == 4);
    assert(counts[0].tx_retries == 10);
    reports[0].tx.dropped.drop_stats[0] = UINT32_MAX;
    reports[0].tx.dropped.drop_stats[2] = UINT32_MAX;
    update(peers, reports);
    assert(counts[0].tx_failed == 14 + 2 * (uint64_t)UINT32_MAX);
    assert(counts[1].tx_failed == 0);
    assert(counts[2].tx_failed == 6);
    puts("NSS multi-peer drop accounting passed");
    return 0;
}
"""
            source = root / "accounting.c"
            source.write_text(harness.replace("ACCOUNTING", accounting))
            executable = root / "accounting"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(executable)],
                           check=True, capture_output=True)
            result = subprocess.run([str(executable)], check=True, capture_output=True,
                                    text=True, timeout=10)
            self.assertIn("NSS multi-peer drop accounting passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
