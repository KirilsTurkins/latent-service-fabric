"""Bounded reads of the runner's resolved cgroup v2, never an ancestor fallback.

Controller limits are local settings; an ancestor may impose a tighter ceiling.
Counters describe this shared cgroup, not the separately observed server PID.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path, PurePosixPath
import re
import stat


FILES = ("cpu.max", "cpu.stat", "memory.max", "memory.current", "memory.stat",
         "memory.events", "cpu.pressure", "memory.pressure", "io.pressure")
MEMBERSHIP_BYTES = 16 * 1024
MOUNTINFO_BYTES = 1024 * 1024
CONTROLLER_BYTES = 64 * 1024
_ESCAPES = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}


class ProbeError(Exception):
    """A fixed diagnostic without host exception text."""


def _reason(error: OSError) -> str:
    if error.errno in (errno.ENOENT, errno.ENOTDIR):
        return "missing"
    if error.errno in (errno.EACCES, errno.EPERM):
        return "permission-denied"
    return "unavailable"


def _read(path: str | Path, maximum: int, *, directory: int | None = None) -> str:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, dir_fd=directory)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ProbeError("invalid")
        chunks = bytearray()
        while len(chunks) <= maximum:
            chunk = os.read(descriptor, maximum + 1 - len(chunks))
            if not chunk:
                break
            chunks.extend(chunk)
        if len(chunks) > maximum:
            raise ProbeError("oversized")
        try:
            return chunks.decode("utf-8")
        except UnicodeError as error:
            raise ProbeError("invalid") from error
    finally:
        os.close(descriptor)


def _path(value: str) -> PurePosixPath:
    if not value.startswith("/") or value.startswith("//") or any(part in (".", "..") for part in value.split("/")) or "\0" in value:
        raise ProbeError("invalid")
    return PurePosixPath(value)


def _unescape(value: str) -> str:
    # Decode once: a literal backslash followed by 040 must remain literal.
    if re.search(r"\\(?!040|011|012|134)", value):
        raise ProbeError("invalid")
    return re.sub(r"\\(040|011|012|134)", lambda match: _ESCAPES[match[1]], value)


def resolve_candidates(membership: str, mountinfo: str) -> list[dict]:
    """Pure parser; directory identity is checked separately before any reads."""
    if len(membership.encode()) > MEMBERSHIP_BYTES or len(mountinfo.encode()) > MOUNTINFO_BYTES:
        raise ProbeError("oversized")
    entries = [line.split(":", 2) for line in membership.splitlines()]
    if any(len(entry) != 3 or not entry[0].isdigit() for entry in entries):
        raise ProbeError("invalid")
    unified = [entry[2] for entry in entries if entry[:2] == ["0", ""]]
    if len(unified) != 1:
        raise ProbeError("invalid")
    current = _path(unified[0])
    lines = mountinfo.splitlines()
    if len(lines) > 4096:
        raise ProbeError("oversized")
    candidates = []
    for line in lines:
        before, separator, after = line.partition(" - ")
        if not separator:
            raise ProbeError("invalid")
        filesystem = after.split()
        if len(filesystem) < 3:
            raise ProbeError("invalid")
        if filesystem[0] != "cgroup2":
            continue
        fields = before.split()
        if len(fields) < 6 or not fields[0].isdigit() or not re.fullmatch(r"[0-9]+:[0-9]+", fields[2]):
            raise ProbeError("invalid")
        root = _path(_unescape(fields[3]))
        point = _path(_unescape(fields[4]))
        try:
            relative = current.relative_to(root)
        except ValueError:
            continue
        candidates.append({"path": str(point / relative), "mount_id": fields[0],
                           "mount_root": str(root), "mount_point": str(point), "device": fields[2]})
        if len(candidates) > 64:
            raise ProbeError("oversized")
    return sorted(candidates, key=lambda item: (-len(PurePosixPath(item["mount_root"]).parts), item["path"]))


def _open_candidate(candidates: list[dict]) -> tuple[int, dict]:
    selected: tuple[int, dict] | None = None
    identity = None
    inaccessible = "unavailable"
    try:
        for candidate in candidates:
            try:
                descriptor = os.open(candidate["path"], os.O_RDONLY | os.O_DIRECTORY
                                     | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
            except OSError as error:
                inaccessible = _reason(error)
                continue
            keep = False
            try:
                info = os.fstat(descriptor)
                device = f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"
                if device != candidate["device"]:
                    raise ProbeError("invalid")
                observed = (info.st_dev, info.st_ino)
                if identity is not None and observed != identity:
                    raise ProbeError("ambiguous")
                if selected is None:
                    selected = (descriptor, {**candidate, "status": "resolved", "inode": str(info.st_ino)})
                    identity = observed
                    keep = True
            finally:
                if not keep:
                    os.close(descriptor)
        if selected is None:
            raise ProbeError(inaccessible)
        return selected
    except BaseException:
        if selected is not None:
            os.close(selected[0])
        raise


def _unsupported() -> dict:
    return {"status": "unsupported", **dict.fromkeys(("path", "mount_id", "mount_root", "mount_point", "device", "inode"))}


def cgroup(*, proc_root: Path = Path("/proc/self")) -> dict:
    """Preserve raw bounded counters and explicit unavailable measurements."""
    result = {"scope": "runner-cgroup-shared", "process_membership": "", **dict.fromkeys(FILES),
              "resolution": _unsupported(), "errors": {}}
    stage = "process_membership"
    descriptor = None
    try:
        membership = _read(proc_root / "cgroup", MEMBERSHIP_BYTES)
        result["process_membership"] = membership
        stage = "mountinfo"
        mountinfo = _read(proc_root / "mountinfo", MOUNTINFO_BYTES)
        stage = "resolution"
        descriptor, resolution = _open_candidate(resolve_candidates(membership, mountinfo))
        for name in FILES:
            try:
                result[name] = _read(name, CONTROLLER_BYTES, directory=descriptor)
            except ProbeError as error:
                result["errors"][name] = str(error)
            except OSError as error:
                result["errors"][name] = _reason(error)
        if _read(proc_root / "cgroup", MEMBERSHIP_BYTES) != membership:
            raise ProbeError("membership-changed")
        result["resolution"] = resolution
    except (ProbeError, OSError) as error:
        result["errors"][stage] = str(error) if isinstance(error, ProbeError) else _reason(error)
        result.update(dict.fromkeys(FILES))
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return result
