"""Verify each retained file before allowing a reference to participate in replay."""

from __future__ import annotations

from .common import (
    BINARY_BYTES, DOCUMENT_BYTES, MAX_ARTIFACTS, TOTAL_BYTES, fields,
    read_json, require, uint, verify_artifact,
)


class Artifacts:
    def __init__(self, root, rows, executable_paths):
        require(isinstance(rows, list) and 1 <= len(rows) <= MAX_ARTIFACTS,
                "invalid-artifact-manifest-size")
        self.root = root
        self.rows = {}
        self.paths = {}
        folded = set()
        total = 0
        for row in rows:
            fields(row, "path sha256 bytes")
            name = row["path"]
            require(isinstance(name, str) and name.casefold() not in folded,
                    "duplicate-artifact")
            folded.add(name.casefold())
            maximum = BINARY_BYTES if name in executable_paths else DOCUMENT_BYTES
            total += uint(row["bytes"])
            require(total <= TOTAL_BYTES, "artifact-total-byte-bound")
            path = verify_artifact(root, row, maximum)
            self.rows[name] = row
            self.paths[name] = path

    def path(self, value):
        fields(value, "path sha256 bytes")
        require(self.rows.get(value["path"]) == value, "unbound-artifact-reference")
        return self.paths[value["path"]]

    def json(self, value, maximum=DOCUMENT_BYTES):
        return read_json(self.path(value), maximum)
