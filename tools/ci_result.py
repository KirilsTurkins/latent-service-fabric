#!/usr/bin/env python3
"""Fail closed when any selected CI job fails, is cancelled, or is skipped."""
from __future__ import annotations

import json
import os
import sys

PRODUCT = frozenset({"rust", "oci-registry", "catalog", "msrv", "contracts", "sdks"})
COMMON = frozenset({"profile", "docs", "website"})


def failures(results: dict) -> list[str]:
    if not isinstance(results, dict) or set(results) != PRODUCT | COMMON:
        return ["invalid-job-inventory"]
    if any(not isinstance(value, dict) or value.get("result") not in
           {"success", "failure", "cancelled", "skipped"} for value in results.values()):
        return ["invalid-job-state"]
    outputs = results["profile"].get("outputs", {})
    profile = outputs.get("profile") if isinstance(outputs, dict) else None
    if profile not in {"docs", "website", "full"}:
        return ["unknown-profile"]
    required = COMMON | (PRODUCT if profile == "full" else frozenset())
    failed = [name for name in sorted(required) if results[name]["result"] != "success"]
    if profile != "full":
        failed += [name for name in sorted(PRODUCT) if results[name]["result"] != "skipped"]
    return failed


def main() -> int:
    encoded = os.environ.get("CI_JOB_RESULTS", "")
    try:
        if len(encoded.encode()) > 65536:
            raise ValueError("job-result-bound")
        rejected = failures(json.loads(encoded))
    except (ValueError, TypeError, RecursionError):
        rejected = ["invalid-job-results"]
    if rejected:
        print("CI did not satisfy its selected profile: " + ", ".join(rejected), file=sys.stderr)
        return 1
    print("Every selected CI job passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
