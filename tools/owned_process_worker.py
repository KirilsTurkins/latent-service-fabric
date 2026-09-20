#!/usr/bin/env python3
"""Private Linux subreaper for one owned command; not a persistent service.

Only owned_test_process starts this helper. Control records use an inherited
anonymous pipe, never a readiness file or the command's stdout. Descendants are
adopted here, so waitpid(-1) cannot reap another runner's children.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

PROTOCOL = "latent.owned-process.v1"
MAX_SPEC = 1024 * 1024
MAX_CHILDREN = 4096


def children() -> list[int]:
    # This process is single-threaded. Do not enumerate /proc or inspect peers.
    with Path(f"/proc/self/task/{os.getpid()}/children").open("rb") as source:
        data = source.read(64 * 1024 + 1)
    if len(data) > 64 * 1024:
        raise RuntimeError("owned-child-list-limit")
    found = [int(value) for value in data.split()]
    if len(found) > MAX_CHILDREN:
        raise RuntimeError("owned-child-count-limit")
    return found


def retire(deadline: float, target_pid: int | None) -> tuple[int, bool, int | None]:
    """Reap/kill only our children, including newly adopted escaped descendants."""
    reaped = 0
    status = None
    while True:
        while True:
            try:
                pid, observed = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return reaped, True, status
            if not pid:
                break
            if pid == target_pid:
                status = os.waitstatus_to_exitcode(observed)
            reaped += 1
        # Listed PIDs remain our unreaped children until the next wait above.
        # They cannot be reused between this read and signal. No peer scanning.
        for pid in children():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if time.monotonic() >= deadline:
            return reaped, False, status
        time.sleep(0.005)


def main() -> int:
    status_fd, nonce = int(sys.argv[1]), sys.argv[2]
    os.set_inheritable(status_fd, False)
    cancelled = False

    def interrupt(_signum: int, _frame: object) -> None:
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)

    def emit(event: str, **values: object) -> None:
        record = dict(protocol=PROTOCOL, nonce=nonce, event=event, **values)
        encoded = (json.dumps(record, separators=(",", ":")) + "\n").encode()
        if len(encoded) > 4096:
            raise RuntimeError("status-record-limit")
        os.write(status_fd, encoded)

    started = time.monotonic()
    deadline = started + 5
    code = None
    reason = None
    target = None
    owner_ready = False
    reaped = 0
    cleaned = False
    try:
        # Reading the launch specification itself has a finite watchdog.
        spec = bytearray()
        while not spec.endswith(b"\n"):
            if cancelled or time.monotonic() >= deadline:
                raise RuntimeError("launch-specification-timeout")
            if not select.select([sys.stdin.fileno()], [], [], 0.05)[0]:
                continue
            chunk = os.read(sys.stdin.fileno(), 65536)
            if not chunk:
                raise RuntimeError("launch-specification-truncated")
            spec.extend(chunk)
            if len(spec) > MAX_SPEC:
                raise RuntimeError("launch-specification-limit")
        value = json.loads(spec)
        deadline = float(value["deadline"])
        work_deadline = float(value["workDeadline"])
        if not started < work_deadline < deadline <= started + 86400:
            raise RuntimeError("invalid-command-deadline")
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER, process-local
            raise RuntimeError("subreaper-unavailable")
        children()  # Prove owned-process accounting access before spawning work.
        owner_ready = True
        if cancelled:
            raise RuntimeError("cancelled")
        target = subprocess.Popen(value["command"], cwd=value["cwd"], env=value["env"],
                                  stdin=subprocess.DEVNULL, close_fds=True)
        emit("started", pid=target.pid, startupMs=(time.monotonic() - started) * 1000)
        while True:
            code = target.poll()
            if code is not None:
                break
            if cancelled:
                reason = "cancelled"
                break
            if time.monotonic() >= work_deadline:
                reason = "timeout"
                break
            time.sleep(0.005)
    except FileNotFoundError:
        reason = "executable-unavailable" if owner_ready else "owned-accounting-unavailable"
    except PermissionError:
        reason = "accounting-or-execution-denied"
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        reason = "supervisor-unavailable" if target is None else "supervisor-failed"
    finally:
        teardown = time.monotonic()
        try:
            reaped, cleaned, retired_status = retire(deadline, target.pid if target else None)
            if code is None:
                code = retired_status
        except (OSError, ValueError, RuntimeError):
            cleaned = False
        if target is not None and code is not None:
            target.returncode = code
        if not cleaned:
            reason = "cleanup-timeout"
        try:
            emit("finished", returncode=code, reason=reason, reaped=reaped,
                 cleaned=cleaned, teardownMs=(time.monotonic() - teardown) * 1000,
                 elapsedMs=(time.monotonic() - started) * 1000)
        except (OSError, RuntimeError):
            return 1
        finally:
            os.close(status_fd)
    return 0 if cleaned else 1


if __name__ == "__main__":
    raise SystemExit(main())
