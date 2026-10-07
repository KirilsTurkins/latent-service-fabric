#!/usr/bin/env python3
"""Generate and check an explicitly selected typed Java HTTP adapter."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

sys.dont_write_bytecode = True
if __package__ in {None, ""}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.java_http_generation.project import generate, check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "check"))
    parser.add_argument("domain", type=Path, help="Independent Java domain project")
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (generate if args.command == "generate" else check)(args.domain, args.selection, args.output)
        print(result)
    except (ValueError, OSError, RuntimeError) as error:
        print("Java HTTP generation failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
