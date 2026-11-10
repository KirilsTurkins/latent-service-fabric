"""Public operator commands with explicit scoped configuration and no retries."""
from __future__ import annotations

from pathlib import Path
import time

from . import process
from .common import DevError, decode, require, sha


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
        self.expected_config_digest = None

    def pin_config(self, expected_digest: str) -> None:
        expected_digest = sha(expected_digest)
        require(self.expected_config_digest in (None, expected_digest), "operator-client-already-bound")
        self.expected_config_digest = expected_digest

    def require_scenario_budget_support(self) -> None:
        # This fixed local probe supplies no configuration, credentials or
        # payload. A supporting CLI parses --budget-json, then rejects the
        # deliberately incompatible quiet/JSON pair before config or I/O.
        # A legacy CLI rejects the unknown budget option during argument parse.
        # This observes compatibility now; it does not pin the executable.
        def probe(with_budget):
            timeout = 3.0
            if self.deadline is not None:
                remaining = self.deadline - time.monotonic()
                require(remaining > 5, "node-test-run-deadline")
                timeout = min(timeout, remaining - 5)
            arguments = [
                str(self.binary), "--output", "json", "--quiet", "invoke",
                "--service", "capability-probe", "--contract", "tests:probe/api@0.1.0",
                "--function", "check", "--input", "-",
            ]
            if with_budget:
                arguments.extend(["--budget-json", "{}"])
            result = process.run(arguments, self.directory, timeout=timeout, maximum=65536)
            require(result.returncode == 2 and not result.stderr, "installed-cli-budget-probe-failed")
            try:
                value = decode(result.stdout, 65536)
            except DevError:
                raise DevError("installed-cli-budget-probe-invalid-response") from None
            require(isinstance(value, dict)
                    and value.get("schemaVersion") == "latent.cli.result.v1"
                    and value.get("category") == "local-error"
                    and value.get("outcomeKnown") is True
                    and value.get("requestDispatched") is False
                    and isinstance(value.get("error"), dict), "installed-cli-budget-probe-invalid-response")
            return value.get("command"), value["error"].get("code")

        # The first probe verifies every fixed option before attributing a
        # second parse failure to the newly required budget option.
        if probe(False) != ("invoke", "conflicting-output-options"):
            raise DevError("installed-cli-budget-probe-inconclusive")
        observation = probe(True)
        if observation == ("invoke", "conflicting-output-options"):
            return
        if observation == ("arguments", "invalid-arguments"):
            raise DevError("installed-cli-budget-option-unavailable-upgrade-runtime")
        raise DevError("installed-cli-budget-probe-inconclusive")

    def call(self, *arguments: str, timeout: float = 30, check=None, stdin: bytes | None = None) -> dict:
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
            require(timeout > 0, "node-test-run-deadline")
        require(stdin is None or type(stdin) is bytes, "operator-request-input-type")
        pin = [] if self.expected_config_digest is None else ["--expect-config-digest-stdin"]
        prefix = b"" if self.expected_config_digest is None else (self.expected_config_digest + "\n").encode("ascii")
        input_options = {} if not prefix and stdin is None else {"stdin": prefix + (stdin or b"")}
        result = process.run([str(self.binary), "--config", str(self.config), "--output", "json",
                               *pin, *map(str, arguments)], self.directory, timeout=timeout,
                             maximum=1048576, check=check, **input_options)
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

    def control(self, language: str, *arguments: str, stdin: bytes | None = None) -> dict:
        # SpiderMonkey package preparation uses the language owner's existing
        # bounded control allowance. This is one request, never a retry after
        # timeout, and does not increase the server or activation limits.
        timeout = 130 if language == "typescript" else 30
        rpc_millis = 125000 if language == "typescript" else 5000
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            require(remaining > 0, "node-test-run-deadline")
            rpc_millis = min(rpc_millis, max(1, int((remaining - 1) * 1000)))
        options = {} if stdin is None else {"stdin": stdin}
        return self.call("--rpc-timeout-ms", str(rpc_millis), *arguments, timeout=timeout, **options)

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
