"""Lossless, ownership-local contracts; immutable pins never become baselines."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from tools import ci_contracts as contracts, ci_coverage as coverage
from tools import ci_lane_inventory as lanes, ci_suite_inventory as registry

ROOT = registry.ROOT
CHECKOUT_PIN = "a" * 40
PYTHON_PIN = "b" * 40


def save_workflow(path: Path, model: dict) -> None:
    text = yaml.safe_dump(model, sort_keys=False, width=120)
    # These are inert fixture identities. No upstream action is downloaded/run.
    text = "\n".join(line + " # immutable test fixture" if "uses:" in line and "@" in line else line
                     for line in text.splitlines()) + "\n"
    path.write_text(text)


def fixture(root: Path) -> None:
    (root / ".github/workflows").mkdir(parents=True)
    (root / "tools/tests").mkdir(parents=True)
    (root / ".gitignore").write_text("/target/\n__pycache__/\n")
    (root / "tools/owner.py").write_text("print('owned')\n")
    (root / "tools/ci_result.py").write_text("print('fixture aggregate')\n")
    for name in ("alpha", "beta"):
        (root / f"tools/tests/test_{name}.py").write_text(
            "import unittest\nclass Cases(unittest.TestCase):\n    def test_works(self):\n        self.assertTrue(True)\n")
    jobs = {job: {"runs-on": "ubuntu-24.04", "steps": [{"id": "verify", "run": "python3 tools/owner.py"}]}
            for job in sorted(registry.ALL_JOBS)}
    jobs["docs"]["steps"].insert(0, {"id": "checkout", "uses": "actions/checkout@" + CHECKOUT_PIN,
                                       "with": {"persist-credentials": False, "fetch-depth": 0}})
    jobs["rust"]["steps"].insert(0, {"id": "python", "uses": "actions/setup-python@" + PYTHON_PIN,
                                       "with": {"python-version": "3.13.5"}})
    jobs["result"] = {"name": "CI result", "if": "always()", "needs": sorted(registry.ALL_JOBS),
                      "runs-on": "ubuntu-24.04", "steps": [{"id": "result",
                      "run": "python3 tools/ci_result.py", "env": {"CI_JOB_RESULTS": "${{ toJSON(needs) }}"}}]}
    model = {"name": "CI", "on": {"pull_request": {"branches": ["development"], "paths": ["**", "!docs/**"]}},
             "permissions": {"contents": "read"}, "concurrency": {"group": "${{ github.ref }}", "cancel-in-progress": True},
             "defaults": {"run": {"shell": "bash", "working-directory": "."}}, "jobs": jobs}
    save_workflow(root / ".github/workflows/ci.yml", model)
    save_workflow(root / ".github/workflows/extra.yaml", {"on": {"workflow_dispatch": {}}, "jobs": {
        "build": {"runs-on": "ubuntu-24.04", "steps": [{"id": "build", "run": "python3 tools/owner.py"}]}}})
    actual = coverage.commands(root)
    data = {"schemaVersion": "latent.ci.commands.v1", "baselineRevision": "fixture-reviewed-baseline",
            "before": actual, "after": actual,
            "coverage": {key: {"after": key, "disposition": "unchanged", "reason": "Fixture baseline is retained."} for key in actual},
            "workflowIdentities": {path.relative_to(root).as_posix(): contracts.digest(path) for path in contracts.workflow_paths(root)},
            "delegatedOwners": coverage.delegated_owners(root, actual), "pythonCases": coverage.python_cases(root),
            "pythonTestModules": sorted(coverage.python_cases(root))}
    (root / "legacy.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    contracts.migrate(root, root / "legacy.json", root / contracts.DIRECTORY)


def git(root: Path, *args: str) -> str:
    environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                   "GIT_AUTHOR_NAME": "Contract fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                   "GIT_COMMITTER_NAME": "Contract fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                   "GIT_AUTHOR_DATE": "2001-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2001-01-01T00:00:00Z"}
    return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", *args],
                          cwd=root, env=environment, check=True, capture_output=True, text=True, timeout=20).stdout.strip()


def initialize_git(root: Path) -> str:
    git(root, "init", "--initial-branch=main")
    git(root, "add", ".")
    git(root, "commit", "-m", "reviewed base")
    return git(root, "rev-parse", "HEAD")


def commit(root: Path, message: str) -> str:
    git(root, "add", ".")
    git(root, "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def rewrite_fragment(root: Path, relative: str, mutate) -> None:
    path = root / contracts.DIRECTORY / relative
    value = contracts.read_json(path)
    mutate(value)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        fixture(self.root)

    def source(self, mutate, workflow="ci.yml"):
        path = self.root / ".github/workflows" / workflow
        model = lanes.workflow_model(path.read_text())
        mutate(model)
        save_workflow(path, model)

    def test_initial_assembly_is_lossless_and_deterministic(self):
        legacy = contracts.read_json(self.root / "legacy.json")
        expected = contracts.load(self.root)
        for field in ("before", "after", "coverage", "baselineRevision", "delegatedOwners", "pythonCases", "pythonTestModules"):
            self.assertEqual(expected[field], legacy[field], field)
        fragments = contracts.fragments(self.root)
        self.assertEqual(expected, contracts.assemble(dict(reversed(list(fragments.items())))))
        self.assertNotIn("workflowIdentities", expected)
        coverage.validate(self.root)

    def test_both_workflow_extensions_are_observed(self):
        self.assertEqual(set(contracts.load(self.root)["workflowContracts"]),
                         {".github/workflows/ci.yml", ".github/workflows/extra.yaml"})
        self.source(lambda model: model["jobs"]["build"]["steps"][0].update(run="true"), "extra.yaml")
        with self.assertRaisesRegex(ValueError, "changed-workflow-job"):
            coverage.validate(self.root)

    def test_pin_only_comments_and_yaml_formatting_do_not_change_contracts(self):
        path = self.root / ".github/workflows/ci.yml"
        before = {name: contracts.canonical(value) for name, value in contracts.fragments(self.root).items()}
        path.write_text("# reviewed upstream update\n\n" + path.read_text().replace(CHECKOUT_PIN, "c" * 40)
                        .replace(PYTHON_PIN, "d" * 40).replace("# immutable test fixture", "# reviewed fixture v2"))
        coverage.validate(self.root)
        self.assertEqual(before, {name: contracts.canonical(value) for name, value in contracts.fragments(self.root).items()})

    def test_mutable_pins_and_missing_version_comments_still_fail(self):
        path = self.root / ".github/workflows/ci.yml"
        original = path.read_text()
        for text in (original.replace(CHECKOUT_PIN, "main"), original.replace(" # immutable test fixture", "")):
            with self.subTest(text=text[:30]):
                path.write_text(text)
                with self.assertRaisesRegex(ValueError, "workflow-action-pin-policy"):
                    coverage.validate(self.root)
        path.write_text(original)

    def test_action_repository_path_and_inputs_are_not_revision_exceptions(self):
        original = (self.root / ".github/workflows/ci.yml").read_text()
        for target in ("other/checkout", "actions/checkout/subpath"):
            with self.subTest(target=target):
                (self.root / ".github/workflows/ci.yml").write_text(original.replace("actions/checkout@", target + "@"))
                with self.assertRaisesRegex(ValueError, "changed-workflow-job"):
                    coverage.validate(self.root)
        (self.root / ".github/workflows/ci.yml").write_text(original)
        self.source(lambda model: model["jobs"]["docs"]["steps"][0]["with"].update({"persist-credentials": True}))
        with self.assertRaises(ValueError):
            coverage.validate(self.root)

    def test_workflow_security_and_execution_fields_cannot_disappear(self):
        original = (self.root / ".github/workflows/ci.yml").read_text()
        changes = {
            "trigger": {"on": {"pull_request_target": {}}},
            "filters": {"on": {"pull_request": {"paths-ignore": ["tools/**"]}}},
            "permissions": {"permissions": {"contents": "write"}},
            "environment": {"env": {"VALIDATION_MODE": "relaxed"}},
            "shell inheritance": {"defaults": {"run": {"shell": "sh", "working-directory": "tools"}}},
            "concurrency": {"concurrency": {"group": "constant", "cancel-in-progress": False}},
            "unknown": {"future-execution-field": {"preserve": ["order", "and values"]}},
        }
        for label, change in changes.items():
            with self.subTest(field=label):
                (self.root / ".github/workflows/ci.yml").write_text(original)
                self.source(lambda model, c=change: model.update(c))
                with self.assertRaisesRegex(ValueError, "changed-workflow-policy"):
                    coverage.validate(self.root)

    def test_job_execution_fields_matrices_and_unknown_fields_are_preserved(self):
        original = (self.root / ".github/workflows/ci.yml").read_text()
        changes = {"if": "false", "needs": ["rust", "profile"], "runs-on": ["self-hosted"],
                   "strategy": {"fail-fast": False, "matrix": {"os": ["linux", "windows"], "include": [{"os": "other"}]}},
                   "permissions": {"contents": "write"}, "env": {"MODE": "other"},
                   "environment": {"name": "production"}, "defaults": {"run": {"shell": "sh", "working-directory": "sdk"}},
                   "continue-on-error": True, "timeout-minutes": 1, "concurrency": "different", "container": "image",
                   "services": {"db": {"image": "db", "ports": ["1:2"]}}, "outputs": {"ok": "true"},
                   "future-job-field": {"nested": [3, 2, 1]}}
        for key, value in changes.items():
            with self.subTest(field=key):
                (self.root / ".github/workflows/ci.yml").write_text(original)
                self.source(lambda model, k=key, v=value: model["jobs"]["docs"].update({k: v}))
                with self.assertRaisesRegex(ValueError, "changed-workflow-job"):
                    coverage.validate(self.root)

    def test_step_conditions_shells_environment_timeouts_and_failure_tolerance_are_preserved(self):
        original = (self.root / ".github/workflows/ci.yml").read_text()
        changes = {"if": "false", "shell": "sh", "working-directory": "sdk", "env": {"MODE": "other"},
                   "timeout-minutes": 1, "continue-on-error": True, "future-step-field": [2, 1]}
        for key, value in changes.items():
            with self.subTest(field=key):
                (self.root / ".github/workflows/ci.yml").write_text(original)
                self.source(lambda model, k=key, v=value: model["jobs"]["docs"]["steps"][-1].update({k: v}))
                with self.assertRaisesRegex(ValueError, "changed-workflow-job"):
                    coverage.validate(self.root)

    def test_reordering_prerequisites_is_not_fragment_sorting(self):
        self.source(lambda model: model["jobs"]["docs"]["steps"].reverse())
        with self.assertRaisesRegex(ValueError, "changed-workflow-job"):
            coverage.validate(self.root)

    def test_reusable_workflow_inputs_secrets_and_identity_are_preserved(self):
        model = {"on": {"workflow_dispatch": {}}, "jobs": {"call": {
            "uses": "owner/repo/.github/workflows/build.yml@" + CHECKOUT_PIN,
            "with": {"mode": "locked"}, "secrets": {"token": "${{ secrets.CI_TOKEN }}"},
            "permissions": {"contents": "read"}}}}
        normalized = lanes.structural_workflow(model)
        self.assertEqual(normalized["jobs"]["call"]["uses"], "owner/repo/.github/workflows/build.yml")
        changed = copy.deepcopy(model)
        changed["jobs"]["call"]["uses"] = changed["jobs"]["call"]["uses"].replace(CHECKOUT_PIN, PYTHON_PIN)
        self.assertEqual(normalized, lanes.structural_workflow(changed))
        for key, value in (("with", {"mode": "unlocked"}), ("secrets", "inherit"), ("permissions", {"contents": "write"})):
            changed = copy.deepcopy(model)
            changed["jobs"]["call"][key] = value
            self.assertNotEqual(normalized, lanes.structural_workflow(changed))

    def test_local_action_paths_are_not_treated_as_revisions(self):
        model = {"jobs": {"call": {"uses": "$/ .github/workflows/local.yml".replace(" ", "")}}}
        self.assertEqual(model, lanes.structural_workflow(model))
        model["jobs"]["call"]["uses"] = "./.github/workflows/other.yaml"
        self.assertEqual(model, lanes.structural_workflow(model))

    def test_docker_digest_exception_preserves_image_identity(self):
        model = {"jobs": {"job": {"steps": [{"uses": "docker://example/image@sha256:" + "a" * 64}]}}}
        before = lanes.structural_workflow(model)
        model["jobs"]["job"]["steps"][0]["uses"] = "docker://example/image@sha256:" + "b" * 64
        self.assertEqual(before, lanes.structural_workflow(model))
        model["jobs"]["job"]["steps"][0]["uses"] = "docker://other/image@sha256:" + "b" * 64
        self.assertNotEqual(before, lanes.structural_workflow(model))

    def test_required_job_removal_and_unregistered_workflows_fail(self):
        workflow = self.root / ".github/workflows/ci.yml"
        original = workflow.read_text()
        self.source(lambda model: model["jobs"].pop("rust"))
        with self.assertRaises(ValueError):
            coverage.validate(self.root)
        # Restore the removed job so the next failure proves independent
        # rejection of the unregistered workflow, not the earlier missing job.
        workflow.write_text(original)
        coverage.validate(self.root)
        shutil.copyfile(self.root / ".github/workflows/extra.yaml", self.root / ".github/workflows/unregistered.yml")
        with self.assertRaises(ValueError):
            coverage.validate(self.root)

    def test_conditional_or_incomplete_result_cannot_be_rebaselined(self):
        original = lanes.workflow_model((self.root / ".github/workflows/ci.yml").read_text())
        variants = [lambda gate: gate.update({"if": "success()"}), lambda gate: gate["needs"].pop(),
                    lambda gate: gate["needs"].append(gate["needs"][0]),
                    lambda gate: gate.update({"continue-on-error": True}),
                    lambda gate: gate["steps"][0].update({"continue-on-error": True}),
                    lambda gate: gate["steps"][0].update({"if": "false"}),
                    lambda gate: gate["steps"][0].update({"run": "python3 tools/ci_result.py || true"}),
                    lambda gate: gate["steps"][0]["env"].update({"CI_JOB_RESULTS": "{}"}),
                    lambda gate: gate["steps"][0].update({"env": None}),
                    lambda gate: gate["steps"][0].update({"env": []}),
                    lambda gate: gate["steps"][0].update({"if": {"unexpected": True}})]
        for index, mutate in enumerate(variants):
            with self.subTest(variant=index):
                model = copy.deepcopy(original)
                mutate(model["jobs"]["result"])
                self.assertTrue(lanes.result_contract_errors(model))
        self.assertEqual(lanes.result_contract_errors(original), ())

    def test_yaml_duplicate_keys_aliases_tags_and_ambiguous_steps_fail(self):
        samples = ["jobs: {}\njobs: {}\n", "on: push\n'on': pull_request\njobs: {}\n",
                   "jobs:\n  duplicate: {steps: []}\n  duplicate: {steps: []}\n",
                   "jobs: {x: {steps: [{id: same, run: one}, {id: same, run: two}]}}",
                   "jobs: {x: {steps: [{run: one, uses: 'actions/checkout@" + CHECKOUT_PIN + "'}]}}",
                   "jobs: {x: {steps: [{id: one, run: true}]}}",
                   "jobs: {x: {steps: &steps [{id: one, run: one}]}, y: {steps: *steps}}",
                   "jobs: {x: {<<: {steps: []}}}", "jobs: !!map {}", "jobs: [unterminated", "jobs: {}\n---\njobs: {}"]
        for sample in samples:
            with self.subTest(source=sample):
                with self.assertRaises((ValueError, yaml.YAMLError)):
                    lanes.workflow_model(sample)

    def test_boolean_integer_and_string_invocations_are_not_equal(self):
        path = self.root / ".github/workflows/ci.yml"
        original = path.read_text()
        for change in (lambda model: model["concurrency"].update({"cancel-in-progress": 1}),
                       lambda model: model["jobs"]["docs"]["steps"][0]["with"].update({"persist-credentials": 0}),
                       lambda model: model["jobs"]["docs"]["steps"][0]["with"].update({"fetch-depth": False}),
                       lambda model: model["jobs"]["docs"]["steps"][0]["with"].update({"fetch-depth": "0"})):
            with self.subTest(mutation=change):
                path.write_text(original)
                self.source(change)
                with self.assertRaisesRegex(ValueError, "changed-workflow"):
                    coverage.validate(self.root)

    def test_ambiguous_numeric_scalars_require_quotes_and_workflows_are_bounded(self):
        prefix = "jobs: {test: {steps: [{id: verify, run: 'true'}], timeout-minutes: "
        for value in ("012", "0x10", "1:20", ".inf", ".NaN"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "ambiguous-workflow-number"):
                    lanes.workflow_model(prefix + value + "}}")
                lanes.workflow_model(prefix + "'" + value + "'}}")
        from tools.validate_workflow_actions import MAX_WORKFLOW_BYTES
        with self.assertRaisesRegex(ValueError, "workflow-byte-limit"):
            lanes.workflow_model("#" * (MAX_WORKFLOW_BYTES + 1))

    def test_expected_workflow_definition_cannot_hide_malformed_execution(self):
        path = "workflows/ci.yml/jobs/docs.json"
        original = (self.root / contracts.DIRECTORY / path).read_text()
        for definition in ({"steps": "invalid"}, {"steps": [{"id": "verify", "run": True}]},
                           {"steps": [{"id": "verify", "run": "true"}, {"id": "verify", "run": "true"}]},
                           {"steps": [{"run": "true", "uses": "actions/checkout"}]}, {"uses": []}):
            with self.subTest(definition=definition):
                (self.root / contracts.DIRECTORY / path).write_text(original)
                rewrite_fragment(self.root, path, lambda value: value.update(definition=definition))
                with self.assertRaises(ValueError):
                    contracts.load(self.root)

    def test_setup_module_hooks_and_unittest_skip_flags_need_explicit_review(self):
        path = self.root / "tools/tests/test_alpha.py"
        original = path.read_text()
        variants = (original + "    def setUp(self):\n        self.skipTest('fixture')\n",
                    original + "    __unittest_skip__ = True\n",
                    original + "def setUpModule():\n    raise unittest.SkipTest('fixture')\n",
                    original + "def load_tests(loader, tests, pattern):\n    return unittest.TestSuite()\n",
                    original + "    def run(self, result=None):\n        return result\n")
        for text in variants:
            with self.subTest(source=text):
                path.write_text(text)
                with self.assertRaisesRegex(ValueError, "changed-python-test-execution-guard"):
                    coverage.validate(self.root)
                with self.assertRaisesRegex(ValueError, "explicit-python-skip-review"):
                    contracts.propose(self.root, "python", "tools/tests/test_alpha.py", None,
                                      self.root / "target/ci/proposals", "Explicit fixture proposal")

    def test_changed_skip_predicate_binding_and_unreachable_class_are_rejected(self):
        path = self.root / "tools/tests/test_alpha.py"
        original = path.read_text()
        path.write_text(original.replace("class Cases", "SKIP = False\n@unittest.skipIf(SKIP, 'fixture')\nclass Cases"))
        expected = contracts.python_expectations(self.root)["tools/tests/test_alpha.py"]
        rewrite_fragment(self.root, "python/test_alpha.py.json", lambda value: value.update(expected))
        coverage.validate(self.root)
        path.write_text(path.read_text().replace("SKIP = False", "SKIP = True"))
        with self.assertRaisesRegex(ValueError, "changed-python-test-execution-guard"):
            coverage.validate(self.root)
        path.write_text(original)
        expected = contracts.python_expectations(self.root)["tools/tests/test_alpha.py"]
        rewrite_fragment(self.root, "python/test_alpha.py.json", lambda value: value.update(expected))
        lines = original.splitlines()
        path.write_text(lines[0] + "\nif False:\n" + "\n".join("    " + line for line in lines[1:]) + "\n")
        with self.assertRaisesRegex(ValueError, "changed-python-test-execution-guard"):
            coverage.validate(self.root)

    def test_nested_proposal_symlink_cannot_escape_untracked_destination(self):
        output = self.root / "target/ci/proposals"
        output.mkdir(parents=True)
        (output / "python").symlink_to(self.root / "tools/tests", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink-contract-proposal-path"):
            contracts.propose(self.root, "python", "tools/tests/test_alpha.py", None, output, "Scoped fixture review")
        self.assertFalse((self.root / "tools/tests/test_alpha.py.json").exists())

    def test_on_key_and_yaml_boolean_values_do_not_alias(self):
        model = lanes.workflow_model("on: push\njobs: {test: {runs-on: linux, steps: [{id: run, run: 'true', continue-on-error: false}]}}")
        self.assertIn("on", model)
        self.assertNotIn(True, model)
        self.assertIs(model["jobs"]["test"]["steps"][0]["continue-on-error"], False)

    def test_malformed_duplicate_and_nonfinite_json_is_rejected(self):
        path = self.root / contracts.DIRECTORY / "python/test_alpha.py.json"
        original = path.read_text()
        for text in ('{"kind":"python","kind":"owner"}', original.replace('"cases": [', '"cases": [NaN,'), '{'):
            with self.subTest(text=text[:30]):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    contracts.load(self.root)
        path.write_text(original)

    def test_unknown_schema_fields_and_duplicate_python_expectations_fail(self):
        path = "python/test_alpha.py.json"
        original = (self.root / contracts.DIRECTORY / path).read_text()
        for mutate in (lambda value: value.update(schemaVersion="latent.ci.contracts.v999"),
                       lambda value: value.update(unmodeled=True), lambda value: value["cases"].append(value["cases"][0]),
                       lambda value: value.update(cases=[]), lambda value: value.update(guards={})):
            with self.subTest(mutation=mutate.__name__):
                (self.root / contracts.DIRECTORY / path).write_text(original)
                rewrite_fragment(self.root, path, mutate)
                with self.assertRaises(ValueError):
                    contracts.load(self.root)

    def test_missing_extra_and_misplaced_fragments_fail(self):
        directory = self.root / contracts.DIRECTORY
        path = directory / "workflows/ci.yml/jobs/docs.json"
        original = path.read_text()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing-or-extra-job"):
            contracts.load(self.root)
        path.write_text(original)
        for name in ("workflows/ci.yml/jobs/extra.json", "unknown.json", "scratch.txt"):
            with self.subTest(path=name):
                extra = directory / name
                extra.write_text(original)
                with self.assertRaises(ValueError):
                    contracts.load(self.root)
                extra.unlink()

    def test_duplicate_historical_obligation_and_missing_replacement_fail(self):
        records = copy.deepcopy(contracts.fragments(self.root))
        jobs = [value for value in records.values() if value["kind"] == "job" and value["before"]]
        key = next(iter(jobs[0]["before"]))
        jobs[1]["before"][key] = jobs[0]["before"][key]
        jobs[1]["coverage"][key] = jobs[0]["coverage"][key]
        with self.assertRaises(ValueError):
            contracts.assemble(records)
        records = copy.deepcopy(contracts.fragments(self.root))
        job = next(value for value in records.values() if value["kind"] == "job" and value["coverage"])
        next(iter(job["coverage"].values()))["after"] += "-removed"
        with self.assertRaisesRegex(ValueError, "removed-required-command"):
            contracts.assemble(records)

    def test_unsafe_and_absolute_owner_paths_fail(self):
        for path in ("../outside.py", "/tmp/outside.py", "tools/../../outside.py", "tools//owner.py", "tools\\owner.py", "tools/C:owner.py"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                contracts.record("owner", "reviewed", path=path, sha256="a" * 64, reviewBoundary="committed-fingerprint")

    def test_owner_fingerprints_cannot_be_replaced_by_unenforced_codeowners(self):
        rewrite_fragment(self.root, "owners/tools/owner.py.json", lambda value: value.update(reviewBoundary="CODEOWNERS"))
        with self.assertRaisesRegex(ValueError, "unenforced-owner-review-boundary"):
            contracts.load(self.root)

    def test_changed_owner_body_requires_its_own_reviewed_fingerprint(self):
        (self.root / "tools/owner.py").write_text("print('changed body')\n")
        with self.assertRaisesRegex(ValueError, "changed-command-owner-needs-review"):
            coverage.validate(self.root)

    def test_owner_parent_and_source_workflow_symlinks_are_rejected(self):
        path = self.root / "tools/owner.py"
        original = path.read_text()
        target = self.root / "outside.py"
        target.write_text(original)
        path.unlink()
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink-contract-path"):
            coverage.validate(self.root)
        path.unlink()
        path.write_text(original)
        workflow = self.root / ".github/workflows/extra.yaml"
        contents = workflow.read_text()
        workflow.unlink()
        target.write_text(contents)
        workflow.symlink_to(target)
        with self.assertRaises(ValueError):
            coverage.validate(self.root)

    def test_contract_directory_and_fragment_symlinks_are_rejected(self):
        path = self.root / contracts.DIRECTORY / "python/test_alpha.py.json"
        target = self.root / "outside.json"
        target.write_text(path.read_text())
        path.unlink()
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink-contract-path"):
            contracts.load(self.root)
        path.unlink()
        path.write_text(target.read_text())
        directory = self.root / contracts.DIRECTORY
        moved = self.root / "saved-contracts"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink-contract-path"):
            contracts.load(self.root)

    def test_source_parent_symlink_is_rejected_even_within_repository(self):
        directory = self.root / "tools/tests"
        moved = self.root / "saved-tests"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink-contract-path"):
            coverage.validate(self.root)

    def test_missing_renamed_added_empty_and_duplicate_python_cases_fail(self):
        path = self.root / "tools/tests/test_alpha.py"
        original = path.read_text()
        variants = [original.replace("test_works", "test_renamed"), "import unittest\n",
                    original + "    def test_new(self):\n        pass\n",
                    original + "    def test_works(self):\n        pass\n"]
        for source in variants:
            with self.subTest(source=source):
                path.write_text(source)
                with self.assertRaises(ValueError):
                    coverage.validate(self.root)
        path.unlink()
        with self.assertRaises(ValueError):
            coverage.validate(self.root)

    def test_unregistered_python_modules_fail_without_a_central_index(self):
        shutil.copyfile(self.root / "tools/tests/test_alpha.py", self.root / "tools/tests/test_unregistered.py")
        with self.assertRaisesRegex(ValueError, "unregistered-python-case"):
            coverage.validate(self.root)

    def test_new_skips_expected_failures_and_class_guards_fail(self):
        path = self.root / "tools/tests/test_alpha.py"
        original = path.read_text()
        variants = [original.replace("    def test_works", "    @unittest.skip('review needed')\n    def test_works"),
                    original.replace("class Cases", "@unittest.skipIf(True, 'review needed')\nclass Cases"),
                    original.replace("    def test_works", "    @unittest.expectedFailure\n    def test_works"),
                    original.replace("self.assertTrue(True)", "self.skipTest('review needed')"),
                    original.replace("unittest.TestCase", "object")]
        for source in variants:
            with self.subTest(source=source):
                path.write_text(source)
                with self.assertRaisesRegex(ValueError, "changed-python-test-execution-guard"):
                    coverage.validate(self.root)

    def test_initial_migration_refuses_stale_workflow_owner_and_test_snapshots(self):
        source = self.root / ".github/workflows/ci.yml"
        original = source.read_text()
        for path, contents in ((source, original.replace(CHECKOUT_PIN, "c" * 40)),
                               (self.root / "tools/owner.py", "print('different')\n"),
                               (self.root / "tools/tests/test_alpha.py", "class Cases:\n    def test_changed(self): pass\n")):
            before = path.read_text()
            path.write_text(contents)
            output = self.root / "target/proposed-migration"
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, "stale-migration"):
                contracts.migrate(self.root, self.root / "legacy.json", output)
            self.assertFalse(output.exists())
            path.write_text(before)

    def test_proposals_are_scoped_and_never_write_expected_records(self):
        path = self.root / "tools/owner.py"
        path.write_text("print('reviewed change')\n")
        before = contracts.fragments(self.root)
        output = self.root / "target/ci/proposals"
        proposed = contracts.propose(self.root, "owner", "tools/owner.py", None, output, "Reviewed behavioral change with regression coverage.")
        self.assertEqual(contracts.read_json(proposed)["sha256"], contracts.digest(path))
        self.assertEqual(before, contracts.fragments(self.root))
        with self.assertRaisesRegex(ValueError, "changed-command-owner-needs-review"):
            coverage.validate(self.root)
        with self.assertRaisesRegex(ValueError, "refuse-overwrite"):
            contracts.propose(self.root, "owner", "tools/owner.py", None, output, "Still explicit.")

    def test_proposal_cannot_bless_removed_commands_cases_or_new_skips(self):
        output = self.root / "target/ci/proposals"
        self.source(lambda model: model["jobs"]["docs"]["steps"].pop())
        with self.assertRaisesRegex(ValueError, "proposal-would-remove-required-command"):
            contracts.propose(self.root, "job", ".github/workflows/ci.yml", "docs", output, "Review requested.")
        path = self.root / "tools/tests/test_alpha.py"
        original = path.read_text()
        path.write_text(original.replace("test_works", "test_renamed"))
        with self.assertRaisesRegex(ValueError, "proposal-would-remove-or-rename"):
            contracts.propose(self.root, "python", "tools/tests/test_alpha.py", None, output, "Review requested.")
        path.write_text(original.replace("self.assertTrue(True)", "self.skipTest('new skip')"))
        with self.assertRaisesRegex(ValueError, "proposal-needs-explicit-python-skip-review"):
            contracts.propose(self.root, "python", "tools/tests/test_alpha.py", None, output, "Review requested.")
        self.assertFalse(output.exists())

    def test_unchanged_historical_replacement_needs_explicit_review(self):
        self.source(lambda model: model["jobs"]["docs"]["steps"][-1].update(run="python3 tools/owner.py --different"))
        with self.assertRaisesRegex(ValueError, "proposal-needs-explicit-replacement-review"):
            contracts.propose(self.root, "job", ".github/workflows/ci.yml", "docs", self.root / "target/ci/proposals", "Review requested.")

    def test_proposal_output_cannot_overwrite_source_or_traverse_symlinks(self):
        with self.assertRaisesRegex(ValueError, "proposal-output-must-be-untracked"):
            contracts.propose(self.root, "owner", "tools/owner.py", None, self.root / contracts.DIRECTORY, "Review requested.")
        (self.root / "target").symlink_to(self.root / "tools", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink-contract-path"):
            contracts.propose(self.root, "owner", "tools/owner.py", None, self.root / "target/ci/proposals", "Review requested.")

    def test_pin_branches_merge_and_validate_without_inventory_refresh(self):
        base = initialize_git(self.root)
        workflow = self.root / ".github/workflows/ci.yml"
        contract_tree = git(self.root, "rev-parse", "HEAD:" + contracts.DIRECTORY)
        git(self.root, "checkout", "-b", "pin-checkout", base)
        workflow.write_text(workflow.read_text().replace(CHECKOUT_PIN, "c" * 40))
        commit(self.root, "review checkout revision")
        git(self.root, "checkout", "-b", "pin-python", base)
        workflow.write_text(workflow.read_text().replace(PYTHON_PIN, "d" * 40))
        other = commit(self.root, "review Python action revision")
        git(self.root, "checkout", "pin-checkout")
        git(self.root, "merge", "--no-ff", "-m", "combine independent reviewed pins", other)
        self.assertEqual(git(self.root, "rev-parse", "HEAD:" + contracts.DIRECTORY), contract_tree)
        self.assertIn("c" * 40, workflow.read_text())
        self.assertIn("d" * 40, workflow.read_text())
        coverage.validate(self.root)
        receipt = coverage.write_receipt(self.root, Path("target/ci/observed-inventory.json"), "passed")
        self.assertEqual(receipt["testedCommit"], git(self.root, "rev-parse", "HEAD"))
        self.assertEqual(len(git(self.root, "rev-list", "--parents", "-n", "1", "HEAD").split()), 3)
        self.assertEqual(receipt["paths"][".github/workflows/ci.yml"]["sha256"], contracts.digest(workflow))
        self.assertFalse(receipt["workingTreeModified"])
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_independent_jobs_and_python_modules_merge_with_only_local_contracts(self):
        base = initialize_git(self.root)
        for branch, job, module in (("first", "docs", "alpha"), ("second", "rust", "beta")):
            git(self.root, "checkout", "-b", branch, base)
            self.source(lambda model, j=job: model["jobs"][j]["steps"][-1].update(run="python3 tools/owner.py --" + j))
            definition = contracts.observed_workflows(self.root)[".github/workflows/ci.yml"]["jobs"][job]
            def reviewed(record):
                record["definition"] = definition
                record["reviewReason"] = "Review this independently changed command."
                for row in record["coverage"].values():
                    row.update(disposition="extended", reason="Preserve the original owner with additional reviewed arguments.")
            rewrite_fragment(self.root, f"workflows/ci.yml/jobs/{job}.json", reviewed)
            path = self.root / f"tools/tests/test_{module}.py"
            path.write_text(path.read_text() + "    def test_additional(self):\n        self.assertTrue(True)\n")
            expectation = contracts.python_expectations(self.root)[path.relative_to(self.root).as_posix()]
            rewrite_fragment(self.root, f"python/test_{module}.py.json", lambda value: value.update(expectation))
            coverage.validate(self.root)
            commit(self.root, "review " + branch)
        git(self.root, "checkout", "first")
        git(self.root, "merge", "--no-ff", "-m", "combine independent contracts", "second")
        coverage.validate(self.root)
        changed = set(git(self.root, "diff", "--name-only", base, "HEAD").splitlines())
        self.assertEqual(changed, {".github/workflows/ci.yml", "tools/tests/test_alpha.py", "tools/tests/test_beta.py",
            contracts.DIRECTORY + "/workflows/ci.yml/jobs/docs.json", contracts.DIRECTORY + "/workflows/ci.yml/jobs/rust.json",
            contracts.DIRECTORY + "/python/test_alpha.py.json", contracts.DIRECTORY + "/python/test_beta.py.json"})

    def test_receipts_use_actual_checkout_not_event_sha_and_never_expose_environment(self):
        head = initialize_git(self.root)
        # Deliberate dummy values are source fixtures, not real credentials.
        dummy = "NOT_A_SECRET_ENVIRONMENT_FIXTURE_732"
        self.source(lambda model: model.update(env={"PRIVATE_VALUE": dummy}))
        with patch.dict(os.environ, {"GITHUB_SHA": "f" * 40, "PRIVATE_VALUE": dummy}):
            receipt = coverage.write_receipt(self.root, Path("target/ci/observed-inventory.json"), "failed")
        self.assertEqual(receipt["testedCommit"], head)
        self.assertTrue(receipt["workingTreeModified"])
        self.assertNotIn(dummy, json.dumps(receipt))
        self.assertNotIn("python3 tools/owner.py", json.dumps(receipt))
        self.assertEqual(receipt["validationStatus"], "failed")

    def test_cli_retains_failure_receipt_for_malformed_source(self):
        head = initialize_git(self.root)
        workflow = self.root / ".github/workflows/ci.yml"
        workflow.write_text("jobs: [malformed\n")
        validate = coverage.validate
        with patch.object(registry, "ROOT", self.root), patch.object(coverage, "validate", side_effect=lambda: validate(self.root)), \
                patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(coverage.main([]), 1)
        receipt = contracts.read_json(self.root / "target/ci/observed-inventory.json")
        self.assertEqual(receipt["testedCommit"], head)
        self.assertEqual(receipt["validationStatus"], "failed")
        self.assertIn("workflow-observation", receipt["observationErrors"])
        self.assertEqual(receipt["paths"][".github/workflows/ci.yml"]["sha256"], contracts.digest(workflow))
        self.assertNotIn("malformed", json.dumps(receipt))

    def test_validation_is_read_only_and_receipt_cannot_overwrite_tracked_contract(self):
        initialize_git(self.root)
        coverage.validate(self.root)
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        with self.assertRaisesRegex(ValueError, "receipt-must-be-under-target-ci"):
            coverage.write_receipt(self.root, Path(contracts.DIRECTORY + "/python/test_alpha.py.json"), "passed")
        (self.root / "target").symlink_to(self.root / "tools", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink-contract-path"):
            coverage.write_receipt(self.root, Path("target/ci/receipt.json"), "passed")


class RepositoryMigrationTests(unittest.TestCase):
    def test_every_historical_obligation_and_current_expectation_is_accounted_for(self):
        legacy = contracts.read_json(ROOT / "tools/ci/history/commands-v1.json")
        data = contracts.load(ROOT)
        for field in ("before", "coverage", "baselineRevision"):
            self.assertEqual(data[field], legacy[field], field)
        self.assertEqual(len(legacy["before"]), 88)
        self.assertEqual(len(legacy["after"]), 208)
        self.assertEqual(len(legacy["delegatedOwners"]), 124)
        self.assertEqual(len(legacy["pythonTestModules"]), 260)
        self.assertEqual(sum(map(len, legacy["pythonCases"].values())), 2675)
        reviewed_extension = ".github/workflows/ci.yml:docs:Validate documentation and profile selection"
        for key, value in legacy["after"].items():
            self.assertIn(key, data["after"])
            if key != reviewed_extension:
                self.assertEqual(data["after"][key], value, key)
            else:
                self.assertEqual({k: v for k, v in data["after"][key].items() if k != "run"},
                                 {k: v for k, v in value.items() if k != "run"})
                old_modules = {word for word in value["run"].split() if word.startswith("tools.tests.")}
                self.assertTrue(old_modules <= set(data["after"][key]["run"].split()))
        self.assertTrue(set(legacy["delegatedOwners"]) <= set(data["delegatedOwners"]))
        for name, cases in legacy["pythonCases"].items():
            self.assertTrue(set(cases) <= set(data["pythonCases"][name]), name)
        # Historical obligations are a floor, not a ban on reviewed new lanes.
        self.assertTrue(set(legacy["workflowIdentities"]) <= set(data["workflowContracts"]))
        self.assertEqual(set(data["workflowContracts"]),
                         {path.relative_to(ROOT).as_posix() for path in contracts.workflow_paths(ROOT)})
        self.assertFalse((ROOT / "tools/ci/commands.json").exists())

    def test_workflow_and_shared_contract_edits_still_select_full_ci(self):
        from tools.ci_profile import classify_paths
        for path in (".github/workflows/ci.yml", "tools/ci/contracts/python/test_ci_contracts.py.json", "tools/ci_contracts.py"):
            with self.subTest(path=path):
                self.assertEqual(classify_paths([path]).profile, "full")

    def test_receipt_is_uploaded_unconditionally_and_protected_result_is_unchanged(self):
        model = lanes.workflow_model((ROOT / ".github/workflows/ci.yml").read_text())
        self.assertEqual(lanes.result_contract_errors(model), ())
        steps = model["jobs"]["docs"]["steps"]
        validation = next(index for index, step in enumerate(steps) if step.get("id") == "contract_coverage")
        tests = next(index for index, step in enumerate(steps) if step.get("name") == "Validate documentation and profile selection")
        self.assertLess(validation, tests)
        upload = next(step for step in steps if step.get("id") == "contract_evidence")
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["path"], "target/ci/observed-inventory.json")
