#!/usr/bin/env python3
"""Explicit hosted LLVM compiler producer; no guest/runtime execution."""
from pathlib import Path
import argparse
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_guest.llvm_ssa_producer import admission, produce
from tools.java_guest.llvm_ssa_distribution import admit_upload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--admit-upload', action='store_true')
    args = parser.parse_args()
    if args.admit_upload:
        origin = admission(args.output, artifact_only=True)
        print(json.dumps(admit_upload(args.output, origin['sourceCommit'],
                                     time.monotonic() + min(120, 95 * 60 - (time.time() - origin['startedEpoch'])))))
        return
    result = produce(args.output)
    print(json.dumps({'status': result['status'], 'profile': result['profile'],
                      'units': result['tests']['units']['passed'],
                      'originalSjLjFiles': result['tests']['originalSjLj']['passed'],
                      'javaComponentQualification': False, 'javaRuntimeQualification': False}))


if __name__ == '__main__':
    main()
