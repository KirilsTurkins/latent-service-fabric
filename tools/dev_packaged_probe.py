#!/usr/bin/env python3
"""Drive explicitly approved packaged candidates from an isolated qualification directory."""
import argparse
from pathlib import Path
import sys

# Isolated mode omits the script directory. Add only this separately staged,
# reviewed conductor directory; never a candidate project or LSF checkout.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dev_packaged_process import read_json
from dev_packaged_windows import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(read_json(args.inputs.absolute()), args.output.absolute())
    print('Packaged Windows schedule passed:', result['passed'])


if __name__ == '__main__':
    main()
