#!/usr/bin/env python3
"""Qualify independent Go builds, signed SDK execution, real node and printed guide."""
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
    print(json.dumps(qualify(parser.parse_args().output, language="go")))
