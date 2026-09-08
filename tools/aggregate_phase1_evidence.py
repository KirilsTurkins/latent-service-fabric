#!/usr/bin/env python3
"""Aggregate retained Phase 1 measurements, preserving failures and per-kind scope."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

try:
    from .phase1_evidence.aggregate import aggregate_suites
    from .phase1_evidence.common import EvidenceError, write_json
except ImportError:
    from phase1_evidence.aggregate import aggregate_suites
    from phase1_evidence.common import EvidenceError, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = aggregate_suites(arguments.suite, arguments.output.parent)
        write_json(arguments.output, result)
    except (EvidenceError, OSError, ValueError) as error:
        reason = str(error) if isinstance(error, EvidenceError) else "invalid-evidence"
        print("Phase 1 aggregation failed: " + reason, file=sys.stderr)
        return 2
    print("Validated Phase 1 " + result["profile"] + " measurement aggregate; full phase completion remains incomplete.")
    return 1 if any(group["status"] == "failed" for group in result["kinds"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
