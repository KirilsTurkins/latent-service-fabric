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


def run(credential: Path, *, certificate: Path | None = None, private_key: Path | None = None):
    if (certificate is None) != (private_key is None):
        raise ValueError('standard-http-tls-certificate-key-pair-required')
    if certificate is not None:
        for path in (certificate, private_key):
            if not path.is_absolute() or path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 65536:
                raise ValueError('standard-http-tls-regular-bounded-input-required')
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
    if certificate is None:
        peer = Peer(authorization, maximum_seconds=300)
    else:
        from tools.standard_http.tls_peer import TLSPeer
        peer = TLSPeer(authorization, certificate, private_key, maximum_seconds=300)
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
    parser.add_argument('--certificate', type=Path)
    parser.add_argument('--private-key', type=Path)
    args = parser.parse_args()
    run(args.credential, certificate=args.certificate, private_key=args.private_key)
