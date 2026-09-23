"""One request, bounded pipes, private stdin and the maintained process owner."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from tools import build_process
from tools.build_process_signals import owned_cancellation
from .common import DevError, MAX_LOG, MAX_SNAPSHOT, require


def environment(home: Path | None = None) -> dict[str, str]:
    # No token, proxy, SSH agent, cloud credential or language-hook inheritance.
    result = {"PATH": os.defpath, "LANG": "C.UTF-8", "NO_COLOR": "1", "TERM": "dumb"}
    if os.name == "nt":
        for key in ("SystemRoot", "WINDIR", "TEMP", "TMP"):
            if key in os.environ:
                result[key] = os.environ[key]
    if home is not None:
        result["HOME"] = str(home)
        result["USERPROFILE"] = str(home)
    return result


def run(command: list[str], cwd: Path, *, timeout: float = 30, maximum: int = MAX_LOG,
        stdin: bytes = b"", env: dict | None = None, check=None, graceful: float = 0) -> subprocess.CompletedProcess:
    require(len(stdin) <= MAX_SNAPSHOT * 2, "request-byte-limit")
    require(0 <= graceful <= 15, "process-grace-period-limit")
    selected = environment() if env is None else env
    argv = build_process._validate(command, cwd, selected, timeout, maximum)
    owner, failure, result = None, None, None
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryFile() as source, owned_cancellation() as cancellation:
        source.write(stdin)
        source.seek(0)
        try:
            with cancellation.defer():
                owner = build_process._new_owner()
                owner.spawn(argv, cwd, selected, deadline, stdin=source)
            class Observation:
                def check(self):
                    cancellation.check()
                    if check is not None:
                        check()
                def defer(self):
                    return cancellation.defer()
            output, errors = build_process._capture(owner, deadline, maximum, Observation())
            result = subprocess.CompletedProcess(argv, owner.process.returncode, output, errors)
        except BaseException as error:
            failure = error
        finally:
            if owner is not None:
                with cancellation.defer():
                    try:
                        if failure is not None and graceful and os.name == "posix" and owner.process is not None:
                            # Maintained language recipes own nested process groups.
                            # Give their signal handlers time to reap those children
                            # before the outer owner performs its final group sweep.
                            if not owner.exited():
                                try:
                                    os.killpg(owner.process.pid, signal.SIGTERM)
                                except ProcessLookupError:
                                    pass  # The unreaped leader reservation is still held.
                            grace_deadline = time.monotonic() + graceful
                            while not owner.exited() and time.monotonic() < grace_deadline:
                                time.sleep(0.01)
                            if not owner.exited():
                                failure = DevError("owned-process-cleanup-unconfirmed", uncertain=True)
                        owner.finish(time.monotonic() + 5)
                    except BaseException:
                        failure = DevError("owned-process-cleanup-unconfirmed", uncertain=True)
                    finally:
                        owner.close()
        if failure is not None:
            if isinstance(failure, (KeyboardInterrupt, SystemExit, DevError)):
                raise failure from None
            if isinstance(failure, build_process.BuildProcessError) and failure.reason in {"command-deadline", "command-output-limit"}:
                # The finally block has confirmed reaping; remote mutation outcome
                # still belongs to Backend/Journal and must not be inferred here.
                raise DevError("owned-process-" + failure.reason) from None
            raise DevError("owned-process-failed", uncertain=True) from None
        return result
