#!/usr/bin/env python3
"""Collect the fixed scheduler suite using retained libtest binaries."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from tools.optimization_scheduler.collect import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "full"), required=True)
    parser.add_argument("--builds", type=Path, required=True)
    try:
        return execute(parser.parse_args(), ROOT)
    except (OSError, ValueError, TimeoutError) as error:
        parser.exit(1, f"scheduler collection failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
