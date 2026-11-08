"""Public operator commands with explicit scoped configuration and no retries."""
from __future__ import annotations

from pathlib import Path
import time

from . import process
from .common import DevError, decode, require


# Native CLI Category::exit_code is a closed, one-to-one result contract.
CATEGORY_EXIT_CODES = {
    "success": 0, "local-error": 2, "declared-error": 3,
    "platform-failure": 4, "transport-failure": 5, "not-found": 6,
    "interrupted": 130,
}


class Client:
    def __init__(self, binary: Path, config: Path, directory: Path, *, deadline: float | None = None, observer=None):
        self.binary, self.config, self.directory = binary, config, directory
        self.deadline = deadline
        self.observer, self.calls, self.failed_call = observer, 0, None
        self.observation_failed = False

    def call(self, *arguments: str, timeout: float = 30, check=None) -> dict:
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
            require(timeout > 0, "node-test-run-deadline")
        result = process.run([str(self.binary), "--config", str(self.config), "--output", "json",
                               *map(str, arguments)], self.directory, timeout=timeout, maximum=1048576, check=check)
        self.calls += 1
        value, failure = None, None
        try:
            value = decode(result.stdout, 1048576)
            require(isinstance(value, dict) and value.get("schemaVersion") == "latent.cli.result.v1"
                    and type(value.get("outcomeKnown")) is bool and isinstance(value.get("data"), dict)
                    and type(value.get("category")) is str and value["category"] in CATEGORY_EXIT_CODES,
                    "operator-response-format")
            require(type(result.returncode) is int and result.returncode == CATEGORY_EXIT_CODES[value["category"]],
                    "operator-response-exit-mismatch")
            return value
        except DevError as error:
            failure = error.code
            raise
        finally:
            if self.observer is not None:
                from tools.phase2_operator_process import failed_call_record
                observation = {**failed_call_record(value, self.calls, result.returncode),
                    "stdoutBytes": len(result.stdout), "stderrBytes": len(result.stderr),
                    "validationCode": failure}
                if failure is not None or (value is not None and value.get("category") != "success"):
                    self.failed_call = observation
                try:
                    self.observer(observation)
                except (OSError, DevError):
                    # Diagnostics cannot replace the original response decision.
                    self.observation_failed = True

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
