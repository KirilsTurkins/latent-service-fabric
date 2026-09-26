"""Host probes run under the node identity before service activation."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import secrets
import sys

from .common import execute, require
from . import files
from .verify import PLATFORM, TARGET


def numeric(value: str) -> tuple[int, int]:
    match = re.match(r"([0-9]+)\.([0-9]+)", value)
    require(match is not None, "unknown-host-version")
    return int(match[1]), int(match[2])


def platform_check() -> dict:
    require(sys.platform == "linux" and platform.machine() == "x86_64", "supported-host-is-linux-x86_64")
    release = {}
    for line in files.read(Path("/usr/lib/os-release"), 8192).decode().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            release[key] = value.strip('"')
    require(release.get("ID") == PLATFORM["osId"] and release.get("VERSION_ID") == PLATFORM["osVersion"],
            "supported-distribution-is-ubuntu-24.04")
    require(numeric(platform.release()) >= numeric(PLATFORM["minimumKernel"]), "kernel-6.8-or-newer-required")
    libc = os.confstr("CS_GNU_LIBC_VERSION") or ""
    require(libc.startswith("glibc ") and numeric(libc[6:]) >= numeric(PLATFORM["minimumGlibc"]),
            "glibc-2.39-or-newer-required")
    require(sys.version_info >= (3, 12), "python-3.12-or-newer-required")
    cpu = files.read(Path("/proc/cpuinfo"), 1_048_576).decode()
    flags = [set(line.split(":", 1)[1].split()) for line in cpu.splitlines() if line.startswith("flags\t")]
    require(flags and all(set(PLATFORM["cpuFeatures"]) <= entry for entry in flags), "cpu-sse2-required")
    for name in ("cpu", "memory"):
        pressure = files.read(Path("/proc/pressure") / name, 4096)
        require(re.search(rb"some avg10=[0-9.]+ avg60=[0-9.]+ avg300=[0-9.]+ total=[0-9]+", pressure),
                "readable-cpu-and-memory-pressure-required")
    return {"target": TARGET, "distribution": "ubuntu-24.04", "kernel": platform.release(),
            "glibc": libc, "python": platform.python_version(), "pressureReadable": True}


def filesystem_probe(path: Path) -> None:
    import fcntl
    name = ".lsf-probe-" + secrets.token_hex(16)
    with files.directory(path, {0, os.geteuid()}) as parent:
        metadata = os.fstat(parent)
        require(metadata.st_uid == os.geteuid() and not metadata.st_mode & 0o077, "private-node-storage-required")
        descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=parent)
        try:
            os.write(descriptor, b"lsf-filesystem-probe-v1\n")
            os.fsync(descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            second = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            try:
                try:
                    fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    require(False, "filesystem-lock-exclusion-unavailable")
            finally:
                os.close(second)
            os.fsync(parent)
        finally:
            os.close(descriptor)
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)


def dynamic_probe(binary: Path) -> None:
    status, output = execute(["/usr/bin/ldd", str(binary)], maximum=32768, timeout=10)
    require(status == 0 and b"not found" not in output, "install-libc6-and-libgcc-s1")
