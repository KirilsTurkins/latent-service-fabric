from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR = ROOT / "tools" / "aggregate_phase0_resource_soak.py"
CALIBRATION = (
    ROOT
    / "benchmarks"
    / "phase0"
    / "calibration"
    / "native-linux-2026-08-27-reachable-source"
    / "aggregate.json"
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
        value["normal_measured_activations_completed"] = min(
            max(0, index - warmup_batches) * 1_000,
            100_000,
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
                "wsl_detected": False,
                "container_kind": "none",
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
            "prepared_cache_enabled": True,
            "wasmtime_instance_allocator": "on_demand",
            "wasmtime_copy_on_write_images": True,
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
        "post_shutdown": {"observed_runtime_workers": 0, "process": samples[-1]["process"]},
        "checks": [
            {"name": name, "passed": True, "expected": "test", "observed": "test"}
            for name in sorted(CHECKS)
        ],
    }


def host_document(phase: str) -> dict[str, object]:
    return {
        "schema_version": "latent.phase0.resource-soak.host-observation.v1",
        "phase": phase,
        "native_linux_reference": True,
        "source_identity": {
            "published_commit": SOURCE_COMMIT,
            "published_tree": SOURCE_TREE,
            "execution_commit": SOURCE_COMMIT,
            "execution_tree": SOURCE_TREE,
            "tree_identity_verified": True,
        },
    }


class Phase0ResourceSoakAggregateTests(unittest.TestCase):
    def make_archive(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        archive = Path(temporary.name)
        for index in range(1, 4):
            run = archive / "runs" / f"run-{index:02d}"
            run.mkdir(parents=True)
            (run / "raw.json").write_text(
                json.dumps(raw_document(index)), encoding="utf-8"
            )
            for phase in ("before", "after"):
                (run / f"host-{phase}.json").write_text(
                    json.dumps(host_document(phase)), encoding="utf-8"
                )
            (run / "execution-status.json").write_text(
                json.dumps(
                    {
                        "schema_version": "latent.phase0.resource-soak.execution-status.v1",
                        "exit_code": 0,
                        "source_commit": SOURCE_COMMIT,
                        "source_tree": SOURCE_TREE,
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
                str(CALIBRATION),
            ],
            check=False,
            text=True,
            capture_output=True,
        )

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
            self.assertIn("#38 calibrated RSS noise band", report)
            self.assertIn("## Conclusion", report)

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


if __name__ == "__main__":
    unittest.main()
