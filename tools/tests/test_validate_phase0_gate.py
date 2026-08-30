from __future__ import annotations

import io
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools.phase0_collector_identity import EXPECTED_RELEASE_BUILD_CONFIGURATION
from tools.phase0_evidence import (
    CALIBRATION_SCHEMA,
    CALIBRATION_SOURCE_PROVENANCE_SCHEMA,
    EvidenceValidationError,
    PROFILE_SCHEMA,
    _profile_required_candidate_runs,
    extract_tar_stream,
    verify_calibration_evidence,
    verify_profile_evidence,
    verify_resource_soak_evidence,
)
from tools.validate_phase0_gate import (
    GateValidationError,
    PROFILE_SOURCE_PROVENANCE_SCHEMA,
    REQUIRED_CHECKS,
    REQUIRED_DECISION_CANDIDATES,
    REQUIRED_PROFILE_GUARDRAILS,
    REQUIRED_PROFILE_WORKLOADS,
    _baseline_authorization_blockers,
    _baseline_source_identity,
    _baseline_soak_blockers,
    _collector_blockers,
    _identity_blockers,
    _require_baseline_workload_profile,
    build_gate_receipt,
    validate_calibration,
    validate_profiling,
    validate_resource_soak,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_CALIBRATION = (
    REPOSITORY_ROOT / "benchmarks/phase0/calibration/native-linux-2026-08-28-6a64f063/aggregate.json"
)
HISTORICAL_PROFILE_CALIBRATION = (
    REPOSITORY_ROOT
    / "benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/aggregate.json"
)
HISTORICAL_PROFILE = (
    REPOSITORY_ROOT / "benchmarks/phase0/profiling/native-linux-2026-08-27-de2337906/aggregate.json"
)
HISTORICAL_SOAK = (
    REPOSITORY_ROOT / "benchmarks/phase0/soak/native-linux-2026-08-28-6a64f063/aggregate.json"
)

CURRENT_SOAK_CAPSULE_DIGEST = "sha256:" + "c" * 64
CURRENT_SOAK_CAPSULE_BYTES = 123
PROFILE_SOURCE_COMMIT = "a" * 40
PROFILE_SOURCE_TREE = "b" * 40
PROFILE_SOURCE_REF = "refs/heads/fix/phase0-gate-validation"
PROFILE_SOURCE_REF_HEAD = "c" * 40


def collector_identity(name: str, digest_character: str = "1") -> dict[str, object]:
    return {
        "schema_version": "latent.phase0.native-collector.v1",
        "collector": name,
        "executable_digest": "sha256:" + digest_character * 64,
        "executable_bytes": 100,
        "build_configuration": dict(EXPECTED_RELEASE_BUILD_CONFIGURATION),
    }


def tar_bytes(members: list[tuple[str, bytes, str]]) -> io.BytesIO:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, contents, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                info.size = len(contents)
                archive.addfile(info, io.BytesIO(contents))
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "outside"
                archive.addfile(info)
            else:
                raise AssertionError(f"unknown member kind {kind}")
    stream.seek(0)
    return stream


class BaselineSourceIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "sha256": "sha256:" + "1" * 64,
        }

    @patch("tools.validate_phase0_gate.execution_evidence_identity_for_commit")
    def test_different_commit_with_same_canonical_identity_passes(
        self, identity_for_commit: object
    ) -> None:
        source_commit = "c" * 40
        source_tree = "d" * 40
        identity_for_commit.return_value = {
            "commit": source_commit,
            "tree": source_tree,
            "sha256": self.current["sha256"],
        }

        identity = _baseline_source_identity(source_commit, self.current)

        self.assertEqual(identity["commit"], source_commit)
        self.assertEqual(identity["tree"], source_tree)
        identity_for_commit.assert_called_once_with(source_commit)

    @patch("tools.validate_phase0_gate.execution_evidence_identity_for_commit")
    def test_exact_current_commit_still_passes(self, identity_for_commit: object) -> None:
        identity_for_commit.return_value = dict(self.current)

        identity = _baseline_source_identity(self.current["commit"], self.current)

        self.assertEqual(identity, self.current)

    @patch("tools.validate_phase0_gate.execution_evidence_identity_for_commit")
    def test_canonical_identity_mismatch_fails(self, identity_for_commit: object) -> None:
        identity_for_commit.return_value = {
            "commit": "c" * 40,
            "tree": "d" * 40,
            "sha256": "sha256:" + "2" * 64,
        }

        with self.assertRaisesRegex(
            GateValidationError, "execution evidence identity does not match"
        ):
            _baseline_source_identity("c" * 40, self.current)

    @patch("tools.validate_phase0_gate.execution_evidence_identity_for_commit")
    def test_resolution_failure_is_controlled(self, identity_for_commit: object) -> None:
        identity_for_commit.side_effect = EvidenceValidationError("missing commit")

        with self.assertRaisesRegex(
            GateValidationError, "cannot bind fresh baseline.*missing commit"
        ):
            _baseline_source_identity("c" * 40, self.current)

    def test_malformed_commit_fails_before_resolution(self) -> None:
        with self.assertRaisesRegex(
            GateValidationError, "lowercase 40-character Git object ID"
        ):
            _baseline_source_identity("invalid", self.current)


def current_schema_profile() -> dict[str, object]:
    """Build the smallest complete v5 profile receipt accepted by the gate."""

    digest = "sha256:" + "d" * 64
    measurement_identity = {
        "schema_version": "latent.phase0.measurement-identity.v1",
        "artifact": {
            "component_digest": "sha256:" + "e" * 64,
            "component_bytes": 1,
            "capsule_digest": "sha256:" + "f" * 64,
            "capsule_bytes": 1,
        },
        "configuration": {"pool_capacity": 2},
    }
    host_observations = {
        "before": "host-before.json",
        "before_sha256": digest,
        "after": "host-after.json",
        "after_sha256": digest,
        "static_identity": {
            "virtualization": {},
            "allocator": {},
            "cpu_frequency_policy": {},
        },
    }
    collector = collector_identity("phase0-baseline")

    def profile_artifact(fields: tuple[str, ...]) -> dict[str, object]:
        artifact: dict[str, object] = {
            "measurement_identity": json.loads(json.dumps(measurement_identity)),
            "host_observations": json.loads(json.dumps(host_observations)),
        }
        for field in fields:
            artifact[field] = f"{field}.data"
            artifact[f"{field}_sha256"] = digest
        return artifact

    profiles = []
    for workload in sorted(REQUIRED_PROFILE_WORKLOADS):
        profiles.append(
            {
                "workload": workload,
                "scenario_semantics": f"selective {workload} boundary",
                "selected_scenarios": [],
                "collector_identity": json.loads(json.dumps(collector)),
                "composition_identity": json.loads(json.dumps(measurement_identity)),
                "perf": profile_artifact(("data", "report", "inclusive_report")),
                "allocation": profile_artifact(
                    ("data", "report", "leak_report", "compact_contributors")
                ),
                "contributor_attribution": {
                    "categories": {
                        "runtime": {
                            "allocation_calls": 1,
                            "allocation_peak_bytes": 1,
                            "cpu_self_percent": 1.0,
                            "cpu_inclusive_percent": 1.0,
                        }
                    },
                    "totals": {"allocation_calls": 1, "allocation_peak_bytes": 1},
                },
            }
        )

    raw_runs = [
        {
            "measurement_identity": json.loads(json.dumps(measurement_identity)),
            "collector_identity": json.loads(json.dumps(collector)),
            "host_observations": json.loads(json.dumps(host_observations)),
        }
        for _ in range(7)
    ]
    provenance = {
        "schema_version": PROFILE_SOURCE_PROVENANCE_SCHEMA,
        "published_commit": PROFILE_SOURCE_COMMIT,
        "published_tree": PROFILE_SOURCE_TREE,
        "published_source_ref": PROFILE_SOURCE_REF,
        "published_source_ref_head": PROFILE_SOURCE_REF_HEAD,
        "published_commit_reachable_from_ref": True,
        "execution_commit": PROFILE_SOURCE_COMMIT,
        "execution_tree": PROFILE_SOURCE_TREE,
        "execution_commit_matches_published": True,
        "tree_identity_verified": True,
    }
    return {
        "schema_version": PROFILE_SCHEMA,
        "status": "pass",
        "observational_only": True,
        "production_slo": False,
        "cross_platform_claim": False,
        "source_commit": PROFILE_SOURCE_COMMIT,
        "source_tree": PROFILE_SOURCE_TREE,
        "source_provenance": provenance,
        "collector_identity": json.loads(json.dumps(collector)),
        "guardrails": dict(REQUIRED_PROFILE_GUARDRAILS),
        "profiles": profiles,
        "hard_invariants": {
            "canonical_names": sorted(REQUIRED_CHECKS),
            "full_invariant_proof": {
                "raw_results": "full-invariant-proof/raw-results.json",
                "raw_results_sha256": digest,
                "command": "full-invariant-proof/command.json",
                "command_sha256": digest,
                "command_identity": {
                    "source_commit": PROFILE_SOURCE_COMMIT,
                    "source_tree": PROFILE_SOURCE_TREE,
                    "published_source_ref": PROFILE_SOURCE_REF,
                    "published_source_ref_head": PROFILE_SOURCE_REF_HEAD,
                    "execution_commit": PROFILE_SOURCE_COMMIT,
                    "execution_tree": PROFILE_SOURCE_TREE,
                },
                "measurement_identity": json.loads(json.dumps(measurement_identity)),
                "composition_identity": json.loads(json.dumps(measurement_identity)),
                "host_observations": json.loads(json.dumps(host_observations)),
                "collector_identity": json.loads(json.dumps(collector)),
            },
        },
        "candidates": {
            "worker-cell-2w-2c": {
                "run_count": 7,
                "measurement_identity": json.loads(json.dumps(measurement_identity)),
                "collector_identity": json.loads(json.dumps(collector)),
                "raw_runs": raw_runs,
                "representatives": {
                    "warm_echo_p50_micros": 1,
                    "at_capacity_activations_per_second": 1,
                    "fixed_runtime_rss_bytes": 1,
                    "peak_rss_bytes": 1,
                    "post_release_rss_delta_bytes": 0,
                    "peak_threads": 1,
                    "peak_open_sockets": 0,
                    "peak_listening_sockets": 0,
                },
                "calibration_comparison_eligibility": {
                    "status": "reference_equivalent"
                },
                "calibration_comparison": {
                    "warm_echo_p50_micros": {"status": "inside_advisory_band"}
                },
            }
        },
        "decisions": [
            {
                "candidate": candidate,
                "decision": "defer",
                "rationale": "bounded experiment only",
                "handoff": "retain for Phase 1",
            }
            for candidate in sorted(REQUIRED_DECISION_CANDIDATES)
        ],
    }


class Phase0GateEvidenceTests(unittest.TestCase):
    def test_smoke_baseline_can_pass_validation_but_never_authorize(self) -> None:
        self.assertEqual(_baseline_authorization_blockers({"profile": "full"}), [])
        self.assertEqual(
            _baseline_authorization_blockers({"profile": "smoke"}),
            [
                "fresh baseline profile is 'smoke'; Phase 1 authorization "
                "requires 'full'"
            ],
        )

    def test_smoke_workload_cannot_be_relabelled_as_a_full_baseline(self) -> None:
        smoke_sized = {
            "mode": "full",
            "warm_samples": 5,
            "sequence_repetitions": 2,
            "throughput_batches": 2,
            "pool_iterations": 32,
        }
        with self.assertRaisesRegex(
            GateValidationError, "full baseline warm_samples must be at least 40"
        ):
            _require_baseline_workload_profile(smoke_sized, 12)

        full_sized = {
            "mode": "full",
            "warm_samples": 40,
            "sequence_repetitions": 10,
            "throughput_batches": 24,
            "pool_iterations": 2_000,
        }
        with self.assertRaisesRegex(
            GateValidationError,
            "full baseline executable harness must retain at least 12",
        ):
            _require_baseline_workload_profile(full_sized, 3)
        self.assertEqual(_require_baseline_workload_profile(full_sized, 12), "full")

    def test_baseline_and_soak_require_the_same_canonical_measurement_identity(self) -> None:
        toolchain = {
            "rustc": "rustc",
            "cargo": "cargo",
            "rust_target": "x86_64-unknown-linux-gnu",
            "build_profile": "release",
            "wasmtime_version": "wasmtime",
        }
        measurement_identity = {
            "schema_version": "latent.phase0.measurement-identity.v1",
            "artifact": {
                "component_digest": "sha256:" + "a" * 64,
                "component_bytes": 1,
                "capsule_digest": "sha256:" + "b" * 64,
                "capsule_bytes": 2,
            },
            "configuration": {
                "pool_capacity": 2,
                "fuel": 100,
            },
        }
        baseline = {
            "measurement_identity": measurement_identity,
            "toolchain": toolchain,
        }
        soak = {
            "measurement_identity": json.loads(json.dumps(measurement_identity)),
            "configuration": {"environment": toolchain},
        }
        self.assertEqual(_baseline_soak_blockers(baseline, soak), [])

        soak["measurement_identity"]["artifact"]["capsule_digest"] = (
            "sha256:" + "c" * 64
        )
        self.assertEqual(
            _baseline_soak_blockers(baseline, soak),
            [
                "fresh baseline canonical measurement identity does not match "
                "the final resource soak"
            ],
        )

        soak["measurement_identity"] = json.loads(json.dumps(measurement_identity))
        soak["measurement_identity"]["configuration"]["fuel"] = 101
        self.assertEqual(
            _baseline_soak_blockers(baseline, soak),
            [
                "fresh baseline canonical measurement identity does not match "
                "the final resource soak"
            ],
        )

    def current_schema_soak(self) -> dict[str, object]:
        """Upgrade an immutable archive only in memory for gate-schema tests."""

        document = json.loads(HISTORICAL_SOAK.read_text(encoding="utf-8"))
        source_commit = document["source_commit"]
        source_tree = document["source_tree"]
        provenance = {
            "schema_version": "latent.phase0.resource-soak.source-provenance.v1",
            "published_commit": source_commit,
            "published_tree": source_tree,
            "published_source_ref": "refs/heads/fix/phase0-gate-validation",
            "published_source_ref_head": source_commit,
            "published_commit_reachable_from_ref": True,
            "execution_commit": source_commit,
            "execution_tree": source_tree,
            "execution_commit_matches_published": True,
            "tree_identity_verified": True,
        }
        document["source_provenance"] = provenance
        configuration = document["configuration_identity"]
        configuration["collector"] = collector_identity("phase0-soak", "2")
        configuration["capsule_digest"] = CURRENT_SOAK_CAPSULE_DIGEST
        configuration["capsule_bytes"] = CURRENT_SOAK_CAPSULE_BYTES
        configuration["source_identity"].update(
            {
                "published_commit": source_commit,
                "published_tree": source_tree,
                "published_source_ref": provenance["published_source_ref"],
                "published_source_ref_head": provenance["published_source_ref_head"],
                "published_commit_reachable_from_ref": True,
                "execution_commit": source_commit,
                "execution_tree": source_tree,
                "execution_commit_matches_published": True,
                "final_configuration_commit": source_commit,
            }
        )
        for run in document["raw_runs"]:
            source_identity = run["source_identity"]
            source_identity.update(
                {
                    "published_commit": source_commit,
                    "published_tree": source_tree,
                    "published_source_ref": provenance["published_source_ref"],
                    "published_source_ref_head": provenance["published_source_ref_head"],
                    "published_commit_reachable_from_ref": True,
                    "execution_commit": source_commit,
                    "execution_tree": source_tree,
                    "execution_commit_matches_published": True,
                    "tree_identity_verified": True,
                    "final_configuration_commit": source_commit,
                }
            )
            run["artifact"].update(
                {
                    "capsule_digest": CURRENT_SOAK_CAPSULE_DIGEST,
                    "capsule_bytes": CURRENT_SOAK_CAPSULE_BYTES,
                    "collector": collector_identity("phase0-soak", "2"),
                }
            )
        return document

    def test_profile_reverification_preserves_reference_and_experiment_run_counts(self) -> None:
        document = {
            "candidates": {
                "worker-cell-2w-2c": {"run_count": 7},
                "worker-cell-1w-1c": {"run_count": 3},
                "worker-cell-2w-4c": {"run_count": 3},
            }
        }
        self.assertEqual(_profile_required_candidate_runs(document), (3, 7))

        document["candidates"]["worker-cell-2w-4c"]["run_count"] = 4
        with self.assertRaisesRegex(
            EvidenceValidationError, "bounded experiment candidates do not retain one common"
        ):
            _profile_required_candidate_runs(document)

    def test_checked_in_calibration_is_regenerated_from_raw_runs(self) -> None:
        document = verify_calibration_evidence(HISTORICAL_CALIBRATION)
        self.assertEqual(document["status"], "pass")
        self.assertGreaterEqual(document["run_count"], 7)
        self.assertGreater(len(document["metrics"]), 0)

    def test_historical_calibration_fixture_is_integrity_verifiable_but_non_authorizing(self) -> None:
        document = verify_calibration_evidence(HISTORICAL_CALIBRATION)
        self.assertNotEqual(document["schema_version"], CALIBRATION_SCHEMA)
        with self.assertRaisesRegex(GateValidationError, "unexpected calibration schema"):
            validate_calibration(document, str(HISTORICAL_CALIBRATION))

    def test_current_calibration_schema_requires_durable_ref_provenance(self) -> None:
        document = verify_calibration_evidence(HISTORICAL_CALIBRATION)
        document = json.loads(json.dumps(document))
        document["schema_version"] = CALIBRATION_SCHEMA
        document["comparison_method"]["rerun_required_rule"] = (
            "Invalid comparison inputs require a fresh rerun."
        )
        document["comparison_method"].pop("inconclusive_rule")
        for metric in document["metrics"].values():
            comparison = metric.get("comparison")
            if comparison is not None:
                comparison["rerun_required_rule"] = (
                    "Invalid comparison inputs require a fresh rerun."
                )
                comparison.pop("inconclusive_rule")
        document["reference_identity"]["artifact"]["capsule_digest"] = "sha256:" + "a" * 64
        document["reference_identity"]["artifact"]["capsule_bytes"] = 1
        document["reference_identity"]["collector"] = collector_identity(
            "phase0-baseline"
        )
        for run in document["raw_runs"]:
            run["collector_identity"] = collector_identity("phase0-baseline")
        with self.assertRaisesRegex(
            GateValidationError, "lacks the durable-ref schema"
        ):
            validate_calibration(document, str(HISTORICAL_CALIBRATION))

        source_commit = document["source_commit"]
        source_tree = document["source_tree"]
        document["source_provenance"].update(
            {
                "schema_version": CALIBRATION_SOURCE_PROVENANCE_SCHEMA,
                "published_source_ref": "fix/phase0-gate-validation",
                "published_source_ref_head": source_commit,
                "published_commit_reachable_from_ref": True,
                "execution_commit": source_commit,
                "execution_tree": source_tree,
                "execution_commit_matches_published": True,
                "tree_identity_verified": True,
            }
        )
        receipt = validate_calibration(document, str(HISTORICAL_CALIBRATION))
        self.assertEqual(receipt["status"], "pass")

    def test_current_schema_soak_requires_durable_provenance_and_capsule_identity(self) -> None:
        document = self.current_schema_soak()
        self.assertNotIn(
            "tree_identity_verified",
            document["configuration_identity"]["source_identity"],
        )
        receipt, blockers = validate_resource_soak(document, "soak.json")
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(blockers, [])
        self.assertIs(
            receipt["configuration"]["source_identity"]["tree_identity_verified"],
            True,
        )
        self.assertEqual(
            receipt["configuration"]["artifact"]["capsule_digest"],
            CURRENT_SOAK_CAPSULE_DIGEST,
        )
        self.assertEqual(
            receipt["source_provenance"]["published_source_ref"],
            "refs/heads/fix/phase0-gate-validation",
        )

        missing_provenance = self.current_schema_soak()
        del missing_provenance["source_provenance"]
        with self.assertRaisesRegex(GateValidationError, "resource-soak source provenance"):
            validate_resource_soak(missing_provenance, "soak.json")

        missing_capsule = self.current_schema_soak()
        del missing_capsule["configuration_identity"]["capsule_digest"]
        with self.assertRaisesRegex(GateValidationError, "resource-soak capsule digest"):
            validate_resource_soak(missing_capsule, "soak.json")

    def test_current_schema_soak_inherits_only_the_omitted_derived_tree_proof(self) -> None:
        for invalid in (False, None):
            with self.subTest(configuration_tree_identity_verified=invalid):
                document = self.current_schema_soak()
                document["configuration_identity"]["source_identity"][
                    "tree_identity_verified"
                ] = invalid
                with self.assertRaisesRegex(
                    GateValidationError,
                    "resource-soak configuration source provenance source tree was not verified",
                ):
                    validate_resource_soak(document, "soak.json")

        missing_aggregate_proof = self.current_schema_soak()
        del missing_aggregate_proof["source_provenance"]["tree_identity_verified"]
        with self.assertRaisesRegex(
            GateValidationError,
            "resource-soak source provenance source tree was not verified",
        ):
            validate_resource_soak(missing_aggregate_proof, "soak.json")

        missing_raw_proof = self.current_schema_soak()
        del missing_raw_proof["raw_runs"][0]["source_identity"][
            "tree_identity_verified"
        ]
        with self.assertRaisesRegex(
            GateValidationError,
            "resource-soak run-01 source provenance source tree was not verified",
        ):
            validate_resource_soak(missing_raw_proof, "soak.json")

        missing_configuration_tree = self.current_schema_soak()
        del missing_configuration_tree["configuration_identity"]["source_identity"][
            "execution_tree"
        ]
        with self.assertRaisesRegex(
            GateValidationError,
            "resource-soak configuration source provenance execution tree does not equal",
        ):
            validate_resource_soak(missing_configuration_tree, "soak.json")

    def test_current_schema_soak_rejects_mismatched_raw_capsule_and_ref_provenance(self) -> None:
        capsule_mismatch = self.current_schema_soak()
        capsule_mismatch["raw_runs"][0]["artifact"]["capsule_digest"] = "sha256:" + "d" * 64
        with self.assertRaisesRegex(
            GateValidationError, "raw-run artifact capsule_digest differs"
        ):
            validate_resource_soak(capsule_mismatch, "soak.json")

        ref_mismatch = self.current_schema_soak()
        ref_mismatch["raw_runs"][0]["source_identity"]["published_source_ref_head"] = "d" * 40
        with self.assertRaisesRegex(
            GateValidationError, "durable source provenance differs from the aggregate"
        ):
            validate_resource_soak(ref_mismatch, "soak.json")

    def test_identity_blockers_compare_canonical_measurement_and_source_provenance(self) -> None:
        source_commit = "a" * 40
        source_tree = "b" * 40
        canonical = {
            "schema_version": "latent.phase0.measurement-identity.v1",
            "artifact": {
                "component_digest": "sha256:" + "e" * 64,
                "component_bytes": 1,
                "capsule_digest": "sha256:" + "f" * 64,
                "capsule_bytes": 1,
            },
            "configuration": {"pool_capacity": 2},
        }
        different_capsule = json.loads(json.dumps(canonical))
        different_capsule["artifact"]["capsule_digest"] = "sha256:" + "0" * 64
        provenance = {
            "published_commit": source_commit,
            "published_tree": source_tree,
            "published_source_ref": "refs/heads/fix/phase0-gate-validation",
            "published_source_ref_head": source_commit,
            "published_commit_reachable_from_ref": True,
            "execution_commit": source_commit,
            "execution_tree": source_tree,
            "execution_commit_matches_published": True,
            "tree_identity_verified": True,
        }
        evidence = {
            "calibration": {
                "source_commit": source_commit,
                "source_tree": source_tree,
                "measurement_identity": canonical,
            },
            "resource soak": {
                "source_commit": source_commit,
                "source_tree": source_tree,
                "source_provenance": provenance,
                "measurement_identity": different_capsule,
            },
        }
        current = {"sha256": "sha256:" + "1" * 64, "worktree_clean": True}
        execution_identity = {
            "sha256": current["sha256"],
            "commit": source_commit,
            "tree": source_tree,
        }
        with patch(
            "tools.validate_phase0_gate.execution_evidence_identity",
            return_value=execution_identity,
        ):
            identities, blockers = _identity_blockers(current, evidence)
        self.assertIn(
            "resource soak canonical measurement identity does not match calibration",
            blockers,
        )
        self.assertEqual(
            identities["resource soak"]["source_provenance"]["execution_commit"],
            source_commit,
        )

    @unittest.skipUnless(shutil.which("zstd"), "zstd is required for archive integration verification")
    def test_checked_in_calibration_archive_is_lossless(self) -> None:
        archive = HISTORICAL_CALIBRATION.parent / "raw-evidence.tar.zst"
        manifest = HISTORICAL_CALIBRATION.parent / "raw-evidence.manifest.sha256"
        self.assertEqual(
            (HISTORICAL_CALIBRATION.parent / "raw-evidence.tar.zst.sha256").read_text(
                encoding="utf-8"
            ),
            f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  raw-evidence.tar.zst\n",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            extracted = Path(temporary_directory)
            result = subprocess.run(
                ["tar", "--use-compress-program=zstd", "-xf", str(archive), "-C", str(extracted)],
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (extracted / "raw-evidence.manifest.sha256").read_bytes(),
                manifest.read_bytes(),
            )
            checks = subprocess.run(
                ["sha256sum", "--check", "raw-evidence.manifest.sha256"],
                cwd=extracted,
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(checks.returncode, 0, checks.stderr)

    def test_safe_extractor_rejects_path_traversal_and_links(self) -> None:
        for name, contents, kind, expected in (
            ("../outside.json", b"bad", "file", "traversal"),
            ("C:/outside.json", b"bad", "file", "drive-qualified"),
            ("runs/run-01/raw.json", b"bad", "symlink", "prohibited link"),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary_directory:
                destination = Path(temporary_directory) / "extract"
                with self.assertRaisesRegex(EvidenceValidationError, expected):
                    extract_tar_stream(tar_bytes([(name, contents, kind)]), destination, "test archive")

    def test_safe_extractor_rejects_duplicate_normalized_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "extract"
            archive = tar_bytes(
                [
                    ("runs/run-01/raw.json", b"first", "file"),
                    ("./runs/run-01/raw.json", b"second", "file"),
                ]
            )
            with self.assertRaisesRegex(EvidenceValidationError, "duplicate path"):
                extract_tar_stream(archive, destination, "test archive")

    def test_arbitrary_archive_bytes_cannot_substitute_for_raw_soak_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "raw-evidence.tar.zst").write_bytes(b"synthetic evidence")
            (root / "raw-evidence.tar.zst.sha256").write_text(
                "00" * 32 + "  raw-evidence.tar.zst\n", encoding="utf-8"
            )
            (root / "raw-evidence.manifest.sha256").write_text(
                "00" * 32 + "  runs/run-01/raw.json\n", encoding="utf-8"
            )
            (root / "aggregate.json").write_text(
                json.dumps(
                    {
                        "schema_version": "latent.phase0.resource-soak.aggregate.v1",
                        "raw_evidence_archive": {
                            "path": "raw-evidence.tar.zst",
                            "manifest": "raw-evidence.manifest.sha256",
                            "sha256": "sha256:" + "00" * 32,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "README.md").write_text("evidence", encoding="utf-8")
            (root / "SOAK.md").write_text("evidence", encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                verify_resource_soak_evidence(root / "aggregate.json", HISTORICAL_CALIBRATION)

    def test_passing_summary_fields_cannot_authorize_without_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            calibration = root / "calibration.json"
            profile = root / "profile.json"
            soak = root / "soak.json"
            calibration.write_text(
                json.dumps(
                    {
                        "schema_version": "latent.phase0.calibration.v1",
                        "status": "pass",
                        "minimum_required_run_count": 7,
                        "raw_runs": [],
                    }
                ),
                encoding="utf-8",
            )
            profile.write_text(
                json.dumps({"schema_version": "latent.phase0.hot-path.aggregate.v3", "status": "pass"}),
                encoding="utf-8",
            )
            soak.write_text(
                json.dumps({"schema_version": "latent.phase0.resource-soak.aggregate.v1", "status": "pass"}),
                encoding="utf-8",
            )
            with self.assertRaises(GateValidationError):
                build_gate_receipt({}, "placeholder-baseline.json", calibration, profile, soak)

    def test_historical_profile_fixture_is_not_gate_eligible_under_v5_schema(self) -> None:
        document = json.loads(HISTORICAL_PROFILE.read_text(encoding="utf-8"))
        self.assertNotEqual(document["schema_version"], PROFILE_SCHEMA)
        with self.assertRaisesRegex(GateValidationError, "unexpected hot-path profile schema"):
            validate_profiling(document, str(HISTORICAL_PROFILE))

    def test_profile_receipt_propagates_validated_durable_source_provenance(self) -> None:
        document = current_schema_profile()
        receipt = validate_profiling(document, "profiling.json")
        self.assertEqual(
            receipt["source_provenance"]["published_source_ref"],
            PROFILE_SOURCE_REF,
        )
        self.assertEqual(
            receipt["source_provenance"]["execution_commit"],
            PROFILE_SOURCE_COMMIT,
        )

        execution_identity = {
            "sha256": "sha256:" + "1" * 64,
            "commit": PROFILE_SOURCE_COMMIT,
            "tree": PROFILE_SOURCE_TREE,
        }
        current = {**execution_identity, "worktree_clean": True}
        with patch(
            "tools.validate_phase0_gate.execution_evidence_identity",
            return_value=execution_identity,
        ):
            identities, blockers = _identity_blockers(
                current, {"hot-path profiling": receipt}
            )
        self.assertEqual(blockers, [])
        self.assertEqual(
            identities["hot-path profiling"]["source_provenance"]["execution_commit"],
            PROFILE_SOURCE_COMMIT,
        )

    def test_profile_rejects_mismatched_execution_provenance_and_full_proof(self) -> None:
        provenance_mismatch = current_schema_profile()
        provenance_mismatch["source_provenance"]["execution_commit"] = "d" * 40
        with self.assertRaisesRegex(
            GateValidationError,
            "execution commit does not equal the published source commit",
        ):
            validate_profiling(provenance_mismatch, "profiling.json")

        proof_mismatch = current_schema_profile()
        proof_mismatch["hard_invariants"]["full_invariant_proof"]["command_identity"][
            "execution_commit"
        ] = "d" * 40
        with self.assertRaisesRegex(
            GateValidationError,
            "full-invariant command identity differs for execution_commit",
        ):
            validate_profiling(proof_mismatch, "profiling.json")

    def test_fully_current_receipt_authorizes_and_stale_profile_calibration_blocks_gate(self) -> None:
        """A separately verified profile calibration must still match the current tree.

        The verifier stubs deliberately represent already checksummed and
        regenerated evidence.  The regression isolates the public gate
        behavior: the optional ``--profile-calibration`` input cannot bypass
        canonical execution-identity binding merely because the profile
        archive references its checksum.
        """

        current_digest = "sha256:" + "1" * 64
        stale_digest = "sha256:" + "2" * 64
        current_commit = "a" * 40
        current_tree = "b" * 40
        stale_commit = "c" * 40
        stale_tree = "d" * 40
        calibration_path = Path("calibration.json")
        profile_calibration_path = Path("profile-calibration.json")
        profiling_path = Path("profiling.json")
        soak_path = Path("soak.json")
        calibration_document = {"archive_checksum_verified": True}
        profile_calibration_document = {"archive_checksum_verified": True}
        profiling_document = {"archive_checksum_verified": True}
        soak_document = {"archive_checksum_verified": True}

        configuration = {
            "pool_capacity": 2,
            "pool_queue_capacity": 4,
            "runtime_workers": 2,
            "prepared_cache_enabled": True,
            "wasmtime_instance_allocator": "on_demand",
            "wasmtime_copy_on_write_images": True,
        }
        toolchain = {
            "rustc": "rustc",
            "cargo": "cargo",
            "rust_target": "x86_64-unknown-linux-gnu",
            "build_profile": "release",
            "wasmtime_version": "wasmtime",
        }
        baseline_receipt = {
            "profile": "full",
            "fixture": {"component_digest": "sha256:" + "e" * 64},
            "configuration": configuration,
            "toolchain": toolchain,
            "measurement_identity": {
                "schema_version": "latent.phase0.measurement-identity.v1",
                "artifact": {
                    "component_digest": "sha256:" + "e" * 64,
                    "component_bytes": 1,
                    "capsule_digest": "sha256:" + "f" * 64,
                    "capsule_bytes": 2,
                },
                "configuration": configuration,
            },
            "collector_identity": collector_identity("phase0-baseline"),
        }
        soak_receipt = {
            "source_commit": current_commit,
            "source_tree": current_tree,
            "measurement_identity": json.loads(
                json.dumps(baseline_receipt["measurement_identity"])
            ),
            "configuration": {
                "artifact": {"component_digest": "sha256:" + "e" * 64, "component_bytes": 1},
                "config": configuration,
                "environment": toolchain,
            },
            "collector_identity": collector_identity("phase0-soak", "2"),
        }
        calibration_receipt = {
            "source_commit": current_commit,
            "source_tree": current_tree,
            "collector_identity": collector_identity("phase0-baseline"),
        }
        profile_calibration_receipt = {
            "source_commit": current_commit,
            "source_tree": current_tree,
            "collector_identity": collector_identity("phase0-baseline"),
        }
        profiling_receipt = {
            "source_commit": current_commit,
            "source_tree": current_tree,
            "collector_identity": collector_identity("phase0-baseline"),
        }
        current_identity = {
            "sha256": current_digest,
            "worktree_clean": True,
            "commit": current_commit,
            "tree": current_tree,
        }

        def verified_calibration(path: Path) -> dict[str, bool]:
            if path == calibration_path:
                return calibration_document
            self.assertEqual(path, profile_calibration_path)
            return profile_calibration_document

        def validated_calibration(document: dict[str, bool], _path: str) -> dict[str, str]:
            if document is calibration_document:
                return calibration_receipt
            self.assertIs(document, profile_calibration_document)
            return profile_calibration_receipt

        def evidence_identity(commit: str, tree: str) -> dict[str, str]:
            if (commit, tree) == (stale_commit, stale_tree):
                return {"sha256": stale_digest}
            self.assertEqual((commit, tree), (current_commit, current_tree))
            return {"sha256": current_digest}

        with (
            patch(
                "tools.validate_phase0_gate.verify_calibration_evidence",
                side_effect=verified_calibration,
            ),
            patch(
                "tools.validate_phase0_gate.verify_profile_evidence",
                return_value=profiling_document,
            ) as verify_profile,
            patch(
                "tools.validate_phase0_gate.verify_resource_soak_evidence",
                return_value=soak_document,
            ),
            patch(
                "tools.validate_phase0_gate.current_execution_evidence_identity",
                return_value=current_identity,
            ),
            patch(
                "tools.validate_phase0_gate.validate_baseline",
                return_value=baseline_receipt,
            ),
            patch(
                "tools.validate_phase0_gate.validate_calibration",
                side_effect=validated_calibration,
            ),
            patch(
                "tools.validate_phase0_gate.validate_profiling",
                return_value=profiling_receipt,
            ),
            patch(
                "tools.validate_phase0_gate.validate_resource_soak",
                return_value=(soak_receipt, []),
            ),
            patch(
                "tools.validate_phase0_gate.execution_evidence_identity",
                side_effect=evidence_identity,
            ),
        ):
            authorized = build_gate_receipt(
                {},
                "baseline.json",
                calibration_path,
                profiling_path,
                soak_path,
                profile_calibration_path,
            )
            self.assertEqual(authorized["authorization_status"], "authorized")
            self.assertTrue(authorized["phase1_authorized"])
            self.assertEqual(authorized["blockers"], [])
            self.assertFalse(authorized["phase1_api_compatible"])

            profile_calibration_receipt["source_commit"] = stale_commit
            profile_calibration_receipt["source_tree"] = stale_tree
            receipt = build_gate_receipt(
                {},
                "baseline.json",
                calibration_path,
                profiling_path,
                soak_path,
                profile_calibration_path,
            )

        self.assertEqual(verify_profile.call_count, 2)
        verify_profile.assert_called_with(profiling_path, profile_calibration_path)
        self.assertEqual(receipt["authorization_status"], "blocked")
        self.assertFalse(receipt["phase1_authorized"])
        self.assertEqual(
            receipt["blockers"],
            [
                "profile calibration execution evidence identity does not match "
                "the current executable implementation"
            ],
        )
        self.assertEqual(
            receipt["execution_evidence"]["retained"]["profile calibration"]["sha256"],
            stale_digest,
        )

    @unittest.skipUnless(shutil.which("zstd"), "zstd is required for archive integration verification")
    def test_historical_calibration_and_soak_archives_are_verified_but_profile_is_not_gate_eligible(self) -> None:
        calibration = verify_calibration_evidence(HISTORICAL_CALIBRATION)
        profile_calibration = verify_calibration_evidence(HISTORICAL_PROFILE_CALIBRATION)
        soak = verify_resource_soak_evidence(HISTORICAL_SOAK, HISTORICAL_CALIBRATION)
        self.assertEqual(calibration["status"], "pass")
        self.assertEqual(profile_calibration["status"], "pass")
        self.assertEqual(soak["status"], "pass")
        with self.assertRaisesRegex(EvidenceValidationError, "unexpected profiling schema"):
            verify_profile_evidence(HISTORICAL_PROFILE, HISTORICAL_PROFILE_CALIBRATION)


if __name__ == "__main__":
    unittest.main()
