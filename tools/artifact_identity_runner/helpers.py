"""Bounded helper output, including large interpreted allocation traces."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time

from .files import fingerprint, write_json
from .model import MAX_FILE_BYTES, MAX_TOTAL_BYTES
from .resources import process_stat


@dataclass(frozen=True)
class DirectoryLimits:
    maximum_depth: int = 0
    maximum_files: int = 16
    maximum_entries: int = 16
    maximum_file_bytes: int = MAX_FILE_BYTES

    def __post_init__(self):
        values = (self.maximum_depth, self.maximum_files, self.maximum_entries, self.maximum_file_bytes)
        if (any(type(value) is not int for value in values) or not 0 <= self.maximum_depth <= 2
                or not 1 <= self.maximum_files <= 64 or not self.maximum_files <= self.maximum_entries <= 80
                or not 1 <= self.maximum_file_bytes <= 512 * 1024**2):
            raise ValueError("helper-directory-limits")


def directory_bytes(directory: Path, limits: DirectoryLimits | None = None, *,
                    minimum_file_sizes: dict[Path, int] | None = None,
                    temporary_file: Path | None = None) -> int:
    limits = limits or DirectoryLimits()
    if temporary_file is not None and (not isinstance(temporary_file, Path)
                                      or temporary_file.parent != directory):
        raise ValueError("helper-temporary-file-path")
    minimum_file_sizes = minimum_file_sizes or {}
    if (len(minimum_file_sizes) > limits.maximum_files
            or any(not isinstance(path, Path) or type(size) is not int or size < 0
                   for path, size in minimum_file_sizes.items())):
        raise ValueError("helper-artifact-minimum-size")
    root = directory.lstat()
    if not stat.S_ISDIR(root.st_mode) or getattr(root, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("helper-artifact-count-or-type")
    total = 0
    files = entries = matched_minimums = 0
    pending = [(directory, 0)]
    while pending:
        current, depth = pending.pop()
        with os.scandir(current) as children:
            for child in children:
                entries += 1
                if entries > limits.maximum_entries:
                    raise ValueError("helper-artifact-count-or-type")
                value = child.stat(follow_symlinks=False)
                if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ValueError("helper-artifact-count-or-type")
                if stat.S_ISDIR(value.st_mode):
                    if Path(child.path) == temporary_file:
                        raise ValueError("helper-temporary-file-type")
                    if depth >= limits.maximum_depth:
                        raise ValueError("helper-artifact-depth-bound" if limits.maximum_depth else "helper-artifact-count-or-type")
                    pending.append((Path(child.path), depth + 1))
                elif stat.S_ISREG(value.st_mode):
                    files += 1
                    if files > limits.maximum_files:
                        raise ValueError("helper-artifact-count-or-type")
                    path = Path(child.path)
                    matched_minimums += path in minimum_file_sizes
                    # Directory entries can lag an open writer, including on Windows.
                    size = max(value.st_size, minimum_file_sizes.get(path, 0))
                    maximum = (limits.maximum_file_bytes if temporary_file is None or path == temporary_file
                               else min(limits.maximum_file_bytes, MAX_FILE_BYTES))
                    if size > maximum:
                        raise ValueError("helper-artifact-byte-bound")
                    # One explicitly named expanded stream owns a separate bounded
                    # scratch allowance. All other files, including its gzip, count.
                    if path != temporary_file:
                        total += size
                else:
                    raise ValueError("helper-artifact-count-or-type")
    if matched_minimums != len(minimum_file_sizes):
        raise ValueError("helper-artifact-count-or-type")
    return total


def command(argv: list[str], log: Path, timeout: int, cwd: Path, deadline: int,
            env: dict | None = None, maximum: int = 16 * 1024 * 1024,
            watched: Path | None = None, remaining: int = MAX_TOTAL_BYTES,
            directory_limits: DirectoryLimits | None = None,
            temporary_file: Path | None = None) -> dict:
    if temporary_file is not None and (not isinstance(temporary_file, Path) or watched is None
                                      or temporary_file.parent != watched):
        raise ValueError("helper-temporary-file-path")
    checksum = fingerprint(Path(argv[0]))[0]
    until = min(deadline, time.monotonic_ns() + timeout * 1_000_000_000)
    receipt = {"process_id": None, "start_time_ticks": None, "role": "artifact-identity-helper",
               "executable_sha256": checksum, "reaped": False, "output_closed": False, "exit_code": None}
    child = None
    selector = selectors.DefaultSelector()
    try:
        with log.open("xb") as destination:
            if time.monotonic_ns() >= until:
                raise TimeoutError("helper-deadline-before-spawn")
            child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            receipt["process_id"] = child.pid
            receipt["start_time_ticks"] = process_stat(child.pid)[19]
            os.set_blocking(child.stdout.fileno(), False)
            selector.register(child.stdout, selectors.EVENT_READ)
            count = 0
            while selector.get_map() or os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                if time.monotonic_ns() > until:
                    raise TimeoutError("helper-deadline")
                for key, _ in selector.select(0.01):
                    block = os.read(key.fd, 65536)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    count += len(block)
                    if count > maximum:
                        raise ValueError("helper-output-bound")
                    destination.write(block)
                if watched is not None and directory_bytes(watched, directory_limits,
                                                          temporary_file=temporary_file) > remaining:
                    raise ValueError("helper-total-output-bound")
            if watched is not None and directory_bytes(watched, directory_limits,
                                                      temporary_file=temporary_file) > remaining:
                raise ValueError("helper-total-output-bound")
    finally:
        if child is not None:
            # Keep the leader unreaped until its exclusively owned group closes.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5)
            child.stdout.close()
            receipt.update(reaped=True, output_closed=True, exit_code=child.returncode)
        selector.close()
        write_json(log.with_suffix(log.suffix + ".process.json"), receipt)
    if receipt["exit_code"] != 0:
        raise RuntimeError("helper-exit-failed")
    return receipt
