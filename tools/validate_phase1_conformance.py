#!/usr/bin/env python3
"""Verify a bounded deterministic report; this never approves the Phase 1 gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

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
           " clean quarantinedCells telemetryRetainedEntries telemetryFlushed epochHelperJoined")
    require(all(raw[key] is True for key in ("clean", "telemetryFlushed", "epochHelperJoined")), "unclean-shutdown")
    require(all(type(raw[key]) is int and raw[key] == 0 for key in ZERO_SHUTDOWN_FIELDS), "live-transient-owners")
    number(raw["quarantinedCells"], cells)
    number(raw["telemetryRetainedEntries"], 65536)


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
    number(cell["capacity"], 2, 1)
    number(cell["queueCapacity"], 2, 1)
    number(cell["maximumMemoryBytes"], 64 * 1024 * 1024, 1)
    execution = fields(config["execution"], "maximumCpuFuel maximumWallTimeMillis maximumLogBytes")
    number(execution["maximumCpuFuel"], 100_000_000, 1)
    number(execution["maximumWallTimeMillis"], 5000, 1)
    number(execution["maximumLogBytes"], 16384, 1)
    number(config["shutdownGraceMillis"], 500, 1)


def verify_parity(observations: Any, identity: dict[str, Any]) -> None:
    fields(observations, "pairs shutdown node_starts public_config config_sha256 inputs comparison variable_fields scope retained_metric_points inventory_cache_entries")
    require(uint(observations["node_starts"]) == 1, "adapter-node-start-bound")
    require(uint(observations["retained_metric_points"]) <= 1024, "adapter-metric-retention-bound")
    require(uint(observations["inventory_cache_entries"]) == 1, "adapter-cache-entry-count")
    verify_config_digest(observations["public_config"], observations["config_sha256"])
    verify_adapter_config(observations["public_config"])
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
            verify_parity(entry["observations"], report["identity"])
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
        driver_counts[name] = work(driver["work"], *( (48, 224) if name == "process" else (16, 32) ))
    require(tuple(sum(item[index] for item in driver_counts.values()) for index in (0, 1)) == counts,
            "driver-work-mismatch")
    require(driver_counts["adapter"] == found["adapter-rpc-parity"], "adapter-work-mismatch")
    require(driver_counts["adapter"][1] == 16, "missing-parity-pairs")


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
    verify_cases(report, manifest, artifacts, artifacts_root)
    verify_samples(report)
    deferred = report["deferred_evidence"]
    require(isinstance(deferred, list) and len(deferred) == len(manifest["deferred_evidence"]), "missing-deferred-evidence")
    identifiers = set()
    for entry in deferred:
        fields(entry, "id status reason")
        text(entry["id"], 128)
        require(entry["id"] not in identifiers and entry["id"] in manifest["deferred_evidence"], "invalid-deferred-evidence")
        identifiers.add(entry["id"])
        require(entry["status"] == "not_run" and entry["reason"] == "not-authorized-heavy-work", "unauthorized-heavy-evidence")


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
