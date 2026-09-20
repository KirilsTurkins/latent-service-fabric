#!/usr/bin/env python3
"""Fail-closed verification of an expected injected failure, never retry-to-green."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def check(root: Path, suite: str, reason: str) -> None:
    paths = list(root.glob('*.json'))
    if len(paths) != 1:
        raise ValueError('expected one fresh fault diagnostic')
    with paths[0].open('rb') as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError('diagnostic limit')
    record = json.loads(raw)
    if not (record.get('schemaVersion') == 'latent.test-run.v1' and record.get('suite') == suite
            and record.get('outcome') == 'failed' and record.get('reason') == reason
            and record.get('child', {}).get('cleanupAcknowledged') is True
            and record.get('cleanupFailures') == []
            and record.get('reproduction', {}).get('fault') == reason.removeprefix('injected-')
            and record.get('source', {}).get('observed') is True
            and record.get('fixtures')):
        raise ValueError('expected failure or cleanup evidence missing')
    print(json.dumps({'suite': suite, 'expectedFault': reason, 'cleanupVerified': True}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--suite', required=True)
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    check(args.root, args.suite, args.reason)


if __name__ == '__main__':
    main()
