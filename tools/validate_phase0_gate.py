#!/usr/bin/env python3
"""Validate Phase 0 completion evidence and emit a fail-closed receipt.

Authorization is intentionally stronger than a check of aggregate status
fields. The verifier rebuilds each retained aggregate from raw evidence,
validates archive integrity, and binds every evidence set to the current
execution-relevant Git tree before it can authorize Phase 1.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any

try:  # Support both ``python tools/...`` and package-style unit-test imports.
    from .phase0_evidence import (
        CALIBRATION_SCHEMA,
        EvidenceValidationError,
        PROFILE_SCHEMA,
        SOAK_SCHEMA,
        current_execution_evidence_identity,
        execution_evidence_identity,
        verify_calibration_evidence,
        verify_profile_evidence,
        verify_resource_soak_evidence,
    )
except ImportError:  # pragma: no cover - exercised by the command-line entrypoint.
    from phase0_evidence import (
        CALIBRATION_SCHEMA,
        EvidenceValidationError,
        PROFILE_SCHEMA,
        SOAK_SCHEMA,
        current_execution_evidence_identity,
        execution_evidence_identity,
        verify_calibration_evidence,
        verify_profile_evidence,
        verify_resource_soak_evidence,
    )


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_SCHEMA = "latent.phase0.baseline.v2"
GATE_SCHEMA = "latent.phase0.gate.v3"
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

DEFAULT_CALIBRATION = (
    REPOSITORY_ROOT
    / "benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/aggregate.json"
)
DEFAULT_PROFILING = (
    REPOSITORY_ROOT
    / "benchmarks/phase0/profiling/native-linux-2026-08-27-de2337906/aggregate.json"
)
DEFAULT_SOAK = (
    REPOSITORY_ROOT
    / "benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/aggregate.json"
)

REQUIRED_CHECKS = frozenset(
    {
        "real_issue23_executable_probe_passed",
        "real_issue23_executable_failure_and_recovery_probe_passed",
        "linux_process_resource_probe_supported",
        "configured_runtime_workers_observed_before_and_after_loading",
        "prepared_cache_bounded_after_prepare",
        "fixed_pool_queue_saturation_is_bounded",
        "fixed_pool_returns_to_configured_idle_state",
        "real_activation_throughput_reaches_pool_capacity",
        "real_activation_throughput_reaches_bounded_queue_saturation",
        "activation_owned_state_returns_to_baseline_after_every_sample",
        "all_scenarios_return_expected_terminal_outcomes",
        "failure_does_not_degrade_the_next_cause_specific_echo",
        "timeout_and_cancellation_overshoot_are_bounded",
        "topology_constant_across_component_loading_and_repeated_invocations",
        "rss_has_no_unbounded_monotonic_growth",
        "file_descriptors_have_no_unbounded_monotonic_growth",
        "explicit_release_clears_prepared_cache",
        "post_release_backend_and_pool_are_clean",
        "runtime_shutdown_returns_thread_count_to_process_baseline",
    }
)
REQUIRED_TERMINAL_OUTCOMES = frozenset(
    {"success", "domain_error", "trap", "timeout", "cancelled", "resource_exhausted"}
)
REQUIRED_SCENARIO_OUTCOMES = frozenset(
    {
        ("domain_error", "domain_error"),
        ("trap", "trap"),
        ("timeout", "timeout"),
        ("cancellation", "cancelled"),
        ("memory_pressure", "resource_exhausted"),
        ("recovery_after_domain_error", "success"),
        ("recovery_after_trap", "success"),
        ("recovery_after_timeout", "success"),
        ("recovery_after_cancellation", "success"),
        ("recovery_after_memory_pressure", "success"),
        ("throughput_at_capacity", "success"),
        ("throughput_bounded_queue_saturation", "success"),
    }
)
REQUIRED_PROFILE_WORKLOADS = frozenset(
    {
        "cold-preparation",
        "prepared-cache-reuse",
        "first-activation",
        "warm-execution",
        "failure-containment",
        "cleanup",
        "at-capacity-contention",
        "queued-contention",
    }
)
REQUIRED_PROFILE_GUARDRAILS = {
    "bounded_node_owned_state": True,
    "cleanup_proof_before_cell_reuse": True,
    "fixed_node_topology": True,
    "fresh_store_per_invocation": True,
    "native_execution": False,
    "persistent_aot_or_compiler_cache": False,
    "store_or_instance_reuse": False,
}
REQUIRED_DECISION_CANDIDATES = frozenset(
    {
        "fixed 2-worker/2-cell on-demand configuration",
        "bounded preparation/cache reuse versus cold preparation",
        "worker/cell capacity ratios",
        "Wasmtime pooling allocator",
        "copy-on-write initialized memory",
        "avoidable activation-path allocations and payload copies",
        "store/instance reuse, persistent AOT artifacts, compiler caches, snapshots, and native execution",
    }
)
PERMITTED_PROFILE_DECISIONS = frozenset(
    {
        "retain existing default; no new adoption",
        "retain existing setting; no new adoption",
        "carry as configurable Phase 1 experiment",
        "defer",
        "reject",
    }
)
REQUIRED_TOOLCHAIN_FIELDS = (
    "rustc",
    "cargo",
    "rust_target",
    "build_profile",
    "wasmtime_version",
)


class GateValidationError(ValueError):
    """Raised when a Phase 0 gate input cannot be safely validated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateValidationError(message)


def _mapping(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    _require(isinstance(value, list), f"{label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    _require(isinstance(value, str) and value, f"{label} must be a non-empty string")
    return value


def _positive_int(value: Any, label: str) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value > 0,
        f"{label} must be a positive integer",
    )
    return value


def _number(value: Any, label: str) -> float:
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        f"{label} must be numeric",
    )
    return float(value)


def _exact_names(names: list[str], expected: frozenset[str], label: str) -> None:
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    actual = set(names)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    _require(
        not missing and not unexpected and not duplicates,
        f"{label} mismatch missing={missing} unexpected={unexpected} duplicates={duplicates}",
    )


def _load_document(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise GateValidationError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise GateValidationError(f"cannot parse JSON in {path}: {error}") from error
    return _mapping(payload, str(path))


def _require_non_production(document: dict[str, Any], label: str) -> None:
    _require(document.get("observational_only") is True, f"{label} must remain observational")
    _require(document.get("production_slo") is False, f"{label} must not claim a production SLO")


def _valid_digest(value: Any, label: str) -> str:
    digest = _string(value, label)
    _require(SHA256_PATTERN.fullmatch(digest) is not None, f"{label} must be a SHA-256 digest")
    return digest


def validate_baseline(
    document: dict[str, Any], baseline_path: str, current_identity: dict[str, Any]
) -> dict[str, Any]:
    """Validate the newly executed full or smoke baseline, including provenance."""

    _require(document.get("schema_version") == BASELINE_SCHEMA, "unexpected Phase 0 baseline schema")
    _require(document.get("status") == "pass", "Phase 0 baseline did not pass")
    _require(document.get("observational_only") is True, "baseline must remain observational")
    _require(document.get("production_ready") is False, "baseline must remain explicitly non-production")
    _require(
        document.get("phase1_api_compatible") is False,
        "baseline must remain explicitly non-Phase-1-compatible",
    )

    checks = _list(document.get("checks"), "baseline checks")
    check_names: list[str] = []
    for check in checks:
        check_document = _mapping(check, "baseline check")
        check_names.append(_string(check_document.get("name"), "baseline check name"))
        _require(check_document.get("passed") is True, f"baseline check {check_names[-1]!r} did not pass")
    _exact_names(check_names, REQUIRED_CHECKS, "baseline hard checks")

    activation_samples = _list(document.get("activation_samples"), "activation samples")
    scenario_outcomes: set[tuple[str, str]] = set()
    terminal_outcomes: set[str] = set()
    for sample in activation_samples:
        sample_document = _mapping(sample, "activation sample")
        scenario = _string(sample_document.get("scenario"), "activation sample scenario")
        outcome = _mapping(sample_document.get("outcome"), "activation sample outcome")
        outcome_name = _string(outcome.get("name"), "activation terminal outcome")
        scenario_outcomes.add((scenario, outcome_name))
        terminal_outcomes.add(outcome_name)
    missing_scenarios = sorted(REQUIRED_SCENARIO_OUTCOMES - scenario_outcomes)
    missing_outcomes = sorted(REQUIRED_TERMINAL_OUTCOMES - terminal_outcomes)
    _require(
        not missing_scenarios and not missing_outcomes,
        f"baseline scenarios missing={missing_scenarios} terminal_outcomes_missing={missing_outcomes}",
    )

    harness = _mapping(document.get("executable_harness"), "executable harness")
    success_samples = _list(harness.get("samples"), "executable success samples")
    _require(len(success_samples) >= 3, "executable harness must retain at least three cold success samples")
    for sample in success_samples:
        sample_document = _mapping(sample, "executable success sample")
        _require(sample_document.get("shutdown_clean") is True, "executable success sample did not shut down cleanly")
        _require(sample_document.get("topology_unchanged") is True, "executable success sample changed topology")

    failure_samples = _list(harness.get("failure_recovery_samples"), "executable failure/recovery samples")
    failures_by_scenario: dict[str, dict[str, Any]] = {}
    for sample in failure_samples:
        sample_document = _mapping(sample, "executable failure/recovery sample")
        scenario = _string(sample_document.get("scenario"), "executable failure/recovery scenario")
        _require(scenario not in failures_by_scenario, f"duplicate executable failure/recovery scenario: {scenario}")
        failures_by_scenario[scenario] = sample_document
    _exact_names(
        list(failures_by_scenario),
        frozenset({"trap", "timeout", "trap_then_recovery"}),
        "executable failure/recovery scenarios",
    )
    for scenario, expected_outcome in (("trap", "trap"), ("timeout", "timeout"), ("trap_then_recovery", "success")):
        sample = failures_by_scenario[scenario]
        _require(sample.get("expected_outcome") == expected_outcome, f"executable {scenario} outcome is incorrect")
        raw_result = _mapping(sample.get("raw_result"), f"executable {scenario} raw result")
        _require(raw_result.get("outcome") == expected_outcome, f"executable {scenario} raw result outcome is incorrect")
        shutdown = _mapping(raw_result.get("shutdown"), f"executable {scenario} shutdown")
        topology = _mapping(raw_result.get("topology"), f"executable {scenario} topology")
        _require(shutdown.get("clean") is True, f"executable {scenario} did not shut down cleanly")
        _require(topology.get("unchanged") is True, f"executable {scenario} changed topology")

    artifact = _mapping(document.get("artifact"), "baseline artifact")
    component_digest = _valid_digest(artifact.get("component_digest"), "baseline component digest")
    component_bytes = _positive_int(artifact.get("component_bytes"), "baseline component bytes")
    config = _mapping(document.get("config"), "baseline configuration")
    pool_capacity = _positive_int(config.get("pool_capacity"), "baseline pool capacity")
    queue_capacity = _positive_int(config.get("pool_queue_capacity"), "baseline queue capacity")
    _positive_int(config.get("runtime_workers"), "baseline runtime worker count")
    _require(config.get("prepared_cache_enabled") is True, "baseline must retain prepared-cache enablement")
    _require(config.get("wasmtime_allocator") == "on_demand", "baseline must retain on-demand Wasmtime allocation")
    _require(config.get("wasmtime_copy_on_write_images") is True, "baseline must retain initialized-memory COW")

    environment = _mapping(document.get("environment"), "baseline environment")
    _require(
        environment.get("repository_commit") == current_identity["commit"],
        "fresh baseline source commit does not match the current executable implementation",
    )
    for field in REQUIRED_TOOLCHAIN_FIELDS:
        _string(environment.get(field), f"baseline environment {field}")

    throughput = _mapping(document.get("activation_throughput"), "activation throughput")
    at_capacity = _mapping(throughput.get("at_capacity"), "at-capacity throughput")
    saturated = _mapping(throughput.get("bounded_queue_saturation"), "bounded-queue throughput")
    _require(
        at_capacity.get("maximum_observed_active_leases") == pool_capacity
        and at_capacity.get("maximum_observed_queue_depth") == 0,
        "at-capacity activation workload did not prove the configured pool state",
    )
    _require(
        saturated.get("maximum_observed_active_leases") == pool_capacity
        and saturated.get("maximum_observed_queue_depth") == queue_capacity
        and _mapping(saturated.get("queued_acquire_wait_micros"), "queued acquire wait distribution").get("samples", 0) > 0,
        "bounded-queue activation workload did not prove the configured queue state",
    )

    return {
        "status": "pass",
        "schema_version": BASELINE_SCHEMA,
        "baseline_path": baseline_path,
        "profile": config.get("mode"),
        "required_checks_passed": len(REQUIRED_CHECKS),
        "observed_terminal_outcomes": sorted(REQUIRED_TERMINAL_OUTCOMES),
        "executable_e2e": "passed",
        "source_commit": environment["repository_commit"],
        "source_tree": current_identity["tree"],
        "fixture": {"component_digest": component_digest, "component_bytes": component_bytes},
        "configuration": {
            "pool_capacity": pool_capacity,
            "pool_queue_capacity": queue_capacity,
            "runtime_workers": config["runtime_workers"],
            "prepared_cache_enabled": True,
            "wasmtime_instance_allocator": "on_demand",
            "wasmtime_copy_on_write_images": True,
        },
        "toolchain": {field: environment[field] for field in REQUIRED_TOOLCHAIN_FIELDS},
        "production_ready": False,
        "phase1_api_compatible": False,
    }


def validate_calibration(document: dict[str, Any], calibration_path: str) -> dict[str, Any]:
    """Check the raw-regenerated native-Linux calibration conclusions."""

    _require(document.get("schema_version") == CALIBRATION_SCHEMA, "unexpected calibration schema")
    _require(document.get("status") == "pass", "native-Linux calibration did not pass")
    _require_non_production(document, "native-Linux calibration")
    _require(document.get("cross_machine_claim") is False, "calibration must not make a cross-machine claim")
    minimum_runs = _positive_int(document.get("minimum_required_run_count"), "calibration minimum run count")
    run_count = _positive_int(document.get("run_count"), "calibration run count")
    _require(minimum_runs >= 7 and run_count >= minimum_runs, "calibration must retain at least seven runs")

    raw_runs = _list(document.get("raw_runs"), "calibration raw runs")
    _require(len(raw_runs) == run_count, "calibration raw run count does not match the aggregate")
    run_names: list[str] = []
    for run in raw_runs:
        run_document = _mapping(run, "calibration raw run")
        run_names.append(_string(run_document.get("run"), "calibration run name"))
        _require(run_document.get("status") == "pass", f"calibration run {run_names[-1]!r} did not pass")
        for field in ("raw_results", "baseline_report", "host_before", "host_after", "execution_status"):
            _string(run_document.get(field), f"calibration {run_names[-1]} {field}")
    _require(len(run_names) == len(set(run_names)), "calibration has duplicate raw run names")

    hard_invariants = _mapping(document.get("hard_invariants"), "calibration hard invariants")
    _require(hard_invariants.get("all_runs_passed") is True, "calibration hard invariants did not all pass")
    _require(hard_invariants.get("performance_runs_excluded") == 0, "calibration excluded a performance run")
    check_names = [_string(name, "calibration hard-invariant name") for name in _list(hard_invariants.get("checks_passed_in_every_run"), "calibration hard-invariant names")]
    _exact_names(check_names, REQUIRED_CHECKS, "calibration hard-invariant names")

    comparison_method = _mapping(document.get("comparison_method"), "calibration comparison method")
    for field in (
        "applicability",
        "hard_invariant_rule",
        "no_detectable_regression_rule",
        "inconclusive_rule",
        "regression_candidate_rule",
        "confirmed_regression_rule",
        "shared_hosted_ci",
    ):
        _string(comparison_method.get(field), f"calibration comparison method {field}")
    _require(comparison_method.get("not_a_production_slo") is True, "calibration comparison must remain non-SLO")
    _require(comparison_method.get("not_a_cross_machine_claim") is True, "calibration comparison must remain single-host")

    host_observations = _mapping(document.get("host_observations"), "calibration host observations")
    _require(host_observations.get("native_linux_reference") is True, "calibration was not retained from native Linux")
    hosts = _list(host_observations.get("runs"), "calibration host observations")
    _require(len(hosts) == run_count, "calibration host observation count does not match run count")
    for host in hosts:
        host_record = _mapping(host, "calibration host observation")
        _string(host_record.get("run"), "calibration host observation run")
        _string(host_record.get("before"), "calibration host before path")
        _string(host_record.get("after"), "calibration host after path")
        _mapping(host_record.get("virtualization"), "calibration virtualization observation")
        _mapping(host_record.get("allocator"), "calibration allocator observation")

    reference_identity = _mapping(document.get("reference_identity"), "calibration reference identity")
    artifact = _mapping(reference_identity.get("artifact"), "calibration reference artifact")
    _valid_digest(artifact.get("component_digest"), "calibration component digest")
    _positive_int(artifact.get("component_bytes"), "calibration component bytes")
    _mapping(reference_identity.get("config"), "calibration reference configuration")
    environment = _mapping(reference_identity.get("environment"), "calibration reference environment")
    for field in REQUIRED_TOOLCHAIN_FIELDS:
        _string(environment.get(field), f"calibration environment {field}")

    metrics = _mapping(document.get("metrics"), "calibration metrics")
    _require(metrics, "calibration has no measured metrics")
    for name, metric in metrics.items():
        metric_document = _mapping(metric, f"calibration metric {name}")
        _string(metric_document.get("unit"), f"calibration metric {name} unit")
        _require(metric_document.get("run_count") == run_count, f"calibration metric {name} run count is invalid")
        samples = _mapping(metric_document.get("samples"), f"calibration metric {name} samples")
        representatives = _mapping(metric_document.get("run_representatives"), f"calibration metric {name} dispersion")
        _positive_int(samples.get("sample_count"), f"calibration metric {name} sample count")
        _positive_int(representatives.get("sample_count"), f"calibration metric {name} representative count")
        comparison_value = metric_document.get("comparison")
        if comparison_value is None:
            _require(
                name in {
                    "process_peak_file_descriptor_count",
                    "process_peak_listening_socket_count",
                    "process_peak_open_socket_count",
                    "process_peak_thread_count",
                },
                f"calibration metric {name} lacks a comparison rule",
            )
            continue
        comparison = _mapping(comparison_value, f"calibration metric {name} comparison")
        _number(comparison.get("reference_median"), f"calibration metric {name} reference median")
        _number(comparison.get("advisory_noise_band"), f"calibration metric {name} advisory noise band")
        _require(comparison.get("direction") in {"increase_is_regression", "decrease_is_regression"}, f"calibration metric {name} comparison direction is invalid")

    provenance = _mapping(document.get("source_provenance"), "calibration source provenance")
    _require(provenance.get("tree_identity_verified") is True, "calibration source tree was not verified")
    return {
        "status": "pass",
        "schema_version": CALIBRATION_SCHEMA,
        "path": calibration_path,
        "run_count": run_count,
        "metric_count": len(metrics),
        "source_commit": _string(document.get("source_commit"), "calibration source commit"),
        "source_tree": _string(document.get("source_tree"), "calibration source tree"),
        "reference_identity": reference_identity,
    }


def validate_profiling(document: dict[str, Any], profiling_path: str) -> dict[str, Any]:
    """Check raw-regenerated CPU/allocation artifacts and decision records."""

    _require(document.get("schema_version") == PROFILE_SCHEMA, "unexpected hot-path profile schema")
    _require(document.get("status") == "pass", "hot-path profiling aggregate did not pass")
    _require_non_production(document, "hot-path profiling aggregate")
    _require(document.get("cross_platform_claim") is False, "profiling must not make a cross-platform claim")
    guardrails = _mapping(document.get("guardrails"), "profiling guardrails")
    for guardrail, expected_value in REQUIRED_PROFILE_GUARDRAILS.items():
        _require(guardrails.get(guardrail) is expected_value, f"profiling guardrail {guardrail!r} is not preserved")

    profiles = _list(document.get("profiles"), "profile workloads")
    workload_names: list[str] = []
    for profile in profiles:
        record = _mapping(profile, "profile workload")
        workload = _string(record.get("workload"), "profile workload name")
        workload_names.append(workload)
        _string(record.get("scenario_semantics"), f"profile {workload} scenario semantics")
        _list(record.get("selected_scenarios"), f"profile {workload} selected scenarios")
        perf = _mapping(record.get("perf"), f"profile {workload} CPU artifact")
        allocation = _mapping(record.get("allocation"), f"profile {workload} allocation artifact")
        for artifact, fields in ((perf, ("data", "report", "inclusive_report")), (allocation, ("data", "report", "leak_report", "compact_contributors"))):
            for field in fields:
                _string(artifact.get(field), f"profile {workload} artifact {field}")
                _valid_digest(artifact.get(f"{field}_sha256"), f"profile {workload} artifact {field} checksum")
        contributors = _mapping(record.get("contributor_attribution"), f"profile {workload} contributor attribution")
        categories = _mapping(contributors.get("categories"), f"profile {workload} contributor categories")
        _require(categories, f"profile {workload} has no quantified contributors")
        for category, values in categories.items():
            category_values = _mapping(values, f"profile {workload} contributor {category}")
            _number(category_values.get("allocation_calls"), f"profile {workload} contributor {category} allocation calls")
            _number(category_values.get("allocation_peak_bytes"), f"profile {workload} contributor {category} allocation peak")
            _number(category_values.get("cpu_self_percent"), f"profile {workload} contributor {category} CPU self")
            _number(category_values.get("cpu_inclusive_percent"), f"profile {workload} contributor {category} CPU inclusive")
        totals = _mapping(contributors.get("totals"), f"profile {workload} contributor totals")
        _number(totals.get("allocation_calls"), f"profile {workload} total allocation calls")
        _number(totals.get("allocation_peak_bytes"), f"profile {workload} total allocation peak")
    _exact_names(workload_names, REQUIRED_PROFILE_WORKLOADS, "profile workload names")

    hard_invariants = _mapping(document.get("hard_invariants"), "profiling hard invariants")
    canonical_names = [_string(name, "profiling hard-invariant name") for name in _list(hard_invariants.get("canonical_names"), "profiling hard-invariant names")]
    _require(len(canonical_names) == len(set(canonical_names)), "profiling hard-invariant names contain duplicates")
    _require(REQUIRED_CHECKS <= set(canonical_names), "profiling full-invariant proof omits a Phase 0 hard invariant")
    full_proof = _mapping(hard_invariants.get("full_invariant_proof"), "profiling full-invariant proof")
    _string(full_proof.get("raw_results"), "profiling full-invariant raw results path")
    _valid_digest(full_proof.get("raw_results_sha256"), "profiling full-invariant raw results checksum")
    _string(full_proof.get("command"), "profiling full-invariant command path")
    _valid_digest(full_proof.get("command_sha256"), "profiling full-invariant command checksum")

    candidates = _mapping(document.get("candidates"), "profiling candidates")
    _require(candidates, "profiling has no candidate measurements")
    for name, candidate in candidates.items():
        candidate_document = _mapping(candidate, f"profiling candidate {name}")
        _positive_int(candidate_document.get("run_count"), f"profiling candidate {name} run count")
        metrics = _mapping(candidate_document.get("representatives"), f"profiling candidate {name} representatives")
        for metric in (
            "warm_echo_p50_micros",
            "at_capacity_activations_per_second",
            "fixed_runtime_rss_bytes",
            "peak_rss_bytes",
            "post_release_rss_delta_bytes",
            "peak_threads",
            "peak_open_sockets",
            "peak_listening_sockets",
        ):
            _number(metrics.get(metric), f"profiling candidate {name} {metric}")

    decisions = _list(document.get("decisions"), "optimization decisions")
    decision_candidates: list[str] = []
    for decision in decisions:
        decision_document = _mapping(decision, "optimization decision")
        decision_candidates.append(_string(decision_document.get("candidate"), "optimization decision candidate"))
        classification = _string(decision_document.get("decision"), "optimization decision classification")
        _require(classification in PERMITTED_PROFILE_DECISIONS, f"profiling decision {classification!r} is not permitted")
        _string(decision_document.get("rationale"), "optimization decision rationale")
        _string(decision_document.get("handoff"), "optimization decision handoff")
    _exact_names(decision_candidates, REQUIRED_DECISION_CANDIDATES, "optimization decision candidates")

    return {
        "status": "pass",
        "schema_version": PROFILE_SCHEMA,
        "path": profiling_path,
        "workloads": sorted(workload_names),
        "decisions": len(decision_candidates),
        "candidate_count": len(candidates),
        "source_commit": _string(document.get("source_commit"), "profiling source commit"),
        "source_tree": _string(document.get("source_tree"), "profiling source tree"),
    }


def validate_resource_soak(document: dict[str, Any], soak_path: str) -> tuple[dict[str, Any], list[str]]:
    """Check raw-regenerated soak evidence and return non-structural blockers."""

    _require(document.get("schema_version") == SOAK_SCHEMA, "unexpected resource-soak schema")
    _require_non_production(document, "resource-soak aggregate")
    _require(document.get("cross_machine_claim") is False, "resource soak must not make a cross-machine claim")
    minimum_runs = _positive_int(document.get("minimum_required_run_count"), "resource-soak minimum run count")
    run_count = _positive_int(document.get("run_count"), "resource-soak run count")
    _require(minimum_runs >= 3 and run_count >= minimum_runs, "resource soak must retain at least three processes")
    hard_invariants = _mapping(document.get("hard_invariants"), "resource-soak hard invariants")
    _require(hard_invariants.get("all_runs_passed") is True, "resource-soak hard invariants did not all pass")
    canonical_checks = [_string(name, "resource-soak hard-invariant name") for name in _list(hard_invariants.get("canonical_check_names"), "resource-soak hard-invariant names")]
    _require(canonical_checks, "resource-soak has no hard-invariant names")
    _require(len(canonical_checks) == len(set(canonical_checks)), "resource-soak hard-invariant names contain duplicates")

    raw_runs = _list(document.get("raw_runs"), "resource-soak raw runs")
    _require(len(raw_runs) == run_count, "resource-soak raw run count does not match the aggregate")
    labels: list[str] = []
    for run in raw_runs:
        record = _mapping(run, "resource-soak raw run")
        labels.append(_string(record.get("label"), "resource-soak run label"))
        _require(record.get("schema_version") == "latent.phase0.resource-soak.run.v1", "unexpected resource-soak raw-run schema")
        source_identity = _mapping(record.get("source_identity"), "resource-soak source identity")
        _require(source_identity.get("tree_identity_verified") is True, "resource-soak source tree was not verified")
        _string(record.get("raw_json"), f"resource-soak {labels[-1]} raw JSON path")
        _valid_digest(record.get("sha256"), f"resource-soak {labels[-1]} raw JSON checksum")
    _require(len(labels) == len(set(labels)), "resource soak has duplicate raw run labels")

    workload = _mapping(document.get("workload"), "resource-soak workload")
    _require(set(workload) == set(labels), "resource-soak workload entries do not match raw runs")
    for label in labels:
        run_workload = _mapping(workload[label], f"resource-soak workload {label}")
        _require(run_workload.get("warmup_activations") >= 1_000, f"resource-soak {label} has fewer than 1,000 warm-ups")
        _require(run_workload.get("normal_measured_activations") >= 100_000, f"resource-soak {label} has fewer than 100,000 measured activations")
        saturation = _mapping(run_workload.get("saturation_batch_counts"), f"resource-soak {label} saturation coverage")
        _require(saturation.get("at_capacity", 0) >= 100 and saturation.get("bounded_queue_saturation", 0) >= 100, f"resource-soak {label} has incomplete saturation coverage")

    configuration = _mapping(document.get("configuration_identity"), "resource-soak configuration identity")
    artifact = (
        _mapping(configuration.get("artifact"), "resource-soak artifact")
        if isinstance(configuration.get("artifact"), dict)
        else configuration
    )
    _valid_digest(artifact.get("component_digest"), "resource-soak component digest")
    _positive_int(artifact.get("component_bytes"), "resource-soak component bytes")
    config = _mapping(configuration.get("config"), "resource-soak configuration")
    for field in ("pool_capacity", "pool_queue_capacity", "runtime_workers"):
        _positive_int(config.get(field), f"resource-soak {field}")
    _require(config.get("prepared_cache_enabled") is True, "resource-soak must retain prepared cache")
    _require(config.get("wasmtime_instance_allocator") == "on_demand", "resource-soak must retain on-demand allocator")
    _require(config.get("wasmtime_copy_on_write_images") is True, "resource-soak must retain initialized-memory COW")
    environment = _mapping(configuration.get("environment"), "resource-soak environment")
    for field in REQUIRED_TOOLCHAIN_FIELDS:
        _string(environment.get(field), f"resource-soak environment {field}")

    evidence_completeness = _mapping(document.get("evidence_completeness"), "resource-soak evidence completeness")
    calibration_noise = _mapping(document.get("calibration_noise"), "resource-soak calibration evidence")
    calibration_applicability = _mapping(calibration_noise.get("applicability"), "resource-soak calibration applicability")
    file_descriptors = _mapping(document.get("file_descriptors"), "resource-soak file-descriptor evidence")
    blockers: list[str] = []
    if document.get("status") != "pass":
        blockers.append(f"resource-soak aggregate status is {document.get('status')!r}")
    if evidence_completeness.get("status") != "complete":
        blockers.append(f"resource-soak evidence completeness is {evidence_completeness.get('status')!r}")
    if calibration_applicability.get("status") != "matched":
        blockers.append(f"resource-soak calibration applicability is {calibration_applicability.get('status')!r}")
    if file_descriptors.get("status") != "pass":
        blockers.append(f"resource-soak file-descriptor lifecycle evidence is {file_descriptors.get('status')!r}")
    receipt_configuration = dict(configuration)
    receipt_configuration["artifact"] = {
        "component_digest": artifact["component_digest"],
        "component_bytes": artifact["component_bytes"],
    }
    return (
        {
            "status": document.get("status"),
            "schema_version": SOAK_SCHEMA,
            "path": soak_path,
            "run_count": run_count,
            "calibration_applicability": calibration_applicability.get("status"),
            "evidence_completeness": evidence_completeness.get("status"),
            "descriptor_lifecycle": file_descriptors.get("status"),
            "source_commit": _string(document.get("source_commit"), "resource-soak source commit"),
            "source_tree": _string(document.get("source_tree"), "resource-soak source tree"),
            "configuration": receipt_configuration,
        },
        blockers,
    )


def _baseline_soak_blockers(baseline: dict[str, Any], soak: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    configuration = _mapping(soak.get("configuration"), "resource-soak receipt configuration")
    artifact = _mapping(configuration.get("artifact"), "resource-soak receipt artifact")
    config = _mapping(configuration.get("config"), "resource-soak receipt config")
    environment = _mapping(configuration.get("environment"), "resource-soak receipt environment")
    fixture = _mapping(baseline.get("fixture"), "fresh baseline fixture")
    if fixture.get("component_digest") != artifact.get("component_digest"):
        blockers.append("fresh baseline fixture digest does not match the final resource-soak fixture")
    for field in ("pool_capacity", "pool_queue_capacity", "runtime_workers", "prepared_cache_enabled", "wasmtime_instance_allocator", "wasmtime_copy_on_write_images"):
        if baseline["configuration"].get(field) != config.get(field):
            blockers.append(f"fresh baseline configuration does not match the final resource soak for {field}")
    for field in REQUIRED_TOOLCHAIN_FIELDS:
        if baseline["toolchain"].get(field) != environment.get(field):
            blockers.append(f"fresh baseline toolchain does not match the final resource soak for {field}")
    return blockers


def _identity_blockers(
    current: dict[str, Any], evidence: dict[str, dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    blockers: list[str] = []
    if not current.get("worktree_clean"):
        blockers.append("current repository worktree is not clean")
    evidence_identities: dict[str, dict[str, Any]] = {}
    for label, document in evidence.items():
        try:
            identity = execution_evidence_identity(document["source_commit"], document["source_tree"])
        except EvidenceValidationError as error:
            raise GateValidationError(f"cannot bind {label} evidence to its Git source: {error}") from error
        evidence_identities[label] = identity
        if identity["sha256"] != current["sha256"]:
            blockers.append(f"{label} execution evidence identity does not match the current executable implementation")
    return evidence_identities, blockers


def build_gate_receipt(
    baseline_document: dict[str, Any],
    baseline_path: str,
    calibration_path: Path,
    profiling_path: Path,
    soak_path: Path,
) -> dict[str, Any]:
    """Build a receipt. Invalid evidence raises; incomplete evidence blocks."""

    try:
        calibration_document = verify_calibration_evidence(calibration_path)
        profiling_document = verify_profile_evidence(profiling_path, calibration_path)
        soak_document = verify_resource_soak_evidence(soak_path, calibration_path)
        current_identity = current_execution_evidence_identity()
    except EvidenceValidationError as error:
        raise GateValidationError(str(error)) from error

    baseline = validate_baseline(baseline_document, baseline_path, current_identity)
    calibration = validate_calibration(calibration_document, str(calibration_path))
    profiling = validate_profiling(profiling_document, str(profiling_path))
    soak, blockers = validate_resource_soak(soak_document, str(soak_path))
    evidence_identities, identity_blockers = _identity_blockers(
        current_identity,
        {"calibration": calibration, "hot-path profiling": profiling, "resource soak": soak},
    )
    blockers.extend(identity_blockers)
    blockers.extend(_baseline_soak_blockers(baseline, soak))
    blockers = list(dict.fromkeys(blockers))
    authorization_status = "authorized" if not blockers else "blocked"
    return {
        "schema_version": GATE_SCHEMA,
        "status": "pass" if authorization_status == "authorized" else "blocked",
        "authorization_status": authorization_status,
        "phase1_authorized": authorization_status == "authorized",
        "production_ready": False,
        "phase1_api_compatible": False,
        "current_repository": current_identity,
        "execution_evidence": {
            "comparison_rule": "Every retained evidence source must have the exact canonical execution-relevant tree identity of the current clean checkout. Git commit/tree are retained separately so documentation-only differences remain auditable without permitting execution-affecting drift.",
            "current": current_identity,
            "retained": evidence_identities,
        },
        "evidence_verification": {
            "calibration": "raw runs and host/execution records regenerated the retained aggregate",
            "hot_path_profiling": "sharded archive, manifest, CPU/allocation artifacts, full invariant proof, and aggregate were independently verified",
            "resource_soak": "zstd archive, manifest, raw runs, host/execution records, calibration applicability, and aggregate were independently verified",
        },
        "baseline": baseline,
        "calibration": calibration,
        "hot_path_profiling": profiling,
        "resource_soak": soak,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="fresh Phase 0 baseline JSON")
    parser.add_argument("output", type=Path, help="new receipt path")
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--profiling", type=Path, default=DEFAULT_PROFILING)
    parser.add_argument("--soak", type=Path, default=DEFAULT_SOAK)
    parser.add_argument(
        "--require-authorized",
        action="store_true",
        help="return non-zero unless the evidence authorizes Phase 1",
    )
    arguments = parser.parse_args()
    try:
        receipt = build_gate_receipt(
            _load_document(arguments.baseline),
            str(arguments.baseline),
            arguments.calibration,
            arguments.profiling,
            arguments.soak,
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except GateValidationError as error:
        print(f"Phase 0 gate validation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": receipt["status"], "authorization_status": receipt["authorization_status"], "output": str(arguments.output)}, sort_keys=True))
    if arguments.require_authorized and receipt["authorization_status"] != "authorized":
        print("Phase 0 gate did not authorize Phase 1; see the retained receipt", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
