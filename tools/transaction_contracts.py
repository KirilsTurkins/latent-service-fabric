"""Canonical Phase 4 contract framing and bounded transport validation.

This is a shared vector/HTTP decoder owner, not a state engine. SHA-256 inputs
match latent_core::transaction_contract; neither function grants authority.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import struct

from jsonschema import Draft202012Validator

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
ENVELOPE_BYTES = 2 * 1024 * 1024
ENVELOPE_NODES = 32768
ENVELOPE_DEPTH = 32

_HTTP_SCHEMA = json.loads((Path(__file__).resolve().parents[1]
                          / "schemas/transaction-api.schema.json").read_text(encoding="utf-8"))
_HTTP_VALIDATOR = Draft202012Validator(_HTTP_SCHEMA)


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
    if not isinstance(media, str) or not media or not all(32 <= ord(char) <= 126 for char in media) or len(media) > 128:
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


def _bounded_json(value):
    # Check the traversal budget before recursive schema validation/serialization.
    pending, count, string_bytes = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > ENVELOPE_NODES or depth > ENVELOPE_DEPTH:
            raise ValueError("envelope-traversal-limit")
        if isinstance(item, str):
            string_bytes += len(item.encode("utf-8", errors="strict"))
            if string_bytes > ENVELOPE_BYTES:
                raise ValueError("envelope-byte-limit")
        elif isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ValueError("invalid-json-key")
            if count + len(pending) + 2 * len(item) > ENVELOPE_NODES:
                raise ValueError("envelope-traversal-limit")
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if count + len(pending) + len(item) > ENVELOPE_NODES:
                raise ValueError("envelope-traversal-limit")
            pending.extend((child, depth + 1) for child in item)
        elif item is not None and not isinstance(item, (bool, int)):
            raise ValueError("invalid-json-scalar")
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > ENVELOPE_BYTES:
        raise ValueError("envelope-byte-limit")


def _source(value):
    for name in ("publicationId", "revisionId", "inputFormat", "resultFormat"):
        identity(value[name])
    unsigned64(value["routeGeneration"])


def _retention(value, record_format):
    if value["recordFormat"] != record_format or type(value["recordVersion"]) is not int:
        raise ValueError("wrong-retention-format")
    for name in ("payloadExpiresAtUnixMillis", "identityExpiresAtUnixMillis", "remainingRecoveryMillis"):
        if name in value:
            unsigned64(value[name])
    for record_id in value["requiredRecordIds"]:
        identity(record_id)
    if ("payloadExpiresAtUnixMillis" in value and "identityExpiresAtUnixMillis" in value
            and unsigned64(value["payloadExpiresAtUnixMillis"]) > unsigned64(value["identityExpiresAtUnixMillis"])):
        raise ValueError("payload-outlives-recovery-identity")


def _abort(value):
    for name in ("commandId", "attemptId", "transactionId"):
        identity(value[name])
    bytes_value(value["ownerFence"], VERSION_BYTES, nonempty=True)


def _response(value):
    for name in ("commandId", "attemptId", "receiptId", "resultFormat", "cleanupFailure"):
        if name in value:
            identity(value[name])
    for name in ("remainingRecoveryMillis",):
        if name in value:
            unsigned64(value[name])
    if "viewVersion" in value:
        bytes_value(value["viewVersion"], VERSION_BYTES, nonempty=True)
    if "sourceIdentity" in value:
        _source(value["sourceIdentity"])
        if "resultFormat" in value and value["resultFormat"] != value["sourceIdentity"]["resultFormat"]:
            raise ValueError("result-format-source-mismatch")
    if "result" in value:
        content(value["result"])
        if "resultFormat" not in value:
            raise ValueError("result-format-required")
    if "retention" in value:
        _retention(value["retention"], "lsf-command-result-v1")
        if not value["retention"]["payloadAvailable"] and "result" in value:
            raise ValueError("expired-payload-present")
        if (value["outcome"] in {"committed", "rejected"} and value["retention"]["payloadAvailable"]
                and "result" not in value):
            raise ValueError("retained-terminal-result-required")
        if ("remainingRecoveryMillis" in value and "remainingRecoveryMillis" in value["retention"]
                and value["remainingRecoveryMillis"] != value["retention"]["remainingRecoveryMillis"]):
            raise ValueError("recovery-window-mismatch")
    if "viewIdentity" in value:
        view = value["viewIdentity"]
        identity(view["namespace"])
        identity(view["incarnation"])
        bytes_value(view["version"], VERSION_BYTES, nonempty=True)
        if "viewVersion" in value and value["viewVersion"] != view["version"]:
            raise ValueError("view-version-mismatch")
        if "sourceIdentity" in value and view["stateSchema"] != value["sourceIdentity"]["stateSchema"]:
            raise ValueError("view-schema-source-mismatch")
    if "provenAbort" in value:
        fence = value["provenAbort"]
        _abort(fence)
        if value["commandId"] != fence["commandId"] or value["attemptId"] != fence["attemptId"]:
            raise ValueError("abort-attempt-mismatch")
    commit = value.get("commitReceipt")
    if commit is not None:
        for name in ("commandId", "attemptId", "transactionId", "receiptId"):
            identity(commit[name])
        for name in ("commandId", "attemptId", "receiptId"):
            if value[name] != commit[name]:
                raise ValueError("commit-attempt-mismatch")
        bytes_value(commit["committedVersion"], VERSION_BYTES, nonempty=True)
        if "viewVersion" in value and value["viewVersion"] != commit["committedVersion"]:
            raise ValueError("commit-view-mismatch")
        unsigned64(commit["committedAtUnixMillis"])
        _source(commit["sourceIdentity"])
        if commit["sourceIdentity"] != value["sourceIdentity"]:
            raise ValueError("commit-source-mismatch")
        for effect_id in commit["effectIds"]:
            identity(effect_id)
    seen = set()
    for effect in value.get("effects", []):
        for name in ("effectId", "commandId", "commandAttemptId", "providerProfile", "providerReceipt", "failureCode", "managementOperationReceiptId"):
            if name in effect:
                identity(effect[name])
        if type(effect["dispatchAttempt"]) is not int:
            raise ValueError("invalid-dispatch-attempt")
        if (commit is None or effect["effectId"] not in commit["effectIds"]
                or effect["commandId"] != value["commandId"] or effect["commandAttemptId"] != value["attemptId"]):
            raise ValueError("effect-command-mismatch")
        if effect["effectId"] in seen:
            raise ValueError("duplicate-effect-receipt")
        seen.add(effect["effectId"])
        unsigned64(effect["occurredAtUnixMillis"])
        _retention(effect["retention"], "lsf-effect-intent-v1")
        if effect["disposition"] == "administratively-terminated" and "managementOperationReceiptId" not in effect:
            raise ValueError("administrative-receipt-required")


def envelope(value):
    """Validate the bounded HTTP definition; this never authorizes or executes it.

    Structural validation, full-width integers, decoded bytes, presence and
    receipt linkage are all mandatory. An abort fence is opaque server data;
    accepting its shape is not proof that its physical owner has retired.
    """
    _bounded_json(value)
    if not _HTTP_VALIDATOR.is_valid(value):
        raise ValueError("invalid-transaction-envelope")
    if value["kind"] == "response":
        _response(value)
        return value
    for name in ("namespace", "incarnation", "operation", "clientKey", "entity", "sharedRecoveryScope", "attemptId", "inputFormat"):
        if name in value:
            identity(value[name])
    if "input" in value:
        content(value["input"])
    if "minimumViewVersion" in value:
        bytes_value(value["minimumViewVersion"], VERSION_BYTES, nonempty=True)
    if value["kind"] == "command":
        fingerprint({name: value[name] for name in ("inputFormat", "input", "expectedVersions")})
        if "retryAttempt" in value:
            identity(value["retryAttempt"]["requestId"])
            _abort(value["retryAttempt"]["expectedAbort"])
    return value


def decode_envelope(raw):
    """Decode bounded strict UTF-8 JSON without duplicate fields or deep lifting."""
    if not isinstance(raw, bytes) or len(raw) > ENVELOPE_BYTES:
        raise ValueError("envelope-byte-limit")
    # Lexical accounting precedes JSON allocation. Punctuation within strings
    # does not count as structure; json.loads still owns all syntax checking.
    quoted, escaped, token, depth, nodes = False, False, False, 0, 0
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
            continue
        if byte == 34:
            quoted, token = True, False
            nodes += 1
        elif byte in (91, 123):
            depth += 1
            nodes += 1
            token = False
        elif byte in (93, 125):
            depth -= 1
            token = False
        elif byte in (9, 10, 13, 32, 44, 58):
            token = False
        elif not token:
            token = True
            nodes += 1
        # JSON's root container has lexical depth one and traversal depth zero.
        if depth > ENVELOPE_DEPTH + 1 or nodes > ENVELOPE_NODES:
            raise ValueError("envelope-traversal-limit")

    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate-json-field")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("invalid-json-scalar")

    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique_fields,
                           parse_constant=invalid_constant)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("invalid-json-envelope") from error
    return envelope(value)
