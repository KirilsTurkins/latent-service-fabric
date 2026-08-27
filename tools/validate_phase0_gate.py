#!/usr/bin/env python3
"""Validate the Phase 0 completion evidence and emit a fail-closed receipt."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

BASELINE_SCHEMA = "latent.phase0.baseline.v2"
CALIBRATION_SCHEMA = "latent.phase0.calibration.v1"
PROFILE_SCHEMA = "latent.phase0.hot-path.aggregate.v3"
SOAK_SCHEMA = "latent.phase0.resource-soak.aggregate.v1"
GATE_SCHEMA = "latent.phase0.gate.v2"

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


class GateValidationError(ValueError):
    """Raised when the Phase 0 evidence cannot support a gate decision."""


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
    _require(isinstance(value, int) and not isinstance(value, bool) and value > 0, f"{label} must be a positive integer")
    return value


def _exact_names(
    names: list[str],
    expected: frozenset[str],
    label: str,
) -> None:
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
        return _mapping(json.loads(path.read_text(encoding="utf-8")), str(path))
    except OSError as error:
        raise GateValidationError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise GateValidationError(f"cannot parse JSON in {path}: {error}") from error


def _require_non_production(document: dict[str, Any], label: str) -> None:
    _require(document.get("observational_only") is True, f"{label} must remain observational")
    _require(document.get("production_slo") is False, f"{label} must not claim a production SLO")


def validate_baseline(document: dict[str, Any], baseline_path: str) -> dict[str, Any]:
    """Validate the current executable baseline produced by the local gate."""

    _require(document.get("schema_version") == BASELINE_SCHEMA, "unexpected Phase 0 baseline schema")
    _require(document.get("status") == "pass", "Phase 0 baseline did not pass")
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
        _require(
            check_document.get("passed") is True,
            f"baseline check {check_names[-1]!r} did not pass",
        )
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

    config = _mapping(document.get("config"), "baseline configuration")
    pool_capacity = _positive_int(config.get("pool_capacity"), "baseline pool capacity")
    queue_capacity = _positive_int(config.get("pool_queue_capacity"), "baseline queue capacity")
    _positive_int(config.get("runtime_workers"), "baseline runtime worker count")

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
        "production_ready": False,
        "phase1_api_compatible": False,
    }


def validate_calibration(document: dict[str, Any], calibration_path: str) -> dict[str, Any]:
    """Validate the native-Linux variance evidence used for Phase 1 comparisons."""

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
    _require(len(run_names) == len(set(run_names)), "calibration has duplicate raw run names")

    hard_invariants = _mapping(document.get("hard_invariants"), "calibration hard invariants")
    _require(hard_invariants.get("all_runs_passed") is True, "calibration hard invariants did not all pass")
    _require(hard_invariants.get("performance_runs_excluded") == 0, "calibration excluded a performance run")
    check_names = [
        _string(name, "calibration hard-invariant name")
        for name in _list(hard_invariants.get("checks_passed_in_every_run"), "calibration hard-invariant names")
    ]
    _exact_names(check_names, REQUIRED_CHECKS, "calibration hard-invariant names")

    provenance = _mapping(document.get("source_provenance"), "calibration source provenance")
    _require(provenance.get("tree_identity_verified") is True, "calibration source tree was not verified")

    return {
        "status": "pass",
        "schema_version": CALIBRATION_SCHEMA,
        "path": calibration_path,
        "run_count": run_count,
        "source_commit": _string(document.get("source_commit"), "calibration source commit"),
        "source_tree": _string(document.get("source_tree"), "calibration source tree"),
    }


def validate_profiling(document: dict[str, Any], profiling_path: str) -> dict[str, Any]:
    """Validate the hot-path profile and optimization-handoff evidence."""

    _require(document.get("schema_version") == PROFILE_SCHEMA, "unexpected hot-path profile schema")
    _require(document.get("status") == "pass", "hot-path profiling aggregate did not pass")
    _require_non_production(document, "hot-path profiling aggregate")
    _require(document.get("cross_platform_claim") is False, "profiling must not make a cross-platform claim")

    guardrails = _mapping(document.get("guardrails"), "profiling guardrails")
    for guardrail, expected_value in REQUIRED_PROFILE_GUARDRAILS.items():
        _require(
            guardrails.get(guardrail) is expected_value,
            f"profiling guardrail {guardrail!r} is not preserved",
        )

    profiles = _list(document.get("profiles"), "profile workloads")
    workload_names = [
        _string(_mapping(profile, "profile workload").get("workload"), "profile workload name")
        for profile in profiles
    ]
    _exact_names(workload_names, REQUIRED_PROFILE_WORKLOADS, "profile workload names")

    decisions = _list(document.get("decisions"), "optimization decisions")
    decision_candidates: list[str] = []
    for decision in decisions:
        decision_document = _mapping(decision, "optimization decision")
        decision_candidates.append(_string(decision_document.get("candidate"), "optimization decision candidate"))
        _string(decision_document.get("decision"), "optimization decision")
        _string(decision_document.get("rationale"), "optimization decision rationale")
        _string(decision_document.get("handoff"), "optimization decision handoff")
    _exact_names(decision_candidates, REQUIRED_DECISION_CANDIDATES, "optimization decision candidates")

    hard_invariants = _mapping(document.get("hard_invariants"), "profiling hard invariants")
    canonical_names = [
        _string(name, "profiling hard-invariant name")
        for name in _list(hard_invariants.get("canonical_names"), "profiling hard-invariant names")
    ]
    _require(
        REQUIRED_CHECKS <= set(canonical_names),
        "profiling full-invariant proof omits a Phase 0 hard invariant",
    )
    full_proof = _mapping(hard_invariants.get("full_invariant_proof"), "profiling full-invariant proof")
    _string(full_proof.get("raw_results"), "profiling full-invariant raw results path")

    return {
        "status": "pass",
        "schema_version": PROFILE_SCHEMA,
        "path": profiling_path,
        "workloads": sorted(workload_names),
        "decisions": len(decision_candidates),
        "source_commit": _string(document.get("source_commit"), "profiling source commit"),
        "source_tree": _string(document.get("source_tree"), "profiling source tree"),
    }


def _archive_path(aggregate_path: Path, value: str, label: str) -> Path:
    aggregate_root = aggregate_path.parent.resolve()
    candidate = (aggregate_root / value).resolve()
    _require(candidate.is_relative_to(aggregate_root), f"{label} escapes the evidence directory")
    _require(candidate.is_file(), f"{label} is missing: {candidate}")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_resource_soak(document: dict[str, Any], soak_path: Path) -> tuple[dict[str, Any], list[str]]:
    """Validate soak structure and return explicit blockers for incomplete evidence."""

    _require(document.get("schema_version") == SOAK_SCHEMA, "unexpected resource-soak schema")
    _require_non_production(document, "resource-soak aggregate")
    _require(document.get("cross_machine_claim") is False, "resource soak must not make a cross-machine claim")

    minimum_runs = _positive_int(document.get("minimum_required_run_count"), "resource-soak minimum run count")
    run_count = _positive_int(document.get("run_count"), "resource-soak run count")
    _require(minimum_runs >= 3 and run_count >= minimum_runs, "resource soak must retain at least three processes")

    hard_invariants = _mapping(document.get("hard_invariants"), "resource-soak hard invariants")
    _require(hard_invariants.get("all_runs_passed") is True, "resource-soak hard invariants did not all pass")

    raw_runs = _list(document.get("raw_runs"), "resource-soak raw runs")
    _require(len(raw_runs) == run_count, "resource-soak raw run count does not match the aggregate")
    run_labels: list[str] = []
    for run in raw_runs:
        run_document = _mapping(run, "resource-soak raw run")
        run_labels.append(_string(run_document.get("label"), "resource-soak run label"))
        _require(run_document.get("schema_version") == "latent.phase0.resource-soak.run.v1", "unexpected resource-soak raw-run schema")
        source_identity = _mapping(run_document.get("source_identity"), "resource-soak source identity")
        _require(source_identity.get("tree_identity_verified") is True, "resource-soak source tree was not verified")
    _require(len(run_labels) == len(set(run_labels)), "resource soak has duplicate raw run labels")

    workload = _mapping(document.get("workload"), "resource-soak workload")
    _require(set(workload) == set(run_labels), "resource-soak workload entries do not match raw runs")
    for label in run_labels:
        run_workload = _mapping(workload[label], f"resource-soak workload {label}")
        _require(
            _positive_int(run_workload.get("warmup_activations"), f"{label} warm-up count") >= 1_000,
            f"resource-soak {label} has fewer than 1,000 warm-ups",
        )
        _require(
            _positive_int(run_workload.get("normal_measured_activations"), f"{label} measured activation count") >= 100_000,
            f"resource-soak {label} has fewer than 100,000 measured activations",
        )
        saturation_counts = _mapping(run_workload.get("saturation_batch_counts"), f"{label} saturation batches")
        _require(
            _positive_int(saturation_counts.get("at_capacity"), f"{label} at-capacity batch count") >= 100
            and _positive_int(saturation_counts.get("bounded_queue_saturation"), f"{label} bounded-queue batch count") >= 100,
            f"resource-soak {label} has incomplete saturation coverage",
        )

    raw_evidence = _mapping(document.get("raw_evidence_archive"), "resource-soak raw evidence archive")
    archive = _archive_path(soak_path, _string(raw_evidence.get("path"), "resource-soak archive path"), "resource-soak archive")
    _archive_path(soak_path, _string(raw_evidence.get("manifest"), "resource-soak manifest path"), "resource-soak manifest")
    expected_digest = _string(raw_evidence.get("sha256"), "resource-soak archive digest")
    observed_digest = "sha256:" + _sha256(archive)
    _require(observed_digest == expected_digest, "resource-soak archive digest does not match the aggregate")

    evidence_completeness = _mapping(document.get("evidence_completeness"), "resource-soak evidence completeness")
    calibration_noise = _mapping(document.get("calibration_noise"), "resource-soak calibration evidence")
    calibration_applicability = _mapping(
        calibration_noise.get("applicability"),
        "resource-soak calibration applicability",
    )
    file_descriptors = _mapping(document.get("file_descriptors"), "resource-soak file-descriptor evidence")

    blockers: list[str] = []
    if document.get("status") != "pass":
        blockers.append(f"resource-soak aggregate status is {document.get('status')!r}")
    if evidence_completeness.get("status") != "pass":
        blockers.append(
            "resource-soak evidence completeness is "
            f"{evidence_completeness.get('status')!r}"
        )
    if calibration_applicability.get("status") != "pass":
        blockers.append(
            "resource-soak calibration applicability is "
            f"{calibration_applicability.get('status')!r}"
        )
    if file_descriptors.get("status") != "pass":
        blockers.append(
            "resource-soak file-descriptor lifecycle evidence is "
            f"{file_descriptors.get('status')!r}"
        )

    return (
        {
            "status": document.get("status"),
            "schema_version": SOAK_SCHEMA,
            "path": str(soak_path),
            "run_count": run_count,
            "evidence_completeness": evidence_completeness.get("status"),
            "calibration_applicability": calibration_applicability.get("status"),
            "file_descriptor_lifecycle": file_descriptors.get("status"),
            "source_commit": _string(document.get("source_commit"), "resource-soak source commit"),
            "source_tree": _string(document.get("source_tree"), "resource-soak source tree"),
        },
        blockers,
    )


def build_gate_receipt(
    baseline_document: dict[str, Any],
    baseline_path: str,
    calibration_document: dict[str, Any],
    calibration_path: str,
    profiling_document: dict[str, Any],
    profiling_path: str,
    soak_document: dict[str, Any],
    soak_path: Path,
) -> dict[str, Any]:
    """Return a receipt; an incomplete retained soak is reported as blocked, not passed."""

    baseline = validate_baseline(baseline_document, baseline_path)
    calibration = validate_calibration(calibration_document, calibration_path)
    profiling = validate_profiling(profiling_document, profiling_path)
    soak, blockers = validate_resource_soak(soak_document, soak_path)
    authorized = not blockers

    return {
        "schema_version": GATE_SCHEMA,
        "status": "pass" if authorized else "blocked",
        "authorization_status": "authorized" if authorized else "blocked",
        "baseline": baseline,
        "reference_evidence": {
            "calibration": calibration,
            "hot_path_profiling": profiling,
            "resource_soak": soak,
        },
        "blockers": blockers,
        "production_ready": False,
        "phase1_api_compatible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="fresh Phase 0 baseline JSON")
    parser.add_argument("output", type=Path, help="path for the generated gate receipt")
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--profiling", type=Path, default=DEFAULT_PROFILING)
    parser.add_argument("--soak", type=Path, default=DEFAULT_SOAK)
    parser.add_argument(
        "--require-authorized",
        action="store_true",
        help="return non-zero unless all retained evidence authorizes Phase 1",
    )
    args = parser.parse_args()

    try:
        receipt = build_gate_receipt(
            _load_document(args.baseline),
            str(args.baseline),
            _load_document(args.calibration),
            str(args.calibration),
            _load_document(args.profiling),
            str(args.profiling),
            _load_document(args.soak),
            args.soak,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except GateValidationError as error:
        print(f"Phase 0 gate validation failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps(receipt, sort_keys=True))
    if args.require_authorized and receipt["authorization_status"] != "authorized":
        print(
            "Phase 0 completion gate is blocked: " + "; ".join(receipt["blockers"]),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
