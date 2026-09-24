#!/usr/bin/env python3
"""Compare shared typed application cases on a real Linux node and a native host."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dev_workflow.common import HOST_ABI, decode, digest, encode, require, sha
from tools.dev_workflow.scenarios import NODE_ONLY


def compare(node: dict, portable: dict) -> dict:
    for report, environment in ((node, "node"), (portable, "portable")):
        require(report.get("schemaVersion") == "latent.dev.test-report.v1"
                and report.get("environment") == environment and report.get("passed") is True,
                "passing-explicit-node-and-portable-reports-required")
        require(isinstance(report.get("results"), list) and 0 < len(report["results"]) <= 128
                and all(row.get("status") == "passed" and row.get("outcomeKnown") is True for row in report["results"]),
                "comparison-cannot-count-unsupported-or-unknown")
        require(report.get("selection") == [row["id"] for row in report["results"]]
                and len(set(report["selection"])) == len(report["selection"]), "comparison-selection-association")
        require(report["identity"].get("hostAbi") == HOST_ABI, "comparison-host-abi")
    require(node["selection"] == portable["selection"], "comparison-selection-mismatch")
    require(node.get("pendingOperation") is None and node.get("cleanup") == "invocation-results-received-node-retained",
            "comparison-node-invocation-cleanup")
    require(portable.get("cleanup") == "owned-native-host-reaped", "comparison-native-cleanup")
    left, right = node["identity"], portable["identity"]
    require(left.get("os") == "linux" and left.get("profile") in {"local-experimental-v1", "external-capsule-v1"}
            and left.get("admission") in {"trusted-local", "enforced"}, "comparison-real-linux-node-identity")
    require(right.get("productionNode") is False and set(portable.get("excludedChecks", [])) == NODE_ONLY,
            "comparison-native-exclusions-required")
    for name in ("component", "capsule", "contracts"):
        sha(left["artifacts"][name])
        require(left["artifacts"][name] == right["artifacts"][name], "comparison-exact-artifact-bytes")
    require(left["package"]["componentDigest"] == left["artifacts"]["component"]
            and left["deployment"]["componentDigest"] == left["artifacts"]["component"], "comparison-node-package-component")
    runtime = right["runtime"]
    runs = runtime.get("runs")
    require(runtime.get("execution") == "actual-component-production-wasmtime"
            and isinstance(runs, list) and 0 < len(runs) <= 8, "comparison-actual-native-host")
    for run in runs:
        require(run.get("schemaVersion") == "latent.dev.portable-result.v1" and run.get("productionNode") is False
                and run.get("environment") == "portable" and run.get("os") == "windows"
                and run.get("architecture") == "x86_64" and run.get("component") == left["artifacts"]["component"]
                and run.get("wasmtime") == left["runtime"]["engine"]["wasmtimeVersion"],
                "comparison-qualified-native-platform-required")
    rows = []
    for actual, native in zip(node["results"], portable["results"]):
        sha(actual.get("inputSha256"))
        if actual.get("category") in {"success", "declared-error"}:
            sha(actual.get("payloadSha256"))
        require(actual.get("targetMatches") is True and isinstance(actual.get("resolvedRevision"), dict)
                and native.get("resolvedRevision") is None, "comparison-node-revision-required")
        expected = actual.get("expectedRevision", left["expectedRevision"])
        require(isinstance(expected, dict)
                and {"publicationId", "releaseDigest", "routeGeneration"} <= expected.keys()
                <= {"publicationId", "releaseDigest", "routeGeneration", "revisionId"}
                and all(expected[key] == left["expectedRevision"][key] for key in ("publicationId", "releaseDigest")),
                "comparison-case-publication-identity")
        require(all(actual["resolvedRevision"].get(key) == value for key, value in expected.items()),
                "comparison-node-selected-revision")
        keys = ("id", "inputSha256", "category", "payloadSha256", "platformCode", "fixtures", "execution")
        require(all(actual.get(key) == native.get(key) for key in keys), "comparison-typed-result-mismatch")
        rows.append({key: actual.get(key) for key in keys})
    return {"schemaVersion": "latent.dev.node-portable-comparison.v1", "passed": True,
        "qualificationComplete": False, "scope": "selected-typed-application-values",
        "nodeReportSha256": digest(encode(node)), "portableReportSha256": digest(encode(portable)),
        "artifacts": right["artifacts"], "selection": node["selection"], "results": rows,
        "nodeProfile": left["profile"], "nodeAdmission": left["admission"],
        "reviewedDifferences": ["node-only-publication-admission-and-routing", "host-os-and-architecture",
            "bounded-cold-node-preparation-deadline", "system-clock-and-entropy-not-compared"],
        "portableExcludedChecks": portable["excludedChecks"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("node", "portable", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    arguments = parser.parse_args()
    require(not arguments.output.exists(), "new-comparison-output-required")
    reports = [decode(path.read_bytes(), 4 * 1024 * 1024) for path in (arguments.node, arguments.portable)]
    result = compare(*reports)
    arguments.output.write_bytes(encode(result))
    print("Same-component Linux-node and native Windows scenarios passed")


if __name__ == "__main__":
    main()
