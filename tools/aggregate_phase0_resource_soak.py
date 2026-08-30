#!/usr/bin/env python3
"""Capture and analyse native-Linux Phase 0 resource-soak evidence.

The Rust probe makes correctness and logical-resource checks after every
completed batch.  This helper refuses incomplete evidence, checks that three
or more independent processes are comparable, and analyses only post-warm-up
batch snapshots for a resource plateau.  It is intentionally an explicit
native-Linux command, never a shared CI performance gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, NoReturn

try:  # Support both ``python -m tools...`` and direct script execution.
    from . import aggregate_phase0_calibration as calibration_aggregate
    from .phase0_collector_identity import (
        CollectorIdentityError,
        require_native_collector_identity,
        verify_retained_native_collector,
    )
except ImportError:  # pragma: no cover - exercised by direct CLI invocation.
    import aggregate_phase0_calibration as calibration_aggregate
    from phase0_collector_identity import (  # type: ignore[no-redef]
        CollectorIdentityError,
        require_native_collector_identity,
        verify_retained_native_collector,
    )


RUN_SCHEMA = "latent.phase0.resource-soak.run.v1"
HOST_SCHEMA = "latent.phase0.resource-soak.host-observation.v1"
AGGREGATE_SCHEMA = "latent.phase0.resource-soak.aggregate.v1"
SOURCE_PROVENANCE_SCHEMA = "latent.phase0.resource-soak.source-provenance.v1"
LEGACY_CALIBRATION_SCHEMA = "latent.phase0.calibration.v1"
CALIBRATION_SCHEMA = "latent.phase0.calibration.v2"
SUPPORTED_CALIBRATION_SCHEMAS = frozenset(
    {LEGACY_CALIBRATION_SCHEMA, CALIBRATION_SCHEMA}
)
MINIMUM_RUNS = 3
ROBUST_OUTLIER_THRESHOLD = 3.5
EXPECTED_CHECKS = {
    "native_linux_process_resource_probes_are_available",
    "prepared_cache_is_fixed_and_bounded",
    "every_completed_batch_returns_logical_resources_to_zero",
    "fresh_store_outcomes_and_cause_specific_recovery_pass",
    "real_at_capacity_batches_reach_exact_pool_capacity",
    "real_bounded_queue_batches_reach_exact_pool_and_queue_capacity",
    "post_release_returns_all_logical_resources_to_zero",
    "runtime_shutdown_returns_to_process_baseline",
}
REQUIRED_SCENARIOS = {
    "success",
    "domain_error",
    "trap",
    "timeout",
    "cancellation",
    "memory_pressure",
    "recovery_after_domain_error",
    "recovery_after_trap",
    "recovery_after_timeout",
    "recovery_after_cancellation",
    "recovery_after_memory_pressure",
}
CALIBRATION_ENVIRONMENT_FIELDS = (
    "operating_system",
    "architecture",
    "cpu_model",
    "logical_cpu_count",
    "total_memory_bytes",
    "kernel",
    "rustc",
    "cargo",
    "rust_target",
    "build_profile",
    "wasmtime_version",
)
CALIBRATION_CONFIG_FIELDS = (
    "pool_capacity",
    "pool_queue_capacity",
    "runtime_workers",
    "fuel",
    "memory_bytes",
    "memory_pressure_bytes",
    "timeout_ms",
    "cancel_after_ms",
    "prepared_cache_enabled",
    "wasmtime_instance_allocator",
    "wasmtime_copy_on_write_images",
)
HOST_ENVIRONMENT_FIELDS = (
    "operating_system",
    "architecture",
    "cpu_model",
    "logical_cpu_count",
    "total_memory_bytes",
    "kernel",
)
MANDATORY_SOCKET_PROBE_FAILURES = (
    "cannot read /proc/net/tcp",
    "listening socket probe unavailable",
    "required listening-socket probe",
)
DURABLE_SOURCE_REF_PATTERN = re.compile(r"^refs/(?:heads|tags)/")
# The first archive predates these fields in EffectiveConfig. They are fixed
# harness bounds at its execution tree and are labelled as such in the report;
# newly captured raw documents retain them directly in config.
LEGACY_RETAINED_STATE_LIMITS = {
    "component_maximum_bytes": 64 * 1024 * 1024,
    "prepared_cache_maximum_entries": 1,
    "prepared_cache_maximum_bytes": 64 * 1024 * 1024,
    "invocation_log_maximum_entries": 64,
    "invocation_log_maximum_bytes": 64 * 1024,
    "retained_log_maximum_entries": 64,
    "retained_log_maximum_bytes": 64 * 1024,
}
# This immutable archive was collected before the soak binary serialized its
# retained-state bounds and pre-runtime snapshot.  It is the only historical
# source allowed to use the documented retained-state fallback.  Every other
# archive must retain those values directly in raw JSON.
KNOWN_LEGACY_SOAK_SOURCE = {
    "published_commit": "6250b9782ffc4174676d2d72bd023dbfc38c39d7",
    "published_tree": "65ba341221ea89e107a3e0e3c4b0aed7e26efd9b",
}
# These immutable pre-provenance archives remain independently revalidatable,
# but they can never pass the current authorization gate.  Any other source
# record is newly collected evidence and must retain the durable origin-ref
# receipt emitted by the runner before measurement.
KNOWN_PRE_PROVENANCE_SOAK_SOURCES = frozenset(
    {
        (
            "6250b9782ffc4174676d2d72bd023dbfc38c39d7",
            "65ba341221ea89e107a3e0e3c4b0aed7e26efd9b",
        ),
        (
            "6a64f0630cee9afa080d33f376aabadac724fa72",
            "d27ff38ebbd891c5be949f54a0047522ed893d20",
        ),
        (
            "a724a5e35234175f1001d1983e4411296ffa6b78",
            "c06ace2ae0f503495fa5bf87710ae5fc74c7ef50",
        ),
    }
)


class SoakError(Exception):
    """Evidence is malformed, incomplete, or not comparable."""


def fail(message: str) -> NoReturn:
    raise SoakError(message)


def is_known_legacy_soak_source(identity: Any) -> bool:
    return isinstance(identity, dict) and all(
        identity.get(field) == value for field, value in KNOWN_LEGACY_SOAK_SOURCE.items()
    )


def is_pre_provenance_soak_source(identity: Any) -> bool:
    return (
        isinstance(identity, dict)
        and (
            identity.get("published_commit"),
            identity.get("published_tree"),
        )
        in KNOWN_PRE_PROVENANCE_SOAK_SOURCES
    )


def has_recorded_retained_state_limits(config: dict[str, Any]) -> bool:
    return all(
        isinstance(config.get(field), int) and not isinstance(config.get(field), bool)
        and config[field] > 0
        for field in LEGACY_RETAINED_STATE_LIMITS
    )


def retained_state_limit_source(document: dict[str, Any], label: str) -> str:
    config = document.get("config")
    if not isinstance(config, dict):
        fail(f"{label} config is malformed")
    if has_recorded_retained_state_limits(config):
        return "recorded"
    if is_known_legacy_soak_source(document.get("source_identity")):
        return "known_legacy"
    missing = [
        field
        for field in LEGACY_RETAINED_STATE_LIMITS
        if (
            not isinstance(config.get(field), int)
            or isinstance(config.get(field), bool)
            or config[field] <= 0
        )
    ]
    fail(
        f"{label} lacks recorded retained-state numeric limits ({', '.join(missing)}); "
        "only the known 6250b978/65ba3412 historical archive may use the legacy fallback"
    )


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def command_output(arguments: list[str]) -> str:
    try:
        completed = subprocess.run(
            arguments,
            check=False,
            text=True,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"unavailable ({error})"
    stdout = completed.stdout.strip()
    if stdout:
        return stdout
    return "none" if completed.returncode in (0, 1) else "unavailable"


def parse_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    contents = read_text(Path("/proc/meminfo"))
    if contents is None:
        return values
    for line in contents.splitlines():
        match = re.match(r"^([^:]+):\s+(\d+)\s+kB$", line)
        if match:
            values[match.group(1)] = int(match.group(2)) * 1024
    return values


def parse_loadavg() -> dict[str, Any]:
    contents = read_text(Path("/proc/loadavg"))
    if contents is None:
        return {"available": False}
    fields = contents.split()
    if len(fields) < 4:
        return {"available": False}
    runnable, _, total = fields[3].partition("/")
    return {
        "available": True,
        "one_minute": float(fields[0]),
        "five_minutes": float(fields[1]),
        "fifteen_minutes": float(fields[2]),
        "runnable_tasks": int(runnable),
        "total_tasks": int(total) if total.isdigit() else None,
    }


def allocator_observation(repository_root: Path) -> dict[str, Any]:
    """Capture allocator provenance without retaining sensitive environment values."""
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(repository_root),
                "grep",
                "-n",
                "global_allocator",
                "--",
                "*.rs",
            ],
            check=False,
            text=True,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        matches: list[str] = []
        lookup = "unavailable"
    else:
        matches = completed.stdout.splitlines() if completed.returncode == 0 else []
        lookup = "completed" if completed.returncode in (0, 1) else "unavailable"
    return {
        "source_global_allocator_lookup": lookup,
        "source_global_allocator_matches": matches,
        "ld_preload": (
            "set (value intentionally not recorded)" if os.environ.get("LD_PRELOAD") else "unset"
        ),
        "malloc_conf": (
            "set (value intentionally not recorded)" if os.environ.get("MALLOC_CONF") else "unset"
        ),
        "observation": (
            "When no source global allocator is found and LD_PRELOAD is unset, "
            "Rust uses its standard allocator backed by the platform allocator."
        ),
    }


def capture_host_observation(
    output: Path,
    phase: str,
    run_index: int,
    source_commit: str,
    source_tree: str,
    execution_commit: str,
    execution_tree: str,
    published_source_ref: str | None = None,
    published_source_ref_head: str | None = None,
) -> None:
    kernel_text = "\n".join(
        filter(
            None,
            [
                read_text(Path("/proc/sys/kernel/osrelease")),
                read_text(Path("/proc/version")),
            ],
        )
    ).lower()
    container = command_output(["systemd-detect-virt", "--container"])
    virtualization = command_output(["systemd-detect-virt"])
    virtual_machine = command_output(["systemd-detect-virt", "--vm"])
    memory = parse_meminfo()
    source_identity: dict[str, Any] = {
        "published_commit": source_commit,
        "published_tree": source_tree,
        "execution_commit": execution_commit,
        "execution_tree": execution_tree,
        "tree_identity_verified": execution_tree == source_tree,
    }
    if published_source_ref is not None or published_source_ref_head is not None:
        if published_source_ref is None or published_source_ref_head is None:
            fail("host capture requires both durable published source ref and ref head")
        source_identity.update(
            {
                "published_source_ref": published_source_ref,
                "published_source_ref_head": published_source_ref_head,
                "published_commit_reachable_from_ref": True,
                "execution_commit_matches_published": execution_commit == source_commit,
            }
        )
        durable_source_provenance(source_identity, "host capture")
    payload = {
        "schema_version": HOST_SCHEMA,
        "captured_at_utc": now_utc(),
        "phase": phase,
        "run_index": run_index,
        "source_identity": source_identity,
        "native_linux_reference": (
            platform.system() == "Linux"
            and "microsoft" not in kernel_text
            and "wsl" not in kernel_text
            and container == "none"
        ),
        "host": {
            "operating_system": platform.system().lower(),
            "architecture": platform.machine(),
            "kernel": command_output(["uname", "-srvmo"]),
            "cpu_model": cpu_model(),
            "logical_cpu_count": os.cpu_count(),
            "total_memory_bytes": memory.get("MemTotal"),
            "virtualization": {
                "systemd_detect_virt": virtualization,
                "systemd_detect_virt_container": container,
                "systemd_detect_virt_vm": virtual_machine,
                "wsl_detected": "microsoft" in kernel_text or "wsl" in kernel_text,
            },
        },
        "allocator": allocator_observation(Path.cwd()),
        "cpu_frequency_policy": calibration_aggregate.cpu_frequency_policy(),
        "background_load": {
            "load_average": parse_loadavg(),
            "memory_available_bytes": memory.get("MemAvailable"),
            "memory_free_bytes": memory.get("MemFree"),
            "swap_free_bytes": memory.get("SwapFree"),
            "notes": "Captured before and after every retained process; no run is removed because of these observations.",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cpu_model() -> str:
    contents = read_text(Path("/proc/cpuinfo"))
    if contents is None:
        return "unknown"
    for line in contents.splitlines():
        if line.startswith("model name\t: "):
            return line.removeprefix("model name\t: ")
        if line.startswith("Hardware\t: "):
            return line.removeprefix("Hardware\t: ")
    return "unknown"


def load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read JSON {path}: {error}")
    if not isinstance(document, dict):
        fail(f"JSON document {path} must be an object")
    return document


def value_at(document: dict[str, Any], dotted_path: str) -> Any:
    current: Any = document
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            fail(f"missing required field {dotted_path}")
        current = current[part]
    return current


def number_at(document: dict[str, Any], dotted_path: str) -> float:
    value = value_at(document, dotted_path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"required numeric field {dotted_path} is not numeric")
    return float(value)


def integer_at(document: dict[str, Any], dotted_path: str) -> int:
    value = value_at(document, dotted_path)
    if isinstance(value, bool) or not isinstance(value, int):
        fail(f"required integer field {dotted_path} is not an integer")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def valid_object_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{40}", value))


def valid_durable_source_ref(value: Any) -> bool:
    """Accept the durable branch/tag namespace and Git-safe ref characters."""

    if not isinstance(value, str) or DURABLE_SOURCE_REF_PATTERN.match(value) is None:
        return False
    suffix = value.removeprefix("refs/heads/")
    if suffix == value:
        suffix = value.removeprefix("refs/tags/")
    return bool(
        suffix
        and not suffix.startswith(("/", "."))
        and not suffix.endswith(("/", "."))
        and suffix != "@"
        and ".." not in suffix
        and "//" not in suffix
        and "@{" not in suffix
        and not any(character.isspace() or character in "~^:?*[\\" for character in suffix)
    )


def durable_source_provenance(
    identity: dict[str, Any], label: str
) -> dict[str, str] | None:
    """Return the origin-ref receipt for new evidence, preserving old archives.

    Historical archives predate durable-ref recording and are retained
    verbatim. Any newly recorded provenance must be complete and internally
    consistent; a partial ref receipt is invalid evidence rather than a
    calibration caveat.
    """

    fields = (
        "published_source_ref",
        "published_source_ref_head",
        "published_commit_reachable_from_ref",
        "execution_commit_matches_published",
    )
    present = [field in identity for field in fields]
    if not any(present):
        return None
    if not all(present):
        fail(f"{label} has incomplete durable source provenance")
    source_ref = identity.get("published_source_ref")
    source_ref_head = identity.get("published_source_ref_head")
    if (
        not valid_durable_source_ref(source_ref)
        or not valid_object_id(source_ref_head)
        or identity.get("published_commit_reachable_from_ref") is not True
        or identity.get("execution_commit_matches_published") is not True
    ):
        fail(f"{label} has malformed durable source provenance")
    return {
        "published_source_ref": source_ref,
        "published_source_ref_head": source_ref_head,
        "published_commit_reachable_from_ref": True,
        "execution_commit_matches_published": True,
    }


def hard_checks(document: dict[str, Any], label: str) -> set[str]:
    checks = document.get("checks")
    if not isinstance(checks, list) or not checks:
        fail(f"{label} has no hard invariant checks")
    names: set[str] = set()
    failed: list[str] = []
    for index, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            fail(f"{label} hard invariant {index} is malformed")
        name = check.get("name")
        if not isinstance(name, str) or not name:
            fail(f"{label} hard invariant {index} has no name")
        if name in names:
            fail(f"{label} has duplicate hard invariant {name}")
        names.add(name)
        if check.get("passed") is not True:
            failed.append(name)
    if names != EXPECTED_CHECKS:
        missing = sorted(EXPECTED_CHECKS - names)
        unexpected = sorted(names - EXPECTED_CHECKS)
        fail(
            f"{label} hard invariant set differs from the canonical soak set; "
            f"missing: {', '.join(missing) or 'none'}; unexpected: {', '.join(unexpected) or 'none'}"
        )
    if failed:
        fail(f"{label} has failed hard invariants: {', '.join(failed)}")
    return names


def pool_is_clean(pool: dict[str, Any], expected_capacity: int) -> bool:
    return (
        pool.get("capacity") == expected_capacity
        and pool.get("available") == expected_capacity
        and pool.get("queue_depth") == 0
        and pool.get("active_leases") == 0
        and pool.get("quarantined") == 0
    )


def logical_resources_are_clean(sample: dict[str, Any], expected_capacity: int) -> bool:
    pool = sample.get("pool")
    runner = sample.get("runner")
    backend = sample.get("backend_resources")
    timing = sample.get("backend_timing_store")
    if not all(isinstance(value, dict) for value in (pool, runner, backend, timing)):
        return False
    return (
        pool_is_clean(pool, expected_capacity)
        and runner.get("active_cancellation_registrations") == 0
        and runner.get("running_invocations") == 0
        and runner.get("quarantined_cells") == 0
        and runner.get("disposition_failures") == 0
        and backend.get("active_invocations") == 0
        and backend.get("live_stores") == 0
        and backend.get("live_host_states") == 0
        and backend.get("live_component_instances") == 0
        and backend.get("live_temporary_buffers") == 0
        and backend.get("live_cancellation_probes") == 0
        and timing.get("entries") == 0
        and isinstance(timing.get("maximum_entries"), int)
        and timing["maximum_entries"] > 0
        and sample.get("retained_log_entries_after_clear") == 0
    )


def validate_process_snapshot(process: Any, label: str) -> dict[str, Any]:
    if not isinstance(process, dict):
        fail(f"{label} lacks a process snapshot")
    for field in (
        "process_count",
        "child_process_count",
        "thread_count",
        "file_descriptor_count",
        "open_socket_count",
        "listening_socket_count",
        "rss_bytes",
        "virtual_memory_bytes",
    ):
        if not isinstance(process.get(field), int):
            fail(f"{label} process.{field} is missing or non-integral")
    for field in ("pss_bytes", "private_bytes"):
        if process.get(field) is not None and not isinstance(process.get(field), int):
            fail(f"{label} process.{field} must be an integer or null")
    notes = process.get("probe_notes")
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        fail(f"{label} process.probe_notes is missing or malformed")
    unavailable = [
        note
        for note in notes
        if any(marker in note.lower() for marker in MANDATORY_SOCKET_PROBE_FAILURES)
    ]
    if unavailable:
        fail(
            f"{label} has an unavailable mandatory listening-socket probe: "
            f"{'; '.join(unavailable)}"
        )
    return process


def validate_sample(
    sample: Any,
    label: str,
    expected_capacity: int,
    expected_workers: int,
    cache_released: bool,
) -> dict[str, Any]:
    if not isinstance(sample, dict):
        fail(f"{label} sample is malformed")
    if sample.get("invariant_passed") is not True:
        fail(f"{label} sample did not pass its per-batch invariant")
    if not logical_resources_are_clean(sample, expected_capacity):
        fail(f"{label} contains non-baseline logical resources")
    if sample.get("observed_runtime_workers") != expected_workers:
        fail(f"{label} has an unexpected worker count")
    process = sample.get("process")
    cache = sample.get("prepared_cache")
    if not isinstance(process, dict) or not isinstance(cache, dict):
        fail(f"{label} lacks process/cache samples")
    validate_process_snapshot(process, label)
    if cache_released:
        if cache.get("entries") != 0 or cache.get("source_bytes") != 0:
            fail(f"{label} retained a prepared cache entry after explicit release")
    elif not (
        cache.get("entries") == 1
        and isinstance(cache.get("source_bytes"), int)
        and isinstance(cache.get("maximum_entries"), int)
        and isinstance(cache.get("maximum_source_bytes"), int)
        and cache["entries"] <= cache["maximum_entries"]
        and cache["source_bytes"] <= cache["maximum_source_bytes"]
    ):
        fail(f"{label} has an unbounded or changed prepared cache")
    return sample


def validate_shutdown(
    shutdown: Any,
    label: str,
    post_release: dict[str, Any],
    process_before_runtime: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(shutdown, dict) or shutdown.get("observed_runtime_workers") != 0:
        fail(f"{label} did not retain clean runtime shutdown evidence")
    process = validate_process_snapshot(shutdown.get("process"), f"{label} post-shutdown")
    release_process = validate_process_snapshot(
        post_release.get("process"), f"{label} post-release"
    )
    exact_fields = (
        "process_count",
        "child_process_count",
        "open_socket_count",
        "listening_socket_count",
    )
    changed = [
        field
        for field in exact_fields
        if process[field] != release_process[field]
    ]
    if changed:
        fail(
            f"{label} post-shutdown process topology differs from post-release for "
            f"{', '.join(changed)}"
        )
    expected_terminal = {
        "process_count": 1,
        "child_process_count": 0,
        "open_socket_count": 0,
        "listening_socket_count": 0,
        "thread_count": 1,
    }
    nonterminal = [
        field
        for field, expected in expected_terminal.items()
        if process[field] != expected
    ]
    if nonterminal:
        fail(
            f"{label} post-shutdown process is not at the required terminal topology: "
            f"{', '.join(nonterminal)}"
        )
    if process["thread_count"] > release_process["thread_count"]:
        fail(f"{label} post-shutdown thread count increased after release")
    if process["file_descriptor_count"] > release_process["file_descriptor_count"]:
        fail(f"{label} has an unexplained post-release-to-shutdown FD increase")
    if process_before_runtime is not None:
        baseline = validate_process_snapshot(
            process_before_runtime, f"{label} pre-runtime"
        )
        baseline_fields = (
            "process_count",
            "child_process_count",
            "open_socket_count",
            "listening_socket_count",
        )
        changed_from_baseline = [
            field for field in baseline_fields if process[field] != baseline[field]
        ]
        if changed_from_baseline:
            fail(
                f"{label} post-shutdown process topology differs from its pre-runtime "
                f"baseline for {', '.join(changed_from_baseline)}"
            )
        if process["thread_count"] > baseline["thread_count"] + 1:
            fail(f"{label} post-shutdown thread count exceeds its pre-runtime baseline")
        if process["file_descriptor_count"] > baseline["file_descriptor_count"]:
            fail(f"{label} post-shutdown FD count exceeds its pre-runtime baseline")
    return shutdown


def run_directories(runs_directory: Path, minimum_runs: int) -> list[tuple[str, Path]]:
    if not runs_directory.is_dir():
        fail(f"runs directory does not exist: {runs_directory}")
    runs: list[tuple[int, str, Path]] = []
    for candidate in runs_directory.iterdir():
        if not candidate.is_dir():
            continue
        match = re.fullmatch(r"run-(\d{2,})", candidate.name)
        if match is None:
            fail(f"unexpected entry in run archive: {candidate.name}")
        runs.append((int(match.group(1)), candidate.name, candidate))
    runs.sort()
    if len(runs) < minimum_runs:
        fail(f"resource soak requires at least {minimum_runs} independent runs; found {len(runs)}")
    expected_indices = list(range(1, len(runs) + 1))
    actual_indices = [index for index, _, _ in runs]
    if actual_indices != expected_indices:
        fail(f"run directories must be consecutive from run-01; found {actual_indices}")
    return [(label, path) for _, label, path in runs]


def validate_host(
    document: dict[str, Any],
    label: str,
    phase: str,
    source_commit: str,
    source_tree: str,
    execution_commit: str,
    expected_provenance: dict[str, str] | None,
) -> dict[str, Any]:
    if document.get("schema_version") != HOST_SCHEMA:
        fail(f"{label} {phase} host observation has an unexpected schema")
    if document.get("phase") != phase:
        fail(f"{label} host observation has the wrong phase")
    if document.get("run_index") != int(label.removeprefix("run-")):
        fail(f"{label} {phase} host observation run index does not match its retained directory")
    if document.get("native_linux_reference") is not True:
        fail(f"{label} is not a native-Linux host or VM observation")
    identity = document.get("source_identity")
    if not isinstance(identity, dict):
        fail(f"{label} host observation lacks source identity")
    if (
        identity.get("published_commit") != source_commit
        or identity.get("published_tree") != source_tree
        or identity.get("execution_commit") != execution_commit
        or identity.get("execution_tree") != source_tree
        or identity.get("tree_identity_verified") is not True
    ):
        fail(f"{label} host observation source identity does not match the archive")
    observed_provenance = durable_source_provenance(
        identity, f"{label} {phase} host observation"
    )
    if observed_provenance != expected_provenance:
        fail(f"{label} {phase} host observation durable source provenance does not match the raw run")
    host = document.get("host")
    if not isinstance(host, dict):
        fail(f"{label} {phase} host observation lacks host context")
    for field in HOST_ENVIRONMENT_FIELDS:
        value = host.get(field)
        if field in ("logical_cpu_count", "total_memory_bytes"):
            valid = isinstance(value, int) and not isinstance(value, bool) and value > 0
        else:
            valid = isinstance(value, str) and bool(value)
        if not valid:
            fail(f"{label} {phase} host observation lacks valid host.{field}")
    virtualization = host.get("virtualization")
    if not isinstance(virtualization, dict):
        fail(f"{label} {phase} host observation lacks virtualization context")
    for field, expected_type in (
        ("systemd_detect_virt", str),
        ("systemd_detect_virt_container", str),
        ("wsl_detected", bool),
    ):
        if not isinstance(virtualization.get(field), expected_type):
            fail(f"{label} {phase} host observation lacks virtualization.{field}")
    if (
        not isinstance(virtualization.get("systemd_detect_virt_vm"), str)
        and not is_known_legacy_soak_source(identity)
    ):
        fail(f"{label} {phase} host observation lacks virtualization.systemd_detect_virt_vm")
    if not isinstance(document.get("allocator"), dict) and not is_known_legacy_soak_source(identity):
        fail(f"{label} {phase} host observation lacks allocator provenance")
    if expected_provenance is not None:
        static_host_identity(document, f"{label} {phase} host observation")
    return document


def static_host_identity(document: dict[str, Any], label: str) -> dict[str, Any]:
    """Reuse calibration's exact static virtualization/allocator/policy identity."""

    host = document.get("host")
    if not isinstance(host, dict):
        fail(f"{label} lacks host context")
    try:
        return calibration_aggregate.host_comparability_identity(
            {
                "virtualization": host.get("virtualization"),
                "allocator": document.get("allocator"),
                "cpu_frequency_policy": document.get("cpu_frequency_policy"),
            }
        )
    except calibration_aggregate.CalibrationError as error:
        fail(f"{label} has invalid static host identity: {error}")


def reconcile_raw_environment_with_host(
    document: dict[str, Any],
    label: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Prove that process-reported and independently captured host identity agree."""
    environment = value_at(document, "environment")
    native = value_at(document, "environment.native_linux_validation")
    if not isinstance(environment, dict) or not isinstance(native, dict):
        fail(f"{label} has malformed environment or native-Linux validation")
    legacy = is_known_legacy_soak_source(document.get("source_identity"))
    limitations: list[str] = []
    compared_fields = list(HOST_ENVIRONMENT_FIELDS)
    for phase, observation in (("before", before), ("after", after)):
        host = observation["host"]
        for field in HOST_ENVIRONMENT_FIELDS:
            if environment.get(field) != host.get(field):
                fail(
                    f"{label} raw environment.{field} does not match {phase} "
                    "host observation"
                )
        virtualization = host["virtualization"]
        if native.get("operating_system") != host.get("operating_system"):
            fail(
                f"{label} raw native-Linux operating system does not match {phase} "
                "host observation"
            )
        if native.get("wsl_detected") != virtualization.get("wsl_detected"):
            fail(
                f"{label} raw WSL status does not match {phase} host observation"
            )
        if native.get("container_kind") != virtualization.get("systemd_detect_virt_container"):
            fail(
                f"{label} raw container status does not match {phase} host observation"
            )
        raw_virtualization = native.get("virtualization_kind")
        if not isinstance(raw_virtualization, str) or not raw_virtualization:
            if not legacy:
                fail(f"{label} raw native-Linux validation lacks virtualization_kind")
            limitations.append("raw native-Linux virtualization_kind is absent")
        elif raw_virtualization != virtualization.get("systemd_detect_virt"):
            fail(
                f"{label} raw virtualization status does not match {phase} host observation"
            )
        if not isinstance(virtualization.get("systemd_detect_virt_vm"), str):
            if not legacy:
                fail(f"{label} {phase} host observation lacks VM virtualization status")
            limitations.append(f"{phase} host VM virtualization status is absent")
        if not isinstance(observation.get("allocator"), dict):
            if not legacy:
                fail(f"{label} {phase} host observation lacks allocator provenance")
            limitations.append(f"{phase} host allocator provenance is absent")
    return {
        "status": "incomplete" if limitations else "pass",
        "rule": (
            "Every raw process environment must match both independent before/after "
            "host observations for OS, architecture, CPU, logical CPUs, memory, kernel, "
            "and native-Linux virtualization state."
        ),
        "compared_fields": compared_fields
        + [
            "native_linux_validation.operating_system",
            "native_linux_validation.wsl_detected",
            "native_linux_validation.container_kind",
            "native_linux_validation.virtualization_kind",
        ],
        "limitations": sorted(set(limitations)),
    }


def config_identity(document: dict[str, Any]) -> dict[str, Any]:
    config = value_at(document, "config")
    artifact = value_at(document, "artifact")
    environment = value_at(document, "environment")
    if not isinstance(config, dict) or not isinstance(artifact, dict) or not isinstance(environment, dict):
        fail("soak raw document has malformed configuration identity")
    source_identity = value_at(document, "source_identity")
    if not isinstance(source_identity, dict):
        fail("soak raw document has malformed source identity")
    provenance = durable_source_provenance(source_identity, "soak raw document")
    if provenance is None and not is_pre_provenance_soak_source(source_identity):
        fail("new soak raw document lacks durable source provenance")
    identity = {
        "source_identity": {
            key: value_at(document, f"source_identity.{key}")
            for key in (
                "published_commit",
                "published_tree",
                "execution_commit",
                "execution_tree",
                "final_configuration_commit",
            )
        },
        "config": config,
        "component_digest": artifact.get("component_digest"),
        "component_bytes": artifact.get("component_bytes"),
        "environment": {
            key: environment.get(key)
            for key in (
                "operating_system",
                "architecture",
                "kernel",
                "cpu_model",
                "logical_cpu_count",
                "total_memory_bytes",
                "rustc",
                "cargo",
                "rust_target",
                "build_profile",
                "wasmtime_version",
                "allocator_statistics",
                "native_linux_validation",
            )
        },
    }
    if provenance is not None:
        identity["source_identity"].update(provenance)
        try:
            identity["collector"] = require_native_collector_identity(
                artifact.get("collector"),
                "resource-soak native collector identity",
                "phase0-soak",
            )
        except CollectorIdentityError as error:
            fail(str(error))
    capsule_digest = artifact.get("capsule_digest")
    capsule_bytes = artifact.get("capsule_bytes")
    if capsule_digest is not None or capsule_bytes is not None:
        if (
            not isinstance(capsule_digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", capsule_digest) is None
            or not isinstance(capsule_bytes, int)
            or isinstance(capsule_bytes, bool)
            or capsule_bytes <= 0
        ):
            fail("soak raw document has an invalid capsule identity")
        identity["capsule_digest"] = capsule_digest
        identity["capsule_bytes"] = capsule_bytes
    elif provenance is not None:
        fail("new soak raw document lacks its capsule identity")
    return identity


def validate_run(
    document: dict[str, Any],
    label: str,
    source_commit: str,
    source_tree: str,
) -> dict[str, Any]:
    if document.get("schema_version") != RUN_SCHEMA:
        fail(f"{label} has an unexpected resource-soak schema")
    if document.get("status") != "pass" or document.get("test_only") is not False:
        fail(f"{label} is not a completed non-test resource soak")
    if document.get("profile") != "native_linux_resource_soak":
        fail(f"{label} has an unexpected soak profile")
    command = document.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(argument, str) and argument for argument in command
    ):
        fail(f"{label} does not retain the exact resource-soak command")
    expected_run_index = int(label.removeprefix("run-"))
    if document.get("run_index") != expected_run_index:
        fail(f"{label} raw run index does not match its retained directory")
    identity = document.get("source_identity")
    if not isinstance(identity, dict):
        fail(f"{label} lacks source identity")
    provenance = durable_source_provenance(identity, f"{label} raw source identity")
    if provenance is None and not is_pre_provenance_soak_source(identity):
        fail(f"{label} lacks durable source provenance for newly collected evidence")
    if (
        identity.get("published_commit") != source_commit
        or identity.get("published_tree") != source_tree
        or not valid_object_id(identity.get("execution_commit"))
        or identity.get("execution_tree") != source_tree
        or identity.get("tree_identity_verified") is not True
        or identity.get("final_configuration_commit") != source_commit
    ):
        fail(f"{label} source/final-configuration identity does not match the archive")
    if provenance is not None and identity.get("execution_commit") != source_commit:
        fail(f"{label} execution commit differs from the published source commit")
    hard_checks(document, label)
    environment = document.get("environment")
    if not isinstance(environment, dict) or environment.get("operating_system") != "linux":
        fail(f"{label} does not report Linux as its resource-soak operating system")
    native_validation = environment.get("native_linux_validation")
    if not isinstance(native_validation, dict) or (
        native_validation.get("wsl_detected") is not False
        or native_validation.get("container_kind") != "none"
        or native_validation.get("proc_probe_available") is not True
    ):
        fail(f"{label} lacks a passing native-Linux process probe validation")
    config = value_at(document, "config")
    if not isinstance(config, dict):
        fail(f"{label} config is malformed")
    limits_source = retained_state_limit_source(document, label)
    if (
        config.get("prepared_cache_enabled") is not True
        or config.get("wasmtime_instance_allocator") != "on_demand"
        or config.get("wasmtime_copy_on_write_images") is not True
    ):
        fail(
            f"{label} does not retain the final ordinary Phase 0 cache/allocator/COW configuration"
        )
    warmup = integer_at(document, "workload.warmup_activations")
    normal_measured = integer_at(document, "workload.normal_measured_activations")
    saturation_activations = integer_at(document, "workload.saturation_activations")
    checked_batches = integer_at(document, "workload.batch_invariants_checked")
    batch_size = config.get("batch_size")
    if (
        warmup < 1_000
        or normal_measured < 100_000
        or not isinstance(batch_size, int)
        or batch_size < 11
        or warmup % batch_size != 0
        or normal_measured % batch_size != 0
        or saturation_activations <= 0
    ):
        fail(f"{label} does not meet required warm-up/measured fresh-store workload size")
    saturation_counts = value_at(document, "workload.saturation_batch_counts")
    if not isinstance(saturation_counts, dict):
        fail(f"{label} saturation batch counts are malformed")
    if set(saturation_counts) != {"at_capacity", "bounded_queue_saturation"}:
        fail(f"{label} has an unexpected saturation batch-count set")
    saturation_interval = config.get("saturation_every_batches")
    normal_batches = normal_measured // batch_size
    if (
        not isinstance(saturation_interval, int)
        or saturation_interval <= 0
        or saturation_interval > 10
    ):
        fail(f"{label} does not schedule saturation batches frequently enough")
    expected_saturation_batches = normal_batches // saturation_interval
    if not all(
        isinstance(saturation_counts.get(name), int)
        and saturation_counts[name] == expected_saturation_batches
        and saturation_counts[name] > 0
        for name in ("at_capacity", "bounded_queue_saturation")
    ):
        fail(f"{label} lacks repeated at-capacity or bounded-queue batches")
    expected_batches = warmup // batch_size + normal_batches + sum(saturation_counts.values())
    if checked_batches != expected_batches:
        fail(f"{label} did not retain exactly one invariant check per completed batch")
    scenario_counts = value_at(document, "workload.scenario_counts")
    if not isinstance(scenario_counts, dict) or any(
        not isinstance(scenario_counts.get(name), int) or scenario_counts[name] <= 0
        for name in REQUIRED_SCENARIOS
    ):
        fail(f"{label} lacks required success/failure/recovery scenarios")
    expected_capacity = config.get("pool_capacity")
    expected_workers = config.get("runtime_workers")
    if not isinstance(expected_capacity, int) or not isinstance(expected_workers, int):
        fail(f"{label} lacks fixed pool/runtime configuration")
    samples = document.get("resource_samples")
    if not isinstance(samples, list) or len(samples) != expected_batches + 1:
        fail(f"{label} does not retain every bounded interval sample")
    previous_index = -1
    previous_normal_measured = -1
    previous_total_activations = -1
    measured_samples: list[dict[str, Any]] = []
    prepared_cache_bytes: int | None = None
    for position, raw_sample in enumerate(samples):
        sample = validate_sample(
            raw_sample,
            f"{label} resource sample {position}",
            expected_capacity,
            expected_workers,
            cache_released=False,
        )
        index = sample.get("batch_index")
        if not isinstance(index, int) or index != previous_index + 1:
            fail(f"{label} has missing or reordered batch checkpoints")
        previous_index = index
        normal_completed = sample.get("normal_measured_activations_completed")
        total_completed = sample.get("total_activation_count")
        if (
            not isinstance(normal_completed, int)
            or not isinstance(total_completed, int)
            or normal_completed < previous_normal_measured
            or total_completed < previous_total_activations
        ):
            fail(f"{label} has non-monotonic activation counters in its raw samples")
        previous_normal_measured = normal_completed
        previous_total_activations = total_completed
        source_bytes = sample["prepared_cache"]["source_bytes"]
        if prepared_cache_bytes is None:
            prepared_cache_bytes = source_bytes
        elif source_bytes != prepared_cache_bytes:
            fail(f"{label} prepared cache source bytes changed during retained workload")
        if sample.get("phase") == "measured":
            measured_samples.append(sample)
    warmup_batches = warmup // batch_size
    if samples[0].get("phase") != "after_prepare":
        fail(f"{label} does not retain its post-preparation checkpoint first")
    if any(sample.get("phase") != "warmup" for sample in samples[1 : warmup_batches + 1]):
        fail(f"{label} has a missing or incorrectly classified warm-up interval")
    if any(sample.get("phase") != "measured" for sample in samples[warmup_batches + 1 :]):
        fail(f"{label} has a missing or incorrectly classified measured interval")
    if samples[-1].get("normal_measured_activations_completed") != normal_measured:
        fail(f"{label} final measured checkpoint does not retain every normal measured activation")
    if not measured_samples:
        fail(f"{label} has no post-warm-up samples")
    process_before_runtime = document.get("process_before_runtime")
    process_after_warmup = document.get("process_after_warmup")
    evidence_limitations: list[str] = []
    if process_before_runtime is None:
        if not is_known_legacy_soak_source(identity):
            fail(f"{label} lacks its pre-runtime process baseline")
        evidence_limitations.append("pre-runtime process baseline is absent")
    else:
        process_before_runtime = validate_process_snapshot(
            process_before_runtime, f"{label} pre-runtime"
        )
    if process_after_warmup is None:
        if not is_known_legacy_soak_source(identity):
            fail(f"{label} lacks its post-warm-up descriptor baseline")
        evidence_limitations.append("post-warm-up descriptor baseline is absent")
    else:
        process_after_warmup = validate_process_snapshot(
            process_after_warmup, f"{label} post-warm-up baseline"
        )
    post_release = validate_sample(
        document.get("post_release"),
        f"{label} post-release sample",
        expected_capacity,
        expected_workers,
        cache_released=True,
    )
    if post_release.get("batch_index") != expected_batches + 1:
        fail(f"{label} post-release checkpoint is not after every workload batch")
    shutdown = validate_shutdown(
        document.get("post_shutdown"), label, post_release, process_before_runtime
    )
    saturation_observations = document.get("saturation_observations")
    if not isinstance(saturation_observations, list):
        fail(f"{label} lacks saturation observations")
    queue_capacity = config.get("pool_queue_capacity")
    if not isinstance(queue_capacity, int):
        fail(f"{label} lacks a fixed queue capacity")
    modes = {"at_capacity", "bounded_queue_saturation"}
    if any(not isinstance(value, dict) for value in saturation_observations):
        fail(f"{label} has a malformed saturation observation")
    observed_modes = {value.get("mode") for value in saturation_observations}
    if observed_modes != modes:
        fail(f"{label} saturation observations do not have the declared mode set")
    expected_observations = {
        "at_capacity": {
            "count": saturation_counts["at_capacity"],
            "activations": expected_capacity,
            "queue_depth": 0,
        },
        "bounded_queue_saturation": {
            "count": saturation_counts["bounded_queue_saturation"],
            "activations": expected_capacity + queue_capacity,
            "queue_depth": queue_capacity,
        },
    }
    for mode, expected in expected_observations.items():
        observations = [value for value in saturation_observations if value["mode"] == mode]
        if len(observations) != expected["count"]:
            fail(f"{label} does not retain every declared {mode} observation")
        if any(
            observation.get("activations") != expected["activations"]
            or observation.get("maximum_observed_active_leases") != expected_capacity
            or observation.get("maximum_observed_queue_depth") != expected["queue_depth"]
            for observation in observations
        ):
            fail(f"{label} did not prove every {mode} batch reached the real configured bound")
    observed_saturation_activations = sum(
        observation["activations"] for observation in saturation_observations
    )
    if observed_saturation_activations != saturation_activations:
        fail(f"{label} saturation activation count does not match its observations")
    expected_total_activations = warmup + normal_measured + saturation_activations
    if samples[-1].get("total_activation_count") != expected_total_activations:
        fail(f"{label} final activation counter does not reconcile with its workload totals")
    return {
        "document": document,
        "measured_samples": measured_samples,
        "identity": config_identity(document),
        "post_release": post_release,
        "post_shutdown": shutdown,
        "process_before_runtime": process_before_runtime,
        "prepared_baseline": process_after_warmup,
        "retained_state_limit_source": limits_source,
        "evidence_limitations": evidence_limitations,
        "execution_commit": identity["execution_commit"],
        "source_provenance": provenance,
    }


def metric_values(samples: Iterable[dict[str, Any]], path: str) -> list[float] | None:
    values: list[float] = []
    for sample in samples:
        current: Any = sample
        for part in path.split("."):
            if not isinstance(current, dict):
                fail(f"sample is missing metric path {path}")
            current = current.get(part)
        if current is None:
            return None
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            fail(f"sample metric {path} is not numeric")
        values.append(float(current))
    return values


def median_absolute_deviation(values: list[float]) -> float:
    if not values:
        return 0.0
    center = statistics.median(values)
    return statistics.median(abs(value - center) for value in values)


def summary(values: list[float]) -> dict[str, Any]:
    if not values:
        fail("cannot summarize no values")
    mean = statistics.fmean(values)
    minimum = min(values)
    maximum = max(values)
    coefficient: float | None
    reason: str | None
    if len(values) < 2 or mean == 0:
        coefficient = None
        reason = "fewer than two values" if len(values) < 2 else "mean is zero"
    else:
        coefficient = statistics.pstdev(values) * 100.0 / abs(mean)
        reason = None
    return {
        "sample_count": len(values),
        "minimum": minimum,
        "median": statistics.median(values),
        "maximum": maximum,
        "mean": mean,
        "median_absolute_deviation": median_absolute_deviation(values),
        "coefficient_of_variation_percent": coefficient,
        "coefficient_of_variation_not_meaningful_reason": reason,
    }


def robust_outliers(values: dict[str, float]) -> list[str]:
    if len(values) < 3:
        return []
    center = statistics.median(values.values())
    mad = median_absolute_deviation(list(values.values()))
    if mad == 0:
        return [label for label, value in values.items() if value != center]
    return sorted(
        label
        for label, value in values.items()
        if abs(0.6745 * (value - center) / mad) > ROBUST_OUTLIER_THRESHOLD
    )


def rolling_ranges(values: list[float], window_size: int) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    for start in range(0, len(values), window_size):
        window = values[start : start + window_size]
        if not window:
            continue
        minimum = min(window)
        maximum = max(window)
        ranges.append(
            {
                "start_sample": start,
                "end_sample": start + len(window) - 1,
                "minimum": minimum,
                "maximum": maximum,
                "range": maximum - minimum,
            }
        )
    return ranges


def theil_sen_slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    slopes = [
        (values[right] - values[left]) / (right - left)
        for left in range(len(values) - 1)
        for right in range(left + 1, len(values))
    ]
    return statistics.median(slopes)


def analyse_series(values: list[float]) -> dict[str, Any]:
    if len(values) < 5:
        fail("a measured resource series needs at least five bounded interval samples")
    window_size = max(5, min(25, len(values) // 10 or 5))
    final_window = values[-window_size:]
    return {
        "sample_count": len(values),
        "minimum": min(values),
        "peak": max(values),
        "final_value": values[-1],
        "rolling_window_size": window_size,
        "rolling_ranges": rolling_ranges(values, window_size),
        "final_window_delta": final_window[-1] - final_window[0],
        "robust_late_window_slope_per_sample": theil_sen_slope(final_window),
        "late_window_start": len(values) - window_size,
        "late_window_end": len(values) - 1,
    }


def calibration_host_identity(document: dict[str, Any]) -> dict[str, Any]:
    host_observations = document.get("host_observations")
    if not isinstance(host_observations, dict):
        fail("calibration aggregate lacks host observations")
    runs = host_observations.get("runs")
    if not isinstance(runs, list) or not runs:
        fail("calibration aggregate has no host-observation runs")
    policy_presence = [
        isinstance(run, dict) and "cpu_frequency_policy" in run for run in runs
    ]
    if any(policy_presence) and not all(policy_presence):
        fail("calibration host observations inconsistently retain CPU frequency/power-policy evidence")
    identities: list[dict[str, Any]] = []
    for index, run in enumerate(runs, start=1):
        if not isinstance(run, dict):
            fail(f"calibration host observation {index} is malformed")
        virtualization = run.get("virtualization")
        allocator = run.get("allocator")
        if not isinstance(virtualization, dict) or not isinstance(allocator, dict):
            fail(f"calibration host observation {index} lacks virtualization or allocator evidence")
        identity = {"virtualization": virtualization, "allocator": allocator}
        if policy_presence[index - 1]:
            try:
                identity = calibration_aggregate.host_comparability_identity(
                    {
                        **identity,
                        "cpu_frequency_policy": run.get("cpu_frequency_policy"),
                    }
                )
            except calibration_aggregate.CalibrationError as error:
                fail(f"calibration host observation {index} has invalid static identity: {error}")
        identities.append(identity)
    if any(stable_json(identity) != stable_json(identities[0]) for identity in identities[1:]):
        fail(
            "calibration host observations do not retain one static virtualization/allocator"
            "/CPU-frequency-policy identity"
        )
    return identities[0]


def soak_host_identity(host_observations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    identities: list[dict[str, Any]] = []
    policy_presence: list[bool] = []
    for label, phases in sorted(host_observations.items()):
        for phase in ("before", "after"):
            observation = phases[phase]
            host = observation.get("host")
            if not isinstance(host, dict):
                fail(f"{label} {phase} host observation lacks host context")
            virtualization = host.get("virtualization")
            if not isinstance(virtualization, dict):
                fail(f"{label} {phase} host observation lacks virtualization context")
            allocator = observation.get("allocator")
            identity = {
                "host": {field: host.get(field) for field in HOST_ENVIRONMENT_FIELDS},
                "native_linux_reference": observation.get("native_linux_reference"),
                "virtualization": virtualization,
                "allocator": allocator,
            }
            has_policy = "cpu_frequency_policy" in observation
            policy_presence.append(has_policy)
            if has_policy:
                identity["cpu_frequency_policy"] = static_host_identity(
                    observation, f"{label} {phase} host observation"
                )["cpu_frequency_policy"]
            identities.append(identity)
    if not identities:
        fail("resource-soak archive has no host observations")
    if any(policy_presence) and not all(policy_presence):
        fail(
            "resource-soak host observations inconsistently retain CPU frequency/power-policy evidence"
        )
    if any(stable_json(identity) != stable_json(identities[0]) for identity in identities[1:]):
        fail(
            "resource-soak host observations do not retain one static OS/CPU/memory/kernel, "
            "virtualization, allocator, and CPU frequency/power-policy identity"
        )
    return identities[0]


def calibration_mismatches(
    reference_identity: dict[str, Any],
    candidate_identity: dict[str, Any],
    reference_host: dict[str, Any],
    candidate_host: dict[str, Any],
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []

    def compare(path: str, reference: Any, candidate: Any) -> None:
        if reference != candidate:
            if reference is None:
                reason = "missing calibration value"
            elif candidate is None:
                reason = "missing soak value"
            else:
                reason = "mismatch"
            mismatches.append(
                {
                    "field": path,
                    "calibration": reference,
                    "soak": candidate,
                    "reason": reason,
                }
            )

    def config_value(config: dict[str, Any], field: str) -> Any:
        if field != "wasmtime_instance_allocator":
            return config.get(field)
        canonical = config.get("wasmtime_instance_allocator")
        historical = config.get("wasmtime_allocator")
        if canonical is not None and historical is not None and canonical != historical:
            fail("calibration configuration records conflicting Wasmtime allocator modes")
        return canonical if canonical is not None else historical

    reference_environment = reference_identity.get("environment")
    candidate_environment = candidate_identity.get("environment")
    reference_artifact = reference_identity.get("artifact")
    reference_collector = reference_identity.get("collector")
    candidate_collector = candidate_identity.get("collector")
    candidate_config = candidate_identity.get("config")
    reference_config = reference_identity.get("config")
    if not all(
        isinstance(value, dict)
        for value in (
            reference_environment,
            candidate_environment,
            reference_artifact,
            candidate_config,
            reference_config,
        )
    ):
        fail("calibration or soak comparison identity is malformed")
    for field in CALIBRATION_ENVIRONMENT_FIELDS:
        compare(
            f"environment.{field}",
            reference_environment.get(field),
            candidate_environment.get(field),
        )
    for field in ("component_digest", "component_bytes"):
        compare(
            f"artifact.{field}",
            reference_artifact.get(field),
            candidate_identity.get(field),
        )
    for field in ("capsule_digest", "capsule_bytes"):
        if field in reference_artifact or field in candidate_identity:
            compare(
                f"artifact.{field}",
                reference_artifact.get(field),
                candidate_identity.get(field),
            )
    for field in CALIBRATION_CONFIG_FIELDS:
        compare(
            f"config.{field}",
            config_value(reference_config, field),
            config_value(candidate_config, field),
        )
    if reference_collector is not None or candidate_collector is not None:
        if not isinstance(reference_collector, dict) or not isinstance(candidate_collector, dict):
            fail("calibration or soak comparison identity lacks native collector build identity")
        compare(
            "collector.build_configuration",
            reference_collector.get("build_configuration"),
            candidate_collector.get("build_configuration"),
        )
    reference_virtualization = reference_host.get("virtualization")
    candidate_virtualization = candidate_host.get("virtualization")
    reference_allocator = reference_host.get("allocator")
    candidate_allocator = candidate_host.get("allocator")
    if not isinstance(reference_virtualization, dict) or not isinstance(reference_allocator, dict):
        fail("calibration host identity is malformed")
    if not isinstance(candidate_virtualization, dict):
        mismatches.append(
            {
                "field": "host.virtualization",
                "calibration": reference_virtualization,
                "soak": candidate_virtualization,
                "reason": "missing candidate value",
            }
        )
    else:
        for field in (
            "systemd_detect_virt",
            "systemd_detect_virt_container",
            "systemd_detect_virt_vm",
            "wsl_detected",
        ):
            compare(
                f"host.virtualization.{field}",
                reference_virtualization.get(field),
                candidate_virtualization.get(field),
            )
    compare("host.allocator", reference_allocator, candidate_allocator)
    candidate_source_identity = candidate_identity.get("source_identity")
    candidate_has_durable_provenance = (
        isinstance(candidate_source_identity, dict)
        and durable_source_provenance(
            candidate_source_identity, "soak calibration comparison"
        )
        is not None
    )
    if candidate_has_durable_provenance:
        compare(
            "host.cpu_frequency_policy",
            reference_host.get("cpu_frequency_policy"),
            candidate_host.get("cpu_frequency_policy"),
        )
    return mismatches


def calibration_noise(
    calibration: Path,
    candidate_identity: dict[str, Any],
    candidate_host: dict[str, Any],
) -> dict[str, Any]:
    document = load_json(calibration)
    if (
        document.get("schema_version") not in SUPPORTED_CALIBRATION_SCHEMAS
        or document.get("status") != "pass"
    ):
        fail(f"calibration evidence is not a passing Phase 0 calibration: {calibration}")
    metrics = document.get("metrics")
    reference_identity = document.get("reference_identity")
    if not isinstance(metrics, dict) or not isinstance(reference_identity, dict):
        fail("calibration aggregate lacks metrics or reference identity")
    candidate_source_identity = candidate_identity.get("source_identity")
    candidate_has_durable_provenance = (
        isinstance(candidate_source_identity, dict)
        and durable_source_provenance(
            candidate_source_identity, "soak calibration comparison"
        )
        is not None
    )
    reference_host = calibration_host_identity(document)
    if not candidate_has_durable_provenance:
        # Preserve the immutable v1 aggregate identity for historical raw
        # packages. New durable evidence below requires the full static CPU
        # policy comparison.
        reference_host = {
            "virtualization": reference_host.get("virtualization"),
            "allocator": reference_host.get("allocator"),
        }
    mismatches = calibration_mismatches(
        reference_identity,
        candidate_identity,
        reference_host,
        candidate_host,
    )

    def noise_for(metric: str) -> dict[str, Any]:
        value = metrics.get(metric)
        if not isinstance(value, dict):
            fail(f"calibration aggregate lacks {metric}")
        comparison = value.get("comparison")
        if not isinstance(comparison, dict):
            fail(f"calibration metric {metric} lacks a comparison band")
        band = comparison.get("advisory_noise_band")
        if isinstance(band, bool) or not isinstance(band, (int, float)) or band <= 0:
            fail(f"calibration metric {metric} has an invalid advisory noise band")
        return {
            "advisory_noise_band": float(band),
            "reference_median": comparison.get("reference_median"),
            "source_metric": metric,
        }

    rss = noise_for("process_peak_rss_bytes")
    virtual = noise_for("process_peak_virtual_memory_bytes")
    return {
        "path": str(calibration),
        "schema_version": document["schema_version"],
        "source_commit": document.get("source_commit"),
        "source_tree": document.get("source_tree"),
        "applicability": {
            "status": "matched" if not mismatches else "not_applicable_for_phase0_calibration",
            "rule": "Apply issue #38 byte-scale advisory bands only when CPU, memory, kernel, virtualization, Rust/Cargo/Wasmtime toolchain, target, build profile, allocator observation, fixture digest, and relevant execution configuration—including prepared-cache enablement, Wasmtime allocator mode, and initialized-memory COW—match the calibration.",
            "mismatches": mismatches,
            "calibration_host_identity": reference_host,
            "soak_host_identity": candidate_host,
        },
        "rss_bytes": rss,
        "virtual_memory_bytes": virtual,
        "pss_bytes": {
            **rss,
            "source_metric": "process_peak_rss_bytes",
            "mapping": "PSS has no Phase 0 calibration metric; the same byte-scale RSS noise band is used conservatively only for material-growth triage on a proven matched host.",
        },
        "private_bytes": {
            **rss,
            "source_metric": "process_peak_rss_bytes",
            "mapping": "Private mappings have no Phase 0 calibration metric; the same byte-scale RSS noise band is used conservatively only for material-growth triage on a proven matched host.",
        },
    }


def plateau_metric(
    per_run: dict[str, list[float] | None],
    noise: dict[str, Any] | None,
) -> dict[str, Any]:
    availability = {label: values is not None for label, values in per_run.items()}
    if not any(availability.values()):
        return {
            "availability": "unsupported",
            "reason": "the Linux host did not expose this optional process mapping measure",
        }
    if not all(availability.values()):
        fail("optional process mapping probe availability differs across independent runs")
    analyses = {label: analyse_series(values or []) for label, values in per_run.items()}
    peaks = {label: analysis["peak"] for label, analysis in analyses.items()}
    deltas = {label: analysis["final_window_delta"] for label, analysis in analyses.items()}
    slopes = {
        label: analysis["robust_late_window_slope_per_sample"]
        for label, analysis in analyses.items()
    }
    if noise is None:
        decision = {
            "status": "observed",
            "rule": "No calibrated material-growth band is defined for this metric; retain rolling ranges and final-window slope for diagnosis.",
            "material_growth_limit": None,
            "violations": [],
        }
    else:
        limit = float(noise["advisory_noise_band"])
        late_window_size = max(1, next(iter(analyses.values()))["rolling_window_size"] - 1)
        slope_limit = limit / late_window_size
        violations = sorted(
            label
            for label, analysis in analyses.items()
            if analysis["final_window_delta"] > limit
            or analysis["robust_late_window_slope_per_sample"] > slope_limit
        )
        decision = {
            "status": "pass" if not violations else "material_growth_detected",
            "rule": "final-window positive delta must not exceed the matched Phase 0 calibrated noise band and the robust late-window slope must not exceed that band per late-window interval",
            "material_growth_limit": limit,
            "late_window_slope_limit_per_sample": slope_limit,
            "violations": violations,
            "calibration": noise,
        }
    return {
        "availability": "available",
        "per_run": analyses,
        "peaks": summary(list(peaks.values())),
        "final_window_deltas": summary(list(deltas.values())),
        "robust_late_window_slopes": summary(list(slopes.values())),
        "peak_run_level_outliers": robust_outliers(peaks),
        "delta_run_level_outliers": robust_outliers(deltas),
        "decision": decision,
    }


def fd_growth(
    per_run_samples: dict[str, list[dict[str, Any]]],
    post_release: dict[str, dict[str, Any]],
    post_shutdown: dict[str, dict[str, Any]],
    process_before_runtime: dict[str, dict[str, Any] | None],
    prepared_baselines: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    per_run: dict[str, dict[str, Any]] = {}
    measured_violations: list[str] = []
    terminal: dict[str, dict[str, Any]] = {}
    terminal_violations: list[str] = []
    lifecycle: dict[str, dict[str, Any]] = {}
    lifecycle_violations: list[str] = []
    lifecycle_incomplete: list[str] = []
    for label, samples in per_run_samples.items():
        values = metric_values(samples, "process.file_descriptor_count")
        assert values is not None
        change = values[-1] - values[0]
        per_run[label] = {
            "initial": values[0],
            "final": values[-1],
            "net_growth": change,
            "peak": max(values),
        }
        if change != 0:
            measured_violations.append(label)
        release_count = post_release[label]["process"]["file_descriptor_count"]
        shutdown_count = post_shutdown[label]["process"]["file_descriptor_count"]
        terminal_change = shutdown_count - release_count
        terminal[label] = {
            "post_release": release_count,
            "post_shutdown": shutdown_count,
            "net_growth": terminal_change,
        }
        if terminal_change > 0:
            terminal_violations.append(label)
        prepared_baseline = prepared_baselines[label]
        pre_runtime = process_before_runtime[label]
        if prepared_baseline is None or pre_runtime is None:
            lifecycle[label] = {
                "pre_runtime": None,
                "prepared_baseline": (
                    None
                    if prepared_baseline is None
                    else prepared_baseline["file_descriptor_count"]
                ),
                "final_measured": values[-1],
                "post_release": release_count,
                "post_shutdown": shutdown_count,
                "status": "incomplete",
                "reason": (
                    "raw document predates one or more serialized pre-runtime or "
                    "post-warm-up descriptor baselines"
                ),
            }
            lifecycle_incomplete.append(label)
            continue
        prepared_count = prepared_baseline["file_descriptor_count"]
        pre_runtime_count = pre_runtime["file_descriptor_count"]
        final_measured_delta = values[-1] - prepared_count
        post_release_delta = release_count - pre_runtime_count
        post_shutdown_delta = shutdown_count - pre_runtime_count
        violated = (
            final_measured_delta > 0
            or post_release_delta > 0
            or post_shutdown_delta > 0
        )
        lifecycle[label] = {
            "pre_runtime": pre_runtime_count,
            "prepared_baseline": prepared_count,
            "final_measured": values[-1],
            "post_release": release_count,
            "post_shutdown": shutdown_count,
            "final_measured_vs_prepared_delta": final_measured_delta,
            "post_release_vs_pre_runtime_delta": post_release_delta,
            "post_shutdown_vs_pre_runtime_delta": post_shutdown_delta,
            "status": "unexplained_net_growth" if violated else "pass",
        }
        if violated:
            lifecycle_violations.append(label)
    violations = sorted(
        set(measured_violations) | set(terminal_violations) | set(lifecycle_violations)
    )
    status = (
        "unexplained_net_growth"
        if violations
        else "incomplete"
        if lifecycle_incomplete
        else "pass"
    )
    return {
        "per_run": per_run,
        "measured_window": {
            "status": "pass" if not measured_violations else "unexplained_net_growth",
            "rule": "the final post-warm-up FD count must equal the first post-warm-up FD count in every independent process",
            "violations": measured_violations,
        },
        "post_release_to_shutdown": {
            "per_run": terminal,
            "status": "pass" if not terminal_violations else "unexplained_net_growth",
            "rule": "post-shutdown FD count must not exceed the explicit post-release count in any independent process",
            "violations": terminal_violations,
        },
        "lifecycle_baselines": {
            "per_run": lifecycle,
            "status": (
                "unexplained_net_growth"
                if lifecycle_violations
                else "incomplete"
                if lifecycle_incomplete
                else "pass"
            ),
            "rule": (
                "the final measured FD count must not exceed the post-warm-up baseline, "
                "and post-release/post-shutdown counts must not exceed the serialized "
                "pre-runtime baseline in every independent process"
            ),
            "violations": lifecycle_violations,
            "incomplete_runs": lifecycle_incomplete,
        },
        "status": status,
        "rule": (
            "the measured window, post-release-to-shutdown, and complete descriptor "
            "lifecycle baseline comparisons must have no unexplained growth"
        ),
        "violations": violations,
    }


def simple_topology_analysis(per_run_samples: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    fields = {
        "process_count": "process.process_count",
        "child_process_count": "process.child_process_count",
        "thread_count": "process.thread_count",
        "open_socket_count": "process.open_socket_count",
        "listening_socket_count": "process.listening_socket_count",
    }
    result: dict[str, Any] = {}
    for name, path in fields.items():
        per_run: dict[str, dict[str, float]] = {}
        violations: list[str] = []
        for label, samples in per_run_samples.items():
            values = metric_values(samples, path)
            assert values is not None
            per_run[label] = {"minimum": min(values), "maximum": max(values)}
            if min(values) != max(values):
                violations.append(label)
        result[name] = {
            "per_run": per_run,
            "status": "pass" if not violations else "changed",
            "violations": violations,
        }
    return result


def raw_run_record(
    label: str,
    path: Path,
    document: dict[str, Any],
    archive_root: Path,
) -> dict[str, Any]:
    artifact = {
        "component_digest": document["artifact"]["component_digest"],
        "component_bytes": document["artifact"]["component_bytes"],
    }
    if "capsule_digest" in document["artifact"] or "capsule_bytes" in document["artifact"]:
        artifact["capsule_digest"] = document["artifact"].get("capsule_digest")
        artifact["capsule_bytes"] = document["artifact"].get("capsule_bytes")
    collector = document["artifact"].get("collector")
    if collector is not None:
        artifact["collector"] = collector
    return {
        "label": label,
        "raw_json": relative_path(path, archive_root),
        "sha256": sha256_file(path),
        "schema_version": document["schema_version"],
        "run_index": document["run_index"],
        "command_profile": document["profile"],
        "command": document["command"],
        "source_identity": document["source_identity"],
        "artifact": artifact,
    }


def raw_evidence_archive_record(output_json: Path) -> dict[str, str] | None:
    archive = output_json.parent / "raw-evidence.tar.zst"
    if not archive.is_file():
        return None
    manifest = output_json.parent / "raw-evidence.manifest.sha256"
    checksum = output_json.parent / "raw-evidence.tar.zst.sha256"
    if not manifest.is_file() or not checksum.is_file():
        fail("checked-in raw-evidence archive lacks its manifest or archive checksum")
    expected_checksum = f"{sha256_file(archive).removeprefix('sha256:')}  {archive.name}"
    if read_text(checksum) != expected_checksum:
        fail("checked-in raw-evidence archive checksum does not match its payload")
    return {
        "path": archive.name,
        "sha256": sha256_file(archive),
        "manifest": manifest.name,
    }


def relative_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def aggregate(
    runs_directory: Path,
    output_json: Path,
    output_report: Path,
    source_commit: str,
    source_tree: str,
    calibration: Path,
    minimum_runs: int,
    retaining_subsystem: str | None,
    followup_issue: str | None,
) -> tuple[dict[str, Any], int]:
    if not valid_object_id(source_commit) or not valid_object_id(source_tree):
        fail("source commit and tree must be 40-character lowercase Git object IDs")
    if minimum_runs < MINIMUM_RUNS:
        fail(f"a resource-soak aggregate requires at least {MINIMUM_RUNS} runs")
    raw_evidence_archive = raw_evidence_archive_record(output_json)
    validated: dict[str, dict[str, Any]] = {}
    host_observations: dict[str, dict[str, Any]] = {}
    host_reconciliation: dict[str, dict[str, Any]] = {}
    raw_runs: list[dict[str, Any]] = []
    evidence_limitations: list[str] = []
    expected_identity: dict[str, Any] | None = None
    execution_commit: str | None = None
    source_provenance: dict[str, str] | None = None
    for label, directory in run_directories(runs_directory, minimum_runs):
        raw_path = directory / "raw.json"
        document = load_json(raw_path)
        result = validate_run(document, label, source_commit, source_tree)
        identity = result["identity"]
        if expected_identity is None:
            expected_identity = identity
            execution_commit = result["execution_commit"]
            source_provenance = result["source_provenance"]
        elif stable_json(identity) != stable_json(expected_identity):
            fail(f"{label} differs in source fixture, toolchain, host, or soak configuration")
        elif result["execution_commit"] != execution_commit:
            fail(f"{label} differs in execution-commit provenance")
        elif result["source_provenance"] != source_provenance:
            fail(f"{label} differs in durable source provenance")
        assert execution_commit is not None
        if source_provenance is not None and execution_commit != source_commit:
            fail(f"{label} execution commit differs from the published source commit")
        before = validate_host(
            load_json(directory / "host-before.json"),
            label,
            "before",
            source_commit,
            source_tree,
            execution_commit,
            result["source_provenance"],
        )
        after = validate_host(
            load_json(directory / "host-after.json"),
            label,
            "after",
            source_commit,
            source_tree,
            execution_commit,
            result["source_provenance"],
        )
        reconciliation = reconcile_raw_environment_with_host(document, label, before, after)
        status = load_json(directory / "execution-status.json")
        if (
            status.get("schema_version") != "latent.phase0.resource-soak.execution-status.v1"
            or status.get("exit_code") != 0
            or status.get("run_index") != int(label.removeprefix("run-"))
            or status.get("source_commit") != source_commit
            or status.get("source_tree") != source_tree
            or status.get("published_source_ref") != (
                None if result["source_provenance"] is None else result["source_provenance"]["published_source_ref"]
            )
            or status.get("published_source_ref_head") != (
                None if result["source_provenance"] is None else result["source_provenance"]["published_source_ref_head"]
            )
            or status.get("published_commit_reachable_from_ref") != (
                None
                if result["source_provenance"] is None
                else result["source_provenance"]["published_commit_reachable_from_ref"]
            )
            or status.get("execution_commit_matches_published") != (
                None
                if result["source_provenance"] is None
                else result["source_provenance"]["execution_commit_matches_published"]
            )
            or status.get("execution_commit") != execution_commit
            or status.get("execution_tree") != source_tree
        ):
            fail(f"{label} lacks a successful matching execution status")
        validated[label] = result
        host_observations[label] = {"before": before, "after": after}
        host_reconciliation[label] = reconciliation
        evidence_limitations.extend(
            f"{label}: {limitation}" for limitation in result["evidence_limitations"]
        )
        evidence_limitations.extend(
            f"{label}: {limitation}" for limitation in reconciliation["limitations"]
        )
        raw_runs.append(raw_run_record(label, raw_path, document, runs_directory.parent))
    assert expected_identity is not None
    assert execution_commit is not None
    if source_provenance is not None:
        try:
            verify_retained_native_collector(
                runs_directory.parent,
                expected_identity["collector"],
                "resource-soak native collector",
                "phase0-soak",
            )
        except CollectorIdentityError as error:
            fail(str(error))
    host_identity = soak_host_identity(host_observations)
    noise = calibration_noise(calibration, expected_identity, host_identity)
    calibration_matched = noise["applicability"]["status"] == "matched"
    per_run_samples = {
        label: value["measured_samples"] for label, value in validated.items()
    }
    metric_specs = {
        "rss_bytes": (
            "process.rss_bytes",
            "bytes",
            noise["rss_bytes"] if calibration_matched else None,
        ),
        "virtual_memory_bytes": (
            "process.virtual_memory_bytes",
            "bytes",
            noise["virtual_memory_bytes"] if calibration_matched else None,
        ),
        "pss_bytes": (
            "process.pss_bytes",
            "bytes",
            noise["pss_bytes"] if calibration_matched else None,
        ),
        "private_bytes": (
            "process.private_bytes",
            "bytes",
            noise["private_bytes"] if calibration_matched else None,
        ),
        "prepared_cache_source_bytes": ("prepared_cache.source_bytes", "bytes", None),
        "backend_timing_store_entries": ("backend_timing_store.entries", "entries", None),
        "active_leases": ("pool.active_leases", "entries", None),
        "queue_depth": ("pool.queue_depth", "entries", None),
    }
    metrics: dict[str, Any] = {}
    for name, (path, unit, metric_noise) in metric_specs.items():
        values = {
            label: metric_values(samples, path)
            for label, samples in per_run_samples.items()
        }
        metrics[name] = {"unit": unit, **plateau_metric(values, metric_noise)}
    topology = simple_topology_analysis(per_run_samples)
    post_release = {label: value["post_release"] for label, value in validated.items()}
    post_shutdown = {label: value["post_shutdown"] for label, value in validated.items()}
    descriptors = fd_growth(
        per_run_samples,
        post_release,
        post_shutdown,
        {label: value["process_before_runtime"] for label, value in validated.items()},
        {label: value["prepared_baseline"] for label, value in validated.items()},
    )
    if descriptors["status"] == "incomplete":
        evidence_limitations.append(
            "complete descriptor lifecycle comparison is unavailable for "
            + ", ".join(descriptors["lifecycle_baselines"]["incomplete_runs"])
        )
    evidence_limitations = sorted(set(evidence_limitations))
    evidence_complete = not evidence_limitations
    material_growth = {
        name: metric["decision"]["violations"]
        for name, metric in metrics.items()
        if metric.get("availability") == "available"
        and metric["decision"]["status"] == "material_growth_detected"
    }
    identified_outliers = {
        name: sorted(
            set(metric.get("peak_run_level_outliers", []))
            | set(metric.get("delta_run_level_outliers", []))
        )
        for name, metric in metrics.items()
        if metric.get("availability") == "available"
        and (
            metric.get("peak_run_level_outliers")
            or metric.get("delta_run_level_outliers")
        )
    }
    # A robust cross-run peak difference is useful diagnostic evidence, but it
    # is not by itself sustained growth.  A run can have a different stable
    # PSS/RSS baseline while every late-window delta and slope remains inside
    # the matched #38 noise band.  Classify that as observed variability; only
    # a metric that already breaches the calibrated late-window rule is
    # material enough to fail the plateau decision.
    material_outliers = {
        name: labels
        for name, labels in identified_outliers.items()
        if metrics[name].get("decision", {}).get("status") == "material_growth_detected"
    }
    topology_violations = {
        name: analysis["violations"]
        for name, analysis in topology.items()
        if analysis["violations"]
    }
    failures: list[str] = []
    if material_growth:
        failures.append("material RSS/PSS/private/VM growth")
    if descriptors["violations"]:
        failures.append("unexplained net file-descriptor growth")
    if topology_violations:
        failures.append("topology changed during measured workload")
    if material_outliers:
        failures.append("material run-level resource outlier")
    investigation: dict[str, Any] | None = None
    if material_growth:
        investigation = {
            "required": True,
            "retaining_subsystem": retaining_subsystem,
            "followup_issue": followup_issue,
            "rule": "Do not increase the calibrated allowance. Identify the retaining subsystem with a heap/allocator/process probe and record a focused issue before accepting a later rerun.",
        }
        if not retaining_subsystem and not followup_issue:
            failures.append("retaining subsystem/focused issue not yet recorded")
    if failures:
        status = "fail"
    elif not calibration_matched:
        status = "not_applicable_for_phase0_calibration"
    elif not evidence_complete:
        status = "incomplete_evidence"
    else:
        status = "pass"
    document = {
        "schema_version": AGGREGATE_SCHEMA,
        "generated_at_utc": now_utc(),
        "status": status,
        "observational_only": True,
        "production_slo": False,
        "cross_machine_claim": False,
        "minimum_required_run_count": minimum_runs,
        "run_count": len(validated),
        "source_commit": source_commit,
        "source_tree": source_tree,
        "final_configuration_commit": source_commit,
        "comparison_method": {
            "post_warmup_only": True,
            "rolling_ranges": True,
            "final_window_delta": True,
            "robust_late_window_slope": "Theil-Sen median pairwise slope over the final rolling window",
            "calibrated_rss_pss_noise": "Issue #38 calibrated RSS advisory band is applied to RSS and, where exposed, PSS/private byte growth only after strict calibration applicability verification.",
            "run_level_outliers": "Robust cross-run peak/delta outliers are retained as diagnostic variability. They fail the plateau only when the same metric breaches its calibrated late-window material-growth rule.",
        },
        "configuration_identity": expected_identity,
        "calibration_noise": noise,
        "raw_evidence_archive": raw_evidence_archive,
        "raw_runs": raw_runs,
        "host_observations": host_observations,
        "host_reconciliation": {
            "all_runs_match": all(
                reconciliation["status"] == "pass"
                for reconciliation in host_reconciliation.values()
            ),
            "per_run": host_reconciliation,
        },
        "evidence_completeness": {
            "status": "complete" if evidence_complete else "incomplete",
            "rule": (
                "A conclusive retained soak requires complete raw/host identity and "
                "descriptor-lifecycle evidence in addition to a matched calibration."
            ),
            "limitations": evidence_limitations,
        },
        "hard_invariants": {
            "canonical_check_names": sorted(EXPECTED_CHECKS),
            "all_runs_passed": True,
            "per_batch_checks": {
                label: value["document"]["workload"]["batch_invariants_checked"]
                for label, value in validated.items()
            },
        },
        "workload": {
            label: value["document"]["workload"] for label, value in validated.items()
        },
        "metrics": metrics,
        "topology": topology,
        "file_descriptors": descriptors,
        "post_release": post_release,
        "post_shutdown": post_shutdown,
        "run_level_resource_outliers": identified_outliers,
        "material_run_level_outliers": material_outliers,
        "material_growth": material_growth,
        "investigation": investigation,
        "failures": failures,
        "unsupported_measurements": {
            name: metric.get("reason")
            for name, metric in metrics.items()
            if metric.get("availability") == "unsupported"
        },
    }
    if source_provenance is not None:
        document["source_provenance"] = {
            "schema_version": SOURCE_PROVENANCE_SCHEMA,
            "published_commit": source_commit,
            "published_tree": source_tree,
            **source_provenance,
            "execution_commit": execution_commit,
            "execution_tree": source_tree,
            "tree_identity_verified": True,
            "rule": (
                "The published source commit was resolved from the recorded durable origin "
                "branch or tag before any measured process began."
            ),
        }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_report.write_text(render_report(document, output_json), encoding="utf-8")
    return document, 0 if status == "pass" else 1


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def format_bytes(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "n/a"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    unit = 0
    while amount >= 1024 and unit < len(units) - 1:
        amount /= 1024
        unit += 1
    return f"{amount:.2f} {units[unit]} ({int(value)} bytes)"


def retained_state_limits(document: dict[str, Any]) -> list[tuple[str, Any, str]]:
    config = document["configuration_identity"]["config"]
    raw_has_limits = has_recorded_retained_state_limits(config)
    if raw_has_limits:
        source = "recorded raw config"
    else:
        if not is_known_legacy_soak_source(
            document["configuration_identity"]["source_identity"]
        ):
            fail(
                "retained-state fallback is restricted to the known "
                "6250b978/65ba3412 historical archive"
            )
        source = (
            "fixed harness bound verified only for known historical source "
            "6250b978/65ba3412 (v1 raw schema did not serialize this key)"
        )
    values = {
        key: config.get(key, legacy)
        for key, legacy in LEGACY_RETAINED_STATE_LIMITS.items()
    }
    first_release = next(iter(document["post_release"].values()))
    timing_limit = first_release["backend_timing_store"]["maximum_entries"]
    return [
        ("Component input", format_bytes(values["component_maximum_bytes"]), source),
        (
            "Prepared cache",
            f"{values['prepared_cache_maximum_entries']} entry; {format_bytes(values['prepared_cache_maximum_bytes'])}",
            source,
        ),
        (
            "Invocation log",
            f"{values['invocation_log_maximum_entries']} entries; {format_bytes(values['invocation_log_maximum_bytes'])}",
            source,
        ),
        (
            "Retained log",
            f"{values['retained_log_maximum_entries']} entries; {format_bytes(values['retained_log_maximum_bytes'])}",
            source,
        ),
        ("Backend timing store", f"{timing_limit} entries", "recorded raw snapshot"),
    ]


def render_report(document: dict[str, Any], raw_path: Path) -> str:
    identity = document["configuration_identity"]
    config = identity["config"]
    environment = identity["environment"]
    first_label = sorted(document["host_observations"])[0]
    first_host = document["host_observations"][first_label]["before"]
    host_context = first_host["host"]
    allocator_context = first_host.get("allocator")
    if allocator_context is None:
        allocator_context = (
            "unavailable in retained host observation; process report: "
            f"{environment['allocator_statistics']}"
        )
    status_label = {
        "pass": "PASS",
        "fail": "FAIL",
        "not_applicable_for_phase0_calibration": "NOT APPLICABLE FOR PHASE 0 CALIBRATION",
        "incomplete_evidence": "INCOMPLETE EVIDENCE",
    }.get(document["status"], document["status"].upper())
    lines = [
        "# Phase 0 native-Linux resource plateau soak",
        "",
        f"**Status:** {status_label}",
        f"**Schema:** `{document['schema_version']}`",
        f"**Generated:** {document['generated_at_utc']}",
        f"**Aggregate:** `{raw_path}`",
        "",
        "> Observational Phase 0 evidence only. This is not a production SLO, capacity guarantee, or cross-machine claim.",
        "",
        "## Source, repetitions, and exact commands",
        "",
        f"- Published final configuration commit: `{document['final_configuration_commit']}`",
        f"- Source tree: `{document['source_tree']}`",
        f"- Local execution commit shared by every retained process: `{identity['source_identity']['execution_commit']}`",
        f"- Independent native-Linux processes: {document['run_count']}",
        "",
        "Exact retained process commands:",
    ]
    for run in document["raw_runs"]:
        lines.append(f"- {run['label']}: `{' '.join(run['command'])}`")
    lines.extend(["", "## Reference environment and toolchain", ""])
    lines.extend(
        [
            "| Field | Recorded value |",
            "|---|---|",
            f"| Operating system / architecture | `{environment['operating_system']}` / `{environment['architecture']}` |",
            f"| CPU | {markdown_cell(environment['cpu_model'])} |",
            f"| Logical CPUs | {environment['logical_cpu_count']} |",
            f"| Memory | {format_bytes(environment['total_memory_bytes'])} |",
            f"| Kernel | {markdown_cell(environment['kernel'])} |",
            f"| Virtualization | {markdown_cell(host_context['virtualization'])} |",
            f"| Rust | {markdown_cell(environment['rustc'])} |",
            f"| Cargo | {markdown_cell(environment['cargo'])} |",
            f"| Target / build profile | `{environment['rust_target']}` / `{environment['build_profile']}` |",
            f"| Wasmtime | {markdown_cell(environment['wasmtime_version'])} |",
            f"| Allocator observation | {markdown_cell(allocator_context)} |",
            f"| Fixture | `{identity['component_digest']}` ({identity['component_bytes']} bytes) |",
        ]
    )
    lines.extend(["", "## Effective configuration, bounds, and sampling schedule", ""])
    lines.extend(
        [
            "| Setting | Effective value |",
            "|---|---|",
            f"| Warm-up activations (excluded) | {config['warmup_activations']} |",
            f"| Normal measured activations | {config['measured_activations']} |",
            f"| Normal activations per batch | {config['batch_size']} |",
            f"| Saturation interval | after every {config['saturation_every_batches']} normal batches |",
            f"| Fixed pool / queue capacity | {config['pool_capacity']} / {config['pool_queue_capacity']} |",
            f"| Runtime workers | {config['runtime_workers']} |",
            f"| Fuel | {config['fuel']} |",
            f"| Memory grant / pressure grant | {format_bytes(config['memory_bytes'])} / {format_bytes(config['memory_pressure_bytes'])} |",
            f"| Timeout / cancellation delay | {config['timeout_ms']} ms / {config['cancel_after_ms']} ms |",
            f"| Prepared cache / Wasmtime allocator / initialized-memory COW | `{str(config['prepared_cache_enabled']).lower()}` / `{config['wasmtime_instance_allocator']}` / `{str(config['wasmtime_copy_on_write_images']).lower()}` |",
        ]
    )
    lines.extend(["", "Retained-state numeric bounds:", "", "| State | Limit | Evidence source |", "|---|---|---|"])
    for name, value, source in retained_state_limits(document):
        lines.append(f"| {name} | {value} | {source} |")
    workload = document["workload"][first_label]
    warmup_batches = workload["warmup_activations"] // config["batch_size"]
    normal_batches = workload["normal_measured_activations"] // config["batch_size"]
    lines.extend(
        [
            "",
            "Sampling schedule:",
            f"- {warmup_batches} excluded warm-up checkpoints of {config['batch_size']} activations.",
            f"- {normal_batches} normal measured checkpoints of {config['batch_size']} activations.",
            f"- Every {config['saturation_every_batches']} normal checkpoints, one at-capacity batch ({config['pool_capacity']} activations) and one bounded-queue batch ({config['pool_capacity'] + config['pool_queue_capacity']} activations) run before their own checkpoints.",
            f"- Retained totals per process: {workload['saturation_batch_counts']['at_capacity']} at-capacity observations, {workload['saturation_batch_counts']['bounded_queue_saturation']} bounded-queue observations, {workload['saturation_activations']} additional saturation activations, and {workload['batch_invariants_checked']} batch-invariant checkpoints (plus post-prepare and post-release snapshots).",
        ]
    )
    lines.extend(["", "## Raw evidence", ""])
    raw_evidence_archive = document.get("raw_evidence_archive")
    if raw_evidence_archive:
        lines.extend(
            [
                "The raw paths below are losslessly retained in `{}`; verify its `{}` and extract it before inspection.".format(
                    raw_evidence_archive["path"], raw_evidence_archive["manifest"]
                ),
                "",
            ]
        )
    lines.extend(["| Run | Raw file | SHA-256 | Component digest |", "|---|---|---|---|"])
    report_base = raw_path.parent
    for run in document["raw_runs"]:
        lines.append(
            "| {label} | `{raw}` | `{sha}` | `{component}` |".format(
                label=run["label"],
                raw=relative_path(Path(run["raw_json"]), report_base),
                sha=run["sha256"],
                component=run["artifact"]["component_digest"],
            )
        )
    applicability = document["calibration_noise"]["applicability"]
    lines.extend(["", "## Calibration applicability and plateau analysis", ""])
    if applicability["status"] == "matched":
        lines.append("The issue #38 host/configuration identity is strictly matched, so its byte-scale advisory bands are applied to RSS, VM, and available PSS/private metrics.")
    else:
        lines.append("**Calibration is not applicable:** the issue #38 bands are not applied because the required identity is not fully matched and recorded. This archive cannot authorize Phase 0.")
        for mismatch in applicability["mismatches"]:
            lines.append(
                "- `{}`: calibration `{}`; soak `{}` ({}).".format(
                    mismatch["field"],
                    markdown_cell(mismatch["calibration"]),
                    markdown_cell(mismatch["soak"]),
                    mismatch["reason"],
                )
            )
    completeness = document["evidence_completeness"]
    reconciliation = document["host_reconciliation"]
    if completeness["status"] == "complete":
        lines.append(
            "The raw process environment reconciles with every before/after host observation, and complete descriptor-lifecycle baselines are retained."
        )
    else:
        lines.append(
            "**INCOMPLETE retained evidence:** a future archive must retain the missing identity or descriptor-lifecycle fields before it can support a conclusive plateau claim."
        )
        grouped_limitations: dict[str, list[str]] = {}
        for limitation in completeness["limitations"]:
            label, separator, reason = limitation.partition(": ")
            if separator and re.fullmatch(r"run-\d+", label):
                grouped_limitations.setdefault(reason, []).append(label)
            else:
                grouped_limitations.setdefault(limitation, [])
        for reason, labels in grouped_limitations.items():
            prefix = f"{', '.join(labels)}: " if labels else ""
            lines.append(f"- {prefix}{reason}.")
    lines.append(
        "Host reconciliation: **{}**.".format(
            "PASS" if reconciliation["all_runs_match"] else "INCOMPLETE"
        )
    )
    lines.extend(
        [
            "",
            "The raw interval series retains rolling ranges, peak, final-window delta, and a Theil-Sen robust late-window slope per run. PSS/private use the RSS byte-scale band only when calibration applicability is matched because #38 did not collect separate PSS/private bands.",
            "",
            "| Metric | Availability | Peak median | Final-window delta median | Late slope median | Decision |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for name, metric in document["metrics"].items():
        if metric.get("availability") == "unsupported":
            lines.append(f"| {name} | unsupported | n/a | n/a | n/a | {metric['reason']} |")
            continue
        decision = metric["decision"]
        lines.append(
            "| {name} | available | {peak:.1f} | {delta:.1f} | {slope:.4f} | {status} |".format(
                name=name,
                peak=metric["peaks"]["median"],
                delta=metric["final_window_deltas"]["median"],
                slope=metric["robust_late_window_slopes"]["median"],
                status=decision["status"],
            )
        )
    lines.extend(["", "## Run-level variability", ""])
    outliers = document["run_level_resource_outliers"]
    if not outliers:
        lines.append("No robust cross-run peak or final-window-delta outlier was identified.")
    else:
        lines.append("Robust outliers are retained for review. They are not discarded or silently relabelled.")
        for name, labels in outliers.items():
            metric = document["metrics"][name]
            decision = metric.get("decision", {})
            if decision.get("status") == "pass":
                assessment = "within calibrated late-window bound"
            elif decision.get("status") == "observed":
                assessment = "diagnostic metric without an applicable calibrated growth band"
            else:
                assessment = "also breaches the material-growth rule"
            lines.append(f"- {name}: {', '.join(labels)} ({assessment}).")
    lines.extend(["", "## Topology, descriptors, explicit release, and shutdown", ""])
    lines.append(
        "File descriptors: **{}**; {}.".format(
            document["file_descriptors"]["status"].upper(),
            document["file_descriptors"]["rule"],
        )
    )
    lifecycle = document["file_descriptors"]["lifecycle_baselines"]
    lines.append(
        "Descriptor lifecycle baselines: **{}**; {}.".format(
            lifecycle["status"].upper(), lifecycle["rule"]
        )
    )
    lines.extend(
        [
            "",
            "| Run | Pre-runtime FDs | Post-warm-up FDs | Final measured FDs | Post-release FDs | Post-shutdown FDs | Lifecycle status |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for label, values in lifecycle["per_run"].items():
        lines.append(
            "| {label} | {pre_runtime} | {prepared} | {final} | {release} | {shutdown} | {status} |".format(
                label=label,
                pre_runtime=("n/a" if values["pre_runtime"] is None else values["pre_runtime"]),
                prepared=(
                    "n/a"
                    if values["prepared_baseline"] is None
                    else values["prepared_baseline"]
                ),
                final=values["final_measured"],
                release=values["post_release"],
                shutdown=values["post_shutdown"],
                status=values["status"],
            )
        )
    for name, analysis in document["topology"].items():
        lines.append(f"- measured {name}: **{analysis['status'].upper()}**")
    lines.extend(
        [
            "",
            "| Run | Stage | Proc. | Children | Threads | FDs | Open sockets | Listeners | RSS | PSS | Private | VM |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for label in sorted(document["post_release"]):
        for stage, snapshot in (
            ("post-release", document["post_release"][label]["process"]),
            ("post-shutdown", document["post_shutdown"][label]["process"]),
        ):
            lines.append(
                "| {label} | {stage} | {process_count} | {child_process_count} | {thread_count} | {file_descriptor_count} | {open_socket_count} | {listening_socket_count} | {rss} | {pss} | {private} | {virtual} |".format(
                    label=label,
                    stage=stage,
                    process_count=snapshot["process_count"],
                    child_process_count=snapshot["child_process_count"],
                    thread_count=snapshot["thread_count"],
                    file_descriptor_count=snapshot["file_descriptor_count"],
                    open_socket_count=snapshot["open_socket_count"],
                    listening_socket_count=snapshot["listening_socket_count"],
                    rss=format_bytes(snapshot["rss_bytes"]),
                    pss=format_bytes(snapshot["pss_bytes"]),
                    private=format_bytes(snapshot["private_bytes"]),
                    virtual=format_bytes(snapshot["virtual_memory_bytes"]),
                )
            )
    lines.extend(["", "## Method and explicit limits", ""])
    lines.extend(
        [
            "- The command is explicit native-Linux soak work and intentionally does not run in shared PR smoke CI.",
            "- Every normal and saturation batch uses the real shared Phase 0 runtime, bounded fixed pool, Wasmtime backend, prepared cache, activation runner, and a fresh store per activation.",
            "- The runner fails on WSL, a container, missing required Linux process/socket probes, a dirty tree, source/tree mismatch, unavailable fixture/toolchain input, test-only output, or an existing archive destination.",
            "- The aggregate rejects missing/duplicate hard checks, mismatched execution commit/tree or run index, raw/host environment disagreement, missing samples, saturation-count/activation-counter disagreement, changed measured topology, measured-window FD growth, a post-release-to-shutdown FD increase, a descriptor value above its retained lifecycle baseline, and invalid terminal process topology.",
            "- New archives must retain the selected prepared-cache, Wasmtime allocator, initialized-memory COW, retained-state-limit, raw virtualization, pre-runtime, and post-warm-up descriptor-baseline fields. The sole 6250b978/65ba3412 historical fallback is explicitly incomplete where it cannot prove a lifecycle comparison.",
            "- A material calibrated growth result must identify a retaining subsystem or focused issue; the allowance is never raised to clear a run.",
        ]
    )
    lines.extend(["", "## Unsupported measurements and conclusions", ""])
    lines.extend(
        [
            "- Allocator-internal statistics are unsupported until a safe allocator-specific probe is configured.",
            "- This finite single-host process evidence does not prove arbitrary-duration leak freedom, multi-node behavior, cluster scaling, 100,000-service density, state throughput, remote-call latency, networking, autoscaling, or call-graph fusion.",
            "- It is not a production SLO, release promise, capacity guarantee, competitive-performance result, cross-machine result, or cross-platform result.",
            "- An archive without a strictly matched calibration must not be used to claim that its RSS/PSS/private/VM series is inside the #38 advisory band.",
        ]
    )
    if document["failures"]:
        lines.extend(["", "## Required follow-up", ""])
        for failure in document["failures"]:
            lines.append(f"- {failure}")
        investigation = document.get("investigation")
        if investigation:
            lines.append("- Do not increase the noise allowance. Record heap/allocator/process evidence and a focused retaining-subsystem issue before accepting a rerun.")
            if investigation.get("retaining_subsystem"):
                lines.append(f"- Retaining subsystem: {investigation['retaining_subsystem']}")
            if investigation.get("followup_issue"):
                lines.append(f"- Focused issue: {investigation['followup_issue']}")
    else:
        lines.extend(["", "## Conclusion", ""])
        if document["status"] == "pass":
            lines.append("All independent native-Linux processes passed every hard invariant, the full measured and terminal FD checks, and bounded topology validation; no calibrated material RSS/PSS/private/VM growth was detected for the strictly matched configuration. This is a Phase 0 plateau observation for the recorded configuration, not a production claim.")
        elif document["status"] == "not_applicable_for_phase0_calibration":
            lines.append(
                "All retained processes pass hard invariants, measured topology, and the retained terminal shutdown checks, but the strict #38 identity does not apply. This archive is not eligible for Phase 0 authorization and must be replaced by a fresh fully matched archive."
            )
        elif document["status"] == "incomplete_evidence":
            lines.append(
                "The retained measurements are incomplete for Phase 0 authorization and must be replaced by a fresh complete archive."
            )
    return "\n".join(lines) + "\n"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    capture = subcommands.add_parser("capture-host")
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--phase", choices=("before", "after"), required=True)
    capture.add_argument("--run-index", type=int, required=True)
    capture.add_argument("--source-commit", required=True)
    capture.add_argument("--source-tree", required=True)
    capture.add_argument("--published-source-ref")
    capture.add_argument("--published-source-ref-head")
    capture.add_argument("--execution-commit", required=True)
    capture.add_argument("--execution-tree", required=True)
    aggregate_parser = subcommands.add_parser("aggregate")
    aggregate_parser.add_argument("--runs-directory", type=Path, required=True)
    aggregate_parser.add_argument("--output-json", type=Path, required=True)
    aggregate_parser.add_argument("--output-report", type=Path, required=True)
    aggregate_parser.add_argument("--source-commit", required=True)
    aggregate_parser.add_argument("--source-tree", required=True)
    aggregate_parser.add_argument("--calibration", type=Path, required=True)
    aggregate_parser.add_argument("--minimum-runs", type=int, default=MINIMUM_RUNS)
    aggregate_parser.add_argument("--retaining-subsystem")
    aggregate_parser.add_argument("--followup-issue")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        if arguments.command == "capture-host":
            capture_host_observation(
                arguments.output,
                arguments.phase,
                arguments.run_index,
                arguments.source_commit,
                arguments.source_tree,
                arguments.execution_commit,
                arguments.execution_tree,
                arguments.published_source_ref,
                arguments.published_source_ref_head,
            )
            return 0
        _, status = aggregate(
            arguments.runs_directory,
            arguments.output_json,
            arguments.output_report,
            arguments.source_commit,
            arguments.source_tree,
            arguments.calibration,
            arguments.minimum_runs,
            arguments.retaining_subsystem,
            arguments.followup_issue,
        )
        return status
    except SoakError as error:
        print(f"Phase 0 resource soak aggregation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
