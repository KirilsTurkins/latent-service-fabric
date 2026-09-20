"""Bounded local selection receipts, not a native prepared-artifact validator.

No command, environment, log text or executable path is accepted from a receipt.
The shared artifact/diagnostic owners remain #428/#434.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys

from tools import ci_rust_artifacts as artifacts

MAX_JSON = 64 * 1024
MAX_CASES = 256
SCHEMA = "latent.local-test-selection.v1"
STATES = {"passed", "failed", "cancelled", "not-run"}


class LocalTestError(Exception):
    def __init__(self, reason: str, code: int = 3, state: str = "not-run") -> None:
        super().__init__(reason)
        self.code = code
        self.state = state


def digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(data.encode()).hexdigest()


def environment() -> dict[str, str]:
    """The source-only tooling suite does not need provider/Actions credentials."""
    names = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", LC_ALL="C",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_TERMINAL_PROMPT="0")
    return env


def source_identity(repo: Path) -> dict:
    def git(arguments: list[str], limit: int) -> bytes:
        status, output = artifacts.run_owned(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "gc.auto=0",
             *arguments], cwd=repo, env=environment(), timeout=15, maximum=limit)
        if status:
            raise LocalTestError("local Git checkout unavailable; no source identity was inferred")
        return output

    commit = git(["rev-parse", "--verify", "HEAD"], 256).strip().decode("ascii")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise LocalTestError("invalid local source identity")
    # Dirty worktrees are always identified as non-exact, even when HEAD matches.
    # Do not copy private patches, paths or untracked file contents into a report.
    status = git(["status", "--porcelain=v1", "-z", "--untracked-files=normal",
                  "--ignore-submodules=none"], MAX_JSON)
    return {"commit": commit, "dirty": bool(status)}


def host_identity() -> dict:
    return {"platform": sys.platform, "machine": platform.machine(),
            "python": platform.python_version()}


def bounded_read(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON:
            raise LocalTestError("report must be a regular file of at most 64 KiB")
        data = stream.read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
        raise LocalTestError("report exceeds 64 KiB")
    return data


def decode(data: bytes) -> object:
    if len(data) > MAX_JSON:
        raise LocalTestError("JSON exceeds 64 KiB")
    try:
        return json.loads(data, object_pairs_hook=artifacts.unique_object)
    except (ValueError, artifacts.ArtifactError, RecursionError) as error:
        raise LocalTestError("invalid or duplicate-key JSON") from error


def keys(value: object, expected: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise LocalTestError("unknown or missing report fields; commands and environments are not accepted")
    return value


def valid_case(value: object) -> bool:
    return (isinstance(value, str) and len(value) <= 512
            and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9.:]*", value) is not None)


def validate_report(value: object) -> dict:
    report = keys(value, {"schema", "suite", "case", "source", "host", "recipe", "fixtures",
                          "options", "state", "exit_code", "required_cases", "observed_cases",
                          "failed_cases"})
    if report["schema"] != SCHEMA:
        raise LocalTestError("unsupported receipt schema; #426/#434 adapters are not integrated")
    if not isinstance(report["suite"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", report["suite"]):
        raise LocalTestError("invalid suite ID")
    if report["case"] is not None and not valid_case(report["case"]):
        raise LocalTestError("invalid exact case ID")
    source = keys(report["source"], {"commit", "dirty"})
    if (not isinstance(source["commit"], str)
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source["commit"])
            or type(source["dirty"]) is not bool):
        raise LocalTestError("invalid source identity")
    host = keys(report["host"], {"platform", "machine", "python"})
    if any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", v) for v in host.values()):
        raise LocalTestError("invalid host identity")
    if not isinstance(report["recipe"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", report["recipe"]):
        raise LocalTestError("invalid recipe identity")
    if report["fixtures"] != "source-only" or report["options"] != {}:
        raise LocalTestError("native fixtures and captured options need the shared #428/#434 contract")
    if not isinstance(report["state"], str) or report["state"] not in STATES:
        raise LocalTestError("invalid execution state")
    for name, maximum in (("exit_code", 255), ("required_cases", MAX_CASES), ("observed_cases", MAX_CASES)):
        if type(report[name]) is not int or not 0 <= report[name] <= maximum:
            raise LocalTestError("invalid exit or case count")
    if report["required_cases"] == 0 or report["observed_cases"] > report["required_cases"]:
        raise LocalTestError("empty or inconsistent case counts")
    failed = report["failed_cases"]
    if (not isinstance(failed, list) or len(failed) > report["observed_cases"]
            or any(not valid_case(case) for case in failed) or len(failed) != len(set(failed))):
        raise LocalTestError("invalid failed-case inventory")
    if report["state"] == "passed":
        if report["exit_code"] or failed or report["observed_cases"] != report["required_cases"]:
            raise LocalTestError("inconsistent passing receipt")
    elif report["exit_code"] == 0:
        raise LocalTestError("non-passing receipt cannot have exit zero")
    return report


def write_report(path: Path, report: dict) -> None:
    validate_report(report)
    data = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
    if len(data) > MAX_JSON:
        raise LocalTestError("report exceeds 64 KiB")
    # Explicit, exclusive creation. Never replace another run's report or follow
    # an existing symlink. The caller owns creation/cleanup of the parent folder.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o600), "wb") as stream:
        stream.write(data)


def reproduce_selection(report: dict, plan: dict, source: dict, host: dict,
                        *, allow_changed: bool = False) -> str:
    validate_report(report)
    if report["state"] == "passed":
        raise LocalTestError("receipt records a passed run, not a recorded failure")
    if report["suite"] != plan["suite"] or report["recipe"] != plan["recipe_identity"]:
        raise LocalTestError("suite/recipe changed; inspect the current plan and prepare a new selection")
    if any(case not in plan["cases"] for case in report["failed_cases"]):
        raise LocalTestError("failed case was not in the recorded selection")
    if report["required_cases"] != len(plan["cases"]):
        raise LocalTestError("required case count changed")
    if report["fixtures"] != plan["fixtures"]:
        raise LocalTestError("fixture identity changed; prepare the selected suite again")
    changed = (source != report["source"] or source["dirty"] or report["source"]["dirty"]
               or host != report["host"])
    if changed and not allow_changed:
        raise LocalTestError("checkout or host changed/dirty: not exact; use --allow-changed-checkout for a labelled rerun")
    return "changed-input-rerun" if changed else "same-input-selection"
