"""A bounded regular-file-only USTAR reader, not tarfile.extractall."""

from __future__ import annotations

import gzip
import hashlib
import os
from pathlib import Path
import stat

from .common import require
from . import files
from .verify import relative


def octal(field: bytes) -> int:
    value = field.rstrip(b"\0 ").lstrip(b" ")
    require(value and all(byte in b"01234567" for byte in value), "archive-invalid-octal")
    return int(value, 8)


def extract(descriptor: int, destination: Path, inventory: list[dict]) -> None:
    expected = {entry["path"]: entry for entry in inventory}
    require(len(expected) == len(inventory), "archive-duplicate-inventory")
    directories = {"/".join(name.split("/")[:depth]) for name in expected
                   for depth in range(1, len(name.split("/")))}
    identity = (os.geteuid(), os.getegid())
    for name in sorted(directories, key=lambda item: (item.count("/"), item)):
        files.mkdir(destination / name, 0o755, identity, owners={0, identity[0]})
    os.lseek(descriptor, 0, os.SEEK_SET)
    with os.fdopen(os.dup(descriptor), "rb") as raw, gzip.GzipFile(fileobj=raw, mode="rb") as stream:
        seen = set()
        while True:
            header = stream.read(512)
            require(len(header) == 512, "archive-truncated-header")
            if header == bytes(512):
                require(stream.read(512) == bytes(512), "archive-missing-end-marker")
                tail = stream.read(10241)
                require(len(tail) <= 10240 and not any(tail), "archive-trailing-data")
                break
            require(len(seen) < len(expected), "archive-entry-limit")
            require(header[257:265] == b"ustar\x0000" and header[156:157] in (b"0", b"\0")
                    and not any(header[157:257]), "archive-unsupported-entry-type")
            require(octal(header[148:156]) == sum(header[:148]) + 256 + sum(header[156:]),
                    "archive-header-checksum")
            try:
                name = header[:100].split(b"\0", 1)[0].decode("ascii")
                prefix = header[345:500].split(b"\0", 1)[0].decode("ascii")
            except UnicodeDecodeError:
                name, prefix = "", ""
            name = relative(prefix + "/" + name if prefix else name)
            require(name in expected and name not in seen, "archive-unexpected-or-duplicate-file")
            entry = expected[name]
            require(octal(header[100:108]) == entry["mode"] and octal(header[124:136]) == entry["size"]
                    and octal(header[108:116]) == 0 and octal(header[116:124]) == 0,
                    "archive-file-metadata-mismatch")
            target = destination / name
            digest = hashlib.sha256()
            with files.directory(target.parent, {0, identity[0]}) as parent:
                output = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=parent)
                with os.fdopen(output, "wb") as sink:
                    remaining = entry["size"]
                    while remaining:
                        block = stream.read(min(65536, remaining))
                        require(block, "archive-truncated-file")
                        sink.write(block)
                        digest.update(block)
                        remaining -= len(block)
                    require(digest.hexdigest() == entry["sha256"], "archive-file-digest-mismatch")
                    sink.flush()
                    os.fchmod(sink.fileno(), entry["mode"])
                    os.fsync(sink.fileno())
                os.fsync(parent)
            padding = (-entry["size"]) % 512
            require(stream.read(padding) == bytes(padding), "archive-nonzero-padding")
            seen.add(name)
        require(seen == set(expected), "archive-missing-file")


def check_tree(root: Path, inventory: list[dict], *, allow_missing: bool = False) -> None:
    expected = {entry["path"]: entry for entry in inventory}
    expected_directories = {"/".join(name.split("/")[:depth]) for name in expected
                            for depth in range(1, len(name.split("/")))}
    observed = set()
    directory_count = 0
    for directory, directories, names in os.walk(root, followlinks=False):
        directory_count += len(directories)
        require(directory_count <= 4096, "installed-directory-limit")
        require(len(observed) + len(names) <= 4096, "installed-inventory-limit")
        for name in directories:
            child = Path(directory) / name
            require(child.relative_to(root).as_posix() in expected_directories, "untracked-installation-directory")
            with files.directory(child, {0, os.geteuid()}):
                pass
        for name in names:
            path = Path(directory) / name
            relative_name = path.relative_to(root).as_posix()
            require(relative_name in expected, "untracked-installation-file")
            entry = expected[relative_name]
            with files.regular(path, owners={0, os.geteuid()}) as descriptor:
                metadata = os.fstat(descriptor)
                digest, size = files.digest_fd(descriptor)
                require(size == entry["size"] and digest == entry["sha256"]
                        and stat.S_IMODE(metadata.st_mode) == entry["mode"], "installed-file-changed")
            observed.add(relative_name)
    require(allow_missing or observed == set(expected), "installed-file-missing")
