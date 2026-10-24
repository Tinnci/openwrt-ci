"""Guard the small, deliberately restricted set of live GitHub workflows.

These text-level policy checks complement (not replace) actionlint's YAML and
GitHub expression validation. Archived upstream YAML is intentionally excluded.
"""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
BUILD = "IPQ60XX-CUSTOM-WIFI.yml"
CHECK = "check-ax5.yml"


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
        self.assertIn("run: sha256sum --check SHA256SUMS", text)

    def test_checks_limit_duplicate_work(self):
        text = self.workflows[CHECK]
        self.assertIn("push:\n    branches: [main]", text)
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
