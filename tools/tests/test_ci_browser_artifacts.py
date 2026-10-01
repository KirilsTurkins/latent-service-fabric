"""Keep browser evidence retention tied to its actual producing step."""
from __future__ import annotations

from pathlib import Path
import json
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
PRODUCER = "Run bounded renderer and provider integration lanes"
UPLOAD = "Retain bounded browser boundary observations"


def retention_enabled(expression: str, renderer: str, outcome: str | None,
                      job_status: str = "success", lane: str = "renderer-public") -> bool:
    """Evaluate this guard's conjunctions, comparisons and status checks only."""
    context = {"needs.profile.outputs.renderer": renderer, "matrix.lane": lane}
    if outcome is not None:
        context["steps.integration_lanes.outcome"] = outcome
    status_checks = {
        "always()": True,
        "success()": job_status == "success",
        "failure()": job_status == "failure",
        "cancelled()": job_status == "cancelled",
    }
    clauses = [clause.strip() for clause in expression.split("&&")]
    # Actions adds success() when the expression has no status check function.
    results = [True if any(c in status_checks for c in clauses) else job_status == "success"]
    for clause in clauses:
        if clause.startswith("(") and clause.endswith(")"):
            clause = clause[1:-1].strip()
        if clause in status_checks:
            results.append(status_checks[clause])
            continue
        match = re.fullmatch(r"([a-z_][a-z_.]*)\s*(==|!=)\s*'([^']*)'", clause)
        if match is None:
            raise AssertionError(f"Unsupported retention guard clause: {clause!r}")
        key, operator, value = match.groups()
        actual = context.get(key, "")
        results.append(actual == value if operator == "==" else actual != value)
    return all(results)


class BrowserArtifactTests(unittest.TestCase):
    def test_website_image_matches_the_locked_browser_and_supplies_dependencies_without_network_apt(self):
        website = yaml.safe_load((ROOT / ".github/workflows/docs-site.yml").read_text())["jobs"]["website"]
        version = json.loads((ROOT / "website/package.json").read_text())["devDependencies"]["@playwright/test"]
        self.assertRegex(website["container"]["image"],
            rf"^mcr\.microsoft\.com/playwright:v{re.escape(version)}-noble@sha256:[0-9a-f]{{64}}$")
        self.assertEqual(website["container"]["options"], "--init --ipc=host")
        browser = next(step for step in website["steps"] if step.get("name") == "Install the pinned test browser and its OS prerequisites")
        self.assertEqual(browser["run"], "npm run browser:install")
        self.assertNotIn("if", browser)
        self.assertNotIn("continue-on-error", browser)

    def setUp(self) -> None:
        self.workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        self.steps = self.workflow["jobs"]["rust"]["steps"]
        self.producer = self.step(PRODUCER)
        self.upload = self.step(UPLOAD)

    def step(self, name: str) -> dict:
        matches = [step for step in self.steps if step.get("name") == name]
        self.assertEqual(len(matches), 1, name)
        return matches[0]

    def test_guard_references_the_unique_preceding_producer(self) -> None:
        self.assertEqual(self.producer.get("id"), "integration_lanes")
        self.assertEqual(sum(step.get("id") == "integration_lanes" for step in self.steps), 1)
        self.assertLess(self.steps.index(self.producer), self.steps.index(self.upload))
        self.assertIn("steps.integration_lanes.outcome", self.upload["if"])
        self.assertEqual(
            self.producer["env"]["CI_LANE_RENDERER"],
            "${{ needs.profile.outputs.renderer }}",
        )
        self.assertIn("tools/run_ci_lanes.py", self.producer["run"])
        self.assertIn("--renderer \"$CI_LANE_RENDERER\"", self.producer["run"])
        self.assertNotIn("continue-on-error", self.producer)

    def test_skipped_or_unreached_producer_never_uploads(self) -> None:
        for outcome in (None, "", "skipped"):
            for status in ("success", "failure", "cancelled"):
                with self.subTest(outcome=outcome, status=status):
                    self.assertFalse(retention_enabled(self.upload["if"], "true", outcome, status))

    def test_attempted_producer_retains_success_and_failure_diagnostics(self) -> None:
        for outcome in ("success", "failure", "cancelled"):
            for status in ("success", "failure", "cancelled"):
                with self.subTest(outcome=outcome, status=status):
                    self.assertTrue(retention_enabled(self.upload["if"], "true", outcome, status))

    def test_unselected_renderer_never_uploads(self) -> None:
        for renderer in ("false", ""):
            for outcome in (None, "", "skipped", "success", "failure", "cancelled"):
                with self.subTest(renderer=renderer, outcome=outcome):
                    self.assertFalse(retention_enabled(self.upload["if"], renderer, outcome, "failure"))

    def test_other_matrix_lanes_cannot_upload_browser_evidence(self) -> None:
        lanes = self.workflow["jobs"]["rust"]["strategy"]["matrix"]["lane"]
        self.assertIn("renderer-public", lanes)
        for lane in set(lanes) - {"renderer-public"}:
            with self.subTest(lane=lane):
                self.assertFalse(retention_enabled(self.upload["if"], "true", "success", lane=lane))
        self.assertTrue(self.upload["with"]["name"].endswith("-${{ matrix.lane }}"))

    def test_missing_evidence_is_still_fatal_after_execution(self) -> None:
        self.assertEqual(self.upload["with"]["if-no-files-found"], "error")
        self.assertNotIn("continue-on-error", self.upload)
        self.assertRegex(self.upload["uses"], r"^actions/upload-artifact@[0-9a-f]{40}$")
        self.assertEqual(self.upload["with"]["path"].splitlines(), [
            "${{ runner.temp }}/browser-boundary/build-receipt.json",
            "${{ runner.temp }}/browser-boundary/browser-receipt.json",
            "${{ runner.temp }}/browser-boundary/browser-application-receipt.json",
        ])

    def test_regressions_run_in_the_existing_lightweight_job(self) -> None:
        commands = "\n".join(step.get("run", "") for step in self.workflow["jobs"]["docs"]["steps"])
        self.assertIn("tools.tests.test_ci_browser_artifacts", commands)


if __name__ == "__main__":
    unittest.main()
