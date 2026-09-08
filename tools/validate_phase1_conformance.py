#!/usr/bin/env python3
"""Verify a bounded deterministic report; this never approves the Phase 1 gate."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

if __package__:
    from .phase1_compiler_shutdown import validate_compiler_shutdown
else:
    from phase1_compiler_shutdown import validate_compiler_shutdown

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/phase1/cases.json"
MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_TOTAL_ARTIFACT_BYTES = 64 * 1024 * 1024
SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
GIT_HASH = re.compile(r"[0-9a-f]{40}\Z")
DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,19})\Z")
PARITY_PAIRS = ("success", "declared-error", "malformed-json", "absolute-deadline",
                "zero-memory", "zero-fuel", "missing-route", "foreign-tenant")
PARITY_INPUTS = ("echo-capsule.wasm", "capsule.json", "contracts.json", "deployment.json")
ZERO_SHUTDOWN_FIELDS = (
    "activeConnections", "activeRpcs", "activeControlJobs", "activeActivations",
    "cancellationRegistrations", "observerCorrelations", "quotaReservations",
    "queuedReservations", "reservedCpuFuel", "reservedMemoryBytes", "activeLeases",
    "queuedActivations", "activeBackendInvocations", "instanceReservations",
    "preparingComponents", "preparingSourceBytes", "preparingMetadataBytes",
    "liveStores", "liveHostStates", "liveInstances", "liveTemporaryBuffers",
    "liveCancellationProbes",
)


class ConformanceValidationError(ValueError):
    """A fixed diagnostic, never a raw secret, payload, or filesystem path."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ConformanceValidationError(reason)


def fields(value: Any, names: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == set(names.split()), "invalid-object-fields")
    return value


def uint(value: Any) -> int:
    require(isinstance(value, str) and DECIMAL.fullmatch(value) is not None, "invalid-u64")
    number = int(value)
    require(number <= 2**64 - 1, "invalid-u64")
    return number


def number(value: Any, maximum: int = 2**32 - 1, minimum: int = 0) -> int:
    require(type(value) is int and minimum <= value <= maximum, "invalid-integer")
    return value


def text(value: Any, maximum: int = 4096) -> str:
    require(isinstance(value, str) and 0 < len(value.encode("utf-8")) <= maximum, "invalid-string")
    require(not any(ord(char) < 32 for char in value), "invalid-string")
    return value


def digest(value: Any) -> str:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None, "invalid-digest")
    return value


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate-json-field")
        result[key] = value
    return result


def load_bounded(path: Path, maximum: int = MAX_REPORT_BYTES) -> Any:
    try:
        require(path.is_file(), "nonregular-evidence-file")
        with path.open("rb") as source:
            data = source.read(maximum + 1)
    except OSError as error:
        raise ConformanceValidationError("unreadable-evidence-file") from error
    return parse_bounded(data, maximum)


def parse_bounded(data: bytes, maximum: int = MAX_REPORT_BYTES) -> Any:
    require(len(data) <= maximum, "report-byte-limit")
    # Bound nesting before the standard parser allocates containers/descends.
    depth = 0
    quoted = escaped = False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            require(depth <= 48, "report-depth-limit")
        elif byte in (93, 125):
            depth -= 1
    try:
        value = json.loads(data, object_pairs_hook=_unique, parse_constant=lambda _: _invalid_constant(),
                           parse_int=_json_integer)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ConformanceValidationError("invalid-report-json") from error
    bounded_tree(value)
    return value


def _invalid_constant() -> None:
    raise ConformanceValidationError("non-finite-json-number")


def _json_integer(value: str) -> int:
    require(len(value) <= 21, "json-integer-limit")
    result = int(value)
    require(-(2**63) <= result <= 2**64 - 1, "json-integer-limit")
    return result


def bounded_tree(value: Any) -> None:
    stack = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        require(nodes <= 65536 and depth <= 48, "report-structure-limit")
        if isinstance(current, dict):
            require(len(current) <= 4096, "report-collection-limit")
            for key, item in current.items():
                require(len(key.encode("utf-8")) <= 4096, "report-string-limit")
                stack.append((item, depth + 1))
        elif isinstance(current, list):
            require(len(current) <= 4096, "report-collection-limit")
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str):
            require(len(current.encode("utf-8")) <= 65536, "report-string-limit")
        elif isinstance(current, float):
            require(math.isfinite(current), "non-finite-json-number")


def work(value: Any, invokes: int = 64, commands: int = 256) -> tuple[int, int]:
    fields(value, "commands invoke_attempts budget_exhausted")
    actual_commands, actual_invokes = uint(value["commands"]), uint(value["invoke_attempts"])
    require(value["budget_exhausted"] is False, "work-budget-exhausted")
    require(actual_invokes <= invokes and actual_commands <= commands and actual_invokes <= actual_commands,
            "work-budget-exceeded")
    return actual_commands, actual_invokes


def safe_path(root: Path, relative: Any) -> Path:
    relative = text(relative, 512)
    pure = PurePosixPath(relative)
    require(not pure.is_absolute() and "\\" not in relative and ":" not in relative
            and all(part not in ("", ".", "..") for part in relative.split("/")), "invalid-artifact-path")
    resolved_root = root.resolve(strict=True)
    candidate = resolved_root
    for part in pure.parts:
        candidate /= part
        require(not candidate.is_symlink(), "symlink-artifact-path")
    try:
        require(candidate.resolve(strict=True).is_relative_to(resolved_root), "artifact-path-escape")
        require(candidate.is_file(), "nonregular-artifact")
    except OSError as error:
        raise ConformanceValidationError("missing-artifact") from error
    return candidate


def verify_artifacts(report: dict[str, Any], root: Path) -> set[str]:
    artifacts = report["artifacts"]
    require(isinstance(artifacts, list) and 0 < len(artifacts) <= 512, "artifact-count-limit")
    paths: set[str] = set()
    total = 0
    for artifact in artifacts:
        fields(artifact, "path sha256 bytes")
        path = safe_path(root, artifact["path"])
        require(artifact["path"] not in paths, "duplicate-artifact")
        paths.add(artifact["path"])
        size = uint(artifact["bytes"])
        total += size
        require(size <= MAX_ARTIFACT_BYTES and total <= MAX_TOTAL_ARTIFACT_BYTES, "artifact-byte-limit")
        try:
            with path.open("rb") as source:
                data = source.read(size + 1)
        except OSError as error:
            raise ConformanceValidationError("unreadable-artifact") from error
        require(len(data) == size and sha256(data) == digest(artifact["sha256"]), "artifact-content-mismatch")
    return paths


def verify_identity(identity: Any) -> None:
    fields(identity, "source_commit source_tree source_dirty cargo_lock_sha256 config_sha256 binaries fixtures")
    for field in ("source_commit", "source_tree"):
        require(isinstance(identity[field], str) and GIT_HASH.fullmatch(identity[field]) is not None,
                "invalid-source-identity")
    require(type(identity["source_dirty"]) is bool, "invalid-source-identity")
    digest(identity["cargo_lock_sha256"])
    digest(identity["config_sha256"])
    for key, required in (("binaries", {"latent", "latentd"}), ("fixtures", {"echo", "generic", "capabilities"})):
        entries = identity[key]
        require(isinstance(entries, list) and len(entries) <= 16, "invalid-file-identities")
        names = set()
        for entry in entries:
            fields(entry, "name sha256 bytes")
            name = text(entry["name"], 128)
            require(name not in names, "duplicate-file-identity")
            names.add(name)
            digest(entry["sha256"])
            require(uint(entry["bytes"]) > 0, "empty-file-identity")
        require(required <= names, "missing-file-identity")


def verify_public_config(config: Any) -> None:
    require(isinstance(config, dict) and bool(config), "missing-public-config")
    stack = [config]
    forbidden = {"token", "credentials", "authorization", "password", "secret", "bearer"}
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            require(not any(key.lower() in forbidden for key in value), "secret-config-field")
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, float):
            require(False, "nonintegral-public-config-number")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_config_digest(config: Any, expected: Any) -> None:
    verify_public_config(config)
    require(sha256(canonical_json(config)) == digest(expected), "public-config-digest-mismatch")


def verified_json_artifact(report: dict[str, Any], root: Path, name: str, maximum: int) -> Any:
    reference = next((entry for entry in report["artifacts"] if entry["path"] == name), None)
    require(reference is not None, "missing-case-artifact")
    path = safe_path(root, name)
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    require(len(data) <= maximum, "case-artifact-byte-limit")
    require(len(data) == uint(reference["bytes"]) and sha256(data) == reference["sha256"], "artifact-content-mismatch")
    return parse_bounded(data, maximum)


def verify_case_artifact(entry: dict[str, Any], report: dict[str, Any], root: Path) -> None:
    if entry["id"] == "adapter-rpc-parity":
        require("adapter.json" in entry["diagnostics"], "missing-adapter-artifact")
        fragment = verified_json_artifact(report, root, "adapter.json", 1024 * 1024)
        fields(fragment, "driver cases work artifacts")
        require(fragment["driver"] == "adapter" and isinstance(fragment["cases"], list)
                and len(fragment["cases"]) == 1, "invalid-adapter-fragment")
        require(canonical_json(fragment["cases"][0]) == canonical_json(entry)
                and canonical_json(fragment["work"]) == canonical_json(entry["work"]),
                "adapter-fragment-mismatch")
        require(isinstance(fragment["artifacts"], list)
                and all(artifact in report["artifacts"] for artifact in fragment["artifacts"]),
                "missing-adapter-fragment-artifact")
    else:
        name = f"case-{entry['id']}.json"
        require(name in entry["diagnostics"], "missing-case-observation-artifact")
        raw = verified_json_artifact(report, root, name, 256 * 1024)
        require(canonical_json(raw) == canonical_json(entry["observations"]), "case-observation-mismatch")


def verify_shutdown(raw: Any, *, cells: int = 5) -> None:
    fields(raw, " ".join(ZERO_SHUTDOWN_FIELDS) +
           " clean quarantinedCells telemetryRetainedEntries telemetryFlushed epochHelperJoined"
           + (" compiler" if isinstance(raw, dict) and "compiler" in raw else ""))
    if "compiler" in raw:
        validate_compiler_shutdown(raw["compiler"], require)
    require(all(raw[key] is True for key in ("clean", "telemetryFlushed", "epochHelperJoined")), "unclean-shutdown")
    require(all(type(raw[key]) is int and raw[key] == 0 for key in ZERO_SHUTDOWN_FIELDS), "live-transient-owners")
    number(raw["quarantinedCells"], cells)
    number(raw["telemetryRetainedEntries"], 65536)


def cli_data(value: Any, command: str, category: str, *, known: bool = True) -> dict[str, Any]:
    fields(value, "schemaVersion command category data error requestDispatched outcomeKnown")
    require(value["schemaVersion"] == "latent.cli.result.v1" and value["command"] == command
            and value["category"] == category and value["requestDispatched"] is True
            and value["outcomeKnown"] is known, "invalid-case-cli-outcome")
    require(isinstance(value["data"], dict), "missing-case-cli-data")
    if category == "success":
        require(value["error"] is None, "unexpected-case-cli-error")
    return value["data"]


def cli_consumption(value: Any) -> dict[str, int]:
    fields(value, "cpuFuel peakMemoryBytes wallTimeMicros childCalls outboundRequests stateReadBytes stateWriteBytes blobReadBytes blobWriteBytes logBytes effectCount")
    numbers = {key: uint(value[key]) for key in ("cpuFuel", "peakMemoryBytes", "wallTimeMicros",
               "stateReadBytes", "stateWriteBytes", "blobReadBytes", "blobWriteBytes", "logBytes")}
    for key in ("childCalls", "outboundRequests", "effectCount"):
        numbers[key] = number(value[key], 0)
    require(all(numbers[key] == 0 for key in ("stateReadBytes", "stateWriteBytes", "blobReadBytes", "blobWriteBytes")),
            "unexpected-later-phase-consumption")
    return numbers


def cli_payload(value: Any) -> Any:
    fields(value, "encoding mediaType data byteLength")
    require(value["encoding"] == "base64" and value["mediaType"] == "application/vnd.latent.wit-values.v1+json",
            "invalid-case-payload-media")
    require(isinstance(value["data"], str) and len(value["data"]) <= 8192, "case-payload-byte-limit")
    try:
        raw = base64.b64decode(value["data"], validate=True)
    except (ValueError, binascii.Error) as error:
        raise ConformanceValidationError("invalid-case-payload-encoding") from error
    require(len(raw) == uint(value["byteLength"]) and len(raw) <= 4096, "case-payload-byte-limit")
    return parse_bounded(raw, 4096)


def terminal_status(value: Any, activation_id: str, terminal: str, consumption: Any) -> dict[str, Any]:
    data = cli_data(value, "activation get", "success")
    require(data.get("activationId") == activation_id and data.get("terminalState") == terminal,
            "case-terminal-association")
    require(uint(data.get("terminalAtUnixMillis")) > 0, "missing-case-terminal-time")
    cli_consumption(data.get("finalConsumption"))
    require(canonical_json(data["finalConsumption"]) == canonical_json(consumption), "case-terminal-accounting-mismatch")
    return data


def phase_status(value: Any, activation_id: str, phase: str) -> None:
    data = cli_data(value, "activation get", "success")
    require(data.get("activationId") == activation_id and data.get("phase") == phase
            and data.get("terminalState") is None and data.get("finalConsumption") is None
            and data.get("terminalAtUnixMillis") is None, "case-pending-association")


def invocation_failure(value: Any, activation_id: str, code: str, terminal: str) -> dict[str, Any]:
    data = cli_data(value, "invoke", "platform-failure")
    require(data.get("activationId") == activation_id and data.get("terminalState") == terminal
            and isinstance(value["error"], dict) and value["error"].get("code") == code,
            "case-platform-outcome-mismatch")
    cli_consumption(data.get("consumption"))
    pin = fields(data.get("resolvedRevision"), "revisionId releaseDigest routeGeneration")
    text(pin["revisionId"], 512)
    digest(pin["releaseDigest"])
    require(uint(pin["routeGeneration"]) > 0, "missing-case-revision")
    return data


def idle_sample(sample: Any, report: dict[str, Any], phase: str) -> None:
    fields(sample, "sequence sample_started_micros sample_finished_micros node_instance phase process inventory")
    require(sample["phase"] == phase and isinstance(sample["process"], dict), "invalid-idle-sample")
    uint(sample["sequence"])
    require(uint(sample["sample_started_micros"]) <= uint(sample["sample_finished_micros"]), "invalid-observation-window")
    require(any(sample["node_instance"] == retained["node_instance"]
                and sample["process"].get("identity") == retained["process"]["identity"]
                for retained in report["samples"]), "wrong-idle-sample-owner")
    inventory = sample["inventory"]
    require(isinstance(inventory, dict), "missing-idle-inventory")
    require(uint(inventory.get("queueDepth")) == 0, "nonempty-idle-queue")
    cache = inventory.get("cacheSummary")
    require(isinstance(cache, dict), "missing-idle-cache")
    for key in ("preparing", "preparingSourceBytes", "preparingMetadataBytes"):
        require(uint(cache.get(key)) == 0, "live-idle-preparation")
    quotas = inventory.get("quotas")
    require(isinstance(quotas, dict) and isinstance(quotas.get("usage"), dict), "missing-idle-quota")
    usage = quotas["usage"]
    for key in ("activeActivations", "queuedActivations"):
        number(usage.get(key), 0)
    for key in ("reservedCpuFuel", "reservedMemoryBytes"):
        require(uint(usage.get(key)) == 0, "live-idle-quota")
    cells = inventory.get("cellCapacity")
    require(isinstance(cells, list) and len(cells) == 1 and isinstance(cells[0], dict), "missing-idle-cells")
    for key, expected in (("total", 2), ("available", 2), ("active", 0), ("quarantined", 0), ("queueDepth", 0)):
        number(cells[0].get(key), expected, expected)
    topology = inventory.get("topology")
    require(isinstance(topology, dict) and topology.get("available") is True
            and isinstance(topology.get("entries"), list) and 0 < len(topology["entries"]) <= 32,
            "missing-idle-topology")
    for entry in topology["entries"]:
        require(isinstance(entry, dict), "invalid-idle-topology-row")
        if entry.get("ownership") in ("activation-scoped", "service-resident"):
            require(uint(entry.get("activeCount")) == 0, "live-idle-owner")
        if entry.get("ownership") == "service-resident":
            require(uint(entry.get("configuredCount")) == 0, "service-resident-owner")


def verify_fuel(observations: Any, report: dict[str, Any]) -> None:
    fields(observations, "response status fuelGrant idleSample")
    require(uint(observations["fuelGrant"]) == 50_000, "invalid-fuel-witness-grant")
    response = invocation_failure(observations["response"], "fuel-exhausted", "resource-exhausted", "resource_exhausted")
    spent = cli_consumption(response["consumption"])
    require(0 < spent["cpuFuel"] <= 50_000 and spent["peakMemoryBytes"] > 0, "missing-positive-fuel-exhaustion")
    terminal_status(observations["status"], "fuel-exhausted", "resource_exhausted", response["consumption"])
    idle_sample(observations["idleSample"], report, "fuel-settled")


def full_queue(inventory: Any) -> None:
    require(isinstance(inventory, dict), "missing-full-queue-inventory")
    cells = inventory.get("cellCapacity")
    require(isinstance(cells, list) and len(cells) == 1 and isinstance(cells[0], dict), "missing-full-queue-cells")
    for key, expected in (("total", 2), ("active", 2), ("available", 0), ("queueDepth", 3), ("queuedTenants", 2)):
        number(cells[0].get(key), expected, expected)
    require(uint(inventory.get("queueDepth")) == 3, "invalid-full-queue-depth")
    require(isinstance(inventory.get("quotas"), dict) and isinstance(inventory["quotas"].get("usage"), dict),
            "missing-full-queue-quota")
    number(inventory["quotas"]["usage"].get("activeActivations"), 5, 5)
    number(inventory["quotas"]["usage"].get("queuedActivations"), 3, 3)


def verify_fair_queue(observations: Any, report: dict[str, Any]) -> None:
    fields(observations, "holdersRunning queued full overflow overflowStatus unchangedFull firstHandoff secondHandoff cancelled holderResults queuedResults queuedStatuses idleSample fairnessOracle overflowBoundary")
    require(observations["fairnessOracle"] == "other-tenant-completes-before-uncancelled-same-tenant-spin"
            and observations["overflowBoundary"] == "standalone-active-owner-ceiling-before-extra-journal-registration",
            "invalid-fairness-witness")
    holders = ("queue-holder-first", "queue-holder-second")
    queued = ("queued-tests-first", "queued-tests-second", "queued-examples")
    for key, identifiers, phase in (("holdersRunning", holders, "running"), ("queued", queued, "queued")):
        rows = observations[key]
        require(isinstance(rows, list) and len(rows) == len(identifiers), "missing-queue-owners")
        for row, identifier in zip(rows, identifiers):
            phase_status(row, identifier, phase)
    full_queue(observations["full"])
    full_queue(observations["unchangedFull"])
    overflow = observations["overflow"]
    fields(overflow, "schemaVersion command category data error requestDispatched outcomeKnown")
    require(overflow["schemaVersion"] == "latent.cli.result.v1" and overflow["command"] == "invoke"
            and overflow["category"] == "transport-failure" and overflow["requestDispatched"] is True
            and overflow["outcomeKnown"] is False and isinstance(overflow["error"], dict)
            and overflow["error"].get("grpcCode") == "resource-exhausted", "missing-queue-overflow-rejection")
    absent = observations["overflowStatus"]
    fields(absent, "schemaVersion command category data error requestDispatched outcomeKnown")
    require(absent["schemaVersion"] == "latent.cli.result.v1" and absent["command"] == "activation get"
            and absent["category"] == "not-found" and absent["requestDispatched"] is True
            and absent["outcomeKnown"] is True, "missing-overflow-status-proof")
    phase_status(observations["firstHandoff"], queued[0], "running")
    handoff = fields(observations["secondHandoff"], "examplesResult secondHolderRunning secondQueuedRunning")
    phase_status(handoff["secondHolderRunning"], holders[1], "running")
    phase_status(handoff["secondQueuedRunning"], queued[1], "running")
    cancellations = observations["cancelled"]
    require(isinstance(cancellations, list) and len(cancellations) == 4, "missing-accepted-cancellations")
    for row, identifier in zip(cancellations, (holders[0], queued[0], queued[1], holders[1])):
        data = cli_data(row, "activation cancel", "success")
        require(data.get("activationId") == identifier and data.get("disposition") == "accepted"
                and data.get("terminalState") is None, "queue-owner-expired-before-cancellation")
    results, statuses = observations["queuedResults"], observations["queuedStatuses"]
    require(isinstance(results, list) and len(results) == 3 and isinstance(statuses, list) and len(statuses) == 3,
            "missing-queue-terminal-evidence")
    for index, (row, status, identifier) in enumerate(zip(results, statuses, queued)):
        if index < 2:
            data = invocation_failure(row, identifier, "cancelled", "cancelled")
        else:
            data = cli_data(row, "invoke", "success")
            require(data.get("activationId") == identifier and cli_payload(data.get("payload")) == [{"ok": "queued other tenant"}],
                    "wrong-other-tenant-result")
            require(canonical_json(row) == canonical_json(handoff["examplesResult"]), "changed-fairness-result")
        terminal_status(status, identifier, "cancelled" if index < 2 else "completed", data.get("consumption"))
    holder_results = observations["holderResults"]
    require(isinstance(holder_results, list) and len(holder_results) == 2, "missing-holder-results")
    for row, identifier in zip(holder_results, holders):
        invocation_failure(row, identifier, "cancelled", "cancelled")
    idle_sample(observations["idleSample"], report, "queue-settled")


def verify_fresh(observations: Any, report: dict[str, Any]) -> None:
    fields(observations, "responses sample")
    rows = observations["responses"]
    require(isinstance(rows, list) and len(rows) == 4, "missing-reused-cell-witness")
    cells = []
    for index, (row, activation_id) in enumerate(zip(rows, ("warmup", "fresh-first", "fresh-second", "fresh-third"))):
        data = cli_data(row, "invoke", "success")
        require(data.get("activationId") == activation_id and cli_payload(data.get("payload")) == [11 if index == 0 else 1],
                "guest-state-not-fresh")
        require(isinstance(data.get("metadata"), dict), "missing-fresh-cell-identity")
        cells.append(text(data["metadata"].get("cell-id"), 512))
        cli_consumption(data.get("consumption"))
    require(cells[1] == cells[3] and cells[1] != cells[2], "missing-actual-cell-reuse")
    idle_sample(observations["sample"], report, "warm")


def wall_observation(value: Any, activation_id: str, ceiling: int, absolute: int | None = None) -> None:
    fields(value, "response status decoded beforeUnixMillis afterUnixMillis effectiveDeadlineUnixMillis remainingMillis requestedWallMillis clockResolutionMillis")
    before, after = uint(value["beforeUnixMillis"]), uint(value["afterUnixMillis"])
    effective, remaining = uint(value["effectiveDeadlineUnixMillis"]), uint(value["remainingMillis"])
    require(before > 0 and after >= before and effective > before and 0 < remaining <= ceiling
            and uint(value["requestedWallMillis"]) == 5000 and uint(value["clockResolutionMillis"]) == 1,
            "invalid-relative-wall-observation")
    if absolute is None:
        require(before + ceiling - 1 <= effective <= after + ceiling + 1, "aged-relative-ceiling-became-deadline")
    else:
        require(effective == absolute and 0 < absolute - before < 1000, "caller-deadline-not-preserved")
    data = cli_data(value["response"], "invoke", "success")
    require(data.get("activationId") == activation_id, "wrong-wall-activation")
    decoded = cli_payload(data.get("payload"))
    require(canonical_json(decoded) == canonical_json(value["decoded"])
            and isinstance(decoded, list) and len(decoded) == 1 and isinstance(decoded[0], dict),
            "wall-payload-mismatch")
    snapshot = decoded[0]
    require(snapshot.get("activation") == activation_id and snapshot.get("deadline") == {"some": str(effective)}
            and isinstance(snapshot.get("remaining"), dict)
            and snapshot["remaining"].get("wall-time-limit-millis") == {"some": str(remaining)},
            "wall-context-mismatch")
    terminal_status(value["status"], activation_id, "completed", data.get("consumption"))


def wall_deployment(value: Any, command: str, ceiling: int | None) -> dict[str, Any]:
    data = cli_data(value, command, "success")
    deployment = fields(data.get("deployment"), "manifest generation")
    require(uint(deployment["generation"]) > 0 and isinstance(deployment["manifest"], dict), "invalid-wall-deployment")
    manifest = deployment["manifest"]
    require(isinstance(manifest.get("metadata"), dict) and manifest["metadata"].get("name") == "capabilities"
            and manifest["metadata"].get("tenant") == "tests" and isinstance(manifest.get("spec"), dict)
            and isinstance(manifest["spec"].get("resources"), dict)
            and manifest["spec"]["resources"].get("wallTimeLimitMillis") == ceiling, "wrong-persisted-relative-ceiling")
    return deployment


def verify_wall(observations: Any, report: dict[str, Any]) -> None:
    fields(observations, "nodeCeiling deploymentCeiling callerDeadline restored idleSample")
    node = fields(observations["nodeCeiling"], "ceilingMillis nodeAgeMillis observation scope")
    require(uint(node["ceilingMillis"]) == 5000 and uint(node["nodeAgeMillis"]) > 5000
            and node["scope"] == "configured-standalone-transport-and-admission", "missing-aged-node-ceiling")
    wall_observation(node["observation"], "wall-node-aged", 5000)
    deployment = fields(observations["deploymentCeiling"],
                        "ceilingMillis agedMillis committedUnixMillis original applied persistedBefore observation persistedAfter")
    require(isinstance(deployment["observation"], dict), "missing-deployment-wall-observation")
    require(uint(deployment["ceilingMillis"]) == 1000 and uint(deployment["agedMillis"]) > 1000
            and uint(deployment["observation"].get("beforeUnixMillis")) > uint(deployment["committedUnixMillis"]) + 1000,
            "missing-aged-deployment-ceiling")
    original = wall_deployment(deployment["original"], "deployment get", None)
    applied = wall_deployment(deployment["applied"], "deployment apply", 1000)
    before = wall_deployment(deployment["persistedBefore"], "deployment get", 1000)
    after = wall_deployment(deployment["persistedAfter"], "deployment get", 1000)
    require(canonical_json(applied) == canonical_json(before) == canonical_json(after)
            and uint(applied["generation"]) > uint(original["generation"]), "persistent-ceiling-mutated-by-invocation")
    wall_observation(deployment["observation"], "wall-deployment-aged", 1000)
    caller = fields(observations["callerDeadline"], "absoluteUnixMillis observation")
    wall_observation(caller["observation"], "wall-caller-earlier", 500, uint(caller["absoluteUnixMillis"]))
    restored = wall_deployment(observations["restored"], "deployment apply", None)
    require(canonical_json(restored["manifest"]) == canonical_json(original["manifest"])
            and uint(restored["generation"]) > uint(applied["generation"]), "relative-ceiling-not-restored")
    idle_sample(observations["idleSample"], report, "wall-ceilings-settled")


def verify_adapter_config(config: Any) -> None:
    fields(config, "formatVersion dataDirectory nodeId bind workers cells execution shutdownGraceMillis")
    require(config["formatVersion"] == 1 and type(config["formatVersion"]) is int
            and config["nodeId"] == "phase1-adapter-parity" and config["dataDirectory"] == "data"
            and config["bind"] == "127.0.0.1:0", "invalid-adapter-node-config")
    workers = fields(config["workers"], "runtime control")
    number(workers["runtime"], 1, 1)
    number(workers["control"], 1, 1)
    require(isinstance(config["cells"], list) and len(config["cells"]) == 1, "adapter-cell-bound")
    cell = fields(config["cells"][0], "class capacity queueCapacity maximumMemoryBytes")
    require(cell["class"] == "standard", "adapter-cell-class")
    number(cell["capacity"], 1, 1)
    number(cell["queueCapacity"], 2, 1)
    # The selected capability pairs actually receive these full grants. A
    # smaller reported node ceiling cannot describe their execution honestly.
    number(cell["maximumMemoryBytes"], 64 * 1024 * 1024, 64 * 1024 * 1024)
    execution = fields(config["execution"], "maximumCpuFuel maximumWallTimeMillis maximumLogBytes")
    number(execution["maximumCpuFuel"], 100_000_000, 100_000_000)
    number(execution["maximumWallTimeMillis"], 5000, 4000)
    number(execution["maximumLogBytes"], 16384, 16384)
    number(config["shutdownGraceMillis"], 500, 1)


def parity_consumption(value: Any) -> dict[str, int]:
    fields(value, "cpu_fuel peak_memory_bytes wall_time_micros log_bytes child_calls outbound_requests state_read_bytes state_write_bytes blob_read_bytes blob_write_bytes effect_count")
    result = {key: uint(item) for key, item in value.items()}
    require(0 < result["cpu_fuel"] <= 100_000_000 and 0 < result["peak_memory_bytes"] <= 67_108_864
            and result["log_bytes"] <= 16384 and result["wall_time_micros"] <= 4_500_000,
            "capability-consumption-bound")
    require(all(result[key] == 0 for key in result if key not in ("cpu_fuel", "peak_memory_bytes", "log_bytes", "wall_time_micros")),
            "unexpected-later-phase-consumption")
    return result


def parity_trace(value: Any) -> None:
    fields(value, "trace_id span_id trace_flags baggage")
    for key, width in (("trace_id", 32), ("span_id", 16)):
        require(isinstance(value[key], str) and re.fullmatch(f"[0-9a-fA-F]{{{width}}}", value[key]) is not None,
                "invalid-observed-trace")
    number(value["trace_flags"], 255)
    require(value["baggage"] == {}, "private-trace-baggage")


def telemetry_correlation(call: Any, tenant: str, activation: str, expected_logs: int) -> None:
    require(call["activation_id"] == activation and call["tenant"] == tenant and call["service"] == "shared",
            "wrong-telemetry-tenant-owner")
    root, parent = (("parity-root", "parity-parent") if tenant == "examples" else ("capability-root", "capability-parent"))
    require(call["root_activation_id"] == root and call["parent_activation_id"] == parent, "wrong-telemetry-lineage")
    digest(call["release_digest"])
    text(call["revision_id"], 512)
    require(uint(call["route_generation"]) > 0, "missing-telemetry-pin")
    correlation = {"activation_id": activation, "root_activation_id": root, "parent_activation_id": parent,
                   "tenant": tenant, "service": "shared", "release": call["release_digest"],
                   "revision": call["revision_id"], "route_generation": call["route_generation"]}
    correlation["contract"] = "examples:echo/api@0.1.0" if tenant == "examples" else "tests:capabilities/api@0.1.0"
    correlation["function"] = "echo" if tenant == "examples" else activation.split("-cap-", 1)[-1]
    span = fields(call["completion_span"], "name status attributes trace started_at_unix_nanos ended_at_unix_nanos")
    require(span["name"] == "latent.activation" and span["status"] == "ok"
            and 0 < uint(span["started_at_unix_nanos"]) <= uint(span["ended_at_unix_nanos"]), "invalid-completion-span")
    parity_trace(span["trace"])
    logs = call["guest_logs"]
    require(isinstance(logs, list) and len(logs) == expected_logs, "missing-accepted-guest-logs")
    for row in [span, *logs]:
        attributes = row["attributes"] if isinstance(row, dict) and "attributes" in row else None
        require(isinstance(attributes, dict) and all(attributes.get(key) == item for key, item in correlation.items()),
                "telemetry-correlation-mismatch")
        require(not any(key.startswith("guest.") for key in attributes)
                and "private-context-marker" not in canonical_json(row).decode(), "private-telemetry-field")
    for log in logs:
        fields(log, "body attributes trace observed_at_unix_millis")
        require(log["body"] == "[REDACTED]" and uint(log["observed_at_unix_millis"]) > 0
                and canonical_json(log["trace"]) == canonical_json(span["trace"]), "guest-log-trace-mismatch")


def remaining_budget(value: Any) -> dict[str, int]:
    fields(value, "cpu-fuel memory-bytes wall-time-limit-millis child-calls outbound-requests state-read-bytes state-write-bytes blob-read-bytes blob-write-bytes log-bytes effect-count")
    result = {key: uint(value[key]) for key in ("cpu-fuel", "memory-bytes", "log-bytes",
              "state-read-bytes", "state-write-bytes", "blob-read-bytes", "blob-write-bytes")}
    require(result["cpu-fuel"] < 100_000_000 and result["memory-bytes"] < 67_108_864
            and result["log-bytes"] <= 16384, "remaining-budget-exceeds-grant")
    require(all(result[key] == 0 for key in ("state-read-bytes", "state-write-bytes", "blob-read-bytes", "blob-write-bytes")),
            "unexpected-later-phase-budget")
    for key in ("child-calls", "outbound-requests", "effect-count"):
        number(value[key], 0)
    wall = fields(value["wall-time-limit-millis"], "some")
    # Millisecond projection can be zero while the monotonic ledger still has
    # a positive sub-millisecond remainder. Terminal success is checked apart.
    require(uint(wall["some"]) <= 4000, "invalid-remaining-wall-budget")
    return result


def capability_call(call: Any, name: str, direct: bool, before: int, after: int) -> None:
    fields(call, "activation_id root_activation_id parent_activation_id tenant service release_digest revision_id route_generation completion_span guest_logs cell_id decoded consumption grant retained_status")
    identifier = ("direct" if direct else "remote") + "-cap-" + name
    telemetry_correlation(call, "tests", identifier, {"snapshot": 0, "work-observe": 1, "clocks": 2}[name])
    require(call["cell_id"] == "phase1-adapter-parity:phase0:standard:00000000", "capability-cell-not-reused")
    grant = fields(call["grant"], "cpu_fuel memory_bytes log_bytes wall_time_limit_millis")
    for key, expected in (("cpu_fuel", 100_000_000), ("memory_bytes", 67_108_864), ("log_bytes", 16384), ("wall_time_limit_millis", 4000)):
        require(uint(grant[key]) == expected, "wrong-capability-grant")
    used = parity_consumption(call["consumption"])
    status = fields(call["retained_status"], "activation_id phase terminal_state final_consumption terminal_at_unix_millis last_updated_unix_millis metadata terminal_kind")
    require(status["activation_id"] == identifier and status["terminal_state"] == "completed" and status["terminal_kind"] == "success"
            and 0 < uint(status["terminal_at_unix_millis"]) == uint(status["last_updated_unix_millis"]),
            "capability-retained-status-mismatch")
    text(status["phase"], 64)
    require(isinstance(status["metadata"], dict)
            and canonical_json(status["final_consumption"]) == canonical_json(call["consumption"]), "capability-retained-accounting-mismatch")
    require(all(status["metadata"].get(key) == call[field] for key, field in
                (("release", "release_digest"), ("revision", "revision_id"), ("route-generation", "route_generation"))),
            "capability-retained-pin-mismatch")
    for attribute, field in (("cpu_fuel", "cpu_fuel"), ("memory_bytes", "peak_memory_bytes"),
                             ("wall_time_micros", "wall_time_micros"), ("log_bytes", "log_bytes")):
        require(call["completion_span"]["attributes"].get(attribute) == call["consumption"][field], "span-accounting-mismatch")
    decoded = call["decoded"]
    require(isinstance(decoded, list) and len(decoded) == 1 and "private-context-marker" not in canonical_json(decoded).decode(),
            "invalid-capability-result")
    output = decoded[0]
    if name == "snapshot":
        fields(output, "activation root parent principal trace deadline metadata remaining")
        require(output["activation"] == identifier and output["root"] == "capability-root"
                and output["parent"] == {"some": "capability-parent"} and output["metadata"] == [["guest.visible", "paired"]],
                "capability-context-owner-mismatch")
        principal = fields(output["principal"], "subject kind tenant service claims")
        require(principal["subject"] == "parity-tests" and principal["tenant"] == {"some": "tests"}
                and principal["claims"] == [] and principal["kind"] == "administrator"
                and principal["service"] == {"none": None}, "capability-principal-mismatch")
        observed = call["completion_span"]["trace"]
        require(output["trace"] == {"trace-id": observed["trace_id"], "span-id": observed["span_id"],
                                     "trace-flags": observed["trace_flags"], "baggage": []}, "guest-context-trace-mismatch")
        deadline = uint(fields(output["deadline"], "some")["some"])
        require(before + 4000 <= deadline <= after + 4000, "capability-deadline-mismatch")
        remaining = remaining_budget(output["remaining"])
        require(remaining["log-bytes"] == 16384 and used["log_bytes"] == 0, "snapshot-log-accounting-mismatch")
    elif name == "work-observe":
        fields(output, "before after logged checksum")
        require(type(output["checksum"]) is int and output["checksum"] == 1024 and output["logged"] == {"ok": True},
                "missing-bounded-guest-work")
        first, last = remaining_budget(output["before"]), remaining_budget(output["after"])
        require(all(last[key] < first[key] for key in ("cpu-fuel", "memory-bytes", "log-bytes")), "missing-live-budget-delta")
        require(first["log-bytes"] == 16384 and used["log_bytes"] == 16384 - last["log-bytes"]
                and used["cpu_fuel"] >= 100_000_000 - last["cpu-fuel"]
                and used["peak_memory_bytes"] >= 67_108_864 - last["memory-bytes"], "live-budget-accounting-mismatch")
    else:
        require(isinstance(output, list) and len(output) == 3 and used["log_bytes"] > 0, "missing-clock-readings")
        previous = 0
        for reading in output:
            fields(reading, "wall monotonic")
            require(uint(reading["wall"]) > 0 and uint(reading["monotonic"]) >= previous, "nonmonotonic-guest-clock")
            previous = uint(reading["monotonic"])


def verify_published_inputs(observations: Any, report: dict[str, Any], root: Path) -> dict[str, str]:
    rows = observations["published_inputs"]
    require(isinstance(rows, list) and len(rows) == 2, "missing-published-parity-inputs")
    releases = {}
    for row, name, tenant in zip(rows, ("echo", "capabilities"), ("examples", "tests")):
        fields(row, "tenant service component_sha256 manifest contracts deployment")
        source = next(item for item in report["identity"]["fixtures"] if item["name"] == name)
        require(row["tenant"] == tenant and row["service"] == "shared" and row["component_sha256"] == source["sha256"],
                "published-parity-source-mismatch")
        releases[tenant] = row["component_sha256"]
        documents = {}
        for kind in ("manifest", "contracts", "deployment"):
            reference = fields(row[kind], "path sha256 bytes")
            require(reference["path"] == f"adapter-inputs/{name}-{kind}.json" and reference in report["artifacts"],
                    "missing-transmitted-parity-artifact")
            documents[kind] = verified_json_artifact(report, root, reference["path"], 1024 * 1024)
        manifest, deployment, contracts = (documents[key] for key in ("manifest", "deployment", "contracts"))
        require(isinstance(manifest, dict) and isinstance(deployment, dict) and isinstance(contracts, dict), "invalid-published-parity-document")
        require(isinstance(manifest.get("metadata"), dict) and manifest["metadata"].get("tenant") == tenant
                and manifest["metadata"].get("name") == "shared" and isinstance(manifest.get("component"), dict)
                and manifest["component"].get("digest") == releases[tenant], "published-manifest-scope-mismatch")
        require(isinstance(deployment.get("metadata"), dict) and deployment["metadata"].get("tenant") == tenant
                and isinstance(deployment.get("spec"), dict) and deployment["spec"].get("service") == "shared"
                and deployment["spec"].get("release") == releases[tenant], "published-deployment-scope-mismatch")
        require(type(contracts.get("format_version")) is int and contracts["format_version"] == 1
                and isinstance(contracts.get("contracts"), list) and 0 < len(contracts["contracts"]) <= 16,
                "invalid-published-contract-metadata")
        expected_package = "examples:echo" if name == "echo" else "tests:capabilities"
        expected_contract = expected_package + "/api@0.1.0"
        require(manifest.get("exports") == [expected_contract] and len(contracts["contracts"]) == 1
                and isinstance(contracts["contracts"][0], dict)
                and contracts["contracts"][0].get("id") == expected_contract
                and contracts["contracts"][0].get("package_name") == expected_package,
                "published-contract-export-mismatch")
    require(releases["examples"] != releases["tests"], "tenant-release-not-isolated")
    return releases


def verify_capability_parity(observations: Any, releases: dict[str, str]) -> None:
    rows = observations["capability_pairs"]
    require(isinstance(rows, list) and len(rows) == 3, "missing-capability-parity-pairs")
    traces = set()
    for row, name in zip(rows, ("snapshot", "work-observe", "clocks")):
        fields(row, "name direct rpc observed_before_unix_millis observed_after_unix_millis")
        require(row["name"] == name, "invalid-capability-pair-order")
        before, after = uint(row["observed_before_unix_millis"]), uint(row["observed_after_unix_millis"])
        require(0 < before <= after, "invalid-capability-pair-window")
        for side in ("direct", "rpc"):
            capability_call(row[side], name, side == "direct", before, after)
            require(row[side]["release_digest"] == releases["tests"], "capability-release-mismatch")
            observed_trace = row[side]["completion_span"]["trace"]["trace_id"]
            require(observed_trace not in traces, "activation-trace-reused")
            traces.add(observed_trace)
        for key in ("revision_id", "route_generation", "cell_id"):
            require(row["direct"][key] == row["rpc"][key], "capability-pair-pin-mismatch")
        for key in ("peak_memory_bytes", "log_bytes"):
            require(row["direct"]["consumption"][key] == row["rpc"]["consumption"][key], "capability-pair-accounting-mismatch")
    tenant_rows = observations["tenant_telemetry"]
    require(isinstance(tenant_rows, list) and len(tenant_rows) == 2, "missing-tenant-telemetry")
    echo = fields(tenant_rows[0], "activation_id root_activation_id parent_activation_id tenant service release_digest revision_id route_generation completion_span guest_logs")
    telemetry_correlation(echo, "examples", "remote-0", 1)
    require(echo["release_digest"] == releases["examples"] and echo["completion_span"]["trace"]["trace_id"] not in traces,
            "cross-tenant-telemetry-identity")
    success = observations["pairs"][0] if isinstance(observations["pairs"], list) and observations["pairs"] else None
    require(isinstance(success, dict), "missing-echo-success-pair")
    for attribute, field in (("cpu_fuel", "cpu_fuel"), ("memory_bytes", "peak_memory_bytes"), ("log_bytes", "log_bytes")):
        require(echo["completion_span"]["attributes"].get(attribute) == success.get(field), "echo-span-accounting-mismatch")
    require(canonical_json(tenant_rows[1]) == canonical_json(rows[1]["rpc"]), "tenant-telemetry-call-mismatch")


def verify_parity(observations: Any, report: dict[str, Any], root: Path) -> None:
    identity = report["identity"]
    fields(observations, "pairs capability_pairs tenant_telemetry published_inputs shutdown node_starts public_config config_sha256 inputs comparison variable_fields scope retained_metric_points inventory_cache_entries")
    require(uint(observations["node_starts"]) == 1, "adapter-node-start-bound")
    require(uint(observations["retained_metric_points"]) <= 1024, "adapter-metric-retention-bound")
    require(uint(observations["inventory_cache_entries"]) == 2, "adapter-cache-entry-count")
    verify_config_digest(observations["public_config"], observations["config_sha256"])
    verify_adapter_config(observations["public_config"])
    releases = verify_published_inputs(observations, report, root)
    verify_capability_parity(observations, releases)
    verify_shutdown(observations["shutdown"], cells=observations["public_config"]["cells"][0]["capacity"])
    text(observations["comparison"], 1024)
    text(observations["scope"], 1024)
    require(isinstance(observations["variable_fields"], list) and len(observations["variable_fields"]) <= 8,
            "invalid-parity-variable-fields")
    for field in observations["variable_fields"]:
        text(field, 128)
    rows = observations["pairs"]
    require(isinstance(rows, list) and len(rows) == len(PARITY_PAIRS), "missing-parity-pairs")
    for index, (row, name) in enumerate(zip(rows, PARITY_PAIRS)):
        require(isinstance(row, dict) and row.get("name") == name, "invalid-parity-pair-order")
        if index in (3, 7):
            fields(row, "name classification code")
            require(row["classification"] == "rpc-rejection"
                    and row["code"] == ("DeadlineExceeded" if index == 3 else "PermissionDenied"),
                    "invalid-parity-rejection")
        else:
            fields(row, "name classification cpu_fuel peak_memory_bytes log_bytes receipt_pin_equal")
            expected = "success" if index == 0 else "declared-error" if index == 1 else "platform-failure"
            require(row["classification"] == expected and row["receipt_pin_equal"] is True,
                    "invalid-parity-classification")
            require(uint(row["cpu_fuel"]) <= 1_000_000 and uint(row["peak_memory_bytes"]) <= 4 * 1024 * 1024
                    and uint(row["log_bytes"]) <= 16384, "parity-consumption-bound")
    inputs = observations["inputs"]
    require(isinstance(inputs, list) and len(inputs) == len(PARITY_INPUTS), "missing-parity-input")
    echo = next(item for item in identity["fixtures"] if item["name"] == "echo")
    for index, (item, name) in enumerate(zip(inputs, PARITY_INPUTS)):
        fields(item, "name sha256 bytes")
        require(item["name"] == name, "invalid-parity-input-order")
        digest(item["sha256"])
        require(0 < uint(item["bytes"]) <= (16 * 1024 * 1024 if index == 0 else 64 * 1024), "parity-input-byte-limit")
        if index == 0:
            require(item["sha256"] == echo["sha256"] and item["bytes"] == echo["bytes"], "parity-fixture-mismatch")


def verify_cases(report: dict[str, Any], manifest: dict[str, Any], artifacts: set[str], root: Path) -> None:
    entries = report["cases"]
    require(isinstance(entries, list), "invalid-cases")
    found: dict[str, tuple[int, int]] = {}
    for entry in entries:
        fields(entry, "id status reason work observations diagnostics")
        identifier = text(entry["id"], 128)
        require(identifier not in found, "duplicate-case")
        require(identifier in manifest["required_cases"], "unknown-case")
        require(entry["status"] == "passed" and entry["reason"] is None, "required-case-not-passed")
        require(isinstance(entry["observations"], dict) and bool(entry["observations"]), "missing-case-observations")
        require(isinstance(entry["diagnostics"], list) and 0 < len(entry["diagnostics"]) <= 32
                and all(isinstance(path, str) and path in artifacts for path in entry["diagnostics"]),
                "missing-case-diagnostics")
        found[identifier] = work(entry["work"])
        verify_case_artifact(entry, report, root)
        if identifier == "adapter-rpc-parity":
            verify_parity(entry["observations"], report, root)
        elif identifier == "fuel-budget":
            verify_fuel(entry["observations"], report)
        elif identifier == "queue-admission":
            verify_fair_queue(entry["observations"], report)
        elif identifier == "fresh-store":
            verify_fresh(entry["observations"], report)
        elif identifier == "persistent-wall-ceiling":
            verify_wall(entry["observations"], report)
    require(set(found) == set(manifest["required_cases"]), "missing-required-case")
    counts = work(report["work"])
    require(tuple(sum(item[index] for item in found.values()) for index in (0, 1)) == counts,
            "case-work-mismatch")
    drivers = report["drivers"]
    require(isinstance(drivers, list) and len(drivers) == 2, "missing-driver-work")
    driver_counts = {}
    for driver in drivers:
        fields(driver, "driver work")
        name = driver["driver"]
        require(name in ("process", "adapter") and name not in driver_counts, "invalid-driver-work")
        driver_counts[name] = work(driver["work"], *( (36, 192) if name == "process" else (28, 64) ))
    require(tuple(sum(item[index] for item in driver_counts.values()) for index in (0, 1)) == counts,
            "driver-work-mismatch")
    require(driver_counts["adapter"] == found["adapter-rpc-parity"], "adapter-work-mismatch")
    require(driver_counts["adapter"][1] == 22, "missing-parity-pairs")


def verify_samples(report: dict[str, Any]) -> None:
    samples = report["samples"]
    require(isinstance(samples, list) and 4 <= len(samples) <= 32, "missing-process-samples")
    identities: dict[int, tuple[int, int]] = {}
    last_phases: dict[int, int] = {}
    dormant_topology: dict[int, tuple[int, int, int]] = {}
    phases = set()
    previous = -1
    previous_finished = 0
    for sample in samples:
        fields(sample, "sequence sample_started_micros sample_finished_micros node_instance phase process inventory")
        sequence = uint(sample["sequence"])
        require(sequence > previous, "unordered-sample")
        previous = sequence
        started, finished = uint(sample["sample_started_micros"]), uint(sample["sample_finished_micros"])
        require(previous_finished <= started <= finished, "invalid-observation-window")
        previous_finished = finished
        node = number(sample["node_instance"], 3, 1)
        phase = sample["phase"]
        require(phase in ("empty", "dormant", "warm", "post-mixed", "pre-shutdown"), "invalid-sample-phase")
        ordinal = ("empty", "dormant", "warm", "post-mixed", "pre-shutdown").index(phase)
        require(ordinal > last_phases.get(node, -1), "unordered-sample-phase")
        last_phases[node] = ordinal
        phases.add(phase)
        process = fields(sample["process"], "identity process taskCount uniqueSocketCount listeningTcpSocketCount descendants sampleAttempts")
        identity = fields(process["identity"], "processId startTimeTicks")
        pair = (number(identity["processId"], minimum=1), uint(identity["startTimeTicks"]))
        require(pair[1] > 0 and (node not in identities or identities[node] == pair), "changed-child-identity")
        identities[node] = pair
        raw = fields(process["process"], "processId residentMemoryBytes threadCount openFileDescriptors socketCount")
        require(raw["processId"] == pair[0], "wrong-resource-pid")
        require(uint(raw["residentMemoryBytes"]) > 0 and uint(raw["threadCount"]) > 0
                and uint(raw["openFileDescriptors"]) > 0, "unavailable-required-measurement")
        sockets = uint(raw["socketCount"])
        unique = uint(process["uniqueSocketCount"])
        listening = uint(process["listeningTcpSocketCount"])
        require(0 < uint(process["taskCount"]) <= 256 and unique <= sockets <= uint(raw["openFileDescriptors"])
                and listening == 1 and listening <= unique, "invalid-child-topology")
        require(uint(process["taskCount"]) == uint(raw["threadCount"]), "incoherent-thread-count")
        require(process["descendants"] == [], "unexpected-child-descendants")
        topology = (1, uint(process["taskCount"]), listening)
        if phase == "empty":
            dormant_topology[node] = topology
        if phase == "dormant":
            require(node in dormant_topology and dormant_topology[node] == topology, "dormant-topology-growth")
        number(process["sampleAttempts"], 3, 1)
        require(isinstance(sample["inventory"], dict) and bool(sample["inventory"]), "missing-inventory-sample")
    require({"empty", "dormant", "warm", "post-mixed"} <= phases, "missing-required-sample-phase")
    shutdowns = report["shutdowns"]
    require(isinstance(shutdowns, list) and len(shutdowns) == len(identities), "missing-cleanup-evidence")
    seen = set()
    for shutdown in shutdowns:
        fields(shutdown, "node_instance process_id start_time_ticks exit_success reaped readers_joined report")
        node = number(shutdown["node_instance"], 3, 1)
        require(node not in seen and node in identities, "invalid-shutdown-owner")
        seen.add(node)
        require((number(shutdown["process_id"], minimum=1), uint(shutdown["start_time_ticks"])) == identities[node], "wrong-shutdown-identity")
        require(all(shutdown[key] is True for key in ("exit_success", "reaped", "readers_joined")), "unreaped-child")
        verify_shutdown(shutdown["report"])


def validate_report(report: Any, artifacts_root: Path, *, expected_source_commit: str | None = None,
                    expected_config_sha256: str | None = None) -> None:
    bounded_tree(report)
    fields(report, "schema profile case_manifest_sha256 identity environment public_config work drivers cases samples shutdowns artifacts deferred_evidence deterministic_status phase1_completion")
    require(report["schema"] == "latent.phase1.conformance.v1" and report["profile"] == "bounded-deterministic",
            "wrong-report-profile")
    require(report["deterministic_status"] == "passed" and report["phase1_completion"] == "incomplete",
            "invalid-completion-claim")
    manifest = load_bounded(MANIFEST, 65536)
    require(digest(report["case_manifest_sha256"]) == sha256(MANIFEST.read_bytes()), "changed-case-manifest")
    verify_identity(report["identity"])
    if expected_source_commit is not None:
        require(report["identity"]["source_commit"] == expected_source_commit, "source-identity-mismatch")
    if expected_config_sha256 is not None:
        require(report["identity"]["config_sha256"] == expected_config_sha256, "config-identity-mismatch")
    environment = report["environment"]
    require(isinstance(environment, dict), "missing-environment")
    for key in ("os", "kernel", "architecture", "rust_version", "wasmtime_version"):
        text(environment.get(key), 1024)
    require(environment["os"].lower() == "linux", "linux-evidence-required")
    verify_config_digest(report["public_config"], report["identity"]["config_sha256"])
    artifacts = verify_artifacts(report, artifacts_root)
    verify_samples(report)
    verify_cases(report, manifest, artifacts, artifacts_root)
    deferred = report["deferred_evidence"]
    require(isinstance(deferred, list) and len(deferred) == len(manifest["deferred_evidence"]), "missing-deferred-evidence")
    identifiers = set()
    for entry in deferred:
        fields(entry, "id status reason")
        text(entry["id"], 128)
        require(entry["id"] not in identifiers and entry["id"] in manifest["deferred_evidence"], "invalid-deferred-evidence")
        identifiers.add(entry["id"])
        # Earlier retained v1 runs recorded the authorization state at collection.
        # New runs describe the fixed profile boundary independently of permission.
        require(entry["status"] == "not_run" and entry["reason"] in
                {"outside-bounded-profile", "not-authorized-heavy-work"}, "evidence-outside-bounded-profile")


def file_digest(path: Path, maximum: int) -> tuple[str, int]:
    require(path.is_file(), "missing-identity-input")
    result = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while True:
            chunk = source.read(min(65536, maximum + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            require(total <= maximum, "identity-input-byte-limit")
            result.update(chunk)
    return "sha256:" + result.hexdigest(), total


def verify_input_files(identity: dict[str, Any], binaries: list[str], fixtures: list[str],
                       cargo_lock: Path | None) -> None:
    for key, arguments, ceiling in (("binaries", binaries, 1024 * 1024 * 1024),
                                    ("fixtures", fixtures, 16 * 1024 * 1024)):
        indexed = {entry["name"]: entry for entry in identity[key]}
        seen = set()
        require(len(arguments) <= 16, "identity-input-count-limit")
        for argument in arguments:
            name, separator, value = argument.partition("=")
            require(bool(separator) and name in indexed and name not in seen, "invalid-identity-input")
            seen.add(name)
            hashed, size = file_digest(Path(value), ceiling)
            require(indexed[name]["sha256"] == hashed and uint(indexed[name]["bytes"]) == size,
                    "input-identity-mismatch")
    if cargo_lock is not None:
        require(file_digest(cargo_lock, 4 * 1024 * 1024)[0] == identity["cargo_lock_sha256"], "lock-identity-mismatch")


def verify_adapter_input_files(report: dict[str, Any], fixtures: list[str]) -> None:
    echo = next((value.partition("=")[2] for value in fixtures if value.partition("=")[0] == "echo"), None)
    if echo is None:
        return
    case = next(entry for entry in report["cases"] if entry["id"] == "adapter-rpc-parity")
    for index, item in enumerate(case["observations"]["inputs"]):
        path = Path(echo) if index == 0 else Path(echo).parent / item["name"]
        actual, size = file_digest(path, 16 * 1024 * 1024 if index == 0 else 64 * 1024)
        require(item["sha256"] == actual and uint(item["bytes"]) == size, "adapter-input-identity-mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--expected-source-commit")
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--binary", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--fixture", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--cargo-lock", type=Path)
    args = parser.parse_args()
    try:
        report = load_bounded(args.report)
        validate_report(report, args.artifacts_root,
                        expected_source_commit=args.expected_source_commit,
                        expected_config_sha256=args.expected_config_sha256)
        verify_input_files(report["identity"], args.binary, args.fixture, args.cargo_lock)
        verify_adapter_input_files(report, args.fixture)
    except (ConformanceValidationError, OSError) as error:
        reason = str(error) if isinstance(error, ConformanceValidationError) else "evidence-io-error"
        print(f"Phase 1 bounded evidence rejected: {reason}", file=sys.stderr)
        return 1
    print("Phase 1 deterministic evidence passed; full Phase 1 completion remains incomplete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
