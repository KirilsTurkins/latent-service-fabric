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
        for field in ("after", "delegatedOwners", "pythonCases", "pythonTestModules"):
            self.assertEqual(expected[field], legacy[field], field)
        fragments = contracts.fragments(self.root)
        self.assertEqual(expected, contracts.assemble(dict(reversed(list(fragments.items())))))
        self.assertNotIn("workflowIdentities", expected)
        # Fixed expected output for the small inert migration fixture: the old
        # map is validated during migration but is not a current job contract.
        self.assertEqual(expected["workflowContracts"][".github/workflows/extra.yaml"]["jobs"]["build"],
                         {"runs-on": "ubuntu-24.04", "steps": [{"id": "build", "run": "python3 tools/owner.py"}]})
        coverage.validate(self.root)
        # Physical owner banks preserve the exact old virtual identity model.
        bank_path = self.root / contracts.DIRECTORY / "owner-banks/source.json"
        bank_path.parent.mkdir()
        selected = [name for name, row in fragments.items() if row["kind"] == "owner"]
        leaves = [fragments[name] for name in selected]
        self.assertTrue(leaves)
        bank = {"schemaVersion": contracts.OWNER_BANK_SCHEMA, "records": leaves}
        for name in selected:
            (self.root / contracts.DIRECTORY / name).unlink()
        # The fixture's now-empty owners/tools chain no longer has a file.
        (self.root / contracts.DIRECTORY / "owners/tools").rmdir()
        (self.root / contracts.DIRECTORY / "owners").rmdir()
        bank_path.write_text(json.dumps(bank))
        self.assertEqual(contracts.fragments(self.root), fragments)
        self.assertEqual(list(contracts.fragments(self.root)), list(fragments))
        self.assertEqual(contracts.load(self.root), expected)
        variants = [dict(bank, extra=True), dict(bank, schemaVersion="unknown"), dict(bank, records=[]),
                    dict(bank, records={}), dict(bank, records=[None]),
                    dict(bank, records=[leaves[0], dict(leaves[0], kind="python")]),
                    dict(bank, records=[dict(leaves[0], sha256="invalid")]),
                    dict(bank, records=[leaves[0]] * (contracts.MAX_BANK_OWNERS + 1)),
                    dict(bank, records=[leaves[0], leaves[0]])]
        for malformed in variants:
            bank_path.write_text(json.dumps(malformed))
            with self.subTest(bank=malformed), self.assertRaises(ValueError):
                contracts.fragments(self.root)
        for nonobject in ([], None, 0, "owner"):
            bank_path.write_text(json.dumps(nonobject))
            with self.subTest(nonobject=nonobject), self.assertRaisesRegex(ValueError, "contract-object-required"):
                contracts.fragments(self.root)
        bank_path.write_text(json.dumps(bank))
        with patch.object(contracts, "MAX_FRAGMENTS", len(fragments) - 1):
            with self.assertRaisesRegex(ValueError, "contract-fragment-limit"):
                contracts.fragments(self.root)
        with patch.object(registry, "MAX_BYTES", bank_path.stat().st_size - 1):
            with self.assertRaisesRegex(ValueError, "contract-byte-limit"):
                contracts.fragments(self.root)
        # A bank and standalone leaf may not claim the same identity.
        duplicate = self.root / contracts.DIRECTORY / selected[0]
        duplicate.parent.mkdir(parents=True)
        duplicate.write_text(json.dumps(leaves[0]))
        with self.assertRaisesRegex(ValueError, "duplicate-contract-identity"):
            contracts.fragments(self.root)
        duplicate.unlink()
        duplicate.parent.rmdir(); duplicate.parent.parent.rmdir()
        # The physical path remains closed independently of record semantics.
        wrong = bank_path.with_name("Bad.json")
        bank_path.rename(wrong)
        with self.assertRaisesRegex(ValueError, "owner-bank-fields-or-path"):
            contracts.fragments(self.root)
        wrong.rename(bank_path)
        self.assertEqual(contracts.load(self.root), expected)
        coverage.validate(self.root)

    def test_shared_python_storage_preserves_order_values_and_semantic_hashes(self):
        original = contracts.fragments(self.root)["python/test_alpha.py.json"]
        guard = original["guards"][original["cases"][0]]
        guard = {key: copy.deepcopy(guard[key]) for key in reversed(guard)}
        guard["decorators"] = ["second(\u00e9)", "first(\u03b2)"]
        value = copy.deepcopy(original)
        value["cases"] = ["Cases.test_first", "Cases.test_second"]
        value["guards"] = {case: copy.deepcopy(guard) for case in reversed(value["cases"])}
        stored = contracts.shared_python_record(value)
        self.assertEqual(len(stored["guardDefinitions"]), 1)
        restored = contracts.semantic_record(stored)
        self.assertEqual(restored, value)
        self.assertEqual(list(restored), list(value))
        self.assertEqual(list(restored["guards"]), list(value["guards"]))
        for case in value["cases"]:
            self.assertEqual(list(restored["guards"][case]), list(value["guards"][case]))
        self.assertEqual(coverage._value_digest(restored), coverage._value_digest(value))
        self.assertEqual(contracts.fragment_path(stored), contracts.fragment_path(value))
        self.assertEqual(contracts.shared_python_record(stored), stored)
        destination = self.root / "readable-shared-proposal"
        contracts.write_records(destination, [stored])
        written = destination / contracts.fragment_path(stored)
        physical = contracts.read_json(written)
        self.assertEqual(physical, stored)
        self.assertEqual(list(physical), list(stored))
        self.assertEqual(list(physical["guards"]), list(stored["guards"]))
        self.assertEqual(list(next(iter(physical["guardDefinitions"].values()))), list(guard))
        self.assertEqual(contracts.semantic_record(physical), value)
        lines = written.read_text(encoding="utf-8").splitlines()
        for case, identity in stored["guards"].items():
            key = json.dumps(case, ensure_ascii=False) + ":"
            index = next(index for index, line in enumerate(lines) if line.strip() == key)
            self.assertEqual(json.loads(lines[index + 1].strip().rstrip(",")), identity)
        self.assertNotIn(b"\r", written.read_bytes())

    def test_shared_storage_is_normalized_before_assembly_and_validation(self):
        before = contracts.fragments(self.root)
        expected = contracts.load(self.root)
        for relative, value in before.items():
            if value["kind"] == "python":
                stored = contracts.shared_python_record(value)
                path = self.root / contracts.DIRECTORY / relative
                path.write_text(json.dumps(stored, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        self.assertEqual(contracts.fragments(self.root), before)
        self.assertEqual(contracts.load(self.root), expected)
        physical = {relative: contracts.read_json(self.root / contracts.DIRECTORY / relative) for relative in before}
        self.assertEqual(contracts.assemble(physical), expected)
        coverage.validate(self.root)

    def test_shared_storage_rejects_unknown_schemas_kinds_and_closed_fields(self):
        value = contracts.fragments(self.root)["python/test_alpha.py.json"]
        stored = contracts.shared_python_record(value)
        variants = [dict(stored, schemaVersion="latent.ci.contracts.v3"),
                    dict(stored, kind="owner"), dict(stored, extra="field"),
                    {key: item for key, item in stored.items() if key != "guardDefinitions"},
                    dict(value, guardDefinitions={})]
        for malformed in variants:
            with self.subTest(fields=list(malformed)), self.assertRaises(ValueError):
                contracts.fragment_path(malformed)
        with self.assertRaisesRegex(ValueError, "shared-storage-requires-python"):
            contracts.shared_python_record(contracts.fragments(self.root)["owners/tools/owner.py.json"])

    def test_shared_storage_requires_exact_case_reference_and_definition_coverage(self):
        stored = contracts.shared_python_record(contracts.fragments(self.root)["python/test_alpha.py.json"])
        case, identity = next(iter(stored["guards"].items()))
        variants = [dict(stored, guards={}), dict(stored, guards={"Other.test_case": identity}),
                    dict(stored, cases=[case, case]), dict(stored, cases=[3]),
                    dict(stored, guards={case: "f" * 64}), dict(stored, guards={case: None}),
                    dict(stored, guards={case: {"ref": identity}}), dict(stored, guardDefinitions={}),
                    dict(stored, guardDefinitions=[])]
        extra = copy.deepcopy(stored)
        other = copy.deepcopy(extra["guardDefinitions"][identity])
        other["decorators"].append("reviewed_other_guard")
        extra["guardDefinitions"][hashlib.sha256(contracts.canonical(other).encode()).hexdigest()] = other
        variants.append(extra)
        for malformed in variants:
            with self.subTest(value=malformed), self.assertRaises(ValueError):
                contracts.fragment_path(malformed)

    def test_shared_storage_rejects_digest_mismatches_duplicate_and_recursive_definitions(self):
        stored = contracts.shared_python_record(contracts.fragments(self.root)["python/test_alpha.py.json"])
        case, identity = next(iter(stored["guards"].items()))
        for guard in ({"ref": identity}, dict(stored["guardDefinitions"][identity], extra=[]),
                      dict(stored["guardDefinitions"][identity], bases=[{"ref": identity}]),
                      dict(stored["guardDefinitions"][identity], skipSites=[True]),
                      dict(stored["guardDefinitions"][identity], decorators=["changed"]),
                      dict(stored["guardDefinitions"][identity], fixtureGuards=identity)):
            malformed = copy.deepcopy(stored)
            malformed["guardDefinitions"][identity] = guard
            with self.subTest(guard=guard), self.assertRaises(ValueError):
                contracts.fragment_path(malformed)
        malformed = copy.deepcopy(stored)
        malformed["guardDefinitions"][identity.upper()] = malformed["guardDefinitions"].pop(identity)
        malformed["guards"][case] = identity.upper()
        with self.assertRaisesRegex(ValueError, "python-guard-definition-digest"):
            contracts.fragment_path(malformed)
        path = self.root / "duplicate-definitions.json"
        raw = json.dumps(stored)
        definition = json.dumps(stored["guardDefinitions"][identity])
        raw = raw.replace(json.dumps(identity) + ": " + definition,
                          json.dumps(identity) + ": " + definition + ", " + json.dumps(identity) + ": " + definition)
        path.write_text(raw)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            contracts.read_json(path)

    def test_shared_storage_checks_original_decoded_bound_before_copying(self):
        value = contracts.fragments(self.root)["python/test_alpha.py.json"]
        stored = contracts.shared_python_record(value)
        size = len(contracts.canonical(value).encode("utf-8"))
        with patch.object(registry, "MAX_BYTES", size):
            self.assertEqual(contracts.semantic_record(stored), value)
        with patch.object(registry, "MAX_BYTES", size - 1), patch.object(contracts.copy, "deepcopy", side_effect=AssertionError("expanded before bound")):
            with self.assertRaisesRegex(ValueError, "decoded-contract-byte-limit"):
                contracts.semantic_record(stored)
        case, identity = next(iter(stored["guards"].items()))
        large = copy.deepcopy(stored)
        guard = large["guardDefinitions"].pop(identity)
        guard["fixtureGuards"] = ["\u00e9" * 300000]
        identity = hashlib.sha256(contracts.canonical(guard).encode("utf-8")).hexdigest()
        large["guardDefinitions"][identity] = guard
        large["cases"] = ["Cases.test_" + str(index) for index in range(4)]
        large["guards"] = {item: identity for item in large["cases"]}
        path = self.root / "bounded-v2.json"
        path.write_bytes(json.dumps(large, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self.assertLess(path.stat().st_size, registry.MAX_BYTES)
        with patch.object(contracts.copy, "deepcopy", side_effect=AssertionError("expanded before bound")):
            with self.assertRaisesRegex(ValueError, "decoded-contract-byte-limit"):
                contracts.fragment_path(contracts.read_json(path))
        path.write_bytes(b" " * (registry.MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "contract-byte-limit"):
            contracts.read_json(path)

    def test_shared_storage_resolves_independent_copies_and_rejects_order_loss(self):
        value = contracts.fragments(self.root)["python/test_alpha.py.json"]
        first = value["cases"][0]
        second = "Cases.test_z_other"
        value["cases"].append(second)
        value["guards"][second] = copy.deepcopy(value["guards"][first])
        stored = contracts.shared_python_record(value)
        restored = contracts.semantic_record(stored)
        restored["guards"][first]["bases"].append("mutated")
        self.assertEqual(restored["guards"][second], value["guards"][second])
        self.assertNotIn("mutated", next(iter(stored["guardDefinitions"].values()))["bases"])
        stored["cases"].append("Cases.test_z_mutated")
        self.assertNotIn("Cases.test_z_mutated", value["cases"])
        value["guards"][second] = dict(reversed(list(value["guards"][second].items())))
        with self.assertRaisesRegex(ValueError, "python-guard-definition-order-conflict"):
            contracts.shared_python_record(value)

    def test_python_proposal_preserves_reviewed_storage_and_v1_defaults(self):
        path = self.root / contracts.DIRECTORY / "python/test_alpha.py.json"
        original = contracts.read_json(path)
        self.assertEqual(original["schemaVersion"], contracts.SCHEMA)
        stored = contracts.shared_python_record(original)
        path.write_text(json.dumps(stored, separators=(",", ":")) + "\n")
        source = self.root / "tools/tests/test_alpha.py"
        source.write_text(source.read_text() + "    def test_z_additional(self):\n        self.assertTrue(True)\n")
        proposed = contracts.propose(self.root, "python", "tools/tests/test_alpha.py", None,
                                     self.root / "target/ci/proposals", "Add the reviewed regression case.")
        physical = contracts.read_json(proposed)
        self.assertEqual(physical["schemaVersion"], contracts.PYTHON_STORAGE_SCHEMA)
        self.assertEqual(contracts.semantic_record(physical)["guards"],
                         contracts.python_expectations(self.root)["tools/tests/test_alpha.py"]["guards"])
        self.assertEqual(contracts.read_json(path), stored)
        self.assertEqual(contracts.record("python", "Explicit v1 default.", module=original["module"],
                                         cases=original["cases"], guards=original["guards"])["schemaVersion"], contracts.SCHEMA)
        beta = contracts.propose(self.root, "python", "tools/tests/test_beta.py", None,
                                 self.root / "target/ci/proposals", "Retain the reviewed v1 storage.")
        self.assertEqual(contracts.read_json(beta)["schemaVersion"], contracts.SCHEMA)

    def test_both_workflow_extensions_are_observed(self):
        self.assertEqual(set(contracts.load(self.root)["workflowContracts"]),
                         {".github/workflows/ci.yml", ".github/workflows/extra.yaml"})
        self.source(lambda model: model["jobs"]["build"]["steps"][0].update(run="true"), "extra.yaml")
        with self.assertRaisesRegex(ValueError, "changed-workflow-job"):
            coverage.validate(self.root)

    def test_case_key_storage_roundtrips_v1_v2_order_and_complete_assembly(self):
        def ordered(value):
            if isinstance(value, dict):
                return (dict, [(key, ordered(item)) for key, item in value.items()])
            if isinstance(value, list):
                return (list, [ordered(item) for item in value])
            return (type(value), value)

        before = contracts.fragments(self.root)
        value = copy.deepcopy(before["python/test_alpha.py.json"])
        value = dict(reversed(list(value.items())))
        guard = dict(reversed(list(next(iter(value["guards"].values())).items())))
        guard["decorators"] = ["second(é)", "first(β)"]
        value["cases"] = ["Cases.test_first", "Cases.test_second"]
        value["guards"] = {case: copy.deepcopy(guard) for case in value["cases"]}
        for version, physical in (("v1", value), ("v2", contracts.shared_python_record(value))):
            with self.subTest(version=version):
                stored = contracts.case_key_python_record(physical)
                self.assertNotIn("cases", stored)
                self.assertEqual(stored["storageCases"], "guard-keys")
                self.assertEqual(ordered(contracts.semantic_record(stored)), ordered(value))
                self.assertEqual(contracts.case_key_python_record(stored), stored)
                shared = contracts.shared_python_record(stored)
                self.assertEqual(shared["storageCases"], "guard-keys")
                self.assertEqual(ordered(contracts.semantic_record(shared)), ordered(value))
                destination = self.root / ("case-key-" + version)
                contracts.write_records(destination, [stored])
                loaded = contracts.read_json(destination / contracts.fragment_path(stored))
                self.assertEqual(ordered(loaded), ordered(stored))
                self.assertEqual(ordered(contracts.semantic_record(loaded)), ordered(value))
                self.assertNotIn(b"\r", (destination / contracts.fragment_path(stored)).read_bytes())

        expected = contracts.load(self.root)
        for relative, original in before.items():
            if original["kind"] == "python":
                physical = (contracts.shared_python_record(original)
                            if relative.endswith("test_beta.py.json") else original)
                stored = contracts.case_key_python_record(physical)
                path = self.root / contracts.DIRECTORY / relative
                path.write_text(json.dumps(stored, ensure_ascii=False, separators=(",", ":")) + "\n",
                                encoding="utf-8")
        self.assertEqual(ordered(contracts.fragments(self.root)), ordered(before))
        self.assertEqual(ordered(contracts.load(self.root)), ordered(expected))
        coverage.validate(self.root)

    def test_case_key_storage_refuses_ambiguous_malformed_and_ordered_inventory_changes(self):
        value = contracts.fragments(self.root)["python/test_alpha.py.json"]
        for physical in (value, contracts.shared_python_record(value)):
            stored = contracts.case_key_python_record(physical)
            variants = [dict(stored, storageCases="other"), dict(stored, storageCases=True),
                        dict(stored, schemaVersion="latent.ci.contracts.v3"), dict(stored, kind="owner"),
                        dict(stored, cases=value["cases"]), dict(stored, extra="field"),
                        {key: item for key, item in stored.items() if key != "storageCases"},
                        dict(stored, guards={}), dict(stored, guards=[]),
                        dict(stored, module="tools/tests/../outside.py")]
            guard = next(iter(stored["guards"].values()))
            for name in ("broken", "Cases.helper", "Cases.test_bad.extra", "1Cases.test_ok",
                         "Cases.test_bad-name", "class.test_ok", 7):
                variants.append(dict(stored, guards={name: guard}))
            variants.append(dict(stored, guards={"Cases.test_z": guard, "Cases.test_a": guard}))
            if physical["schemaVersion"] == contracts.PYTHON_STORAGE_SCHEMA:
                variants.extend([dict(stored, guards={value["cases"][0]: "f" * 64}),
                                 {key: item for key, item in stored.items() if key != "guardDefinitions"}])
            for malformed in variants:
                with self.subTest(schema=physical["schemaVersion"], fields=malformed), self.assertRaises(ValueError):
                    contracts.fragment_path(malformed)
            duplicate = self.root / (physical["schemaVersion"].rsplit(".", 1)[-1] + "-duplicate-case-storage.json")
            raw = json.dumps(stored)
            raw = raw.replace('"storageCases": "guard-keys"',
                              '"storageCases": "guard-keys", "storageCases": "guard-keys"', 1)
            duplicate.write_text(raw)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                contracts.read_json(duplicate)
        ineligible = copy.deepcopy(value)
        guard = next(iter(ineligible["guards"].values()))
        ineligible["cases"] = ["Cases.test_a", "Cases.test_z"]
        ineligible["guards"] = {case: guard for case in reversed(ineligible["cases"])}
        with self.assertRaisesRegex(ValueError, "case-storage-requires-ordered-guards"):
            contracts.case_key_python_record(ineligible)

    def test_case_key_storage_keeps_physical_and_expanded_bounds_before_guard_copies(self):
        value = contracts.fragments(self.root)["python/test_alpha.py.json"]
        for physical in (value, contracts.shared_python_record(value)):
            stored = contracts.case_key_python_record(physical)
            size = max(len(contracts.canonical(physical).encode("utf-8")),
                       len(contracts.canonical(value).encode("utf-8")))
            with patch.object(registry, "MAX_BYTES", size):
                self.assertEqual(contracts.semantic_record(stored), value)
            with patch.object(registry, "MAX_BYTES", len(contracts.canonical(physical).encode("utf-8")) - 1), \
                    patch.object(contracts.copy, "deepcopy", side_effect=AssertionError("copied before bound")):
                with self.assertRaisesRegex(ValueError, "decoded-contract-byte-limit"):
                    contracts.semantic_record(stored)

        value["cases"] = ["Cases.test_" + str(index) for index in range(4)]
        guard = next(iter(value["guards"].values()))
        value["guards"] = {case: copy.deepcopy(guard) for case in value["cases"]}
        stored = contracts.case_key_python_record(contracts.shared_python_record(value))
        identity = next(iter(stored["guardDefinitions"]))
        large_guard = stored["guardDefinitions"].pop(identity)
        large_guard["fixtureGuards"] = ["é" * 300000]
        identity = hashlib.sha256(contracts.canonical(large_guard).encode("utf-8")).hexdigest()
        stored["guardDefinitions"][identity] = large_guard
        stored["guards"] = {case: identity for case in value["cases"]}
        path = self.root / "case-key-expanded-bound.json"
        path.write_bytes(json.dumps(stored, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self.assertLess(path.stat().st_size, registry.MAX_BYTES)
        with patch.object(contracts.copy, "deepcopy", side_effect=AssertionError("copied before bound")):
            with self.assertRaisesRegex(ValueError, "decoded-contract-byte-limit"):
                contracts.fragment_path(contracts.read_json(path))
        path.write_bytes(b" " * (registry.MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "contract-byte-limit"):
            contracts.read_json(path)

    def test_case_key_proposals_preserve_opt_in_defaults_and_source_guard_failures(self):
        for shared in (False, True):
            with self.subTest(shared=shared), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture(root)
                source = root / "tools/tests/test_alpha.py"
                source.write_text(source.read_text() + "    def test_a_first(self):\n        self.assertTrue(True)\n")
                baseline_source = source.read_text()
                observed = contracts.python_expectations(root)["tools/tests/test_alpha.py"]
                self.assertNotEqual(list(observed["guards"]), observed["cases"])
                path = root / contracts.DIRECTORY / "python/test_alpha.py.json"
                reviewed = contracts.read_json(path)
                fields = list(next(iter(reviewed["guards"].values())))
                reviewed["cases"] = observed["cases"]
                reviewed["guards"] = {case: {field: observed["guards"][case][field] for field in fields}
                                      for case in reviewed["cases"]}
                stored = contracts.case_key_python_record(
                    contracts.shared_python_record(reviewed) if shared else reviewed)
                path.write_text(json.dumps(stored, ensure_ascii=False, separators=(",", ":")) + "\n")
                coverage.validate(root)
                source.write_text(baseline_source + "    def test_zz_added(self):\n        self.assertTrue(True)\n")
                proposal = contracts.propose(root, "python", "tools/tests/test_alpha.py", None,
                    root / "target/ci/proposals/selected", "Add one reviewed case, preserving explicit storage.")
                selected = contracts.read_json(proposal)
                self.assertEqual(selected["storageCases"], "guard-keys")
                self.assertEqual(selected["schemaVersion"], stored["schemaVersion"])
                resolved = contracts.semantic_record(selected)
                self.assertEqual(list(resolved), list(reviewed))
                self.assertEqual(resolved["cases"], [*reviewed["cases"], "Cases.test_zz_added"])
                self.assertEqual(resolved["guards"],
                                 contracts.python_expectations(root)["tools/tests/test_alpha.py"]["guards"])
                for case in reviewed["cases"]:
                    self.assertEqual(list(resolved["guards"][case]), list(reviewed["guards"][case]))
                self.assertEqual(contracts.read_json(path), stored)
                default = contracts.propose(root, "python", "tools/tests/test_beta.py", None,
                    root / "target/ci/proposals/default", "Preserve the unselected v1 default.")
                self.assertEqual(contracts.read_json(default)["schemaVersion"], contracts.SCHEMA)
                self.assertNotIn("storageCases", contracts.read_json(default))
                from tools.ci_python_policy import require_no_new_controls
                require_no_new_controls(baseline_source, baseline_source.replace("def test_works", "def test_renamed"))
                require_no_new_controls(baseline_source, "CHANGED_SETUP = True\n" + baseline_source)
                with self.assertRaisesRegex(ValueError, "suppression"):
                    require_no_new_controls(baseline_source, baseline_source.replace(
                        "    def test_works", "    @unittest.skip('changed')\n    def test_works"))

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
        from tools.ci_python_policy import require_no_new_controls
        original = (self.root / "tools/tests/test_alpha.py").read_text()
        variants = (original + "    def setUp(self):\n        self.skipTest('fixture')\n",
                    original + "    __unittest_skip__ = True\n",
                    original + "def setUpModule():\n    raise unittest.SkipTest('fixture')\n",
                    original + "def load_tests(loader, tests, pattern):\n    return unittest.TestSuite()\n",
                    original + "    def run(self, result=None):\n        return result\n")
        for text in variants:
            with self.subTest(source=text), self.assertRaisesRegex(ValueError, "suppression"):
                require_no_new_controls(original, text)

    def test_changed_skip_predicate_binding_and_unreachable_class_are_rejected(self):
        from tools.ci_python_policy import require_no_new_controls
        original = (self.root / "tools/tests/test_alpha.py").read_text()
        baseline = original.replace("class Cases", "SKIP = False\n@unittest.skipIf(SKIP, 'fixture')\nclass Cases")
        with self.assertRaisesRegex(ValueError, "suppression"):
            require_no_new_controls(baseline, baseline.replace("SKIP = False", "SKIP = True"))
        lines = original.splitlines()
        unreachable = lines[0] + "\nif False:\n" + "\n".join("    " + line for line in lines[1:]) + "\n"
        with self.assertRaisesRegex(ValueError, "discovery-changed"):
            require_no_new_controls(original, unreachable)

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
        legacy = contracts.read_json(self.root / "legacy.json")
        row = next(iter(legacy["coverage"].values()))
        row["after"] += "-missing"
        (self.root / "legacy.json").write_text(json.dumps(legacy))
        with self.assertRaisesRegex(ValueError, "invalid-migration-obligation"):
            contracts.migrate(self.root, self.root / "legacy.json", self.root / "target/migration")
        self.assertFalse((self.root / "target/migration").exists())

    def test_unsafe_and_absolute_owner_paths_fail(self):
        for path in ("../outside.py", "/tmp/outside.py", "tools/../../outside.py", "tools//owner.py", "tools\\owner.py", "tools/C:owner.py"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                contracts.record("owner", "reviewed", path=path, sha256="a" * 64, reviewBoundary="committed-fingerprint")

    def test_owner_fingerprints_cannot_be_replaced_by_unenforced_codeowners(self):
        rewrite_fragment(self.root, "owners/tools/owner.py.json", lambda value: value.update(reviewBoundary="CODEOWNERS"))
        with self.assertRaisesRegex(ValueError, "unenforced-owner-review-boundary"):
            contracts.load(self.root)

    def test_changed_owner_body_remains_observable_without_fingerprint_refresh(self):
        path = self.root / "tools/owner.py"
        before = coverage.delegated_owners(self.root, coverage.commands(self.root))
        contracts_before = contracts.fragments(self.root)
        path.write_text("print('changed body')\n")
        (self.root / "tools/ci_result.py").write_text("print('independently changed aggregate')\n")
        after = coverage.delegated_owners(self.root, coverage.commands(self.root))
        self.assertNotEqual(before["tools/owner.py"], after["tools/owner.py"])
        self.assertNotEqual(before["tools/ci_result.py"], after["tools/ci_result.py"])
        self.assertEqual(contracts_before, contracts.fragments(self.root))
        coverage.validate(self.root)
        from tools.ci_python_policy import require_no_new_controls
        module = self.root / "tools/tests/test_alpha.py"
        original = "def helper(): return 1\n" + module.read_text()
        changed = original.replace("return 1", "return 1 + 0")
        module.write_text(changed)
        require_no_new_controls(original, changed)
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

    def test_ordinary_python_names_are_dynamic_but_empty_or_duplicate_modules_fail(self):
        path = self.root / "tools/tests/test_alpha.py"
        original = path.read_text()
        for source in (original.replace("test_works", "test_renamed"),
                       original + "    def test_new(self):\n        pass\n"):
            path.write_text(source)
            coverage.validate(self.root)
        for source in ("import unittest\n", original + "    def test_works(self):\n        pass\n"):
            path.write_text(source)
            with self.assertRaises(ValueError): coverage.validate(self.root)

    def test_new_python_modules_need_no_central_index(self):
        shutil.copyfile(self.root / "tools/tests/test_alpha.py", self.root / "tools/tests/test_added.py")
        coverage.validate(self.root)

    def test_new_skips_expected_failures_and_class_guards_fail(self):
        from tools.ci_python_policy import require_no_new_controls
        original = (self.root / "tools/tests/test_alpha.py").read_text()
        variants = [original.replace("    def test_works", "    @unittest.skip('review needed')\n    def test_works"),
                    original.replace("class Cases", "@unittest.skipIf(True, 'review needed')\nclass Cases"),
                    original.replace("    def test_works", "    @unittest.expectedFailure\n    def test_works"),
                    original.replace("self.assertTrue(True)", "self.skipTest('review needed')"),
                    original.replace("unittest.TestCase", "object")]
        for source in variants:
            with self.subTest(source=source), self.assertRaises(ValueError):
                require_no_new_controls(original, source)

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
        contracts.propose(self.root, "job", ".github/workflows/ci.yml", "docs", self.root / "target/ci/proposals", "Review requested.")
        with self.assertRaisesRegex(ValueError, "changed-workflow-job"):
            coverage.validate(self.root)

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
        # Archived history is not compared with today's job bytes. Current job
        # contracts and the unconditional aggregate retain execution ownership.
        data = contracts.load(ROOT)
        model = data["workflowContracts"][".github/workflows/ci.yml"]
        self.assertEqual(lanes.result_contract_errors(model), ())
        self.assertNotIn("before", data)
        self.assertNotIn("coverage", data)
        self.assertTrue((ROOT / "tools/ci/history/commands-v1.json").is_file())
        c = lanes.workflow_model((ROOT / ".github/workflows/c-guest-authoring.yml").read_text())
        guard = c["jobs"]["runtime"]["if"]
        # Evaluate only the closed grammar used by this guard; an unfamiliar
        # construct fails the test rather than being guessed or executed.
        import ast, re
        def selected(event, ref, replay):
            expression = guard.removeprefix("${{").removesuffix("}}").strip()
            expression = re.sub(r"github\.ref\s*!=\s*'([^']+)'", lambda m: str(ref != m.group(1)), expression)
            expression = expression.replace("github.event_name", repr(event)).replace("inputs.replay-closed-filesystem", str(replay))
            expression = expression.replace("&&", " and ").replace("||", " or ")
            expression = re.sub(r"!(?!=)", " not ", expression).strip()
            tree = ast.parse(expression, mode="eval")
            allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.Compare,
                       ast.Eq, ast.NotEq, ast.Constant, ast.Load)
            self.assertTrue(all(isinstance(node, allowed) for node in ast.walk(tree)))
            return bool(eval(compile(tree, "<guard>", "eval"), {"__builtins__": {}}, {}))
        self.assertTrue(selected("pull_request", "refs/pull/42/merge", False))
        self.assertTrue(selected("push", "refs/heads/development", False))
        self.assertTrue(selected("workflow_dispatch", "refs/heads/development", False))
        self.assertFalse(selected("workflow_dispatch", "refs/heads/development", True))
        self.assertIn("pull_request", c["on"])
        self.assertIn("development", c["on"]["push"]["branches"])

    def test_workflow_and_shared_contract_edits_still_select_full_ci(self):
        from tools.ci_profile import classify_paths
        for path in (".github/workflows/ci.yml", "tools/ci_python_policy.py", "tools/ci_contracts.py"):
            with self.subTest(path=path):
                self.assertEqual(classify_paths([path]).profile, "full")

    def test_receipt_is_uploaded_unconditionally_and_protected_result_is_unchanged(self):
        model = lanes.workflow_model((ROOT / ".github/workflows/ci.yml").read_text())
        self.assertEqual(lanes.result_contract_errors(model), ())
        steps = model["jobs"]["docs"]["steps"]
        validation = next(index for index, step in enumerate(steps) if step.get("id") == "contract_coverage")
        tests = next(index for index, step in enumerate(steps) if step.get("name") == "Validate documentation and profile selection")
        self.assertLess(validation, tests)
        invocations = [line.strip() for step in steps for line in step.get("run", "").splitlines()
                       if line.strip().startswith("python3 tools/ci_coverage.py")]
        self.assertEqual(invocations, ["python3 tools/ci_coverage.py --receipt target/ci/observed-inventory.json"])
        deterministic = next(step for step in steps if step.get("name") == "Validate deterministic dependency regressions")
        self.assertEqual(deterministic["if"], "needs.profile.outputs.profile != 'full'")
        self.assertEqual(model["jobs"]["contracts"]["if"], "needs.profile.outputs.profile == 'full'")
        self.assertIn("python", model["jobs"]["contracts"]["strategy"]["matrix"]["lane"])
        upload = next(step for step in steps if step.get("id") == "contract_evidence")
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["path"], "target/ci/observed-inventory.json")
