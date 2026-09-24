#!/usr/bin/env python3
"""Compare actual typed output bytes and component identities across native hosts."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dev_workflow.common import decode, digest, encode, require, sha
from tools.dev_workflow import paths


def projection(report: dict, expected_os: str) -> dict:
    require(report.get("schemaVersion") == "latent.dev.portable-applications.v1"
        and report.get("os") == expected_os and report.get("passed") is True
        and report.get("execution") == "actual-component-production-wasmtime"
        and report.get("compilerInExecutionPath") is False and report.get("outsideCheckout") is True
        and report.get("cleanup") == "owned-processes-reaped", "native-receipt-required")
    require(set(report["applications"]) == {"greeting", "word-count", "shipping"}, "common-applications-required")
    applications = {}
    for name, app in report["applications"].items():
        require(app["passed"] is True and app["environment"] == "portable"
            and app["cleanup"] == "owned-native-host-reaped", "native-application-incomplete")
        runs = app["identity"]["runtime"]["runs"]
        require(runs and all(run["os"].casefold() == expected_os.casefold()
            and run["productionNode"] is False for run in runs), "cross-host-receipt-mismatch")
        require(app["results"] and all(case["status"] == "passed" and case["outcomeKnown"] is True
            and case["category"] in {"success", "declared-error"} for case in app["results"]), "required-native-results-missing")
        applications[name] = {"artifacts": app["identity"]["artifacts"], "hostAbi": app["identity"]["hostAbi"],
            "runtimeProfiles": [run["runtimeProfile"] for run in runs],
            "cases": [{key: case[key] for key in ("id", "category", "inputSha256", "payloadSha256", "platformCode")}
                      for case in app["results"]]}
        for case in applications[name]["cases"]:
            sha(case["inputSha256"])
            sha(case["payloadSha256"])
    return {"language": report["language"], "ownerIssue": report["ownerIssue"], "applications": applications}


def compare(windows: bytes, linux: bytes) -> dict:
    left = projection(decode(windows, 4 * 1024 * 1024), "Windows")
    right = projection(decode(linux, 4 * 1024 * 1024), "Linux")
    require(left == right, "native-windows-linux-differential-mismatch")
    return {"schemaVersion": "latent.dev.portable-differential.v1", "passed": True, "language": left["language"],
        "windowsReceipt": digest(windows), "linuxReceipt": digest(linux), "observed": left,
        "qualification": "native-tutorial-subset-only", "excludedChecks": ["node-admission", "provider-clock-values", "clean-host-install"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("windows", "linux", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.write_bytes(encode(compare(
        paths.read(args.windows.absolute().parent, args.windows.name, 4 * 1024 * 1024),
        paths.read(args.linux.absolute().parent, args.linux.name, 4 * 1024 * 1024))))
    print("Native Windows/Linux tutorial outputs match")
