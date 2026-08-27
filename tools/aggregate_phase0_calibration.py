#!/usr/bin/env python3
"""Capture and aggregate repeated native-Linux Phase 0 full-profile runs.

The baseline executable owns all correctness, topology, containment, and
reclamation assertions. This helper preserves those assertions as binary:
no failed or malformed run may be removed because of a performance value.
"""

from __future__ import annotations

import argparse
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


BASELINE_SCHEMA = "latent.phase0.baseline.v2"
CALIBRATION_SCHEMA = "latent.phase0.calibration.v1"
HOST_OBSERVATION_SCHEMA = "latent.phase0.calibration.host-observation.v1"
MINIMUM_REFERENCE_RUNS = 7
ROBUST_OUTLIER_THRESHOLD = 3.5
MAD_NORMALIZATION = 1.4826


class CalibrationError(Exception):
    """The calibration is incomplete, invalid, or not comparable."""


def fail(message: str) -> NoReturn:
    raise CalibrationError(message)


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def read_first_line(path: Path) -> str | None:
    value = read_text(path)
    if value is None:
        return None
    return value.splitlines()[0] if value else ""


def run_command(arguments: list[str]) -> str:
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
    if completed.returncode != 0:
        return "unavailable"
    return "none"


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


def numeric_values(values: Iterable[str | None]) -> list[int]:
    result: list[int] = []
    for value in values:
        if value is None:
            continue
        try:
            result.append(int(value))
        except ValueError:
            continue
    return result


def cpu_frequency_policy() -> dict[str, Any]:
    roots = sorted(Path("/sys/devices/system/cpu").glob("cpu[0-9]*"))
    fields = (
        "scaling_driver",
        "scaling_governor",
        "energy_performance_preference",
        "scaling_min_freq",
        "scaling_max_freq",
        "scaling_cur_freq",
        "cpuinfo_min_freq",
        "cpuinfo_max_freq",
    )
    observed: dict[str, list[str]] = {field: [] for field in fields}
    cpus_with_policy = 0
    for root in roots:
        cpufreq = root / "cpufreq"
        if cpufreq.exists():
            cpus_with_policy += 1
        for field in fields:
            value = read_first_line(cpufreq / field)
            if value is not None:
                observed[field].append(value)
    unique = {
        field: sorted(set(values)) for field, values in observed.items() if values
    }
    current = numeric_values(unique.get("scaling_cur_freq", []))
    return {
        "cpus_with_cpufreq_sysfs": cpus_with_policy,
        "observed": unique,
        "current_frequency_khz_range": (
            {"minimum": min(current), "maximum": max(current)} if current else None
        ),
        "notes": (
            "Read-only Linux cpufreq observations. The command does not pin "
            "governors or frequencies."
        ),
    }


def allocator_observation(repository_root: Path) -> dict[str, Any]:
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
            "set (value intentionally not recorded)"
            if os.environ.get("LD_PRELOAD")
            else "unset"
        ),
        "malloc_conf": (
            "set (value intentionally not recorded)"
            if os.environ.get("MALLOC_CONF")
            else "unset"
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
    repository_root: Path,
) -> None:
    kernel = run_command(["uname", "-srvmo"])
    kernel_text = "\n".join(
        filter(
            None,
            [
                read_text(Path("/proc/sys/kernel/osrelease")),
                read_text(Path("/proc/version")),
            ],
        )
    ).lower()
    wsl_detected = "microsoft" in kernel_text or "wsl" in kernel_text
    container = run_command(["systemd-detect-virt", "--container"])
    virtualization = run_command(["systemd-detect-virt"])
    virtual_machine = run_command(["systemd-detect-virt", "--vm"])
    memory = parse_meminfo()
    payload = {
        "schema_version": HOST_OBSERVATION_SCHEMA,
        "captured_at_utc": now_utc(),
        "phase": phase,
        "run_index": run_index,
        "source_commit": source_commit,
        "source_identity": {
            "published_commit": source_commit,
            "published_tree": source_tree,
            "execution_commit": execution_commit,
            "execution_tree": execution_tree,
            "tree_identity_verified": execution_tree == source_tree,
            "rule": (
                "The local execution worktree must have the exact Git tree of the "
                "reachable published source commit before a calibration run starts."
            ),
        },
        "operating_system": platform.system().lower(),
        "architecture": platform.machine(),
        "kernel": kernel,
        "native_linux_reference": (
            platform.system() == "Linux"
            and not wsl_detected
            and container in ("none", "unavailable")
        ),
        "virtualization": {
            "systemd_detect_virt": virtualization,
            "systemd_detect_virt_container": container,
            "systemd_detect_virt_vm": virtual_machine,
            "wsl_detected": wsl_detected,
        },
        "cpu_frequency_policy": cpu_frequency_policy(),
        "allocator": allocator_observation(repository_root),
        "background_load": {
            "load_average": parse_loadavg(),
            "memory_available_bytes": memory.get("MemAvailable"),
            "memory_free_bytes": memory.get("MemFree"),
            "swap_free_bytes": memory.get("SwapFree"),
            "notes": (
                "Load average, runnable tasks, and memory availability are captured "
                "before and after every full-profile process. No run is excluded "
                "based on this context."
            ),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read JSON {path}: {error}")
    if not isinstance(payload, dict):
        fail(f"JSON document {path} must be an object")
    return payload


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


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def relative_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def hard_invariant_names(document: dict[str, Any], run_label: str) -> set[str]:
    checks = document.get("checks")
    if not isinstance(checks, list) or not checks:
        fail(f"{run_label} has no hard invariant checks")
    names: set[str] = set()
    failures: list[str] = []
    for index, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            fail(f"{run_label} has a malformed hard invariant at position {index}")
        name = check.get("name")
        if not isinstance(name, str) or not name.strip():
            fail(f"{run_label} has an unnamed hard invariant at position {index}")
        if name in names:
            fail(f"{run_label} has a duplicate hard invariant: {name}")
        names.add(name)
        if check.get("passed") is not True:
            failures.append(name)
    if failures:
        fail(f"{run_label} has failed hard invariants: {', '.join(failures)}")
    return names


def validate_baseline(
    document: dict[str, Any], source_commit: str, run_label: str
) -> set[str]:
    if document.get("schema_version") != BASELINE_SCHEMA:
        fail(f"{run_label} has an unexpected baseline schema")
    if document.get("status") != "pass":
        fail(f"{run_label} did not pass the full profile")
    if value_at(document, "config.mode") != "full":
        fail(f"{run_label} is not a full-profile run")
    if value_at(document, "environment.operating_system") != "linux":
        fail(f"{run_label} does not report Linux as its benchmark operating system")
    kernel = str(value_at(document, "environment.kernel")).lower()
    if "microsoft" in kernel or "wsl" in kernel:
        fail(f"{run_label} is a WSL result and cannot be the calibration reference")
    if value_at(document, "environment.repository_commit") != source_commit:
        fail(f"{run_label} did not use source commit {source_commit}")
    check_names = hard_invariant_names(document, run_label)
    samples = value_at(document, "executable_harness.samples")
    if not isinstance(samples, list) or len(samples) < 3:
        fail(f"{run_label} lacks independent executable cold samples")
    probes = value_at(document, "executable_harness.failure_recovery_samples")
    scenarios = {
        probe.get("scenario") for probe in probes if isinstance(probe, dict)
    }
    if scenarios != {"trap", "timeout", "trap_then_recovery"}:
        fail(f"{run_label} has incomplete executable failure/recovery evidence")
    return check_names


def median(values: list[float]) -> float:
    if not values:
        fail("cannot calculate a median for an empty set")
    return float(statistics.median(values))


def summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        fail("cannot summarize an empty set")
    ordered = sorted(values)
    center = median(ordered)
    mad = median([abs(value - center) for value in ordered])
    mean = statistics.fmean(ordered)
    if len(ordered) < 2 or math.isclose(mean, 0.0):
        cv = None
        reason = (
            "undefined for fewer than two samples"
            if len(ordered) < 2
            else "undefined when the mean is zero"
        )
    else:
        cv = statistics.stdev(ordered) / abs(mean) * 100.0
        reason = None
    return {
        "sample_count": len(ordered),
        "minimum": ordered[0],
        "maximum": ordered[-1],
        "median": center,
        "mean": mean,
        "median_absolute_deviation": mad,
        "coefficient_of_variation_percent": cv,
        "coefficient_of_variation_not_meaningful_reason": reason,
    }


def outliers(representatives: dict[str, float]) -> list[dict[str, Any]]:
    values = list(representatives.values())
    if len(values) < 3:
        return []
    center = median(values)
    mad = median([abs(value - center) for value in values])
    result: list[dict[str, Any]] = []
    if math.isclose(mad, 0.0):
        for run, value in representatives.items():
            if not math.isclose(value, center):
                result.append(
                    {
                        "run": run,
                        "value": value,
                        "median": center,
                        "reason": "deviates from a zero-MAD run-level median",
                    }
                )
        return result
    scale = MAD_NORMALIZATION * mad
    for run, value in representatives.items():
        robust_z = abs(value - center) / scale
        if robust_z > ROBUST_OUTLIER_THRESHOLD:
            result.append(
                {
                    "run": run,
                    "value": value,
                    "median": center,
                    "robust_z": robust_z,
                    "reason": (
                        f"run-level robust z-score exceeds "
                        f"{ROBUST_OUTLIER_THRESHOLD:g}"
                    ),
                }
            )
    return result


def comparison_band(
    unit: str, direction: str, run_summary: dict[str, Any], advisory: bool
) -> dict[str, Any] | None:
    if not advisory:
        return None
    reference = float(run_summary["median"])
    mad = float(run_summary["median_absolute_deviation"])
    if unit == "microseconds":
        absolute_floor, relative_floor = 10.0, 0.10
    elif unit == "bytes":
        absolute_floor, relative_floor = float(1024 * 1024), 0.10
    elif unit == "activations_per_second":
        absolute_floor, relative_floor = 1.0, 0.15
    else:
        absolute_floor, relative_floor = 1.0, 0.10
    delta = max(3.0 * mad, abs(reference) * relative_floor, absolute_floor)
    rule = (
        "candidate median > reference median + advisory_noise_band"
        if direction == "increase_is_regression"
        else "candidate median < reference median - advisory_noise_band"
    )
    return {
        "comparison_statistic": "median of per-run representative values",
        "direction": direction,
        "reference_median": reference,
        "advisory_noise_band": delta,
        "noise_band_formula": (
            f"max(3 x run-level MAD, {relative_floor:.0%} x absolute reference "
            f"median, {absolute_floor:g} {unit})"
        ),
        "candidate_regression_rule": rule,
        "no_detectable_regression_rule": (
            "A candidate inside this advisory noise band has no detectable regression "
            "when it has at least seven valid comparable runs, a stable environment, "
            "all hard invariants passing, and no material run-level outlier."
        ),
        "inconclusive_rule": (
            "Insufficient samples, environment instability, or a material run-level "
            "outlier is inconclusive and must be rerun."
        ),
        "ci_enforcement": "never a shared-hosted-CI pass/fail threshold",
    }


class MetricCollector:
    def __init__(self) -> None:
        self.metrics: dict[str, dict[str, Any]] = {}

    def add(
        self,
        name: str,
        *,
        run: str,
        values: Iterable[float],
        label: str,
        group: str,
        unit: str,
        direction: str,
        advisory: bool = True,
    ) -> None:
        numeric = [float(value) for value in values]
        if not numeric:
            fail(f"{run} has no observations for required metric {name}")
        entry = self.metrics.setdefault(
            name,
            {
                "label": label,
                "group": group,
                "unit": unit,
                "direction": direction,
                "advisory": advisory,
                "values": [],
                "by_run": defaultdict(list),
            },
        )
        if (
            entry["label"],
            entry["group"],
            entry["unit"],
            entry["direction"],
        ) != (label, group, unit, direction):
            fail(f"inconsistent metric metadata for {name}")
        entry["values"].extend(numeric)
        entry["by_run"][run].extend(numeric)

    def render(self) -> dict[str, Any]:
        rendered: dict[str, Any] = {}
        for name, metric in sorted(self.metrics.items()):
            representatives = {
                run: median(values) for run, values in sorted(metric["by_run"].items())
            }
            run_summary = summarize(list(representatives.values()))
            rendered[name] = {
                "label": metric["label"],
                "group": metric["group"],
                "unit": metric["unit"],
                "direction": metric["direction"],
                "samples": summarize(metric["values"]),
                "run_count": len(representatives),
                "per_run_representatives": representatives,
                "run_representatives": run_summary,
                "run_level_outliers": outliers(representatives),
                "comparison": comparison_band(
                    metric["unit"],
                    metric["direction"],
                    run_summary,
                    bool(metric["advisory"]),
                ),
            }
        return rendered


PHASE_METRICS = (
    ("component_post_return_micros", "Component canonical post-return"),
    (
        "activation_resource_reclamation_micros",
        "Activation-resource reclamation",
    ),
    ("outcome_classification_micros", "Outcome classification"),
    ("reusable_proof_micros", "Reusable-proof return"),
    (
        "cell_disposition_micros",
        "Cell release or quarantine disposition",
    ),
    ("post_invocation_cleanup_micros", "Post-invocation cleanup"),
)


def add_metrics(collector: MetricCollector, document: dict[str, Any], run: str) -> None:
    runtime_ready = number_at(document, "timings.process_launch_to_runtime_ready_micros")
    rust_runtime_ready = number_at(document, "timings.rust_entry_to_runtime_ready_micros")
    retained_ready = number_at(
        document, "timings.rust_entry_to_first_invocation_ready_micros"
    )
    collector.add(
        "process_launch_to_runtime_ready_micros",
        run=run,
        values=[runtime_ready],
        label="External process launch to runtime/pool ready",
        group="Startup and preparation",
        unit="microseconds",
        direction="increase_is_regression",
    )
    collector.add(
        "process_launch_to_ready_to_invoke_micros",
        run=run,
        values=[runtime_ready + max(0.0, retained_ready - rust_runtime_ready)],
        label="Derived external process launch to ready-to-invoke",
        group="Startup and preparation",
        unit="microseconds",
        direction="increase_is_regression",
    )
    for name, label in (
        ("capsule_validation_and_load_micros", "Capsule validation and component load"),
        ("wasmtime_engine_construction_micros", "Wasmtime engine/backend construction"),
        ("component_preparation_micros", "Component preparation"),
        ("prepared_component_release_micros", "Prepared-component release"),
    ):
        collector.add(
            name,
            run=run,
            values=[number_at(document, f"timings.{name}")],
            label=label,
            group="Startup and preparation",
            unit="microseconds",
            direction="increase_is_regression",
        )

    executable = value_at(document, "executable_harness.samples")
    if not isinstance(executable, list):
        fail(f"{run} executable samples must be a list")
    executable_samples = [sample for sample in executable if isinstance(sample, dict)]
    if len(executable_samples) != len(executable):
        fail(f"{run} has a malformed executable sample")
    collector.add(
        "process_launch_to_completion_real_executable_micros",
        run=run,
        values=[number_at(sample, "launch_to_completion_micros") for sample in executable_samples],
        label="Real executable process launch to completion",
        group="Cold and warm activation",
        unit="microseconds",
        direction="increase_is_regression",
    )
    collector.add(
        "cold_activation_elapsed_micros",
        run=run,
        values=[number_at(sample, "activation_elapsed_micros") for sample in executable_samples],
        label="Cold activation inside real executable harness",
        group="Cold and warm activation",
        unit="microseconds",
        direction="increase_is_regression",
    )

    raw_samples = value_at(document, "activation_samples")
    if not isinstance(raw_samples, list):
        fail(f"{run} activation samples must be a list")
    samples = [sample for sample in raw_samples if isinstance(sample, dict)]
    if len(samples) != len(raw_samples):
        fail(f"{run} has a malformed activation sample")

    def scenario_values(scenario: str) -> list[float]:
        values = [
            number_at(sample, "elapsed_micros")
            for sample in samples
            if sample.get("scenario") == scenario
        ]
        if not values:
            fail(f"{run} has no {scenario} activation samples")
        return values

    collector.add(
        "warm_activation_elapsed_micros",
        run=run,
        values=scenario_values("warm_echo"),
        label="Warm activation latency",
        group="Cold and warm activation",
        unit="microseconds",
        direction="increase_is_regression",
    )
    collector.add(
        "trap_elapsed_micros",
        run=run,
        values=scenario_values("trap"),
        label="Trap containment latency",
        group="Containment and recovery",
        unit="microseconds",
        direction="increase_is_regression",
    )
    for scenario, label in (
        ("recovery_after_domain_error", "Recovery after domain error"),
        ("recovery_after_trap", "Recovery after trap"),
        ("recovery_after_timeout", "Recovery after timeout"),
        ("recovery_after_cancellation", "Recovery after cancellation"),
        ("recovery_after_memory_pressure", "Recovery after memory pressure"),
    ):
        collector.add(
            f"{scenario}_elapsed_micros",
            run=run,
            values=scenario_values(scenario),
            label=label,
            group="Containment and recovery",
            unit="microseconds",
            direction="increase_is_regression",
        )

    collector.add(
        "activation_acquire_or_queue_wait_micros",
        run=run,
        values=[
            number_at(sample, "phase_timings.acquire_or_queue_wait_micros")
            for sample in samples
        ],
        label="Activation acquire or queue wait",
        group="Queueing and release",
        unit="microseconds",
        direction="increase_is_regression",
    )
    queued = [
        sample
        for sample in samples
        if value_at(sample, "phase_timings.acquisition_queued") is True
    ]
    collector.add(
        "activation_queued_acquire_wait_micros",
        run=run,
        values=[
            number_at(sample, "phase_timings.acquire_or_queue_wait_micros")
            for sample in queued
        ],
        label="Queued activation acquire wait",
        group="Queueing and release",
        unit="microseconds",
        direction="increase_is_regression",
    )
    collector.add(
        "activation_cell_disposition_micros",
        run=run,
        values=[
            number_at(sample, "phase_timings.cell_disposition_micros")
            for sample in samples
        ],
        label="Activation cell release or quarantine disposition",
        group="Queueing and release",
        unit="microseconds",
        direction="increase_is_regression",
    )
    for source, label in PHASE_METRICS:
        collector.add(
            source,
            run=run,
            values=[number_at(sample, f"phase_timings.{source}") for sample in samples],
            label=label,
            group="Post-invocation cleanup",
            unit="microseconds",
            direction="increase_is_regression",
        )
    for scenario, metric, label in (
        ("timeout", "timeout_overshoot_micros", "Timeout interruption overshoot"),
        (
            "cancellation",
            "cancellation_overshoot_micros",
            "Cancellation interruption overshoot",
        ),
    ):
        overshoot = [
            sample.get("timeout_or_cancel_overshoot_micros")
            for sample in samples
            if sample.get("scenario") == scenario
        ]
        if not overshoot or any(value is None for value in overshoot):
            fail(f"{run} has no {scenario} overshoot samples")
        collector.add(
            metric,
            run=run,
            values=[float(value) for value in overshoot if value is not None],
            label=label,
            group="Containment and recovery",
            unit="microseconds",
            direction="increase_is_regression",
        )

    pool_probe = value_at(document, "pool_probe")
    if not isinstance(pool_probe, dict):
        fail(f"{run} pool probe must be an object")
    for source, metric, label in (
        ("acquire_micros", "fixed_pool_acquire_p50_micros", "Fixed-pool acquire P50"),
        (
            "queued_wait_micros",
            "fixed_pool_queued_wait_p50_micros",
            "Fixed-pool queued wait P50",
        ),
        ("release_micros", "fixed_pool_release_p50_micros", "Fixed-pool release P50"),
    ):
        collector.add(
            metric,
            run=run,
            values=[number_at(pool_probe, f"{source}.p50")],
            label=label,
            group="Queueing and release",
            unit="microseconds",
            direction="increase_is_regression",
        )

    throughput = value_at(document, "activation_throughput")
    if not isinstance(throughput, dict):
        fail(f"{run} throughput section must be an object")
    for source, metric, label in (
        (
            "at_capacity",
            "at_capacity_activations_per_second",
            "At-capacity activation throughput",
        ),
        (
            "bounded_queue_saturation",
            "bounded_queue_saturation_activations_per_second",
            "Bounded-queue-saturation activation throughput",
        ),
    ):
        collector.add(
            metric,
            run=run,
            values=[number_at(throughput, f"{source}.activations_per_second")],
            label=label,
            group="Activation throughput",
            unit="activations_per_second",
            direction="decrease_is_regression",
        )

    process_snapshots = value_at(document, "process_snapshots")
    if not isinstance(process_snapshots, list) or not process_snapshots:
        fail(f"{run} has no process resource snapshots")
    for source, metric, label in (
        ("rss_bytes", "process_peak_rss_bytes", "Process peak RSS"),
        (
            "virtual_memory_bytes",
            "process_peak_virtual_memory_bytes",
            "Process peak virtual memory",
        ),
        ("thread_count", "process_peak_thread_count", "Process peak thread count"),
        (
            "file_descriptor_count",
            "process_peak_file_descriptor_count",
            "Process peak file-descriptor count",
        ),
        ("open_socket_count", "process_peak_open_socket_count", "Process peak open sockets"),
        (
            "listening_socket_count",
            "process_peak_listening_socket_count",
            "Process peak listening sockets",
        ),
    ):
        values = [
            sample.get(source)
            for sample in process_snapshots
            if isinstance(sample, dict) and sample.get(source) is not None
        ]
        if not values:
            fail(f"{run} has no {source} resource observations")
        collector.add(
            metric,
            run=run,
            values=[max(float(value) for value in values)],
            label=label,
            group="Process resources (per-run peak)",
            unit="bytes" if source in ("rss_bytes", "virtual_memory_bytes") else "count",
            direction="increase_is_regression",
            advisory=source in ("rss_bytes", "virtual_memory_bytes"),
        )


def identity(document: dict[str, Any]) -> dict[str, Any]:
    environment = value_at(document, "environment")
    artifact = value_at(document, "artifact")
    config = value_at(document, "config")
    if not all(isinstance(value, dict) for value in (environment, artifact, config)):
        fail("baseline identity sections must be objects")
    return {
        "environment": {
            field: environment.get(field)
            for field in (
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
        },
        "artifact": {
            field: artifact.get(field) for field in ("component_digest", "component_bytes")
        },
        "config": config,
    }


def host_comparability_identity(observation: dict[str, Any]) -> dict[str, Any]:
    policy = observation.get("cpu_frequency_policy")
    if not isinstance(policy, dict):
        fail("host observation lacks CPU frequency/power-policy data")
    observed = policy.get("observed")
    if not isinstance(observed, dict):
        fail("host observation has malformed CPU frequency/power-policy data")
    static_observed = {
        field: value
        for field, value in observed.items()
        if field != "scaling_cur_freq"
    }
    return {
        "virtualization": observation.get("virtualization"),
        "allocator": observation.get("allocator"),
        "cpu_frequency_policy": {
            "cpus_with_cpufreq_sysfs": policy.get("cpus_with_cpufreq_sysfs"),
            "observed": static_observed,
        },
    }


def validate_source_identity(
    observation: dict[str, Any],
    *,
    run: str,
    phase: str,
    source_commit: str,
    source_tree: str,
) -> dict[str, Any]:
    source_identity = observation.get("source_identity")
    if not isinstance(source_identity, dict):
        fail(f"{run} host observation lacks source-tree provenance ({phase})")
    required = (
        "published_commit",
        "published_tree",
        "execution_commit",
        "execution_tree",
        "tree_identity_verified",
    )
    missing = [field for field in required if field not in source_identity]
    if missing:
        fail(
            f"{run} host observation has incomplete source-tree provenance "
            f"({phase}): {', '.join(missing)}"
        )
    if source_identity["published_commit"] != source_commit:
        fail(f"{run} host observation does not match the published source commit")
    if source_identity["published_tree"] != source_tree:
        fail(f"{run} host observation does not match the published source tree")
    if source_identity["execution_tree"] != source_tree:
        fail(
            f"{run} execution worktree does not match the published source tree "
            f"({phase})"
        )
    if source_identity["tree_identity_verified"] is not True:
        fail(f"{run} did not verify published and execution tree identity ({phase})")
    execution_commit = source_identity["execution_commit"]
    if not isinstance(execution_commit, str) or not execution_commit:
        fail(f"{run} host observation has no execution commit ({phase})")
    return {
        "published_commit": source_commit,
        "published_tree": source_tree,
        "execution_commit": execution_commit,
        "execution_tree": source_tree,
        "tree_identity_verified": True,
    }


def host_summary(
    observations: list[tuple[str, dict[str, Any], dict[str, Any], Path, Path]],
    calibration_root: Path,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    loads: list[float] = []
    memories: list[float] = []
    for run, before, after, before_path, after_path in observations:
        for observation in (before, after):
            load = value_at(observation, "background_load.load_average")
            if isinstance(load, dict) and isinstance(load.get("one_minute"), (int, float)):
                loads.append(float(load["one_minute"]))
            memory = value_at(observation, "background_load.memory_available_bytes")
            if isinstance(memory, (int, float)):
                memories.append(float(memory))
        records.append(
            {
                "run": run,
                "before": relative_path(before_path, calibration_root),
                "after": relative_path(after_path, calibration_root),
                "virtualization": before.get("virtualization"),
                "cpu_frequency_policy": before.get("cpu_frequency_policy"),
                "allocator": before.get("allocator"),
                "background_load": {
                    "before": before.get("background_load"),
                    "after": after.get("background_load"),
                },
            }
        )
    return {
        "native_linux_reference": all(
            before.get("native_linux_reference") is True
            and after.get("native_linux_reference") is True
            for _, before, after, _, _ in observations
        ),
        "runs": records,
        "one_minute_load_range": (
            {"minimum": min(loads), "maximum": max(loads)} if loads else None
        ),
        "available_memory_bytes_range": (
            {"minimum": min(memories), "maximum": max(memories)} if memories else None
        ),
    }


def build_aggregate(
    runs_directory: Path, source_commit: str, source_tree: str, minimum_runs: int
) -> dict[str, Any]:
    run_dirs = sorted(
        path
        for path in runs_directory.iterdir()
        if path.is_dir() and path.name.startswith("run-")
    )
    if len(run_dirs) < minimum_runs:
        fail(f"expected at least {minimum_runs} full-profile runs, found {len(run_dirs)}")
    calibration_root = runs_directory.parent
    collector = MetricCollector()
    identities: list[tuple[str, dict[str, Any]]] = []
    host_identities: list[tuple[str, dict[str, Any]]] = []
    source_identities: list[tuple[str, dict[str, Any]]] = []
    raw_runs: list[dict[str, Any]] = []
    observations: list[tuple[str, dict[str, Any], dict[str, Any], Path, Path]] = []
    expected_check_names: set[str] | None = None
    expected_check_run: str | None = None
    for run_dir in run_dirs:
        run = run_dir.name
        raw_path = run_dir / "raw-results.json"
        report_path = run_dir / "BASELINE.md"
        before_path = run_dir / "host-before.json"
        after_path = run_dir / "host-after.json"
        execution_path = run_dir / "execution-status.json"
        document = load_json(raw_path)
        before = load_json(before_path)
        after = load_json(after_path)
        execution = load_json(execution_path)
        check_names = validate_baseline(document, source_commit, run)
        if expected_check_names is None:
            expected_check_names = check_names
            expected_check_run = run
        elif check_names != expected_check_names:
            missing_checks = sorted(expected_check_names - check_names)
            unexpected_checks = sorted(check_names - expected_check_names)
            differences: list[str] = []
            if missing_checks:
                differences.append(f"missing: {', '.join(missing_checks)}")
            if unexpected_checks:
                differences.append(f"unexpected: {', '.join(unexpected_checks)}")
            fail(
                f"{run} hard invariant set differs from canonical {expected_check_run} "
                f"set ({'; '.join(differences)})"
            )
        if (
            execution.get("schema_version")
            != "latent.phase0.calibration.execution-status.v1"
            or execution.get("source_commit") != source_commit
            or execution.get("source_tree") != source_tree
            or execution.get("execution_tree") != source_tree
            or not isinstance(execution.get("execution_commit"), str)
            or not execution.get("execution_commit")
            or execution.get("exit_code") != 0
        ):
            fail(f"{run} did not complete the full-profile command successfully")
        before_source_identity: dict[str, Any] | None = None
        for phase, observation in (("before", before), ("after", after)):
            if observation.get("schema_version") != HOST_OBSERVATION_SCHEMA:
                fail(f"{run} has an unexpected host observation schema ({phase})")
            if observation.get("source_commit") != source_commit:
                fail(f"{run} host observation does not match the source commit")
            if observation.get("native_linux_reference") is not True:
                fail(f"{run} is not a native-Linux reference environment")
            observed_source_identity = validate_source_identity(
                observation,
                run=run,
                phase=phase,
                source_commit=source_commit,
                source_tree=source_tree,
            )
            if before_source_identity is None:
                before_source_identity = observed_source_identity
            elif stable_json(observed_source_identity) != stable_json(
                before_source_identity
            ):
                fail(f"{run} changed source provenance during its full-profile process")
        if before_source_identity is None:
            fail(f"{run} has no host source provenance")
        if execution["execution_commit"] != before_source_identity["execution_commit"]:
            fail(f"{run} execution status does not match host source provenance")
        identities.append((run, identity(document)))
        host_identities.append((run, host_comparability_identity(before)))
        source_identities.append((run, before_source_identity))
        add_metrics(collector, document, run)
        raw_runs.append(
            {
                "run": run,
                "raw_results": relative_path(raw_path, calibration_root),
                "baseline_report": relative_path(report_path, calibration_root),
                "host_before": relative_path(before_path, calibration_root),
                "host_after": relative_path(after_path, calibration_root),
                "execution_status": relative_path(execution_path, calibration_root),
                "status": document["status"],
                "generated_at_unix_millis": document.get("generated_at_unix_millis"),
            }
        )
        observations.append((run, before, after, before_path, after_path))
    reference_identity = identities[0][1]
    inconsistent = [
        run
        for run, run_identity in identities
        if stable_json(run_identity) != stable_json(reference_identity)
    ]
    if inconsistent:
        fail(
            "every run must retain the same environment, toolchain, fixture digest, "
            f"configuration, and build profile; inconsistent: {', '.join(inconsistent)}"
        )
    reference_host_identity = host_identities[0][1]
    inconsistent_hosts = [
        run
        for run, run_identity in host_identities
        if stable_json(run_identity) != stable_json(reference_host_identity)
    ]
    if inconsistent_hosts:
        fail(
            "all runs must retain the same virtualization, allocator, and static "
            f"CPU frequency/power policy; inconsistent: {', '.join(inconsistent_hosts)}"
        )
    reference_source_identity = source_identities[0][1]
    inconsistent_source_identities = [
        run
        for run, run_identity in source_identities
        if stable_json(run_identity) != stable_json(reference_source_identity)
    ]
    if inconsistent_source_identities:
        fail(
            "all runs must retain the same published and execution source provenance; "
            f"inconsistent: {', '.join(inconsistent_source_identities)}"
        )
    if expected_check_names is None:
        fail("no hard invariant set was available to validate")
    metrics = collector.render()
    return {
        "schema_version": CALIBRATION_SCHEMA,
        "status": "pass",
        "generated_at_utc": now_utc(),
        "observational_only": True,
        "production_slo": False,
        "cross_machine_claim": False,
        "run_count": len(run_dirs),
        "minimum_required_run_count": minimum_runs,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "source_provenance": {
            **reference_source_identity,
            "rule": (
                "The published commit must remain reachable, and every local execution "
                "worktree must exactly match its recorded Git tree."
            ),
        },
        "reference_identity": reference_identity,
        "raw_runs": raw_runs,
        "hard_invariants": {
            "all_runs_passed": True,
            "checks_passed_in_every_run": sorted(expected_check_names),
            "canonical_check_set_derived_from": expected_check_run,
            "check_set_rule": (
                "The first validated run defines the canonical hard-invariant name set. "
                "Every later run must contain exactly that set once, with every check "
                "passing; duplicates, omissions, and unexpected checks invalidate "
                "calibration."
            ),
            "performance_runs_excluded": 0,
            "rule": (
                "A failed check, missing raw run, environment mismatch, or malformed "
                "probe invalidates calibration. Timing, throughput, and resource values "
                "never cause a run to be discarded."
            ),
        },
        "host_observations": host_summary(observations, calibration_root),
        "metrics": metrics,
        "material_run_level_outliers": {
            name: metric["run_level_outliers"]
            for name, metric in metrics.items()
            if metric["run_level_outliers"]
        },
        "comparison_method": {
            "applicability": (
                "Compare only a candidate with at least seven independent full-profile "
                "runs whose CPU, logical CPU count, memory, kernel, virtualization, "
                "Rust/Cargo/Wasmtime versions, target, build profile, allocator, "
                "fixture digest, and configuration are materially equivalent."
            ),
            "hard_invariant_rule": (
                "Topology, capacity, containment, cleanup, and reclamation checks remain "
                "binary. Any failure is a failure, never a statistical tolerance."
            ),
            "no_detectable_regression_rule": (
                "An inside-band candidate is terminally no detectable regression or "
                "statistically indistinguishable when it has at least seven valid "
                "comparable runs, a stable environment, all hard invariants passing, "
                "and no material run-level outlier."
            ),
            "inconclusive_rule": (
                "Insufficient samples, environment instability or mismatch, a material "
                "run-level outlier, or a failed hard invariant is inconclusive and "
                "must be rerun after the invalid condition is resolved."
            ),
            "regression_candidate_rule": (
                "A deterioration beyond an advisory band is a regression candidate; "
                "preserve all raw runs and repeat a comparable seven-run set."
            ),
            "confirmed_regression_rule": (
                "Repeated outside-band deterioration in the second comparable set is "
                "a confirmed regression."
            ),
            "shared_hosted_ci": (
                "Hosted CI may run deterministic correctness smoke checks but must not "
                "fail on these microbenchmark bands."
            ),
            "not_a_production_slo": True,
            "not_a_cross_machine_claim": True,
        },
    }


def number_text(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(round(value))) if math.isclose(value, round(value)) else f"{value:.2f}"
    return str(value)


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def render_report(document: dict[str, Any], output_json: Path, output_report: Path) -> str:
    identity_data = document["reference_identity"]
    environment = identity_data["environment"]
    host = document["host_observations"]
    source_provenance = document["source_provenance"]
    first_host_run = host["runs"][0]
    lines = [
        "# Phase 0 native-Linux calibration",
        "",
        "- **Status:** PASS",
        f"- **Schema:** {document['schema_version']}",
        f"- **Source commit:** {document['source_commit']}",
        f"- **Independent full-profile runs:** {document['run_count']}",
        f"- **Machine-readable aggregate:** {relative_path(output_json, output_report.parent)}",
        "",
        (
            "> Observational variance evidence only. This is not a production SLO, "
            "a cross-machine claim, or a shared-CI performance gate."
        ),
        "",
        "## Reference environment and provenance",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Published source commit | {markdown_cell(source_provenance['published_commit'])} |",
        f"| Published source Git tree | {markdown_cell(source_provenance['published_tree'])} |",
        f"| Local execution commit | {markdown_cell(source_provenance['execution_commit'])} |",
        f"| Local execution Git tree | {markdown_cell(source_provenance['execution_tree'])} |",
        (
            f"| Published/execution tree identity verified | "
            f"{markdown_cell(source_provenance['tree_identity_verified'])} |"
        ),
        f"| CPU | {markdown_cell(environment['cpu_model'])} |",
        f"| Logical CPUs | {markdown_cell(environment['logical_cpu_count'])} |",
        f"| Memory | {markdown_cell(environment['total_memory_bytes'])} bytes |",
        f"| Kernel | {markdown_cell(environment['kernel'])} |",
        f"| Rust | {markdown_cell(environment['rustc'])} |",
        f"| Cargo | {markdown_cell(environment['cargo'])} |",
        f"| Wasmtime | {markdown_cell(environment['wasmtime_version'])} |",
        (
            f"| Target / build profile | {markdown_cell(environment['rust_target'])} / "
            f"{markdown_cell(environment['build_profile'])} |"
        ),
        f"| Fixture digest | {markdown_cell(identity_data['artifact']['component_digest'])} |",
        f"| Native-Linux reference | {host['native_linux_reference']} |",
        (
            f"| Virtualization | "
            f"{markdown_cell(first_host_run['virtualization'])} |"
        ),
        (
            f"| Allocator observation | "
            f"{markdown_cell(first_host_run['allocator'])} |"
        ),
        (
            f"| CPU frequency/power policy | "
            f"{markdown_cell(first_host_run['cpu_frequency_policy'])} |"
        ),
        f"| One-minute load observed | {markdown_cell(host['one_minute_load_range'])} |",
        (
            f"| Available memory observed | "
            f"{markdown_cell(host['available_memory_bytes_range'])} bytes |"
        ),
        "",
        (
            "Every run directory retains raw full-profile output, its concise report, "
            "and before/after host observations. Those observations record "
            "virtualization detection, allocator observation, frequency/power policy "
            "where Linux exposes it, background-load context, and the verified "
            "published/execution Git-tree provenance."
        ),
        "",
        "## Hard invariant status",
        "",
        (
            f"All {document['run_count']} runs passed every original Phase 0 hard "
            "invariant. No run was excluded for timing, throughput, RSS, or any other "
            "performance value. The aggregate adds no statistical tolerance to "
            "topology, capacity, containment, cleanup, or reclamation checks."
        ),
        "",
        "## Aggregate measurements",
        "",
        (
            "Rows contain all retained underlying samples where available; startup, "
            "throughput, fixed-pool P50, and per-run peak-resource rows contain one "
            "representative observation per process. MAD is median absolute deviation. "
            "CV is sample coefficient of variation."
        ),
        "",
    ]
    metrics = document["metrics"]
    for group in sorted({metric["group"] for metric in metrics.values()}):
        lines.extend(
            [
                f"### {group}",
                "",
                "| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for name, metric in metrics.items():
            if metric["group"] != group:
                continue
            samples = metric["samples"]
            flagged = metric["run_level_outliers"]
            outlier_text = (
                "; ".join(f"{item['run']}={number_text(item['value'])}" for item in flagged)
                if flagged
                else "none"
            )
            cv = samples["coefficient_of_variation_percent"]
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_cell(f"{name} — {metric['label']}"),
                        metric["unit"],
                        number_text(samples["sample_count"]),
                        number_text(metric["run_count"]),
                        number_text(samples["minimum"]),
                        number_text(samples["median"]),
                        number_text(samples["maximum"]),
                        number_text(samples["median_absolute_deviation"]),
                        "n/a" if cv is None else f"{cv:.2f}%",
                        markdown_cell(outlier_text),
                    ]
                )
                + " |"
            )
        lines.append("")
    lines.extend(
        [
            "## Environmental noise and outliers",
            "",
            (
                "Outliers use per-run representative values and a robust z-score above "
                f"{ROBUST_OUTLIER_THRESHOLD:g}, or any deviation from a zero-MAD "
                "run-level median. Flags remain in the aggregate and raw archive; they "
                "prompt investigation or rerun and never permit discarding a run."
            ),
            "",
        ]
    )
    material = document["material_run_level_outliers"]
    if not material:
        lines.extend(["No run-level metric outliers were flagged by this rule.", ""])
    else:
        lines.extend(["| Metric | Flagged runs |", "|---|---|"])
        for name, flagged in material.items():
            items = "; ".join(
                f"{item['run']}={number_text(item['value'])} ({item['reason']})"
                for item in flagged
            )
            lines.append(f"| {name} | {markdown_cell(items)} |")
        lines.append("")
    lines.extend(
        [
            "## Phase 1 advisory comparison bands",
            "",
            (
                "The bands are like-for-like native-Linux regression-detection aids, "
                "not SLOs, release promises, or cross-machine claims. Candidates need "
                "at least seven comparable full-profile processes and all hard "
                "invariants must pass."
            ),
            "",
            "| Metric | Direction | Reference run median | Advisory noise band | Candidate regression rule |",
            "|---|---|---:|---:|---|",
        ]
    )
    for name, metric in metrics.items():
        comparison = metric["comparison"]
        if comparison is None:
            continue
        direction = (
            "higher is worse"
            if comparison["direction"] == "increase_is_regression"
            else "lower is worse"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(f"{name} — {metric['label']}"),
                    direction,
                    number_text(comparison["reference_median"]),
                    number_text(comparison["advisory_noise_band"]),
                    markdown_cell(comparison["candidate_regression_rule"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            (
                "An inside-band candidate with at least seven valid comparable runs, "
                "a stable environment, all hard invariants passing, and no material "
                "run-level outlier is terminally **no detectable regression** (or "
                "statistically indistinguishable). Insufficient samples, environment "
                "instability, material outliers, or a failed invariant are inconclusive "
                "and must be rerun after the invalid condition is resolved. A "
                "deterioration outside a band is a regression candidate that requires "
                "a second comparable set; repeated outside-band deterioration confirms "
                "the regression."
            ),
            "",
            "Shared hosted CI must never fail on these microbenchmark bands; it may run "
            "the deterministic Phase 0 correctness smoke profile only.",
            "",
            "## Raw run archive",
            "",
            "| Run | Raw full-profile output | Per-run report | Host observations | Exit status |",
            "|---|---|---|---|---|",
        ]
    )
    for run in document["raw_runs"]:
        lines.append(
            f"| {run['run']} | {run['raw_results']} | {run['baseline_report']} | "
            f"{run['host_before']}, {run['host_after']} | {run['execution_status']} |"
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- The workload is the Phase 0 spike, not a productionized multi-service or cluster workload.",
            "- CPU frequency and background load are observed where available, not controlled by this command.",
            "- This calibration does not establish dormant-service density, long-duration soak behavior, remote calls, or production capacity.",
            "- Phase 1 must report deltas against this evidence instead of replacing the reference after productionization.",
            "",
        ]
    )
    return "\n".join(lines)


def write_aggregate(output_json: Path, output_report: Path, aggregate: dict[str, Any]) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    output_report.write_text(
        render_report(aggregate, output_json, output_report), encoding="utf-8"
    )


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture and aggregate repeated Phase 0 native-Linux profiles."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture-host", help="record host context for one run")
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--phase", choices=("before", "after"), required=True)
    capture.add_argument("--run-index", type=int, required=True)
    capture.add_argument("--source-commit", required=True)
    capture.add_argument("--source-tree", required=True)
    capture.add_argument("--execution-commit", required=True)
    capture.add_argument("--execution-tree", required=True)
    capture.add_argument("--repository-root", type=Path, required=True)
    aggregate = commands.add_parser("aggregate", help="validate and aggregate runs")
    aggregate.add_argument("--runs-directory", type=Path, required=True)
    aggregate.add_argument("--output-json", type=Path, required=True)
    aggregate.add_argument("--output-report", type=Path, required=True)
    aggregate.add_argument("--source-commit", required=True)
    aggregate.add_argument("--source-tree", required=True)
    aggregate.add_argument("--minimum-runs", type=int, default=MINIMUM_REFERENCE_RUNS)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    parsed = parse_arguments(arguments if arguments is not None else sys.argv[1:])
    try:
        if parsed.command == "capture-host":
            capture_host_observation(
                parsed.output,
                parsed.phase,
                parsed.run_index,
                parsed.source_commit,
                parsed.source_tree,
                parsed.execution_commit,
                parsed.execution_tree,
                parsed.repository_root.resolve(),
            )
            return 0
        if parsed.minimum_runs < MINIMUM_REFERENCE_RUNS:
            fail(
                f"--minimum-runs cannot be lower than {MINIMUM_REFERENCE_RUNS} for "
                "a Phase 0 calibration reference"
            )
        aggregate = build_aggregate(
            parsed.runs_directory.resolve(),
            parsed.source_commit,
            parsed.source_tree,
            parsed.minimum_runs,
        )
        write_aggregate(parsed.output_json, parsed.output_report, aggregate)
        print(
            json.dumps(
                {
                    "schema_version": CALIBRATION_SCHEMA,
                    "status": "pass",
                    "run_count": aggregate["run_count"],
                    "output_json": str(parsed.output_json),
                    "output_report": str(parsed.output_report),
                },
                sort_keys=True,
            )
        )
        return 0
    except CalibrationError as error:
        print(f"Phase 0 calibration failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
