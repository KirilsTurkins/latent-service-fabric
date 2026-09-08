"""Bounded helper output, including large interpreted allocation traces."""
from __future__ import annotations

import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

from .files import fingerprint, write_json
from .model import MAX_FILE_BYTES, MAX_TOTAL_BYTES
from .resources import process_stat


def directory_bytes(directory: Path) -> int:
    total = 0
    for index, path in enumerate(directory.iterdir()):
        if index >= 16 or path.is_symlink() or not path.is_file():
            raise ValueError("helper-artifact-count-or-type")
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError("helper-artifact-byte-bound")
        total += size
    return total


def command(argv: list[str], log: Path, timeout: int, cwd: Path, deadline: int,
            env: dict | None = None, maximum: int = 16 * 1024 * 1024,
            watched: Path | None = None, remaining: int = MAX_TOTAL_BYTES) -> dict:
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
                if watched is not None and directory_bytes(watched) > remaining:
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
