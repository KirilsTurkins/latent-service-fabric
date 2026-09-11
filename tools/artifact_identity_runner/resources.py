"""Bind observed probe resources to the still-owned launcher process group."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import time


def read(path: Path, maximum: int = 65536) -> str:
    with path.open("rb") as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError("proc-file-bound")
    return value.decode("utf-8")


def process_stat(pid: int) -> list[str]:
    value = read(Path(f"/proc/{pid}/stat"), 4096).rpartition(") ")[2].split()
    if len(value) < 22:
        raise ValueError("proc-stat-shape")
    return value


def sample(pid: int, start: str) -> dict:
    before = process_stat(pid)
    if before[19] != start or before[0] == "Z":
        raise ValueError("probe-not-live")
    root = Path(f"/proc/{pid}")
    fields = dict(line.split(":", 1) for line in read(root / "status").splitlines())
    io = dict(line.split(":", 1) for line in read(root / "io").splitlines())
    descriptors = 0
    with os.scandir(root / "fd") as entries:
        for _ in entries:
            descriptors += 1
            if descriptors > 4096:
                raise ValueError("probe-descriptor-bound")
    after = process_stat(pid)
    if after[19] != start or after[0] == "Z":
        raise ValueError("probe-changed-during-sample")
    return {
        "process_id": pid, "start_time_ticks": start, "observed_ns": str(time.monotonic_ns()),
        "rss_bytes": str(int(fields["VmRSS"].split()[0]) * 1024),
        "kernel_high_water_rss_bytes": str(int(fields["VmHWM"].split()[0]) * 1024),
        "cpu_user_ticks": after[11], "cpu_system_ticks": after[12],
        "threads": int(fields["Threads"]), "fd_count": descriptors,
        "read_bytes": io["read_bytes"].strip(), "write_bytes": io["write_bytes"].strip(),
    }


def bind(pid: int, owner, binary: Path, binary_sha256: str) -> dict:
    if isinstance(pid, bool) or not isinstance(pid, int) or not 1 < pid < 2**31:
        raise ValueError("probe-pid-invalid")
    before = process_stat(pid)
    if int(before[2]) != owner.child.pid or int(before[3]) != owner.child.pid:
        raise ValueError("probe-group-mismatch")
    parent = pid
    for _ in range(16):
        if parent == owner.child.pid:
            break
        parent = int(process_stat(parent)[1])
    else:
        raise ValueError("probe-ancestry-mismatch")
    with Path(f"/proc/{pid}/exe").open("rb") as executable:
        info = os.fstat(executable.fileno())
        expected = binary.stat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 256 * 1024 * 1024:
            raise ValueError("probe-executable-bound")
        if (info.st_dev, info.st_ino, info.st_size) != (expected.st_dev, expected.st_ino, expected.st_size):
            raise ValueError("probe-executable-mismatch")
    after = process_stat(pid)
    if before[19] != after[19] or owner.exited():
        raise ValueError("probe-identity-mismatch")
    return {"process_id": pid, "start_time_ticks": before[19],
            "executable_sha256": binary_sha256, "executable_device": str(info.st_dev),
            "executable_inode": str(info.st_ino), "owned_process_group": owner.child.pid,
            "observed_exited": False, "reaped_by_runner": pid == owner.child.pid}


def exited(identity: dict) -> bool:
    try:
        current = process_stat(identity["process_id"])
        return current[19] != identity["start_time_ticks"] or current[0] == "Z"
    except (FileNotFoundError, ProcessLookupError):
        return True
