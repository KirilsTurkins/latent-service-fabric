#!/usr/bin/env python3
"""Run the existing signed borrow programme with same-workflow source products."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.typescript_guest.borrow_current_controls import qualify

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('tools', 'engine', 'splicer', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.tools, args.engine, args.splicer, args.output)))
