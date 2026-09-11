#!/usr/bin/env python3
"""Validate a Phase 1 raw run, suite, or replayable aggregate without executing guests."""

import argparse
from pathlib import Path
import sys

try:
    from .phase1_evidence.common import EvidenceError
    from .phase1_evidence.raw import read_raw
    from .phase1_evidence.replay import validate_aggregate, validate_comparison
    from .phase1_evidence.suite import validate_suite
except ImportError:
    from phase1_evidence.common import EvidenceError
    from phase1_evidence.raw import read_raw
    from phase1_evidence.replay import validate_aggregate, validate_comparison
    from phase1_evidence.suite import validate_suite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selected = parser.add_mutually_exclusive_group(required=True)
    for name in ("raw", "suite", "aggregate", "comparison"):
        selected.add_argument("--" + name, type=Path)
    parser.add_argument("--phase0-runs", type=Path, help="Extracted verified reference runs when replaying matched Phase0 populations")
    args = parser.parse_args()
    try:
        if args.raw:
            read_raw(args.raw)
        elif args.suite:
            validate_suite(args.suite)
        elif args.aggregate:
            validate_aggregate(args.aggregate)
        else:
            validate_comparison(args.comparison, args.phase0_runs)
    except (ValueError, OSError) as error:
        print("Phase 1 evidence invalid: " + (str(error) if isinstance(error, EvidenceError) else "invalid-evidence"), file=sys.stderr)
        return 2
    print("Phase 1 evidence validated; selected scope and incompleteness are retained.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
