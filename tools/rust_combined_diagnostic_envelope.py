#!/usr/bin/env python3
"""Build one untrusted proof-carrying component for the diagnostic host.

The host independently checks the component and original source; this tool
only frames bounded bytes and never selects a runtime or grants authority.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import rust_original_delta as delta

NAME = b'latent-rust-original-delta-v1'
COMPONENT = b'\0asm\x0d\0\x01\0'
MAX_SECTIONS = 256


def u32(value: int) -> bytes:
    if type(value) is not int or not 0 <= value <= 0xffffffff:
        raise ValueError('rust-delta-framing-u32')
    result = bytearray()
    while True:
        part, value = value & 0x7f, value >> 7
        result.append(part | (0x80 if value else 0))
        if not value:
            return bytes(result)


def read_u32(raw: bytes, cursor: int) -> tuple[int, int]:
    start, value = cursor, 0
    for shift in range(0, 35, 7):
        if cursor >= len(raw):
            raise ValueError('rust-delta-framing-truncated')
        byte = raw[cursor]
        cursor += 1
        if shift == 28 and byte > 15:
            raise ValueError('rust-delta-framing-overflow')
        value |= (byte & 0x7f) << shift
        if byte < 0x80:
            if raw[start:cursor] != u32(value):
                raise ValueError('rust-delta-framing-noncanonical')
            return value, cursor
    raise ValueError('rust-delta-framing-overflow')


def frame(base: bytes, proof: bytes) -> bytes:
    if len(base) > delta.MAX_BASE or base[:8] != COMPONENT:
        raise ValueError('rust-delta-framing-component')
    if not 16 <= len(proof) <= delta.MAX_DELTA or proof[:8] != delta.MAGIC:
        raise ValueError('rust-delta-framing-proof')
    cursor, count = 8, 0
    while cursor < len(base):
        count += 1
        if count > MAX_SECTIONS:
            raise ValueError('rust-delta-framing-sections')
        kind = base[cursor]
        size, body = read_u32(base, cursor + 1)
        end = body + size
        if end > len(base):
            raise ValueError('rust-delta-framing-truncated')
        if kind == 0:
            length, start = read_u32(base, body)
            if length > 512 or start + length > end:
                raise ValueError('rust-delta-framing-name')
            if base[start:start + length] == NAME:
                raise ValueError('rust-delta-framing-duplicate')
        cursor = end
    if count >= MAX_SECTIONS:
        raise ValueError('rust-delta-framing-sections')
    payload = u32(len(NAME)) + NAME + proof
    result = base + b'\x00' + u32(len(payload)) + payload
    if len(result) > delta.MAX_BASE:
        raise ValueError('rust-delta-framing-byte-bound')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--component', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    original = delta.read_bounded(args.original, delta.MAX_ORIGINAL)
    base = delta.read_bounded(args.component, delta.MAX_BASE)
    proof = delta.encode(original, base)
    result = frame(base, proof)
    with args.output.open('xb') as output:
        output.write(result)
    print(json.dumps({'originalBytes': len(original), 'componentBytes': len(base),
                      'proofBytes': len(proof), 'wrappedBytes': len(result),
                      'wrappedSha256': hashlib.sha256(result).hexdigest(),
                      'authenticated': False, 'runtimeQualified': False}, sort_keys=True))


if __name__ == '__main__':
    main()
