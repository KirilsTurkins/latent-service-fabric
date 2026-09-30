"""Bounded, content-addressed application inputs; cache presence confers no trust."""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import stat
import tarfile
import tempfile
import zipfile

from tools.build_snapshot import canonical, digest, is_reparse

MAX_OBJECT = 64 * 1024 * 1024
MAX_FILES = 8192
MAX_EXPANDED = 256 * 1024 * 1024
SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z", re.I)


class DependencyError(ValueError):
    """A static diagnostic, safe to put in public failed-stage evidence."""


def path_name(value: str) -> str:
    if (not isinstance(value, str) or not 0 < len(value) <= 512 or "\\" in value
            or value.startswith("/") or len(value.split("/")) > 32):
        raise DependencyError("dependency-path-invalid")
    for part in value.split("/"):
        if (not re.fullmatch(r"[A-Za-z0-9_@+.,() -]{1,128}", part) or part in {".", ".."}
                or part.endswith((".", " ")) or DEVICE.fullmatch(part)):
            raise DependencyError("dependency-path-invalid")
    return value


def regular_path(path: Path) -> Path:
    path = path.absolute()
    for parent in (*reversed(path.parents), path):
        if os.path.lexists(parent) and is_reparse(parent):
            raise DependencyError("dependency-link-denied")
    return path


def read_bytes(path: Path, maximum: int = MAX_OBJECT) -> bytes:
    regular_path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise DependencyError("dependency-object-limit")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if (len(data) > maximum or len(data) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise DependencyError("dependency-input-mutated")
    return data


class Store:
    def __init__(self, root: Path):
        self.root = regular_path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, identity: str) -> Path:
        if not isinstance(identity, str) or not SHA.fullmatch(identity):
            raise DependencyError("dependency-digest-invalid")
        return regular_path(self.root / identity[7:9] / identity[9:])

    def put(self, data: bytes) -> dict:
        if len(data) > MAX_OBJECT:
            raise DependencyError("dependency-object-limit")
        identity = digest(data)
        target = self.path(identity)
        target.parent.mkdir(mode=0o700, exist_ok=True)
        # Atomic create, never replace. Concurrent writers can only agree on the
        # exact content addressed bytes. A poisoned existing object fails.
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".capture-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                stream.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
            if self.get(identity, len(data)) != data:
                raise DependencyError("dependency-cache-collision")
        finally:
            temporary.unlink(missing_ok=True)
        return {"digest": identity, "size": len(data)}

    def get(self, digest: str, size: int) -> bytes:
        if type(size) is not int or not 0 <= size <= MAX_OBJECT:
            raise DependencyError("dependency-object-limit")
        try:
            data = read_bytes(self.path(digest))
        except FileNotFoundError:
            raise DependencyError("dependency-artifact-missing-resolve-explicitly") from None
        if len(data) != size or "sha256:" + hashlib.sha256(data).hexdigest() != digest:
            raise DependencyError("dependency-artifact-integrity")
        return data


class Entries:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.spellings: dict[str, str] = {}
        self.directories: set[str] = set()
        self.headers: set[str] = set()
        self.expanded = 0
        self.count = 0

    def add(self, name: str, data: bytes | None):
        name = path_name(name)
        if name in self.headers:
            raise DependencyError("dependency-path-collision")
        self.headers.add(name)
        self.count += 1
        if self.count > MAX_FILES:
            raise DependencyError("dependency-entry-limit")
        for length in range(1, len(name.split("/")) + 1):
            prefix = "/".join(name.split("/")[:length])
            if self.spellings.setdefault(prefix.casefold(), prefix) != prefix:
                raise DependencyError("dependency-path-collision")
            if length < len(name.split("/")):
                if prefix in self.files:
                    raise DependencyError("dependency-path-collision")
                self.directories.add(prefix)
        if name in self.files or data is not None and name in self.directories:
            raise DependencyError("dependency-path-collision")
        if data is None:
            self.directories.add(name)
            return
        self.expanded += len(data)
        if len(data) > MAX_OBJECT or self.expanded > MAX_EXPANDED:
            raise DependencyError("dependency-expanded-byte-limit")
        self.files[name] = data


def directory_files(root: Path) -> dict[str, bytes]:
    root = regular_path(root)
    entries = Entries()
    pending = [root]
    while pending:
        parent = pending.pop()
        for path in sorted(parent.iterdir()):
            regular_path(path)
            name = path.relative_to(root).as_posix()
            if path.is_dir():
                entries.add(name, None)
                pending.append(path)
            else:
                entries.add(name, read_bytes(path))
    return dict(sorted(entries.files.items()))


def archive_files(data: bytes, kind: str) -> dict[str, bytes]:
    if len(data) > MAX_OBJECT:
        raise DependencyError("dependency-object-limit")
    entries = Entries()
    try:
        if kind == "zip":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if len(archive.infolist()) > MAX_FILES:
                    raise DependencyError("dependency-entry-limit")
                seen = set()
                for entry in archive.infolist():
                    # ZipInfo normalizes backslashes on Windows. Inspect the
                    # original central-directory spelling before normalization.
                    name = entry.orig_filename.rstrip("/") if entry.is_dir() else entry.orig_filename
                    if name.casefold() in seen:
                        raise DependencyError("dependency-path-collision")
                    seen.add(name.casefold())
                    mode = entry.external_attr >> 16
                    if (entry.flag_bits & 1 or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
                            or entry.file_size > MAX_OBJECT):
                        raise DependencyError("dependency-archive-entry-denied")
                    if entry.is_dir():
                        if entry.file_size:
                            raise DependencyError("dependency-archive-entry-denied")
                        entries.add(name, None)
                    else:
                        # Check the declared total before decompression; read a
                        # bounded stream rather than ZipFile.read/extractall.
                        if entries.expanded + entry.file_size > MAX_EXPANDED:
                            raise DependencyError("dependency-expanded-byte-limit")
                        with archive.open(entry) as stream:
                            payload = stream.read(entry.file_size + 1)
                        if len(payload) != entry.file_size:
                            raise DependencyError("dependency-archive-length")
                        entries.add(name, payload)
        elif kind == "tar":
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
                for entry in archive:
                    if not (entry.isdir() or entry.isreg()) or entry.size > MAX_OBJECT:
                        raise DependencyError("dependency-archive-entry-denied")
                    if entry.isdir():
                        if entry.size:
                            raise DependencyError("dependency-archive-entry-denied")
                        entries.add(entry.name.rstrip("/"), None)
                    else:
                        if entries.expanded + entry.size > MAX_EXPANDED:
                            raise DependencyError("dependency-expanded-byte-limit")
                        stream = archive.extractfile(entry)
                        if stream is None:
                            raise DependencyError("dependency-archive-length")
                        with stream:
                            payload = stream.read(entry.size + 1)
                        if len(payload) != entry.size:
                            raise DependencyError("dependency-archive-length")
                        entries.add(entry.name, payload)
        else:
            raise DependencyError("dependency-archive-format")
    except (zipfile.BadZipFile, tarfile.TarError, RuntimeError, EOFError, OSError):
        raise DependencyError("dependency-archive-invalid") from None
    return dict(sorted(entries.files.items()))


def captured_files(files: dict[str, bytes], store: Store) -> list[dict]:
    return [{"path": name, **store.put(data)} for name, data in sorted(files.items())]


def materialize(files: list[dict], destination: Path, store: Store):
    regular_path(destination)
    entries = Entries()
    for row in files:
        if set(row) != {"path", "digest", "size"}:
            raise DependencyError("dependency-file-inventory-invalid")
        entries.add(row["path"], store.get(row["digest"], row["size"]))
    for name, data in entries.files.items():
        path = regular_path(destination / name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(data)


def tree_identity(files: list[dict]) -> str:
    return digest(canonical(files))
