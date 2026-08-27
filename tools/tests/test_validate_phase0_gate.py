from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from tools.validate_phase0_gate import (
    BASELINE_SCHEMA,
    CALIBRATION_SCHEMA,
    PROFILE_SCHEMA,
    REQUIRED_CHECKS,
    REQUIRED_DECISION_CANDIDATES,
    REQUIRED_PROFILE_GUARDRAILS,
    REQUIRED_PROFILE_WORKLOADS,
    REQUIRED_SCENARIO_OUTCOMES,
    SOAK_SCHEMA,
    GateValidationError,
    build_gate_receipt,
)


def passing_baseline() -> dict:
    return {
        "schema_version": BASELINE_SCHEMA,
        "status": "pass",
        "production_ready": False,
        "phase1_api_compatible": False,
        "config": {"mode": "smoke", "pool_capacity": 2, "pool_queue_capacity": 4, "runtime_workers": 2},
        "checks": [{"name": name, "passed": True} for name in sorted(REQUIRED_CHECKS)],
        "activation_samples": [
            {"scenario": scenario, "outcome": {"name": outcome}}
            for scenario, outcome in sorted(REQUIRED_SCENARIO_OUTCOMES)
        ],
        "executable_harness": {
            "samples": [
                {"shutdown_clean": True, "topology_unchanged": True},
                {"shutdown_clean": True, "topology_unchanged": True},
                {"shutdown_clean": True, "topology_unchanged": True},
            ],
            "failure_recovery_samples": [
                {
                    "scenario": scenario,
                    "expected_outcome": outcome,
                    "raw_result": {
                        "outcome": outcome,
                        "shutdown": {"clean": True},
                        "topology": {"unchanged": True},
                    },
                }
                for scenario, outcome in (
                    ("trap", "trap"),
                    ("timeout", "timeout"),
                    ("trap_then_recovery", "success"),
                )
            ],
        },
        "activation_throughput": {
            "at_capacity": {
                "maximum_observed_active_leases": 2,
                "maximum_observed_queue_depth": 0,
            },
            "bounded_queue_saturation": {
                "maximum_observed_active_leases": 2,
                "maximum_observed_queue_depth": 4,
                "queued_acquire_wait_micros": {"samples": 1},
            },
        },
    }


def passing_calibration() -> dict:
    return {
        "schema_version": CALIBRATION_SCHEMA,
        "status": "pass",
        "observational_only": True,
        "production_slo": False,
        "cross_machine_claim": False,
        "minimum_required_run_count": 7,
        "run_count": 7,
        "raw_runs": [{"run": f"run-{index:02d}", "status": "pass"} for index in range(1, 8)],
        "hard_invariants": {
            "all_runs_passed": True,
            "performance_runs_excluded": 0,
            "checks_passed_in_every_run": sorted(REQUIRED_CHECKS),
        },
        "source_provenance": {"tree_identity_verified": True},
        "source_commit": "calibration-commit",
        "source_tree": "calibration-tree",
    }


def passing_profile() -> dict:
    return {
        "schema_version": PROFILE_SCHEMA,
        "status": "pass",
        "observational_only": True,
        "production_slo": False,
        "cross_platform_claim": False,
        "guardrails": dict(REQUIRED_PROFILE_GUARDRAILS),
        "profiles": [{"workload": workload} for workload in sorted(REQUIRED_PROFILE_WORKLOADS)],
        "decisions": [
            {
                "candidate": candidate,
                "decision": "defer",
                "rationale": "requires Phase 1 evidence",
                "handoff": "#9",
            }
            for candidate in sorted(REQUIRED_DECISION_CANDIDATES)
        ],
        "hard_invariants": {
            "canonical_names": sorted(REQUIRED_CHECKS),
            "full_invariant_proof": {"raw_results": "full-invariant-proof/raw-results.json"},
        },
        "source_commit": "profile-commit",
        "source_tree": "profile-tree",
    }


def passing_soak(directory: Path) -> dict:
    archive = directory / "raw-evidence.tar.zst"
    archive.write_bytes(b"retained raw soak evidence")
    (directory / "raw-evidence.manifest.sha256").write_text("manifest\n", encoding="utf-8")
    labels = ["run-01", "run-02", "run-03"]
    return {
        "schema_version": SOAK_SCHEMA,
        "status": "pass",
        "observational_only": True,
        "production_slo": False,
        "cross_machine_claim": False,
        "minimum_required_run_count": 3,
        "run_count": 3,
        "hard_invariants": {"all_runs_passed": True},
        "raw_runs": [
            {
                "label": label,
                "schema_version": "latent.phase0.resource-soak.run.v1",
                "source_identity": {"tree_identity_verified": True},
            }
            for label in labels
        ],
        "workload": {
            label: {
                "warmup_activations": 1_000,
                "normal_measured_activations": 100_000,
                "saturation_batch_counts": {"at_capacity": 100, "bounded_queue_saturation": 100},
            }
            for label in labels
        },
        "raw_evidence_archive": {
            "path": archive.name,
            "manifest": "raw-evidence.manifest.sha256",
            "sha256": "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest(),
        },
        "evidence_completeness": {"status": "pass"},
        "calibration_noise": {"applicability": {"status": "pass"}},
        "file_descriptors": {"status": "pass"},
        "source_commit": "soak-commit",
        "source_tree": "soak-tree",
    }


class Phase0GateValidationTests(unittest.TestCase):
    def build_receipt(self, soak: dict, soak_path: Path) -> dict:
        return build_gate_receipt(
            passing_baseline(),
            "baseline.json",
            passing_calibration(),
            "calibration.json",
            passing_profile(),
            "profiling.json",
            soak,
            soak_path,
        )

    def test_complete_evidence_authorizes_phase1_without_promoting_the_spike(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            receipt = self.build_receipt(passing_soak(directory), directory / "aggregate.json")

        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(receipt["authorization_status"], "authorized")
        self.assertEqual(receipt["baseline"]["required_checks_passed"], len(REQUIRED_CHECKS))
        self.assertFalse(receipt["production_ready"])
        self.assertFalse(receipt["phase1_api_compatible"])

    def test_missing_or_duplicate_baseline_checks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            baseline = passing_baseline()
            baseline["checks"].pop()
            with self.assertRaisesRegex(GateValidationError, "baseline hard checks"):
                build_gate_receipt(
                    baseline,
                    "baseline.json",
                    passing_calibration(),
                    "calibration.json",
                    passing_profile(),
                    "profiling.json",
                    passing_soak(directory),
                    directory / "aggregate.json",
                )

            baseline = passing_baseline()
            baseline["checks"].append(copy.deepcopy(baseline["checks"][0]))
            with self.assertRaisesRegex(GateValidationError, "baseline hard checks"):
                build_gate_receipt(
                    baseline,
                    "baseline.json",
                    passing_calibration(),
                    "calibration.json",
                    passing_profile(),
                    "profiling.json",
                    passing_soak(directory),
                    directory / "aggregate.json",
                )

    def test_incomplete_soak_is_a_blocker_not_a_passing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            soak = passing_soak(directory)
            soak["status"] = "inconclusive"
            soak["evidence_completeness"]["status"] = "incomplete"
            soak["calibration_noise"]["applicability"]["status"] = "inconclusive"
            soak["file_descriptors"]["status"] = "incomplete"
            receipt = self.build_receipt(soak, directory / "aggregate.json")

        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(receipt["authorization_status"], "blocked")
        self.assertEqual(len(receipt["blockers"]), 4)

    def test_missing_guardrail_or_changed_archive_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            profile = passing_profile()
            profile["guardrails"]["fresh_store_per_invocation"] = False
            with self.assertRaisesRegex(GateValidationError, "fresh_store_per_invocation"):
                build_gate_receipt(
                    passing_baseline(),
                    "baseline.json",
                    passing_calibration(),
                    "calibration.json",
                    profile,
                    "profiling.json",
                    passing_soak(directory),
                    directory / "aggregate.json",
                )

            soak = passing_soak(directory)
            (directory / "raw-evidence.tar.zst").write_bytes(b"modified evidence")
            with self.assertRaisesRegex(GateValidationError, "archive digest"):
                self.build_receipt(soak, directory / "aggregate.json")


if __name__ == "__main__":
    unittest.main()
