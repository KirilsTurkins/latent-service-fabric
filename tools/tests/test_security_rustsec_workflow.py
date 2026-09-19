from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import yaml

from tools.ci_profile import classify_paths
from tools.security_common import ROOT
from tools.security_scope import classify, select, validate_results
from tools.validate_workflow_actions import validate_repository


class SecurityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = yaml.load((ROOT / ".github/workflows/security-baseline.yml").read_text(), Loader=yaml.BaseLoader)
        cls.rustsec = yaml.load((ROOT / ".github/workflows/security-rustsec.yml").read_text(), Loader=yaml.BaseLoader)

    def test_one_coordinator_reuses_rustsec_and_covers_both_maintained_branches(self) -> None:
        self.assertEqual(set(self.baseline["on"]), {"pull_request", "push", "schedule", "workflow_dispatch"})
        self.assertEqual(set(self.rustsec["on"]), {"workflow_call"})
        for event in ("pull_request", "push"):
            self.assertEqual(self.baseline["on"][event]["branches"], ["development", "release"])
            self.assertNotIn("paths", self.baseline["on"][event])
        self.assertEqual(self.baseline["jobs"]["rustsec"]["uses"], "./.github/workflows/security-rustsec.yml")
        with patch("tools.security_scope.changed_paths", side_effect=AssertionError("must not need a changed lock")):
            for event in ("schedule", "workflow_dispatch"):
                selection = select(event, {}, ROOT, "a" * 40)
                self.assertEqual(selection["refs"], ["development", "release"])
                self.assertTrue(all(selection[name] for name in ("rustsec", "dependencies", "static", "selftest")))

    def test_docs_and_svg_only_keep_existing_ci_profile_and_only_secret_job(self) -> None:
        paths = ["docs/development/security-baseline.md", "README.md", "docs/assets/architecture.svg"]
        self.assertEqual(classify_paths(paths).profile, "docs")
        self.assertFalse(any(classify(paths).values()))
        self.assertNotIn("if", self.baseline["jobs"]["secrets"])
        self.assertEqual(self.baseline["jobs"]["result"]["if"], "always()")

    def test_sensitive_paths_select_their_analyses(self) -> None:
        self.assertTrue(classify(["Cargo.lock"])["rustsec"])
        self.assertTrue(classify(["sdk/rust/Cargo.toml"])["rustsec"])
        self.assertTrue(classify(["sdk/typescript-client/package-lock.json"])["dependencies"])
        self.assertTrue(classify(["sdk/go/go.mod"])["dependencies"])
        self.assertTrue(classify(["sdk/dotnet/Latent.Sdk/Latent.Sdk.csproj"])["dependencies"])
        self.assertTrue(classify(["apps/latentd/src/main.rs"])["static"])
        self.assertTrue(classify([".github/workflows/ci.yml"])["selftest"])
        self.assertTrue(all(classify([".github/security/exceptions.json"]).values()))
        self.assertTrue(all(classify(["tools/toolchain.toml"]).values()))
        self.assertTrue(all(classify(["tools/validate_workflow_actions.py"]).values()))

    def test_fork_pull_requests_have_no_privileged_token_cache_or_input_execution(self) -> None:
        for workflow in (self.baseline, self.rustsec):
            self.assertEqual(workflow["permissions"], {"contents": "read"})
            self.assertNotIn("pull_request_target", workflow["on"])
            for job in workflow["jobs"].values():
                self.assertNotIn("permissions", job)
                self.assertNotIn("secrets", job)
                if "uses" not in job:
                    self.assertLessEqual(int(job["timeout-minutes"]), 8)
                for step in job.get("steps", []):
                    self.assertNotIn("continue-on-error", step)
                    if step.get("uses", "").startswith("actions/checkout@"):
                        self.assertEqual(step["with"]["persist-credentials"], "false")
                    serialized = json.dumps(step)
                    for forbidden in ("pull_request_target", "secrets.", "upload-artifact", "rust-cache", "actions/cache",
                                      "cargo build", "cargo test", "cargo install", "npm install", "npm ci", "python3 source/"):
                        self.assertNotIn(forbidden, serialized)

    def test_policy_checks_immutable_actions_including_reused_workflow(self) -> None:
        references, workflows, failures = validate_repository(ROOT)
        self.assertGreater(references, 0)
        self.assertGreaterEqual(workflows, 7)
        self.assertEqual(failures, [])

    def test_exact_selected_result_cannot_pass_after_failure_or_cancellation(self) -> None:
        for enabled in (True, False):
            outputs = dict.fromkeys(("rustsec", "dependencies", "static", "selftest"), str(enabled).lower())
            results = {"scope": {"result": "success", "outputs": outputs}, "secrets": {"result": "success"}}
            results.update({name: {"result": "success" if enabled else "skipped"}
                            for name in ("rustsec", "dependencies", "static", "self-test")})
            self.assertTrue(validate_results(results))
            for job in results:
                for failure in ("failure", "cancelled", "unknown"):
                    mutated = copy.deepcopy(results)
                    mutated[job]["result"] = failure
                    self.assertFalse(validate_results(mutated))
            results["scope"]["outputs"]["rustsec"] = "unknown"
            self.assertFalse(validate_results(results))

    def test_actual_aggregate_script_checks_the_same_results(self) -> None:
        script = self.baseline["jobs"]["result"]["steps"][0]["run"]
        program = script.split("\n", 1)[1].rsplit("\nPY", 1)[0]
        results = {"scope": {"result": "success", "outputs": dict.fromkeys(
            ("rustsec", "dependencies", "static", "selftest"), "false")}, "secrets": {"result": "success"}}
        results.update({name: {"result": "skipped"} for name in ("rustsec", "dependencies", "static", "self-test")})
        for expected in (0, 1):
            if expected:
                results["secrets"]["result"] = "skipped"
            process = subprocess.run([sys.executable, "-c", program],
                                     env={**os.environ, "SECURITY_RESULTS": json.dumps(results)},
                                     capture_output=True, timeout=10, check=False)
            self.assertEqual(process.returncode, expected)

    def test_pr_uses_complete_git_diff_not_api_first_page(self) -> None:
        event = {"pull_request": {"base": {"sha": "b" * 40}, "head": {"repo": {"fork": True}}}}
        with patch("tools.security_scope.changed_paths", return_value=["docs/README.md", "Cargo.lock"]) as changed:
            selection = select("pull_request", event, ROOT, "a" * 40)
        changed.assert_called_once_with(ROOT, "b" * 40, "a" * 40)
        self.assertEqual(selection["refs"], ["a" * 40])
        self.assertTrue(selection["rustsec"])


if __name__ == "__main__":
    unittest.main()
