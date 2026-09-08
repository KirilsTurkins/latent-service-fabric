#!/usr/bin/env python3
"""Run the separate backend diagnostic in its already populated build archive directory."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from tools.optimization_backend_revision.collect import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--experiment", choices=("warm", "cold"), default="warm",
                        help="cold selects the separate #101 population and schemas")
    parser.add_argument("--builds", type=Path, required=True, help="backend-builds.json; its parent receives the new suite")
    parser.add_argument("--target-root", type=Path, default=ROOT / "target")
    try:
        return execute(parser.parse_args(), ROOT)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Backend revision diagnostic failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
