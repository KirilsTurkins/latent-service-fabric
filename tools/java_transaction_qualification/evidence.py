"""Bounded original observations; an observer never supplies durable authority."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time

from tools.phase2_operator_process import Client, Process, diagnostic_code, diagnostic_grpc

from .inputs import decode, digest, require


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


class Evidence:
    def __init__(self, directory: Path):
        directory.mkdir(mode=0o700)
        self.directory = directory
        self.files, self.cases, self.total = [], [], 0

    def write(self, name: str, raw: bytes) -> dict:
        require(isinstance(name, str) and re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,95}", name),
                "closed-evidence-file-name")
        require(isinstance(raw, bytes) and len(raw) <= 1048576 and len(self.files) < 1024
                and self.total + len(raw) <= 33554432, "original-evidence-byte-bound")
        path = self.directory / name
        with path.open("xb") as target:
            target.write(raw)
        path.chmod(0o600)
        record = {"path": name, "bytes": len(raw), "digest": digest(raw)}
        self.files.append(record)
        self.total += len(raw)
        return record

    def record(self, name: str, value) -> dict:
        return self.write(name + ".json", encoded(value))

    def passed(self, name: str, observed: dict):
        require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name)
                and name not in self.cases and len(self.cases) < 64,
                "bounded-distinct-measured-case")
        self.record("case-" + name, {"passed": True, "observed": observed})
        self.cases.append(name)

    def summary(self):
        return {"files": list(self.files), "bytes": self.total, "cases": list(self.cases)}


class RecordingClient(Client):
    """The original single-call CLI path, with raw output retained before checks.

    No argv or credential bytes are recorded. Failed or uncertain mutations are
    never retried. The inherited process owner positively reaps every CLI.
    """
    def __init__(self, executable, directory, cancellation, deadline, evidence):
        super().__init__(executable, directory, cancellation, deadline)
        self.evidence = evidence

    def call(self, *arguments, codes=(0,), timeout=25):
        self.cancellation.check()
        require(self.calls < 256 and time.monotonic() < self.deadline,
                "original-cli-campaign-bound")
        if self.node:
            self.node.drain()
        prefix = [self.executable, "--output", "json"]
        if self.config:
            prefix += ["--config", str(self.config), "--profile", "operator"]
        self.calls += 1
        ordinal = self.calls
        process = Process(prefix + [str(value) for value in arguments], self.directory,
                          self.environment, self.cancellation, maximum=1048576)
        result = None
        try:
            result = process.complete(min(self.deadline, time.monotonic() + timeout))
        finally:
            process.close()
            self.evidence.write(f"cli-{ordinal:03d}.stdout", bytes(process.buffers[0]))
            self.evidence.write(f"cli-{ordinal:03d}.stderr", bytes(process.buffers[1]))
            self.evidence.record(f"cli-{ordinal:03d}-process", {
                "exitStatus": process.owner.process.returncode,
                "reaped": process.closed and process.owner.finished})
        if self.node:
            self.node.drain()
        value = decode(result.stdout, 1048576)
        require(result.returncode in codes,
                f"cli-exit-call-{ordinal}-status-{result.returncode}-code-{diagnostic_code(value)}"
                f"-grpc-{diagnostic_grpc(value)}")
        require(isinstance(value, dict) and value.get("schemaVersion") == "latent.cli.result.v1"
                and type(value.get("outcomeKnown")) is bool and isinstance(value.get("data"), dict),
                "actual-cli-result-contract")
        require(result.returncode != 0 or value["category"] == "success", "actual-cli-success-category")
        return value


def native(client: RecordingClient, executable: Path, stage: str, *arguments, timeout=60):
    """One owned native helper; its original output and actual exit are evidence."""
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", stage), "native-helper-stage")
    client.cancellation.check()
    process = Process([str(executable), *[str(value) for value in arguments]], client.directory,
                      client.environment, client.cancellation, maximum=1048576)
    result = None
    try:
        result = process.complete(min(client.deadline, time.monotonic() + timeout))
    finally:
        process.close()
        client.evidence.write(stage + ".stdout", bytes(process.buffers[0]))
        client.evidence.write(stage + ".stderr", bytes(process.buffers[1]))
        client.evidence.record(stage + "-process", {
            "exitStatus": process.owner.process.returncode,
            "reaped": process.closed and process.owner.finished})
    require(result.returncode == 0, "native-helper-refused-" + stage)
    return result.stdout
