#!/usr/bin/env python3
"""Replay an optimization suite and optionally write/check its exact aggregate."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.optimization_evidence.common import EvidenceError, canonical, read_json, require
from tools.optimization_evidence.suite import validate_suite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("--aggregate", type=Path)
    parser.add_argument("--check-aggregate", type=Path)
    arguments = parser.parse_args()
    try:
        aggregate = validate_suite(arguments.suite)
        if arguments.check_aggregate:
            require(read_json(arguments.check_aggregate) == aggregate, "aggregate-replay-mismatch")
        if arguments.aggregate:
            with arguments.aggregate.open("xb") as destination:
                destination.write(canonical(aggregate) + b"\n")
        print(json.dumps({key: aggregate[key] for key in ("schema", "profile", "status", "validated_attempts",
                                                        "population_complete")}, sort_keys=True))
        return 1 if aggregate["status"] == "failed" else 0
    except (EvidenceError, OSError, KeyError, TypeError, ValueError):
        print("Optimization evidence validation failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
