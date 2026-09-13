from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/security-rustsec.yml"


class RustSecWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.workflow = yaml.load(cls.text, Loader=yaml.BaseLoader)

    def test_events_are_scoped_and_never_use_pull_request_target(self) -> None:
        events = self.workflow["on"]
        self.assertNotIn("pull_request_target", events)
        self.assertEqual(set(events), {"pull_request", "push", "schedule", "workflow_dispatch"})
        self.assertEqual(events["pull_request"]["branches"], ["development"])
        self.assertEqual(events["push"]["branches"], ["development", "release"])
        for event in ("pull_request", "push"):
            paths = set(events[event]["paths"])
            self.assertIn("Cargo.lock", paths)
            self.assertIn("**/Cargo.toml", paths)
            self.assertIn("rust-toolchain.toml", paths)
            self.assertIn(".cargo/audit.toml", paths)
            self.assertNotIn("**/*.md", paths)

    def test_scheduled_and_manual_runs_explicitly_cover_both_maintained_refs(self) -> None:
        job = self.workflow["jobs"]["maintained-branches"]
        self.assertEqual(job["strategy"]["matrix"]["ref"], ["development", "release"])
        self.assertIn("github.event_name == 'schedule'", job["if"])
        self.assertIn("github.event_name == 'workflow_dispatch'", job["if"])
        checkout = job["steps"][0]
        self.assertEqual(checkout["with"]["ref"], "${{ matrix.ref }}")

    def test_change_job_does_not_run_for_scheduled_or_manual_events(self) -> None:
        job = self.workflow["jobs"]["changed-lockfile"]
        self.assertEqual(
            job["if"],
            "github.event_name == 'pull_request' || github.event_name == 'push'",
        )

    def test_permissions_tool_and_database_identity_are_explicit(self) -> None:
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        env = self.workflow["env"]
        self.assertEqual(env["CARGO_AUDIT_VERSION"], "0.22.2")
        self.assertEqual(env["RUSTSEC_DB_URL"], "https://github.com/RustSec/advisory-db.git")
        self.assertEqual(env["RUSTSEC_DB_BRANCH"], "main")
        self.assertEqual(env["SCANNER_RUST"], "1.97.1")
        self.assertNotIn("continue-on-error", self.text)
        self.assertIn("cargo audit --db", self.text)
        self.assertIn("--no-fetch --file Cargo.lock", self.text)
        self.assertIn("git ls-remote", self.text)
        self.assertIn('test "${database_sha}" = "${remote_sha}"', self.text)

    def test_external_actions_are_immutable_pins(self) -> None:
        expected = {
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
            "dtolnay/rust-toolchain@4716b85f2fac3e324e64fa2810f6b5c3905760a5",
        }
        for job in self.workflow["jobs"].values():
            uses = {step["uses"].split(" #", 1)[0] for step in job["steps"] if "uses" in step}
            self.assertEqual(uses, expected)

    def test_scanner_and_network_commands_have_finite_deadlines(self) -> None:
        self.assertIn("timeout-minutes: 15", self.text)
        self.assertGreaterEqual(self.text.count("timeout --signal=TERM --kill-after=10s 8m"), 2)
        self.assertGreaterEqual(self.text.count("timeout --signal=TERM --kill-after=10s 90s"), 2)
        self.assertGreaterEqual(self.text.count("timeout --signal=TERM --kill-after=10s 5m"), 2)


if __name__ == "__main__":
    unittest.main()
