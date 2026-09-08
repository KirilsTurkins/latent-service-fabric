#!/usr/bin/env python3
"""Collect normal and separately profiled artifact-identity paired evidence."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))
sys.path.insert(0, str(REPOSITORY / "tools"))

from artifact_identity_runner.collect import execute


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-ref", required=True)
    parser.add_argument("--candidate-ref", required=True)
    parser.add_argument("--component", required=True, type=Path)
    parser.add_argument("--capsule", required=True, type=Path)
    parser.add_argument("--contracts", required=True, type=Path)
    parser.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        return execute(args, REPOSITORY)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"artifact identity collection could not start: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
