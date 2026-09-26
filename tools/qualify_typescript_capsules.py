#!/usr/bin/env python3
"""Qualify captured TypeScript projects, SDK ownership, enforced node and guide."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.qualify_rust_capsules import qualify


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tools", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.output, language="typescript", typescript_tools=args.tools)))
