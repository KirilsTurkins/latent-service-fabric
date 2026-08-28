from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR = ROOT / "tools" / "aggregate_phase0_resource_soak.py"
RUNNER = ROOT / "tools" / "run_phase0_resource_soak.sh"
CALIBRATION = (
    ROOT
    / "benchmarks"
    / "phase0"
    / "calibration"
    / "native-linux-2026-08-28-6a64f063"
    / "aggregate.json"
)
CHECKED_IN_SOAK = (
    ROOT
    / "benchmarks"
    / "phase0"
    / "soak"
    / "native-linux-2026-08-28-6a64f063"
)
SOURCE_COMMIT = "a" * 40
SOURCE_TREE = "b" * 40
CHECKS = {
    "native_linux_process_resource_probes_are_available",
    "prepared_cache_is_fixed_and_bounded",
    "every_completed_batch_returns_logical_resources_to_zero",
    "fresh_store_outcomes_and_cause_specific_recovery_pass",
    "real_at_capacity_batches_reach_exact_pool_capacity",
    "real_bounded_queue_batches_reach_exact_pool_and_queue_capacity",
    "post_release_returns_all_logical_resources_to_zero",
    "runtime_shutdown_returns_to_process_baseline",
}


def sample(index: int, phase: str, run_offset: int) -> dict[str, object]:
    value = run_offset + index
    return {
        "phase": phase,
        "batch_kind": "mixed_success_failure_recovery",
        "batch_index": index,
        "normal_measured_activations_completed": max(0, (index - 1) * 1_000),
        "total_activation_count": index * 1_000,
        "process": {
            "offset_micros": index * 10,
            "process_count": 1,
            "child_process_count": 0,
            "thread_count": 3,
            "file_descriptor_count": 5,
            "open_socket_count": 0,
            "listening_socket_count": 0,
            "rss_bytes": 17_000_000 + value,
            "virtual_memory_bytes": 231_000_000 + value,
            "pss_bytes": 12_000_000 + value,
            "private_bytes": 11_000_000 + value,
            "probe_notes": [],
        },
        "pool": {
            "capacity": 2,
            "available": 2,
            "queue_depth": 0,
            "active_leases": 0,
            "quarantined": 0,
        },
        "runner": {
            "active_cancellation_registrations": 0,
            "running_invocations": 0,
            "total_invocations": index * 1_000,
            "released_cells": index * 1_000,
            "quarantined_cells": 0,
            "disposition_failures": 0,
        },
        "backend_resources": {
            "active_invocations": 0,
            "live_stores": 0,
            "live_host_states": 0,
            "live_component_instances": 0,
            "live_temporary_buffers": 0,
            "live_cancellation_probes": 0,
            "stores_created": index * 1_000,
        },
        "prepared_cache": {
            "entries": 1,
            "source_bytes": 100,
            "maximum_entries": 1,
            "maximum_source_bytes": 65_536,
        },
        "backend_timing_store": {"entries": 0, "maximum_entries": 256},
        "retained_log_entries_after_clear": 0,
        "observed_runtime_workers": 2,
        "invariant_passed": True,
    }


def raw_document(run_index: int) -> dict[str, object]:
    warmup_batches = 1
    measured_batches = 100
    saturation_batches = 10
    completed_batches = warmup_batches + measured_batches + saturation_batches * 2
    samples = [sample(0, "after_prepare", run_index * 100)]
    for index in range(1, completed_batches + 1):
        phase = "warmup" if index <= warmup_batches else "measured"
        samples.append(sample(index, phase, run_index * 100))
    for value in samples:
        index = int(value["batch_index"])
        normal_completed = min(max(0, index - warmup_batches) * 1_000, 100_000)
        value["normal_measured_activations_completed"] = normal_completed
        value["total_activation_count"] = (
            1_000 + normal_completed + (normal_completed // 10_000) * 8
            if index
            else 0
        )
    post_release = copy.deepcopy(samples[-1])
    post_release["phase"] = "post_release"
    post_release["batch_index"] = completed_batches + 1
    post_release["prepared_cache"] = {
        "entries": 0,
        "source_bytes": 0,
        "maximum_entries": 1,
        "maximum_source_bytes": 65_536,
    }
    post_release["process"]["file_descriptor_count"] = 4
    scenario_counts = {
        "success": 100_800,
        "domain_error": 100,
        "trap": 100,
        "timeout": 100,
        "cancellation": 100,
        "memory_pressure": 100,
        "recovery_after_domain_error": 100,
        "recovery_after_trap": 100,
        "recovery_after_timeout": 100,
        "recovery_after_cancellation": 100,
        "recovery_after_memory_pressure": 100,
    }
    return {
        "schema_version": "latent.phase0.resource-soak.run.v1",
        "status": "pass",
        "test_only": False,
        "profile": "native_linux_resource_soak",
        "run_index": run_index,
        "command": ["phase0-soak", "--test-fixture-command"],
        "source_identity": {
            "published_commit": SOURCE_COMMIT,
            "published_tree": SOURCE_TREE,
            "execution_commit": SOURCE_COMMIT,
            "execution_tree": SOURCE_TREE,
            "tree_identity_verified": True,
            "final_configuration_commit": SOURCE_COMMIT,
        },
        "environment": {
            "operating_system": "linux",
            "architecture": "x86_64",
            "kernel": "Linux native-test 1.0 x86_64",
            "cpu_model": "test CPU",
            "logical_cpu_count": 4,
            "total_memory_bytes": 16_000_000_000,
            "rustc": "rustc test",
            "cargo": "cargo test",
            "rust_target": "x86_64-unknown-linux-gnu",
            "build_profile": "release",
            "wasmtime_version": "47.0.3 (workspace pin)",
            "allocator_statistics": {"available": False, "method": "not_collected"},
            "native_linux_validation": {
                "operating_system": "linux",
                "wsl_detected": False,
                "container_kind": "none",
                "virtualization_kind": "none",
                "proc_probe_available": True,
            },
        },
        "artifact": {
            "component_digest": "sha256:" + "c" * 64,
            "component_bytes": 100,
        },
        "config": {
            "warmup_activations": 1_000,
            "measured_activations": 100_000,
            "batch_size": 1_000,
            "saturation_every_batches": 10,
            "pool_capacity": 2,
            "pool_queue_capacity": 4,
            "runtime_workers": 2,
            "fuel": 1_000_000_000_000,
            "memory_bytes": 16 * 1024 * 1024,
            "memory_pressure_bytes": 4 * 1024 * 1024,
            "timeout_ms": 25,
            "cancel_after_ms": 5,
            "prepared_cache_enabled": True,
            "wasmtime_instance_allocator": "on_demand",
            "wasmtime_copy_on_write_images": True,
            "component_maximum_bytes": 64 * 1024 * 1024,
            "prepared_cache_maximum_entries": 1,
            "prepared_cache_maximum_bytes": 64 * 1024 * 1024,
            "invocation_log_maximum_entries": 64,
            "invocation_log_maximum_bytes": 64 * 1024,
            "retained_log_maximum_entries": 64,
            "retained_log_maximum_bytes": 64 * 1024,
            "test_mode": False,
        },
        "workload": {
            "warmup_activations": 1_000,
            "normal_measured_activations": 100_000,
            "saturation_activations": 80,
            "batch_invariants_checked": completed_batches,
            "scenario_counts": scenario_counts,
            "saturation_batch_counts": {
                "at_capacity": saturation_batches,
                "bounded_queue_saturation": saturation_batches,
            },
        },
        "resource_samples": samples,
        "saturation_observations": [
            {
                "mode": "at_capacity",
                "activations": 2,
                "maximum_observed_active_leases": 2,
                "maximum_observed_queue_depth": 0,
            }
            for _ in range(saturation_batches)
        ]
        + [
            {
                "mode": "bounded_queue_saturation",
                "activations": 6,
                "maximum_observed_active_leases": 2,
                "maximum_observed_queue_depth": 4,
            }
            for _ in range(saturation_batches)
        ],
        "post_release": post_release,
        "process_before_runtime": {
            **copy.deepcopy(samples[0]["process"]),
            "offset_micros": 0,
            "thread_count": 1,
            "file_descriptor_count": 4,
        },
        "process_after_warmup": copy.deepcopy(samples[warmup_batches]["process"]),
        "post_shutdown": {
            "observed_runtime_workers": 0,
            "process": {
                **copy.deepcopy(post_release["process"]),
                "thread_count": 1,
            },
        },
        "checks": [
            {"name": name, "passed": True, "expected": "test", "observed": "test"}
            for name in sorted(CHECKS)
        ],
    }


def host_document(phase: str, run_index: int) -> dict[str, object]:
    return {
        "schema_version": "latent.phase0.resource-soak.host-observation.v1",
        "phase": phase,
        "run_index": run_index,
        "native_linux_reference": True,
        "host": {
            "operating_system": "linux",
            "architecture": "x86_64",
            "cpu_model": "test CPU",
            "logical_cpu_count": 4,
            "total_memory_bytes": 16_000_000_000,
            "kernel": "Linux native-test 1.0 x86_64",
            "virtualization": {
                "systemd_detect_virt": "none",
                "systemd_detect_virt_container": "none",
                "systemd_detect_virt_vm": "none",
                "wsl_detected": False,
            }
        },
        "allocator": {
            "source_global_allocator_lookup": "completed",
            "source_global_allocator_matches": [],
            "ld_preload": "unset",
            "malloc_conf": "unset",
            "observation": "test allocator",
        },
        "source_identity": {
            "published_commit": SOURCE_COMMIT,
            "published_tree": SOURCE_TREE,
            "execution_commit": SOURCE_COMMIT,
            "execution_tree": SOURCE_TREE,
            "tree_identity_verified": True,
        },
    }


def calibration_document() -> dict[str, object]:
    raw = raw_document(1)
    environment = raw["environment"]
    config = raw["config"]
    host = host_document("before", 1)
    return {
        "schema_version": "latent.phase0.calibration.v1",
        "status": "pass",
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "reference_identity": {
            "artifact": raw["artifact"],
            "config": {
                key: config[key]
                for key in (
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
            },
            "environment": {
                key: environment[key]
                for key in (
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
            },
        },
        "host_observations": {
            "runs": [
                {
                    "virtualization": host["host"]["virtualization"],
                    "allocator": host["allocator"],
                }
            ]
        },
        "metrics": {
            "process_peak_rss_bytes": {
                "comparison": {"advisory_noise_band": 1_000_000, "reference_median": 17_000_000}
            },
            "process_peak_virtual_memory_bytes": {
                "comparison": {"advisory_noise_band": 1_000_000, "reference_median": 231_000_000}
            },
        },
    }


class Phase0ResourceSoakAggregateTests(unittest.TestCase):
    def test_runner_validates_fixtures_in_the_isolated_soak_target_root(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            'CARGO_TARGET_DIR="$TARGET_ROOT" tools/validate_contracts.sh', runner
        )

    def make_archive(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        archive = Path(temporary.name)
        (archive / "calibration.json").write_text(
            json.dumps(calibration_document()), encoding="utf-8"
        )
        for index in range(1, 4):
            run = archive / "runs" / f"run-{index:02d}"
            run.mkdir(parents=True)
            (run / "raw.json").write_text(
                json.dumps(raw_document(index)), encoding="utf-8"
            )
            for phase in ("before", "after"):
                (run / f"host-{phase}.json").write_text(
                    json.dumps(host_document(phase, index)), encoding="utf-8"
                )
            (run / "execution-status.json").write_text(
                json.dumps(
                    {
                        "schema_version": "latent.phase0.resource-soak.execution-status.v1",
                        "run_index": index,
                        "exit_code": 0,
                        "source_commit": SOURCE_COMMIT,
                        "source_tree": SOURCE_TREE,
                        "execution_commit": SOURCE_COMMIT,
                        "execution_tree": SOURCE_TREE,
                    }
                ),
                encoding="utf-8",
            )
        return temporary, archive

    def aggregate(self, archive: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(AGGREGATOR),
                "aggregate",
                "--runs-directory",
                str(archive / "runs"),
                "--output-json",
                str(archive / "aggregate.json"),
                "--output-report",
                str(archive / "SOAK.md"),
                "--source-commit",
                SOURCE_COMMIT,
                "--source-tree",
                SOURCE_TREE,
                "--calibration",
                str(archive / "calibration.json"),
            ],
            check=False,
            text=True,
            capture_output=True,
        )

    @staticmethod
    def update_all_raw_documents(archive: Path, update: object) -> None:
        for index in range(1, 4):
            path = archive / "runs" / f"run-{index:02d}" / "raw.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            update(document)
            path.write_text(json.dumps(document), encoding="utf-8")

    @staticmethod
    def update_all_host_documents(archive: Path, update: object) -> None:
        for index in range(1, 4):
            for phase in ("before", "after"):
                path = archive / "runs" / f"run-{index:02d}" / f"host-{phase}.json"
                document = json.loads(path.read_text(encoding="utf-8"))
                update(document)
                path.write_text(json.dumps(document), encoding="utf-8")

    def test_aggregates_three_full_soaks_and_uses_calibrated_rss_noise(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            aggregate = json.loads((archive / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["status"], "pass")
            self.assertEqual(aggregate["run_count"], 3)
            self.assertEqual(aggregate["metrics"]["rss_bytes"]["decision"]["status"], "pass")
            self.assertEqual(aggregate["file_descriptors"]["status"], "pass")
            self.assertEqual(len(aggregate["raw_runs"]), 3)
            report = (archive / "SOAK.md").read_text(encoding="utf-8")
            self.assertIn("issue #38 host/configuration identity is strictly matched", report)
            self.assertIn("## Conclusion", report)

    def test_checked_in_resource_soak_archive_is_lossless(self) -> None:
        self.assertIsNotNone(shutil.which("zstd"), "zstd is required for evidence integrity")
        archive = CHECKED_IN_SOAK / "raw-evidence.tar.zst"
        declared_checksum = (CHECKED_IN_SOAK / "raw-evidence.tar.zst.sha256").read_text(
            encoding="utf-8"
        )
        observed_checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(declared_checksum, f"{observed_checksum}  raw-evidence.tar.zst\n")
        aggregate = json.loads((CHECKED_IN_SOAK / "aggregate.json").read_text(encoding="utf-8"))
        self.assertEqual(
            aggregate["raw_evidence_archive"],
            {
                "manifest": "raw-evidence.manifest.sha256",
                "path": "raw-evidence.tar.zst",
                "sha256": f"sha256:{observed_checksum}",
            },
        )
        self.assertIn(
            "**Status:** PASS",
            (CHECKED_IN_SOAK / "SOAK.md").read_text(encoding="utf-8"),
        )
        with tempfile.TemporaryDirectory() as directory:
            extracted = Path(directory)
            integrity = subprocess.run(
                ["zstd", "--test", str(archive)], text=True, capture_output=True, check=False
            )
            self.assertEqual(integrity.returncode, 0, integrity.stderr)
            extraction = subprocess.run(
                [
                    "tar",
                    "--use-compress-program=zstd",
                    "-xf",
                    str(archive),
                    "-C",
                    str(extracted),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(extraction.returncode, 0, extraction.stderr)
            self.assertEqual(
                (extracted / "raw-evidence.manifest.sha256").read_text(encoding="utf-8"),
                (CHECKED_IN_SOAK / "raw-evidence.manifest.sha256").read_text(encoding="utf-8"),
            )
            manifest = subprocess.run(
                ["sha256sum", "--check", "raw-evidence.manifest.sha256"],
                cwd=extracted,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(manifest.returncode, 0, manifest.stderr)
            revalidated = subprocess.run(
                [
                    sys.executable,
                    str(AGGREGATOR),
                    "aggregate",
                    "--runs-directory",
                    str(extracted / "runs"),
                    "--output-json",
                    str(extracted / "revalidated-aggregate.json"),
                    "--output-report",
                    str(extracted / "revalidated-SOAK.md"),
                    "--source-commit",
                    "6a64f0630cee9afa080d33f376aabadac724fa72",
                    "--source-tree",
                    "d27ff38ebbd891c5be949f54a0047522ed893d20",
                    "--calibration",
                    str(CALIBRATION),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(revalidated.returncode, 0, revalidated.stderr)
            revalidated_document = json.loads(
                (extracted / "revalidated-aggregate.json").read_text(encoding="utf-8")
            )
            self.assertEqual(revalidated_document["status"], "pass")
            self.assertEqual(
                revalidated_document["calibration_noise"]["applicability"]["status"],
                "matched",
            )
            self.assertEqual(set(revalidated_document["post_shutdown"]), {"run-01", "run-02", "run-03"})
            self.assertEqual(revalidated_document["file_descriptors"]["status"], "pass")
            self.assertEqual(
                revalidated_document["evidence_completeness"]["status"], "complete"
            )
            self.assertIn(
                "issue #38 host/configuration identity is strictly matched",
                (extracted / "revalidated-SOAK.md").read_text(encoding="utf-8"),
            )

    def test_retains_without_failing_a_stable_within_band_peak_outlier(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            raw = archive / "runs" / "run-03" / "raw.json"
            document = json.loads(raw.read_text(encoding="utf-8"))
            first_measured = next(
                sample
                for sample in document["resource_samples"]
                if sample["phase"] == "measured"
            )
            first_measured["process"]["pss_bytes"] += 4_000_000
            raw.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            aggregate = json.loads((archive / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["status"], "pass")
            self.assertEqual(
                aggregate["run_level_resource_outliers"]["pss_bytes"], ["run-03"]
            )
            self.assertEqual(aggregate["material_run_level_outliers"], {})
            report = (archive / "SOAK.md").read_text(encoding="utf-8")
            self.assertIn("within calibrated late-window bound", report)

    def test_rejects_missing_canonical_hard_invariant(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            raw = archive / "runs" / "run-03" / "raw.json"
            document = json.loads(raw.read_text(encoding="utf-8"))
            document["checks"].pop()
            raw.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("hard invariant set differs", completed.stderr)
            self.assertFalse((archive / "aggregate.json").exists())

    def test_rejects_a_run_without_an_exact_command(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            raw = archive / "runs" / "run-03" / "raw.json"
            document = json.loads(raw.read_text(encoding="utf-8"))
            document.pop("command")
            raw.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("exact resource-soak command", completed.stderr)

    def test_rejects_a_nonfinal_cache_allocator_or_cow_configuration(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            raw = archive / "runs" / "run-03" / "raw.json"
            document = json.loads(raw.read_text(encoding="utf-8"))
            document["config"]["wasmtime_instance_allocator"] = "pooling"
            raw.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("final ordinary Phase 0 cache/allocator/COW", completed.stderr)

    def test_retains_failure_report_for_unexplained_fd_growth(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            raw = archive / "runs" / "run-03" / "raw.json"
            document = json.loads(raw.read_text(encoding="utf-8"))
            measured = [
                sample
                for sample in document["resource_samples"]
                if sample["phase"] == "measured"
            ]
            measured[-1]["process"]["file_descriptor_count"] = 6
            raw.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 1, completed.stderr)
            aggregate = json.loads((archive / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["status"], "fail")
            self.assertIn("run-03", aggregate["file_descriptors"]["violations"])
            self.assertTrue((archive / "SOAK.md").is_file())

    def test_rejects_a_post_shutdown_fd_leak(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            raw = archive / "runs" / "run-03" / "raw.json"
            document = json.loads(raw.read_text(encoding="utf-8"))
            document["post_shutdown"]["process"]["file_descriptor_count"] = 6
            raw.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("post-release-to-shutdown FD increase", completed.stderr)

    def test_rejects_equally_elevated_post_release_and_shutdown_fds(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            raw = archive / "runs" / "run-03" / "raw.json"
            document = json.loads(raw.read_text(encoding="utf-8"))
            document["post_release"]["process"]["file_descriptor_count"] = 5
            document["post_shutdown"]["process"]["file_descriptor_count"] = 5
            raw.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("post-shutdown FD count exceeds its pre-runtime baseline", completed.stderr)

    def test_rejects_post_release_fd_above_pre_runtime_baseline(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            raw = archive / "runs" / "run-03" / "raw.json"
            document = json.loads(raw.read_text(encoding="utf-8"))
            document["post_release"]["process"]["file_descriptor_count"] = 5
            raw.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 1, completed.stderr)
            aggregate = json.loads((archive / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["status"], "fail")
            self.assertIn("run-03", aggregate["file_descriptors"]["violations"])

    def test_rejects_missing_pre_runtime_baseline_for_new_evidence(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            self.update_all_raw_documents(
                archive, lambda document: document.pop("process_before_runtime")
            )
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("lacks its pre-runtime process baseline", completed.stderr)

    def test_rejects_missing_post_warmup_descriptor_baseline_for_new_evidence(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            self.update_all_raw_documents(
                archive, lambda document: document.pop("process_after_warmup")
            )
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("lacks its post-warm-up descriptor baseline", completed.stderr)

    def test_rejects_altered_post_shutdown_topology(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            raw = archive / "runs" / "run-03" / "raw.json"
            document = json.loads(raw.read_text(encoding="utf-8"))
            document["post_shutdown"]["process"]["open_socket_count"] = 1
            raw.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("post-shutdown process topology differs", completed.stderr)

    def test_rejects_an_unavailable_listening_socket_probe(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            raw = archive / "runs" / "run-03" / "raw.json"
            document = json.loads(raw.read_text(encoding="utf-8"))
            document["resource_samples"][0]["process"]["probe_notes"].append(
                "cannot read /proc/net/tcp: permission denied"
            )
            raw.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("unavailable mandatory listening-socket probe", completed.stderr)

    def test_rejects_unreconciled_saturation_observations(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            raw = archive / "runs" / "run-03" / "raw.json"
            document = json.loads(raw.read_text(encoding="utf-8"))
            document["saturation_observations"].pop()
            raw.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("does not retain every declared bounded_queue_saturation observation", completed.stderr)

    def test_rejects_host_and_status_execution_provenance_mismatches(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            host = archive / "runs" / "run-03" / "host-before.json"
            host_document_data = json.loads(host.read_text(encoding="utf-8"))
            host_document_data["source_identity"]["execution_commit"] = "d" * 40
            host.write_text(json.dumps(host_document_data), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("host observation source identity", completed.stderr)

        temporary, archive = self.make_archive()
        with temporary:
            status = archive / "runs" / "run-03" / "execution-status.json"
            status_document = json.loads(status.read_text(encoding="utf-8"))
            status_document["run_index"] = 2
            status.write_text(json.dumps(status_document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("successful matching execution status", completed.stderr)

    def test_rejects_raw_environment_that_disagrees_with_host_observations(self) -> None:
        mutations = {
            "operating_system": lambda host: host.__setitem__("operating_system", "other"),
            "architecture": lambda host: host.__setitem__("architecture", "other"),
            "cpu_model": lambda host: host.__setitem__("cpu_model", "other CPU"),
            "logical_cpu_count": lambda host: host.__setitem__("logical_cpu_count", 8),
            "total_memory_bytes": lambda host: host.__setitem__("total_memory_bytes", 8_000_000_000),
            "kernel": lambda host: host.__setitem__("kernel", "other kernel"),
            "virtualization": lambda host: host["virtualization"].__setitem__(
                "systemd_detect_virt", "kvm"
            ),
        }
        for field, mutation in mutations.items():
            with self.subTest(field=field):
                temporary, archive = self.make_archive()
                with temporary:
                    self.update_all_host_documents(archive, lambda document: mutation(document["host"]))
                    completed = self.aggregate(archive)
                    self.assertEqual(completed.returncode, 2)
                    if field == "virtualization":
                        self.assertIn("raw virtualization status", completed.stderr)
                    else:
                        self.assertIn(f"raw environment.{field}", completed.stderr)

    def test_rejects_missing_new_raw_or_host_identity_fields(self) -> None:
        cases = {
            "raw virtualization": (
                lambda archive: self.update_all_raw_documents(
                    archive,
                    lambda document: document["environment"]["native_linux_validation"].pop(
                        "virtualization_kind"
                    ),
                ),
                "lacks virtualization_kind",
            ),
            "host VM virtualization": (
                lambda archive: self.update_all_host_documents(
                    archive,
                    lambda document: document["host"]["virtualization"].pop(
                        "systemd_detect_virt_vm"
                    ),
                ),
                "lacks virtualization.systemd_detect_virt_vm",
            ),
            "host allocator": (
                lambda archive: self.update_all_host_documents(
                    archive, lambda document: document.pop("allocator")
                ),
                "lacks allocator provenance",
            ),
        }
        for name, (mutate, expected) in cases.items():
            with self.subTest(name=name):
                temporary, archive = self.make_archive()
                with temporary:
                    mutate(archive)
                    completed = self.aggregate(archive)
                    self.assertEqual(completed.returncode, 2)
                    self.assertIn(expected, completed.stderr)

    def test_rejects_unbound_legacy_retained_state_fallback(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            self.update_all_raw_documents(
                archive,
                lambda document: [
                    document["config"].pop(field)
                    for field in (
                        "component_maximum_bytes",
                        "prepared_cache_maximum_entries",
                        "prepared_cache_maximum_bytes",
                        "invocation_log_maximum_entries",
                        "invocation_log_maximum_bytes",
                        "retained_log_maximum_entries",
                        "retained_log_maximum_bytes",
                    )
                ],
            )
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("only the known 6250b978/65ba3412 historical archive", completed.stderr)

    def test_marks_calibration_identity_mismatches_inconclusive(self) -> None:
        raw_mutations = {
            "environment.cpu_model": (
                lambda document: document["environment"].__setitem__("cpu_model", "other CPU"),
                lambda document: document["host"].__setitem__("cpu_model", "other CPU"),
            ),
            "environment.kernel": (
                lambda document: document["environment"].__setitem__("kernel", "other kernel"),
                lambda document: document["host"].__setitem__("kernel", "other kernel"),
            ),
            "artifact.component_digest": (
                lambda document: document["artifact"].__setitem__(
                    "component_digest", "sha256:" + "d" * 64
                ),
                None,
            ),
            "environment.rustc": (
                lambda document: document["environment"].__setitem__("rustc", "other rustc"),
                None,
            ),
        }
        calibration_mutations = {
            "config.prepared_cache_enabled": lambda document: document["reference_identity"][
                "config"
            ].__setitem__("prepared_cache_enabled", False),
            "config.wasmtime_instance_allocator": lambda document: document[
                "reference_identity"
            ]["config"].__setitem__("wasmtime_instance_allocator", "pooling"),
            "config.wasmtime_copy_on_write_images": lambda document: document[
                "reference_identity"
            ]["config"].__setitem__("wasmtime_copy_on_write_images", False),
        }
        for expected_field, (raw_mutation, host_mutation) in raw_mutations.items():
            with self.subTest(expected_field=expected_field):
                temporary, archive = self.make_archive()
                with temporary:
                    self.update_all_raw_documents(archive, raw_mutation)
                    if host_mutation is not None:
                        self.update_all_host_documents(archive, host_mutation)
                    completed = self.aggregate(archive)
                    self.assertEqual(completed.returncode, 1, completed.stderr)
                    aggregate = json.loads((archive / "aggregate.json").read_text(encoding="utf-8"))
                    self.assertEqual(aggregate["status"], "inconclusive")
                    mismatch_fields = {
                        mismatch["field"]
                        for mismatch in aggregate["calibration_noise"]["applicability"]["mismatches"]
                    }
                    self.assertIn(expected_field, mismatch_fields)
        for expected_field, mutation in calibration_mutations.items():
            with self.subTest(expected_field=expected_field):
                temporary, archive = self.make_archive()
                with temporary:
                    path = archive / "calibration.json"
                    document = json.loads(path.read_text(encoding="utf-8"))
                    mutation(document)
                    path.write_text(json.dumps(document), encoding="utf-8")
                    completed = self.aggregate(archive)
                    self.assertEqual(completed.returncode, 1, completed.stderr)
                    aggregate = json.loads((archive / "aggregate.json").read_text(encoding="utf-8"))
                    self.assertEqual(aggregate["status"], "inconclusive")
                    mismatch_fields = {
                        mismatch["field"]
                        for mismatch in aggregate["calibration_noise"]["applicability"]["mismatches"]
                    }
                    self.assertIn(expected_field, mismatch_fields)

    def test_accepts_the_baseline_allocator_field_name_for_new_calibration(self) -> None:
        temporary, archive = self.make_archive()
        with temporary:
            path = archive / "calibration.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            config = document["reference_identity"]["config"]
            config["wasmtime_allocator"] = config.pop("wasmtime_instance_allocator")
            path.write_text(json.dumps(document), encoding="utf-8")
            completed = self.aggregate(archive)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            aggregate = json.loads((archive / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["calibration_noise"]["applicability"]["status"], "matched")


if __name__ == "__main__":
    unittest.main()
