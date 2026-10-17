#!/usr/bin/env python3
"""Build the actual source-owned asynchronous typed-import compiler input."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.typescript_guest.splicer_build import build

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tools',type=Path,required=True)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.output,arguments.tools)))
