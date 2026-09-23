"""One request, bounded pipes, private stdin and the maintained process owner."""
from __future__ import annotations

import os
from pathlib import Path
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
        stdin: bytes = b"", env: dict | None = None) -> subprocess.CompletedProcess:
    require(len(stdin) <= MAX_SNAPSHOT * 2, "request-byte-limit")
    selected = environment() if env is None else env
    argv = build_process._validate(command, cwd, selected, timeout, maximum)
    owner, failure, result = None, None, None
    with tempfile.TemporaryFile() as source, owned_cancellation() as cancellation:
        source.write(stdin)
        source.seek(0)
        try:
            with cancellation.defer():
                owner = build_process._new_owner()
                owner.spawn(argv, cwd, selected, time.monotonic() + timeout, stdin=source)
            output, errors = build_process._capture(owner, time.monotonic() + timeout, maximum, cancellation)
            result = subprocess.CompletedProcess(argv, owner.process.returncode, output, errors)
        except BaseException as error:
            failure = error
        finally:
            if owner is not None:
                with cancellation.defer():
                    try:
                        owner.finish(time.monotonic() + 5)
                    except BaseException:
                        failure = DevError("owned-process-cleanup-unconfirmed", uncertain=True)
                    finally:
                        owner.close()
        if failure is not None:
            if isinstance(failure, (KeyboardInterrupt, SystemExit, DevError)):
                raise failure from None
            raise DevError("owned-process-failed", uncertain=True) from None
        return result
