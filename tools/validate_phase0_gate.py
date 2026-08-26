#!/usr/bin/env python3
"""Validate a Phase 0 baseline as a completion-gate receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

BASELINE_SCHEMA = "latent.phase0.baseline.v2"
GATE_SCHEMA = "latent.phase0.gate.v1"
REFERENCE_EVIDENCE = "benchmarks/phase0/raw-results.json"

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
REQUIRED_OUTCOMES = frozenset(
    {"success", "domain_error", "trap", "timeout", "cancelled", "resource_exhausted"}
)


class GateValidationError(ValueError):
    """Raised when machine-readable Phase 0 evidence cannot authorize the gate."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateValidationError(message)


def validate_baseline(document: dict[str, Any], baseline_path: str) -> dict[str, Any]:
    """Validate required issue-25 evidence and return a machine-readable receipt."""

    _require(
        document.get("schema_version") == BASELINE_SCHEMA,
        "unexpected Phase 0 baseline schema",
    )
    _require(document.get("status") == "pass", "Phase 0 baseline did not pass")
    _require(
        document.get("production_ready") is False,
        "baseline must remain explicitly non-production",
    )
    _require(
        document.get("phase1_api_compatible") is False,
        "Phase 0 spike must remain explicitly non-Phase-1-compatible",
    )

    checks = {
        check.get("name"): check
        for check in document.get("checks", [])
        if isinstance(check, dict) and isinstance(check.get("name"), str)
    }
    missing = sorted(REQUIRED_CHECKS - checks.keys())
    failed = sorted(
        name
        for name in REQUIRED_CHECKS
        if name in checks and checks[name].get("passed") is not True
    )
    _require(
        not missing and not failed,
        f"required Phase 0 checks missing={missing} failed={failed}",
    )

    observed_outcomes = {
        sample.get("outcome", {}).get("name")
        for sample in document.get("activation_samples", [])
        if isinstance(sample, dict) and isinstance(sample.get("outcome"), dict)
    }
    missing_outcomes = sorted(REQUIRED_OUTCOMES - observed_outcomes)
    _require(
        not missing_outcomes,
        f"required terminal outcomes were not observed: {missing_outcomes}",
    )

    harness = document.get("executable_harness")
    _require(isinstance(harness, dict), "real executable harness evidence is missing")
    success_samples = harness.get("samples", [])
    failure_samples = harness.get("failure_recovery_samples", [])
    _require(bool(success_samples), "real executable harness produced no success samples")
    _require(bool(failure_samples), "real executable harness produced no failure/recovery samples")
    _require(
        all(isinstance(sample, dict) for sample in success_samples),
        "real executable success samples are malformed",
    )
    _require(
        all(sample.get("shutdown_clean") is True for sample in success_samples),
        "real executable success sample did not shut down cleanly",
    )
    _require(
        all(sample.get("topology_unchanged") is True for sample in success_samples),
        "real executable success sample changed configured topology",
    )

    return {
        "schema_version": GATE_SCHEMA,
        "status": "pass",
        "profile": document.get("config", {}).get("mode"),
        "baseline_schema_version": document["schema_version"],
        "baseline_path": baseline_path,
        "reference_evidence_path": REFERENCE_EVIDENCE,
        "required_checks_passed": len(REQUIRED_CHECKS),
        "observed_terminal_outcomes": sorted(REQUIRED_OUTCOMES),
        "executable_e2e": "passed",
        "production_ready": False,
        "phase1_api_compatible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    document = json.loads(args.baseline.read_text(encoding="utf-8"))
    receipt = validate_baseline(document, str(args.baseline))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
