#!/usr/bin/env python3
"""Trusted compiler leaf: preserve a nonzero exit without losing bounded logs.

The parent runs this wrapper with tools.build_process.run_bounded. The compiler
inherits that owned process group/job and the same bounded output streams. Do
not start a new session, capture unbounded output, or launch a background worker.
The status file is private to a new attempt; this helper is not a build sandbox.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit('usage: capture.py STATUS_FILE COMMAND [ARG ...]')
    status_file = Path(sys.argv[1])
    try:
        status = {'returncode': subprocess.call(sys.argv[2:])}
    except OSError as error:
        print(f'compiler spawn failed: {error}', file=sys.stderr)
        status = {'spawnError': type(error).__name__}
    # A separate status keeps arbitrary compiler stdout out of the protocol.
    with status_file.open('x', encoding='utf-8') as stream:
        json.dump(status, stream)
        stream.write('\n')


if __name__ == '__main__':
    main()
