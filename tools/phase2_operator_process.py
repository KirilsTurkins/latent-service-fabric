"""Private, bounded Linux subprocess ownership for the operator workflow test.

Uses the maintained unreaped-group owner. No reader threads, retained log files,
shells, daemon adoption, or signaling of a reaped PID. These are trusted test
executables; deliberate session escape and supervisor SIGKILL remain excluded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from tools.build_process_linux import OwnedProcess


class WorkflowError(RuntimeError):
    """Only fixed test-stage diagnostics may be supplied."""


def require(condition, reason):
    if not condition:
        raise WorkflowError(reason)


def diagnostic_code(value):
    """Keep only the CLI's bounded code token, never messages or error details."""
    if not isinstance(value, dict) or value.get("schemaVersion") != "latent.cli.result.v1":
        return "unavailable"
    error = value.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", code):
        return code
    return "unavailable"


def diagnostic_grpc(value):
    """Only the finite gRPC status vocabulary already projected by the CLI."""
    if not isinstance(value, dict) or value.get("schemaVersion") != "latent.cli.result.v1":
        return "absent"
    error = value.get("error")
    code = error.get("grpcCode") if isinstance(error, dict) else None
    allowed = ("ok", "cancelled", "unknown", "invalid-argument", "deadline-exceeded",
               "not-found", "already-exists", "permission-denied", "resource-exhausted",
               "failed-precondition", "aborted", "out-of-range", "unimplemented",
               "internal", "unavailable", "data-loss", "unauthenticated")
    return code if isinstance(code, str) and code in allowed else "absent"


def read_json(path: Path, maximum=262144):
    require(path.is_file() and not path.is_symlink(), "fixture-file")
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    require(len(data) <= maximum, "fixture-size")
    return json.loads(data)


def write_json(path: Path, value):
    data = json.dumps(value, separators=(",", ":")).encode("utf-8")
    require(len(data) <= 262144, "fixture-size")
    with path.open("xb") as target:
        target.write(data)
    path.chmod(0o600)


def write_candidate_manifest(source: Path, output: Path, weight: int):
    """Create the operator's explicit candidate without rewriting its fixture."""
    require(weight in (1000, 5000), "candidate-weight")
    manifest = read_json(source)
    require(manifest.get("kind") == "Deployment", "candidate-manifest")
    manifest["spec"]["route"]["weight"] = weight
    write_json(output, manifest)
    return output


class Process:
    """A leader stays unreaped until its complete owned group is finished."""

    def __init__(self, argv, cwd, environment, cancellation, maximum=1048576):
        self.owner = OwnedProcess()
        self.cancellation = cancellation
        self.maximum = maximum
        self.total = 0
        self.buffers = [bytearray(), bytearray()]
        self.streams = []
        self.closed = False
        try:
            with cancellation.defer():
                self.owner.spawn(argv, cwd, environment, time.monotonic() + 30)
                self.streams = [self.owner.process.stdout, self.owner.process.stderr]
                for stream in self.streams:
                    os.set_blocking(stream.fileno(), False)
        except BaseException:
            self.close()
            raise

    def drain(self):
        self.cancellation.check()
        for index, stream in enumerate(self.streams):
            if stream is None:
                continue
            # At most two fixed-size reads per turn. Accounting is cumulative
            # even if a caller consumes an earlier startup line.
            try:
                chunk = os.read(stream.fileno(), min(16384, self.maximum - self.total + 1))
            except BlockingIOError:
                continue
            require(len(chunk) <= self.maximum - self.total, "process-output-limit")
            self.total += len(chunk)
            self.buffers[index].extend(chunk)
            if not chunk:
                self.streams[index] = None

    def line(self, deadline):
        while time.monotonic() < deadline:
            self.drain()
            buffer = self.buffers[0]
            if b"\n" in buffer:
                line, _, tail = buffer.partition(b"\n")
                require(len(line) <= 16384, "node-startup-size")
                self.buffers[0] = bytearray(tail)
                return json.loads(line)
            require(len(buffer) <= 16384, "node-startup-size")
            require(not self.owner.exited(), "node-startup-exit")
            time.sleep(0.01)
        raise WorkflowError("node-startup-deadline")

    def complete(self, deadline):
        while True:
            self.drain()
            if self.owner.exited():
                # finish retains the leader reservation while cleaning children.
                with self.cancellation.defer():
                    self.owner.finish(time.monotonic() + 5)
                for _ in range(128):
                    if not any(self.streams):
                        break
                    self.drain()
                require(not any(self.streams), "process-pipe-cleanup")
                require(time.monotonic() < deadline, "process-deadline")
                return subprocess.CompletedProcess([], self.owner.process.returncode,
                                                   bytes(self.buffers[0]), bytes(self.buffers[1]))
            require(time.monotonic() < deadline, "process-deadline")
            time.sleep(0.005)

    def stop(self):
        try:
            if not self.owner.exited():
                # Signal only while this owner reserves the unreaped leader.
                os.kill(self.owner.process.pid, signal.SIGTERM)
            result = self.complete(time.monotonic() + 10)
            require(result.returncode == 0, "node-shutdown-exit")
        finally:
            self.close()

    def close(self):
        if self.closed:
            return
        try:
            with self.cancellation.defer():
                try:
                    self.owner.finish(time.monotonic() + 5)
                finally:
                    self.owner.close()
        finally:
            self.closed = True


class Client:
    def __init__(self, executable, directory, cancellation, deadline):
        self.executable = str(executable)
        self.directory = directory
        self.cancellation = cancellation
        self.deadline = deadline
        self.config = None
        self.node = None
        self.calls = 0
        self.environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(directory),
                            "LANG": "C.UTF-8", "RUST_BACKTRACE": "0"}

    def call(self, *arguments, codes=(0,), timeout=25):
        self.cancellation.check()
        require(time.monotonic() < self.deadline, "workflow-deadline")
        if self.node:
            self.node.drain()
        prefix = [self.executable, "--output", "json"]
        if self.config:
            prefix += ["--config", str(self.config), "--profile", "operator"]
        argv = prefix + [str(value) for value in arguments]
        process = Process(argv, self.directory, self.environment, self.cancellation)
        try:
            result = process.complete(min(self.deadline, time.monotonic() + timeout))
        finally:
            process.close()
        if self.node:
            self.node.drain()
        self.calls += 1
        try:
            value = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            value = None
        require(result.returncode in codes,
                f"cli-exit-call-{self.calls}-status-{result.returncode}-code-{diagnostic_code(value)}"
                f"-grpc-{diagnostic_grpc(value)}")
        require(isinstance(value, dict) and value.get("schemaVersion") == "latent.cli.result.v1",
                "cli-result-schema")
        require(isinstance(value.get("outcomeKnown"), bool), "cli-certainty")
        require(isinstance(value.get("data"), dict), "cli-data")
        if result.returncode == 0:
            require(value["category"] == "success", "cli-success-category")
        return value
