"""Owned finite subprocess for the language-independent HTTP conformance peer."""
import argparse
import json
from pathlib import Path
import signal
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.standard_http.peer import Peer


def run(credential: Path):
    stopping = False

    def stop(_number, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if credential.is_symlink() or not credential.is_file() or credential.stat().st_mode & 0o077:
        raise ValueError('standard-http-private-credential-required')
    with credential.open('rb') as source:
        authorization = source.read(129)
    peer = Peer(authorization, maximum_seconds=300)
    try:
        print(json.dumps({'destinations': peer.provider_destinations(), 'origins': {
            role: peer.origin(role) for role in ('primary', 'secondary')}}), flush=True)
        while not stopping and time.monotonic() < peer.deadline:
            peer.poll(.1)
        if not stopping:
            raise ValueError('standard-http-peer-deadline')
    finally:
        peer.close()
    result = peer.observation()
    if result['failure'] is not None:
        raise ValueError('standard-http-peer-failed')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credential', required=True, type=Path)
    run(parser.parse_args().credential)
