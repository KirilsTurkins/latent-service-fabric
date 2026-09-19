"""Descriptor-anchored paths; installation never repairs arbitrary trees."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import os
from pathlib import Path
import stat
import time

from .common import InstallError, require

MAX_FILE = 536_870_912


def absolute(path: Path) -> Path:
    require(path.is_absolute() and ".." not in path.parts, "absolute-nontraversing-path-required")
    require(len(str(path).encode()) <= 4096, "path-byte-limit")
    return path


def no_acl(descriptor: int) -> None:
    for name in ("system.posix_acl_access", "system.posix_acl_default"):
        try:
            value = os.getxattr(descriptor, name)
        except OSError as error:
            require(error.errno == errno.ENODATA, "acl-inspection-failed")
        else:
            require(not value, "extended-acl-not-supported")


def directory_policy(descriptor: int, owners: set[int]) -> None:
    metadata = os.fstat(descriptor)
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid in owners, "unsafe-directory-owner")
    sticky_root = metadata.st_uid == 0 and metadata.st_mode & stat.S_ISVTX
    require(not metadata.st_mode & 0o022 or sticky_root, "unsafe-directory-permissions")
    no_acl(descriptor)


@contextmanager
def directory(path: Path, owners: set[int] | None = None):
    absolute(path)
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        if owners is not None:
            directory_policy(descriptor, owners)
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            if owners is not None:
                directory_policy(descriptor, owners)
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def regular(path: Path, maximum: int = MAX_FILE, *, owners: set[int] | None = None,
            private: bool = False, trusted_gid: int | None = None):
    with directory(absolute(path).parent, owners) as parent:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=parent)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "regular-single-link-file-required")
        require(0 <= before.st_size <= maximum, "file-byte-limit")
        if owners is not None:
            require(before.st_uid in owners and not before.st_mode & 0o022, "unsafe-file-owner-or-mode")
            no_acl(descriptor)
        if private:
            require(not before.st_mode & 0o7137, "private-file-required")
            group = os.getegid() if trusted_gid is None else trusted_gid
            require(not before.st_mode & 0o040 or before.st_gid == group, "private-file-group")
        yield descriptor
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size",
                  "st_mtime_ns", "st_ctime_ns")
        require(all(getattr(before, field) == getattr(after, field) for field in fields),
                "file-changed-during-read")
    finally:
        os.close(descriptor)


def read(path: Path, maximum: int = 1_048_576, **options) -> bytes:
    with regular(path, maximum, **options) as descriptor:
        data = bytearray()
        while True:
            block = os.read(descriptor, min(65536, maximum + 1 - len(data)))
            if not block:
                return bytes(data)
            data.extend(block)
            require(len(data) <= maximum, "file-byte-limit")


def digest_fd(descriptor: int, maximum: int = MAX_FILE) -> tuple[str, int]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while block := os.read(descriptor, 65536):
        total += len(block)
        require(total <= maximum, "file-byte-limit")
        digest.update(block)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest(), total


def digest(path: Path, maximum: int = MAX_FILE) -> str:
    with regular(path, maximum) as descriptor:
        return digest_fd(descriptor, maximum)[0]


def mkdir(path: Path, mode: int, identity: tuple[int, int], *, owners: set[int]) -> bool:
    with directory(absolute(path).parent, owners) as parent:
        try:
            os.mkdir(path.name, mode, dir_fd=parent)
        except FileExistsError:
            created = False
        else:
            created = True
        child = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=parent)
        try:
            if created:
                if os.geteuid() == 0:
                    os.fchown(child, *identity)
                os.fchmod(child, mode)
                os.fsync(parent)
            metadata = os.fstat(child)
            require((metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) ==
                    (*identity, mode), "existing-directory-identity-or-mode")
            no_acl(child)
        finally:
            os.close(child)
    return created


def create(path: Path, data: bytes, mode: int = 0o600,
           identity: tuple[int, int] | None = None) -> None:
    owners = {0, os.geteuid(), identity[0]} if identity is not None else {0, os.geteuid()}
    with directory(absolute(path).parent, owners) as parent:
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             mode, dir_fd=parent)
        try:
            if identity is not None and os.geteuid() == 0:
                os.fchown(descriptor, *identity)
            os.fchmod(descriptor, mode)
            with os.fdopen(os.dup(descriptor), "wb") as stream:
                stream.write(data)
                stream.flush()
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(parent)


def replace(path: Path, data: bytes, mode: int = 0o600, identity: tuple[int, int] | None = None) -> None:
    import secrets
    temporary = path.with_name(".replace-" + secrets.token_hex(16))
    create(temporary, data, mode, identity)
    with directory(path.parent, {0, os.geteuid()}) as parent:
        os.replace(temporary.name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)


def identity(path: Path, owners: set[int] | None = None) -> dict:
    with directory(path, owners or {0, os.geteuid()}) as descriptor:
        metadata = os.fstat(descriptor)
    return {"device": metadata.st_dev, "inode": metadata.st_ino, "uid": metadata.st_uid}


@contextmanager
def lock(path: Path, timeout: float = 10):
    import fcntl
    with directory(path.parent, {0, os.geteuid()}) as parent:
        descriptor = os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             0o600, dir_fd=parent)
    try:
        metadata = os.fstat(descriptor)
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
                and metadata.st_uid == os.geteuid() and stat.S_IMODE(metadata.st_mode) == 0o600,
                "unsafe-installation-lock")
        no_acl(descriptor)
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                require(time.monotonic() < deadline, "installation-busy")
                time.sleep(0.05)
        yield descriptor
    finally:
        os.close(descriptor)


def remove_tree(path: Path, *, maximum: int = 100_000) -> None:
    count = 0
    with directory(path.parent, {0, os.geteuid()}) as parent:
        root = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                       dir_fd=parent)
        try:
            device = os.fstat(root).st_dev

            def visit(descriptor: int, depth: int, deleting: bool) -> None:
                nonlocal count
                require(depth <= 64, "purge-depth-limit")
                for name in os.listdir(descriptor):
                    count += 1
                    require(count <= maximum, "purge-entry-limit")
                    metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    require(metadata.st_dev == device, "purge-mount-boundary")
                    if stat.S_ISDIR(metadata.st_mode):
                        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=descriptor)
                        try:
                            opened = os.fstat(child)
                            require((opened.st_dev, opened.st_ino) == (metadata.st_dev, metadata.st_ino),
                                    "purge-directory-changed")
                            visit(child, depth + 1, deleting)
                        finally:
                            os.close(child)
                        if deleting:
                            os.rmdir(name, dir_fd=descriptor)
                    else:
                        require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
                                "purge-unexpected-file-type")
                        if deleting:
                            os.unlink(name, dir_fd=descriptor)
                if deleting:
                    os.fsync(descriptor)

            visit(root, 0, False)
            count = 0
            visit(root, 0, True)
        finally:
            os.close(root)
        os.rmdir(path.name, dir_fd=parent)
        os.fsync(parent)
