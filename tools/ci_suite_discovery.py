#!/usr/bin/env python3
"""Check registered Cargo identities and test discovery; optionally run host suites.

Uses the exact-selection primitives from #238/#374, not a second security matrix.
Custom executables are NEVER probed with libtest --list or libtest run arguments.
"""
from __future__ import annotations

import argparse
from collections import Counter
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


def validate_custom_listing(raw: bytes, expected: list[str]) -> None:
    from tools.run_aot_tests import listing as custom_listing
    registry.require(len(raw) <= 1024 * 1024, "custom-harness-list-limit")
    custom_listing(raw, frozenset(expected))


def validate_cases(suite: dict, available: frozenset[str], ignored: frozenset[str], selections: dict) -> None:
    registry.require(ignored <= available, "ignored-case-not-listed")
    if suite["mode"] == "compile-only":
        registry.require(not available, "new-tests-need-suite-registration")
    else:
        registry.require(bool(available), "empty-or-missing-suite")
    # Ignore-state changes cannot silently move ordinary coverage into an opt-in
    # lane. The exact selected cases below additionally pin their module paths.
    registry.require({name.rsplit("::", 1)[-1] for name in ignored} <= set(suite["ignoredLeaves"]),
                     "unexpectedly-ignored-case")
    if "expectedIgnored" in suite:
        registry.require(ignored == frozenset(suite["expectedIgnored"]), "changed-test-ignore-state")
    registry.require(set(suite.get("requiredCases", [])) <= available, "missing-required-case")
    registry.require(set(suite.get("caseFixtures", {})) <= available, "missing-fixture-case")
    registry.require(set(suite.get("nestedCases", [])) <= available - ignored, "missing-nested-case")
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


def execution_cases(raw: bytes, available: frozenset[str], ignored: frozenset[str],
                    nested_cases: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Validate named outcomes against this executable's own discovery."""
    lines = raw.decode("utf-8", errors="strict").splitlines()
    passed, skipped, failed, errors = _libtest_outcomes(lines, available, ignored, nested_cases)
    registry.require(not errors and not failed, "host-suite-case-result-mismatch")
    return passed, skipped


def _libtest_outcomes(lines: list[str], available: set[str] | frozenset[str],
                      ignored: set[str] | frozenset[str], nested_cases=()) -> tuple[list[str], list[str], list[str], list[str]]:
    outcomes = {"ok": [], "ignored": [], "FAILED": []}
    summaries = []
    errors = []
    for line in lines:
        if line.startswith("test result:"):
            match = re.match(r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;", line)
            if match:
                summaries.append(match.groups())
        elif line.startswith("test "):
            match = re.fullmatch(r"test (.+) \.\.\. (ok|ignored|FAILED)(?:, .*)?", line)
            if not match:
                errors.append("malformed-outcome")
            elif match.group(1) not in available:
                errors.append("unknown-outcome")
            else:
                outcomes[match.group(2)].append(match.group(1))
    active = set(available) - set(ignored)
    passed, skipped, failed = outcomes["ok"], outcomes["ignored"], outcomes["FAILED"]
    counts = Counter(passed + skipped)
    # A parent test can launch the same libtest binary as a child. Its stdout
    # can interleave with other parent tests. Extra identical case records are
    # accepted only when successful nested summaries account for every one;
    # unknown names, missing parent cases and failed children still fail closed.
    nested = summaries[:-1]
    extra = sum(value - 1 for value in counts.values() if value > 1)
    nested_total = sum(int(p) + int(i) for status, p, f, i in nested
                       if status == "ok" and f == "0")
    if (not summaries or summaries[-1] != ("ok", str(len(active)), "0", str(len(ignored)))
            or len(nested) != sum(status == "ok" and f == "0" for status, p, f, i in nested)
            or set(passed) != active or set(skipped) != set(ignored) or failed
            or set(passed) & set(skipped) or extra != nested_total
            or not {name for name, count in counts.items() if count > 1} <= set(nested_cases)):
        errors.append("execution-mismatch")
    return sorted(set(passed)), sorted(set(skipped)), sorted(failed), errors


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
    artifact_names = set()
    active_count = 0
    for group in selected_groups:
        suite, artifact = selected[group.key], artifacts[group.key]
        artifact_name = artifact.executable.name
        registry.require(artifact_name not in artifact_names, "ambiguous-executable-name")
        artifact_names.add(artifact_name)
        registry.require(sys.platform == "linux" and os.uname().machine == "x86_64", "unsupported-suite-platform")
        if suite["mode"] == "custom":
            registry.require(not execute, "custom-harness-in-fast-lane")
            source = repo / group.manifest
            source = source.parent / group.source
            registry.require(hashlib.sha256(source.read_bytes()).hexdigest() == suite["sourceSha256"],
                             "custom-harness-identity-changed")
            receipt = {"id": group.key, "artifact": artifact_name, "contract": "custom-no-list", "runArgs": [],
                       "successMarker": suite["successMarker"]}
            if suite.get("listContract") == "custom-list":
                env = cargo_environment(repo, artifact, dict(os.environ))
                status, raw = run_owned([str(artifact.executable), "--list"], cwd=artifact.package,
                                        env=env, timeout=30, maximum=1024 * 1024)
                registry.require(status == 0, "custom-harness-list-failed")
                validate_custom_listing(raw, suite["expectedCustomCases"])
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
        receipt = {"id": group.key, "artifact": artifact_name, "cases": sorted(available), "ignored": sorted(ignored),
                   "nestedCases": suite.get("nestedCases", []),
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
            passed, skipped = execution_cases(raw, available, ignored, tuple(suite.get("nestedCases", [])))
            receipt.update(executed=True, executedCases=sorted(passed), skippedCases=sorted(skipped),
                           executionSeconds=round(time.monotonic() - start, 6))
        receipts.append(receipt)
    registry.require(active_count > 0, "no-active-correctness-cases")
    return {"schemaVersion": "latent.ci.discovery.v1", "sourceRevision": os.environ.get("GITHUB_SHA"),
            "packages": packages, "builtPackageIds": dependencies,
            "activeCases": active_count, "suites": receipts}


def source_state(repo: Path) -> dict:
    """Bind tracked dirty bytes without serializing source or environment."""
    environment = dict(os.environ)
    status, porcelain = run_owned(["git", "-c", "gc.auto=0", "status", "--porcelain=v1", "-z",
                                   "--untracked-files=normal"], cwd=repo, env=environment,
                                  timeout=30, maximum=1024 * 1024)
    registry.require(status == 0, "source-status-failed")
    registry.require(not any(row.startswith(b"?? ") for row in porcelain.split(b"\0")),
                     "untracked-source-identity-unavailable")
    status, diff = run_owned(["git", "-c", "gc.auto=0", "diff", "--binary", "HEAD", "--"],
                             cwd=repo, env=environment, timeout=30, maximum=16 * 1024 * 1024)
    registry.require(status == 0, "source-diff-failed")
    return {"trackedChangesSha256": hashlib.sha256(diff).hexdigest(), "workingTreeModified": bool(porcelain)}


def workspace_execution(receipt: dict, raw: str) -> tuple[dict, list[str]]:
    """Compare Cargo's named harness outcomes to its source-bound discovery."""
    registry.require(isinstance(receipt, dict) and receipt.get("schemaVersion") == "latent.ci.discovery.v1"
                     and isinstance(receipt.get("suites"), list), "invalid-discovery-receipt")
    rows = receipt["suites"]
    registry.require(0 < len(rows) <= 10000, "invalid-discovery-suite-count")
    by_artifact = {}
    identities = set()
    for row in rows:
        registry.require(isinstance(row, dict) and isinstance(row.get("id"), str)
                         and re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,255}", row["id"])
                         and isinstance(row.get("artifact"), str)
                         and re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", row["artifact"])
                         and row["artifact"] not in by_artifact and row["id"] not in identities,
                         "invalid-discovery-artifact")
        identities.add(row["id"])
        by_artifact[row["artifact"]] = row
    text = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    sections = {}
    current = None
    errors = []
    for line in text.splitlines():
        marker = re.fullmatch(r"\s*Running .+ \(([^()]*)\)\s*", line)
        if marker:
            artifact = Path(marker.group(1)).name
            if artifact not in by_artifact or artifact in sections:
                errors.append("unexpected-or-duplicate-artifact")
                current = None
            else:
                current = artifact
                sections[artifact] = []
        elif current is not None:
            sections[current].append(line)
    reports = []
    for artifact, row in by_artifact.items():
        result = {"id": row["id"], "artifact": artifact, "discovered": row.get("cases", []),
                  "executed": [], "skipped": [], "failed": []}
        reports.append(result)
        if artifact not in sections:
            errors.append("missing-artifact:" + row["id"])
            continue
        if row.get("contract", "").startswith("custom"):
            if sections[artifact].count(row.get("successMarker")) != 1:
                errors.append("missing-custom-marker:" + row["id"])
            continue
        available, ignored = row.get("cases"), row.get("ignored")
        if (not isinstance(available, list) or not isinstance(ignored, list)
                or len(available) != len(set(available)) or not set(ignored) <= set(available)):
            errors.append("invalid-discovery-cases:" + row["id"])
            continue
        nested_cases = row.get("nestedCases", [])
        if not isinstance(nested_cases, list) or not set(nested_cases) <= set(available) - set(ignored):
            errors.append("invalid-nested-cases:" + row["id"])
            continue
        passed, skipped, failed, findings = _libtest_outcomes(sections[artifact], set(available), set(ignored), nested_cases)
        result.update(executed=passed, skipped=skipped, failed=failed)
        errors.extend(finding + ":" + row["id"] for finding in findings)
    return {"schemaVersion": "latent.ci.workspace-execution.v1", "sourceRevision": receipt.get("sourceRevision"),
            "sourceState": receipt.get("sourceState"), "recipe": "workspace-tests", "suites": reports}, errors


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


def validate_recipe_execution(data: dict, recipe: str, raw: str, listing_raw: str | None = None) -> None:
    """Retain doctest targets and named signing controls without case totals."""
    registry.require(recipe in {"explicit-doctests", "signing-compatibility"}, "unsupported-explicit-recipe")
    contract = data["recipes"][recipe]
    text = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    if recipe == "explicit-doctests":
        argv = contract["run"]
        packages = [argv[index + 1].replace("-", "_") for index, value in enumerate(argv[:-1]) if value == "-p"]
        markers = list(re.finditer(r"^\s*Doc-tests ([A-Za-z0-9_]+)\s*$", text, re.M))
        registry.require(packages and [item.group(1) for item in markers] == packages, "missing-doctest-target")
        if listing_raw is None:
            # The performance observer keeps Cargo stdout and stderr separate
            # to preserve JSON artifact records, so its diagnostic concatenation
            # cannot assign stdout cases to individual stderr target markers.
            # CI's ordered stream additionally compares each target to a listing.
            outcomes = re.findall(r"^test (.+) \.\.\. (ok|ignored|FAILED)(?:, .*)?$", text, re.M)
            summaries = re.findall(r"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;", text, re.M)
            names = [name for name, _ in outcomes]
            registry.require(len(summaries) == len(packages) and names
                             and len(names) == len(set(names))
                             and all(status == 'ok' for _, status in outcomes)
                             and all(failed == ignored == '0' for _, failed, ignored in summaries)
                             and sum(int(passed) for passed, _, _ in summaries) == len(names),
                             'explicit-recipe-result-mismatch')
            return
        sections = [text[item.end():markers[index + 1].start() if index + 1 < len(markers) else len(text)]
                    for index, item in enumerate(markers)]
    else:
        registry.require(re.search(r"^\s*Running unittests .+\(.*latent_signing-[A-Za-z0-9_-]+\)\s*$", text, re.M),
                         "missing-signing-harness")
        sections = [text]
    listed_sections = None
    if listing_raw is not None:
        listing_text = re.sub(r"\x1b\[[0-9;]*m", "", listing_raw)
        if recipe == "explicit-doctests":
            listed_markers = list(re.finditer(r"^\s*Doc-tests ([A-Za-z0-9_]+)\s*$", listing_text, re.M))
            registry.require([item.group(1) for item in listed_markers] == packages, "missing-doctest-listing-target")
            listed_sections = [listing_text[item.end():listed_markers[index + 1].start() if index + 1 < len(listed_markers) else len(listing_text)]
                               for index, item in enumerate(listed_markers)]
        else:
            registry.require(re.search(r"^\s*Running unittests .+\(.*latent_signing-[A-Za-z0-9_-]+\)\s*$", listing_text, re.M),
                             "missing-signing-listing-harness")
            listed_sections = [listing_text]
    all_names = set()
    for index, section in enumerate(sections):
        outcomes = re.findall(r"^test (.+) \.\.\. (ok|ignored|FAILED)(?:, .*)?$", section, re.M)
        summaries = re.findall(r"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;", section, re.M)
        names = [name for name, status in outcomes]
        registry.require(len(summaries) == 1 and summaries[0] == (str(len(names)), "0", "0")
                         and names and len(names) == len(set(names))
                         and all(status == "ok" for _, status in outcomes), "explicit-recipe-result-mismatch")
        if listed_sections is not None:
            listed = re.findall(r"^(.+): test$", listed_sections[index], re.M)
            totals = re.findall(r"^(\d+) tests?, (\d+) benchmarks?$", listed_sections[index], re.M)
            registry.require(len(totals) == 1 and totals[0] == (str(len(listed)), "0")
                             and len(listed) == len(set(listed)) and set(listed) == set(names),
                             "explicit-recipe-discovery-execution-mismatch")
        all_names.update(names)
    if recipe == "signing-compatibility":
        required = contract.get("requiredCases")
        registry.require(isinstance(required, list) and required and set(required) <= all_names,
                         "missing-signing-security-control")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--execution-log", type=Path)
    parser.add_argument("--discovery-log", type=Path)
    parser.add_argument("--discovery-receipt", type=Path)
    parser.add_argument("--execution-receipt", type=Path)
    parser.add_argument("--recipe", choices=("explicit-doctests", "signing-compatibility"))
    args = parser.parse_args()
    try:
        data = registry.load()
        if args.execution_log:
            registry.require(args.execution_log.stat().st_size <= 32 * 1024 * 1024, "execution-log-limit")
            raw = args.execution_log.read_text()
            if args.recipe:
                registry.require(args.discovery_log and args.discovery_receipt, "missing-recipe-discovery-input")
                registry.require(args.discovery_log.stat().st_size <= 32 * 1024 * 1024
                                 and args.discovery_receipt.stat().st_size <= 16 * 1024 * 1024, "recipe-discovery-limit")
                receipt = json.loads(args.discovery_receipt.read_text())
                registry.require(receipt.get("sourceRevision") == os.environ.get("GITHUB_SHA")
                                 and receipt.get("sourceRevision"), "discovery-source-mismatch")
                require_source(registry.ROOT, os.environ.get("GITHUB_SHA"), dict(os.environ))
                registry.require(receipt.get("sourceState") == source_state(registry.ROOT), "discovery-source-state-changed")
                validate_recipe_execution(data, args.recipe, raw, args.discovery_log.read_text())
            else:
                registry.require(args.discovery_receipt and args.execution_receipt, "missing-execution-receipt-input")
                registry.require(args.discovery_receipt.stat().st_size <= 16 * 1024 * 1024, "discovery-receipt-limit")
                receipt = json.loads(args.discovery_receipt.read_text())
                registry.require(receipt.get("sourceRevision") == os.environ.get("GITHUB_SHA")
                                 and receipt.get("sourceRevision"), "discovery-source-mismatch")
                require_source(registry.ROOT, os.environ.get("GITHUB_SHA"), dict(os.environ))
                registry.require(receipt.get("sourceState") == source_state(registry.ROOT), "discovery-source-state-changed")
                report, errors = workspace_execution(receipt, raw)
                try:
                    validate_custom_execution(data, raw)
                except (ArtifactError, ValueError, KeyError, TypeError):
                    errors.append("custom-execution-invalid")
                args.execution_receipt.parent.mkdir(parents=True, exist_ok=True)
                args.execution_receipt.write_text(json.dumps({**report, "errors": errors}, indent=2) + "\n")
                registry.require(not errors, "workspace-execution-mismatch:" + ",".join(errors[:20]))
            return 0
        registry.require(args.inventory and args.receipt, "missing-discovery-input")
        require_source(registry.ROOT, os.environ.get("GITHUB_SHA"), dict(os.environ))
        before = source_state(registry.ROOT)
        receipt = discover(registry.ROOT, args.inventory, data)
        registry.require(before == source_state(registry.ROOT), "discovery-source-state-changed")
        receipt["sourceState"] = before
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"Discovered {len(receipt['suites'])} registered targets, {receipt['activeCases']} active cases")
        return 0
    except (ArtifactError, ValueError, OSError, KeyError, TypeError) as error:
        print(f"Suite discovery failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
