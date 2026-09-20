#!/usr/bin/env python3
"""Check registered Cargo identities and test discovery; optionally run host suites.

Uses the exact-selection primitives from #238/#374, not a second security matrix.
Custom executables are NEVER probed with libtest --list or libtest run arguments.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import ci_suite_inventory as registry
from tools.ci_rust_artifacts import ArtifactError, cargo_environment, require_source, run_owned
from tools.phase3_security_artifacts import listing, read_inventory, validate_selection


@dataclass(frozen=True)
class Group:
    key: str
    manifest: str
    target: str
    kind: str
    source: str


def groups(data: dict, packages: list[str] | None = None) -> tuple[Group, ...]:
    return tuple(Group(s["id"], s["manifest"], s["target"], s["kind"], s["source"])
                 for s in data["suites"] if packages is None or s["package"] in packages)


def artifact_records(path: Path) -> list[dict]:
    # read_inventory has already validated bounded records and successful finish.
    with path.open() as source:
        return [record for line in source if line.strip()
                if (record := json.loads(line)).get("reason") == "compiler-artifact"]


def validate_cases(suite: dict, available: frozenset[str], ignored: frozenset[str], selections: dict) -> None:
    registry.require(ignored <= available, "ignored-case-not-listed")
    if suite["mode"] == "compile-only":
        registry.require(not available, "new-tests-need-suite-registration")
    else:
        registry.require(len(available) >= suite["minimumCases"], "empty-or-missing-suite")
    # Ignore-state changes cannot silently move ordinary coverage into an opt-in
    # lane. The exact selected cases below additionally pin their module paths.
    registry.require({name.rsplit("::", 1)[-1] for name in ignored} <= set(suite["ignoredLeaves"]),
                     "unexpectedly-ignored-case")
    if "expectedIgnored" in suite:
        registry.require(ignored == frozenset(suite["expectedIgnored"]), "changed-test-ignore-state")
    if "expectedCases" in suite:
        registry.require(available == frozenset(suite["expectedCases"]), "renamed-or-missing-test")
    for selection in selections.values():
        if selection["suite"] != suite["id"]:
            continue
        case_group = SimpleNamespace(cases=tuple(SimpleNamespace(name=n, ignored=selection["ignored"])
                                                 for n in selection["names"]))
        validate_selection(case_group, available, ignored)
        selected = {n for n in (ignored if selection["ignored"] else available - ignored)
                    if (n == selection["filter"] if selection["exact"]
                                             else selection["filter"] in n)}
        registry.require(selected == set(selection["names"]), "ambiguous-or-empty-selection")


def discover(repo: Path, inventory: Path, data: dict, packages: list[str] | None = None,
             execute: bool = False) -> dict:
    selected_groups = groups(data, packages)
    registry.require(selected_groups, "empty-suite-selection")
    selected = {s["id"]: s for s in data["suites"] if packages is None or s["package"] in packages}
    artifacts = read_inventory(inventory, repo, selected_groups)
    records = artifact_records(inventory)
    expected = {(str((repo / g.manifest).resolve()), g.target, g.kind) for g in selected_groups}
    actual = set()
    for item in records:
        if item.get("profile", {}).get("test") and item.get("executable"):
            target = item["target"]
            key = (str(Path(item["manifest_path"]).resolve()), target["name"], tuple(target["kind"]))
            registry.require(len(key[2]) == 1, "ambiguous-target-kind")
            actual.add((key[0], key[1], key[2][0]))
    registry.require(actual == expected, "unregistered-or-missing-cargo-target")
    dependencies = sorted({item["package_id"] for item in records})
    if execute:
        registry.require(packages and set(packages) <= set(data["fastPackages"]), "not-a-fast-selection")
        registry.require(not any(forbidden in p for p in dependencies for forbidden in data["forbiddenFastDependencies"]),
                         "heavyweight-fast-build-dependency")
    receipts = []
    active_count = 0
    for group in selected_groups:
        suite, artifact = selected[group.key], artifacts[group.key]
        registry.require(sys.platform == "linux" and os.uname().machine == "x86_64", "unsupported-suite-platform")
        if suite["mode"] == "custom":
            registry.require(not execute, "custom-harness-in-fast-lane")
            source = repo / group.manifest
            source = source.parent / group.source
            registry.require(hashlib.sha256(source.read_bytes()).hexdigest() == suite["sourceSha256"],
                             "custom-harness-identity-changed")
            receipt = {"id": group.key, "contract": "custom-no-list", "runArgs": [],
                       "successMarker": suite["successMarker"]}
            if suite.get("listContract") == "custom-list":
                env = cargo_environment(repo, artifact, dict(os.environ))
                status, raw = run_owned([str(artifact.executable), "--list"], cwd=artifact.package,
                                        env=env, timeout=30, maximum=1024 * 1024)
                registry.require(status == 0 and listing(raw) == set(suite["expectedCustomCases"]),
                                 "custom-harness-list-changed")
                receipt.update(contract="custom-list", cases=sorted(suite["expectedCustomCases"]), executed=False)
            receipts.append(receipt)
            continue
        env = cargo_environment(repo, artifact, dict(os.environ))
        start = time.monotonic()
        discovered = []
        for args in (["--list"], ["--ignored", "--list"]):
            status, raw = run_owned([str(artifact.executable), *args], cwd=artifact.package,
                                    env=env, timeout=30, maximum=1024 * 1024)
            registry.require(status == 0, "test-discovery-failed")
            discovered.append(listing(raw))
        available, ignored = discovered
        try:
            validate_cases(suite, available, ignored, data["selections"])
        except (ValueError, ArtifactError) as error:
            raise registry.InventoryError(f"{group.key}: {error}") from error
        active_count += len(available - ignored)
        receipt = {"id": group.key, "cases": sorted(available), "ignored": sorted(ignored),
                   "discoverySeconds": round(time.monotonic() - start, 6), "executed": False}
        if execute and suite["mode"] != "compile-only":
            start = time.monotonic()
            status, raw = run_owned([str(artifact.executable), "--test-threads=2"], cwd=artifact.package,
                                    env=env, timeout=suite["timeoutSeconds"], maximum=4 * 1024 * 1024)
            print(raw.decode("utf-8", errors="replace"), end="", flush=True)
            registry.require(status == 0, "host-suite-failed")
            outcomes = re.findall(rb"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;", raw, re.M)
            registry.require(outcomes == [(str(len(available - ignored)).encode(), b"0", str(len(ignored)).encode())],
                             "host-suite-result-mismatch")
            receipt.update(executed=True, executionSeconds=round(time.monotonic() - start, 6))
        receipts.append(receipt)
    registry.require(active_count > 0, "no-active-correctness-cases")
    return {"schemaVersion": "latent.ci.discovery.v1", "sourceRevision": os.environ.get("GITHUB_SHA"),
            "packages": packages, "builtPackageIds": dependencies,
            "activeCases": active_count, "suites": receipts}


def validate_custom_execution(data: dict, raw: str) -> None:
    for suite in data["suites"]:
        if suite["mode"] == "custom":
            registry.require(raw.splitlines().count(suite["successMarker"]) == 1, "missing-custom-harness-execution")
            if suite["target"] == "aot_supervisor":
                from tools.run_aot_tests import validate_case_coverage
                # Cargo's aggregate log also contains unrelated libtest summaries.
                # Retain every supervisor case record, including malformed/extra ones.
                selected = "\n".join(line for line in raw.splitlines()
                                     if line.startswith("LSF_AOT_CASE ") or line == suite["successMarker"])
                validate_case_coverage(selected, suite["target"])


def validate_recipe_execution(data: dict, recipe: str, raw: str) -> None:
    expected = data["recipes"][recipe]["expectedResultCounts"]
    matches = re.findall(r"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;", raw, re.M)
    registry.require(matches == [(str(n), "0", "0") for n in expected], "empty-or-changed-recipe-result")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--execution-log", type=Path)
    parser.add_argument("--recipe", choices=("explicit-doctests", "signing-compatibility"))
    args = parser.parse_args()
    try:
        data = registry.load()
        if args.execution_log:
            registry.require(args.execution_log.stat().st_size <= 32 * 1024 * 1024, "execution-log-limit")
            if args.recipe:
                validate_recipe_execution(data, args.recipe, args.execution_log.read_text())
            else:
                validate_custom_execution(data, args.execution_log.read_text())
            return 0
        registry.require(args.inventory and args.receipt, "missing-discovery-input")
        require_source(registry.ROOT, os.environ.get("GITHUB_SHA"), dict(os.environ))
        receipt = discover(registry.ROOT, args.inventory, data)
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"Discovered {len(receipt['suites'])} registered targets, {receipt['activeCases']} active cases")
        return 0
    except (ArtifactError, ValueError, OSError, KeyError, TypeError) as error:
        print(f"Suite discovery failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
