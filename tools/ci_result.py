#!/usr/bin/env python3
"""Fail closed on the complete, independently recomputed selected CI job set."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_suite_inventory as registry


def validate(results: dict, data: dict | None = None) -> set[str]:
    data = registry.load() if data is None else data
    registry.require(isinstance(results, dict) and set(results) == registry.ALL_JOBS, "missing-or-unexpected-job")
    for value in results.values():
        registry.require(isinstance(value, dict) and value.get("result") in {
            "success", "failure", "cancelled", "skipped"}, "missing-or-invalid-job-result")
    registry.require(results["profile"]["result"] == "success", "profile-did-not-succeed")
    outputs = results["profile"].get("outputs")
    registry.require(isinstance(outputs, dict) and all(k in outputs for k in (
        "profile", "reason", "changed_files", "renderer", "fast_packages", "expected_jobs")), "missing-selection-output")
    profile = outputs["profile"]
    registry.require(isinstance(outputs["reason"], str) and outputs["reason"], "missing-selection-reason")
    registry.require(isinstance(outputs["changed_files"], str) and outputs["changed_files"].isdigit(), "invalid-change-count")
    registry.require(outputs["renderer"] in {"true", "false"}, "missing-renderer-selection")
    packages = json.loads(outputs["fast_packages"])
    registry.require(isinstance(packages, list) and all(isinstance(p, str) for p in packages), "invalid-host-selection")
    registry.require(packages == sorted(set(packages)) and set(packages) <= set(data["fastPackages"]), "unregistered-host-selection")
    registry.require(profile != "full" or packages, "missing-full-host-selection")
    registry.require(profile not in {"docs", "website"} or outputs["renderer"] == "false", "invalid-docs-selection")
    required = registry.expected_jobs(profile, packages)
    registry.require(json.loads(outputs["expected_jobs"]) == sorted(required), "selected-job-set-mismatch")
    for name, value in results.items():
        expected = "success" if name in required else "skipped"
        registry.require(value["result"] == expected, f"unexpected-job-result:{name}:{value['result']}")
    return required


def main() -> int:
    try:
        encoded = os.environ.get("CI_JOB_RESULTS", "")
        registry.require(len(encoded) <= 65536, "job-results-limit")
        results = json.loads(encoded, object_pairs_hook=registry.unique_object)
        required = validate(results)
        print("Required CI jobs passed:", ", ".join(sorted(required)))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(f"CI did not satisfy its selected job contract: {error}", file=sys.stderr)
        return 1



if __name__ == "__main__":
    raise SystemExit(main())
