#!/usr/bin/env python3
"""Validate and summarize native-Linux Phase 0 hot-path profile evidence.

This is deliberately separate from the Phase 0 correctness baseline.  The
baseline remains the owner of containment, topology, cleanup, and reclamation
assertions; this tool refuses a profile or experiment whose corresponding
baseline document did not pass every one of those checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, NoReturn

try:  # Support both ``python tools/...`` and package-style imports.
    from . import aggregate_phase0_calibration as calibration_aggregate
except ImportError:  # pragma: no cover - exercised by the command-line entrypoint.
    import aggregate_phase0_calibration as calibration_aggregate


BASELINE_SCHEMA = "latent.phase0.baseline.v2"
TARGETED_PROFILE_SCHEMA = "latent.phase0.targeted-profile.v2"
HOST_SCHEMA = "latent.phase0.hot-path.host-observation.v2"
PROFILE_SCHEMA = "latent.phase0.hot-path.aggregate.v5"
HEAPTRACK_ATTRIBUTION_SCHEMA = "latent.phase0.hot-path.heaptrack-attribution.v3"
MEASUREMENT_IDENTITY_SCHEMA = "latent.phase0.measurement-identity.v1"
MINIMUM_ADOPTION_RUNS = 7
MINIMUM_EXPERIMENT_RUNS = 3
REFERENCE_CANDIDATE = "worker-cell-2w-2c"

# Every retained process has its own baseline document.  These fields make the
# machine/toolchain context in each document auditable rather than relying only
# on the single wrapper-level host observation.
RUN_ENVIRONMENT_FIELDS = (
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
    "repository_commit",
)

# A selective profiler intentionally changes only its workload boundary,
# profiler-friendly cooperative polling, and the number of samples it takes at
# that boundary.  Every other effective configuration field is part of the
# real Phase 0 composition and must agree with the full proof.
PROFILE_SAMPLING_CONFIGURATION_FIELDS = frozenset(
    {
        "profile_workload",
        "coordination_poll_interval_ms",
        "warm_samples",
        "sequence_repetitions",
        "throughput_batches",
        "pool_iterations",
    }
)

DEFAULT_FULL_CONFIGURATION: dict[str, Any] = {
    "mode": "full",
    "profile_workload": None,
    "pool_capacity": 2,
    "pool_queue_capacity": 4,
    "runtime_workers": 2,
    "warm_samples": 40,
    "sequence_repetitions": 10,
    "throughput_batches": 24,
    "pool_iterations": 2_000,
    "fuel": 1_000_000_000_000,
    "memory_bytes": 16 * 1024 * 1024,
    "memory_pressure_bytes": 4 * 1024 * 1024,
    "timeout_ms": 25,
    "cancel_after_ms": 5,
    "maximum_overshoot_ms": 500,
    "coordination_timeout_ms": 2_000,
    "coordination_poll_interval_ms": 0,
    "rss_growth_allowance_bytes": 64 * 1024 * 1024,
    "fd_growth_allowance": 2,
    "wasmtime_allocator": "on_demand",
    "wasmtime_copy_on_write_images": True,
    "prepared_cache_enabled": True,
}

PROFILE_WORKLOADS = (
    "cold-preparation",
    "prepared-cache-reuse",
    "first-activation",
    "warm-execution",
    "failure-containment",
    "cleanup",
    "at-capacity-contention",
    "queued-contention",
)

# These are intentionally asserted from the raw targeted document instead of
# trusting six differently named directories.  They map one-to-one to the
# `ProfileWorkload` branches in `phase0-baseline` and make a broad full-process
# run or a relabelled profile invalid evidence.
PROFILE_WORKLOAD_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "cold-preparation": {
        "semantics": "capsule validation, engine construction, and first prepared-component creation only",
        "scenarios": frozenset(),
    },
    "prepared-cache-reuse": {
        "semantics": "one cold prepared component followed by one same-key bounded-cache reuse probe; no activation, failure sequence, pool probe, or throughput",
        "scenarios": frozenset({"prepared_cache_reuse"}),
    },
    "first-activation": {
        "semantics": "one first echo after preparation; no warm loop, mixed failures, pool probe, or throughput",
        "scenarios": frozenset({"retained_first_echo"}),
    },
    "warm-execution": {
        "semantics": "repeated successful warm echoes after one preparation; no failure sequence, pool probe, or throughput",
        "scenarios": frozenset({"warm_echo"}),
    },
    "failure-containment": {
        "semantics": "trap, timeout, cancellation, and memory-pressure failures with immediate cause-specific recovery",
        "scenarios": frozenset(
            {
                "sequence_echo",
                "domain_error",
                "recovery_after_domain_error",
                "trap",
                "recovery_after_trap",
                "timeout",
                "recovery_after_timeout",
                "cancellation",
                "recovery_after_cancellation",
                "memory_pressure",
                "recovery_after_memory_pressure",
            }
        ),
    },
    "cleanup": {
        "semantics": "successful activations followed by per-activation resource reclamation, cell disposition, and explicit prepared release",
        "scenarios": frozenset({"cleanup_echo"}),
    },
    "at-capacity-contention": {
        "semantics": "real at-capacity activation batches only; no bounded-queue batch, pool microprobe, or mixed failure sequence",
        "scenarios": frozenset({"throughput_at_capacity"}),
    },
    "queued-contention": {
        "semantics": "real bounded-queue saturation batches only; no at-capacity batch, pool microprobe, or mixed failure sequence",
        "scenarios": frozenset({"throughput_bounded_queue_saturation"}),
    },
}

CANDIDATE_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "worker-cell-1w-1c": {
        "runtime_workers": 1,
        "pool_capacity": 1,
        "wasmtime_allocator": "on_demand",
        "wasmtime_copy_on_write_images": True,
        "prepared_cache_enabled": True,
    },
    "worker-cell-2w-2c": {
        "runtime_workers": 2,
        "pool_capacity": 2,
        "wasmtime_allocator": "on_demand",
        "wasmtime_copy_on_write_images": True,
        "prepared_cache_enabled": True,
    },
    "worker-cell-2w-4c": {
        "runtime_workers": 2,
        "pool_capacity": 4,
        "wasmtime_allocator": "on_demand",
        "wasmtime_copy_on_write_images": True,
        "prepared_cache_enabled": True,
    },
    "worker-cell-4w-2c": {
        "runtime_workers": 4,
        "pool_capacity": 2,
        "wasmtime_allocator": "on_demand",
        "wasmtime_copy_on_write_images": True,
        "prepared_cache_enabled": True,
    },
    "on-demand-cow-disabled": {
        "runtime_workers": 2,
        "pool_capacity": 2,
        "wasmtime_allocator": "on_demand",
        "wasmtime_copy_on_write_images": False,
        "prepared_cache_enabled": True,
    },
    "pooling-cow-disabled": {
        "runtime_workers": 2,
        "pool_capacity": 2,
        "wasmtime_allocator": "pooling",
        "wasmtime_copy_on_write_images": False,
        "prepared_cache_enabled": True,
    },
    "pooling-cow-enabled": {
        "runtime_workers": 2,
        "pool_capacity": 2,
        "wasmtime_allocator": "pooling",
        "wasmtime_copy_on_write_images": True,
        "prepared_cache_enabled": True,
    },
    "prepared-cache-disabled": {
        "runtime_workers": 2,
        "pool_capacity": 2,
        "wasmtime_allocator": "on_demand",
        "wasmtime_copy_on_write_images": True,
        "prepared_cache_enabled": False,
    },
}

METRIC_TO_CALIBRATION = {
    "component_preparation_micros": "component_preparation_micros",
    "warm_echo_p50_micros": "warm_activation_elapsed_micros",
    "post_invocation_cleanup_p50_micros": "post_invocation_cleanup_micros",
    "at_capacity_activations_per_second": "at_capacity_activations_per_second",
    "bounded_queue_activations_per_second": "bounded_queue_saturation_activations_per_second",
    "peak_rss_bytes": "process_peak_rss_bytes",
    "peak_virtual_memory_bytes": "process_peak_virtual_memory_bytes",
}

ATTRIBUTION_RULES: dict[str, tuple[str, ...]] = {
    "capsule parsing and digest validation": (
        "load_phase0_artifact",
        "validate_requested_budget",
        "sha256_digest",
        "capsuledocument",
    ),
    # This category intentionally precedes the broad Wasmtime preparation
    # category.  It never matches the word "component" on its own: that
    # previously attributed Cranelift compilation frames to WIT conversion.
    "WIT lifting, lowering, and payload copies": (
        "wasmtime::component::func",
        "wasmtime::component::values",
        "canonical_abi",
        "canon_lift",
        "canon_lower",
    ),
    "activation envelope and metadata handling": (
        "phase0_activation_envelope",
        "activationenvelope",
        "activation_id",
        "invocationtarget",
    ),
    "host context and log calls": (
        "activationhostcontext",
        "boundedlogsink",
        "host_call_timing",
        "hostcall_fuel_limit",
    ),
    "result mapping and diagnostics": (
        "classify_outcome",
        "map_guest_outcome",
        "map_platform_error",
        "render_diagnostic",
        "format_diagnostic",
    ),
    "resource reclamation and cell disposition": (
        "activation_resource_reclamation",
        "cell_disposition",
        "temporary_buffer",
        "reusable_proof",
        "phase0wasmtimebackend::release",
    ),
    "pool/queue coordination and runtime scheduling": (
        "fixedcellpool",
        "timingcellpool",
        "throughputsaturationgate",
        "run_throughput_mode",
        "tokio::runtime",
    ),
    "store, limiter, host state, instance, and import construction": (
        "instantiate_async",
        "wasmtime::store",
        "hoststate",
        "linker::",
        "resource_limiter",
    ),
    "Wasmtime engine and component preparation": (
        "phase0wasmtimeenginefactory",
        "phase0wasmtimebackend::prepare",
        "prepare_inner",
        "cranelift::",
        "cranelift_",
        "wasmtime::engine",
    ),
}

# Heaptrack's folded format is root-to-leaf.  The leaf-side frames commonly
# describe Rust's allocator, generic containers, libc, or Tokio's executor;
# none of those is a reliable owner of an allocation in a Phase 0 path.  Skip
# those frames before selecting the closest remaining frame as the allocation
# owner.  Keep this list deliberately structural: category patterns below
# describe concrete operations, never generic result/error type names.
ALLOCATION_OWNER_PLUMBING_PATTERNS = (
    # Native and Rust allocator implementation.
    "__rust_alloc",
    "__rdl_alloc",
    "malloc",
    "calloc",
    "realloc",
    "memalign",
    "operator new",
    "jemalloc",
    "mimalloc",
    "alloc::alloc",
    "alloc5alloc",
    "alloc::raw_vec",
    "alloc7raw_vec",
    "alloc::vec",
    "alloc3vec",
    "alloc::boxed",
    "alloc5boxed",
    "alloc::sync",
    "alloc4sync",
    "core::alloc",
    "core5alloc",
    "std::alloc",
    "std3alloc",
    # Generic collection and language-runtime implementation.
    "hashbrown",
    "std::collections",
    "std11collections",
    "core::result",
    "core6result",
    "core::future",
    "core6future",
    "core::task",
    "core4task",
    "core::ops::function",
    "core3ops8function",
    "std::panicking",
    "std9panicking",
    "std::panic",
    "std5panic",
    "std::rt",
    "std2rt",
    "std::sys",
    "std3sys",
    "std::thread",
    "std6thread",
    # Tokio executor/task frames are runtime plumbing for allocation ownership.
    # They remain a valid CPU-symbol category below.
    "tokio::runtime",
    "tokio7runtime",
    "tokio::task",
    "tokio4task",
    "tokio::util",
    "tokio4util",
    # Dynamic-loader and pthread allocation machinery.
    "libc.so",
    "__gi_",
    "pthread",
    "dl_allocate_tls",
    "allocate_dtv",
)

HEAPTRACK_OWNER_SELECTION = (
    "Heaptrack folded stacks are root-to-leaf. The classifier scans from the "
    "allocation leaf toward the root, skips allocator/container/runtime plumbing, "
    "selects the first remaining owner frame, and applies category precedence only "
    "within that one frame."
)


class HotPathError(Exception):
    """The profile archive is incomplete, malformed, or unsafe to interpret."""


def fail(message: str) -> NoReturn:
    raise HotPathError(message)


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def first_difference(expected: Any, actual: Any, path: str = "$") -> str:
    """Return one compact, deterministic identity difference for diagnostics."""
    if type(expected) is not type(actual):
        return (
            f"{path} type expected={type(expected).__name__} "
            f"observed={type(actual).__name__}"
        )
    if isinstance(expected, dict):
        expected_keys = set(expected)
        actual_keys = set(actual)
        if expected_keys != actual_keys:
            return (
                f"{path} keys missing={sorted(expected_keys - actual_keys)} "
                f"extra={sorted(actual_keys - expected_keys)}"
            )
        for key in sorted(expected):
            difference = first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return ""
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path} length expected={len(expected)} observed={len(actual)}"
        for index, (expected_value, actual_value) in enumerate(zip(expected, actual, strict=True)):
            difference = first_difference(expected_value, actual_value, f"{path}[{index}]")
            if difference:
                return difference
        return ""
    return "" if expected == actual else f"{path} expected={expected!r} observed={actual!r}"


def require_measurement_identity(
    document: dict[str, Any], label: str, *, exclude_sampling: bool
) -> dict[str, Any]:
    """Derive the artifact and effective-composition identity from one raw run.

    This is intentionally derived from the raw baseline/targeted document, not
    supplied by a caller.  That prevents a report from pairing a CPU trace,
    Heaptrack trace, or full proof collected from different artifacts or
    runtime configurations.
    """
    artifact = document.get("artifact")
    if not isinstance(artifact, dict):
        fail(f"{label} has no artifact identity")
    component_digest = artifact.get("component_digest")
    component_bytes = artifact.get("component_bytes")
    capsule_digest = artifact.get("capsule_digest")
    capsule_bytes = artifact.get("capsule_bytes")
    if not isinstance(component_digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", component_digest) is None:
        fail(f"{label} has an invalid artifact component digest")
    if not isinstance(component_bytes, int) or isinstance(component_bytes, bool) or component_bytes <= 0:
        fail(f"{label} has an invalid artifact component byte count")
    if not isinstance(capsule_digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", capsule_digest) is None:
        fail(f"{label} has an invalid artifact capsule digest")
    if not isinstance(capsule_bytes, int) or isinstance(capsule_bytes, bool) or capsule_bytes <= 0:
        fail(f"{label} has an invalid artifact capsule byte count")

    configuration = document.get("config")
    if not isinstance(configuration, dict):
        fail(f"{label} has no effective configuration")
    identity_configuration = {
        key: value
        for key, value in configuration.items()
        if not exclude_sampling or key not in PROFILE_SAMPLING_CONFIGURATION_FIELDS
    }
    if not identity_configuration:
        fail(f"{label} has no invariant-relevant configuration")
    return {
        "schema_version": MEASUREMENT_IDENTITY_SCHEMA,
        "artifact": {
            "component_digest": component_digest,
            "component_bytes": component_bytes,
            "capsule_digest": capsule_digest,
            "capsule_bytes": capsule_bytes,
        },
        "configuration": identity_configuration,
    }


def require_identity_match(
    expected: dict[str, Any], observed: dict[str, Any], label: str
) -> None:
    if stable_json(expected) != stable_json(observed):
        fail(f"{label} measurement identity mismatch: {first_difference(expected, observed)}")


def require_host_identity_match(
    expected: dict[str, Any], observed: dict[str, Any], label: str
) -> None:
    if stable_json(expected) != stable_json(observed):
        fail(f"{label} static host identity mismatch: {first_difference(expected, observed)}")


def require_exact_configuration(
    actual: Any, expected: dict[str, Any], label: str
) -> dict[str, Any]:
    if not isinstance(actual, dict):
        fail(f"{label} has no effective configuration")
    if stable_json(actual) != stable_json(expected):
        fail(
            f"{label} configuration is not the fixed Phase 0 composition: "
            f"{first_difference(expected, actual)}"
        )
    return actual


def candidate_configuration(name: str) -> dict[str, Any]:
    configuration = dict(DEFAULT_FULL_CONFIGURATION)
    configuration.update(CANDIDATE_EXPECTATIONS[name])
    return configuration


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def archive_path(path: Path, archive_root: Path) -> str:
    """Return a stable, portable path from the checked-in archive root."""
    return os.path.relpath(path.resolve(), start=archive_root.resolve())


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        fail(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"{label} is not valid JSON ({path}): {error}")
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object: {path}")
    return value


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
    output = completed.stdout.strip() or completed.stderr.strip()
    return output if output else ("none" if completed.returncode == 0 else "unavailable")


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


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


def cpu_model_from_proc_cpuinfo(contents: str | None) -> str:
    if contents is None:
        return "unknown"
    for line in contents.splitlines():
        for prefix in ("model name\t: ", "Hardware\t: "):
            if line.startswith(prefix):
                return line.removeprefix(prefix)
    return "unknown"


def cpu_model() -> str:
    return cpu_model_from_proc_cpuinfo(read_text(Path("/proc/cpuinfo")))


def logical_cpu_count() -> int | None:
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count()


def capture_host(
    output: Path,
    source_commit: str,
    source_tree: str,
    source_ref: str,
    source_ref_head: str,
    repository_root: Path,
) -> None:
    kernel_text = "\n".join(
        filter(
            None,
            [read_text(Path("/proc/sys/kernel/osrelease")), read_text(Path("/proc/version"))],
        )
    ).lower()
    container = command_output(["systemd-detect-virt", "--container"])
    virtualization = command_output(["systemd-detect-virt"])
    virtual_machine = command_output(["systemd-detect-virt", "--vm"])
    tools = {
        "perf": command_output(["perf", "--version"]),
        "heaptrack": command_output(["heaptrack", "--version"]),
        "heaptrack_print": command_output(["heaptrack_print", "--version"]),
        "python": command_output([sys.executable, "--version"]),
        "rustc": command_output(["rustc", "--version"]),
        "cargo": command_output(["cargo", "--version"]),
    }
    memory = parse_meminfo()
    payload = {
        "schema_version": HOST_SCHEMA,
        "captured_at_utc": now_utc(),
        "source_commit": source_commit,
        "source_tree": source_tree,
        "published_source_ref": source_ref,
        "published_source_ref_head": source_ref_head,
        "operating_system": platform.system().lower(),
        "architecture": platform.machine(),
        "kernel": command_output(["uname", "-srvmo"]),
        "native_linux_reference": (
            platform.system() == "Linux"
            and "microsoft" not in kernel_text
            and "wsl" not in kernel_text
            and container == "none"
        ),
        "virtualization": {
            "systemd_detect_virt": virtualization,
            "systemd_detect_virt_container": container,
            "systemd_detect_virt_vm": virtual_machine,
            "wsl_detected": "microsoft" in kernel_text or "wsl" in kernel_text,
        },
        "machine": {
            "cpu_model": cpu_model(),
            "logical_cpu_count": logical_cpu_count(),
            "total_memory_bytes": memory.get("MemTotal"),
            "memory": memory,
        },
        "tools": tools,
        # Reuse the calibration collector's exact static-host observations so
        # a profile cannot become calibration-comparable on a different CPU,
        # virtualization layer, allocator, or frequency/power policy.
        "cpu_frequency_policy": calibration_aggregate.cpu_frequency_policy(),
        "allocator": calibration_aggregate.allocator_observation(repository_root),
        "repository_root": str(repository_root),
    }
    write_json(output, payload)


def check_names(document: dict[str, Any], label: str, expected: set[str] | None) -> set[str]:
    checks = document.get("checks")
    if not isinstance(checks, list) or not checks:
        fail(f"{label} contains no hard checks")
    names: list[str] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            fail(f"{label} hard check {index} is not an object")
        name = check.get("name")
        if not isinstance(name, str) or not name:
            fail(f"{label} hard check {index} lacks a name")
        if check.get("passed") is not True:
            fail(f"{label} failed hard check: {name}")
        names.append(name)
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        fail(f"{label} repeats hard checks: {', '.join(duplicates)}")
    observed = set(names)
    if expected is not None and observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        fail(
            f"{label} has a different hard-check set; "
            f"missing={missing or 'none'}, unexpected={unexpected or 'none'}"
        )
    return observed


def verify_baseline(document: dict[str, Any], label: str, expected_checks: set[str] | None) -> set[str]:
    if document.get("schema_version") != BASELINE_SCHEMA:
        fail(f"{label} has unexpected baseline schema: {document.get('schema_version')!r}")
    if document.get("status") != "pass":
        fail(f"{label} is not a passing baseline document")
    return check_names(document, label, expected_checks)


def host_runtime_identity(host: dict[str, Any], label: str) -> dict[str, Any]:
    """Return the process-visible machine identity captured beside a run."""
    strings = ("operating_system", "architecture", "kernel")
    identity: dict[str, Any] = {}
    for field in strings:
        value = host.get(field)
        if not isinstance(value, str) or not value.strip():
            fail(f"{label} has no usable {field}")
        identity[field] = value
    machine = host.get("machine")
    if not isinstance(machine, dict):
        fail(f"{label} has no machine identity")
    cpu_model = machine.get("cpu_model")
    if (
        not isinstance(cpu_model, str)
        or not cpu_model.strip()
        or calibration_aggregate.NON_MEANINGFUL_CPU_MODEL_PATTERN.match(
            cpu_model.strip()
        )
    ):
        fail(f"{label} has no usable CPU model")
    logical_cpus = machine.get("logical_cpu_count")
    if not isinstance(logical_cpus, int) or isinstance(logical_cpus, bool) or logical_cpus <= 0:
        fail(f"{label} has an invalid logical CPU count")
    total_memory = machine.get("total_memory_bytes")
    if not isinstance(total_memory, int) or isinstance(total_memory, bool) or total_memory <= 0:
        fail(f"{label} host observation has an invalid total memory value")
    identity.update(
        {
            "cpu_model": cpu_model,
            "logical_cpu_count": logical_cpus,
            "total_memory_bytes": total_memory,
        }
    )
    return identity


def verify_run_environment(
    document: dict[str, Any],
    label: str,
    host: dict[str, Any],
    expected_environment: dict[str, Any] | None,
    execution_commit: str,
) -> dict[str, Any]:
    """Require a complete, stable per-process runtime/host identity."""
    environment = document.get("environment")
    if not isinstance(environment, dict):
        fail(f"{label} has no per-run environment context")
    missing = [field for field in RUN_ENVIRONMENT_FIELDS if field not in environment]
    if missing:
        fail(f"{label} lacks per-run environment fields: {', '.join(missing)}")
    for field in (
        "operating_system",
        "architecture",
        "kernel",
        "cpu_model",
        "rustc",
        "cargo",
        "rust_target",
        "build_profile",
        "wasmtime_version",
    ):
        if not isinstance(environment.get(field), str) or not environment[field].strip():
            fail(f"{label} has an incomplete per-run environment field: {field}")
    for field in ("logical_cpu_count", "total_memory_bytes"):
        value = environment.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            fail(f"{label} has an invalid per-run environment field: {field}")
    repository_commit = environment.get("repository_commit")
    if not isinstance(repository_commit, str) or re.fullmatch(r"[0-9a-f]{40}", repository_commit) is None:
        fail(f"{label} has an invalid per-run environment field: repository_commit")
    if environment.get("repository_commit") != execution_commit:
        fail(
            f"{label} repository commit does not match the verified execution commit"
        )
    for field, host_value in host_runtime_identity(host, label).items():
        if environment.get(field) != host_value:
            fail(f"{label} per-run environment differs from host observation: {field}")
    tools = host.get("tools")
    if not isinstance(tools, dict):
        fail("host observation lacks tool context")
    rustc = environment.get("rustc")
    if not isinstance(rustc, str) or rustc.splitlines()[0] != tools.get("rustc"):
        fail(f"{label} per-run Rust toolchain differs from host observation")
    if environment.get("cargo") != tools.get("cargo"):
        fail(f"{label} per-run Cargo toolchain differs from host observation")
    if expected_environment is not None and environment != expected_environment:
        fail(f"{label} per-run environment differs from the full-invariant proof")
    return environment


def command_arguments(command: dict[str, Any], label: str) -> list[str]:
    arguments = command.get("command")
    if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
        fail(f"{label} must retain the exact command array")
    if not any(Path(value).name == "phase0-baseline" for value in arguments):
        fail(f"{label} did not invoke phase0-baseline")
    return arguments


def command_option(arguments: list[str], name: str) -> str | None:
    try:
        index = arguments.index(name)
    except ValueError:
        return None
    return arguments[index + 1] if index + 1 < len(arguments) else None


def verify_command_identity(
    command: dict[str, Any],
    label: str,
    source_commit: str,
    source_tree: str,
    published_source_ref: str,
    published_source_ref_head: str,
    expected_execution_commit: str | None = None,
) -> list[str]:
    if command.get("schema_version") != "latent.phase0.hot-path.command.v1":
        fail(f"{label} has an unrecognized command schema")
    for key, expected in (
        ("source_commit", source_commit),
        ("source_tree", source_tree),
        ("published_source_ref", published_source_ref),
        ("published_source_ref_head", published_source_ref_head),
        ("execution_tree", source_tree),
    ):
        if command.get(key) != expected:
            fail(
                f"{label} source identity mismatch for {key}: "
                f"expected {expected!r}, observed {command.get(key)!r}"
            )
    execution_commit = command.get("execution_commit")
    ref_head = command.get("published_source_ref_head")
    for key, value in (
        ("source_commit", command.get("source_commit")),
        ("source_tree", command.get("source_tree")),
        ("execution_tree", command.get("execution_tree")),
    ):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
            fail(f"{label} has no valid {key}")
    if not isinstance(execution_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", execution_commit):
        fail(f"{label} has no valid execution commit")
    if expected_execution_commit is not None and execution_commit != expected_execution_commit:
        fail(
            f"{label} execution commit differs from the full-invariant proof: "
            f"expected {expected_execution_commit!r}, observed {execution_commit!r}"
        )
    if not isinstance(ref_head, str) or not re.fullmatch(r"[0-9a-f]{40}", ref_head):
        fail(f"{label} has no verified durable ref head")
    return command_arguments(command, label)


def verify_targeted_profile_document(
    document: dict[str, Any], label: str, workload: str
) -> None:
    if document.get("schema_version") != TARGETED_PROFILE_SCHEMA:
        fail(f"{label} has unexpected targeted-profile schema")
    if document.get("status") != "pass":
        fail(f"{label} is not a passing targeted profile")
    if document.get("profile_workload") != workload:
        fail(
            f"{label} workload mismatch: expected {workload!r}, "
            f"observed {document.get('profile_workload')!r}"
        )
    if document.get("full_invariant_proof_required") is not True:
        fail(f"{label} does not require its separate full-invariant proof")
    requirement = PROFILE_WORKLOAD_REQUIREMENTS[workload]
    semantics = document.get("workload_semantics")
    if semantics != requirement["semantics"]:
        fail(f"{label} does not declare the canonical {workload} semantics")
    selected_scenarios = document.get("selected_scenarios")
    if not isinstance(selected_scenarios, list) or not all(
        isinstance(scenario, str) for scenario in selected_scenarios
    ):
        fail(f"{label} has no valid selected-scenarios list")
    if len(selected_scenarios) != len(set(selected_scenarios)):
        fail(f"{label} repeats selected scenarios")
    if set(selected_scenarios) != requirement["scenarios"]:
        fail(
            f"{label} selected scenarios do not match the canonical {workload} boundary; "
            f"expected={sorted(requirement['scenarios'])}, observed={sorted(selected_scenarios)}"
        )
    config = document.get("config")
    if not isinstance(config, dict) or config.get("mode") != "full":
        fail(f"{label} does not retain its full-mode effective configuration")
    if config.get("profile_workload") != workload:
        fail(f"{label} config does not declare its exact profile workload")
    # A targeted profiler must not quietly carry the complete two-mode
    # throughput record.  The two contention paths have distinct raw objects
    # and the preparation-cache path has an explicit same-key control.
    if document.get("activation_throughput") is not None:
        fail(f"{label} contains a full throughput result instead of one selective boundary")
    cache_probe = document.get("preparation_cache_reuse")
    if workload == "prepared-cache-reuse":
        if not isinstance(cache_probe, dict):
            fail(f"{label} has no explicit same-key prepared-cache probe")
        if (
            cache_probe.get("cache_enabled") is not True
            or cache_probe.get("status") != "cache_hit"
            or not isinstance(cache_probe.get("first_prepare_micros"), int)
            or not isinstance(cache_probe.get("second_prepare_micros"), int)
            or cache_probe.get("same_prepared_handle") is not True
            or cache_probe.get("cache_entries_after_probe") != 1
        ):
            fail(f"{label} has an invalid prepared-cache reuse observation")
    elif cache_probe is not None:
        fail(f"{label} unexpectedly contains a prepared-cache reuse observation")

    contention = document.get("targeted_contention")
    expected_mode = {
        "at-capacity-contention": ("at_capacity", 0),
        "queued-contention": ("bounded_queue_saturation", None),
    }.get(workload)
    if expected_mode is None:
        if contention is not None:
            fail(f"{label} unexpectedly contains a contention observation")
    else:
        if not isinstance(contention, dict) or not isinstance(contention.get("mode"), dict):
            fail(f"{label} has no distinct targeted contention observation")
        mode = contention["mode"]
        if mode.get("mode") != expected_mode[0]:
            fail(f"{label} records the wrong targeted contention mode")
        if not isinstance(mode.get("maximum_observed_active_leases"), int) or mode.get(
            "maximum_observed_active_leases"
        ) != config.get("pool_capacity"):
            fail(f"{label} does not prove the configured active contention state")
        if expected_mode[1] is not None:
            if mode.get("maximum_observed_queue_depth") != expected_mode[1]:
                fail(f"{label} does not isolate the at-capacity queue state")
        elif mode.get("maximum_observed_queue_depth") != config.get("pool_queue_capacity"):
            fail(f"{label} does not isolate the bounded-queue saturation state")
    check_names(document, label, None)


def distribution_value(document: dict[str, Any], name: str, field: str = "p50") -> float | None:
    value = document.get("timings", {}).get("distributions", {}).get(name)
    if not isinstance(value, dict):
        return None
    observed = value.get(field)
    return float(observed) if isinstance(observed, (int, float)) else None


def maximum_process_value(document: dict[str, Any], field: str) -> float | None:
    values = [
        snapshot.get(field)
        for snapshot in document.get("process_snapshots", [])
        if isinstance(snapshot, dict) and isinstance(snapshot.get(field), (int, float))
    ]
    return float(max(values)) if values else None


def process_value_at_label(document: dict[str, Any], label: str, field: str) -> float | None:
    for snapshot in document.get("process_snapshots", []):
        if not isinstance(snapshot, dict) or snapshot.get("label") != label:
            continue
        value = snapshot.get(field)
        return float(value) if isinstance(value, (int, float)) else None
    return None


def process_delta(
    document: dict[str, Any], before_label: str, after_label: str, field: str
) -> float | None:
    before = process_value_at_label(document, before_label, field)
    after = process_value_at_label(document, after_label, field)
    return None if before is None or after is None else after - before


def candidate_metrics(document: dict[str, Any]) -> dict[str, float | None]:
    throughput = document.get("activation_throughput", {})
    at_capacity = throughput.get("at_capacity", {}) if isinstance(throughput, dict) else {}
    queued = (
        throughput.get("bounded_queue_saturation", {}) if isinstance(throughput, dict) else {}
    )
    return {
        "component_preparation_micros": _number(document.get("timings", {}).get("component_preparation_micros")),
        "warm_echo_p50_micros": distribution_value(document, "warm_echo_elapsed_micros"),
        "post_invocation_cleanup_p50_micros": distribution_value(
            document, "post_invocation_cleanup_micros"
        ),
        "at_capacity_activations_per_second": _number(
            at_capacity.get("activations_per_second") if isinstance(at_capacity, dict) else None
        ),
        "bounded_queue_activations_per_second": _number(
            queued.get("activations_per_second") if isinstance(queued, dict) else None
        ),
        "peak_rss_bytes": maximum_process_value(document, "rss_bytes"),
        "peak_virtual_memory_bytes": maximum_process_value(document, "virtual_memory_bytes"),
        "peak_file_descriptors": maximum_process_value(document, "file_descriptor_count"),
        "peak_threads": maximum_process_value(document, "thread_count"),
        "peak_open_sockets": maximum_process_value(document, "open_socket_count"),
        "peak_listening_sockets": maximum_process_value(document, "listening_socket_count"),
        "fixed_runtime_rss_bytes": process_value_at_label(
            document, "before_component_load", "rss_bytes"
        ),
        "fixed_runtime_virtual_memory_bytes": process_value_at_label(
            document, "before_component_load", "virtual_memory_bytes"
        ),
        "prepared_state_rss_delta_bytes": process_delta(
            document, "before_component_load", "after_component_preparation", "rss_bytes"
        ),
        "prepared_state_virtual_memory_delta_bytes": process_delta(
            document,
            "before_component_load",
            "after_component_preparation",
            "virtual_memory_bytes",
        ),
        "post_release_rss_delta_bytes": process_delta(
            document, "before_component_load", "prepared_component_released", "rss_bytes"
        ),
        "post_release_virtual_memory_delta_bytes": process_delta(
            document,
            "before_component_load",
            "prepared_component_released",
            "virtual_memory_bytes",
        ),
    }


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def median(values: Iterable[float | None]) -> float | None:
    numeric = [value for value in values if value is not None]
    return float(statistics.median(numeric)) if numeric else None


def require_text(path: Path, label: str) -> str:
    if not path.is_file():
        fail(f"{label} is missing: {path}")
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as error:
        fail(f"unable to read {label} ({path}): {error}")
    if not contents.strip():
        fail(f"{label} is empty: {path}")
    return contents


def require_heaptrack_data(directory: Path, label: str) -> Path:
    candidates = sorted(path for path in directory.glob("heaptrack*.gz*") if path.is_file())
    if len(candidates) != 1:
        fail(
            f"{label} must retain exactly one Heaptrack compressed data file; "
            f"found {[str(path) for path in candidates]}"
        )
    return candidates[0]


def heaptrack_summary(report: str, label: str) -> dict[str, Any]:
    allocation_match = re.search(r"calls to allocation functions:\s*(\d+)", report)
    if allocation_match is None or int(allocation_match.group(1)) == 0:
        fail(f"{label} does not contain non-zero Heaptrack allocation evidence")
    leak_match = re.search(r"total memory leaked:\s*([^\r\n]+)", report)
    if leak_match is None:
        fail(f"{label} does not report its Heaptrack process-exit leak total")
    temporary_match = re.search(r"temporary memory allocations:\s*(\d+)", report)
    runtime_match = re.search(r"total runtime:\s*([^\r\n]+)", report)
    return {
        "allocation_calls": int(allocation_match.group(1)),
        "temporary_allocation_calls": (
            int(temporary_match.group(1)) if temporary_match is not None else None
        ),
        "runtime": runtime_match.group(1).strip() if runtime_match is not None else None,
        "process_exit_leaked_memory": leak_match.group(1).strip(),
    }


def perf_samples(report: str) -> list[dict[str, Any]]:
    """Parse no-children self rows or inclusive-children `perf report` rows."""
    samples: list[dict[str, Any]] = []
    for line in report.splitlines():
        fields = re.split(r"\s{2,}", line.strip())
        if len(fields) < 4:
            continue
        percentage = re.fullmatch(r"(\d+(?:\.\d+)?)%", fields[0])
        if percentage is None:
            continue
        # `perf report --no-children` has
        #   Overhead, Command, Shared Object, Symbol
        # while the inclusive report has
        #   Children, Self, Command, Shared Object, Symbol.
        # In the latter case the first percentage is the inclusive value and
        # the extra Self column must not be mistaken for the command name.
        offset = 1 if len(fields) >= 5 and re.fullmatch(r"\d+(?:\.\d+)?%", fields[1]) else 0
        samples.append(
            {
                "percent": float(percentage.group(1)),
                "command": fields[1 + offset],
                "shared_object": fields[2 + offset],
                "symbol": fields[3 + offset],
            }
        )
    return samples


def perf_top_samples(report: str, limit: int = 5) -> list[dict[str, Any]]:
    return perf_samples(report)[:limit]


def parse_folded_stacks(path: Path, label: str) -> list[tuple[str, int]]:
    contents = require_text(path, label)
    records: list[tuple[str, int]] = []
    for line_number, line in enumerate(contents.splitlines(), start=1):
        try:
            stack, raw_value = line.rsplit(" ", 1)
            value = int(raw_value)
        except ValueError:
            fail(f"{label} has an invalid folded-stack line {line_number}")
        if not stack or value < 0:
            fail(f"{label} has an invalid folded-stack value at line {line_number}")
        records.append((stack, value))
    if not records:
        fail(f"{label} has no folded allocation-stack records")
    return records


def contributor_category_for_frame(frame: str) -> str:
    """Classify one concrete symbol/frame, never a concatenated call stack."""
    normalized = frame.strip().lower()
    for category, patterns in ATTRIBUTION_RULES.items():
        if any(pattern in normalized for pattern in patterns):
            return category
    return "unmatched_or_unknown"


def folded_stack_frames(stack: str) -> list[str]:
    frames = [frame.strip() for frame in stack.split(";") if frame.strip()]
    if not frames:
        fail("Heaptrack folded stack has no frames")
    return frames


def allocation_owner_frame(stack: str) -> str | None:
    """Return the leaf-nearest non-plumbing owner from a folded Heaptrack stack.

    `heaptrack_print --print-flamegraph` writes root-to-leaf stacks.  A category
    can therefore be assigned only after looking backwards from the allocation
    leaf and discarding allocator/container/runtime machinery.  Once a
    meaningful frame is selected, no outer frame can override its category.
    """
    for frame in reversed(folded_stack_frames(stack)):
        normalized = frame.lower()
        if any(pattern in normalized for pattern in ALLOCATION_OWNER_PLUMBING_PATTERNS):
            continue
        return frame
    return None


def allocation_contributor(stack: str) -> tuple[str, str]:
    """Return the category and direct owner frame for one allocation stack."""
    owner = allocation_owner_frame(stack)
    if owner is None:
        return "unmatched_or_unknown", "<no non-plumbing allocation owner frame>"
    return contributor_category_for_frame(owner), owner


def add_contributor_sample(entry: dict[str, Any], sample: str, key: str) -> None:
    samples = entry[key]
    compact_sample = sample if len(sample) <= 512 else f"{sample[:509]}..."
    if len(samples) < 3 and compact_sample not in samples:
        samples.append(compact_sample)


def contributor_categories() -> tuple[str, ...]:
    return tuple(ATTRIBUTION_RULES) + ("unmatched_or_unknown",)


def empty_allocation_contributors() -> dict[str, dict[str, Any]]:
    return {
        category: {
            "allocation_calls": 0,
            "allocation_peak_bytes": 0,
            "sample_owner_frames": [],
        }
        for category in contributor_categories()
    }


def summarize_heaptrack_contributors(
    allocation_folded: Path,
    peak_folded: Path,
    raw_heaptrack_data: Path,
    output: Path,
) -> None:
    """Write a compact, auditable classification of transient folded stacks.

    Heaptrack's folded output repeats deep demangled Rust stacks and is vastly
    larger than the compressed Heaptrack trace from which it can be regenerated.
    The retained raw trace, its checksum, normal Heaptrack report, and this
    complete category total keep the evidence inspectable without checking in
    hundreds of megabytes of mechanically regenerated text.
    """
    allocation_calls = parse_folded_stacks(
        allocation_folded, "Heaptrack allocation folded stacks"
    )
    allocation_peak_bytes = parse_folded_stacks(
        peak_folded, "Heaptrack peak-byte folded stacks"
    )
    categories = empty_allocation_contributors()
    for stack, value in allocation_calls:
        category, owner = allocation_contributor(stack)
        categories[category]["allocation_calls"] += value
        add_contributor_sample(categories[category], owner, "sample_owner_frames")
    for stack, value in allocation_peak_bytes:
        category, owner = allocation_contributor(stack)
        categories[category]["allocation_peak_bytes"] += value
        add_contributor_sample(categories[category], owner, "sample_owner_frames")
    allocation_call_total = sum(value for _, value in allocation_calls)
    allocation_peak_total = sum(value for _, value in allocation_peak_bytes)
    write_json(
        output,
        {
            "schema_version": HEAPTRACK_ATTRIBUTION_SCHEMA,
            "raw_heaptrack_sha256": sha256_file(raw_heaptrack_data),
            "measurement": (
                "Heaptrack --flamegraph-cost-type allocations and peak folded stacks; "
                "disjoint nearest non-plumbing allocation-owner-frame classification"
            ),
            "owner_selection": HEAPTRACK_OWNER_SELECTION,
            "categories": categories,
            "totals": {
                "allocation_calls": allocation_call_total,
                "allocation_peak_bytes": allocation_peak_total,
            },
        },
    )


def load_heaptrack_contributors(
    path: Path, raw_heaptrack_data: Path, expected_allocation_calls: int, label: str
) -> dict[str, Any]:
    document = load_json(path, f"{label} compact Heaptrack attribution")
    if document.get("schema_version") != HEAPTRACK_ATTRIBUTION_SCHEMA:
        fail(f"{label} compact Heaptrack attribution has an unexpected schema")
    if document.get("raw_heaptrack_sha256") != sha256_file(raw_heaptrack_data):
        fail(f"{label} compact Heaptrack attribution is not bound to its raw trace")
    owner_selection = document.get("owner_selection")
    if owner_selection != HEAPTRACK_OWNER_SELECTION:
        fail(f"{label} compact Heaptrack attribution has an unexpected owner-selection method")
    categories = document.get("categories")
    if not isinstance(categories, dict) or set(categories) != set(contributor_categories()):
        fail(f"{label} compact Heaptrack attribution has a different category set")
    allocation_call_total = 0
    allocation_peak_total = 0
    normalized: dict[str, dict[str, Any]] = {}
    for category in contributor_categories():
        value = categories.get(category)
        if not isinstance(value, dict):
            fail(f"{label} compact Heaptrack attribution has an invalid {category} category")
        calls = value.get("allocation_calls")
        peak_bytes = value.get("allocation_peak_bytes")
        samples = value.get("sample_owner_frames")
        if (
            not isinstance(calls, int)
            or calls < 0
            or not isinstance(peak_bytes, int)
            or peak_bytes < 0
            or not isinstance(samples, list)
            or len(samples) > 3
            or not all(isinstance(sample, str) and len(sample) <= 512 for sample in samples)
        ):
            fail(f"{label} compact Heaptrack attribution has invalid {category} values")
        normalized[category] = {
            "allocation_calls": calls,
            "allocation_peak_bytes": peak_bytes,
            "sample_owner_frames": samples,
        }
        allocation_call_total += calls
        allocation_peak_total += peak_bytes
    totals = document.get("totals")
    if not isinstance(totals, dict):
        fail(f"{label} compact Heaptrack attribution has no totals")
    if totals.get("allocation_calls") != allocation_call_total or totals.get(
        "allocation_peak_bytes"
    ) != allocation_peak_total:
        fail(f"{label} compact Heaptrack attribution totals do not match its categories")
    if allocation_call_total != expected_allocation_calls:
        fail(
            f"{label} compact Heaptrack allocation total {allocation_call_total} does not equal "
            f"Heaptrack summary {expected_allocation_calls}"
        )
    return {
        "categories": normalized,
        "totals": {
            "allocation_calls": allocation_call_total,
            "allocation_peak_bytes": allocation_peak_total,
        },
    }


def quantitative_attribution(
    self_perf_report: str,
    inclusive_perf_report: str,
    heaptrack_contributors: dict[str, Any],
) -> dict[str, Any]:
    categories = contributor_categories()
    values: dict[str, dict[str, Any]] = {
        category: {
            "cpu_self_percent": 0.0,
            "cpu_inclusive_percent": 0.0,
            "allocation_calls": 0,
            "allocation_peak_bytes": 0,
            "sample_symbols_or_owner_frames": [],
        }
        for category in categories
    }
    self_perf_rows = perf_samples(self_perf_report)
    inclusive_perf_rows = perf_samples(inclusive_perf_report)
    for row in self_perf_rows:
        # `Symbol` is already a single sampled frame. Do not use a shared
        # object name as an outer-frame substitute for a contributor claim.
        category = contributor_category_for_frame(row["symbol"])
        values[category]["cpu_self_percent"] += row["percent"]
        add_contributor_sample(values[category], row["symbol"], "sample_symbols_or_owner_frames")
    for row in inclusive_perf_rows:
        category = contributor_category_for_frame(row["symbol"])
        values[category]["cpu_inclusive_percent"] += row["percent"]
        add_contributor_sample(values[category], row["symbol"], "sample_symbols_or_owner_frames")
    for category in categories:
        allocation = heaptrack_contributors["categories"][category]
        values[category]["allocation_calls"] = allocation["allocation_calls"]
        values[category]["allocation_peak_bytes"] = allocation["allocation_peak_bytes"]
        for sample in allocation["sample_owner_frames"]:
            add_contributor_sample(values[category], sample, "sample_symbols_or_owner_frames")
    for entry in values.values():
        entry["cpu_self_percent"] = round(entry["cpu_self_percent"], 4)
        entry["cpu_inclusive_percent"] = round(entry["cpu_inclusive_percent"], 4)
        entry["observation_status"] = (
            "observed_at_profiler_resolution"
            if any(
                entry[field] > 0
                for field in (
                    "cpu_self_percent",
                    "cpu_inclusive_percent",
                    "allocation_calls",
                    "allocation_peak_bytes",
                )
            )
            else "not_observed_at_profiler_resolution"
        )
    return {
        "cpu_measurement": "perf report --no-children self samples and perf report inclusive samples; inclusive category totals may overlap and need not sum to 100%",
        "allocation_measurement": "Heaptrack folded allocation-call and peak-byte stack costs; categories are disjoint nearest non-plumbing owner-frame classifications",
        "unmatched_bucket": "unmatched_or_unknown",
        "categories": values,
        "totals": {
            "cpu_reported_self_percent": round(
                sum(row["percent"] for row in self_perf_rows), 4
            ),
            "cpu_reported_inclusive_percent": round(
                sum(row["percent"] for row in inclusive_perf_rows), 4
            ),
            "allocation_calls": heaptrack_contributors["totals"]["allocation_calls"],
            "allocation_peak_bytes": heaptrack_contributors["totals"][
                "allocation_peak_bytes"
            ],
        },
    }


def load_full_invariant_proof(
    raw_path: Path,
    archive_root: Path,
    source_commit: str,
    source_tree: str,
    published_source_ref: str,
    published_source_ref_head: str,
) -> tuple[dict[str, Any], set[str], dict[str, Any]]:
    document = load_json(raw_path, "full-invariant proof baseline")
    expected_checks = verify_baseline(document, "full-invariant proof baseline", None)
    command_path = raw_path.parent / "command.json"
    command = load_json(command_path, "full-invariant proof command")
    arguments = verify_command_identity(
        command,
        "full-invariant proof command",
        source_commit,
        source_tree,
        published_source_ref,
        published_source_ref_head,
    )
    if command_option(arguments, "--profile-workload") is not None:
        fail("full-invariant proof command must not use a selective profile workload")
    if command_option(arguments, "--mode") != "full":
        fail("full-invariant proof command must retain full mode")
    if command_option(arguments, "--coordination-poll-interval-ms") != "0":
        fail("full-invariant proof command must retain calibrated cooperative polling")
    config = require_exact_configuration(
        document.get("config"), DEFAULT_FULL_CONFIGURATION, "full-invariant proof"
    )
    measurement_identity = require_measurement_identity(
        document, "full-invariant proof", exclude_sampling=False
    )
    composition_identity = require_measurement_identity(
        document, "full-invariant proof", exclude_sampling=True
    )
    cache_probe = document.get("preparation_cache_reuse")
    if (
        not isinstance(cache_probe, dict)
        or cache_probe.get("cache_enabled") is not True
        or cache_probe.get("status") != "cache_hit"
        or not isinstance(cache_probe.get("first_prepare_micros"), int)
        or not isinstance(cache_probe.get("second_prepare_micros"), int)
        or cache_probe.get("same_prepared_handle") is not True
        or cache_probe.get("cache_entries_after_probe") != 1
    ):
        fail("full-invariant proof lacks a passing same-key prepared-cache reuse control")
    return (
        document,
        expected_checks,
        {
            "raw_results": archive_path(raw_path, archive_root),
            "raw_results_sha256": sha256_file(raw_path),
            "command": archive_path(command_path, archive_root),
            "command_sha256": sha256_file(command_path),
            "command_identity": {
                "source_commit": command["source_commit"],
                "source_tree": command["source_tree"],
                "published_source_ref": command["published_source_ref"],
                "published_source_ref_head": command["published_source_ref_head"],
                "execution_commit": command["execution_commit"],
                "execution_tree": command["execution_tree"],
            },
            "configuration": config,
            "measurement_identity": measurement_identity,
            "composition_identity": composition_identity,
        },
    )


def load_profile(
    profiles_directory: Path,
    name: str,
    full_invariant_proof: dict[str, Any],
    archive_root: Path,
    source_commit: str,
    source_tree: str,
    published_source_ref: str,
    published_source_ref_head: str,
    full_command_identity: dict[str, Any],
    expected_environment: dict[str, Any],
    expected_host_identity: dict[str, Any],
) -> dict[str, Any]:
    root = profiles_directory / name
    perf_root = root / "perf"
    allocation_root = root / "allocation"
    perf_document = load_json(perf_root / "raw-results.json", f"{name} perf targeted profile")
    verify_targeted_profile_document(perf_document, f"{name} perf targeted profile", name)
    allocation_document = load_json(
        allocation_root / "raw-results.json", f"{name} allocation targeted profile"
    )
    verify_targeted_profile_document(
        allocation_document, f"{name} allocation targeted profile", name
    )
    process_host_records: dict[str, dict[str, Any]] = {}
    for label, document, process_root in (
        ("perf", perf_document, perf_root),
        ("allocation", allocation_document, allocation_root),
    ):
        process_host, process_host_record = host_observation_record(
            process_root,
            f"{name} {label} targeted profile",
            archive_root,
            source_commit,
            source_tree,
            published_source_ref,
            published_source_ref_head,
            expected_host_identity,
        )
        verify_run_environment(
            document,
            f"{name} {label} targeted profile",
            process_host,
            expected_environment,
            full_command_identity["execution_commit"],
        )
        process_host_records[label] = process_host_record

    # The perf and Heaptrack processes deliberately differ only by the
    # profiler executable. They must otherwise be byte-for-byte the same
    # effective run. A targeted workload may differ from the full proof only
    # in the explicitly excluded sampling/workload/poll fields.
    perf_exact_identity = require_measurement_identity(
        perf_document, f"{name} perf targeted profile", exclude_sampling=False
    )
    allocation_exact_identity = require_measurement_identity(
        allocation_document, f"{name} allocation targeted profile", exclude_sampling=False
    )
    require_identity_match(
        perf_exact_identity,
        allocation_exact_identity,
        f"{name} perf/allocation",
    )
    perf_composition_identity = require_measurement_identity(
        perf_document, f"{name} perf targeted profile", exclude_sampling=True
    )
    full_measurement_identity = full_invariant_proof.get("composition_identity")
    if not isinstance(full_measurement_identity, dict):
        fail("full-invariant proof has no canonical composition identity")
    require_identity_match(
        full_measurement_identity,
        perf_composition_identity,
        f"{name} targeted profile/full-invariant proof",
    )

    perf_command = load_json(perf_root / "command.json", f"{name} perf command")
    allocation_command = load_json(
        allocation_root / "command.json", f"{name} allocation command"
    )
    for label, command, tool in (
        ("perf", perf_command, "perf"),
        ("allocation", allocation_command, "heaptrack"),
    ):
        if command.get("tool") != tool:
            fail(f"{name} {label} command records the wrong profiling tool")
        arguments = verify_command_identity(
            command,
            f"{name} {label} command",
            source_commit,
            source_tree,
            published_source_ref,
            published_source_ref_head,
            full_command_identity["execution_commit"],
        )
        if command_option(arguments, "--profile-workload") != name:
            fail(f"{name} {label} command does not declare its exact profile workload")
        if command_option(arguments, "--coordination-poll-interval-ms") != "1":
            fail(f"{name} {label} command does not record profiler-only polling")

    perf_report = require_text(perf_root / "perf-report.txt", f"{name} symbolized CPU report")
    perf_inclusive_report = require_text(
        perf_root / "perf-inclusive-report.txt", f"{name} inclusive CPU report"
    )
    allocation_report = require_text(
        allocation_root / "heaptrack-report.txt", f"{name} allocation report"
    )
    allocation_leak_report = require_text(
        allocation_root / "heaptrack-leaks.txt", f"{name} allocation leak report"
    )
    allocation_summary = heaptrack_summary(allocation_report, f"{name} allocation report")
    perf_data = perf_root / "perf.data"
    allocation_data = require_heaptrack_data(allocation_root, f"{name} raw Heaptrack data")
    compact_heaptrack_attribution = allocation_root / "heaptrack-contributors.json"
    if not perf_data.is_file():
        fail(f"{name} raw perf data is missing: {perf_data}")
    heaptrack_contributors = load_heaptrack_contributors(
        compact_heaptrack_attribution,
        allocation_data,
        allocation_summary["allocation_calls"],
        name,
    )
    contributors = quantitative_attribution(
        perf_report,
        perf_inclusive_report,
        heaptrack_contributors,
    )
    return (
        {
            "workload": name,
            "metrics": candidate_metrics(perf_document),
            "top_cpu_samples": perf_top_samples(perf_report),
            "scenario_semantics": perf_document["workload_semantics"],
            "selected_scenarios": perf_document.get("selected_scenarios", []),
            "payload_flow": perf_document.get("payload_flow"),
            "per_run_environment": perf_document["environment"],
            "composition_identity": perf_composition_identity,
            "full_invariant_proof": full_invariant_proof,
            "contributor_attribution": contributors,
            "perf": {
                "measurement_identity": perf_exact_identity,
                "host_observations": process_host_records["perf"],
                "command": perf_command,
                "raw_results": archive_path(perf_root / "raw-results.json", archive_root),
                "raw_results_sha256": sha256_file(perf_root / "raw-results.json"),
                "data": archive_path(perf_data, archive_root),
                "data_sha256": sha256_file(perf_data),
                "report": archive_path(perf_root / "perf-report.txt", archive_root),
                "report_sha256": sha256_file(perf_root / "perf-report.txt"),
                "inclusive_report": archive_path(
                    perf_root / "perf-inclusive-report.txt", archive_root
                ),
                "inclusive_report_sha256": sha256_file(
                    perf_root / "perf-inclusive-report.txt"
                ),
                "report_text": perf_report,
            },
            "allocation": {
                "measurement_identity": allocation_exact_identity,
                "host_observations": process_host_records["allocation"],
                "command": allocation_command,
                "raw_results": archive_path(
                    allocation_root / "raw-results.json", archive_root
                ),
                "raw_results_sha256": sha256_file(allocation_root / "raw-results.json"),
                "data": archive_path(allocation_data, archive_root),
                "data_sha256": sha256_file(allocation_data),
                "report": archive_path(
                    allocation_root / "heaptrack-report.txt", archive_root
                ),
                "report_sha256": sha256_file(allocation_root / "heaptrack-report.txt"),
                "report_text": allocation_report,
                "leak_report": archive_path(
                    allocation_root / "heaptrack-leaks.txt", archive_root
                ),
                "leak_report_sha256": sha256_file(allocation_root / "heaptrack-leaks.txt"),
                "leak_report_text": allocation_leak_report,
                "compact_contributors": archive_path(
                    compact_heaptrack_attribution, archive_root
                ),
                "compact_contributors_sha256": sha256_file(compact_heaptrack_attribution),
                **allocation_summary,
            },
        }
    )


def validate_candidate_config(name: str, document: dict[str, Any]) -> None:
    require_exact_configuration(
        document.get("config"), candidate_configuration(name), f"candidate {name}"
    )


def validate_candidate_cache_reuse(
    name: str, run_name: str, document: dict[str, Any]
) -> dict[str, Any]:
    probe = document.get("preparation_cache_reuse")
    if not isinstance(probe, dict):
        fail(f"candidate {name} {run_name} lacks an explicit prepared-cache reuse control")
    enabled = CANDIDATE_EXPECTATIONS[name]["prepared_cache_enabled"]
    if probe.get("cache_enabled") is not enabled:
        fail(f"candidate {name} {run_name} cache control does not match its configuration")
    first_prepare = probe.get("first_prepare_micros")
    entries = probe.get("cache_entries_after_probe")
    if not isinstance(first_prepare, int) or first_prepare < 0 or not isinstance(entries, int):
        fail(f"candidate {name} {run_name} has invalid cache-control timing or entry count")
    if enabled:
        second_prepare = probe.get("second_prepare_micros")
        if (
            probe.get("status") != "cache_hit"
            or not isinstance(second_prepare, int)
            or second_prepare < 0
            or probe.get("same_prepared_handle") is not True
            or entries != 1
        ):
            fail(f"candidate {name} {run_name} lacks a passing same-key cache-hit observation")
    elif (
        probe.get("status") != "disabled_cold_control"
        or probe.get("second_prepare_micros") is not None
        or probe.get("same_prepared_handle") is not None
        or entries != 0
    ):
        fail(f"candidate {name} {run_name} lacks a valid disabled-cache cold control")
    return {
        "cache_enabled": enabled,
        "status": probe["status"],
        "first_prepare_micros": float(first_prepare),
        "second_prepare_micros": _number(probe.get("second_prepare_micros")),
        "same_prepared_handle": probe.get("same_prepared_handle"),
        "cache_entries_after_probe": entries,
    }


REQUIRED_CANDIDATE_METRICS = (
    "component_preparation_micros",
    "warm_echo_p50_micros",
    "post_invocation_cleanup_p50_micros",
    "at_capacity_activations_per_second",
    "bounded_queue_activations_per_second",
    "fixed_runtime_rss_bytes",
    "fixed_runtime_virtual_memory_bytes",
    "prepared_state_rss_delta_bytes",
    "prepared_state_virtual_memory_delta_bytes",
    "peak_rss_bytes",
    "peak_virtual_memory_bytes",
    "post_release_rss_delta_bytes",
    "post_release_virtual_memory_delta_bytes",
    "peak_threads",
    "peak_open_sockets",
    "peak_listening_sockets",
)


def validate_candidate_metrics(name: str, run_name: str, document: dict[str, Any]) -> dict[str, float | None]:
    metrics = candidate_metrics(document)
    missing = [metric for metric in REQUIRED_CANDIDATE_METRICS if metrics.get(metric) is None]
    if missing:
        fail(
            f"candidate {name} {run_name} lacks required fixed/peak-memory, latency, "
            f"throughput, topology, or reclamation metrics: {', '.join(missing)}"
        )
    return metrics


def load_candidate(
    candidates_directory: Path,
    name: str,
    expected_checks: set[str],
    archive_root: Path,
    source_commit: str,
    source_tree: str,
    published_source_ref: str,
    published_source_ref_head: str,
    full_command_identity: dict[str, Any],
    expected_environment: dict[str, Any],
    expected_host_identity: dict[str, Any],
    required_run_count: int,
) -> dict[str, Any]:
    root = candidates_directory / name
    runs = sorted(path for path in root.glob("run-*/raw-results.json") if path.is_file())
    expected_names = [f"run-{index:02d}" for index in range(1, required_run_count + 1)]
    observed_names = [path.parent.name for path in runs]
    if observed_names != expected_names:
        fail(
            f"candidate {name} must retain exactly {required_run_count} consecutively named runs; "
            f"expected={expected_names}, observed={observed_names}"
        )
    documents: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    host_records: list[dict[str, Any]] = []
    metric_samples: list[dict[str, float | None]] = []
    cache_reuse_controls: list[dict[str, Any]] = []
    for path in runs:
        document = load_json(path, f"candidate {name} baseline")
        verify_baseline(document, f"candidate {name} {path.parent.name}", expected_checks)
        process_host, process_host_record = host_observation_record(
            path.parent,
            f"candidate {name} {path.parent.name}",
            archive_root,
            source_commit,
            source_tree,
            published_source_ref,
            published_source_ref_head,
            expected_host_identity,
        )
        verify_run_environment(
            document,
            f"candidate {name} {path.parent.name}",
            process_host,
            expected_environment,
            full_command_identity["execution_commit"],
        )
        validate_candidate_config(name, document)
        command_path = path.parent / "command.json"
        command = load_json(command_path, f"candidate {name} {path.parent.name} command")
        arguments = verify_command_identity(
            command,
            f"candidate {name} {path.parent.name} command",
            source_commit,
            source_tree,
            published_source_ref,
            published_source_ref_head,
            full_command_identity["execution_commit"],
        )
        if command.get("tool") != "phase0-baseline":
            fail(f"candidate {name} {path.parent.name} did not record phase0-baseline provenance")
        if command_option(arguments, "--profile-workload") is not None:
            fail(f"candidate {name} {path.parent.name} must be a full baseline, not targeted")
        if command_option(arguments, "--mode") != "full":
            fail(f"candidate {name} {path.parent.name} must retain full baseline mode")
        if command_option(arguments, "--coordination-poll-interval-ms") != "0":
            fail(
                f"candidate {name} {path.parent.name} changes calibrated coordination polling"
            )
        documents.append(document)
        identities.append(
            require_measurement_identity(
                document,
                f"candidate {name} {path.parent.name}",
                exclude_sampling=False,
            )
        )
        host_records.append(process_host_record)
        cache_reuse_controls.append(
            validate_candidate_cache_reuse(name, path.parent.name, document)
        )
        metric_samples.append(validate_candidate_metrics(name, path.parent.name, document))
    representatives = {
        metric: median(sample.get(metric) for sample in metric_samples)
        for metric in metric_samples[0]
    }
    first = documents[0]
    first_identity = identities[0]
    for path, identity in zip(runs[1:], identities[1:], strict=True):
        require_identity_match(
            first_identity,
            identity,
            f"candidate {name} {path.parent.name}/run-01",
        )
    return {
        "name": name,
        "run_count": len(documents),
        "raw_runs": [
            {
                "path": archive_path(path, archive_root),
                "sha256": sha256_file(path),
                "status": document["status"],
                "command": archive_path(path.parent / "command.json", archive_root),
                "command_sha256": sha256_file(path.parent / "command.json"),
                "environment": document.get("environment"),
                "measurement_identity": identity,
                "host_observations": host_record,
            }
            for path, document, identity, host_record in zip(
                runs, documents, identities, host_records, strict=True
            )
        ],
        "configuration": first["config"],
        "measurement_identity": first_identity,
        "metrics_per_run": metric_samples,
        "representatives": representatives,
        "prepared_cache_reuse_control": {
            "cache_enabled": cache_reuse_controls[0]["cache_enabled"],
            "status": cache_reuse_controls[0]["status"],
            "first_prepare_micros": median(
                control["first_prepare_micros"] for control in cache_reuse_controls
            ),
            "second_prepare_micros": median(
                control["second_prepare_micros"] for control in cache_reuse_controls
            ),
            "same_prepared_handle": cache_reuse_controls[0]["same_prepared_handle"],
            "cache_entries_after_probe": cache_reuse_controls[0][
                "cache_entries_after_probe"
            ],
            "per_run": cache_reuse_controls,
        },
        "hard_invariants": {
            "status": "pass",
            "rule": "all canonical Phase 0 baseline checks passed exactly once in every retained run",
            "containment_and_reclamation": "validated by the complete canonical check set",
        },
        "topology": {
            "runtime_workers": first["config"].get("runtime_workers"),
            "pool_capacity": first["config"].get("pool_capacity"),
            "pool_queue_capacity": first["config"].get("pool_queue_capacity"),
            "peak_threads": representatives.get("peak_threads"),
            "peak_open_sockets": representatives.get("peak_open_sockets"),
            "peak_listening_sockets": representatives.get("peak_listening_sockets"),
        },
    }


def archive_profile_record(profile: dict[str, Any]) -> dict[str, Any]:
    """Keep reports as raw evidence without duplicating multi-megabyte text.

    Attribution is calculated from the complete reports before this conversion.
    The compact aggregate then links to their retained paths and checksums.
    """
    return {
        **profile,
        "perf": {
            key: value for key, value in profile["perf"].items() if key != "report_text"
        },
        "allocation": {
            key: value
            for key, value in profile["allocation"].items()
            if key not in {"report_text", "leak_report_text"}
        },
    }


def calibration_measurement_identity(calibration: dict[str, Any]) -> dict[str, Any]:
    reference_identity = calibration.get("reference_identity")
    if not isinstance(reference_identity, dict):
        fail("#38 calibration lacks a reference measurement identity")
    return require_measurement_identity(
        {
            "artifact": reference_identity.get("artifact"),
            "config": reference_identity.get("config"),
        },
        "#38 calibration reference",
        exclude_sampling=False,
    )


def calibration_environment(calibration: dict[str, Any]) -> dict[str, Any]:
    reference_identity = calibration.get("reference_identity")
    environment = reference_identity.get("environment") if isinstance(reference_identity, dict) else None
    if not isinstance(environment, dict):
        fail("#38 calibration lacks a reference environment")
    missing = [field for field in RUN_ENVIRONMENT_FIELDS if field not in environment]
    if missing:
        fail(f"#38 calibration lacks reference environment fields: {', '.join(missing)}")
    return {field: environment[field] for field in RUN_ENVIRONMENT_FIELDS}


def calibration_host_identity(calibration: dict[str, Any]) -> dict[str, Any]:
    observations = calibration.get("host_observations")
    runs = observations.get("runs") if isinstance(observations, dict) else None
    if not isinstance(runs, list) or not runs:
        fail("#38 calibration lacks host-comparability observations")
    first = runs[0]
    if not isinstance(first, dict):
        fail("#38 calibration has a malformed host-comparability observation")
    # Normalize through the same helper used for the profile observation. In
    # particular, the calibration archive retains current CPU frequency for
    # auditability, but that instantaneous value is deliberately not a
    # comparability field.
    try:
        return calibration_aggregate.host_comparability_identity(first)
    except calibration_aggregate.CalibrationError as error:
        fail(f"#38 calibration has incomplete host-comparability context: {error}")


def profile_host_identity(host: dict[str, Any]) -> dict[str, Any]:
    try:
        return calibration_aggregate.host_comparability_identity(host)
    except calibration_aggregate.CalibrationError as error:
        fail(f"hot-path host observation lacks complete comparability context: {error}")


def validate_profile_host_observation(
    host: dict[str, Any],
    label: str,
    source_commit: str,
    source_tree: str,
    published_source_ref: str,
    published_source_ref_head: str,
) -> dict[str, Any]:
    if host.get("schema_version") != HOST_SCHEMA:
        fail(f"{label} has an unexpected host observation schema")
    if host.get("native_linux_reference") is not True:
        fail(f"{label} is not from a supported native-Linux host")
    for field, expected in (
        ("source_commit", source_commit),
        ("source_tree", source_tree),
        ("published_source_ref", published_source_ref),
        ("published_source_ref_head", published_source_ref_head),
    ):
        if host.get(field) != expected:
            fail(f"{label} source identity does not match the profile aggregate: {field}")
    host_runtime_identity(host, label)
    tools = host.get("tools")
    if not isinstance(tools, dict):
        fail(f"{label} lacks tool context")
    for tool in ("rustc", "cargo"):
        value = tools.get(tool)
        if not isinstance(value, str) or not value.strip():
            fail(f"{label} has no usable {tool} tool context")
    return profile_host_identity(host)


def host_observation_record(
    root: Path,
    label: str,
    archive_root: Path,
    source_commit: str,
    source_tree: str,
    published_source_ref: str,
    published_source_ref_head: str,
    expected_host_identity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind a measured process to stable before/after host observations."""
    before_path = root / "host-before.json"
    after_path = root / "host-after.json"
    before = load_json(before_path, f"{label} host-before observation")
    after = load_json(after_path, f"{label} host-after observation")
    before_identity = validate_profile_host_observation(
        before,
        f"{label} host-before observation",
        source_commit,
        source_tree,
        published_source_ref,
        published_source_ref_head,
    )
    after_identity = validate_profile_host_observation(
        after,
        f"{label} host-after observation",
        source_commit,
        source_tree,
        published_source_ref,
        published_source_ref_head,
    )
    require_host_identity_match(
        before_identity,
        after_identity,
        f"{label} host-before/host-after",
    )
    require_host_identity_match(
        expected_host_identity,
        before_identity,
        f"{label} host/wrapper",
    )
    return before, {
        "before": archive_path(before_path, archive_root),
        "before_sha256": sha256_file(before_path),
        "after": archive_path(after_path, archive_root),
        "after_sha256": sha256_file(after_path),
        "static_identity": before_identity,
    }


def calibration_mismatches(
    candidate: dict[str, Any],
    calibration: dict[str, Any],
    source_commit: str,
    source_tree: str,
    host_identity: dict[str, Any],
    *,
    require_minimum_runs: bool = True,
) -> list[str]:
    mismatches: list[str] = []
    if calibration.get("source_commit") != source_commit:
        mismatches.append("source_commit differs from the #38 calibration")
    if calibration.get("source_tree") != source_tree:
        mismatches.append("source_tree differs from the #38 calibration")
    minimum_runs = calibration.get("minimum_required_run_count", MINIMUM_ADOPTION_RUNS)
    if not isinstance(minimum_runs, int) or minimum_runs < MINIMUM_ADOPTION_RUNS:
        minimum_runs = MINIMUM_ADOPTION_RUNS
    if require_minimum_runs and candidate["run_count"] < minimum_runs:
        mismatches.append(
            f"only {candidate['run_count']} retained full runs; #38 requires at least {minimum_runs}"
        )

    candidate_identity = candidate.get("measurement_identity")
    if not isinstance(candidate_identity, dict):
        mismatches.append("candidate lacks a canonical measurement identity")
    else:
        reference_identity = calibration_measurement_identity(calibration)
        if stable_json(candidate_identity) != stable_json(reference_identity):
            mismatches.append(
                "measurement identity differs: "
                + first_difference(reference_identity, candidate_identity)
            )

    raw_runs = candidate.get("raw_runs")
    first_run = raw_runs[0] if isinstance(raw_runs, list) and raw_runs else None
    candidate_environment = first_run.get("environment") if isinstance(first_run, dict) else None
    if not isinstance(candidate_environment, dict):
        mismatches.append("candidate lacks per-run environment context")
    else:
        reference_environment = calibration_environment(calibration)
        for field in RUN_ENVIRONMENT_FIELDS:
            if candidate_environment.get(field) != reference_environment.get(field):
                mismatches.append(f"environment differs for {field}")
    reference_host = calibration_host_identity(calibration)
    if stable_json(host_identity) != stable_json(reference_host):
        mismatches.append(
            "host identity differs: " + first_difference(reference_host, host_identity)
        )
    return mismatches


def require_calibration_match(
    candidate: dict[str, Any],
    calibration: dict[str, Any],
    source_commit: str,
    source_tree: str,
    host_identity: dict[str, Any],
    label: str,
    *,
    require_minimum_runs: bool = True,
) -> None:
    mismatches = calibration_mismatches(
        candidate,
        calibration,
        source_commit,
        source_tree,
        host_identity,
        require_minimum_runs=require_minimum_runs,
    )
    if mismatches:
        fail(f"{label} is not reference-equivalent to the #38 calibration: {'; '.join(mismatches)}")


def comparison_to_calibration(candidate: dict[str, Any], calibration: dict[str, Any]) -> dict[str, Any]:
    metrics = calibration.get("metrics")
    if not isinstance(metrics, dict):
        fail("calibration aggregate lacks metrics")
    comparisons: dict[str, Any] = {}
    for metric, calibration_metric in METRIC_TO_CALIBRATION.items():
        candidate_value = candidate["representatives"].get(metric)
        reference = metrics.get(calibration_metric)
        if candidate_value is None or not isinstance(reference, dict):
            fail(f"reference-equivalent candidate lacks calibration metric {metric}")
        comparison = reference.get("comparison")
        if not isinstance(comparison, dict):
            fail(f"#38 calibration lacks comparison data for {calibration_metric}")
        reference_median = comparison.get("reference_median")
        noise_band = comparison.get("advisory_noise_band")
        if not isinstance(reference_median, (int, float)) or not isinstance(noise_band, (int, float)):
            fail(f"#38 calibration has malformed comparison data for {calibration_metric}")
        direction = reference.get("direction")
        if direction == "increase_is_regression":
            outside = candidate_value > float(reference_median) + float(noise_band)
        elif direction == "decrease_is_regression":
            outside = candidate_value < float(reference_median) - float(noise_band)
        else:
            fail(f"#38 calibration has no valid comparison direction for {calibration_metric}")
        comparisons[metric] = {
            "status": "outside_advisory_band" if outside else "inside_advisory_band",
            "candidate_median": candidate_value,
            "reference_median": float(reference_median),
            "advisory_noise_band": float(noise_band),
            "direction": direction,
        }
    return comparisons


def phase1_experiment_scope(name: str) -> dict[str, Any]:
    expected = candidate_configuration(name)
    deltas = {
        key: value
        for key, value in expected.items()
        if value != DEFAULT_FULL_CONFIGURATION.get(key)
    }
    return {
        "status": "not_applicable_for_phase0_calibration",
        "reason": (
            "This is an intentionally different Phase 1 experiment, not a "
            "comparison against the fixed Phase 0 reference configuration."
        ),
        "intentional_configuration_delta": deltas,
    }


def attribution(profile_records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return {
        "method": (
            "Per-workload quantitative attribution is retained in "
            "profiles[*].contributor_attribution. CPU categories use individual perf "
            "symbols; Heaptrack categories use the leaf-nearest non-plumbing owner "
            "frame from each root-to-leaf folded stack. Categories are disjoint and "
            "include unmatched_or_unknown."
        ),
        "heaptrack_owner_selection": {
            "folded_stack_order": "root_to_leaf",
            "scan_direction": "allocation_leaf_to_root",
            "skip": "allocator, generic container, dynamic-loader, and async/runtime plumbing",
            "precedence": "only among patterns that match the selected owner frame",
            "no_direct_sample": "not_observed_at_profiler_resolution",
        },
        "categories": {
            category: {"narrow_patterns": list(patterns)}
            for category, patterns in ATTRIBUTION_RULES.items()
        }
        | {
            "unmatched_or_unknown": {
                "narrow_patterns": [],
                "meaning": "No category matched; it is quantified rather than silently dropped.",
            }
        },
        "workloads": {
            record["workload"]: record["contributor_attribution"] for record in profile_records
        },
    }


def decision_records(candidates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = candidates[REFERENCE_CANDIDATE]
    run_count = baseline["run_count"]
    reference_reason = (
        f"The {run_count}-run default candidate is reference-equivalent to the "
        "calibration and confirms the already selected Phase 0 configuration; it "
        "does not introduce a new runtime behavior."
    )
    return [
        {
            "candidate": "fixed 2-worker/2-cell on-demand configuration",
            "decision": "retain existing default; no new adoption",
            "scope": "existing Phase 0 configuration",
            "rationale": "It preserves the measured fixed topology and fresh-store isolation. " + reference_reason,
            "handoff": "#39 runs the final 3x100k resource soak against this configuration.",
        },
        {
            "candidate": "bounded preparation/cache reuse versus cold preparation",
            "decision": "retain existing setting; no new adoption",
            "scope": "bounded one-entry prepared-component cache and explicit cache-disabled control",
            "rationale": "The matrix includes a cache-disabled control and the targeted cold-preparation profile. The cache-disabled variant is an explicitly separate Phase 1 experiment, so the existing bounded immutable cache remains the reference setting.",
            "handoff": "#9 generalizes the cache key, policy, eviction, and multi-component compatibility proof.",
        },
        {
            "candidate": "worker/cell capacity ratios",
            "decision": "carry as configurable Phase 1 experiment",
            "scope": "#8",
            "rationale": "The matrix retains fixed ratios as explicitly non-reference Phase 1 experiments and does not select a universal winner.",
            "handoff": "#8 owns configuration, fairness, and fixed multi-class capacity policy.",
        },
        {
            "candidate": "Wasmtime pooling allocator",
            "decision": "defer",
            "scope": "#9",
            "rationale": "The experiment has an explicit fixed upper bound and no retained linear-memory allowance, but it changes node-fixed mapping and reset behavior; it is not a comparison against the selected reference.",
            "handoff": "#9 must provide generalized pooling limits, density evidence, and a reset/isolation proof before any production choice.",
        },
        {
            "candidate": "copy-on-write initialized memory",
            "decision": "carry as configurable Phase 1 experiment",
            "scope": "#9",
            "rationale": "Linux support is profiled explicitly, but its parallel-memory tradeoff is workload-dependent and belongs to the explicitly separate Phase 1 experiment scope.",
            "handoff": "#9 owns target-aware Wasmtime policy and must retain a safe non-COW fallback.",
        },
        {
            "candidate": "avoidable activation-path allocations and payload copies",
            "decision": "defer",
            "scope": "#9 and #11",
            "rationale": "Heaptrack evidence and source-attribution maps identify the current boundaries, but removing copies before the Phase 1 generic value codec and lifecycle shapes exist risks changing contracts or attribution.",
            "handoff": "#9 owns canonical value mapping; #11 owns activation-envelope/lifecycle ownership and cleanup.",
        },
        {
            "candidate": "store/instance reuse, persistent AOT artifacts, compiler caches, snapshots, and native execution",
            "decision": "reject",
            "scope": "Phase 2 or later",
            "rationale": "These candidates require a new reset/isolation or provenance proof and are forbidden from silently entering Phase 0.",
            "handoff": "Trusted AOT supply-chain work is Phase 2; fresh stores and instances remain mandatory in #9.",
        },
    ]


def write_report(path: Path, aggregate: dict[str, Any]) -> None:
    lines = [
        "# Phase 0 hot-path profiling evidence",
        "",
        f"**Status:** {aggregate['status']}. This is optimization evidence, not a production SLO, cross-platform claim, or capacity commitment.",
        "",
        "## Profile coverage",
        "",
        "| Workload | Distinct scenario boundary | CPU profile | Allocation evidence | Full-invariant proof | Allocation calls | Payload in/out bytes |",
        "| --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for profile in aggregate["profiles"]:
        payload = profile.get("payload_flow") or {}
        lines.append(
            "| {workload} | {semantics} | `{perf}` | `{allocation}` | `{proof}` | {allocation_calls} | {payload_in}/{payload_out} |".format(
                workload=profile["workload"],
                semantics=profile["scenario_semantics"].replace("|", "\\|"),
                perf=profile["perf"]["report"],
                allocation=profile["allocation"]["report"],
                proof=profile["full_invariant_proof"]["raw_results"],
                allocation_calls=display_number(profile["allocation"]["allocation_calls"]),
                payload_in=display_number(payload.get("input_bytes_submitted_to_typed_call")),
                payload_out=display_number(payload.get("output_bytes_returned_from_typed_call")),
            )
        )
    lines.extend(
        [
            "",
            "Each `perf` and Heaptrack process invokes one named real-composition path only. The retained full-invariant proof is a separate unprofiled full baseline and is the sole source for the canonical topology, containment, recovery, cleanup, and reclamation assertion. The aggregate rejects a missing targeted workload, duplicate semantics, a missing proof, or a command that omits `--profile-workload`.",
            "",
            "## Quantified contributors by workload",
            "",
        ]
    )
    for profile in aggregate["profiles"]:
        attribution_record = profile["contributor_attribution"]
        lines.extend(
            [
                f"### {profile['workload']}",
                "",
                "CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.",
                "",
                "| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |",
                "| --- | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for category, value in attribution_record["categories"].items():
            observed = value["observation_status"] == "observed_at_profiler_resolution"
            lines.append(
                "| {category} | {observation} | {cpu} | {inclusive_cpu} | {calls} | {peak} |".format(
                    category=category,
                    observation=(
                        "observed at profiler resolution"
                        if observed
                        else "not observed at profiler resolution"
                    ),
                    cpu=(display_number(value["cpu_self_percent"]) if value["cpu_self_percent"] else "—"),
                    inclusive_cpu=(
                        display_number(value["cpu_inclusive_percent"])
                        if value["cpu_inclusive_percent"]
                        else "—"
                    ),
                    calls=(display_number(value["allocation_calls"]) if value["allocation_calls"] else "—"),
                    peak=(
                        display_number(value["allocation_peak_bytes"])
                        if value["allocation_peak_bytes"]
                        else "—"
                    ),
                )
            )
        totals = attribution_record["totals"]
        lines.extend(
            [
                "",
                "Folded totals: CPU self {cpu}% and inclusive {inclusive_cpu}%, allocation calls {calls}, allocation peak bytes {peak}; process-exit Heaptrack residue `{leaked}`. Payload flow is {input_bytes} bytes submitted and {output_bytes} bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.".format(
                    cpu=display_number(totals["cpu_reported_self_percent"]),
                    inclusive_cpu=display_number(totals["cpu_reported_inclusive_percent"]),
                    calls=display_number(totals["allocation_calls"]),
                    peak=display_number(totals["allocation_peak_bytes"]),
                    leaked=profile["allocation"]["process_exit_leaked_memory"],
                    input_bytes=display_number((profile.get("payload_flow") or {}).get("input_bytes_submitted_to_typed_call")),
                    output_bytes=display_number((profile.get("payload_flow") or {}).get("output_bytes_returned_from_typed_call")),
                ),
                "",
                "A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.",
                "",
            ]
        )
    lines.extend(
        [
            "## Experiment matrix",
            "",
            "| Candidate | Runs | Prep us | Warm P50 us | At-cap/s | Queued/s | Fixed RSS | Prep Δ RSS | Peak RSS | Fixed VM | Prep Δ VM | Peak VM | Post-release Δ RSS / VM | Peak threads / sockets | Cache control | Topology / containment | #38 result |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for candidate in aggregate["candidates"].values():
        metrics = candidate["representatives"]
        comparisons = candidate.get("calibration_comparison")
        if isinstance(comparisons, dict):
            statuses = sorted(
                value.get("status", "not_available")
                for value in comparisons.values()
                if isinstance(value, dict)
            )
        else:
            scope = candidate.get("phase0_calibration")
            statuses = [
                scope.get("status", "not_available")
                if isinstance(scope, dict)
                else "not_available"
            ]
        lines.append(
            "| {name} | {runs} | {prep} | {warm} | {at_capacity} | {queued} | {fixed_rss} | {prep_delta} | {peak_rss} | {fixed_vm} | {prep_delta_vm} | {peak_vm} | {release_delta} / {release_delta_vm} | {threads} / {sockets} | {cache_control} | {topology} | {status} |".format(
                name=candidate["name"],
                runs=candidate["run_count"],
                prep=display_number(metrics.get("component_preparation_micros")),
                warm=display_number(metrics.get("warm_echo_p50_micros")),
                at_capacity=display_number(metrics.get("at_capacity_activations_per_second")),
                queued=display_number(metrics.get("bounded_queue_activations_per_second")),
                fixed_rss=display_number(metrics.get("fixed_runtime_rss_bytes")),
                prep_delta=display_number(metrics.get("prepared_state_rss_delta_bytes")),
                peak_rss=display_number(metrics.get("peak_rss_bytes")),
                fixed_vm=display_number(metrics.get("fixed_runtime_virtual_memory_bytes")),
                prep_delta_vm=display_number(
                    metrics.get("prepared_state_virtual_memory_delta_bytes")
                ),
                peak_vm=display_number(metrics.get("peak_virtual_memory_bytes")),
                release_delta=display_number(metrics.get("post_release_rss_delta_bytes")),
                release_delta_vm=display_number(
                    metrics.get("post_release_virtual_memory_delta_bytes")
                ),
                threads=display_number(metrics.get("peak_threads")),
                sockets="{open}/{listening}".format(
                    open=display_number(metrics.get("peak_open_sockets")),
                    listening=display_number(metrics.get("peak_listening_sockets")),
                ),
                cache_control="{status}; second={second}".format(
                    status=candidate["prepared_cache_reuse_control"]["status"],
                    second=display_number(
                        candidate["prepared_cache_reuse_control"]["second_prepare_micros"]
                    ),
                ),
                topology="{workers}w/{cells}c; hard invariants pass".format(
                    workers=candidate["topology"]["runtime_workers"],
                    cells=candidate["topology"]["pool_capacity"],
                ),
                status=", ".join(statuses) or "not_available",
            )
        )
    lines.extend(
        [
            "",
            "Fixed RSS/VM is the post-runtime, pre-component baseline. Preparation and post-release deltas are measured against that same baseline; peak values scan every retained process snapshot. `Cache control` is a direct same-key second prepare when enabled, or the explicitly non-reusable disabled-cache control. Every row retains the actual throughput values and complete canonical containment/reclamation checks in `aggregate.json`.",
            "",
            f"Each candidate retains per-run command provenance, complete measurement identity, and host/toolchain context in `aggregate.json`. The fixed {REFERENCE_CANDIDATE} reference candidate has at least {MINIMUM_ADOPTION_RUNS} exact-identity runs and is the only candidate eligible for an advisory-band result. Intentional alternate configurations are Phase 1 experiments and receive no Phase 0 advisory-band calculation.",
            "",
            "## Decisions and Phase 1 handoff",
            "",
        ]
    )
    for decision in aggregate["decisions"]:
        lines.extend(
            [
                f"### {decision['candidate']}: {decision['decision']}",
                "",
                f"{decision['rationale']} {decision['handoff']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Guardrails",
            "",
            "The final Phase 0 configuration remains: fixed node-owned workers and cells; bounded queues, caches, logs, diagnostics, and timing history; a fresh store, limiter, host state, activation context, import table, and instance for every invocation; affirmative cleanup before cell reuse; and no per-service process, thread, listener, connection, runtime instance, or persistent guest memory. Persistent AOT artifacts, provenance-sensitive compiler caches, snapshots, store/instance reuse, shared mutable guest instances, and native execution were not enabled.",
            "",
            "The required #39 resource soak must run after this branch is merged, using its final source tree and the retained default on-demand/COW configuration. It is the long-duration reclamation proof; these finite profiles do not replace it.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def display_number(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def profile_metric_range(profiles: Iterable[dict[str, Any]], metric: str) -> str:
    values = [
        value
        for profile in profiles
        for value in [profile.get("metrics", {}).get(metric)]
        if isinstance(value, (int, float))
    ]
    if not values:
        return "n/a"
    return f"{display_number(min(values))}-{display_number(max(values))}"


def top_cpu_sample(profile: dict[str, Any]) -> str:
    samples = profile.get("top_cpu_samples")
    if not isinstance(samples, list) or not samples:
        return "n/a"
    first = samples[0]
    if not isinstance(first, dict):
        return "n/a"
    percentage = first.get("percent")
    symbol = first.get("symbol")
    if not isinstance(percentage, (int, float)) or not isinstance(symbol, str):
        return "n/a"
    return f"{percentage:.2f}% {symbol}"


def aggregate(arguments: argparse.Namespace) -> None:
    profiles_directory = arguments.profiles_directory.resolve()
    candidates_directory = arguments.candidates_directory.resolve()
    archive_root = arguments.output_json.parent.resolve()
    host = load_json(arguments.host_observation, "hot-path host observation")
    ref_head = host.get("published_source_ref_head")
    if not isinstance(ref_head, str) or not re.fullmatch(r"[0-9a-f]{40}", ref_head):
        fail("host observation lacks a verified durable source-ref head")
    host_identity = validate_profile_host_observation(
        host,
        "hot-path wrapper host observation",
        arguments.source_commit,
        arguments.source_tree,
        arguments.published_source_ref,
        ref_head,
    )

    calibration = load_json(arguments.calibration_aggregate, "Phase 0 calibration aggregate")
    if calibration.get("status") != "pass":
        fail("Phase 0 calibration aggregate is not passing")

    if arguments.required_candidate_runs < MINIMUM_EXPERIMENT_RUNS:
        fail(
            f"required candidate run count must be at least {MINIMUM_EXPERIMENT_RUNS} "
            "for a bounded experiment matrix"
        )
    if arguments.required_reference_candidate_runs < MINIMUM_ADOPTION_RUNS:
        fail(
            f"required reference-candidate run count must be at least {MINIMUM_ADOPTION_RUNS}"
        )
    full_document, expected_checks, full_invariant_proof = load_full_invariant_proof(
        arguments.full_invariant_proof,
        archive_root,
        arguments.source_commit,
        arguments.source_tree,
        arguments.published_source_ref,
        ref_head,
    )
    full_command_identity = full_invariant_proof.get("command_identity")
    if not isinstance(full_command_identity, dict):
        fail("full-invariant proof has no command execution identity")
    full_process_host, full_host_observations = host_observation_record(
        arguments.full_invariant_proof.parent,
        "full-invariant proof baseline",
        archive_root,
        arguments.source_commit,
        arguments.source_tree,
        arguments.published_source_ref,
        ref_head,
        host_identity,
    )
    full_invariant_proof["host_observations"] = full_host_observations
    expected_environment = verify_run_environment(
        full_document,
        "full-invariant proof baseline",
        full_process_host,
        None,
        full_command_identity["execution_commit"],
    )
    full_measurement_identity = full_invariant_proof.get("measurement_identity")
    if not isinstance(full_measurement_identity, dict):
        fail("full-invariant proof has no exact measurement identity")
    require_calibration_match(
        {
            "run_count": 1,
            "measurement_identity": full_measurement_identity,
            "raw_runs": [{"environment": expected_environment}],
        },
        calibration,
        arguments.source_commit,
        arguments.source_tree,
        host_identity,
        "full-invariant proof",
        require_minimum_runs=False,
    )
    profiles: list[dict[str, Any]] = []
    for name in PROFILE_WORKLOADS:
        record = load_profile(
            profiles_directory,
            name,
            full_invariant_proof,
            archive_root,
            arguments.source_commit,
            arguments.source_tree,
            arguments.published_source_ref,
            ref_head,
            full_command_identity,
            expected_environment,
            host_identity,
        )
        profiles.append(record)
    semantics = [profile["scenario_semantics"] for profile in profiles]
    if len(set(semantics)) != len(semantics):
        fail("targeted profiles do not have distinct scenario semantics")
    scenario_sets = [tuple(profile["selected_scenarios"]) for profile in profiles]
    if len(set(scenario_sets)) != len(scenario_sets):
        fail("targeted profiles do not have distinct selected scenario sets")

    candidates: dict[str, dict[str, Any]] = {}
    for name in CANDIDATE_EXPECTATIONS:
        required_run_count = (
            arguments.required_reference_candidate_runs
            if name == REFERENCE_CANDIDATE
            else arguments.required_candidate_runs
        )
        candidate = load_candidate(
            candidates_directory,
            name,
            expected_checks,
            archive_root,
            arguments.source_commit,
            arguments.source_tree,
            arguments.published_source_ref,
            ref_head,
            full_command_identity,
            expected_environment,
            host_identity,
            required_run_count,
        )
        if name == REFERENCE_CANDIDATE:
            require_calibration_match(
                candidate,
                calibration,
                arguments.source_commit,
                arguments.source_tree,
                host_identity,
                "reference candidate",
            )
            candidate["calibration_comparison"] = comparison_to_calibration(
                candidate, calibration
            )
            candidate["calibration_comparison_eligibility"] = {
                "status": "reference_equivalent",
                "required_run_count": arguments.required_reference_candidate_runs,
            }
        else:
            candidate["phase0_calibration"] = phase1_experiment_scope(name)
        candidates[name] = candidate

    aggregate_document = {
        "schema_version": PROFILE_SCHEMA,
        "generated_at_utc": now_utc(),
        "status": "pass",
        "observational_only": True,
        "production_slo": False,
        "cross_platform_claim": False,
        "source_commit": arguments.source_commit,
        "source_tree": arguments.source_tree,
        "source_provenance": {
            "published_source_ref": arguments.published_source_ref,
            "published_source_ref_head": ref_head,
            "execution_identity": full_command_identity,
            "rule": "The runner fetched the durable ref, verified that the supplied commit exists, resolves to source_tree, and is reachable from the ref before execution.",
        },
        "host_observation": {
            "path": archive_path(arguments.host_observation, archive_root),
            "sha256": sha256_file(arguments.host_observation),
            "per_run_context_rule": (
                "Every retained full, targeted, and candidate document must carry "
                "the complete runtime environment and match this host observation "
                "and the full-invariant proof."
            ),
        },
        "calibration_reference": {
            "path": archive_path(arguments.calibration_aggregate, archive_root),
            "sha256": sha256_file(arguments.calibration_aggregate),
            "adoption_rule": (
                f"Only the fixed {REFERENCE_CANDIDATE} reference candidate is eligible "
                f"for Phase 0 advisory-band analysis, and it retains at least {MINIMUM_ADOPTION_RUNS} "
                "exact-identity runs."
            ),
            "comparison_rule": "Only the reference-equivalent default candidate may receive an inside/outside advisory-band result. Intentional Phase 1 configuration experiments retain raw observations without a Phase 0 calibration calculation.",
        },
        "hard_invariants": {
            "canonical_names": sorted(expected_checks),
            "full_invariant_proof": full_invariant_proof,
            "rule": "The separate full-invariant proof and every matrix baseline contain this exact set once and every check passed. Targeted profiler documents have their own reduced, workload-specific checks and cannot substitute for it.",
        },
        "profiles": [archive_profile_record(profile) for profile in profiles],
        "attribution": attribution(profiles),
        "candidates": candidates,
        "decisions": decision_records(candidates),
        "guardrails": {
            "resident_resource_formula": "fixed runtime + active activations + bounded shared preparation state",
            "fresh_store_per_invocation": True,
            "fixed_node_topology": True,
            "bounded_node_owned_state": True,
            "cleanup_proof_before_cell_reuse": True,
            "persistent_aot_or_compiler_cache": False,
            "store_or_instance_reuse": False,
            "native_execution": False,
        },
    }
    write_json(arguments.output_json, aggregate_document)
    write_report(arguments.output_report, aggregate_document)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subcommands = result.add_subparsers(dest="command", required=True)
    capture = subcommands.add_parser("capture-host", help="record native-Linux profiling context")
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--source-commit", required=True)
    capture.add_argument("--source-tree", required=True)
    capture.add_argument("--published-source-ref", required=True)
    capture.add_argument("--published-source-ref-head", required=True)
    capture.add_argument("--repository-root", type=Path, required=True)
    summarize = subcommands.add_parser(
        "summarize-heaptrack",
        help="compact transient Heaptrack folded stacks into auditable category totals",
    )
    summarize.add_argument("--allocation-folded", type=Path, required=True)
    summarize.add_argument("--peak-folded", type=Path, required=True)
    summarize.add_argument("--raw-heaptrack-data", type=Path, required=True)
    summarize.add_argument("--output", type=Path, required=True)
    summary = subcommands.add_parser("aggregate", help="validate and summarize one profile archive")
    summary.add_argument("--profiles-directory", type=Path, required=True)
    summary.add_argument("--full-invariant-proof", type=Path, required=True)
    summary.add_argument("--candidates-directory", type=Path, required=True)
    summary.add_argument("--host-observation", type=Path, required=True)
    summary.add_argument("--calibration-aggregate", type=Path, required=True)
    summary.add_argument("--source-commit", required=True)
    summary.add_argument("--source-tree", required=True)
    summary.add_argument("--published-source-ref", required=True)
    summary.add_argument("--required-candidate-runs", type=int, required=True)
    summary.add_argument("--required-reference-candidate-runs", type=int, default=MINIMUM_ADOPTION_RUNS)
    summary.add_argument("--output-json", type=Path, required=True)
    summary.add_argument("--output-report", type=Path, required=True)
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.command == "capture-host":
            capture_host(
                arguments.output,
                arguments.source_commit,
                arguments.source_tree,
                arguments.published_source_ref,
                arguments.published_source_ref_head,
                arguments.repository_root.resolve(),
            )
        elif arguments.command == "summarize-heaptrack":
            summarize_heaptrack_contributors(
                arguments.allocation_folded,
                arguments.peak_folded,
                arguments.raw_heaptrack_data,
                arguments.output,
            )
        else:
            aggregate(arguments)
    except HotPathError as error:
        print(f"hot-path profile validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
