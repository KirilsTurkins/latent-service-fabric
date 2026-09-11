"""Bounded manifests shared by the two cache packages."""
from pathlib import Path
from tools.optimization_evidence.artifacts import Artifacts as BaseArtifacts
from tools.optimization_evidence.common import fields, require, uint, verify_artifact
from tools.artifact_identity_runner.files import reference, total_limit

MAX_TOTAL = 1024**3


def inventory(root, *, maximum_total_bytes=MAX_TOTAL):
    maximum_total_bytes = total_limit(maximum_total_bytes)
    root = Path(root)
    rows, total = [], 0
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "cache-evidence-symlink")
        if path.is_dir():
            continue
        require(path.is_file(), "cache-evidence-special-file")
        if path.parent == root and path.name in ("suite.json", "aggregate.json"):
            continue
        rows.append(reference(path, root))
        total += uint(rows[-1]["bytes"])
        require(total <= maximum_total_bytes, "cache-artifact-total-bound")
        require(len(rows) <= 4096, "cache-artifact-count-bound")
    return rows


class Artifacts(BaseArtifacts):
    def __init__(self, root, rows, binaries=(), *, maximum_total_bytes=MAX_TOTAL):
        maximum_total_bytes = total_limit(maximum_total_bytes)
        require(isinstance(rows, list) and 1 <= len(rows) <= 4096, "cache-artifact-count-bound")
        total = 0
        for row in rows:
            fields(row, "path sha256 bytes")
            maximum = 1024**3 if row["path"] in binaries else 256 * 1024**2
            total += uint(row["bytes"])
            require(uint(row["bytes"]) <= maximum and total <= maximum_total_bytes, "cache-artifact-byte-bound")
        super().__init__(Path(root), rows, {row["path"] for row in rows})

    def nested(self, parent, row):
        path = verify_artifact(parent, row, 16 * 1024**2)
        name = path.relative_to(self.root.resolve()).as_posix()
        require(self.rows.get(name) == dict(row, path=name), "cache-unregistered-nested-artifact")
        return path
