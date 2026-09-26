#!/usr/bin/env python3
"""Prerequisites, one total watchdog and redacted diagnostics for selected runs.

Suite identities/recipes live in tools/ci/suites.json (#427). Prepared artifacts
remain owned by ci_rust_artifacts (#428); this module is not a build/version tool.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import sys
import tempfile
import threading
import time
from typing import Callable

try:
    from .owned_test_process import ProcessFailure, Result, run_owned
except ImportError:
    from owned_test_process import ProcessFailure, Result, run_owned

ROOT = Path(__file__).resolve().parents[1]
FAILURE_SCHEMA = "latent.test-run.v1"
MAX_TAIL = 4096


def require(condition: object, category: str, reason: str) -> None:
    if not condition:
        raise ProcessFailure(category, reason)


def contract(name: str, inventory: Path | None = None) -> tuple[dict, dict]:
    try:
        try:
            from .ci_suite_inventory import load
        except ImportError:
            from ci_suite_inventory import load
        data = load() if inventory is None else load(inventory)
        selected = data["processContracts"][name]
        rows = {row["id"]: row for row in data["suites"]}
        require(selected["suiteIds"] and all(key in rows for key in selected["suiteIds"]),
                "invalid-fixture", "unregistered-process-suite")
        require(selected["platforms"] and all(set(selected["platforms"]) <= set(row["platforms"])
                for row in (rows[key] for key in selected["suiteIds"])),
                "invalid-fixture", "process-platform-contract")
        require(type(selected["timeoutSeconds"]) is int and 0 < selected["timeoutSeconds"] <= 7200,
                "invalid-fixture", "process-timeout-contract")
        required = selected["prerequisites"]
        require(set(required) == {"tools", "services", "filesystem", "accounting", "artifacts", "versionScopes"},
                "invalid-fixture", "process-prerequisite-contract")
        require(all(isinstance(required[key], list) for key in required),
                "invalid-fixture", "process-prerequisite-list")
        require(all(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,96}", value)
                    for key in required if key != "services" for value in required[key]),
                "invalid-fixture", "invalid-prerequisite-name")
        require(all(isinstance(service, dict) and set(service) == {"type", "image"}
                    and service["type"] == "docker-image" and isinstance(service["image"], str)
                    and re.fullmatch(r"[a-zA-Z0-9./_-]+@sha256:[0-9a-f]{64}", service["image"])
                    for service in required["services"]), "invalid-fixture", "invalid-service-identity")
        return selected, rows
    except ProcessFailure:
        raise
    except (ImportError, OSError, KeyError, TypeError, ValueError, AttributeError):
        raise ProcessFailure("invalid-fixture", "suite-inventory-unavailable-or-invalid") from None


@dataclass(frozen=True)
class Ready:
    owner: str
    run: str
    endpoint: str
    protocol: str


def redact(text: str, private_paths: tuple[str, ...] = (), secrets: tuple[str, ...] = ()) -> str:
    # Redact before taking the tail; truncation must not expose a credential's
    # suffix by discarding its key/prefix. Nothing captures entire environments.
    for value in sorted((*secrets, *private_paths), key=len, reverse=True):
        if value:
            text = text.replace(value, "<redacted>")
    text = re.sub(r"-----BEGIN [^-]+-----.*?(?:-----END [^-]+-----|$)", "<private-key>", text, flags=re.S)
    text = re.sub(r"(?i)(authorization|proxy-authorization|cookie|set-cookie)\s*[:=][^\r\n]*", r"\1=<redacted>", text)
    text = re.sub(r'''(?ix)(["']?(?:password|passwd|token|secret|api[_-]?key|credential)["']?\s*[:=]\s*)
                     (?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}]+)''', r"\1<redacted>", text)
    text = re.sub(r"(?i)\b(?:https?|nats|s3)://[^\s\"'<>]+", "<endpoint>", text)
    text = re.sub(r"(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'<>]+|(?<![\w:])/(?:[^\s\"'<>]+)", "<path>", text)
    # Strip terminal escapes and control bytes from the public diagnostic.
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return "".join(c for c in text if c in "\n\t" or ord(c) >= 32)


def digest(path: Path, maximum: int) -> str:
    with path.open("rb") as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum,
                "invalid-fixture", "artifact-file-limit")
        value = hashlib.sha256()
        consumed = 0
        while chunk := source.read(1024 * 1024):
            consumed += len(chunk)
            require(consumed <= maximum, "invalid-fixture", "artifact-grew-during-check")
            value.update(chunk)
        after = os.fstat(source.fileno())
        require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "invalid-fixture", "artifact-changed-during-check")
    return "sha256:" + value.hexdigest()


class TestRun:
    """One private fixture root and a shared startup/execution/teardown deadline."""
    __test__ = False

    def __init__(self, suite: str, policy: dict, *, repo: Path = ROOT,
                 reproduction: dict | None = None, synthetic: bool = False,
                 secrets: tuple[str, ...] = (), diagnostic_root: Path | None = None):
        require(re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,95}", suite),
                "invalid-fixture", "invalid-diagnostic-suite")
        self.suite, self.policy, self.repo = suite, policy, repo.resolve()
        self.started = time.monotonic()
        timeout = policy["timeoutSeconds"]
        require(isinstance(timeout, (int, float)) and math.isfinite(timeout) and timeout > 0,
                "invalid-fixture", "invalid-total-watchdog")
        self.deadline = self.started + timeout
        self.work_deadline = self.deadline - min(15.0, timeout / 5)
        self.synthetic = synthetic
        # Values are used for redaction only, never retained as diagnostic data.
        self.secrets = (*secrets, *(value for key, value in os.environ.items()
                        if re.search(r"(?i)(secret|password|passwd|token|credential|api.?key)", key)
                        and len(value) >= 4))
        self.reproduction = reproduction or {"suite": suite}
        # Records are selections, not command scripts or captured environments.
        allowed = {"suite", "cases", "recipe", "mode", "web", "observed", "fixtureOnly", "preflight", "fault"}
        require(set(self.reproduction) <= allowed, "invalid-fixture", "unsafe-reproduction-fields")
        for key, value in self.reproduction.items():
            values = value if isinstance(value, list) else [value]
            require(len(values) <= 128 and all(type(v) is bool or isinstance(v, str)
                    and re.fullmatch(r"[a-zA-Z0-9_:.-]{1,256}", v) for v in values),
                    "invalid-fixture", "unsafe-reproduction-selection")
        self.run_id = os.urandom(16).hex()
        self.stage = "prerequisites"
        self.stage_started = self.started
        self.timings: list[dict] = []
        self.fixture_ids: dict[str, str] = {}
        self.source: dict = {"revision": None, "dirty": None, "observed": False}
        self.log_tail = ""
        self.last: Result | None = None
        self.cleanup: list[Callable[[], None]] = []
        self.cleanup_failures: list[str] = []
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-owned-")
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.diagnostic_root = diagnostic_root or (self.repo / "target/test-diagnostics")
        self.record_path: Path | None = None
        self.cancel = threading.Event()
        self.old_signals: dict = {}
        self.alarm = False
        self.record: dict | None = None

    def remaining(self, limit: float | None = None) -> float:
        end = self.deadline if self.stage == "teardown" else self.work_deadline
        end = min(end, getattr(self, "operation_deadline", end))
        left = end - time.monotonic()
        require(left > 0, "infrastructure-timeout", "total-run-watchdog")
        return left if limit is None else min(left, limit)

    def mark(self, stage: str) -> None:
        now = time.monotonic()
        self.timings.append({"stage": self.stage, "elapsedMs": round((now - self.stage_started) * 1000, 3)})
        self.stage, self.stage_started = stage, now

    def __enter__(self) -> "TestRun":
        if threading.current_thread() is not threading.main_thread():
            self.temporary.cleanup()
            raise ProcessFailure("unavailable-environment", "runner-requires-main-thread-watchdog")
        if hasattr(signal, "setitimer") and signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
            self.temporary.cleanup()
            raise ProcessFailure("unavailable-environment", "nested-process-watchdog")
        if threading.current_thread() is threading.main_thread():
            def interrupted(_sig: int, _frame: object) -> None:
                self.cancel.set()
                raise ProcessFailure("cancelled", "runner-interrupted")
            for sig in (signal.SIGTERM, signal.SIGINT):
                self.old_signals[sig] = signal.signal(sig, interrupted)
            if hasattr(signal, "setitimer"):
                def expired(_sig: int, _frame: object) -> None:
                    self.cancel.set()
                    raise ProcessFailure("infrastructure-timeout", "total-run-watchdog")
                self.old_signals[signal.SIGALRM] = signal.signal(signal.SIGALRM, expired)
                signal.setitimer(signal.ITIMER_REAL, self.remaining())
                self.alarm = True
        return self

    def command(self, args: list[str], *, timeout: float = 30, maximum: int = 65536,
                env: dict[str, str] | None = None, check: bool = True,
                cwd: Path | None = None) -> Result:
        try:
            result = run_owned(args, cwd=cwd or self.repo, env=env,
                               timeout=self.remaining(timeout), maximum=maximum,
                               cancel=None if self.stage == "teardown" else self.cancel)
        except ProcessFailure as error:
            if error.result:
                self.observe(error.result)
            raise
        self.observe(result)
        if check and result.returncode != 0:
            raise ProcessFailure("assertion-failure", "child-exit-failure", result)
        return result

    def observe(self, result: Result) -> None:
        self.last = result
        safe = redact(result.output.decode("utf-8", "replace"),
                      (str(self.root), str(self.repo), str(Path.home())), self.secrets)
        self.log_tail = (self.log_tail + safe)[-MAX_TAIL:]

    def source_identity(self) -> None:
        observed = self.command(["git", "-c", "gc.auto=0", "rev-parse", "--verify", "HEAD"], maximum=256)
        revision = observed.output.decode("ascii").strip()
        require(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision), "invalid-fixture", "source-revision-invalid")
        status = self.command(["git", "status", "--porcelain", "--untracked-files=no"], maximum=65536)
        self.source = {"revision": revision, "dirty": bool(status.output.strip()), "observed": True}
        claimed = os.environ.get("GITHUB_SHA")
        require(claimed is None or claimed == revision, "invalid-fixture", "source-checkout-mismatch")

    def artifact(self, role: str, path: Path, maximum: int = 32 * 1024 * 1024) -> None:
        self.remaining()
        try:
            require(path.is_file() and not path.is_symlink(), "invalid-fixture", "prepared-artifact-missing-or-linked")
            self.fixture_ids[role] = digest(path, maximum)
        except OSError:
            raise ProcessFailure("invalid-fixture", "prepared-artifact-unreadable") from None
        self.remaining()

    def prerequisites(self, artifacts: dict[str, Path] | None = None, *, before_build: bool = False) -> None:
        requirements = self.policy["prerequisites"]
        require(f"{sys.platform}-{platform.machine()}" in self.policy["platforms"],
                "unavailable-environment", "unsupported-suite-platform")
        for tool in requirements["tools"]:
            require(isinstance(tool, str) and shutil.which(tool), "unavailable-environment", "missing-tool-" + tool)
        # Probe the exact owned-child facility; no process census or zero values.
        if "owned-descendants" in requirements["accounting"]:
            self.command([sys.executable, "-I", "-c", "pass"], timeout=5)
        unknown = set(requirements["accounting"]) - {"owned-descendants", "owned-io"}
        require(not unknown, "invalid-fixture", "unknown-accounting-prerequisite")
        if "owned-io" in requirements["accounting"]:
            code = "from pathlib import Path; p=Path('/proc/self/io'); d=p.read_text(); assert 'read_bytes:' in d and 'write_bytes:' in d"
            try:
                self.command([sys.executable, "-I", "-c", code], timeout=5)
            except ProcessFailure as error:
                if error.category in {"cancelled", "infrastructure-timeout"}:
                    raise
                raise ProcessFailure("unavailable-environment", "owned-io-accounting-denied", error.result) from None
        for capability in requirements["filesystem"]:
            require(capability in {"private-mode", "atomic-replace", "fsync", "file-lock"},
                    "invalid-fixture", "unknown-filesystem-prerequisite")
        probe = self.root / "filesystem-probe"
        try:
            with probe.open("xb") as stream:
                probe.chmod(0o600)
                stream.write(b"owned fixture probe\n")
                stream.flush()
                if "fsync" in requirements["filesystem"]:
                    os.fsync(stream.fileno())
                if "file-lock" in requirements["filesystem"]:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            if "private-mode" in requirements["filesystem"]:
                require(stat.S_IMODE(probe.stat().st_mode) == 0o600
                        and stat.S_IMODE(self.root.stat().st_mode) == 0o700,
                        "unavailable-environment", "protected-filesystem-modes-unavailable")
            if "atomic-replace" in requirements["filesystem"]:
                probe.replace(self.root / "filesystem-replaced")
                probe = self.root / "filesystem-replaced"
            probe.unlink()
        except OSError:
            raise ProcessFailure("unavailable-environment", "filesystem-capability-unavailable") from None
        for service in requirements["services"]:
            require(set(service) == {"type", "image"} and service["type"] == "docker-image",
                    "invalid-fixture", "unknown-service-prerequisite")
            try:
                self.command(["docker", "image", "inspect", service["image"], "--format", "{{.Id}}"], timeout=5)
            except ProcessFailure as error:
                if error.category in {"cancelled", "infrastructure-timeout"}:
                    raise
                raise ProcessFailure("unavailable-environment", "prepared-provider-image-unavailable", error.result) from None
        for scope in requirements["versionScopes"]:
            # Reuse the existing version authority. #338's future aggregate CLI
            # is not yet present; do not pretend unknown flags select a scope.
            require(scope == "python", "unavailable-environment", "scoped-version-diagnostics-unavailable")
            try:
                try:
                    from . import check_tool_versions as versions
                except ImportError:
                    import check_tool_versions as versions
                baseline = versions.tomllib.loads(versions.BASELINE.read_text(encoding="utf-8"))
                versions.require_exact("Python", versions.platform.python_version(), baseline["contracts"]["python"])
            except (ImportError, OSError, ValueError, KeyError, RuntimeError):
                raise ProcessFailure("unavailable-environment", "authoritative-tool-version-check-failed") from None
        if not before_build:
            provided = artifacts or {}
            for role in requirements["artifacts"]:
                require(role in provided, "invalid-fixture", "missing-prepared-input-" + role)
                self.artifact(role, provided[role])

    def ready(self, expected: Ready, alive: Callable[[], bool], probe: Callable[[], Ready | None],
              timeout: float = 20) -> None:
        deadline = time.monotonic() + self.remaining(timeout)
        # Individually bounded child/HTTP probes inherit the readiness cap too.
        self.operation_deadline = deadline
        try:
            while time.monotonic() < deadline:
                require(alive(), "assertion-failure", "readiness-owner-not-alive")
                observed = probe()  # ONLY a non-mutating request; no mutation retry
                if observed is not None:
                    require(observed == expected and expected.run == self.run_id,
                            "invalid-fixture", "false-or-stale-readiness")
                    require(alive(), "assertion-failure", "readiness-owner-exited")
                    return
                self.cancel.wait(min(0.05, max(0, deadline - time.monotonic())))
                require(not self.cancel.is_set(), "cancelled", "cancelled-readiness")
            raise ProcessFailure("infrastructure-timeout", "readiness-timeout")
        finally:
            del self.operation_deadline

    def __exit__(self, kind: type | None, error: BaseException | None, traceback: object) -> bool:
        failed_stage = self.stage
        failed_result = error.result if isinstance(error, ProcessFailure) and error.result else self.last
        failed_tail = self.log_tail
        self.mark("teardown")
        if self.alarm:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, self.deadline - time.monotonic()))
        try:
            for close in reversed(self.cleanup):
                try:
                    close()
                except BaseException as cleanup_error:
                    self.cleanup_failures.append(type(cleanup_error).__name__)
            try:
                self.temporary.cleanup()
            except BaseException as cleanup_error:
                self.cleanup_failures.append(type(cleanup_error).__name__)
        finally:
            if self.alarm:
                signal.setitimer(signal.ITIMER_REAL, 0)
            for sig, handler in self.old_signals.items():
                signal.signal(sig, handler)
        if error is None and self.cleanup_failures:
            error = ProcessFailure("infrastructure-timeout", "fixture-cleanup-unconfirmed")
            failed_stage = "teardown"
        if error is None and time.monotonic() > self.deadline:
            error = ProcessFailure("infrastructure-timeout", "total-run-watchdog")
            failed_stage = "teardown"
        self.mark("complete")
        category = (error.category if isinstance(error, ProcessFailure) else
                    "cancelled" if isinstance(error, KeyboardInterrupt) else
                    "invalid-fixture" if isinstance(error, (OSError, ValueError)) else "assertion-failure")
        reason = error.reason if isinstance(error, ProcessFailure) else type(error).__name__ if error else None
        result = failed_result
        self.record = {
            "schemaVersion": FAILURE_SCHEMA, "suite": self.suite, "runId": self.run_id,
            "outcome": ("preflight-passed" if self.reproduction.get("preflight") else "passed") if error is None else "not-run" if category == "unavailable-environment" else "failed",
            "category": category if error else None, "reason": reason, "stage": failed_stage,
            "evidenceKind": "synthetic-process-contract" if self.synthetic else "runner-diagnostic-not-qualification",
            "source": self.source, "fixtures": self.fixture_ids,
            "child": {"exit": result.returncode if result and result.returncode is not None and result.returncode >= 0 else None,
                      "signal": -result.returncode if result and result.returncode is not None and result.returncode < 0 else None,
                      "cleanupAcknowledged": result.cleaned if result else None},
            "elapsedMs": round((time.monotonic() - self.started) * 1000, 3), "timings": self.timings,
            "startupMs": result.startup_ms if result else None,
            "teardownMs": result.teardown_ms if result else None,
            "cleanupFailures": self.cleanup_failures, "logTail": failed_tail,
            "reproduction": {**self.reproduction, "source": self.source, "fixtures": self.fixture_ids},
        }
        require(len(json.dumps(self.record).encode()) <= 65536, "invalid-fixture", "diagnostic-record-limit")
        self.diagnostic_root.mkdir(parents=True, exist_ok=True)
        destination = self.diagnostic_root / (self.suite + "-" + self.run_id + ".json")
        # Exclusive write: never overwrite a concurrent run's diagnostics.
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(self.record, output, sort_keys=True, separators=(",", ":"))
            output.write("\n")
        self.record_path = destination
        print(json.dumps({"suite": self.suite, "outcome": self.record["outcome"], "runId": self.run_id,
                          "reason": reason, "diagnostic": destination.name}), flush=True)
        if kind is None and error is not None:
            raise error
        return False


def selected_contract(name: str, *, repo: Path = ROOT, diagnostic_root: Path | None = None) -> tuple[dict, dict]:
    """Even a broken/missing inventory produces a bounded invalid-fixture record."""
    try:
        return contract(name)
    except ProcessFailure:
        with TestRun(name, {"timeoutSeconds": 5}, repo=repo, diagnostic_root=diagnostic_root):
            raise
