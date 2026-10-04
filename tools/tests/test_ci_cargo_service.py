"""Synthetic service contracts are failure controls, never timing evidence."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from tools import ci_cargo_service as service, ci_cargo_evaluate as evaluation
from tools.tests import test_ci_cargo_evaluate as fixtures


class ServiceContracts(unittest.TestCase):
    def fixture(self):
        reports, jobs, entries = [], [], []
        names = [invocation.name for recipe in evaluation.ci_cargo.RUST_RECIPES
                 for invocation in evaluation.ci_cargo.RECIPES[recipe]]
        for kind in service.KINDS:
            prefix = f"{service.PREFIX}-12-1-{kind}-closed-identity"
            entries.append({"id": len(entries) + 1, "key": prefix + "-linux-shape",
                            "ref": "refs/heads/development", "size_in_bytes": 1024})
            for state in service.STATES:
                reports.append({"identity": {"kind": kind, "experiment": "12-1", "prefix": prefix,
                    "source": "a" * 40, "ref": "refs/heads/development", "event": "push",
                    "configuration": "current" if kind == "baseline" else "ci-correctness",
                    "observedBuildIdentity": {"digest": "fixture"}}, "evaluation": {
                        "configuration": "current" if kind == "baseline" else "ci-correctness",
                        "passed": True, "cacheIdentity": {"digest": "fixture"},
                        "cacheBackend": "GitHub-cache-service-pinned-rust-cache", "samples": [{
                            "state": state, "passed": True, "cacheServiceExactHit": state != "cold",
                            "caseIdentityDigest": "b" * 64, "activeCases": 100,
                            "completedSuiteSeconds": 10, "builtArtifactRecords": 2,
                            "freshArtifactRecords": 8, "maximumChildRssKiB": 128,
                            "observations": [f"{state}/{name}/observation.json" for name in names]}]}})
                steps = [{"name": name, "status": "completed", "conclusion": "success",
                    "started_at": "2026-10-03T00:00:00Z", "completed_at": "2026-10-03T00:00:02Z"}
                    for name in ("Restore dependency cache", "Execute every reviewed Cargo invocation", "Post Restore dependency cache")]
                jobs.append({"id": len(jobs) + 1, "name": f"{state} ({kind}) / Cache sample ({kind} / {state})",
                    "run_id": 12, "run_attempt": 1, "head_sha": "a" * 40,
                    "status": "completed", "conclusion": "success", "steps": steps})
        return reports, jobs, entries

    def reconcile(self, reports, jobs, entries):
        return service.reconcile(reports, jobs, entries, source="a" * 40, run_id=12, attempt=1)

    def test_completed_six_samples_keep_combined_action_costs_and_baseline_decision(self):
        report = self.reconcile(*self.fixture())
        self.assertEqual(len(report["samples"]), 6)
        self.assertEqual(report["samplesPerCandidate"]["recipe"], {"cold": 1, "warm": 2})
        self.assertFalse(report["eligibleForAutomaticDefaultPromotion"])
        self.assertIsNone(report["networkTransferSeconds"])
        self.assertIsNone(report["separateExtractionSeconds"])
        self.assertEqual([s["saveActionSeconds"] for s in report["samples"]], [2, None, None] * 2)
        self.assertTrue(all(s["cacheBytes"] == 1024 and s["maximumChildRssKiB"] == 128 for s in report["samples"]))

    def test_missing_duplicate_or_different_suite_samples_fail(self):
        for mutation in ("missing", "duplicate", "case", "count", "invocation", "memory", "hit", "source", "identity"):
            reports, jobs, entries = self.fixture()
            if mutation == "missing": reports.pop()
            elif mutation == "duplicate": reports[-1] = copy.deepcopy(reports[0])
            elif mutation == "case": reports[-1]["evaluation"]["samples"][0]["caseIdentityDigest"] = "c" * 64
            elif mutation == "count": reports[-1]["evaluation"]["samples"][0]["activeCases"] = 99
            elif mutation == "invocation": reports[-1]["evaluation"]["samples"][0]["observations"].pop()
            elif mutation == "memory": reports[-1]["evaluation"]["samples"][0]["maximumChildRssKiB"] = None
            elif mutation == "hit": reports[-1]["evaluation"]["samples"][0]["cacheServiceExactHit"] = False
            elif mutation == "source": reports[-1]["identity"]["source"] = "d" * 40
            else: reports[-1]["evaluation"]["cacheIdentity"] = {"digest": "different"}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.reconcile(reports, jobs, entries)

    def test_pending_failed_wrong_attempt_or_ambiguous_jobs_cannot_qualify(self):
        for mutation in ("pending", "failed", "attempt", "source", "duplicate", "post-missing", "post-failed", "negative-time"):
            reports, jobs, entries = self.fixture()
            if mutation == "pending": jobs[-1]["status"] = "in_progress"
            elif mutation == "failed": jobs[-1]["conclusion"] = "failure"
            elif mutation == "attempt": jobs[-1]["run_attempt"] = 2
            elif mutation == "source": jobs[-1]["head_sha"] = "d" * 40
            elif mutation == "duplicate": jobs.append(copy.deepcopy(jobs[-1]))
            elif mutation == "post-missing": jobs[-1]["steps"].pop()
            elif mutation == "post-failed": jobs[-1]["steps"][-1]["conclusion"] = "failure"
            else: jobs[-1]["steps"][-1]["completed_at"] = "2026-10-02T00:00:00Z"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.reconcile(reports, jobs, entries)

    def test_absent_ambiguous_or_foreign_cache_entries_fail(self):
        for mutation in ("absent", "duplicate", "foreign-ref", "empty"):
            reports, jobs, entries = self.fixture()
            if mutation == "absent": entries.pop()
            elif mutation == "duplicate": entries.append(copy.deepcopy(entries[-1]))
            elif mutation == "foreign-ref": entries[-1]["ref"] = "refs/pull/1/merge"
            else: entries[-1]["size_in_bytes"] = 0
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.reconcile(reports, jobs, entries)

    def test_identity_only_accepts_its_own_development_push(self):
        env = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/development",
               "GITHUB_RUN_ID": "12", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40}
        with mock.patch.object(service.cache, "observe", return_value={"digest": "b" * 64}):
            baseline = service.identity("baseline", "12-1", Path.cwd(), env)
            recipe = service.identity("recipe", "12-1", Path.cwd(), env)
            self.assertNotEqual(baseline["prefix"], recipe["prefix"])
            self.assertTrue(recipe["prefix"].endswith("b" * 64))
            for changed in ({"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_EVENT_NAME": "workflow_dispatch"},
                            {"GITHUB_REF": "refs/heads/release"}, {"GITHUB_RUN_ATTEMPT": "2"}):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    service.identity("recipe", "12-1", Path.cwd(), {**env, **changed})

    def test_api_pagination_and_overall_deadline_are_finite(self):
        with mock.patch.object(service, "get_json", side_effect=[{"jobs": [{}] * 100}, {"jobs": [{}]}]) as call:
            self.assertEqual(len(service.pages("repos/a/b/jobs", "jobs", "private-token", time.monotonic() + 1)), 101)
            self.assertTrue(call.call_args.args[0].endswith("page=2"))
        with mock.patch.object(service, "MAX_PAGES", 1), mock.patch.object(service, "get_json", return_value={"jobs": [{}] * 100}):
            with self.assertRaisesRegex(ValueError, "page-limit"):
                service.pages("repos/a/b/jobs", "jobs", "private-token", time.monotonic() + 1)
        with mock.patch.object(service.urllib.request, "urlopen") as request:
            with self.assertRaisesRegex(ValueError, "overall-deadline"):
                service.get_json("repos/a/b", "private-token", time.monotonic() - 1)
            request.assert_not_called()

    def test_service_workflow_keeps_trusted_writers_and_existing_correctness_guards(self):
        from tools.ci_lane_inventory import workflow_model
        root = Path(__file__).resolve().parents[2]
        workflow = workflow_model((root / ".github/workflows/cargo-cache-service-evaluation.yml").read_text())
        self.assertEqual(workflow["on"]["push"]["branches"], ["development"])
        self.assertNotIn("pull_request", workflow["on"])
        self.assertNotIn("workflow_dispatch", workflow["on"])
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        jobs = workflow["jobs"]
        self.assertEqual(jobs["warm-1"]["needs"], "cold")
        self.assertEqual(jobs["warm-2"]["needs"], "warm-1")
        sample = workflow_model((root / ".github/workflows/cargo-cache-service-sample.yml").read_text())["jobs"]["sample"]
        self.assertEqual(sample["if"], "github.event_name == 'push' && github.ref == 'refs/heads/development'")
        step = next(s for s in sample["steps"] if s.get("name") == "Restore dependency cache")
        self.assertEqual(step["with"]["save-if"], "${{ github.event_name == 'push' && github.ref == 'refs/heads/development' && inputs.state == 'cold' }}")
        for key in ("cache-bin", "cache-workspace-crates", "cache-all-crates", "cache-on-failure"):
            self.assertIs(step["with"][key], False)
        self.assertEqual(step["with"]["cache-provider"], "github")
        self.assertEqual(step["with"]["prefix-key"], "${{ steps.identity.outputs.prefix }}")
        env = sample["env"]
        for profile in ("DEV", "TEST"):
            for guard in ("DEBUG_ASSERTIONS", "OVERFLOW_CHECKS"):
                self.assertEqual(env[f"CARGO_PROFILE_{profile}_{guard}"], "true")


class ServiceExecution(unittest.TestCase):
    def test_each_cold_service_sample_executes_every_recipe_and_existing_handoffs(self):
        fixture = fixtures.EvaluationTests()
        fixture.setUp()
        self.addCleanup(fixture.temporary.cleanup)
        original = evaluation.evaluate
        with mock.patch.object(evaluation, "evaluate", side_effect=lambda *args, **kwargs:
                               original(*args, **kwargs, service_state="cold", service_hit=False)):
            record, observed, custom, recipes = fixture.replay()
        selected = [i.name for recipe in evaluation.ci_cargo.RUST_RECIPES for i in evaluation.ci_cargo.RECIPES[recipe]]
        self.assertEqual([name for name, _, _ in observed], selected)
        self.assertEqual(custom, 1)
        self.assertEqual(recipes, 2)
        self.assertTrue(record["passed"])
        self.assertEqual(len(record["samples"]), 1)
        self.assertIsNone(record["samples"][0]["save"])
        self.assertEqual(record["cacheBackend"], "GitHub-cache-service-pinned-rust-cache")

    def test_false_warm_hits_and_accidental_cold_restore_fail_without_target_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            target = repo / "target"
            for state, hit in (("warm-1", False), ("cold", True), ("warm-2", True)):
                with self.subTest(state=state), self.assertRaises(ValueError):
                    evaluation.evaluate(repo, Path(directory) / "reports", "current", service_state=state, service_hit=hit)
                self.assertFalse(target.exists())
            target.mkdir()
            marker = target / "keep"
            marker.write_text("prior developer state")
            with self.assertRaises(ValueError):
                evaluation.evaluate(repo, Path(directory) / "reports", "current", service_state="cold", service_hit=False)
            self.assertEqual(marker.read_text(), "prior developer state")

    def test_warm_service_sample_executes_every_recipe_again(self):
        fixture = fixtures.EvaluationTests()
        fixture.setUp()
        self.addCleanup(fixture.temporary.cleanup)
        (fixture.repo / "target").mkdir()
        original = evaluation.evaluate
        with mock.patch.object(evaluation, "evaluate", side_effect=lambda *args, **kwargs:
                               original(*args, **kwargs, service_state="warm-1", service_hit=True)):
            record, observed, custom, recipes = fixture.replay()
        self.assertEqual(len(observed), sum(len(evaluation.ci_cargo.RECIPES[r]) for r in evaluation.ci_cargo.RUST_RECIPES))
        self.assertEqual((custom, recipes), (1, 2))
        self.assertTrue(record["samples"][0]["cacheServiceExactHit"])


if __name__ == "__main__":
    unittest.main()
