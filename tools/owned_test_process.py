#!/usr/bin/env python3
"""Bounded execution shared by artifact, provider and renderer test runners.

Linux is the qualified descendant-ownership platform. Unsupported hosts fail
closed rather than quietly falling back to killing only the immediate child.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time
import uuid

PROTOCOL = "latent.owned-process.v1"
MAX_OUTPUT = 16 * 1024 * 1024


@dataclass(frozen=True)
class Result:
    returncode: int | None
    output: bytes
    pid: int | None = None
    elapsed_ms: float = 0
    startup_ms: float = 0
    teardown_ms: float = 0
    reaped: int = 0
    cleaned: bool = False


class ProcessFailure(RuntimeError):
    def __init__(self, category: str, reason: str, result: Result | None = None):
        super().__init__(reason)
        self.category, self.reason, self.result = category, reason, result


def run_owned(command: list[str], *, cwd: Path, env: dict[str, str] | None = None,
              timeout: float = 30, maximum: int = 65536,
              cancel: threading.Event | None = None) -> Result:
    """Execute once, bounding combined output and startup/execution/reap together.

    There are no retries and no shell. A dedicated subreaper retires this
    command's descendants, including children that change session. Raw output
    stays private; callers must redact it before publishing diagnostics.
    """
    if sys.platform != "linux":
        raise ProcessFailure("unavailable-environment", "linux-process-owner-required")
    if (not math.isfinite(timeout) or not 0 < timeout <= 86400
            or type(maximum) is not int or not 0 <= maximum <= MAX_OUTPUT
            or not command or any(not isinstance(arg, str) or "\0" in arg for arg in command)):
        raise ValueError("invalid owned command limits or arguments")
    started = time.monotonic()
    deadline = started + timeout
    # Both the orderly descendant retirement and emergency worker reap are
    # INSIDE the caller's total budget; neither receives a fresh timeout.
    retirement_deadline = deadline - min(0.5, timeout / 10)
    work_deadline = retirement_deadline - min(2.0, timeout / 4)
    nonce = uuid.uuid4().hex
    data = (json.dumps(dict(command=command, cwd=str(cwd), env=env if env is not None else dict(os.environ),
                            deadline=retirement_deadline, workDeadline=work_deadline)) + "\n").encode()
    if len(data) > 1024 * 1024:
        raise ProcessFailure("invalid-fixture", "launch-specification-limit")
    read_fd, write_fd = os.pipe()
    process = None
    capture, statuses = bytearray(), bytearray()
    child_pid, startup_ms, final, problem, original_exception = None, 0.0, None, None, None
    sent, stopped = 0, False
    interrupted = threading.Event()
    selector = selectors.DefaultSelector()
    old_signals = {}

    def stop() -> None:
        nonlocal stopped
        if process is not None and not stopped:
            stopped = True
            try:
                process.terminate()  # the worker still owns descendant retirement
            except ProcessLookupError:
                pass

    def pump() -> None:
        nonlocal sent, child_pid, startup_ms, final, problem
        for key, _ in selector.select(min(0.025, max(0, retirement_deadline - time.monotonic()))):
            if key.data == "input":
                try:
                    sent += os.write(key.fd, data[sent:sent + 65536])
                except BrokenPipeError:
                    sent = len(data)
                if sent == len(data):
                    selector.unregister(key.fileobj)
                    process.stdin.close()
                continue
            chunk = os.read(key.fd, 65536)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            if key.data == "output":
                room = maximum - len(capture)
                capture.extend(chunk[:room])
                if len(chunk) > room and problem is None:
                    problem = ("output-overflow", "command-output-limit")
                    stop()
                continue
            statuses.extend(chunk)
            if len(statuses) > 8192:
                raise ProcessFailure("invalid-fixture", "supervisor-status-limit")
            while b"\n" in statuses:
                line, _, remainder = statuses.partition(b"\n")
                statuses[:] = remainder
                record = json.loads(line)
                if record.get("protocol") != PROTOCOL or record.get("nonce") != nonce:
                    raise ProcessFailure("invalid-fixture", "false-supervisor-identity")
                if record.get("event") == "started" and child_pid is None and final is None:
                    child_pid, startup_ms = record["pid"], record["startupMs"]
                elif record.get("event") == "finished" and final is None:
                    final = record
                else:
                    raise ProcessFailure("invalid-fixture", "false-supervisor-readiness")

    try:
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                old_signals[sig] = signal.signal(sig, lambda _sig, _frame: interrupted.set())
        worker = Path(__file__).with_name("owned_process_worker.py")
        process = subprocess.Popen([sys.executable, "-I", "-u", str(worker), str(write_fd), nonce],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   pass_fds=(write_fd,), start_new_session=True)
        os.close(write_fd)
        write_fd = -1
        assert process.stdin is not None and process.stdout is not None
        for stream, events, kind in ((process.stdin, selectors.EVENT_WRITE, "input"),
                                     (process.stdout, selectors.EVENT_READ, "output"),
                                     (read_fd, selectors.EVENT_READ, "status")):
            os.set_blocking(stream if isinstance(stream, int) else stream.fileno(), False)
            selector.register(stream, events, kind)
        while selector.get_map():
            now = time.monotonic()
            if (interrupted.is_set() or cancel is not None and cancel.is_set()) and problem is None:
                problem = ("cancelled", "cancelled-waiter")
                stop()
            if now >= work_deadline and problem is None and final is None:
                problem = ("infrastructure-timeout", "command-timeout")
                stop()
            if now >= retirement_deadline:
                problem = problem or ("infrastructure-timeout", "cleanup-timeout")
                break
            try:
                pump()
            except BaseException as error:
                # An outer watchdog/interrupt must not abandon the owner. Keep
                # draining the separate acknowledgement pipe during retirement.
                stop()
                if original_exception is not None:
                    break
                original_exception = error
        # Do not poll/wait before the last kill decision: the unreaped session
        # leader pins its process-group ID against unrelated PID reuse.
    except BaseException as error:
        original_exception = error
        stop()
    finally:
        selector.close()
        if write_fd >= 0:
            os.close(write_fd)
        os.close(read_fd)
        if process is not None:
            try:
                # Missing/unconfirmed retirement cannot become a passing run.
                # Kill the still-owned group before reaping its leader.
                if not final or final.get("cleaned") is not True:
                    stop()
                    if final is not None or time.monotonic() >= retirement_deadline:
                        os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=max(0, retirement_deadline - time.monotonic()))
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    pass  # diagnostic remains unconfirmed, never success
                problem = problem or ("infrastructure-timeout", "cleanup-timeout")
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        for sig, handler in old_signals.items():
            signal.signal(sig, handler)
    result = Result(final.get("returncode") if final else None, bytes(capture), child_pid,
                    (time.monotonic() - started) * 1000, startup_ms,
                    final.get("teardownMs", 0) if final else 0,
                    final.get("reaped", 0) if final else 0,
                    bool(final and final.get("cleaned") is True and process and process.returncode == 0))
    if original_exception is not None:
        if isinstance(original_exception, ProcessFailure):
            original_exception.result = result
        raise original_exception
    if problem:
        raise ProcessFailure(*problem, result)
    if final is None or statuses or not result.cleaned:
        raise ProcessFailure("infrastructure-timeout", "missing-cleanup-acknowledgement", result)
    if reason := final.get("reason"):
        category = ("cancelled" if reason == "cancelled" else
                    "infrastructure-timeout" if "timeout" in reason else
                    "unavailable-environment" if child_pid is None else "assertion-failure")
        raise ProcessFailure(category, reason, result)
    return result


async def run_owned_async(command: list[str], **kwargs: object) -> Result:
    """A cancelled async waiter still joins the owner before propagating cancel."""
    cancel = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(run_owned, command, cancel=cancel, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel.set()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except ProcessFailure:
                break
        if task.done() and not task.cancelled():
            task.exception()
        raise
