"""Public operator commands with explicit scoped configuration and no retries."""
from __future__ import annotations

from pathlib import Path

from . import process
from .common import DevError, decode, require


class Client:
    def __init__(self, binary: Path, config: Path, directory: Path):
        self.binary, self.config, self.directory = binary, config, directory

    def call(self, *arguments: str, timeout: int = 30) -> dict:
        result = process.run([str(self.binary), "--config", str(self.config), "--output", "json",
                               *map(str, arguments)], self.directory, timeout=timeout, maximum=1048576)
        value = decode(result.stdout, 1048576)
        require(value.get("schemaVersion") == "latent.cli.result.v1"
                and type(value.get("outcomeKnown")) is bool and isinstance(value.get("data"), dict),
                "operator-response-format")
        require(result.returncode in {0, 2, 3, 4, 5, 6, 130} and (result.returncode != 0 or value.get("category") == "success"),
                "operator-response-exit-mismatch")
        return value

    def lookup(self, kind: str, operation: str) -> dict:
        require(kind in {"release", "deployment", "invoke"}, "unknown-operation-kind")
        return self.call("activation", "get", operation) if kind == "invoke" else self.call(kind, "operation", operation)


def successful(value: dict) -> dict:
    if not value["outcomeKnown"]:
        raise DevError("operator-outcome-uncertain", uncertain=True)
    require(value["category"] == "success", "operator-request-rejected-last-deployment-retained")
    return value["data"]
