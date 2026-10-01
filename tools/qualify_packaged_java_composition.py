#!/usr/bin/env python3
"""Execute approved native packages against fresh maintained Java composition."""
from pathlib import Path
import argparse
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_packaged_process import read_json
from tools.java_http_composition.packaged import qualify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    selected = parser.parse_args()
    qualify(read_json(selected.inputs), selected.output.absolute())


if __name__ == "__main__":
    main()
