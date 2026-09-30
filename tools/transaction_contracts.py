"""Canonical Phase 4 contract framing and bounded transport validation.

This is a shared vector/HTTP decoder owner, not a state engine. SHA-256 inputs
match latent_core::transaction_contract; neither function grants authority.
"""
from __future__ import annotations

import base64
import hashlib
import re
import struct

IDENTITY_BYTES = 256
KEY_BYTES = 1024
VALUE_BYTES = 1024 * 1024
VERSION_BYTES = 256
METADATA_PAIRS = 32
METADATA_BYTES = 8192
PAGE_ENTRIES = 128
PAGE_BYTES = 1024 * 1024
STAGED_BYTES = 8 * 1024 * 1024
MAX_U64 = (1 << 64) - 1


def identity(value):
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("invalid-present-identity")
    raw = value.encode("utf-8", errors="strict")
    if len(raw) > IDENTITY_BYTES:
        raise ValueError("identity-byte-limit")
    return raw


def frame(value):
    return struct.pack("<Q", len(value)) + value


def unsigned64(value):
    # JSON number parsing loses u64 precision in several maintained clients.
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,19}", value):
        raise ValueError("invalid-u64-spelling")
    result = int(value)
    if result > MAX_U64:
        raise ValueError("u64-overflow")
    return result


def bytes_value(value, maximum, *, nonempty=False):
    if not isinstance(value, str) or len(value) > 4 * ((maximum + 2) // 3):
        raise ValueError("byte-limit")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError("invalid-base64") from error
    if base64.b64encode(result).decode() != value or len(result) > maximum:
        raise ValueError("noncanonical-or-oversized-bytes")
    if nonempty and not result:
        raise ValueError("invalid-present-bytes")
    return result


def metadata(value):
    if not isinstance(value, list) or len(value) > METADATA_PAIRS:
        raise ValueError("metadata-count")
    seen, result, total = set(), [], 0
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("metadata-pair")
        key = identity(pair[0])
        if key in seen or not isinstance(pair[1], str):
            raise ValueError("metadata-duplicate-or-invalid")
        raw = pair[1].encode("utf-8", errors="strict")
        if len(raw) > 1024:
            raise ValueError("metadata-value-limit")
        seen.add(key)
        total += len(key) + len(raw)
        if total > METADATA_BYTES:
            raise ValueError("metadata-byte-limit")
        result.append((key, raw))
    return sorted(result)


def content(value):
    if not isinstance(value, dict) or set(value) != {"bytes", "mediaType", "metadata"}:
        raise ValueError("invalid-value-envelope")
    media = value["mediaType"]
    if not isinstance(media, str) or not media or not media.isascii() or "\0" in media or len(media) > 128:
        raise ValueError("invalid-media-type")
    return bytes_value(value["bytes"], VALUE_BYTES), media.encode(), metadata(value["metadata"])


def command_identity(value):
    required = {"tenant", "namespace", "incarnation", "recoveryScope", "operation", "clientKey"}
    if not isinstance(value, dict) or set(value) - required - {"entity"} or required - set(value):
        raise ValueError("invalid-command-key")
    fields = [identity(value[name]) for name in ("tenant", "namespace", "incarnation", "recoveryScope", "operation")]
    entity = identity(value["entity"]) if "entity" in value else None
    return (b"lsf-command-key-v1\0" + b"".join(frame(item) for item in fields)
            + bytes([entity is not None]) + (frame(entity) if entity is not None else b"")
            + frame(identity(value["clientKey"])))


def fingerprint(value):
    if not isinstance(value, dict) or set(value) != {"inputFormat", "input", "expectedVersions"}:
        raise ValueError("invalid-fingerprint-envelope")
    input_format = identity(value["inputFormat"])
    data, media, pairs = content(value["input"])
    conditions = value["expectedVersions"]
    if not isinstance(conditions, list) or len(conditions) > 128:
        raise ValueError("precondition-count")
    entries, seen = [], set()
    for condition in conditions:
        if not isinstance(condition, dict) or set(condition) not in ({"key", "absent"}, {"key", "version"}):
            raise ValueError("invalid-precondition")
        key = bytes_value(condition["key"], KEY_BYTES, nonempty=True)
        if key in seen:
            raise ValueError("duplicate-precondition")
        seen.add(key)
        if "absent" in condition:
            if condition["absent"] is not True:
                raise ValueError("invalid-absence")
            expected = b"\0"
        else:
            expected = b"\1" + frame(bytes_value(condition["version"], VERSION_BYTES, nonempty=True))
        entries.append((key, expected))
    return (b"lsf-command-fingerprint-v1\0" + frame(input_format) + frame(media) + frame(data)
            + struct.pack("<Q", len(pairs)) + b"".join(frame(k) + frame(v) for k, v in pairs)
            + struct.pack("<Q", len(entries)) + b"".join(frame(k) + v for k, v in sorted(entries)))


def digest(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()
