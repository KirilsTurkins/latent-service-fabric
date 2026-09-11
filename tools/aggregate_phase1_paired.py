#!/usr/bin/env python3
"""Validate retained controlled arms and compute paired process contrasts."""
import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase1_evidence.common import EvidenceError, write_json
from tools.phase1_paired.aggregate import aggregate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = aggregate(args.suite, args.output.parent)
        write_json(args.output, result)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("Paired aggregation failed: " + (str(error) if isinstance(error, EvidenceError) else "invalid-evidence"), file=sys.stderr)
        return 2
    print("Validated paired observations; comparison status=" + result["status"] + "; Phase 1 completion remains incomplete.")
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
