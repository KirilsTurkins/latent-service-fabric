#!/usr/bin/env python3
"""Semantically replay scheduler evidence without executing retained binaries."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.optimization_evidence.common import canonical, read_json, require
from tools.optimization_scheduler.evidence import validate_suite
from tools.optimization_scheduler.model import MAX_AGGREGATE_BYTES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("--aggregate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = validate_suite(args.suite)
        encoded = canonical(result) + b"\n"
        require(len(encoded) <= MAX_AGGREGATE_BYTES, "scheduler-aggregate-byte-bound")
        if args.aggregate:
            require(canonical(read_json(args.aggregate, MAX_AGGREGATE_BYTES)) == canonical(result), "scheduler-aggregate-replay-mismatch")
        if args.output:
            require(args.output.resolve() != args.suite.resolve() and (args.aggregate is None or args.output.resolve() != args.aggregate.resolve()),
                    "scheduler-replay-output-overwrites-input")
            args.output.write_bytes(encoded)
        else:
            print(encoded.decode("utf-8"), end="")
        return 1 if result["status"] == "failed" or result["profile"] == "full" and not result["acceptance_qualified"] else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"scheduler replay failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
