#!/usr/bin/env python3
"""Explicit R8 source-qualified compiler producer; never a guest execution."""
from pathlib import Path
import argparse
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.java_guest.llvm_private_store_producer import admission, produce
from tools.java_guest.llvm_private_store_distribution import admit_upload


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
    tests = result['tests']['sjljAndPrivateScalar']
    print(json.dumps({'status': result['status'], 'profile': result['profile'],
        'units': result['tests']['units']['passed'], 'originalSjLjFiles': tests['originalSjLj']['passed'],
        'privateScalarFiles': tests['privateScalar']['passed'],
        'javaComponentQualification': False, 'javaRuntimeQualification': False}))


if __name__ == '__main__':
    main()
