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
    from .phase0_collector_identity import (
        CollectorIdentityError,
        require_native_collector_identity,
        same_identity as same_collector_identity,
        verify_retained_native_collector,
    )
    from .phase0_evidence import (
        CALIBRATION_SCHEMA,
        CALIBRATION_SOURCE_PROVENANCE_SCHEMA,
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
    from phase0_collector_identity import (  # type: ignore[no-redef]
        CollectorIdentityError,
        require_native_collector_identity,
        same_identity as same_collector_identity,
        verify_retained_native_collector,
    )
    from phase0_evidence import (
        CALIBRATION_SCHEMA,
        CALIBRATION_SOURCE_PROVENANCE_SCHEMA,
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
GIT_OBJECT_ID_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DURABLE_SOURCE_REF_PATTERN = re.compile(r"^refs/(?:heads|tags)/")
MEASUREMENT_IDENTITY_SCHEMA = "latent.phase0.measurement-identity.v1"
PROFILE_SOURCE_PROVENANCE_SCHEMA = "latent.phase0.hot-path.source-provenance.v1"
SOAK_SOURCE_PROVENANCE_SCHEMA = "latent.phase0.resource-soak.source-provenance.v1"
REFERENCE_PROFILE_CANDIDATE = "worker-cell-2w-2c"

DEFAULT_CALIBRATION = (
    REPOSITORY_ROOT
    / "benchmarks/phase0/calibration/native-linux-2026-08-30-52ac4754/aggregate.json"
)
DEFAULT_PROFILE_CALIBRATION = (
    REPOSITORY_ROOT
    / "benchmarks/phase0/calibration/native-linux-2026-08-30-52ac4754/aggregate.json"
)
DEFAULT_PROFILING = (
    REPOSITORY_ROOT
    / "benchmarks/phase0/profiling/native-linux-2026-08-30-52ac4754/aggregate.json"
)
DEFAULT_SOAK = (
    REPOSITORY_ROOT
    / "benchmarks/phase0/soak/native-linux-2026-08-30-52ac4754/aggregate.json"
)

REQUIRED_CHECKS = frozenset(
    {
        "real_issue23_executable_probe_passed",
        "real_issue23_executable_failure_and_recovery_probe_passed",
        "linux_process_resource_probe_supported",
        "configured_runtime_workers_observed_before_and_after_loading",
        "prepared_cache_bounded_after_prepare",
        "prepared_cache_reuse_probe_matches_configuration",
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
CANONICAL_MEASUREMENT_CONFIGURATION_FIELDS = (
    "pool_capacity",
    "pool_queue_capacity",
    "runtime_workers",
    "fuel",
    "memory_bytes",
    "memory_pressure_bytes",
    "timeout_ms",
    "cancel_after_ms",
    "prepared_cache_enabled",
    "wasmtime_copy_on_write_images",
)
FULL_BASELINE_MINIMUM_WORKLOAD = {
    "warm_samples": 40,
    "sequence_repetitions": 10,
    "throughput_batches": 24,
    "pool_iterations": 2_000,
}


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


def _git_object_id(value: Any, label: str) -> str:
    object_id = _string(value, label)
    _require(
        GIT_OBJECT_ID_PATTERN.fullmatch(object_id) is not None,
        f"{label} must be a lowercase 40-character Git object ID",
    )
    return object_id


def _durable_source_ref(value: Any, label: str) -> str:
    source_ref = _string(value, label)
    _require(
        DURABLE_SOURCE_REF_PATTERN.match(source_ref) is not None,
        f"{label} must be a branch or tag ref",
    )
    suffix = source_ref.removeprefix("refs/heads/")
    if suffix == source_ref:
        suffix = source_ref.removeprefix("refs/tags/")
    _require(
        bool(suffix)
        and not suffix.startswith(("/", "."))
        and not suffix.endswith(("/", "."))
        and suffix != "@"
        and ".." not in suffix
        and "//" not in suffix
        and "@{" not in suffix
        and not any(character.isspace() or character in "~^:?*[\\" for character in suffix),
        f"{label} is not a valid durable Git ref",
    )
    return source_ref


def _measurement_identity(value: Any, label: str) -> dict[str, Any]:
    identity = _mapping(value, label)
    _require(
        identity.get("schema_version") == MEASUREMENT_IDENTITY_SCHEMA,
        f"{label} has an unexpected schema",
    )
    artifact = _mapping(identity.get("artifact"), f"{label} artifact")
    _valid_digest(artifact.get("component_digest"), f"{label} component digest")
    _positive_int(artifact.get("component_bytes"), f"{label} component bytes")
    _valid_digest(artifact.get("capsule_digest"), f"{label} capsule digest")
    _positive_int(artifact.get("capsule_bytes"), f"{label} capsule bytes")
    configuration = _mapping(identity.get("configuration"), f"{label} configuration")
    _require(configuration, f"{label} has no invariant-relevant configuration")
    return identity


def _collector_identity(value: Any, label: str, executable: str) -> dict[str, Any]:
    try:
        return require_native_collector_identity(value, label, executable)
    except CollectorIdentityError as error:
        raise GateValidationError(str(error)) from error


def _retained_collector_identity(
    evidence_root: Path, value: Any, label: str, executable: str
) -> dict[str, Any]:
    try:
        return verify_retained_native_collector(
            evidence_root, value, label, executable
        )
    except CollectorIdentityError as error:
        raise GateValidationError(str(error)) from error


def _canonical_runtime_measurement_identity(
    artifact: dict[str, Any], config: dict[str, Any], label: str
) -> dict[str, Any]:
    """Normalize the shared Phase 0 runtime identity across evidence types.

    The full-profile calibration names the allocator field
    ``wasmtime_allocator`` while the soak names it
    ``wasmtime_instance_allocator``.  All other fields here are the common
    fixture, runtime-capacity, and execution-budget controls that must be
    held equal for a calibration comparison to be meaningful.
    """

    component_digest = _valid_digest(
        artifact.get("component_digest"), f"{label} component digest"
    )
    component_bytes = _positive_int(
        artifact.get("component_bytes"), f"{label} component bytes"
    )
    capsule_digest = _valid_digest(
        artifact.get("capsule_digest"), f"{label} capsule digest"
    )
    capsule_bytes = _positive_int(
        artifact.get("capsule_bytes"), f"{label} capsule bytes"
    )
    allocator = config.get("wasmtime_instance_allocator")
    historical_allocator = config.get("wasmtime_allocator")
    if allocator is not None and historical_allocator is not None:
        _require(
            allocator == historical_allocator,
            f"{label} records conflicting Wasmtime allocator modes",
        )
    allocator = allocator if allocator is not None else historical_allocator
    _require(
        allocator == "on_demand",
        f"{label} must retain the on-demand Wasmtime allocator",
    )
    canonical_configuration: dict[str, Any] = {}
    for field in CANONICAL_MEASUREMENT_CONFIGURATION_FIELDS:
        value = config.get(field)
        if field in {"prepared_cache_enabled", "wasmtime_copy_on_write_images"}:
            _require(isinstance(value, bool), f"{label} {field} must be boolean")
        else:
            _positive_int(value, f"{label} {field}")
        canonical_configuration[field] = value
    canonical_configuration["wasmtime_instance_allocator"] = allocator
    return {
        "schema_version": MEASUREMENT_IDENTITY_SCHEMA,
        "artifact": {
            "component_digest": component_digest,
            "component_bytes": component_bytes,
            "capsule_digest": capsule_digest,
            "capsule_bytes": capsule_bytes,
        },
        "configuration": canonical_configuration,
    }


def _require_baseline_workload_profile(
    config: dict[str, Any], success_sample_count: int
) -> str:
    """Reject a smoke-sized baseline relabelled as a full authorization run."""

    profile = config.get("mode")
    _require(
        profile in {"full", "smoke"},
        "baseline configuration mode must be either 'full' or 'smoke'",
    )
    minimum_success_samples = 12 if profile == "full" else 3
    _require(
        success_sample_count >= minimum_success_samples,
        f"{profile} baseline executable harness must retain at least "
        f"{minimum_success_samples} cold success samples",
    )
    if profile == "full":
        for field, minimum in FULL_BASELINE_MINIMUM_WORKLOAD.items():
            value = config.get(field)
            _require(
                isinstance(value, int)
                and not isinstance(value, bool)
                and value >= minimum,
                f"full baseline {field} must be at least {minimum}",
            )
    return profile


def _soak_durable_source_provenance(
    value: Any,
    label: str,
    source_commit: str,
    source_tree: str,
    *,
    aggregate: bool,
) -> dict[str, Any]:
    """Validate the durable pushed-source receipt retained with new soaks."""

    provenance = _mapping(value, label)
    if aggregate:
        _require(
            provenance.get("schema_version") == SOAK_SOURCE_PROVENANCE_SCHEMA,
            f"{label} lacks the durable-ref schema",
        )
    _require(
        provenance.get("published_commit") == source_commit,
        f"{label} published commit does not match the soak source commit",
    )
    _require(
        provenance.get("published_tree") == source_tree,
        f"{label} published tree does not match the soak source tree",
    )
    source_ref = _durable_source_ref(
        provenance.get("published_source_ref"), f"{label} durable source ref"
    )
    ref_head = _git_object_id(
        provenance.get("published_source_ref_head"), f"{label} durable source-ref head"
    )
    _require(
        provenance.get("published_commit_reachable_from_ref") is True,
        f"{label} did not verify published commit reachability from its durable ref",
    )
    _require(
        provenance.get("execution_commit") == source_commit,
        f"{label} execution commit does not equal the published source commit",
    )
    _require(
        provenance.get("execution_tree") == source_tree,
        f"{label} execution tree does not equal the published source tree",
    )
    _require(
        provenance.get("execution_commit_matches_published") is True,
        f"{label} did not verify execution HEAD equals the published source commit",
    )
    _require(
        provenance.get("tree_identity_verified") is True,
        f"{label} source tree was not verified",
    )
    return {
        "published_commit": source_commit,
        "published_tree": source_tree,
        "published_source_ref": source_ref,
        "published_source_ref_head": ref_head,
        "published_commit_reachable_from_ref": True,
        "execution_commit": source_commit,
        "execution_tree": source_tree,
        "execution_commit_matches_published": True,
        "tree_identity_verified": True,
    }


def _profile_durable_source_provenance(
    value: Any,
    label: str,
    source_commit: str,
    source_tree: str,
) -> dict[str, Any]:
    """Validate and normalize the profiling runner's durable source receipt."""

    provenance = _mapping(value, label)
    _require(
        provenance.get("schema_version") == PROFILE_SOURCE_PROVENANCE_SCHEMA,
        f"{label} lacks the durable-ref schema",
    )
    published_commit = _git_object_id(
        provenance.get("published_commit"), f"{label} published commit"
    )
    published_tree = _git_object_id(
        provenance.get("published_tree"), f"{label} published tree"
    )
    source_ref = _durable_source_ref(
        provenance.get("published_source_ref"), f"{label} durable source ref"
    )
    ref_head = _git_object_id(
        provenance.get("published_source_ref_head"), f"{label} durable source-ref head"
    )
    execution_commit = _git_object_id(
        provenance.get("execution_commit"), f"{label} execution commit"
    )
    execution_tree = _git_object_id(
        provenance.get("execution_tree"), f"{label} execution tree"
    )
    _require(
        published_commit == source_commit,
        f"{label} published commit does not match the profiling source commit",
    )
    _require(
        published_tree == source_tree,
        f"{label} published tree does not match the profiling source tree",
    )
    _require(
        provenance.get("published_commit_reachable_from_ref") is True,
        f"{label} did not verify published commit reachability from its durable ref",
    )
    _require(
        execution_commit == source_commit,
        f"{label} execution commit does not equal the published source commit",
    )
    _require(
        execution_tree == source_tree,
        f"{label} execution tree does not equal the published source tree",
    )
    _require(
        provenance.get("execution_commit_matches_published") is True,
        f"{label} did not verify execution HEAD equals the published source commit",
    )
    _require(
        provenance.get("tree_identity_verified") is True,
        f"{label} source tree was not verified",
    )
    return {
        "schema_version": PROFILE_SOURCE_PROVENANCE_SCHEMA,
        "published_commit": published_commit,
        "published_tree": published_tree,
        "published_source_ref": source_ref,
        "published_source_ref_head": ref_head,
        "published_commit_reachable_from_ref": True,
        "execution_commit": execution_commit,
        "execution_tree": execution_tree,
        "execution_commit_matches_published": True,
        "tree_identity_verified": True,
    }


def _same_json(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def _profile_host_observations(value: Any, label: str) -> dict[str, Any]:
    observations = _mapping(value, label)
    for field in ("before", "after"):
        _string(observations.get(field), f"{label} {field} path")
        _valid_digest(observations.get(f"{field}_sha256"), f"{label} {field} checksum")
    identity = _mapping(observations.get("static_identity"), f"{label} static identity")
    _mapping(identity.get("virtualization"), f"{label} virtualization identity")
    _mapping(identity.get("allocator"), f"{label} allocator identity")
    _mapping(identity.get("cpu_frequency_policy"), f"{label} CPU policy identity")
    return observations


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
        "baseline must remain explicitly non-Phase-1-API-compatible",
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
    collector_identity = _retained_collector_identity(
        Path(baseline_path).parent,
        artifact.get("collector"),
        "fresh baseline native collector",
        "phase0-baseline",
    )
    config = _mapping(document.get("config"), "baseline configuration")
    measurement_identity = _canonical_runtime_measurement_identity(
        artifact, config, "fresh baseline"
    )
    profile = _require_baseline_workload_profile(config, len(success_samples))
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
        "profile": profile,
        "required_checks_passed": len(REQUIRED_CHECKS),
        "observed_terminal_outcomes": sorted(REQUIRED_TERMINAL_OUTCOMES),
        "executable_e2e": "passed",
        "source_commit": environment["repository_commit"],
        "source_tree": current_identity["tree"],
        "fixture": dict(measurement_identity["artifact"]),
        "configuration": dict(measurement_identity["configuration"]),
        "measurement_identity": measurement_identity,
        "collector_identity": collector_identity,
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
        "rerun_required_rule",
        "regression_candidate_rule",
        "confirmed_regression_rule",
        "shared_hosted_ci",
    ):
        _string(comparison_method.get(field), f"calibration comparison method {field}")
    _require(
        "inconclusive_rule" not in comparison_method,
        "current calibration comparison method must use an explicit rerun-required rule",
    )
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
    collector_identity = _collector_identity(
        reference_identity.get("collector"),
        "calibration reference native collector",
        "phase0-baseline",
    )
    _valid_digest(artifact.get("component_digest"), "calibration component digest")
    _positive_int(artifact.get("component_bytes"), "calibration component bytes")
    _valid_digest(artifact.get("capsule_digest"), "calibration capsule digest")
    _positive_int(artifact.get("capsule_bytes"), "calibration capsule bytes")
    _mapping(reference_identity.get("config"), "calibration reference configuration")
    environment = _mapping(reference_identity.get("environment"), "calibration reference environment")
    for field in REQUIRED_TOOLCHAIN_FIELDS:
        _string(environment.get(field), f"calibration environment {field}")
    for run in raw_runs:
        run_document = _mapping(run, "calibration raw run")
        run_collector = _collector_identity(
            run_document.get("collector_identity"),
            f"calibration {run_document.get('run')} native collector",
            "phase0-baseline",
        )
        _require(
            same_collector_identity(run_collector, collector_identity),
            f"calibration {run_document.get('run')} native collector differs from the reference",
        )

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
        _string(
            comparison.get("rerun_required_rule"),
            f"calibration metric {name} rerun-required rule",
        )
        _require(
            "inconclusive_rule" not in comparison,
            f"calibration metric {name} must use an explicit rerun-required rule",
        )

    source_commit = _git_object_id(
        document.get("source_commit"), "calibration source commit"
    )
    source_tree = _git_object_id(document.get("source_tree"), "calibration source tree")
    provenance = _mapping(document.get("source_provenance"), "calibration source provenance")
    _require(
        provenance.get("schema_version") == CALIBRATION_SOURCE_PROVENANCE_SCHEMA,
        "calibration source provenance lacks the durable-ref schema",
    )
    _require(
        provenance.get("published_commit") == source_commit,
        "calibration published commit does not match the aggregate source commit",
    )
    _require(
        provenance.get("published_tree") == source_tree,
        "calibration published tree does not match the aggregate source tree",
    )
    _git_object_id(
        provenance.get("published_source_ref_head"),
        "calibration durable source-ref head",
    )
    _string(provenance.get("published_source_ref"), "calibration durable source ref")
    _require(
        provenance.get("published_commit_reachable_from_ref") is True,
        "calibration did not verify published commit reachability from its durable ref",
    )
    _require(
        provenance.get("execution_commit") == source_commit,
        "calibration execution commit does not equal the published source commit",
    )
    _require(
        provenance.get("execution_tree") == source_tree,
        "calibration execution tree does not equal the published source tree",
    )
    _require(
        provenance.get("execution_commit_matches_published") is True,
        "calibration did not verify execution HEAD equals the published commit",
    )
    _require(
        provenance.get("tree_identity_verified") is True,
        "calibration source tree was not verified",
    )
    measurement_identity = _canonical_runtime_measurement_identity(
        artifact,
        _mapping(reference_identity.get("config"), "calibration reference configuration"),
        "calibration reference identity",
    )
    return {
        "status": "pass",
        "schema_version": CALIBRATION_SCHEMA,
        "path": calibration_path,
        "run_count": run_count,
        "metric_count": len(metrics),
        "source_commit": source_commit,
        "source_tree": source_tree,
        "source_provenance": provenance,
        "reference_identity": reference_identity,
        "measurement_identity": measurement_identity,
        "collector_identity": collector_identity,
    }


def validate_profiling(document: dict[str, Any], profiling_path: str) -> dict[str, Any]:
    """Check raw-regenerated CPU/allocation artifacts and decision records."""

    _require(document.get("schema_version") == PROFILE_SCHEMA, "unexpected hot-path profile schema")
    _require(document.get("status") == "pass", "hot-path profiling aggregate did not pass")
    _require_non_production(document, "hot-path profiling aggregate")
    _require(document.get("cross_platform_claim") is False, "profiling must not make a cross-platform claim")
    source_commit = _git_object_id(
        document.get("source_commit"), "profiling source commit"
    )
    source_tree = _git_object_id(document.get("source_tree"), "profiling source tree")
    source_provenance = _profile_durable_source_provenance(
        document.get("source_provenance"),
        "profiling source provenance",
        source_commit,
        source_tree,
    )
    collector_identity = _collector_identity(
        document.get("collector_identity"),
        "profiling aggregate native collector",
        "phase0-baseline",
    )
    guardrails = _mapping(document.get("guardrails"), "profiling guardrails")
    for guardrail, expected_value in REQUIRED_PROFILE_GUARDRAILS.items():
        _require(guardrails.get(guardrail) is expected_value, f"profiling guardrail {guardrail!r} is not preserved")

    profiles = _list(document.get("profiles"), "profile workloads")
    workload_names: list[str] = []
    for profile in profiles:
        record = _mapping(profile, "profile workload")
        workload = _string(record.get("workload"), "profile workload name")
        workload_names.append(workload)
        profile_collector = _collector_identity(
            record.get("collector_identity"),
            f"profile {workload} native collector",
            "phase0-baseline",
        )
        _require(
            same_collector_identity(profile_collector, collector_identity),
            f"profile {workload} native collector differs from the aggregate",
        )
        _string(record.get("scenario_semantics"), f"profile {workload} scenario semantics")
        _list(record.get("selected_scenarios"), f"profile {workload} selected scenarios")
        composition_identity = _measurement_identity(
            record.get("composition_identity"), f"profile {workload} composition identity"
        )
        perf = _mapping(record.get("perf"), f"profile {workload} CPU artifact")
        allocation = _mapping(record.get("allocation"), f"profile {workload} allocation artifact")
        perf_identity = _measurement_identity(
            perf.get("measurement_identity"), f"profile {workload} CPU measurement identity"
        )
        allocation_identity = _measurement_identity(
            allocation.get("measurement_identity"),
            f"profile {workload} allocation measurement identity",
        )
        _require(
            _same_json(perf_identity, allocation_identity),
            f"profile {workload} CPU/allocation measurement identities differ",
        )
        _profile_host_observations(
            perf.get("host_observations"), f"profile {workload} CPU host observations"
        )
        _profile_host_observations(
            allocation.get("host_observations"),
            f"profile {workload} allocation host observations",
        )
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
    full_collector = _collector_identity(
        full_proof.get("collector_identity"),
        "profiling full-invariant native collector",
        "phase0-baseline",
    )
    _require(
        same_collector_identity(full_collector, collector_identity),
        "profiling full-invariant native collector differs from the aggregate",
    )
    _string(full_proof.get("raw_results"), "profiling full-invariant raw results path")
    _valid_digest(full_proof.get("raw_results_sha256"), "profiling full-invariant raw results checksum")
    _string(full_proof.get("command"), "profiling full-invariant command path")
    _valid_digest(full_proof.get("command_sha256"), "profiling full-invariant command checksum")
    full_command_identity = _mapping(
        full_proof.get("command_identity"),
        "profiling full-invariant command identity",
    )
    for field, expected in (
        ("source_commit", source_commit),
        ("source_tree", source_tree),
        ("published_source_ref", source_provenance["published_source_ref"]),
        (
            "published_source_ref_head",
            source_provenance["published_source_ref_head"],
        ),
        ("execution_commit", source_commit),
        ("execution_tree", source_tree),
    ):
        _require(
            full_command_identity.get(field) == expected,
            f"profiling full-invariant command identity differs for {field}",
        )
    full_measurement_identity = _measurement_identity(
        full_proof.get("measurement_identity"), "profiling full-invariant measurement identity"
    )
    _profile_host_observations(
        full_proof.get("host_observations"), "profiling full-invariant host observations"
    )
    full_composition_identity = _measurement_identity(
        full_proof.get("composition_identity"), "profiling full-invariant composition identity"
    )
    for profile in profiles:
        record = _mapping(profile, "profile workload")
        workload = _string(record.get("workload"), "profile workload name")
        profile_composition_identity = _measurement_identity(
            record.get("composition_identity"), f"profile {workload} composition identity"
        )
        _require(
            _same_json(profile_composition_identity, full_composition_identity),
            f"profile {workload} composition identity differs from the full-invariant proof",
        )

    candidates = _mapping(document.get("candidates"), "profiling candidates")
    _require(candidates, "profiling has no candidate measurements")
    for name, candidate in candidates.items():
        candidate_document = _mapping(candidate, f"profiling candidate {name}")
        run_count = _positive_int(candidate_document.get("run_count"), f"profiling candidate {name} run count")
        candidate_identity = _measurement_identity(
            candidate_document.get("measurement_identity"),
            f"profiling candidate {name} measurement identity",
        )
        candidate_collector = _collector_identity(
            candidate_document.get("collector_identity"),
            f"profiling candidate {name} native collector",
            "phase0-baseline",
        )
        _require(
            same_collector_identity(candidate_collector, collector_identity),
            f"profiling candidate {name} native collector differs from the aggregate",
        )
        raw_runs = _list(candidate_document.get("raw_runs"), f"profiling candidate {name} raw runs")
        _require(len(raw_runs) == run_count, f"profiling candidate {name} raw-run count is invalid")
        for raw_run in raw_runs:
            raw_run_document = _mapping(raw_run, f"profiling candidate {name} raw run")
            raw_identity = _measurement_identity(
                raw_run_document.get("measurement_identity"),
                f"profiling candidate {name} raw-run measurement identity",
            )
            raw_collector = _collector_identity(
                raw_run_document.get("collector_identity"),
                f"profiling candidate {name} raw-run native collector",
                "phase0-baseline",
            )
            _require(
                same_collector_identity(raw_collector, collector_identity),
                f"profiling candidate {name} raw-run native collector differs from the aggregate",
            )
            _require(
                _same_json(raw_identity, candidate_identity),
                f"profiling candidate {name} raw-run measurement identity differs",
            )
            _profile_host_observations(
                raw_run_document.get("host_observations"),
                f"profiling candidate {name} raw-run host observations",
            )
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
        if name == REFERENCE_PROFILE_CANDIDATE:
            _require(
                run_count >= 7,
                "reference-equivalent profiling candidate must retain at least seven runs",
            )
            _require(
                _same_json(candidate_identity, full_measurement_identity),
                "reference-equivalent profiling candidate identity differs from the full-invariant proof",
            )
            eligibility = _mapping(
                candidate_document.get("calibration_comparison_eligibility"),
                "reference candidate calibration eligibility",
            )
            _require(
                eligibility.get("status") == "reference_equivalent",
                "reference candidate is not calibration reference-equivalent",
            )
            comparisons = _mapping(
                candidate_document.get("calibration_comparison"),
                "reference candidate calibration comparison",
            )
            _require(comparisons, "reference candidate has no calibration comparison")
            for metric, comparison in comparisons.items():
                comparison_document = _mapping(
                    comparison, f"reference candidate comparison {metric}"
                )
                _require(
                    comparison_document.get("status")
                    in {"inside_advisory_band", "outside_advisory_band"},
                    f"reference candidate comparison {metric} is not decisive",
                )
        else:
            scope = _mapping(
                candidate_document.get("phase0_calibration"),
                f"profiling candidate {name} Phase 0 calibration scope",
            )
            _require(
                scope.get("status") == "not_applicable_for_phase0_calibration",
                f"profiling candidate {name} has an invalid Phase 0 calibration scope",
            )
            _require(
                "calibration_comparison" not in candidate_document
                and "calibration_comparison_eligibility" not in candidate_document,
                f"profiling candidate {name} must not publish a Phase 0 calibration comparison",
            )

    _require(
        REFERENCE_PROFILE_CANDIDATE in candidates,
        "profiling has no reference-equivalent default candidate",
    )

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
        "source_commit": source_commit,
        "source_tree": source_tree,
        "source_provenance": source_provenance,
        "collector_identity": collector_identity,
    }


def validate_resource_soak(document: dict[str, Any], soak_path: str) -> tuple[dict[str, Any], list[str]]:
    """Check raw-regenerated soak evidence and return non-structural blockers."""

    _require(document.get("schema_version") == SOAK_SCHEMA, "unexpected resource-soak schema")
    _require_non_production(document, "resource-soak aggregate")
    _require(document.get("cross_machine_claim") is False, "resource soak must not make a cross-machine claim")
    minimum_runs = _positive_int(document.get("minimum_required_run_count"), "resource-soak minimum run count")
    run_count = _positive_int(document.get("run_count"), "resource-soak run count")
    _require(minimum_runs >= 3 and run_count >= minimum_runs, "resource soak must retain at least three processes")
    source_commit = _git_object_id(
        document.get("source_commit"), "resource-soak source commit"
    )
    source_tree = _git_object_id(document.get("source_tree"), "resource-soak source tree")
    source_provenance = _soak_durable_source_provenance(
        document.get("source_provenance"),
        "resource-soak source provenance",
        source_commit,
        source_tree,
        aggregate=True,
    )
    hard_invariants = _mapping(document.get("hard_invariants"), "resource-soak hard invariants")
    _require(hard_invariants.get("all_runs_passed") is True, "resource-soak hard invariants did not all pass")
    canonical_checks = [_string(name, "resource-soak hard-invariant name") for name in _list(hard_invariants.get("canonical_check_names"), "resource-soak hard-invariant names")]
    _require(canonical_checks, "resource-soak has no hard-invariant names")
    _require(len(canonical_checks) == len(set(canonical_checks)), "resource-soak hard-invariant names contain duplicates")

    raw_runs = _list(document.get("raw_runs"), "resource-soak raw runs")
    _require(len(raw_runs) == run_count, "resource-soak raw run count does not match the aggregate")
    labels: list[str] = []
    raw_collectors: list[dict[str, Any]] = []
    for run in raw_runs:
        record = _mapping(run, "resource-soak raw run")
        labels.append(_string(record.get("label"), "resource-soak run label"))
        _require(record.get("schema_version") == "latent.phase0.resource-soak.run.v1", "unexpected resource-soak raw-run schema")
        source_identity = _mapping(record.get("source_identity"), "resource-soak source identity")
        raw_provenance = _soak_durable_source_provenance(
            source_identity,
            f"resource-soak {labels[-1]} source provenance",
            source_commit,
            source_tree,
            aggregate=False,
        )
        _require(
            raw_provenance == source_provenance,
            f"resource-soak {labels[-1]} durable source provenance differs from the aggregate",
        )
        _require(
            source_identity.get("final_configuration_commit") == source_commit,
            f"resource-soak {labels[-1]} final configuration does not match the published source commit",
        )
        raw_artifact = _mapping(record.get("artifact"), f"resource-soak {labels[-1]} artifact")
        raw_collector = _collector_identity(
            raw_artifact.get("collector"),
            f"resource-soak {labels[-1]} native collector",
            "phase0-soak",
        )
        raw_collectors.append(raw_collector)
        _valid_digest(raw_artifact.get("component_digest"), f"resource-soak {labels[-1]} component digest")
        _positive_int(raw_artifact.get("component_bytes"), f"resource-soak {labels[-1]} component bytes")
        _valid_digest(raw_artifact.get("capsule_digest"), f"resource-soak {labels[-1]} capsule digest")
        _positive_int(raw_artifact.get("capsule_bytes"), f"resource-soak {labels[-1]} capsule bytes")
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
    configuration_source_identity = _mapping(
        configuration.get("source_identity"), "resource-soak configuration source identity"
    )
    configuration_provenance = _soak_durable_source_provenance(
        configuration_source_identity,
        "resource-soak configuration source provenance",
        source_commit,
        source_tree,
        aggregate=False,
    )
    _require(
        configuration_provenance == source_provenance,
        "resource-soak configuration durable source provenance differs from the aggregate",
    )
    _require(
        configuration_source_identity.get("final_configuration_commit") == source_commit,
        "resource-soak configuration final configuration does not match the published source commit",
    )
    artifact = (
        _mapping(configuration.get("artifact"), "resource-soak artifact")
        if isinstance(configuration.get("artifact"), dict)
        else configuration
    )
    collector_identity = _collector_identity(
        configuration.get("collector"),
        "resource-soak configuration native collector",
        "phase0-soak",
    )
    _valid_digest(artifact.get("component_digest"), "resource-soak component digest")
    _positive_int(artifact.get("component_bytes"), "resource-soak component bytes")
    _valid_digest(artifact.get("capsule_digest"), "resource-soak capsule digest")
    _positive_int(artifact.get("capsule_bytes"), "resource-soak capsule bytes")
    config = _mapping(configuration.get("config"), "resource-soak configuration")
    for field in ("pool_capacity", "pool_queue_capacity", "runtime_workers"):
        _positive_int(config.get(field), f"resource-soak {field}")
    _require(config.get("prepared_cache_enabled") is True, "resource-soak must retain prepared cache")
    _require(config.get("wasmtime_instance_allocator") == "on_demand", "resource-soak must retain on-demand allocator")
    _require(config.get("wasmtime_copy_on_write_images") is True, "resource-soak must retain initialized-memory COW")
    environment = _mapping(configuration.get("environment"), "resource-soak environment")
    for field in REQUIRED_TOOLCHAIN_FIELDS:
        _string(environment.get(field), f"resource-soak environment {field}")

    measurement_identity = _canonical_runtime_measurement_identity(
        artifact, config, "resource-soak configuration identity"
    )
    for record, raw_collector in zip(raw_runs, raw_collectors, strict=True):
        raw_artifact = _mapping(record.get("artifact"), "resource-soak raw-run artifact")
        for field in ("component_digest", "component_bytes", "capsule_digest", "capsule_bytes"):
            _require(
                raw_artifact.get(field) == artifact.get(field),
                f"resource-soak raw-run artifact {field} differs from the aggregate fixture",
            )
        _require(
            same_collector_identity(raw_collector, collector_identity),
            "resource-soak raw-run native collector differs from the aggregate",
        )

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
        "capsule_digest": artifact["capsule_digest"],
        "capsule_bytes": artifact["capsule_bytes"],
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
            "source_commit": source_commit,
            "source_tree": source_tree,
            "source_provenance": source_provenance,
            "configuration": receipt_configuration,
            "measurement_identity": measurement_identity,
            "collector_identity": collector_identity,
        },
        blockers,
    )


def _baseline_soak_blockers(baseline: dict[str, Any], soak: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    configuration = _mapping(soak.get("configuration"), "resource-soak receipt configuration")
    environment = _mapping(configuration.get("environment"), "resource-soak receipt environment")
    baseline_identity = _measurement_identity(
        baseline.get("measurement_identity"),
        "fresh baseline canonical measurement identity",
    )
    soak_identity = _measurement_identity(
        soak.get("measurement_identity"),
        "resource-soak canonical measurement identity",
    )
    if not _same_json(baseline_identity, soak_identity):
        blockers.append(
            "fresh baseline canonical measurement identity does not match the final resource soak"
        )
    for field in REQUIRED_TOOLCHAIN_FIELDS:
        if baseline["toolchain"].get(field) != environment.get(field):
            blockers.append(f"fresh baseline toolchain does not match the final resource soak for {field}")
    return blockers


def _baseline_authorization_blockers(baseline: dict[str, Any]) -> list[str]:
    """Keep a passing smoke receipt distinct from a full authorization."""

    profile = baseline.get("profile")
    if profile != "full":
        return [
            f"fresh baseline profile is {profile!r}; Phase 1 authorization requires 'full'"
        ]
    return []


def _collector_blockers(
    baseline: dict[str, Any],
    calibration: dict[str, Any],
    profile_calibration: dict[str, Any],
    profiling: dict[str, Any],
    soak: dict[str, Any],
) -> list[str]:
    """Compare collector bytes where executable identity is expected to match.

    The soak intentionally uses another binary, so only its explicit release
    build configuration is compared with the phase0-baseline collectors.
    """

    baseline_collector = baseline["collector_identity"]
    blockers: list[str] = []
    for label, document in (
        ("calibration", calibration),
        ("profile calibration", profile_calibration),
        ("hot-path profiling", profiling),
    ):
        if not same_collector_identity(
            document.get("collector_identity"), baseline_collector
        ):
            blockers.append(
                f"{label} phase0-baseline native collector does not match the fresh baseline"
            )
    baseline_build = baseline_collector["build_configuration"]
    for label, document in (
        ("calibration", calibration),
        ("profile calibration", profile_calibration),
        ("hot-path profiling", profiling),
        ("resource soak", soak),
    ):
        collector = document.get("collector_identity")
        if not isinstance(collector, dict) or not _same_json(
            collector.get("build_configuration"), baseline_build
        ):
            blockers.append(
                f"{label} native collector build configuration does not match the fresh baseline"
            )
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
            identity = dict(
                execution_evidence_identity(
                    document["source_commit"], document["source_tree"]
                )
            )
        except EvidenceValidationError as error:
            raise GateValidationError(f"cannot bind {label} evidence to its Git source: {error}") from error
        provenance = document.get("source_provenance")
        if provenance is not None:
            provenance_document = _mapping(provenance, f"{label} durable source provenance")
            if (
                provenance_document.get("published_commit") != identity["commit"]
                or provenance_document.get("published_tree") != identity["tree"]
                or provenance_document.get("execution_commit") != identity["commit"]
                or provenance_document.get("execution_tree") != identity["tree"]
                or provenance_document.get("tree_identity_verified") is not True
                or provenance_document.get("execution_commit_matches_published") is not True
                or provenance_document.get("published_commit_reachable_from_ref") is not True
            ):
                blockers.append(
                    f"{label} durable source provenance does not match its canonical execution identity"
                )
            else:
                identity["source_provenance"] = provenance_document
        measurement = document.get("measurement_identity")
        if measurement is not None:
            identity["measurement_identity"] = _measurement_identity(
                measurement, f"{label} canonical measurement identity"
            )
        evidence_identities[label] = identity
        if identity["sha256"] != current["sha256"]:
            blockers.append(f"{label} execution evidence identity does not match the current executable implementation")
    calibration_identity = evidence_identities.get("calibration", {}).get(
        "measurement_identity"
    )
    if calibration_identity is not None:
        for label, identity in evidence_identities.items():
            measurement = identity.get("measurement_identity")
            if measurement is not None and not _same_json(measurement, calibration_identity):
                blockers.append(
                    f"{label} canonical measurement identity does not match calibration"
                )
    return evidence_identities, blockers


def build_gate_receipt(
    baseline_document: dict[str, Any],
    baseline_path: str,
    calibration_path: Path,
    profiling_path: Path,
    soak_path: Path,
    profile_calibration_path: Path = DEFAULT_PROFILE_CALIBRATION,
) -> dict[str, Any]:
    """Build a receipt. Invalid evidence raises; incomplete evidence blocks."""

    try:
        calibration_document = verify_calibration_evidence(calibration_path)
        profile_calibration_document = verify_calibration_evidence(profile_calibration_path)
        profiling_document = verify_profile_evidence(profiling_path, profile_calibration_path)
        soak_document = verify_resource_soak_evidence(soak_path, calibration_path)
        current_identity = current_execution_evidence_identity()
    except EvidenceValidationError as error:
        raise GateValidationError(str(error)) from error

    baseline = validate_baseline(baseline_document, baseline_path, current_identity)
    calibration = validate_calibration(calibration_document, str(calibration_path))
    profile_calibration = validate_calibration(
        profile_calibration_document, str(profile_calibration_path)
    )
    profiling = validate_profiling(profiling_document, str(profiling_path))
    soak, blockers = validate_resource_soak(soak_document, str(soak_path))
    evidence_identities, identity_blockers = _identity_blockers(
        current_identity,
        {
            "calibration": calibration,
            "profile calibration": profile_calibration,
            "hot-path profiling": profiling,
            "resource soak": soak,
        },
    )
    blockers.extend(identity_blockers)
    blockers.extend(_baseline_authorization_blockers(baseline))
    blockers.extend(_baseline_soak_blockers(baseline, soak))
    blockers.extend(
        _collector_blockers(
            baseline, calibration, profile_calibration, profiling, soak
        )
    )
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
            "profile_calibration": "the immutable profile calibration raw archive regenerated the retained aggregate",
            "hot_path_profiling": "sharded archive, manifest, CPU/allocation artifacts, full invariant proof, and aggregate were independently verified",
            "resource_soak": "zstd archive, manifest, raw runs, host/execution records, calibration applicability, and aggregate were independently verified",
        },
        "baseline": baseline,
        "calibration": calibration,
        "profile_calibration": profile_calibration,
        "hot_path_profiling": profiling,
        "resource_soak": soak,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="fresh Phase 0 baseline JSON")
    parser.add_argument("output", type=Path, help="new receipt path")
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument(
        "--profile-calibration",
        type=Path,
        default=DEFAULT_PROFILE_CALIBRATION,
        help="the immutable calibration retained with the hot-path profile archive",
    )
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
            arguments.profile_calibration,
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
