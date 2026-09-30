#!/usr/bin/env python3
"""Validate independently reviewed CI contracts and retain commit-bound evidence.

Expected records are read only from ownership-local contracts. Observations never
refresh expectations. Generated receipts contain identities/digests, not run
scripts or environment values, and are not substitutes for execution results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_contracts as contracts, ci_lane_inventory as lanes
from tools import ci_suite_inventory as registry, validate_workflow_actions as actions

INVENTORY = registry.ROOT / contracts.DIRECTORY
SCHEMA = contracts.SCHEMA
RECEIPT_SCHEMA = "latent.ci.observed-inventory.v1"


def workflow_commands(path: str, text: str) -> dict:
    return lanes.run_commands(path, lanes.workflow_model(text))


def commands(root: Path) -> dict:
    return {key: value for path in contracts.workflow_paths(root)
            for key, value in workflow_commands(path.relative_to(root).as_posix(), path.read_text()).items()}


def delegated_owners(root: Path, entries: dict) -> dict[str, dict[str, str]]:
    # Existing script delegation boundary; no second selection list is created.
    names = set()
    pending = [value["run"] for value in entries.values()]
    while pending:
        for name in re.findall(r"(?<![A-Za-z0-9_./-])(?:tools|sdk)/[A-Za-z0-9_./-]+\.(?:py|sh)\b", pending.pop()):
            if name in names:
                continue
            path = contracts.safe_path(root, name)
            names.add(name)
            if path.suffix == ".sh":
                pending.append(path.read_text())
    return {name: {"sha256": contracts.digest(root / name)} for name in sorted(names)}


def python_cases(root: Path) -> dict[str, list[str]]:
    return {name: value["cases"] for name, value in contracts.python_expectations(root).items()}


def validate(root: Path = registry.ROOT, inventory: Path | None = None) -> dict:
    # Load expectations independently, before observing the source under test.
    data = contracts.load(root, inventory)
    _workflows, _references, findings = actions.validate_repository(root)
    registry.require(not findings, "workflow-action-pin-policy:" + ",".join(
        f"{item.path.relative_to(root)}:{item.line}" for item in findings))
    actual_models = contracts.observed_workflows(root)
    expected_models = data["workflowContracts"]
    registry.require(set(actual_models) == set(expected_models), "missing-or-extra-workflow-contract")
    for name, actual in actual_models.items():
        expected = expected_models[name]
        registry.require(contracts.canonical({key: value for key, value in actual.items() if key != "jobs"})
                         == contracts.canonical({key: value for key, value in expected.items() if key != "jobs"}),
                         "changed-workflow-policy:" + name)
        registry.require(set(actual["jobs"]) == set(expected["jobs"]), "missing-or-extra-job-contract:" + name)
        for job, definition in actual["jobs"].items():
            registry.require(contracts.canonical(definition) == contracts.canonical(expected["jobs"][job]), "changed-workflow-job:" + name + ":" + job)
    actual = commands(root)
    registry.require(actual == data["after"], "unregistered-or-changed-required-command")
    registry.require(delegated_owners(root, actual) == data["delegatedOwners"], "changed-command-owner-needs-review")
    # Historical relationships are checked while assembling expected fragments,
    # and again against observations. A changed expected row cannot waive a job.
    for key, record in data["coverage"].items():
        registry.require(record["after"] in actual, "removed-required-command-without-replacement")
        if record["disposition"] == "unchanged":
            registry.require(data["before"][key] == actual[record["after"]], "unchanged-command-drift")
    registry.require(not lanes.result_contract_errors(actual_models[".github/workflows/ci.yml"]),
                     "conditional-or-incomplete-ci-result")
    registry.require(python_cases(root) == data["pythonCases"], "missing-or-renamed-or-unregistered-python-case")
    guards = {name: value["guards"] for name, value in contracts.python_expectations(root).items()}
    registry.require(guards == data["pythonGuards"], "changed-python-test-execution-guard")
    return data


def _value_digest(value: object) -> str:
    return hashlib.sha256(contracts.canonical(value).encode()).hexdigest()


def observed_inventory(root: Path, status: str) -> dict:
    """Best-effort failure evidence. Never serialize source/env/exception text."""
    commit = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root, check=True,
                            capture_output=True, text=True, timeout=10).stdout.strip()
    registry.require(re.fullmatch(r"[0-9a-f]{40,64}", commit), "unidentified-tested-commit")
    dirty = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=normal"],
                           cwd=root, check=True, capture_output=True, timeout=10).stdout
    result = {"schemaVersion": RECEIPT_SCHEMA, "testedCommit": commit,
              "workingTreeModified": bool(dirty), "validationStatus": status,
              "paths": {}, "workflows": {}, "commands": {}, "delegatedOwners": {},
              "pythonCases": {}, "observationErrors": []}

    def attempt(label: str, operation):
        try:
            return operation()
        except (ValueError, TypeError, KeyError, OSError, SyntaxError, RecursionError, yaml.YAMLError):
            result["observationErrors"].append(label)
            return None

    # Hash ordinary relevant source files even when a malformed contract prevents
    # assembly. No environment lookup, raw YAML/run blocks or parser errors enter
    # the receipt. Expected fragments are never used as acceptance observations.
    paths = set()
    for directory, suffixes in ((".github/workflows", {".yml", ".yaml"}),
                                ("tools", {".py", ".sh", ".json"})):
        parent = attempt("source-directory:" + directory, lambda d=directory: contracts.safe_path(root, d, regular=False))
        if parent is not None:
            paths.update(path.relative_to(root).as_posix() for path in parent.rglob("*")
                         if path.suffix in suffixes)
    for name in sorted(paths):
        value = attempt("source-path:" + name, lambda n=name: contracts.digest(contracts.safe_path(root, n)))
        if value is not None:
            result["paths"][name] = {"sha256": value}
    models = attempt("workflow-observation", lambda: contracts.observed_workflows(root))
    if models is not None:
        for name, model in models.items():
            result["workflows"][name] = {"policySha256": _value_digest({k: v for k, v in model.items() if k != "jobs"}),
                "jobs": {job: {"structuralSha256": _value_digest(value)} for job, value in model["jobs"].items()}}
        observed_commands = {key: value for name, model in models.items() for key, value in lanes.run_commands(name, model).items()}
        result["commands"] = {key: {"sha256": _value_digest(value)} for key, value in observed_commands.items()}
        owners = attempt("owner-observation", lambda: delegated_owners(root, observed_commands))
        if owners is not None:
            result["delegatedOwners"] = owners
            result["paths"].update(owners)
    cases = attempt("python-observation", lambda: contracts.python_expectations(root))
    if cases is not None:
        result["pythonCases"] = {name: {"names": value["cases"], "guardsSha256": _value_digest(value["guards"])}
                                 for name, value in cases.items()}
    return result


def write_receipt(root: Path, path: Path, status: str) -> dict:
    path = path if path.is_absolute() else root / path
    registry.require(path.absolute().is_relative_to((root / "target/ci").absolute()), "receipt-must-be-under-target-ci")
    contracts.safe_path(root, path.relative_to(root).as_posix(), regular=False)
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", path.relative_to(root).as_posix()],
                             cwd=root, capture_output=True, timeout=10)
    registry.require(tracked.returncode == 1, "receipt-must-not-overwrite-tracked-source")
    data = observed_inventory(root, status)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(data, output, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=Path("target/ci/observed-inventory.json"))
    args = parser.parse_args(argv)
    status = "failed"
    try:
        data = validate()
        print(f"Covered {len(data['before'])} baseline and {len(data['after'])} current required run blocks; "
              f"{len(data['delegatedOwners'])} delegated script owners")
        status = "passed"
    except (ValueError, KeyError, TypeError, OSError, SyntaxError, RecursionError, yaml.YAMLError) as error:
        print(f"CI command coverage failed: {error}", file=sys.stderr)
    try:
        write_receipt(registry.ROOT, args.receipt, status)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"CI evidence retention failed: {error}", file=sys.stderr)
        return 1
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
