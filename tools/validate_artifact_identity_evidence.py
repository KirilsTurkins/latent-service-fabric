#!/usr/bin/env python3
"""Offline replay of retained artifact identity comparisons; never runs a binary."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.artifact_identity_evidence import validate_suite
from tools.artifact_identity_evidence.common import canonical, read_json, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("--aggregate", type=Path)
    parser.add_argument("--check-aggregate", type=Path)
    args = parser.parse_args()
    try:
        result = validate_suite(args.suite)
        if args.check_aggregate:
            require(read_json(args.check_aggregate) == result, "aggregate-replay-mismatch")
        if args.aggregate:
            with args.aggregate.open("xb") as output:
                output.write(canonical(result) + b"\n")
        print(json.dumps({key: result[key] for key in ("schema", "profile", "status", "validated_runs", "full_comparison_qualified")}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, EOFError) as error:
        print(f"Artifact identity evidence validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
