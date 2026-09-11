"""Finite evidence files and fixed-size input warming."""
from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path
import shutil
import time

from .model import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES
from tools.artifact_identity_evidence.common import MAX_FOLDED_BYTES, folded_limit, folded_scratch_limit


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


class _FoldedGuard:
    def __init__(self, path, maximum_bytes, deadline, remaining, temporary_bytes=0):
        if deadline is not None and (type(deadline) is not int or deadline < 0):
            raise ValueError("folded-compression-deadline-bound")
        if remaining is not None and (type(remaining) is not int or not 0 <= remaining <= 2 * 1024**3):
            raise ValueError("folded-compression-remaining-bound")
        # helpers imports this module's file primitives; defer this import until use.
        from .helpers import DirectoryLimits, directory_bytes
        self.directory, self.deadline, self.remaining = path.parent, deadline, remaining
        self.directory_bytes = directory_bytes
        self.limits = DirectoryLimits(maximum_file_bytes=max(MAX_FILE_BYTES, maximum_bytes))
        self.minimum_file_sizes = {}
        self.temporary_file = path if temporary_bytes else None

    def check(self, additional=0):
        if self.deadline is not None and time.monotonic_ns() >= self.deadline:
            raise TimeoutError("folded-compression-deadline")
        if self.remaining is not None:
            current = self.directory_bytes(self.directory, self.limits,
                                           minimum_file_sizes=self.minimum_file_sizes,
                                           temporary_file=self.temporary_file)
            if current + additional > self.remaining:
                raise ValueError("folded-compression-total-bound")


class _FoldedOutput:
    def __init__(self, raw, guard, path):
        self.raw, self.guard, self.path, self.written = raw, guard, path, 0
        self.error, self.aborted = None, False
        self.guard.minimum_file_sizes[path] = 0

    def abort(self):
        self.aborted = True

    def check(self):
        if self.error is not None:
            raise self.error

    def write(self, data):
        if not self.aborted:
            try:
                if self.written + len(data) > MAX_FILE_BYTES:
                    raise ValueError("folded-compressed-file-bound")
                self.guard.check(len(data))
                written = self.raw.write(data)
                if type(written) is not int or not 0 <= written <= len(data):
                    raise OSError("folded-compression-short-write")
                self.written += written
                self.guard.minimum_file_sizes[self.path] = self.written
                if written != len(data):
                    raise OSError("folded-compression-short-write")
                self.guard.check()
            except BaseException as error:
                self.error, self.aborted = error, True
        # Gzip must drain its bounded internal buffer even after an output error.
        # The caller checks the latched error after every operation; cleanup writes
        # are discarded and cannot replace the original exception or grow the file.
        return len(data)

    def flush(self):
        if not self.aborted:
            try:
                self.guard.check()
                self.raw.flush()
                self.guard.check()
            except BaseException as error:
                self.error, self.aborted = error, True

    def tell(self):
        return self.written


def compress_folded(path: Path, output: Path, *, maximum_bytes: int = MAX_FOLDED_BYTES,
                    deadline: int | None = None, remaining: int | None = None,
                    temporary_folded_bytes: int = 0) -> dict:
    """Retain every stack/weight; optional profile guards include gzip coexistence."""
    maximum_bytes = folded_limit(maximum_bytes)
    temporary_folded_bytes = folded_scratch_limit(maximum_bytes, temporary_folded_bytes)
    if temporary_folded_bytes and (type(remaining) is not int or not 0 <= remaining <= MAX_TOTAL_BYTES):
        raise ValueError("folded-scratch-retained-budget-bound")
    guard = _FoldedGuard(path, maximum_bytes, deadline, remaining, temporary_folded_bytes)
    guard.check()
    original = fingerprint(path, maximum_bytes)
    guard.check()
    destination = path.with_suffix(path.suffix + ".gz")
    # Track accepted bytes as well as directory sizes: Windows may report stale
    # entry sizes even for this unbuffered, still-open destination.
    with path.open("rb") as source, destination.open("xb", buffering=0) as raw:
        sink, compressed = _FoldedOutput(raw, guard, destination), None
        try:
            compressed = gzip.GzipFile(fileobj=sink, mode="wb", filename="", mtime=0)
            sink.check()
            consumed = 0
            while True:
                guard.check()
                chunk = source.read(65536)
                guard.check()
                if not chunk:
                    break
                consumed += len(chunk)
                if consumed > maximum_bytes:
                    raise ValueError("folded-expanded-byte-bound")
                compressed.write(chunk)
                sink.check()
                guard.check()
            compressed.close()
            sink.check()
        except BaseException:
            sink.abort()
            if compressed is not None:
                compressed.close()
            raise
    guard.check()
    digest, size = hashlib.sha256(), 0
    with gzip.open(destination, "rb") as restored:
        while True:
            guard.check()
            chunk = restored.read(65536)
            guard.check()
            if not chunk:
                break
            size += len(chunk)
            if size > maximum_bytes:
                raise ValueError("folded-expanded-byte-bound")
            digest.update(chunk)
    if ("sha256:" + digest.hexdigest(), size) != original:
        raise ValueError("folded-compression-mismatch")
    guard.check()
    result = reference(destination, output)
    guard.check()
    # Retain the original and any partial gzip on every earlier failure.
    path.unlink()
    return result


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


def total_limit(maximum_total_bytes: int) -> int:
    """Closed storage budgets: historical 1 GiB or explicit codec-only 2 GiB."""
    if type(maximum_total_bytes) is not int or maximum_total_bytes not in (1024**3, 2 * 1024**3):
        raise ValueError("unsupported-artifact-total-byte-bound")
    return maximum_total_bytes


def inventory(root: Path, output: Path, *, maximum_total_bytes: int = MAX_TOTAL_BYTES) -> dict:
    maximum_total_bytes = total_limit(maximum_total_bytes)
    result, total = {}, 0
    for path in files(root):
        item = reference(path, output)
        total += int(item["bytes"])
        if total > maximum_total_bytes:
            raise ValueError("artifact-total-bound")
        result[path.relative_to(root).as_posix()] = item
    return result


def total_bytes(root: Path, *, maximum_total_bytes: int = MAX_TOTAL_BYTES) -> int:
    """Enforce storage limits without repeatedly hashing previous run evidence."""
    maximum_total_bytes = total_limit(maximum_total_bytes)
    total = 0
    for path in files(root):
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > maximum_total_bytes:
            raise ValueError("artifact-storage-bound")
    return total


def warm(root: Path, expected: dict, output: Path, *, maximum_total_bytes: int = MAX_TOTAL_BYTES) -> dict:
    # Hash while performing the declared sequential read; never evict OS caches.
    observed = inventory(root, output, maximum_total_bytes=maximum_total_bytes)
    if observed != expected:
        raise ValueError("fixture-mutated")
    return {"policy": "best-effort-sequential-64k-read-before-every-child",
            "files": len(observed), "bytes": str(sum(int(item["bytes"]) for item in observed.values()))}
