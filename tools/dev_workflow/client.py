"""Public operator commands with explicit scoped configuration and no retries."""
from __future__ import annotations

from pathlib import Path
import time

from . import process
from .common import DevError, decode, require


class Client:
    def __init__(self, binary: Path, config: Path, directory: Path, *, deadline: float | None = None):
        self.binary, self.config, self.directory = binary, config, directory
        self.deadline = deadline

    def call(self, *arguments: str, timeout: int = 30) -> dict:
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
            require(timeout > 0, "node-test-run-deadline")
        result = process.run([str(self.binary), "--config", str(self.config), "--output", "json",
                               *map(str, arguments)], self.directory, timeout=timeout, maximum=1048576)
        value = decode(result.stdout, 1048576)
        require(value.get("schemaVersion") == "latent.cli.result.v1"
                and type(value.get("outcomeKnown")) is bool and isinstance(value.get("data"), dict),
                "operator-response-format")
        require(result.returncode in {0, 2, 3, 4, 5, 6, 130} and (result.returncode != 0 or value.get("category") == "success"),
                "operator-response-exit-mismatch")
        return value

    def control(self, language: str, *arguments: str) -> dict:
        # SpiderMonkey package preparation uses the language owner's existing
        # bounded control allowance. This is one request, never a retry after
        # timeout, and does not increase the server or activation limits.
        timeout = 130 if language == "typescript" else 30
        rpc_millis = 125000 if language == "typescript" else 5000
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            require(remaining > 0, "node-test-run-deadline")
            rpc_millis = min(rpc_millis, max(1, int((remaining - 1) * 1000)))
        return self.call("--rpc-timeout-ms", str(rpc_millis), *arguments, timeout=timeout)

    def lookup(self, kind: str, operation: str) -> dict:
        require(kind in {"release", "deployment", "invoke", "policy"}, "unknown-operation-kind")
        if kind == "policy":
            from .policy_operations import lookup
            return lookup(self, operation)
        return self.call("activation", "get", operation) if kind == "invoke" else self.call(kind, "operation", operation)


def successful(value: dict) -> dict:
    if not value["outcomeKnown"]:
        raise DevError("operator-outcome-uncertain", uncertain=True)
    require(value["category"] == "success", "operator-request-rejected-last-deployment-retained")
    return value["data"]
