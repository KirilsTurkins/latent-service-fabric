"""Bounded committed source capture for the maintained provenance recipe."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import binascii
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import tarfile
import tempfile
import tomllib

from tools.build_process import run_bounded
from tools.build_process_signals import owned_cancellation


# Captures every current workspace member and build input, excluding historical
# benchmark evidence, docs and generated/ignored target trees.
SOURCE_ALLOWLIST = (
    ".cargo", "Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "rustfmt.toml",
    "apps", "crates", "tools", "schemas", "wit", "api", "sdk/rust", "sdk/rust-guest",
    "sdk/rust-standard-stdio", "examples",
)
REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SEGMENT = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z", re.I)


class SnapshotError(RuntimeError):
    """Static public error without source paths or command output."""


# The committed tools tree includes ownership-local CI contracts. Keep a
# fixed, reviewed file budget shared with the downstream attribution reader;
# directory, per-file, total-byte and archive-byte budgets remain independent.
# The current selected tree includes the authenticated Wasmtime source and
# exceeds 72 MiB: revision 976e86c has 75,529,037 archived file bytes.
# Retain every selected compiler input within fixed 76 MiB source / 83 MiB
# archive caps; activation/runtime budgets are independent.
# The 2026-10-25 selection at 36a2620 has 8,707 files and an 83,916,800-byte
# Git archive. Its next finite 256-file allowance is shared by capture and Cargo
# attribution; archive transport gets two MiB and no selected input is dropped.
# The 2026-10-25 local-service diagnostic adds more than the 21,034 source bytes
# left at 4168d40; one finite source MiB retains every input. Other caps stay fixed.
# Before this adjustment, R8 totals 77,779,641 archived file bytes, exceeding
# 74 MiB by 185,017 bytes; one finite source MiB retains all selected inputs.
# The 2026-10-29 tree at 877af selects 78,641,503 checkout source bytes.
# The v27 integration adds 67,917 bytes before this finite source adjustment.
# Its 86,353,920-byte Git tar exceeds 82 MiB; retain fixed 83 MiB transport.
# Source and archive framing caps remain independent; runtime budgets stay fixed.
# CI measured 9,037 selected files at the #660 merge fa5395e, exceeding
# the old 8,992-file allowance before compiler work. Add one fixed
# 256-file allowance, shared with attribution, without dropping inputs
# or changing byte, directory, archive or runtime limits.
MAX_SOURCE_FILES = 9248


@dataclass(frozen=True)
class SnapshotLimits:
    max_entries: int = MAX_SOURCE_FILES
    max_directories: int = 4096
    max_file_bytes: int = 4 * 1024 * 1024
    max_total_bytes: int = 76 * 1024 * 1024
    max_archive_bytes: int = 83 * 1024 * 1024

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
                    cancellation=None, *, archive_format="tar", expected_files=None, revision=None) -> bytes:
    """Read a bounded tar without extractall, links, special files or implicit paths."""
    if archive_format == "stored-zip":
        return _extract_stored_zip(archive, destination, limits, cancellation, expected_files, revision)
    if archive_format != "tar":
        raise SnapshotError("source archive format is unsupported")
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
    files = directories = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for entry in stream:
            if cancellation is not None:
                cancellation.check()
            # Git ls-tree counts files; git archive also emits directory
            # headers. Bound both inventories without charging those headers
            # against the documented source-file allowance a second time.
            if entry.isdir():
                directories += 1
            else:
                files += 1
            if files > limits.max_entries or directories > limits.max_directories:
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


def _zip_require(value, reason):
    if not value:
        raise SnapshotError("stored source ZIP " + reason)


def _stored_zip_expectations(expected_files, limits):
    _zip_require(type(expected_files) is dict and 1 <= len(expected_files) <= limits.max_entries,
                 "expected file inventory is invalid")
    expected_dirs = set()
    spellings = {}
    folded_files = set()
    for name, mode in expected_files.items():
        _zip_require(type(name) is str and portable_path(name) == name and _selected(name),
                     "expected path is invalid")
        _zip_require(type(mode) is str and mode in ("100644", "100755"), "expected Git mode is invalid")
        _zip_require(name.lower() not in folded_files, "expected paths collide")
        folded_files.add(name.lower())
        parts = name.split("/")
        for length in range(1, len(parts) + 1):
            prefix = "/".join(parts[:length])
            _zip_require(spellings.setdefault(prefix.lower(), prefix) == prefix,
                         "expected path prefixes collide")
            if length < len(parts):
                expected_dirs.add(prefix)
                _zip_require(len(expected_dirs) <= limits.max_directories, "directory limit exceeded")
    _zip_require(not any(name.lower() in folded_files for name in expected_dirs),
                 "expected file and directory prefixes collide")
    return expected_dirs


def _stored_zip_preflight(archive, limits, expected_files, revision, cancellation):
    """Closed Git/STORED subset; no filesystem effects or ZipFile allocation."""
    _zip_require(type(archive) is bytes, "must be bytes")
    _zip_require(type(revision) is str and REVISION.fullmatch(revision), "revision is invalid")
    _zip_require(len(archive) <= limits.max_archive_bytes, "archive byte limit exceeded")
    expected_dirs = _stored_zip_expectations(expected_files, limits)

    # The only EOCD comment is the exact requested Git revision. Its known
    # length locates EOCD without an attacker-controlled signature search.
    comment = revision.encode("ascii")
    eocd = len(archive) - 22 - len(comment)
    _zip_require(eocd >= 0, "EOCD is truncated")
    end = struct.unpack_from("<4s4H2IH", archive, eocd)
    signature, disk, central_disk, disk_count, count, central_size, central, comment_size = end
    _zip_require(signature == b"PK\x05\x06" and comment_size == len(comment) and
                 archive[eocd + 22:] == comment, "EOCD or commit comment is invalid")
    _zip_require(disk == central_disk == 0 and disk_count == count and
                 0 < count <= limits.max_entries + limits.max_directories and count != 0xffff,
                 "multipart or excessive central directory")
    _zip_require(central != 0xffffffff and central_size != 0xffffffff and
                 central + central_size == eocd and central_size >= 46 * count,
                 "central directory extent is invalid")

    # Parse exactly the bounded central records before allocating any ZIP
    # metadata collection. No ZIP64, decryption, decompressor or format fallback.
    position = central
    next_local = 0
    seen = set()
    actual_files = set()
    actual_dirs = set()
    rows = []
    total = 0
    commit_timestamp = None
    for _ in range(count):
        if cancellation is not None:
            cancellation.check()
        _zip_require(position + 46 <= eocd, "central header is truncated")
        fields = struct.unpack_from("<4s6H3I5H2I", archive, position)
        (signature, creator, version, flags, method, time, date, crc, stored, size,
         name_size, extra_size, entry_comment, start_disk, internal, external, local) = fields
        _zip_require(signature == b"PK\x01\x02" and version == 10 and flags in (0, 8) and
                     method == 0 and start_disk == 0 and internal in (0, 1),
                     "unsupported central header")
        _zip_require(stored == size and size != 0xffffffff and local != 0xffffffff and
                     0 < name_size <= 512 and entry_comment == 0 and extra_size == 9,
                     "unsupported sizes, compression or metadata")
        stop = position + 46 + name_size + extra_size
        _zip_require(stop <= eocd, "central variable fields are truncated")
        name_raw = archive[position + 46:position + 46 + name_size]
        try:
            encoded_name = name_raw.decode("ascii", "strict")
        except UnicodeError as error:
            raise SnapshotError("stored source ZIP path encoding is invalid") from error
        extra = archive[position + 46 + name_size:stop]
        _zip_require(extra[:5] == b"UT\x05\x00\x01", "unsupported extra fields")
        timestamp = extra[5:]
        if commit_timestamp is None:
            commit_timestamp = timestamp
        _zip_require(timestamp == commit_timestamp, "inconsistent commit timestamp metadata")
        directory = encoded_name.endswith("/")
        name = encoded_name[:-1] if directory else encoded_name
        _zip_require(portable_path(name) == name and
                     encoded_name == name + ("/" if directory else ""), "path is noncanonical")
        _zip_require(name.lower() not in seen, "duplicate or colliding path")
        seen.add(name.lower())
        if directory:
            _zip_require(name in expected_dirs and flags == 0 and size == stored == crc == 0,
                         "unexpected directory or directory payload")
            actual_dirs.add(name)
            _zip_require(len(actual_dirs) <= limits.max_directories, "directory limit exceeded")
            mode = None
        else:
            _zip_require(name in expected_files, "unexpected source file")
            actual_files.add(name)
            _zip_require(len(actual_files) <= limits.max_entries and size <= limits.max_file_bytes,
                         "file count or byte limit exceeded")
            total += size
            if total > limits.max_total_bytes:
                raise SnapshotError("captured source total limit exceeded")
            mode = 0o755 if expected_files[name] == "100755" else 0o644

        creator_system = creator >> 8
        unix_mode, dos_mode = external >> 16, external & 0xffff
        if creator_system == 0:
            _zip_require(unix_mode == 0 and dos_mode == (0x10 if directory else 0),
                         "unsupported DOS mode")
        elif creator_system == 3:
            kind = stat.S_IFDIR if directory else stat.S_IFREG
            _zip_require(stat.S_IFMT(unix_mode) == kind and not unix_mode & ~(kind | 0o777) and
                         dos_mode in ((0, 0x10) if directory else (0,)), "special or unsafe Unix mode")
            if not directory:
                _zip_require((0o755 if unix_mode & 0o111 else 0o644) == mode,
                             "Unix mode differs from Git mode")
        else:
            raise SnapshotError("stored source ZIP creator mode is unsupported")

        # Git's central and physical entry order agree. Exact contiguous local
        # coverage rejects aliases, overlaps, hidden records and prefix/gap data.
        _zip_require(local == next_local and local + 30 <= central, "local ranges alias or overlap")
        header = struct.unpack_from("<4s5H3I2H", archive, local)
        (local_sig, local_version, local_flags, local_method, local_time, local_date,
         local_crc, local_stored, local_size, local_name, local_extra) = header
        _zip_require(local_sig == b"PK\x03\x04" and
                     (local_version, local_flags, local_method, local_time, local_date) ==
                     (version, flags, method, time, date) and
                     local_name == name_size and local_extra == extra_size and
                     local_stored == stored and local_size == size and
                     local_crc == (0 if flags == 8 else crc), "local header differs from central header")
        payload = local + 30 + local_name + local_extra
        payload_end = payload + size
        _zip_require(payload_end <= central and archive[local + 30:local + 30 + local_name] == name_raw and
                     archive[local + 30 + local_name:payload] == extra, "local name or extent differs")
        next_local = payload_end
        if flags == 8:
            _zip_require(payload_end + 16 <= central, "data descriptor is truncated")
            descriptor = struct.unpack_from("<4s3I", archive, payload_end)
            _zip_require(descriptor == (b"PK\x07\x08", crc, stored, size), "data descriptor differs")
            next_local += 16
        _zip_require(binascii.crc32(memoryview(archive)[payload:payload_end]) & 0xffffffff == crc,
                     "payload CRC differs")
        if not directory:
            rows.append((name, payload, size, mode, crc))
        position = stop
    _zip_require(position == eocd and next_local == central, "unaccounted central or local bytes")
    _zip_require(actual_files == set(expected_files) and actual_dirs == expected_dirs,
                 "source inventory differs from Git")
    return rows


def _extract_stored_zip(archive, destination, limits, cancellation, expected_files, revision):
    limits.validate()
    rows = _stored_zip_preflight(archive, limits, expected_files, revision, cancellation)
    # All counts, names, modes, CRCs and extents are valid before the first
    # destination effect. Never use extractall or execute any source payload.
    destination.mkdir()
    inventory = []
    for name, offset, size, mode, crc in rows:
        if cancellation is not None:
            cancellation.check()
        target = destination.joinpath(*name.split("/"))
        owned_child(target, destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = archive[offset:offset + size]
        with target.open("xb") as output:
            _zip_require(output.write(data) == size, "source write was incomplete")
        with target.open("rb") as source:
            actual = source.read(size + 1)
        _zip_require(actual == data and len(actual) == size and
                     binascii.crc32(actual) & 0xffffffff == crc, "written source differs")
        if os.name != "nt":
            target.chmod(mode)
        inventory.append({"path": name, "digest": digest(actual), "size": size, "mode": mode})
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
        expected_files: dict[str, str] = {}
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
            if path in expected_files:
                raise SnapshotError("duplicate Git source path")
            expected_files[path] = mode.decode("ascii")
            selected_roots.update(root for root in SOURCE_ALLOWLIST if path == root or path.startswith(root + "/"))
        if not selected_roots:
            raise SnapshotError("captured source selection is empty")
        _stored_zip_expectations(expected_files, limits)
        result = run_bounded(["git", "archive", "--format=zip", "-0", revision, "--", *sorted(selected_roots)],
                             max_output_bytes=limits.max_archive_bytes, **common)
        root = temporary / "source"
        inventory = extract_archive(result.stdout, root, limits, cancellation,
            archive_format="stored-zip", expected_files=expected_files, revision=revision)
        cancellation.check()
        validate_workspace(root)
        yield SourceSnapshot(root, revision, inventory)
    finally:
        if temporary is not None:
            with cancellation.defer():
                remove_owned_directory(temporary, target_root)
