#!/usr/bin/env python3
"""Qualify independently compiled C projects, real admission, ownership and guide."""
from __future__ import annotations

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
    parser.add_argument("--offline", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(qualify(arguments.output, offline=arguments.offline, language="c")))
