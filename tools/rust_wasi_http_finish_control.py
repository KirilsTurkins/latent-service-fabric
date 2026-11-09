"""Extract the actual bounded outgoing-body finish method for native doubles."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'sdk/wasi-http-runtime/types.rs'
START = b'    fn finish(\n        this: types::OutgoingBody,'
END = b'\n}\nimpl Drop for OutgoingBody'


def extract(output: Path) -> None:
    source = SOURCE.read_bytes()
    if len(source) > 1024 * 1024 or source.count(START) != 1 or source.count(END) != 1:
        raise ValueError('rust-http-finish-exact-source-bound')
    start = source.index(START)
    end = source.index(END, start)
    method = source[start:end]
    if not method or len(method) > 16 * 1024:
        raise ValueError('rust-http-finish-method-bound')
    if output.is_symlink() or output.exists():
        raise ValueError('rust-http-finish-fresh-output')
    with output.open('xb') as target:
        target.write(b'impl OutgoingBody {\n' + method + b'\n}\n')
    if SOURCE.read_bytes() != source:
        raise ValueError('rust-http-finish-source-changed')
    print('rust-http-outgoing-finish-sha256=' + hashlib.sha256(method).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    extract(parser.parse_args().output)
