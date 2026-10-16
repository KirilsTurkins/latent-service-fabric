"""Bounded terminal-only matching of public Go panic string/decimal families."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CATALOGUE_SHA256 = '9a533f0dcc67bfd9b81af2b8233e81706513e1bc454b4a9de1f94f1964876554'
STRING_TYPE = 1280848
DATA_SHA256 = 'fc6030959800261f84ae05104787b334cc6235f658d68a3d868ea8679530a73b'
PROOFS = {
    'runtime.fatalpanic': 'f04f62f1557b76b18fdf9c703847ee390aa7a83b5608bacdd1e56fa3df462f68',
    'runtime.preprintpanics': '7a2d1ffd5fc1e5c0c35d388b47660342b3d166bbb6276b26d7f2df91b8a78a46',
    'runtime.gopanic': '4d86d20de72b705da92582181b0d4153195f5f92a12945248168e22e85a8e75a',
}


def reasons() -> list[dict]:
    raw = Path(__file__).with_name('terminal_panic_reasons.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOGUE_SHA256:
        raise ValueError('Go-private-panic-catalogue-preimage')
    rows = json.loads(raw)['reasons']
    if not 1 <= len(rows) <= 127 or [row['id'] for row in rows] != list(range(1, len(rows)+1)):
        raise ValueError('Go-private-panic-catalogue-inventory')
    return rows


def _leb(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        if (value == 0 and not byte & 64) or (value == -1 and byte & 64):
            result.append(byte)
            return bytes(result)
        result.append(byte | 128)


def _const(value: int) -> bytes:
    return b'\x41' + _leb(value)


def _get(index: int) -> bytes:
    return b'\x20' + bytes([index])


def _set(index: int) -> bytes:
    return b'\x21' + bytes([index])


def _memory_bytes() -> bytes:
    return b'\x3f\0\xad\x42\x10\x86'


def _require(condition: bytes) -> bytes:
    return condition + b'\x45\x04\x40\0\x0b'


def _pointer(expression: bytes, target: int, size: int) -> bytes:
    # Check the complete 64-bit Go pointer before any wrapping memory load.
    code = expression + b'\x22\x09\xa7' + _set(target)
    valid = _get(9) + _get(target) + b'\xad\x51'
    valid += _get(target) + b'\x45\x45\x71'
    valid += _get(target) + b'\xad\x42' + _leb(size) + b'\x7c' + _memory_bytes() + b'\x58\x71'
    return code + _require(valid)


def _byte_at_cursor() -> bytes:
    return _get(1) + _get(5) + b'\x6a\x2d\0\0'


def _increment_cursor() -> bytes:
    return _get(5) + _const(1) + b'\x6a' + _set(5)


def _literal(value: bytes) -> bytes:
    code = _get(5) + _const(len(value)) + b'\x6a' + _get(2) + b'\x4d\x04\x40'
    for offset, byte in enumerate(value):
        code += _get(6) + _get(1) + _get(5) + b'\x6a\x2d\0' + _leb(offset)
        code += _const(byte) + b'\x46\x71' + _set(6)
    code += _get(5) + _const(len(value)) + b'\x6a' + _set(5)
    return code + b'\x05' + _const(0) + _set(6) + b'\x0b'


def _decimal(signed: bool, maximum: int) -> bytes:
    code = b''
    if signed:
        code += _get(5) + _get(2) + b'\x49\x04\x40'
        code += _byte_at_cursor() + _const(45) + b'\x46\x04\x40'
        code += _increment_cursor() + b'\x0b\x0b'
    code += _const(0) + _set(7) + b'\x02\x40\x03\x40'
    code += _get(5) + _get(2) + b'\x4f\x0d\x01'
    code += _byte_at_cursor() + _set(8)
    code += _get(8) + _const(48) + b'\x49' + _get(8) + _const(57) + b'\x4b\x72\x0d\x01'
    code += _get(7) + _const(maximum) + b'\x4f\x04\x40'
    code += _const(0) + _set(6) + b'\x0c\x02\x0b'
    code += _increment_cursor() + _get(7) + _const(1) + b'\x6a' + _set(7)
    code += b'\x0c\0\x0b\x0b'
    return code + _get(6) + _get(7) + b'\x45\x45\x71' + _set(6)


def body(bit: int, *, candidate: int | None = None) -> bytes:
    rows = reasons()
    if type(bit) is not int or not 0 <= bit < len(rows).bit_length():
        raise ValueError('Go-private-panic-bit-bound')
    if candidate is not None and (type(candidate) is not int or not 1 <= candidate <= len(rows)):
        raise ValueError('Go-private-panic-candidate-bound')
    # Param0 is Go's continuation PC. Locals1..8 are bounded i32 values;
    # local9 retains the untruncated Go pointer for range validation.
    code = b'\x02\x08\x7f\x01\x7e'
    code += _require(b'\x23\0\xad\x42\x10\x7c' + _memory_bytes() + b'\x58')
    code += _pointer(b'\x23\0\x29\x03\x08', 3, 24)  # SP+8 -> *_panic
    code += _require(_get(3) + b'\x29\0\0\x42' + _leb(STRING_TYPE) + b'\x51')
    # Only a single unrecovered panic is classified. A chain remains unknown.
    code += _require(_get(3) + b'\x29\0\x10\x50')
    code += _pointer(_get(3) + b'\x29\0\x08', 4, 16)  # arg.data -> boxed string
    code += _get(4) + b'\x29\0\x08\x22\x09\xa7' + _set(2)
    code += _require(_get(9) + b'\x42' + _leb(256) + b'\x58')
    code += _pointer(_get(4) + b'\x29\0\0', 1, 0)
    code += _require(_get(1) + b'\xad' + _get(2) + b'\xad\x7c' + _memory_bytes() + b'\x58')
    for row in rows:
        if (candidate is not None and row['id'] != candidate) or (candidate is None and not row['id'] >> bit & 1):
            continue
        code += _const(0) + _set(5) + _const(1) + _set(6)
        for segment in row['segments']:
            if set(segment) == {'literalHex'}:
                code += _literal(bytes.fromhex(segment['literalHex']))
            elif set(segment) == {'decimal'}:
                fields = segment['decimal']
                if (set(fields) != {'signed', 'maximumDigits'} or type(fields['signed']) is not bool
                        or fields['maximumDigits'] != (20 if fields['signed'] else 19)):
                    raise ValueError('Go-private-panic-decimal-shape')
                code += _decimal(fields['signed'], fields['maximumDigits'])
            else:
                raise ValueError('Go-private-panic-pattern-shape')
        code += _get(6) + _get(5) + _get(2) + b'\x46\x71\x04\x40'
        code += b'\x41\0\x41\0\x6e\x1a\0\x0b'
    return code + b'\0\x0b'  # unknown/no-match always traps; never resumes
