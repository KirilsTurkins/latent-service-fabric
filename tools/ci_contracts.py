#!/usr/bin/env python3
"""Ownership-local reviewed contracts; no source discovery writes expectations.

This is the storage/structural reader for ci_coverage, not a selector or runner.
Migration is an explicit, one-time, checked operation. Proposals go to untracked
output and retain all historical obligations; validation is strictly read-only.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_lane_inventory as lanes, ci_suite_inventory as registry

SCHEMA = "latent.ci.contracts.v1"
DIRECTORY = "tools/ci/contracts"
MAX_FRAGMENTS = 2048
COMMON = {"schemaVersion", "kind", "reviewReason"}
KINDS = {
    "workflow": {"workflow", "policy", "requiredJobs"},
    "job": {"workflow", "jobId", "definition", "baselineRevision", "before", "coverage"},
    "owner": {"path", "sha256", "reviewBoundary"},
    "python": {"module", "cases", "guards"},
}
RECORD_FIELDS = {"workflow", "job", "name", "jobIf", "stepIf", "workingDirectory", "shell", "run"}
DISPOSITIONS = {"unchanged", "extended", "conditional-host-replacement"}


def require(condition: Any, reason: str) -> None:
    registry.require(condition, reason)


def safe_path(root: Path, name: str, *, regular: bool = True) -> Path:
    require(registry.path_name(name) and ":" not in name, "unsafe-contract-path")
    root = root.absolute()
    require(root.is_dir() and not root.is_symlink(), "unsafe-contract-root")
    path = root
    for part in name.split("/"):
        path = path / part
        require(not path.is_symlink(), "symlink-contract-path:" + name)
    require(path.resolve().is_relative_to(root.resolve()), "escaping-contract-path")
    if regular:
        require(stat.S_ISREG(path.lstat().st_mode), "nonregular-contract-path:" + name)
    return path


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def read_json(path: Path) -> dict:
    def constant(_value: str) -> None:
        raise ValueError("nonfinite-contract-number")
    with path.open("rb") as source:
        raw = source.read(registry.MAX_BYTES + 1)
    require(len(raw) <= registry.MAX_BYTES, "contract-byte-limit")
    value = json.loads(raw, object_pairs_hook=registry.unique_object, parse_constant=constant)
    require(isinstance(value, dict), "contract-object-required")
    return value


def workflow_paths(root: Path) -> list[Path]:
    directory = safe_path(root, ".github/workflows", regular=False)
    require(directory.is_dir(), "missing-workflow-directory")
    paths = [safe_path(root, path.relative_to(root).as_posix()) for path in sorted(directory.iterdir())
             if path.suffix in {".yml", ".yaml"}]
    require(paths, "empty-workflow-inventory")
    return paths


def observed_workflows(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): lanes.structural_workflow(lanes.workflow_model(path.read_text()))
            for path in workflow_paths(root)}


def python_expectations(root: Path) -> dict:
    directory = safe_path(root, "tools/tests", regular=False)
    def fixture_guards(statements: list[ast.stmt], scope: str) -> list[str]:
        # Bind names/helpers used by decorators and skip predicates, not just
        # the spelling of skipIf(SYMBOL). Hash AST, not comments/formatting.
        setup = [statement for statement in statements
                 if not isinstance(statement, ast.ClassDef)
                 and not (isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and statement.name.startswith("test_"))]
        guards = [scope + ":setup-sha256:" + hashlib.sha256(
            ast.dump(ast.Module(body=setup, type_ignores=[])).encode()).hexdigest()]

        for statement in statements:
            if isinstance(statement, ast.ClassDef):
                continue
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if statement.name.startswith("test_"):
                    continue
                if statement.name in {"load_tests", "run", "__call__", "__init__", "_callTestMethod"}:
                    guards.append(scope + ":execution:" + ast.unparse(statement))
            for node in ast.walk(statement):
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                    if name in {"skipTest", "SkipTest", "skip", "skipIf", "skipUnless", "expectedFailure"}:
                        guards.append(scope + ":skip:" + ast.unparse(node))
                elif isinstance(node, ast.Raise) and node.exc is not None:
                    if "SkipTest" in ast.unparse(node.exc):
                        guards.append(scope + ":raise:" + ast.unparse(node))
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    if "__unittest_skip" in ast.unparse(node) or "__unittest_expecting_failure__" in ast.unparse(node):
                        guards.append(scope + ":flag:" + ast.unparse(node))
        return sorted(set(guards))

    result = {}
    for path in sorted(directory.glob("test_*.py")):
        name = path.relative_to(root).as_posix()
        safe_path(root, name)
        tree = ast.parse(path.read_text(), filename=name)
        guards = {}
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        module_guards = fixture_guards(tree.body, "module")
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            class_guards = fixture_guards(node.body, "class")
            ancestor = parents.get(node)
            context = []
            while ancestor is not None and not isinstance(ancestor, ast.Module):
                # A class inside `if False` is not discoverable. Preserve the
                # enclosing definition/control predicates without test bodies.
                context.append({field: ast.dump(value) if isinstance(value, ast.AST) else repr(value)
                                for field, value in ast.iter_fields(ancestor)
                                if field not in {"body", "orelse", "finalbody", "handlers"}})
                ancestor = parents.get(ancestor)
            if context:
                class_guards.append("definition-context:" + canonical(context))
            for method in node.body:
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) or not method.name.startswith("test_"):
                    continue
                case = f"{node.name}.{method.name}"
                require(case not in guards, "duplicate-python-case:" + name)
                skip_sites = []
                for call in ast.walk(method):
                    if not isinstance(call, ast.Call):
                        continue
                    function = call.func
                    token = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
                    if token in {"skipTest", "SkipTest", "skip", "skipIf", "skipUnless", "expectedFailure"}:
                        skip_sites.append(ast.unparse(call))
                if skip_sites:
                    skip_sites.append("skip-control-sha256:" + hashlib.sha256(ast.dump(method).encode()).hexdigest())
                guards[case] = {
                    "bases": [ast.unparse(base) for base in node.bases],
                    "classDecorators": [ast.unparse(item) for item in node.decorator_list],
                    "decorators": [ast.unparse(item) for item in method.decorator_list],
                    "skipSites": sorted(skip_sites),
                    "fixtureGuards": module_guards + class_guards,
                }
        require(guards, "empty-python-test-module:" + name)
        result[name] = {"cases": sorted(guards), "guards": guards}
    require(result, "empty-python-test-inventory")
    return result


def workflow_name(value: Any) -> str:
    require(isinstance(value, str) and re.fullmatch(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml", value),
            "invalid-contract-workflow")
    return value.rsplit("/", 1)[1]


def fragment_path(record: dict) -> str:
    kind = record.get("kind")
    require(isinstance(kind, str) and kind in KINDS and set(record) == COMMON | KINDS[kind], "contract-fields-or-kind")
    require(record["schemaVersion"] == SCHEMA, "unsupported-contract-schema")
    require(isinstance(record["reviewReason"], str) and record["reviewReason"].strip(), "missing-contract-review-reason")
    if kind in {"workflow", "job"}:
        workflow = workflow_name(record["workflow"])
        if kind == "workflow":
            return f"workflows/{workflow}/workflow.json"
        job = record["jobId"]
        require(isinstance(job, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", job), "invalid-contract-job")
        return f"workflows/{workflow}/jobs/{job}.json"
    if kind == "owner":
        name = record["path"]
        require(isinstance(name, str) and registry.path_name(name) and ":" not in name
                and name.startswith(("tools/", "sdk/")) and name.endswith((".py", ".sh")), "invalid-owner-contract-path")
        require(record["reviewBoundary"] == "committed-fingerprint", "unenforced-owner-review-boundary")
        require(isinstance(record["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", record["sha256"]), "invalid-owner-digest")
        return f"owners/{name}.json"
    name = record["module"]
    require(isinstance(name, str) and re.fullmatch(r"tools/tests/test_[A-Za-z0-9_]+\.py", name), "invalid-python-contract-path")
    require(isinstance(record["cases"], list) and record["cases"]
            and all(isinstance(case, str) for case in record["cases"])
            and record["cases"] == sorted(set(record["cases"])), "empty-or-duplicate-python-cases")
    require(isinstance(record["guards"], dict) and set(record["guards"]) == set(record["cases"]), "python-guard-inventory")
    for guard in record["guards"].values():
        require(isinstance(guard, dict) and set(guard) == {"bases", "classDecorators", "decorators", "skipSites", "fixtureGuards"}, "python-guard-fields")
        require(all(isinstance(value, list) and all(isinstance(item, str) for item in value)
                    for value in guard.values()), "python-guard-types")
    return f"python/{Path(name).name}.json"


def fragments(root: Path, directory: Path | None = None) -> dict[str, dict]:
    directory = directory or root / DIRECTORY
    require(directory.absolute().is_relative_to(root.absolute()), "contract-directory-outside-repository")
    safe_path(root, directory.relative_to(root).as_posix(), regular=False)
    require(directory.is_dir(), "missing-contract-directory")
    records = {}
    directories = set()
    parents = set()
    for path in sorted(directory.rglob("*")):
        safe_path(root, path.relative_to(root).as_posix(), regular=False)
        relative = path.relative_to(directory).as_posix()
        if path.is_dir():
            directories.add(relative)
            continue
        require(path.suffix == ".json", "unexpected-contract-fragment:" + relative)
        safe_path(root, path.relative_to(root).as_posix())
        record = read_json(path)
        expected = fragment_path(record)
        require(relative == expected, "misplaced-or-duplicate-contract:" + relative)
        require(expected not in records, "duplicate-contract-identity")
        records[relative] = record
        parents.update(parent.as_posix() for parent in Path(relative).parents if parent != Path("."))
        require(len(records) <= MAX_FRAGMENTS, "contract-fragment-limit")
    require(records, "empty-contract-directory")
    require(directories == parents, "unexpected-empty-contract-directory")
    return records


def assemble(records: dict[str, dict]) -> dict:
    data = {"schemaVersion": SCHEMA, "before": {}, "after": {}, "coverage": {},
            "delegatedOwners": {}, "pythonCases": {}, "pythonGuards": {}, "workflowContracts": {}}
    policies, jobs, revisions = {}, {}, set()
    for record in records.values():
        kind = record["kind"]
        if kind == "workflow":
            name = record["workflow"]
            require(name not in policies, "duplicate-workflow-contract")
            require(isinstance(record["policy"], dict) and "jobs" not in record["policy"], "workflow-policy-fields")
            required = record["requiredJobs"]
            require(isinstance(required, list) and required and all(isinstance(job, str) for job in required)
                    and required == sorted(set(required)), "empty-or-duplicate-required-jobs")
            policies[name] = record
        elif kind == "job":
            name, job = record["workflow"], record["jobId"]
            require(job not in jobs.setdefault(name, {}), "duplicate-job-contract")
            require(isinstance(record["definition"], dict), "job-definition-type")
            jobs[name][job] = record["definition"]
            revision = record["baselineRevision"]
            require(isinstance(revision, str) and revision, "missing-baseline-revision")
            revisions.add(revision)
            for field in ("before", "coverage"):
                require(isinstance(record[field], dict), "historical-contract-type")
                require(not set(data[field]).intersection(record[field]), "duplicate-historical-obligation")
                data[field].update(record[field])
            require(set(record["before"]) == set(record["coverage"]), "missing-before-after-coverage")
            for key, row in record["before"].items():
                require(isinstance(row, dict) and set(row) == RECORD_FIELDS
                        and all(isinstance(value, str) for value in row.values()), "historical-command-fields")
                coverage = record["coverage"][key]
                require(isinstance(coverage, dict) and set(coverage) == {"after", "disposition", "reason"}, "coverage-fields")
                require(isinstance(coverage["after"], str) and coverage["after"].startswith(f"{name}:{job}:"), "misplaced-historical-obligation")
                require(coverage["disposition"] in DISPOSITIONS and isinstance(coverage["reason"], str)
                        and coverage["reason"].strip(), "invalid-coverage-disposition-or-reason")
        elif kind == "owner":
            name = record["path"]
            require(name not in data["delegatedOwners"], "duplicate-owner-contract")
            data["delegatedOwners"][name] = {"sha256": record["sha256"]}
        else:
            name = record["module"]
            require(name not in data["pythonCases"], "duplicate-python-contract")
            data["pythonCases"][name] = record["cases"]
            data["pythonGuards"][name] = record["guards"]
    require(set(policies) == set(jobs) and policies, "missing-or-extra-workflow-contract")
    for name, policy in policies.items():
        require(set(policy["requiredJobs"]) == set(jobs[name]), "missing-or-extra-job-contract:" + name)
        model = {**policy["policy"], "jobs": jobs[name]}
        lanes.validate_workflow_model(model)
        data["workflowContracts"][name] = model
        data["after"].update(lanes.run_commands(name, model))
    require(len(revisions) == 1, "inconsistent-historical-baseline")
    data["baselineRevision"] = revisions.pop()
    require(data["delegatedOwners"] and data["pythonCases"], "missing-owner-or-python-contracts")
    data["pythonTestModules"] = sorted(data["pythonCases"])
    for key, row in data["coverage"].items():
        require(row["after"] in data["after"], "removed-required-command-without-replacement")
        if row["disposition"] == "unchanged":
            require(data["before"][key] == data["after"][row["after"]], "unchanged-command-drift")
    return data


def load(root: Path = registry.ROOT, directory: Path | None = None) -> dict:
    return assemble(fragments(root, directory))


def record(kind: str, reason: str, **fields: Any) -> dict:
    value = {"schemaVersion": SCHEMA, "kind": kind, "reviewReason": reason, **fields}
    fragment_path(value)
    return value


def write_records(directory: Path, records: list[dict]) -> None:
    directory = directory.absolute()
    for value in records:
        path = directory / fragment_path(value)
        # Check the complete destination chain, not just the output directory.
        # Otherwise a pre-existing nested proposal symlink could escape it.
        for parent in (path, *path.parents):
            require(not parent.is_symlink(), "symlink-contract-proposal-path")
        require(not path.exists(), "refuse-overwrite-contract-proposal")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")


def migrate(root: Path, legacy: Path, output: Path) -> dict:
    """Fail before writing unless the *old* reviewed snapshot matches the source.

    Call only for initial sharding, never as a refresh. Output must not exist.
    Action pins and all old owner/workflow digests still have to match here.
    """
    from tools import ci_coverage
    output = output if output.is_absolute() else root / output
    legacy = legacy if legacy.is_absolute() else root / legacy
    require(output.absolute().is_relative_to(root.absolute()), "migration-output-outside-repository")
    safe_path(root, output.relative_to(root).as_posix(), regular=False)
    data = read_json(legacy)
    require(data.get("schemaVersion") == "latent.ci.commands.v1", "unsupported-migration-source")
    require(not output.exists(), "migration-output-already-exists")
    require({p.relative_to(root).as_posix(): digest(p) for p in workflow_paths(root)} == data["workflowIdentities"],
            "stale-migration-workflow-snapshot")
    models = observed_workflows(root)
    actual = {key: value for name, model in models.items() for key, value in lanes.run_commands(name, model).items()}
    require(actual == data["after"], "stale-migration-command-snapshot")
    require(ci_coverage.delegated_owners(root, actual) == data["delegatedOwners"], "stale-migration-owner-snapshot")
    python = python_expectations(root)
    require(sorted(python) == data["pythonTestModules"]
            and {name: value["cases"] for name, value in python.items()} == data["pythonCases"], "stale-migration-python-snapshot")
    require(set(data["before"]) == set(data["coverage"]), "missing-migration-obligation")
    reason = "Lossless sharding of the reviewed v1 inventory; owner fingerprints remain enforced."
    proposed = []
    for name, model in models.items():
        proposed.append(record("workflow", reason, workflow=name, policy={k: v for k, v in model.items() if k != "jobs"}, requiredJobs=sorted(model["jobs"])))
        for job, definition in model["jobs"].items():
            covered = {key: row for key, row in data["coverage"].items() if row["after"] in actual
                       and actual[row["after"]]["workflow"] == name and actual[row["after"]]["job"] == job}
            proposed.append(record("job", reason, workflow=name, jobId=job, definition=definition,
                                   baselineRevision=data["baselineRevision"],
                                   before={key: data["before"][key] for key in covered}, coverage=covered))
    proposed.extend(record("owner", reason, path=name, sha256=value["sha256"], reviewBoundary="committed-fingerprint")
                    for name, value in data["delegatedOwners"].items())
    proposed.extend(record("python", reason, module=name, **value) for name, value in python.items())
    assembled = assemble({fragment_path(value): value for value in proposed})
    for field in ("baselineRevision", "before", "after", "coverage", "delegatedOwners", "pythonTestModules", "pythonCases"):
        require(assembled[field] == data[field], "lossy-migration:" + field)
    require(assembled["workflowContracts"] == models, "lossy-workflow-migration")
    write_records(output, proposed)
    return assembled


def propose(root: Path, kind: str, source: str, job: str | None, output: Path, reason: str) -> Path:
    """Prepare ONE reviewable fragment, never waive a removal/replacement/skip."""
    require(reason.strip(), "proposal-needs-review-reason")
    require(output.absolute().is_relative_to((root / "target/ci/proposals").absolute()), "proposal-output-must-be-untracked")
    safe_path(root, output.relative_to(root).as_posix(), regular=False)
    existing = fragments(root)
    assembled = assemble(existing)
    if kind in {"workflow", "job"}:
        model = lanes.structural_workflow(lanes.workflow_model(safe_path(root, source).read_text()))
        workflow_name(source)
        if kind == "workflow":
            value = record(kind, reason, workflow=source, policy={k: v for k, v in model.items() if k != "jobs"}, requiredJobs=sorted(model["jobs"]))
            previous = existing.get(fragment_path(value))
            require(previous is None or set(previous["requiredJobs"]) <= set(value["requiredJobs"]), "proposal-would-remove-required-job")
        else:
            require(job in model["jobs"], "proposal-job-missing")
            path = f"workflows/{workflow_name(source)}/jobs/{job}.json"
            previous = existing.get(path)
            value = record(kind, reason, workflow=source, jobId=job, definition=model["jobs"][job],
                           baselineRevision=assembled["baselineRevision"],
                           before=previous["before"] if previous else {}, coverage=previous["coverage"] if previous else {})
            actual = lanes.run_commands(source, {"jobs": {job: value["definition"]}})
            old = lanes.run_commands(source, {"jobs": {job: previous["definition"]}}) if previous else {}
            require(set(old) <= set(actual), "proposal-would-remove-required-command")
            for key, row in value["coverage"].items():
                require(row["after"] in actual, "proposal-would-remove-replacement")
                require(row["disposition"] != "unchanged" or value["before"][key] == actual[row["after"]],
                        "proposal-needs-explicit-replacement-review")
    elif kind == "owner":
        safe_path(root, source)
        from tools import ci_coverage
        observed_owners = ci_coverage.delegated_owners(root, ci_coverage.commands(root))
        require(source in observed_owners, "proposal-owner-not-delegated")
        value = record(kind, reason, path=source, sha256=digest(root / source), reviewBoundary="committed-fingerprint")
    else:
        expectations = python_expectations(root)
        require(source in expectations, "proposal-python-module-missing")
        actual = expectations[source]
        old = assembled["pythonCases"].get(source, [])
        require(set(old) <= set(actual["cases"]), "proposal-would-remove-or-rename-python-case")
        require(all(assembled["pythonGuards"][source][case] == actual["guards"][case] for case in old),
                "proposal-needs-explicit-python-skip-review")
        value = record(kind, reason, module=source, **actual)
    write_records(output, [value])
    return output / fragment_path(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    migration = commands.add_parser("migrate", help="one-time lossless migration; refuses stale snapshots")
    migration.add_argument("--legacy", type=Path, required=True)
    migration.add_argument("--output", type=Path, required=True)
    proposal = commands.add_parser("propose", help="prepare one untracked fragment for explicit review")
    proposal.add_argument("kind", choices=sorted(KINDS))
    proposal.add_argument("source")
    proposal.add_argument("--job")
    proposal.add_argument("--output", type=Path, default=registry.ROOT / "target/ci/proposals")
    proposal.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        if args.command == "migrate":
            migrate(registry.ROOT, args.legacy, args.output)
            print("Lossless migration completed; review the proposed fragments before committing.")
        else:
            output = args.output if args.output.is_absolute() else registry.ROOT / args.output
            print(propose(registry.ROOT, args.kind, args.source, args.job, output, args.reason))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"CI contract proposal failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
