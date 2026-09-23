"""Closed documents, static diagnostics and finite controller budgets."""
from __future__ import annotations

import hashlib
import json
import re

MAX_DOCUMENT = 262144
MAX_FILES = 2048
MAX_FILE = 16 * 1024 * 1024
MAX_SNAPSHOT = 64 * 1024 * 1024
MAX_LOG = 256 * 1024
MAX_WORKSPACES = 8
MAX_REVISIONS = 4
PROTOCOL = "latent.dev.protocol.v1"
HOST_ABI = "lsf-host-abi-phase3-v4"


class DevError(ValueError):
    def __init__(self, code: str, *, uncertain: bool = False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


def require(condition: object, code: str) -> None:
    if not condition:
        raise DevError(code)


def members(value: object, required: set[str], optional: set[str] | None = None) -> dict:
    require(isinstance(value, dict), "document-object-required")
    require(required <= value.keys() <= required | (optional or set()), "unknown-or-missing-field")
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate-field")
        result[key] = value
    return result


def decode(raw: bytes, maximum: int = MAX_DOCUMENT):
    require(0 < len(raw) <= maximum, "document-byte-limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(DevError("nonfinite-number")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise DevError("invalid-json") from error
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        require(depth <= 24 and count <= 32768, "document-complexity-limit")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def sha(value: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value), "invalid-sha256")
    return value


def identifier(value: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,47}", value), "invalid-identifier")
    return value


def integer(value: int, minimum: int, maximum: int) -> int:
    require(type(value) is int and minimum <= value <= maximum, "integer-out-of-range")
    return value
