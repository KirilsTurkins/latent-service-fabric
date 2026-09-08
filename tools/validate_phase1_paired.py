#!/usr/bin/env python3
"""Replay every paired statistic and artifact association from retained bytes."""
import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase1_evidence.common import EvidenceError, canonical, read_json, require, verify_artifact
from tools.phase1_paired.aggregate import aggregate
from tools.phase1_paired.suite import validate


def replay(path):
    path = path.resolve()
    retained = read_json(path)
    source = verify_artifact(path.parent, retained.get("source"))
    regenerated = aggregate(source, path.parent)
    require(canonical(retained) == canonical(regenerated), "paired-aggregate-does-not-match-evidence")
    return regenerated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--suite", type=Path)
    group.add_argument("--aggregate", type=Path)
    args = parser.parse_args()
    try:
        result = replay(args.aggregate) if args.aggregate else validate(args.suite)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("Paired validation failed: " + (str(error) if isinstance(error, EvidenceError) else "invalid-evidence"), file=sys.stderr)
        return 2
    print("Validated controlled comparison evidence.")
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
