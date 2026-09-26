"""Bounded trusted qualification commands with retained, path-redacted output."""
from __future__ import annotations

import os
from pathlib import Path
from subprocess import CompletedProcess

from tools.owned_test_process import ProcessFailure, run_owned


def run_bounded(command: list[str], cwd: Path, env: dict[str, str],
                timeout_seconds: float, max_output_bytes: int) -> CompletedProcess[bytes]:
    """Keep failed compiler diagnostics without abandoning descendant ownership.

    This is a trusted-source qualification runner, not a hostile-build sandbox.
    The caller supplies an allowlisted environment with no deployment credentials.
    """
    try:
        result = run_owned(command, cwd=cwd, env=env, timeout=timeout_seconds,
                           maximum=max_output_bytes)
    except ProcessFailure as error:
        output = error.result.output if error.result is not None else b""
        raise RuntimeError(error.reason + ": " + redact(output, cwd)) from None
    if result.returncode != 0:
        raise RuntimeError(f"compiler-exit-{result.returncode}: " + redact(result.output, cwd))
    return CompletedProcess(command, result.returncode, result.output, b"")


def redact(output: bytes, cwd: Path) -> str:
    text = output.decode("utf-8", errors="replace")
    for value in sorted({str(cwd), str(Path.home()), os.environ.get("RUNNER_TEMP", "")},
                        key=len, reverse=True):
        if value:
            text = text.replace(value, "<local>")
    return text
