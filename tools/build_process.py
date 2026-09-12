"""Bounded subprocess capture for trusted build recipes, without retained logs.

Python 3.13 is required. The caller supplies a trusted argv/environment, owns the
single active build slot and must not install a competing child reaper. Windows
uses a Job; Linux holds the session leader unreaped while killing its group.
Deliberate session escape, supervisor SIGKILL and uninterruptible OS process
creation are outside this helper's boundary. It is not a hostile-build sandbox.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence

MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 3600
_CLEANUP_SECONDS = 5.0
_CHUNK_BYTES = 16 * 1024


class BuildProcessError(RuntimeError):
    """A static reason; argv, environment and captured output are never included."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _validate(command, cwd, env, timeout_seconds, max_output_bytes) -> list[str]:
    if (isinstance(command, (str, bytes)) or not isinstance(command, Sequence)
            or not 1 <= len(command) <= 256
            or any(not isinstance(item, str) or not item or "\0" in item
                   or len(item) > 32768 for item in command)):
        raise BuildProcessError("command-invalid")
    if not isinstance(cwd, (str, os.PathLike)) or not isinstance(env, Mapping):
        raise BuildProcessError("command-context-invalid")
    if any(not isinstance(key, str) or not isinstance(value, str)
           or not key or "=" in key or "\0" in key or "\0" in value
           for key, value in env.items()):
        raise BuildProcessError("command-environment-invalid")
    if (isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS
            or not math.isfinite(timeout_seconds)):
        raise BuildProcessError("command-timeout-invalid")
    if (isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int)
            or not 0 < max_output_bytes <= MAX_OUTPUT_BYTES):
        raise BuildProcessError("command-output-limit-invalid")
    if sys.version_info < (3, 13):
        raise BuildProcessError("python-version-unsupported")
    if threading.current_thread() is not threading.main_thread():
        raise BuildProcessError("process-main-thread-required")
    return list(command)


def _new_owner():
    if os.name == "nt":
        if __package__:
            from .build_process_windows import OwnedProcess
        else:
            from build_process_windows import OwnedProcess
    elif sys.platform == "linux":
        if __package__:
            from .build_process_linux import OwnedProcess
        else:
            from build_process_linux import OwnedProcess
    else:
        raise BuildProcessError("process-platform-unsupported")
    return OwnedProcess()


def _capture(owner, deadline: float, maximum: int, cancellation) -> tuple[bytes, bytes]:
    process = owner.process
    streams = [process.stdout, process.stderr]
    buffers = [bytearray(), bytearray()]
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
    open_streams = {0, 1}
    used = 0
    finished = False
    while open_streams or not finished:
        cancellation.check()
        if time.monotonic() >= deadline:
            raise BuildProcessError("command-deadline")
        progressed = False
        for index in tuple(open_streams):
            try:
                # Read at most one byte beyond the remaining budget, so overflow
                # is detected without retaining an oversized chunk or buffer.
                chunk = os.read(streams[index].fileno(), min(_CHUNK_BYTES, maximum - used + 1))
            except BlockingIOError:
                continue
            if not chunk:
                open_streams.remove(index)
                progressed = True
                continue
            if len(chunk) > maximum - used:
                raise BuildProcessError("command-output-limit")
            buffers[index].extend(chunk)
            used += len(chunk)
            progressed = True
        if not finished and owner.exited():
            # A successful leader may leave descendants with inherited pipes.
            # Kill and account for those descendants before draining final bytes.
            deadline = time.monotonic() + _CLEANUP_SECONDS
            with cancellation.defer():
                owner.finish(deadline)
            finished = True
        if not progressed:
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))
    return bytes(buffers[0]), bytes(buffers[1])


def run_bounded(command: Sequence[str], cwd: str | Path, env: Mapping[str, str],
                timeout_seconds: float, max_output_bytes: int) -> subprocess.CompletedProcess[bytes]:
    """Run a checked command with one combined output cap and finite cleanup.

Both byte streams are returned only after exit code zero and owned descendant
cleanup. Failures discard capture and raise a static ``BuildProcessError``.
Cancellation follows the same cleanup path. No reader threads or log files are
created. Cleanup has an additional five-second deadline; failure to establish
cleanup is reported, never accepted as a successful build.
"""
    argv = _validate(command, cwd, env, timeout_seconds, max_output_bytes)
    if __package__:
        from .build_process_signals import owned_cancellation
    else:
        from build_process_signals import owned_cancellation
    with owned_cancellation() as cancellation:
        return _run_owned(argv, cwd, env, timeout_seconds, max_output_bytes, cancellation)


def _run_owned(argv, cwd, env, timeout_seconds, max_output_bytes, cancellation):
    owner = None
    failure = None
    captured = None
    deadline = time.monotonic() + timeout_seconds
    try:
        with cancellation.defer():
            owner = _new_owner()
            owner.spawn(argv, cwd, dict(env), deadline)
        captured = _capture(owner, deadline, max_output_bytes, cancellation)
        if owner.process.returncode != 0:
            raise BuildProcessError("command-exit")
    except BaseException as error:
        failure = error
    finally:
        if owner is not None:
            cleanup_failed = False
            try:
                with cancellation.defer():
                    try:
                        owner.finish(time.monotonic() + _CLEANUP_SECONDS)
                    except BaseException:
                        cleanup_failed = True
                    try:
                        owner.close()
                    except BaseException:
                        cleanup_failed = True
            except (KeyboardInterrupt, SystemExit) as error:
                failure = error
            except BaseException:
                cleanup_failed = True
            if cleanup_failed:
                failure = BuildProcessError("process-cleanup")
    if failure is not None:
        # Do not retain bounded capture buffers through the original exception's
        # traceback when the caller keeps the static diagnostic for later.
        captured = None
        failure = failure.with_traceback(None)
        failure.__context__ = None
        if isinstance(failure, (BuildProcessError, KeyboardInterrupt, SystemExit)):
            raise failure from None
        raise BuildProcessError("command-failed") from None
    return subprocess.CompletedProcess(argv, 0, *captured)
