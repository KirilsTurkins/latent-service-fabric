"""Finite evidence inputs and exact integer allocation profiles."""
from __future__ import annotations

from decimal import Decimal

from tools.optimization_evidence.artifacts import Artifacts as BaseArtifacts
from tools.optimization_evidence.common import (
    GIT_HASH, canonical, digest, distribution, fields, integer, read_json,
    require, sha256, text, uint,
)

MAX_FILE = 256 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_FILES = 4096
ARMS = ("control", "candidate")
OPERATIONS = ("hash", "artifact-open", "catalog-open")
MODES = ("normal", "allocation")


class Artifacts(BaseArtifacts):
    def __init__(self, root, rows):
        require(isinstance(rows, list) and 1 <= len(rows) <= MAX_FILES, "artifact-count-bound")
        total, large = 0, set()
        for row in rows:
            fields(row, "path sha256 bytes")
            size = uint(row["bytes"])
            require(size <= MAX_FILE, "artifact-byte-bound")
            total += size
            require(total <= MAX_TOTAL, "artifact-total-bound")
            large.add(row["path"])
        # The superclass enforces safe paths, exact hashes, case uniqueness and
        # bound references. This protocol separately caps every file and total.
        super().__init__(root, rows, large)


def folded(path):
    """Sum exact whole-process allocation/peak weights, never rounded SI text."""
    result, total, bytes_read = [], 0, 0
    with path.open("rb") as stream:
        while encoded := stream.readline(64 * 1024 + 1):
            bytes_read += len(encoded)
            require(bytes_read <= 16 * 1024 * 1024 and len(encoded) <= 64 * 1024,
                    "profile-text-bound")
            require(encoded.endswith(b"\n") and len(result) < 100_000, "profile-row-bound")
            try:
                stack, weight = encoded[:-1].decode("utf-8").rsplit(" ", 1)
            except (ValueError, UnicodeError) as error:
                raise ValueError("invalid-folded-profile") from error
            require(stack and "\0" not in stack and len(stack.split(";")) <= 512,
                    "profile-stack-bound")
            amount = uint(weight)
            total += amount
            require(total <= 2**64 - 1, "profile-total-overflow")
            result.append((stack, amount))
    require(bool(result), "empty-allocation-profile")
    return {"rows": str(len(result)), "total": str(total)}


def decimal_distribution(values):
    return distribution([Decimal(str(value)) for value in values]) if values else None
