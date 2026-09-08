#!/usr/bin/env python3
"""Strictly replay the separately archived same-current-collector diagnostic."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from tools.optimization_backend_revision import validate_suite
from tools.optimization_evidence.common import canonical, read_json, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("--aggregate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = validate_suite(args.suite)
        if args.aggregate:
            require(canonical(read_json(args.aggregate)) == canonical(result), "backend-aggregate-does-not-replay")
        if args.output:
            with args.output.open("xb") as destination:
                destination.write(canonical(result) + b"\n")
        print(f"{result['status']}: {result['validated_calls']} calls; population_complete={result['population_complete']}")
        return 1 if result["status"] == "failed" else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Backend revision evidence invalid: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
