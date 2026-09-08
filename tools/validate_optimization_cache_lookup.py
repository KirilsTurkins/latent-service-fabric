#!/usr/bin/env python3
"""Replay cache lookup evidence without running retained executables."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.optimization_cache_lookup.evidence import validate_suite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = validate_suite(args.suite)
        value = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        if args.output:
            args.output.write_text(value, encoding="utf-8")
        else:
            print(value, end="")
        return 1 if result["status"] == "failed" else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"cache lookup replay failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
