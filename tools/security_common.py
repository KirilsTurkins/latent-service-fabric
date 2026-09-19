"""Bounded, nonexecuting input and redacted process helpers for security checks."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / ".github/security"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_PATHS = 20000


class SecurityError(Exception):
    """A fixed diagnostic code, never a scanner's raw output or source text."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SecurityError(code)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate-json-field")
        result[key] = value
    return result


def decode_json(payload: bytes) -> object:
    require(len(payload) <= MAX_OUTPUT_BYTES, "json-size-limit")
    return json.loads(payload, object_pairs_hook=unique_fields)


def relative_path(value: str) -> str:
    require(isinstance(value, str) and 0 < len(value) <= 1024, "invalid-path")
    require(not any(ord(char) < 32 for char in value), "invalid-path")
    require("\\" not in value and ":" not in value, "invalid-path")
    require(not PurePosixPath(value).is_absolute(), "invalid-path")
    require(all(part not in {"", ".", ".."} for part in value.split("/")), "invalid-path")
    return value


def read_file(root: Path, relative: str, limit: int = MAX_FILE_BYTES) -> bytes:
    current = root.resolve(strict=True)
    for part in relative_path(relative).split("/"):
        current = current / part
        metadata = current.lstat()
        require(not stat.S_ISLNK(metadata.st_mode), "linked-input")
        require(not getattr(metadata, "st_file_attributes", 0) & 0x400, "reparse-input")
    require(stat.S_ISREG(metadata.st_mode), "nonregular-input")
    require(metadata.st_size <= limit, "input-size-limit")
    with current.open("rb") as source:
        payload = source.read(limit + 1)
    require(len(payload) <= limit, "input-size-limit")
    return payload


def child_environment(workspace: Path) -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    environment = {name: value for name, value in os.environ.items() if name.upper() in allowed}
    environment.update({
        "HOME": str(workspace), "USERPROFILE": str(workspace),
        "TEMP": str(workspace), "TMP": str(workspace), "TMPDIR": str(workspace),
        "CARGO_HOME": str(workspace / "cargo-home"), "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1", "GIT_PAGER": "cat",
        "NO_COLOR": "1", "ZIZMOR_OFFLINE": "1",
    })
    return environment


def run(command: list[str], cwd: Path, timeout: int = 120,
        accepted: tuple[int, ...] = (0,), limit: int = MAX_OUTPUT_BYTES) -> tuple[int, bytes]:
    process = subprocess.Popen(
        command, cwd=cwd, env=child_environment(cwd), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=os.name == "posix",
    )
    expired = threading.Event()

    def stop() -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass

    def expire() -> None:
        expired.set()
        stop()

    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    timer.start()
    try:
        assert process.stdout is not None
        output = process.stdout.read(limit + 1)
        require(len(output) <= limit, "process-output-limit")
        process.wait(timeout=10)
        require(not expired.is_set(), "process-timeout")
        require(process.returncode in accepted, "scanner-or-network-failed")
        return process.returncode, output
    finally:
        timer.cancel()
        stop()
        process.wait(timeout=10)
        if process.stdout:
            process.stdout.close()


def tracked_paths(repo: Path) -> list[str]:
    _, output = run(["git", "-C", str(repo), "ls-files", "-z", "--cached",
                     "--others", "--exclude-standard"], ROOT, timeout=30)
    paths = sorted(set(output.decode("utf-8").rstrip("\0").split("\0")))
    require(0 < len(paths) <= MAX_PATHS, "path-count-limit")
    return [relative_path(path) for path in paths]


def changed_paths(repo: Path, base: str, revision: str) -> list[str]:
    require(all(re.fullmatch(r"[0-9a-f]{40}", value) is not None for value in (base, revision)), "invalid-change-revision")
    run(["git", "-C", str(repo), "fetch", "--no-tags", "--depth=1", "origin", base], ROOT, timeout=90)
    _, output = run(["git", "-C", str(repo), "diff", "--name-only", "--no-renames", "-z", base, revision, "--"],
                    ROOT, timeout=30)
    paths = output.decode().rstrip("\0").split("\0") if output else []
    require(len(paths) <= MAX_PATHS, "change-count-limit")
    return [relative_path(path) for path in paths]
