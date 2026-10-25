"""Guard the small, deliberately restricted set of live GitHub workflows.

These text-level policy checks complement (not replace) actionlint's YAML and
GitHub expression validation. Archived upstream YAML is intentionally excluded.
"""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
BUILD = "IPQ60XX-CUSTOM-WIFI.yml"
CHECK = "check-ax5.yml"
# These exact upstream action.yml revisions were checked to use runs.using=node24.
NODE24_ACTIONS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/cache": "55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
    "actions/upload-artifact": "cf430e030ddbb5b0abf93d22962f4752f3646cd9",
    "actions/download-artifact": "9000827ccba6bdab643e8b6fd33ac0654aef8333",
}


class WorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.workflows = {
            path.name: path.read_text()
            for path in WORKFLOWS.iterdir()
            if path.suffix in (".yml", ".yaml")
        }

    def test_only_ax5_workflows_are_live(self):
        self.assertEqual(set(self.workflows), {BUILD, CHECK})

    def test_no_schedule_or_privileged_pr_event(self):
        for name, text in self.workflows.items():
            with self.subTest(workflow=name):
                self.assertNotRegex(
                    text, r"(?m)^\s*(schedule|pull_request_target|workflow_run):"
                )
                self.assertNotIn("secrets.", text)
                self.assertIn("permissions:\n  contents: read\n", text)

    def test_all_actions_are_pinned(self):
        for name, text in self.workflows.items():
            uses = re.findall(r"(?m)^\s*(?:-\s*)?uses:\s*(\S+)", text)
            with self.subTest(workflow=name):
                self.assertTrue(uses)
                for action in uses:
                    self.assertRegex(action, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")
                self.assertNotRegex(text, r"(?m)^\s*persist-credentials:\s*true")
                self.assertEqual(
                    sum(action.startswith("actions/checkout@") for action in uses),
                    text.count("persist-credentials: false"),
                )

    def test_official_actions_use_verified_node24_revisions(self):
        seen = set()
        for name, text in self.workflows.items():
            for action, revision in re.findall(r"uses:\s*(actions/[\w-]+)@([0-9a-f]+)", text):
                with self.subTest(workflow=name, action=action):
                    self.assertIn(action, NODE24_ACTIONS)
                    self.assertEqual(revision, NODE24_ACTIONS[action])
                    seen.add(action)
            self.assertNotIn("ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION", text)
            self.assertNotIn("FORCE_JAVASCRIPT_ACTIONS_TO_NODE24", text)
        self.assertEqual(seen, set(NODE24_ACTIONS))

    def test_build_is_manual_and_publish_requires_main(self):
        text = self.workflows[BUILD]
        events = text.split("\npermissions:", 1)[0]
        self.assertIn("\n  workflow_dispatch:\n", events)
        self.assertNotRegex(events, r"(?m)^  (push|pull_request|schedule):")
        self.assertIn("default: false", events)
        self.assertIn(
            "if: github.event_name == 'workflow_dispatch' && "
            "github.ref == 'refs/heads/main' && inputs.publish", text
        )
        # Only the separate publish job may write; builds never inherit write.
        self.assertEqual(text.count("contents: write"), 1)
        self.assertNotIn("contents: write", text.split("\n  publish:", 1)[0])
        self.assertIn('run: sha256sum --check "$BUILD_ID-sha256sums.txt"', text)
        self.assertIn("&& inputs.emmc_mode != 'hs400'", text)
        self.assertIn("default: hs200", events)
        self.assertIn("AX5_EMMC_MODE: ${{ inputs.emmc_mode || 'hs200' }}", text)

    def test_artifact_names_flow_from_shared_identity(self):
        text = self.workflows[BUILD]
        self.assertIn("run: python3 scripts/ax5-build.py identity", text)
        self.assertIn("name: ${{ steps.identity.outputs.firmware_artifact }}", text)
        self.assertIn("name: ${{ needs.build.outputs.firmware_artifact }}", text)
        self.assertIn("BUILD_ID: ${{ needs.build.outputs.build_id }}", text)
        self.assertIn('tag="$BUILD_ID"', text)
        self.assertIn("steps.identity.outputs.config_artifact", self.workflows[CHECK])

    def test_cache_tracks_build_inputs_and_allows_retry_saves(self):
        text = self.workflows[BUILD]
        cache = text.split("path: openwrt/.ccache\n", 1)[1].split("\n      - name:", 1)[0]
        hashes = re.findall(r"\$\{\{ hashFiles\((.*?)\) \}\}", cache)
        self.assertEqual(len(hashes), 2)
        self.assertEqual(hashes[0], hashes[1])
        for path in (
            "configs/ax5-build.lock.json", "configs/ipq60xx-custom-wifi.config",
            "patches/**", "scripts/customize-ax5.sh",
        ):
            self.assertIn(f"'{path}'", hashes[0])
        self.assertIn("${{ github.run_id }}-${{ github.run_attempt }}", cache)

    def test_precompressed_firmware_is_not_compressed_again(self):
        text = self.workflows[BUILD]
        upload = text.split("path: openwrt/dist/\n", 1)[1].split("\n      - name:", 1)[0]
        self.assertIn("compression-level: 0", upload)
        self.assertIn("if-no-files-found: error", upload)

    def test_config_seed_is_applied_only_after_feeds_install(self):
        for name, text in self.workflows.items():
            if name == CHECK:
                text = text.split("\n  config:", 1)[1]
            with self.subTest(workflow=name):
                self.assertLess(text.index("./scripts/feeds update -a"),
                                text.index('ax5-build.py" patch-feeds .'))
                self.assertLess(text.index('ax5-build.py" patch-feeds .'),
                                text.index("./scripts/feeds install -a"))
                self.assertLess(text.index("./scripts/feeds install -a"),
                                text.index('ax5-build.py" configure .'))
                self.assertNotIn("\n          make defconfig", text)
        self.assertIn('"patches/feeds/**"', self.workflows[CHECK])
        self.assertEqual(self.workflows[CHECK].count('"patches/source/**"'), 2)
        self.assertEqual(self.workflows[CHECK].count('"patches/kernel/**"'), 2)

    def test_linux_preflight_runs_before_full_build(self):
        for name, text in self.workflows.items():
            with self.subTest(workflow=name):
                self.assertIn('ax5-build.py" kernel-preflight .', text)
                self.assertLess(text.index('ax5-build.py" configure .'),
                                text.index('ax5-build.py" kernel-preflight .'))
        text = self.workflows[BUILD]
        self.assertLess(text.index('ax5-build.py" kernel-preflight .'),
                        text.index('make download -j8'))
        self.assertIn('"configs/ax5-dynamic-storage.mk"', self.workflows[CHECK])

    def test_compile_logs_and_retry_preserve_failure_status(self):
        block = re.search(
            r"(?m)^          set -o pipefail\n(?:          .*\n)+",
            self.workflows[BUILD],
        )
        self.assertIsNotNone(block)
        script = textwrap.dedent(block.group())
        for parallel, retry, expected in ((0, 1, 0), (1, 0, 0), (1, 2, 2)):
            with self.subTest(parallel=parallel, retry=retry):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "logs/ci").mkdir(parents=True)
                    (root / "bin").mkdir()
                    make = root / "bin/make"
                    make.write_text(
                        '#!/bin/sh\n'
                        'echo "make $*"\n'
                        'if [ "$1" = "-j1" ]; then exit "$RETRY_STATUS"; fi\n'
                        'exit "$PARALLEL_STATUS"\n'
                    )
                    make.chmod(0o755)
                    result = subprocess.run(
                        ["bash", "-e", "-o", "pipefail", "-c", script], cwd=root,
                        env={
                            **os.environ, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"],
                            "PARALLEL_STATUS": str(parallel), "RETRY_STATUS": str(retry),
                        },
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                    self.assertTrue((root / "logs/ci/02-compile.log").is_file())
                    self.assertEqual(
                        (root / "logs/ci/03-compile-retry.log").is_file(), parallel != 0
                    )

    def test_checks_limit_duplicate_work(self):
        text = self.workflows[CHECK]
        self.assertIn('push:\n    branches: [main, "experiment/**"]', text)
        self.assertIn('      - ".github/workflows/**"', text)
        self.assertIn("cancel-in-progress: true", text)
        self.assertNotIn("contents: write", text)

    def test_jobs_and_artifacts_have_limits(self):
        for name, text in self.workflows.items():
            with self.subTest(workflow=name):
                jobs = re.findall(r"(?m)^  [\w-]+:\n(?=    )", text.split("\njobs:\n")[1])
                self.assertEqual(len(jobs), text.count("timeout-minutes:"))
                self.assertEqual(
                    text.count("uses: actions/upload-artifact@"),
                    text.count("retention-days:"),
                )
                for days in re.findall(r"retention-days:\s*(\d+)", text):
                    self.assertLessEqual(int(days), 14)

    def test_legacy_workflows_are_preserved_outside_discovery(self):
        archive = ROOT / "docs/legacy-workflows"
        self.assertEqual(len(list(archive.glob("*.yml"))), 10)
        self.assertTrue((archive / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
