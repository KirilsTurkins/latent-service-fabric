"""Bounded committed source capture for the maintained provenance recipe."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile
import tomllib

from tools.build_process import run_bounded
from tools.build_process_signals import owned_cancellation


# Captures every current workspace member and build input, excluding historical
# benchmark evidence (~484 MB), docs and generated/ignored target trees.
SOURCE_ALLOWLIST = (
    ".cargo", "Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "rustfmt.toml",
    "apps", "crates", "tools", "schemas", "wit", "api", "sdk/rust", "examples",
)
REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SEGMENT = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z", re.I)


class SnapshotError(RuntimeError):
    """Static public error without source paths or command output."""


@dataclass(frozen=True)
class SnapshotLimits:
    max_entries: int = 4096
    max_file_bytes: int = 4 * 1024 * 1024
    max_total_bytes: int = 32 * 1024 * 1024
    max_archive_bytes: int = 40 * 1024 * 1024

    def validate(self) -> None:
        hard = SnapshotLimits()
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= getattr(hard, name):
                raise SnapshotError("invalid source capture limits")


@dataclass(frozen=True)
class SourceSnapshot:
    root: Path
    revision: str
    inventory: bytes

    @property
    def digest(self) -> str:
        return digest(self.inventory)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def portable_path(value: str) -> str:
    if not value or len(value) > 512 or value.startswith("/") or "\\" in value:
        raise SnapshotError("invalid captured source path")
    pieces = value.split("/")
    if len(pieces) > 16 or any(
        not SEGMENT.fullmatch(piece) or piece in (".", "..")
        or piece.endswith(".") or DEVICE.fullmatch(piece) for piece in pieces
    ):
        raise SnapshotError("invalid captured source path")
    return value


def is_reparse(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(path.lstat(), "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def owned_child(path: Path, parent: Path) -> Path:
    """Validate the exact absolute target before recursive filesystem operations."""
    resolved_parent = parent.resolve(strict=True)
    resolved = path.resolve()
    if resolved == resolved_parent or resolved_parent not in resolved.parents:
        raise SnapshotError("generated directory escapes its approved root")
    current = path
    while current != parent:
        if os.path.lexists(current) and is_reparse(current):
            raise SnapshotError("generated directory contains a filesystem link")
        if current == current.parent:
            raise SnapshotError("generated directory escapes its approved root")
        current = current.parent
    return resolved


def remove_owned_directory(path: Path, parent: Path) -> None:
    resolved = owned_child(path, parent)
    if resolved.exists():
        shutil.rmtree(resolved)


def git_environment() -> dict[str, str]:
    """Local read-only Git commands inherit no credentials or Git overrides."""
    names = ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "USERPROFILE", "HOME",
             "APPDATA", "LOCALAPPDATA", "PATHEXT", "TEMP", "TMP", "TMPDIR")
    environment = {name: os.environ[name] for name in names if name in os.environ}
    environment.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0"})
    return environment


def _selected(path: str) -> bool:
    return any(path == root or path.startswith(root + "/") for root in SOURCE_ALLOWLIST)


def extract_archive(archive: bytes, destination: Path, limits: SnapshotLimits,
                    cancellation=None) -> bytes:
    """Read a bounded tar without extractall, links, special files or implicit paths."""
    limits.validate()
    if len(archive) > limits.max_archive_bytes:
        raise SnapshotError("source archive byte limit exceeded")
    destination.mkdir()
    inventory = []
    seen: dict[str, tuple[str, bool]] = {}
    spellings: dict[str, str] = {}
    parent_paths: set[str] = set()
    file_paths: set[str] = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for count, entry in enumerate(stream, 1):
            if cancellation is not None:
                cancellation.check()
            if count > limits.max_entries:
                raise SnapshotError("source archive entry limit exceeded")
            path = portable_path(entry.name.rstrip("/") if entry.isdir() else entry.name)
            if not _selected(path) and not any(root.startswith(path + "/") for root in SOURCE_ALLOWLIST):
                raise SnapshotError("source archive contains an unselected path")
            if not (entry.isdir() or entry.isreg()) or entry.mode & ~0o777:
                raise SnapshotError("source archive contains a link or special file")
            lowered = path.lower()
            if lowered in seen:
                raise SnapshotError("duplicate or colliding captured source path")
            parts = path.split("/")
            for length in range(1, len(parts) + 1):
                prefix = "/".join(parts[:length])
                if spellings.setdefault(prefix.lower(), prefix) != prefix:
                    raise SnapshotError("colliding captured source prefix")
            for parent in PurePosixPath(path).parents:
                name = str(parent)
                if name == ".":
                    continue
                prior = seen.get(name.lower())
                if name.lower() in file_paths or (prior is not None and prior[0] != name):
                    raise SnapshotError("colliding captured source prefix")
            if not entry.isdir() and lowered in parent_paths:
                raise SnapshotError("colliding captured source prefix")
            parent_paths.update("/".join(parts[:length]).lower() for length in range(1, len(parts)))
            seen[lowered] = (path, entry.isdir())
            target = destination.joinpath(*path.split("/"))
            owned_child(target, destination)
            if entry.isdir():
                if entry.size != 0:
                    raise SnapshotError("invalid captured directory")
                target.mkdir(parents=True, exist_ok=True)
                continue
            if entry.size < 0 or entry.size > limits.max_file_bytes:
                raise SnapshotError("captured source file limit exceeded")
            total += entry.size
            if total > limits.max_total_bytes:
                raise SnapshotError("captured source total limit exceeded")
            extracted = stream.extractfile(entry)
            if extracted is None:
                raise SnapshotError("captured source file is unavailable")
            with extracted:
                data = extracted.read(entry.size + 1)
            if len(data) != entry.size:
                raise SnapshotError("captured source length mismatch")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(data)
            # Preserve Git's executable/nonexecutable distinction, normalizing
            # archive umask-dependent permission bits; Windows records that mode.
            mode = 0o755 if entry.mode & 0o111 else 0o644
            if os.name != "nt":
                target.chmod(mode)
            inventory.append({"path": path, "digest": digest(data), "size": len(data), "mode": mode})
            file_paths.add(lowered)
    if not inventory:
        raise SnapshotError("captured source is empty")
    return canonical(sorted(inventory, key=lambda row: row["path"]))


def validate_workspace(snapshot: Path) -> None:
    with (snapshot / "Cargo.toml").open("rb") as source:
        metadata = tomllib.load(source)
    members = metadata.get("workspace", {}).get("members", [])
    if not isinstance(members, list) or not 1 <= len(members) <= 256:
        raise SnapshotError("unsupported captured workspace")
    for member in members:
        if not isinstance(member, str) or not _selected(portable_path(member)):
            raise SnapshotError("workspace member is outside captured source selection")
        if not (snapshot / member / "Cargo.toml").is_file():
            raise SnapshotError("captured workspace member is missing")


@contextmanager
def capture_source(repository: Path, revision: str, target_root: Path,
                   limits: SnapshotLimits = SnapshotLimits()):
    with owned_cancellation() as cancellation:
        with _capture_source(repository, revision, target_root, limits, cancellation) as snapshot:
            yield snapshot


@contextmanager
def _capture_source(repository: Path, revision: str, target_root: Path,
                    limits: SnapshotLimits, cancellation):
    limits.validate()
    if not REVISION.fullmatch(revision):
        raise SnapshotError("source revision must be an exact lowercase Git commit")
    repository = repository.resolve(strict=True)
    target_root = target_root.resolve(strict=True)
    temporary = None
    try:
        with cancellation.defer():
            temporary = Path(tempfile.mkdtemp(prefix="lsf-source-", dir=target_root))
            owned_child(temporary, target_root)
        common = {"cwd": repository, "env": git_environment(), "timeout_seconds": 30}
        result = run_bounded(["git", "rev-parse", "--verify", revision + "^{commit}"],
                             max_output_bytes=1024, **common)
        if result.stdout.decode("ascii").strip() != revision:
            raise SnapshotError("source revision is not an exact commit")
        # ls-tree also rejects gitlinks/symlinks before archive, including
        # submodules that git archive would otherwise turn into empty folders.
        listing = run_bounded(["git", "ls-tree", "-r", "-z", "--full-tree", revision,
                               "--", *SOURCE_ALLOWLIST], max_output_bytes=2 * 1024 * 1024, **common)
        selected_roots: set[str] = set()
        entries = listing.stdout.split(b"\0")
        if len(entries) - 1 > limits.max_entries:
            raise SnapshotError("source tree entry limit exceeded")
        for entry in entries:
            if not entry:
                continue
            header, raw_path = entry.split(b"\t", 1)
            mode, kind, _object = header.split(b" ")
            if mode not in (b"100644", b"100755") or kind != b"blob":
                raise SnapshotError("captured source contains a link or submodule")
            path = portable_path(raw_path.decode("ascii"))
            selected_roots.update(root for root in SOURCE_ALLOWLIST if path == root or path.startswith(root + "/"))
        if not selected_roots:
            raise SnapshotError("captured source selection is empty")
        result = run_bounded(["git", "archive", "--format=tar", revision, "--", *sorted(selected_roots)],
                             max_output_bytes=limits.max_archive_bytes, **common)
        root = temporary / "source"
        inventory = extract_archive(result.stdout, root, limits, cancellation)
        cancellation.check()
        validate_workspace(root)
        yield SourceSnapshot(root, revision, inventory)
    finally:
        if temporary is not None:
            with cancellation.defer():
                remove_owned_directory(temporary, target_root)
