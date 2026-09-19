"""Bounded documents and subprocess ownership for native installation."""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import time


class InstallError(Exception):
    """A fixed, non-secret installation diagnostic."""


def require(condition: object, diagnostic: str) -> None:
    if not condition:
        raise InstallError(diagnostic)


def unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate-document-member")
        result[key] = value
    return result


def document(data: bytes, maximum: int = 1_048_576) -> dict:
    require(len(data) <= maximum, "document-byte-limit")
    try:
        result = json.loads(data, object_pairs_hook=unique_object)
    except (ValueError, RecursionError) as error:
        raise InstallError("invalid-document") from error
    require(isinstance(result, dict), "document-object-required")
    return result


def encode(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def execute(arguments: list[str], *, timeout: float = 30, maximum: int = 262_144,
            identity: tuple[int, int] | None = None, pass_fds: tuple = (),
            environment: dict | None = None, cwd: str = "/", stdout_only: bool = False) -> tuple[int, bytes]:
    require(os.name == "posix", "linux-required")
    options = {}
    if identity is not None and os.geteuid() == 0:
        options = {"user": identity[0], "group": identity[1], "extra_groups": [], "umask": 0o077}
    process = subprocess.Popen(
        arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if stdout_only else subprocess.STDOUT, close_fds=True, pass_fds=pass_fds,
        start_new_session=True, cwd=cwd,
        env=environment or {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        **options,
    )
    output = bytearray()
    diagnostic = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if stdout_only:
                selector.register(process.stderr, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0, "command-timeout")
                for key, _events in selector.select(min(remaining, 0.1)):
                    data = os.read(key.fd, min(65536, maximum + 1 - len(output) - len(diagnostic)))
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        (output if key.fileobj is process.stdout else diagnostic).extend(data)
                        require(len(output) + len(diagnostic) <= maximum, "command-output-limit")
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        return process.returncode, bytes(output) + (bytes(diagnostic) if process.returncode != 0 else b"")
    except subprocess.TimeoutExpired as error:
        raise InstallError("command-timeout") from error
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
