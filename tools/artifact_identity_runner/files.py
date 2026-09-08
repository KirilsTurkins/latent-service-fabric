"""Finite evidence files and fixed-size input warming."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from .model import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES


def fingerprint(path: Path, maximum: int = MAX_FILE_BYTES) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("artifact-file-bound")
    result, length = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            length += len(chunk)
            if length > maximum:
                raise ValueError("artifact-file-bound")
            result.update(chunk)
    return "sha256:" + result.hexdigest(), length


def reference(path: Path, output: Path) -> dict:
    checksum, length = fingerprint(path)
    return {"path": path.relative_to(output).as_posix(), "sha256": checksum, "bytes": str(length)}


def retain(source: Path, destination: Path, output: Path) -> dict:
    fingerprint(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst, 65536)
    if fingerprint(source) != fingerprint(destination):
        raise ValueError("retained-copy-mismatch")
    return reference(destination, output)


def write_json(path: Path, value: object) -> None:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("json-document-bound")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
    temporary.replace(path)


def files(root: Path) -> list[Path]:
    result, pending = [], [root]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            if path.is_symlink():
                raise ValueError("artifact-symlink")
            if path.is_dir():
                pending.append(path)
            elif path.is_file():
                result.append(path)
            else:
                raise ValueError("artifact-nonregular")
            if len(result) + len(pending) > MAX_FILES:
                raise ValueError("artifact-count-bound")
    return sorted(result)


def inventory(root: Path, output: Path) -> dict:
    result, total = {}, 0
    for path in files(root):
        item = reference(path, output)
        total += int(item["bytes"])
        if total > MAX_TOTAL_BYTES:
            raise ValueError("artifact-total-bound")
        result[path.relative_to(root).as_posix()] = item
    return result


def total_bytes(root: Path) -> int:
    """Enforce storage limits without repeatedly hashing previous run evidence."""
    total = 0
    for path in files(root):
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("artifact-storage-bound")
    return total


def warm(root: Path, expected: dict, output: Path) -> dict:
    # Hash while performing the declared sequential read; never evict OS caches.
    observed = inventory(root, output)
    if observed != expected:
        raise ValueError("fixture-mutated")
    return {"policy": "best-effort-sequential-64k-read-before-every-child",
            "files": len(observed), "bytes": str(sum(int(item["bytes"]) for item in observed.values()))}
