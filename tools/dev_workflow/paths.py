"""Exact-byte source inputs; no symlinks, reparse points or portable aliases."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import os
from pathlib import Path, PurePosixPath
import stat
import unicodedata

from .common import DevError, MAX_FILE, require

FORBIDDEN = {".git", ".latent", ".devcontainer", ".ssh", ".aws", ".azure", ".env", "node_modules", "target", "__pycache__"}
RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(10)), *(f"lpt{n}" for n in range(10))}


def relative(value: str) -> str:
    require(isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 1024, "source-path-limit")
    require(not any(ord(c) < 32 or c in '\\:<>"|?*' for c in value), "unsafe-source-path")
    parts = value.split("/")
    require(len(parts) <= 32 and all(part not in {"", ".", ".."} for part in parts), "source-path-traversal")
    require(all(not part.endswith((".", " ")) and len(part.encode("utf-8")) <= 240 for part in parts),
            "source-path-alias")
    require(all(part.split(".")[0].casefold() not in RESERVED for part in parts), "reserved-source-path")
    require(not PurePosixPath(value).is_absolute(), "absolute-source-path")
    return value


def alias(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def excluded(value: str, exclusions: tuple[str, ...] = ()) -> bool:
    return (any(alias(part) in FORBIDDEN or alias(part).startswith(".env.") for part in value.split("/"))
            or any(alias(value) == alias(name) or alias(value).startswith(alias(name) + "/")
                   for name in exclusions))


def regular(metadata) -> None:
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1, "single-link-regular-file-required")
    require(not getattr(metadata, "st_file_attributes", 0) & 0x400, "reparse-point-rejected")


def absolute(path: Path) -> Path:
    require(path.is_absolute() and ".." not in path.parts, "absolute-owned-path-required")
    require(len(str(path)) <= 32700, "absolute-path-limit")
    return path


@contextmanager
def directory(path: Path):
    """Anchor ancestors for the lifetime of a read, including Windows renames."""
    absolute(path)
    if os.name == "nt":
        from .windows import anchored_directory
        with anchored_directory(path) as anchor:
            yield anchor
    else:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in path.parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            yield descriptor
        finally:
            os.close(descriptor)


@contextmanager
def opened(root: Path, name: str):
    relative(name)
    path = absolute(root) / name
    with directory(path.parent):
        if os.name == "nt":
            from .windows import open_file
            descriptor = open_file(path)
        else:
            # Open through the held parent, never re-resolve its pathname.
            with directory(path.parent) as parent:
                descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                     dir_fd=parent)
        try:
            regular(os.fstat(descriptor))
            yield descriptor
        finally:
            os.close(descriptor)


def read(root: Path, name: str, maximum: int = MAX_FILE) -> bytes:
    try:
        with opened(root, name) as descriptor:
            before = os.fstat(descriptor)
            require(before.st_size <= maximum, "file-byte-limit")
            chunks = []
            used = 0
            while True:
                chunk = os.read(descriptor, min(65536, maximum + 1 - used))
                if not chunk:
                    break
                used += len(chunk)
                require(used <= maximum, "file-byte-limit")
                chunks.append(chunk)
            after = os.fstat(descriptor)
            require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "source-changed-during-read")
            return b"".join(chunks)
    except OSError as error:
        raise DevError("source-file-unavailable-or-unsafe") from error


def digest_file(root: Path, name: str, maximum: int = MAX_FILE, *, check=None) -> tuple[str, int]:
    import hashlib
    if check is not None:
        check()
    with opened(root, name) as descriptor:
        before = os.fstat(descriptor)
        require(before.st_size <= maximum, "file-byte-limit")
        checksum, size = hashlib.sha256(), 0
        while raw := os.read(descriptor, 1024 * 1024):
            if check is not None:
                check()
            size += len(raw)
            require(size <= maximum, "file-byte-limit")
            checksum.update(raw)
        after = os.fstat(descriptor)
        if check is not None:
            check()
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns) and size == before.st_size,
                "source-changed-during-read")
        return "sha256:" + checksum.hexdigest(), size


def new_directory(path: Path) -> None:
    absolute(path)
    with directory(path.parent):
        # Python 3.13 maps 0700 to a private DACL on Windows, including at creation.
        path.mkdir(mode=0o700)


def write_new(path: Path, raw: bytes) -> None:
    with directory(absolute(path).parent):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())


def private_root(path: Path) -> None:
    with directory(absolute(path)):
        if os.name == "nt":
            from .windows import check_private
            check_private(path)
        else:
            metadata = path.stat()
            require(metadata.st_uid == os.geteuid() and not metadata.st_mode & 0o077,
                    "private-state-directory-required")


@contextmanager
def held_paths(root: Path, names: list[str]):
    with ExitStack() as stack:
        handles = {name: stack.enter_context(opened(root, name)) for name in names}
        yield handles
