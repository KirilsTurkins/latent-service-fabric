"""Shared bounds and deterministic JSON/statistics; no inferred measurements."""

from __future__ import annotations

from decimal import Decimal, localcontext
import json
import math
import os
from pathlib import Path
import stat

from tools.phase1_evidence.common import (
    EvidenceError, GIT_HASH, canonical, digest, fields, hash_file,
    integer, require, sha256, text, uint, unique_object, verify_artifact,
)
from tools.phase1_evidence.statistics import decimal_string, distribution

PREFIX = "latent.optimization."
DOCUMENT_BYTES = 16 * 1024 * 1024
ROW_BYTES = 16 * 1024
MAX_ATTEMPTS = 100_000
MAX_ARTIFACTS = 4096
BINARY_BYTES = 1024**3
TOTAL_BYTES = 4 * 1024**3
ARMS = ("native", "lsf")
OUTCOMES = (
    "success", "declared-error", "platform-failure", "transport-failure",
    "client-timeout", "client-overload", "client-deadline-before-dispatch",
    "invalid-response",
)


def decode(data: bytes, maximum: int = DOCUMENT_BYTES):
    require(len(data) <= maximum, "json-byte-bound")
    try:
        value = json.loads(data, object_pairs_hook=unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(EvidenceError("invalid-number")))
        pending, nodes = [(value, 0)], 0
        while pending:
            item, depth = pending.pop()
            nodes += 1
            require(nodes <= 1_000_000 and depth <= 48, "json-structure-bound")
            if isinstance(item, dict):
                require(len(item) <= 4096, "json-object-bound")
                for key, child in item.items():
                    text(key, 4096)
                    pending.append((child, depth + 1))
            elif isinstance(item, list):
                require(len(item) <= MAX_ATTEMPTS, "json-array-bound")
                pending.extend((child, depth + 1) for child in item)
            elif isinstance(item, str):
                text(item, 1024 * 1024, empty=True)
            elif isinstance(item, float):
                require(math.isfinite(item), "invalid-number")
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError) as error:
        raise EvidenceError("invalid-json") from error


def read_json(path: Path, maximum: int = DOCUMENT_BYTES):
    try:
        require(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), "not-regular-file")
        with path.open("rb") as source:
            require(stat.S_ISREG(os.fstat(source.fileno()).st_mode), "not-regular-file")
            return decode(source.read(maximum + 1), maximum)
    except OSError as error:
        raise EvidenceError("unreadable-evidence") from error


def ratio(numerator: int, denominator: int) -> str | None:
    """Keep a zero-duration observation explicit instead of claiming infinity."""
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 40
        return decimal_string((Decimal(numerator) / denominator).quantize(Decimal("0.000001")))


def counters(rows: list[dict]) -> dict[str, str]:
    return {name: str(sum(row["outcome"] == name for row in rows)) for name in OUTCOMES}


def load_rows(path: Path) -> list[dict]:
    """Bound bytes before decoding each JSONL row, preserving every attempt."""
    require(not path.is_symlink() and path.is_file(), "invalid-attempt-file")
    result = []
    total = 0
    with path.open("rb") as source:
        while data := source.readline(ROW_BYTES + 1):
            total += len(data)
            require(total <= DOCUMENT_BYTES and len(data) <= ROW_BYTES
                    and data.endswith(b"\n"), "attempt-byte-bound")
            require(len(result) < MAX_ATTEMPTS, "attempt-count-bound")
            value = decode(data, ROW_BYTES)
            require(isinstance(value, dict), "invalid-attempt-row")
            result.append(value)
    return result
