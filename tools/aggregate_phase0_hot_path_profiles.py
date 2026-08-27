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


BASELINE_SCHEMA = "latent.phase0.baseline.v2"
HOST_SCHEMA = "latent.phase0.hot-path.host-observation.v1"
PROFILE_SCHEMA = "latent.phase0.hot-path.aggregate.v1"
MINIMUM_ADOPTION_RUNS = 7

PROFILE_WORKLOADS = (
    "cold-preparation",
    "first-activation",
    "warm-execution",
    "failure-containment",
    "cleanup",
    "contention",
)

CANDIDATE_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "worker-cell-1w-1c": {
        "runtime_workers": 1,
        "pool_capacity": 1,
        "wasmtime_allocator": "on_demand",
        "wasmtime_copy_on_write_images": True,
    },
    "worker-cell-2w-2c": {
        "runtime_workers": 2,
        "pool_capacity": 2,
        "wasmtime_allocator": "on_demand",
        "wasmtime_copy_on_write_images": True,
    },
    "worker-cell-2w-4c": {
        "runtime_workers": 2,
        "pool_capacity": 4,
        "wasmtime_allocator": "on_demand",
        "wasmtime_copy_on_write_images": True,
    },
    "worker-cell-4w-2c": {
        "runtime_workers": 4,
        "pool_capacity": 2,
        "wasmtime_allocator": "on_demand",
        "wasmtime_copy_on_write_images": True,
    },
    "on-demand-cow-disabled": {
        "runtime_workers": 2,
        "pool_capacity": 2,
        "wasmtime_allocator": "on_demand",
        "wasmtime_copy_on_write_images": False,
    },
    "pooling-cow-disabled": {
        "runtime_workers": 2,
        "pool_capacity": 2,
        "wasmtime_allocator": "pooling",
        "wasmtime_copy_on_write_images": False,
    },
    "pooling-cow-enabled": {
        "runtime_workers": 2,
        "pool_capacity": 2,
        "wasmtime_allocator": "pooling",
        "wasmtime_copy_on_write_images": True,
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
        "sha256",
        "serde_json",
        "capsule",
    ),
    "Wasmtime engine and component preparation": (
        "prepare_inner",
        "component::component",
        "wasmtime",
        "cranelift",
    ),
    "store, limiter, host state, instance, and import construction": (
        "instantiate_async",
        "wasmtime::store",
        "hoststate",
        "linker",
    ),
    "activation envelope and metadata handling": (
        "phase0_activation_envelope",
        "activationenvelope",
        "metadata",
        "btreemap",
    ),
    "WIT lifting, lowering, and payload copies": (
        "call_echo",
        "component",
        "memcpy",
        "copy_from_slice",
        "into_bytes",
    ),
    "host context and log calls": (
        "host",
        "context",
        "log",
    ),
    "result mapping and diagnostics": (
        "classify",
        "guestoutcome",
        "platformerror",
        "diagnostic",
    ),
    "resource reclamation and cell disposition": (
        "reclamation",
        "dealloc",
        "drop",
        "madvise",
        "release",
    ),
    "pool/queue coordination and runtime scheduling": (
        "fixedcellpool",
        "acquire",
        "tokio",
        "scheduler",
    ),
}


class HotPathError(Exception):
    """The profile archive is incomplete, malformed, or unsafe to interpret."""


def fail(message: str) -> NoReturn:
    raise HotPathError(message)


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


def capture_host(output: Path, source_commit: str, source_tree: str, repository_root: Path) -> None:
    kernel_text = "\n".join(
        filter(
            None,
            [read_text(Path("/proc/sys/kernel/osrelease")), read_text(Path("/proc/version"))],
        )
    ).lower()
    container = command_output(["systemd-detect-virt", "--container"])
    virtualization = command_output(["systemd-detect-virt"])
    tools = {
        "perf": command_output(["perf", "--version"]),
        "heaptrack": command_output(["heaptrack", "--version"]),
        "heaptrack_print": command_output(["heaptrack_print", "--version"]),
        "python": command_output([sys.executable, "--version"]),
        "rustc": command_output(["rustc", "--version"]),
        "cargo": command_output(["cargo", "--version"]),
    }
    payload = {
        "schema_version": HOST_SCHEMA,
        "captured_at_utc": now_utc(),
        "source_commit": source_commit,
        "source_tree": source_tree,
        "operating_system": platform.system().lower(),
        "architecture": platform.machine(),
        "kernel": command_output(["uname", "-srvmo"]),
        "native_linux_reference": (
            platform.system() == "Linux"
            and "microsoft" not in kernel_text
            and "wsl" not in kernel_text
            and container in ("none", "unavailable")
        ),
        "virtualization": {
            "systemd_detect_virt": virtualization,
            "systemd_detect_virt_container": container,
            "wsl_detected": "microsoft" in kernel_text or "wsl" in kernel_text,
        },
        "machine": {
            "logical_cpu_count": os.cpu_count(),
            "memory": parse_meminfo(),
        },
        "tools": tools,
        "allocator": {
            "ld_preload": "set (value intentionally not recorded)"
            if os.environ.get("LD_PRELOAD")
            else "unset",
            "malloc_conf": "set (value intentionally not recorded)"
            if os.environ.get("MALLOC_CONF")
            else "unset",
            "evidence_tool": "heaptrack (open-source symbolized allocation profiler)",
        },
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


def perf_top_samples(report: str, limit: int = 5) -> list[dict[str, Any]]:
    """Extract the leading sampled symbols from `perf report --stdio`.

    The raw report remains authoritative. This compact index makes it clear
    when a dominant sample comes from required baseline observation overhead
    rather than a production activation-path function.
    """
    samples: list[dict[str, Any]] = []
    for line in report.splitlines():
        fields = re.split(r"\s{2,}", line.strip())
        if len(fields) < 4:
            continue
        percentage = re.fullmatch(r"(\d+(?:\.\d+)?)%", fields[0])
        if percentage is None:
            continue
        samples.append(
            {
                "percent": float(percentage.group(1)),
                "command": fields[1],
                "shared_object": fields[2],
                "symbol": fields[3],
            }
        )
        if len(samples) == limit:
            break
    return samples


def load_profile(
    profiles_directory: Path,
    name: str,
    expected_checks: set[str] | None,
    archive_root: Path,
) -> tuple[dict[str, Any], set[str], dict[str, Any]]:
    root = profiles_directory / name
    perf_root = root / "perf"
    allocation_root = root / "allocation"
    perf_document = load_json(perf_root / "raw-results.json", f"{name} perf baseline")
    expected_checks = verify_baseline(perf_document, f"{name} perf baseline", expected_checks)
    allocation_document = load_json(
        allocation_root / "raw-results.json", f"{name} allocation baseline"
    )
    verify_baseline(allocation_document, f"{name} allocation baseline", expected_checks)

    perf_command = load_json(perf_root / "command.json", f"{name} perf command")
    allocation_command = load_json(
        allocation_root / "command.json", f"{name} allocation command"
    )
    for label, command in (("perf", perf_command), ("allocation", allocation_command)):
        arguments = command.get("command")
        if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
            fail(f"{name} {label} command must retain the exact command array")
        if "phase0-baseline" not in " ".join(arguments):
            fail(f"{name} {label} command did not invoke phase0-baseline")

    perf_report = require_text(perf_root / "perf-report.txt", f"{name} symbolized CPU report")
    allocation_report = require_text(
        allocation_root / "heaptrack-report.txt", f"{name} allocation report"
    )
    allocation_leak_report = require_text(
        allocation_root / "heaptrack-leaks.txt", f"{name} allocation leak report"
    )
    allocation_summary = heaptrack_summary(allocation_report, f"{name} allocation report")
    perf_data = perf_root / "perf.data"
    allocation_data = require_heaptrack_data(allocation_root, f"{name} raw Heaptrack data")
    if not perf_data.is_file():
        fail(f"{name} raw perf data is missing: {perf_data}")
    return (
        {
            "workload": name,
            "metrics": candidate_metrics(perf_document),
            "top_cpu_samples": perf_top_samples(perf_report),
            "perf": {
                "command": perf_command,
                "raw_results": archive_path(perf_root / "raw-results.json", archive_root),
                "raw_results_sha256": sha256_file(perf_root / "raw-results.json"),
                "data": archive_path(perf_data, archive_root),
                "data_sha256": sha256_file(perf_data),
                "report": archive_path(perf_root / "perf-report.txt", archive_root),
                "report_sha256": sha256_file(perf_root / "perf-report.txt"),
                "report_text": perf_report,
            },
            "allocation": {
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
                **allocation_summary,
            },
        },
        expected_checks,
        perf_document,
    )


def validate_candidate_config(name: str, document: dict[str, Any]) -> None:
    expected = CANDIDATE_EXPECTATIONS[name]
    config = document.get("config")
    if not isinstance(config, dict):
        fail(f"candidate {name} has no effective configuration")
    for key, expected_value in expected.items():
        if config.get(key) != expected_value:
            fail(
                f"candidate {name} configuration mismatch for {key}: "
                f"expected {expected_value!r}, observed {config.get(key)!r}"
            )


def load_candidate(
    candidates_directory: Path,
    name: str,
    expected_checks: set[str],
    archive_root: Path,
) -> dict[str, Any]:
    root = candidates_directory / name
    runs = sorted(path for path in root.glob("run-*/raw-results.json") if path.is_file())
    if not runs:
        fail(f"candidate {name} has no retained run documents")
    documents: list[dict[str, Any]] = []
    for path in runs:
        document = load_json(path, f"candidate {name} baseline")
        verify_baseline(document, f"candidate {name} {path.parent.name}", expected_checks)
        validate_candidate_config(name, document)
        documents.append(document)
    metric_samples = [candidate_metrics(document) for document in documents]
    representatives = {
        metric: median(sample.get(metric) for sample in metric_samples)
        for metric in metric_samples[0]
    }
    first = documents[0]
    return {
        "name": name,
        "run_count": len(documents),
        "raw_runs": [
            {
                "path": archive_path(path, archive_root),
                "sha256": sha256_file(path),
                "status": document["status"],
            }
            for path, document in zip(runs, documents, strict=True)
        ],
        "configuration": first["config"],
        "metrics_per_run": metric_samples,
        "representatives": representatives,
        "hard_invariants": "all canonical Phase 0 baseline checks passed in every retained run",
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


def comparison_to_calibration(
    candidate: dict[str, Any], calibration: dict[str, Any]
) -> dict[str, Any]:
    metrics = calibration.get("metrics")
    if not isinstance(metrics, dict):
        fail("calibration aggregate lacks metrics")
    comparisons: dict[str, Any] = {}
    for metric, calibration_metric in METRIC_TO_CALIBRATION.items():
        candidate_value = candidate["representatives"].get(metric)
        reference = metrics.get(calibration_metric)
        if candidate_value is None or not isinstance(reference, dict):
            comparisons[metric] = {"status": "not_available"}
            continue
        comparison = reference.get("comparison")
        if not isinstance(comparison, dict):
            comparisons[metric] = {"status": "not_available"}
            continue
        reference_median = comparison.get("reference_median")
        noise_band = comparison.get("advisory_noise_band")
        if not isinstance(reference_median, (int, float)) or not isinstance(noise_band, (int, float)):
            comparisons[metric] = {"status": "not_available"}
            continue
        direction = reference.get("direction")
        if direction == "increase_is_regression":
            outside = candidate_value > float(reference_median) + float(noise_band)
        elif direction == "decrease_is_regression":
            outside = candidate_value < float(reference_median) - float(noise_band)
        else:
            outside = False
        comparisons[metric] = {
            "status": "outside_advisory_band" if outside else "inside_advisory_band",
            "candidate_median": candidate_value,
            "reference_median": float(reference_median),
            "advisory_noise_band": float(noise_band),
            "direction": direction,
        }
    return comparisons


def attribution(profile_records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    text_by_tool: dict[str, list[str]] = {"perf": [], "heaptrack": []}
    for record in profile_records:
        text_by_tool["perf"].extend(record["perf"]["report_text"].splitlines())
        text_by_tool["heaptrack"].extend(record["allocation"]["report_text"].splitlines())
        text_by_tool["heaptrack"].extend(record["allocation"]["leak_report_text"].splitlines())
    results: dict[str, Any] = {}
    for category, patterns in ATTRIBUTION_RULES.items():
        matches: dict[str, list[str]] = {}
        for tool, lines in text_by_tool.items():
            selected = [
                line.strip()
                for line in lines
                if any(pattern in line.lower() for pattern in patterns)
            ]
            matches[tool] = selected[:12]
        results[category] = {
            "patterns": list(patterns),
            "perf_matches": matches["perf"],
            "allocation_matches": matches["heaptrack"],
            "perf_match_count": len(matches["perf"]),
            "allocation_match_count": len(matches["heaptrack"]),
            "interpretation": (
                "Symbolized reports are retained verbatim; an empty matcher is a review item, "
                "not evidence of zero cost or allocation."
            ),
        }
    return results


def decision_records(candidates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = candidates["worker-cell-2w-2c"]
    run_count = baseline["run_count"]
    no_adoption_reason = (
        f"Only {run_count} matched candidate runs are retained; Phase 0 requires at least "
        f"{MINIMUM_ADOPTION_RUNS} comparable runs before a faster result can justify adoption."
    )
    return [
        {
            "candidate": "fixed 2-worker/2-cell on-demand configuration",
            "decision": "adopt now",
            "scope": "retain existing Phase 0 configuration",
            "rationale": "It preserves the measured fixed topology and fresh-store isolation; this archive introduces no runtime behavior change.",
            "handoff": "#39 runs the final 3x100k resource soak against this configuration.",
        },
        {
            "candidate": "bounded preparation/cache reuse versus cold preparation",
            "decision": "adopt now",
            "scope": "retain existing bounded one-entry prepared-component cache",
            "rationale": "The cache is node-owned, bounded, and stores prepared immutable state only; stores and instances remain fresh per activation.",
            "handoff": "#9 generalizes the cache key, policy, eviction, and multi-component compatibility proof.",
        },
        {
            "candidate": "worker/cell capacity ratios",
            "decision": "carry as configurable Phase 1 experiment",
            "scope": "#8",
            "rationale": f"The matrix measures fixed ratios without selecting a universal winner. {no_adoption_reason}",
            "handoff": "#8 owns configuration, fairness, and fixed multi-class capacity policy.",
        },
        {
            "candidate": "Wasmtime pooling allocator",
            "decision": "defer",
            "scope": "#9",
            "rationale": f"The experiment has an explicit fixed upper bound and no retained linear-memory allowance, but it changes node-fixed mapping and reset behavior. {no_adoption_reason}",
            "handoff": "#9 must provide generalized pooling limits, density evidence, and a reset/isolation proof before any production choice.",
        },
        {
            "candidate": "copy-on-write initialized memory",
            "decision": "carry as configurable Phase 1 experiment",
            "scope": "#9",
            "rationale": f"Linux support is profiled explicitly, but its parallel-memory tradeoff is workload-dependent. {no_adoption_reason}",
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
        "| Workload | CPU profile | Allocation/copy evidence | Prep (us) | Warm P50 (us) | Cleanup P50 (us) | Allocation calls | Process-exit Heaptrack total | Top sampled CPU |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for profile in aggregate["profiles"]:
        metrics = profile["metrics"]
        lines.append(
            "| {workload} | `{perf}` | `{allocation}` | {preparation} | {warm} | {cleanup} | {allocation_calls} | {leaked} | {top_cpu} |".format(
                workload=profile["workload"],
                perf=profile["perf"]["report"],
                allocation=profile["allocation"]["report"],
                preparation=display_number(metrics.get("component_preparation_micros")),
                warm=display_number(metrics.get("warm_echo_p50_micros")),
                cleanup=display_number(metrics.get("post_invocation_cleanup_p50_micros")),
                allocation_calls=display_number(profile["allocation"]["allocation_calls"]),
                leaked=profile["allocation"]["process_exit_leaked_memory"],
                top_cpu=top_cpu_sample(profile),
            )
        )
    lines.extend(
        [
            "",
            "Each profile invokes the real shared Phase 0 composition and retains a passing baseline raw document beside both the symbolized `perf` and `heaptrack` artifacts. Heaptrack allocation-call totals and a dedicated process-exit leak report are mandatory, so an unreadable compressed trace cannot be mistaken for zero allocations. The baseline's hard topology, containment, recovery, cleanup, and reclamation checks are binary prerequisites; profiling never converts them into tolerances.",
            "",
            "## Principal contributors and interpretation",
            "",
            "The retained reports quantify component preparation at {preparation_range} us, warm activation P50 at {warm_range} us, and post-invocation cleanup P50 at {cleanup_range} us across these profile processes. Wasmtime/Cranelift preparation, store/instance construction, WIT lifting/copies, host/context work, result mapping, reclamation, and pool/runtime scheduling are indexed in the aggregate attribution map with the matching raw symbol lines.".format(
                preparation_range=profile_metric_range(
                    aggregate["profiles"], "component_preparation_micros"
                ),
                warm_range=profile_metric_range(aggregate["profiles"], "warm_echo_p50_micros"),
                cleanup_range=profile_metric_range(
                    aggregate["profiles"], "post_invocation_cleanup_p50_micros"),
            ),
            "",
            "The top sampled CPU entry is shown for each workload so benchmark-observer cost is explicit. Full Phase 0 proof intentionally scans Linux process resources (including socket state); those samples can dominate a long warm process and are not silently reclassified as production activation cost. They remain in the profile because the hard resource/topology proof remains mandatory, and no optimization decision is based on removing that proof.",
            "",
            "## Experiment matrix",
            "",
            "| Candidate | Runs | Preparation median (us) | Warm P50 (us) | Peak RSS (bytes) | Result |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for candidate in aggregate["candidates"].values():
        metrics = candidate["representatives"]
        comparisons = candidate["calibration_comparison"]
        statuses = sorted(
            value.get("status", "not_available")
            for value in comparisons.values()
            if isinstance(value, dict)
        )
        lines.append(
            "| {name} | {runs} | {prep} | {warm} | {rss} | {status} |".format(
                name=candidate["name"],
                runs=candidate["run_count"],
                prep=display_number(metrics.get("component_preparation_micros")),
                warm=display_number(metrics.get("warm_echo_p50_micros")),
                rss=display_number(metrics.get("peak_rss_bytes")),
                status=", ".join(statuses) or "not_available",
            )
        )
    lines.extend(
        [
            "",
            f"No new runtime optimization is adopted from this matrix unless it has at least {MINIMUM_ADOPTION_RUNS} comparable runs, passes every hard invariant, stays within documented fixed/peak-memory costs, and clears the #38 calibrated noise envelope. This archive does not meet the run-count threshold for adoption, so it records decisions without promoting a faster single or small-set result.",
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
            "## Attribution map",
            "",
            "The machine-readable aggregate records matching symbol lines from both tools for capsule/digest validation, Wasmtime preparation, store/instance construction, envelope/metadata work, WIT lifting/lowering/copies, host calls, result mapping, reclamation, and pool/runtime coordination. An empty automatic match is explicitly a review item, not an assertion of zero cost.",
            "",
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
    if host.get("schema_version") != HOST_SCHEMA:
        fail("hot-path host observation schema is not recognized")
    if host.get("native_linux_reference") is not True:
        fail("hot-path profiles are not from a supported native-Linux host")
    if host.get("source_commit") != arguments.source_commit or host.get("source_tree") != arguments.source_tree:
        fail("host observation source identity does not match aggregate arguments")

    calibration = load_json(arguments.calibration_aggregate, "Phase 0 calibration aggregate")
    if calibration.get("status") != "pass":
        fail("Phase 0 calibration aggregate is not passing")

    expected_checks: set[str] | None = None
    profiles: list[dict[str, Any]] = []
    for name in PROFILE_WORKLOADS:
        record, expected_checks, _ = load_profile(
            profiles_directory, name, expected_checks, archive_root
        )
        profiles.append(record)
    assert expected_checks is not None

    candidates: dict[str, dict[str, Any]] = {}
    for name in CANDIDATE_EXPECTATIONS:
        candidate = load_candidate(candidates_directory, name, expected_checks, archive_root)
        candidate["calibration_comparison"] = comparison_to_calibration(candidate, calibration)
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
        "host_observation": {
            "path": archive_path(arguments.host_observation, archive_root),
            "sha256": sha256_file(arguments.host_observation),
        },
        "calibration_reference": {
            "path": archive_path(arguments.calibration_aggregate, archive_root),
            "sha256": sha256_file(arguments.calibration_aggregate),
            "adoption_rule": (
                f"No candidate is eligible for Phase 0 adoption with fewer than {MINIMUM_ADOPTION_RUNS} "
                "comparable runs, regardless of a faster median."
            ),
        },
        "hard_invariants": {
            "canonical_names": sorted(expected_checks),
            "rule": "Every profiled and matrix baseline has this exact set once and every check passed.",
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
    capture.add_argument("--repository-root", type=Path, required=True)
    summary = subcommands.add_parser("aggregate", help="validate and summarize one profile archive")
    summary.add_argument("--profiles-directory", type=Path, required=True)
    summary.add_argument("--candidates-directory", type=Path, required=True)
    summary.add_argument("--host-observation", type=Path, required=True)
    summary.add_argument("--calibration-aggregate", type=Path, required=True)
    summary.add_argument("--source-commit", required=True)
    summary.add_argument("--source-tree", required=True)
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
                arguments.repository_root.resolve(),
            )
        else:
            aggregate(arguments)
    except HotPathError as error:
        print(f"hot-path profile validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
