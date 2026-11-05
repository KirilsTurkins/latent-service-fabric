#!/usr/bin/env python3
"""Produce bounded source-reconstruction material; this grants no authority."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

MAGIC = b'LSFDLT01'
MAX_ORIGINAL = 1024 * 1024
MAX_BASE = 2 * 1024 * 1024
MAX_DELTA = 1024 * 1024
MAX_COMMANDS = 32768
WINDOW = 16
MAX_CANDIDATES = 4


def encode(original: bytes, base: bytes) -> bytes:
    """Copy from the unwrapped component, or include literal original bytes.

    The receiver must independently validate the complete component and the
    reconstructed original. This representation itself authenticates nothing.
    """
    if not (8 <= len(original) <= MAX_ORIGINAL and len(base) <= MAX_BASE):
        raise ValueError('rust-delta-input-bound')
    index: dict[bytes, list[int]] = {}
    for offset in range(0, len(base) - WINDOW + 1, WINDOW):
        key = base[offset:offset + WINDOW]
        candidates = index.setdefault(key, [])
        if len(candidates) < MAX_CANDIDATES:
            candidates.append(offset)
    body = bytearray()
    literal = bytearray()
    count = 0

    def append(command: bytes) -> None:
        nonlocal count
        count += 1
        if count > MAX_COMMANDS or len(body) + len(command) + 16 > MAX_DELTA:
            raise ValueError('rust-delta-encoding-bound')
        body.extend(command)

    def flush() -> None:
        if literal:
            append(struct.pack('<BI', 1, len(literal)) + literal)
            literal.clear()

    cursor = 0
    while cursor + WINDOW <= len(original):
        longest, location = 0, 0
        for offset in index.get(original[cursor:cursor + WINDOW], ()):
            size = WINDOW
            while (cursor + size < len(original) and offset + size < len(base)
                   and original[cursor + size] == base[offset + size]):
                size += 1
            if size > longest:
                longest, location = size, offset
        if longest >= WINDOW:
            flush()
            append(struct.pack('<BII', 0, location, longest))
            cursor += longest
        else:
            literal.append(original[cursor])
            cursor += 1
    literal.extend(original[cursor:])
    flush()
    if count == 0:
        raise ValueError('rust-delta-empty')
    return MAGIC + struct.pack('<II', len(original), count) + body


def read_bounded(path: Path, maximum: int) -> bytes:
    with path.open('rb') as source:
        value = source.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError('rust-delta-input-bound')
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', required=True, type=Path)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    original, base = read_bounded(args.original, MAX_ORIGINAL), read_bounded(args.base, MAX_BASE)
    encoded = encode(original, base)
    with args.output.open('xb') as output:
        output.write(encoded)
    print(json.dumps({'originalBytes': len(original), 'baseBytes': len(base),
                      'deltaBytes': len(encoded), 'commands': struct.unpack_from('<I', encoded, 12)[0],
                      'deltaSha256': hashlib.sha256(encoded).hexdigest()}, sort_keys=True))


if __name__ == '__main__':
    main()
