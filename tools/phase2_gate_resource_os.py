"""Bounded Linux observations of one still-owned node; no global PID adoption."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import time

from tools.phase2_gate_resource_profile import PROFILE
from tools.phase2_operator_process import require


def checkpoint(deadline=None, cancellation=None):
    if cancellation is not None:
        cancellation.check()
    require(deadline is None or time.monotonic() < deadline, "resource-deadline")


def hash_file(path, maximum, proc_executable=False, deadline=None, cancellation=None):
    checkpoint(deadline, cancellation)
    if not proc_executable:
        require(path.is_file() and not path.is_symlink(), "identity-file")
    with path.open("rb", buffering=0) as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= maximum, "identity-file-bound")
        total = 0
        hasher = hashlib.sha256()
        while True:
            checkpoint(deadline, cancellation)
            data = stream.read(min(65536, maximum - total + 1))
            if not data:
                break
            total += len(data)
            require(total <= maximum, "identity-file-bound")
            hasher.update(data)
        after = os.fstat(stream.fileno())
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            and total == before.st_size, "identity-file-changed")
    return "sha256:" + hasher.hexdigest()


def fixture_inventory(root, deadline=None, cancellation=None):
    pending, rows, total, visited = [root], [], 0, 0
    while pending:
        checkpoint(deadline, cancellation)
        parent = pending.pop()
        require(not parent.is_symlink(), "fixture-link")
        with os.scandir(parent) as entries:
            for entry in entries:
                checkpoint(deadline, cancellation)
                visited += 1
                require(visited <= PROFILE["maximumFixtureFiles"] and not entry.is_symlink(),
                        "fixture-inventory-bound")
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                else:
                    require(entry.is_file(follow_symlinks=False), "fixture-file")
                    size = entry.stat(follow_symlinks=False).st_size
                    total += size
                    require(total <= PROFILE["maximumFixtureBytes"], "fixture-byte-bound")
                    rows.append({"path": path.relative_to(root).as_posix(), "bytes": size,
                                 "digest": hash_file(path, PROFILE["maximumFixtureBytes"],
                                                     deadline=deadline, cancellation=cancellation)})
    rows.sort(key=lambda row: row["path"])
    return rows


class Probe:
    def __init__(self, process, executable, expected_digest, deadline):
        self.process = process
        self.pid = process.owner.process.pid
        before = self.stat()
        require(int(before[2]) == self.pid and int(before[3]) == self.pid,
                "node-owned-session")
        self.start = before[19]
        require(hash_file(Path(f"/proc/{self.pid}/exe"), PROFILE["maximumBinaryBytes"], True,
                          deadline, process.cancellation)
                == expected_digest, "node-executable-identity")
        info = executable.stat()
        actual = Path(f"/proc/{self.pid}/exe").stat()
        require((info.st_dev, info.st_ino, info.st_size) ==
                (actual.st_dev, actual.st_ino, actual.st_size), "node-executable-inode")
        self.current()
        self.identity = {"processId": self.pid, "startTimeTicks": self.start,
                         "executableDigest": expected_digest, "ownedProcessGroup": self.pid,
                         "executableDevice": str(actual.st_dev), "executableInode": str(actual.st_ino),
                         "exitedSuccessfully": False, "reapedByOwner": False}

    def stat(self):
        with Path(f"/proc/{self.pid}/stat").open("rb") as source:
            value = source.read(4097)
        require(len(value) <= 4096, "proc-stat-bound")
        fields = value.rpartition(b") ")[2].decode("ascii").split()
        require(len(fields) >= 22 and fields[0] not in ("Z", "X"), "node-not-live")
        return fields

    def current(self):
        require(not self.process.owner.exited(), "node-unexpected-exit")
        value = self.stat()
        require(value[19] == self.start and int(value[2]) == self.pid
                and int(value[3]) == self.pid, "node-process-identity")
        return value

    def sample(self):
        limits = PROFILE["proc"]
        deadline = time.monotonic() + limits["sampleSeconds"]
        remaining = 4 * 1024 * 1024
        root = Path(f"/proc/{self.pid}")
        self.current()

        def read(path, maximum=limits["fileBytes"]):
            nonlocal remaining
            require(time.monotonic() < deadline, "proc-sample-deadline")
            with path.open("rb") as source:
                value = source.read(min(maximum, remaining) + 1)
            require(len(value) <= maximum and len(value) <= remaining, "proc-read-bound")
            remaining -= len(value)
            return value.decode("ascii")

        status = dict(line.split(":", 1) for line in read(root / "status").splitlines())
        io = dict(line.split(":", 1) for line in read(root / "io").splitlines())
        sockets, descriptors = set(), 0
        with os.scandir(root / "fd") as entries:
            for entry in entries:
                descriptors += 1
                require(descriptors <= limits["fds"] and time.monotonic() < deadline,
                        "proc-fd-bound")
                target = os.readlink(entry.path)
                require(len(target) <= 4096, "proc-link-bound")
                match = re.fullmatch(r"socket:\[([0-9]{1,20})\]", target)
                if match:
                    sockets.add(match[1])
        tasks, children = 0, set()
        with os.scandir(root / "task") as entries:
            for entry in entries:
                tasks += 1
                require(tasks <= limits["tasks"] and entry.name.isdecimal(), "proc-task-bound")
                for child in read(Path(entry.path) / "children").split():
                    require(child.isdecimal() and len(children) < 32, "proc-child-bound")
                    children.add(child)
        listening = set()
        for table in ("tcp", "tcp6"):
            lines = read(root / "net" / table, limits["networkBytes"]).splitlines()
            require(len(lines) <= limits["networkRows"] + 1, "proc-network-bound")
            for line in lines[1:]:
                columns = line.split()
                require(len(columns) >= 10, "proc-network-shape")
                if columns[9] in sockets and columns[3] == "0A":
                    listening.add(columns[9])
        after = self.current()
        require(time.monotonic() < deadline, "proc-sample-deadline")
        require(tasks == int(status["Threads"]), "proc-task-race")
        return {
            "processId": self.pid, "startTimeTicks": self.start,
            "observedMonotonicNanos": str(time.monotonic_ns()),
            "rssBytes": str(int(status["VmRSS"].split()[0]) * 1024),
            "kernelHighWaterRssBytes": str(int(status["VmHWM"].split()[0]) * 1024),
            "cpuUserTicks": after[11], "cpuSystemTicks": after[12],
            "readBytes": io["read_bytes"].strip(), "writeBytes": io["write_bytes"].strip(),
            "threads": int(status["Threads"]), "tasks": tasks, "fdCount": descriptors,
            "socketCount": len(sockets), "listeningTcpSockets": len(listening),
            "descendants": len(children), "procBytesRead": 4 * 1024 * 1024 - remaining,
        }
