from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR = ROOT / "tools" / "aggregate_phase0_hot_path_profiles.py"
SOURCE_COMMIT = "a" * 40
SOURCE_TREE = "b" * 40
SOURCE_REF = "benchmark/phase0-test-source"
SOURCE_REF_HEAD = "c" * 40

WORKLOAD_SEMANTICS = {
    "cold-preparation": "capsule validation, engine construction, and first prepared-component creation only",
    "prepared-cache-reuse": "one cold prepared component followed by one same-key bounded-cache reuse probe; no activation, failure sequence, pool probe, or throughput",
    "first-activation": "one first echo after preparation; no warm loop, mixed failures, pool probe, or throughput",
    "warm-execution": "repeated successful warm echoes after one preparation; no failure sequence, pool probe, or throughput",
    "failure-containment": "trap, timeout, cancellation, and memory-pressure failures with immediate cause-specific recovery",
    "cleanup": "successful activations followed by per-activation resource reclamation, cell disposition, and explicit prepared release",
    "at-capacity-contention": "real at-capacity activation batches only; no bounded-queue batch, pool microprobe, or mixed failure sequence",
    "queued-contention": "real bounded-queue saturation batches only; no at-capacity batch, pool microprobe, or mixed failure sequence",
}

WORKLOAD_SCENARIOS = {
    "cold-preparation": [],
    "prepared-cache-reuse": ["prepared_cache_reuse"],
    "first-activation": ["retained_first_echo"],
    "warm-execution": ["warm_echo"],
    "failure-containment": [
        "sequence_echo",
        "domain_error",
        "recovery_after_domain_error",
        "trap",
        "recovery_after_trap",
        "timeout",
        "recovery_after_timeout",
        "cancellation",
        "recovery_after_cancellation",
        "memory_pressure",
        "recovery_after_memory_pressure",
    ],
    "cleanup": ["cleanup_echo"],
    "at-capacity-contention": ["throughput_at_capacity"],
    "queued-contention": ["throughput_bounded_queue_saturation"],
}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def environment() -> dict[str, object]:
    return {
        "operating_system": "linux",
        "architecture": "x86_64",
        "kernel": "Linux test",
        "cpu_model": "test CPU",
        "logical_cpu_count": 4,
        "total_memory_bytes": 16_777_216,
        "rustc": "rustc test",
        "cargo": "cargo test",
        "rust_target": "x86_64-unknown-linux-gnu",
        "build_profile": "release",
        "wasmtime_version": "47.0.3 (workspace pin)",
        "repository_commit": "d" * 40,
    }


def configuration(
    *,
    workers: int = 2,
    pool: int = 2,
    allocator: str = "on_demand",
    cow: bool = True,
    cache_enabled: bool = True,
    profile_workload: str | None = None,
    poll_interval: int = 0,
) -> dict[str, object]:
    return {
        "mode": "full",
        "profile_workload": profile_workload,
        "pool_capacity": pool,
        "pool_queue_capacity": 4,
        "runtime_workers": workers,
        "warm_samples": 40,
        "sequence_repetitions": 10,
        "throughput_batches": 24,
        "pool_iterations": 2000,
        "fuel": 1_000_000_000_000,
        "memory_bytes": 16_777_216,
        "memory_pressure_bytes": 4_194_304,
        "timeout_ms": 25,
        "cancel_after_ms": 5,
        "maximum_overshoot_ms": 500,
        "coordination_timeout_ms": 15_000,
        "coordination_poll_interval_ms": poll_interval,
        "rss_growth_allowance_bytes": 67_108_864,
        "fd_growth_allowance": 2,
        "wasmtime_allocator": allocator,
        "wasmtime_copy_on_write_images": cow,
        "prepared_cache_enabled": cache_enabled,
    }


def checks() -> list[dict[str, object]]:
    return [
        {"name": "cleanup_proven", "passed": True},
        {"name": "fixed_topology", "passed": True},
    ]


def snapshots() -> list[dict[str, object]]:
    return [
        {
            "label": "before_component_load",
            "rss_bytes": 1024,
            "virtual_memory_bytes": 2048,
            "file_descriptor_count": 5,
            "thread_count": 3,
            "open_socket_count": 0,
            "listening_socket_count": 0,
        },
        {
            "label": "after_component_preparation",
            "rss_bytes": 1280,
            "virtual_memory_bytes": 2304,
            "file_descriptor_count": 5,
            "thread_count": 3,
            "open_socket_count": 0,
            "listening_socket_count": 0,
        },
        {
            "label": "prepared_component_released",
            "rss_bytes": 1088,
            "virtual_memory_bytes": 2112,
            "file_descriptor_count": 5,
            "thread_count": 3,
            "open_socket_count": 0,
            "listening_socket_count": 0,
        },
    ]


def baseline(**kwargs: object) -> dict[str, object]:
    check_set = kwargs.pop("checks", checks())
    config = configuration(**kwargs)
    cache_enabled = config["prepared_cache_enabled"]
    return {
        "schema_version": "latent.phase0.baseline.v2",
        "status": "pass",
        "checks": check_set,
        "config": config,
        "environment": environment(),
        "timings": {
            "component_preparation_micros": 100,
            "distributions": {
                "warm_echo_elapsed_micros": {"p50": 10},
                "post_invocation_cleanup_micros": {"p50": 2},
            },
        },
        "activation_throughput": {
            "at_capacity": {"activations_per_second": 1000},
            "bounded_queue_saturation": {"activations_per_second": 800},
        },
        "preparation_cache_reuse": {
            "cache_enabled": cache_enabled,
            "first_prepare_micros": 100,
            "second_prepare_micros": 2 if cache_enabled else None,
            "same_prepared_handle": True if cache_enabled else None,
            "cache_entries_after_probe": 1 if cache_enabled else 0,
            "status": "cache_hit" if cache_enabled else "disabled_cold_control",
        },
        "process_snapshots": snapshots(),
    }


def targeted(name: str) -> dict[str, object]:
    document = baseline(profile_workload=name, poll_interval=1)
    document.update(
        {
            "schema_version": "latent.phase0.targeted-profile.v2",
            "profile_workload": name,
            "workload_semantics": WORKLOAD_SEMANTICS[name],
            "full_invariant_proof_required": True,
            "selected_scenarios": WORKLOAD_SCENARIOS[name],
            "activation_throughput": None,
            "preparation_cache_reuse": (
                document["preparation_cache_reuse"]
                if name == "prepared-cache-reuse"
                else None
            ),
            "targeted_contention": (
                {
                    "mode": {
                        "mode": "at_capacity",
                        "maximum_observed_active_leases": 2,
                        "maximum_observed_queue_depth": 0,
                    }
                }
                if name == "at-capacity-contention"
                else {
                    "mode": {
                        "mode": "bounded_queue_saturation",
                        "maximum_observed_active_leases": 2,
                        "maximum_observed_queue_depth": 4,
                    }
                }
                if name == "queued-contention"
                else None
            ),
            "payload_flow": {
                "input_bytes_submitted_to_typed_call": 100,
                "output_bytes_returned_from_typed_call": 100,
                "copy_bytes_claimed": 0,
            },
            "checks": [{"name": f"targeted_{name}", "passed": True}],
        }
    )
    return document


def command(tool: str, *, workload: str | None, poll_interval: int) -> dict[str, object]:
    arguments = [
        tool,
        "record",
        "--",
        "/tmp/phase0-baseline",
        "--mode",
        "full",
        "--coordination-poll-interval-ms",
        str(poll_interval),
    ]
    if workload is not None:
        arguments.extend(["--profile-workload", workload])
    return {
        "schema_version": "latent.phase0.hot-path.command.v1",
        "tool": tool,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "published_source_ref": SOURCE_REF,
        "published_source_ref_head": SOURCE_REF_HEAD,
        "execution_commit": "d" * 40,
        "execution_tree": SOURCE_TREE,
        "command": arguments,
    }


def make_full_proof(root: Path) -> None:
    write_json(root / "raw-results.json", baseline())
    proof_command = command("phase0-baseline-full-invariant-proof", workload=None, poll_interval=0)
    proof_command["command"][0] = "/tmp/phase0-baseline"  # type: ignore[index]
    write_json(root / "command.json", proof_command)


def make_profile(root: Path, name: str) -> None:
    for tool, report in (
        (
            "perf",
            "Overhead  Command  Shared Object  Symbol\n"
            "  50.00%  phase0-baseline  phase0-baseline  phase0_activation_envelope\n",
        ),
        (
            "allocation",
            "calls to allocation functions: 10 (10/s)\n"
            "peak heap memory consumption: 100B\n"
            "total memory leaked: 0B\n",
        ),
    ):
        directory = root / name / tool
        directory.mkdir(parents=True, exist_ok=True)
        write_json(
            directory / "command.json",
            command("perf" if tool == "perf" else "heaptrack", workload=name, poll_interval=1),
        )
        write_json(directory / "raw-results.json", targeted(name))
        if tool == "perf":
            (directory / "perf.data").write_bytes(b"perf")
            (directory / "perf-report.txt").write_text(report, encoding="utf-8")
            (directory / "perf-inclusive-report.txt").write_text(
                "Children  Self  Command  Shared Object  Symbol\n"
                "  50.00%  25.00%  phase0-baseline  phase0-baseline  phase0_activation_envelope\n",
                encoding="utf-8",
            )
        else:
            (directory / "heaptrack.gz.zst").write_bytes(b"heaptrack")
            (directory / "heaptrack-report.txt").write_text(report, encoding="utf-8")
            (directory / "heaptrack-leaks.txt").write_text(
                "MEMORY LEAKS\ntotal memory leaked: 0B\n", encoding="utf-8"
            )
            (directory / "heaptrack-allocations.folded").write_text(
                "phase0_activation_envelope; 10\n", encoding="utf-8"
            )
            (directory / "heaptrack-peak-bytes.folded").write_text(
                "phase0_activation_envelope; 100\n", encoding="utf-8"
            )
            summary = subprocess.run(
                [
                    sys.executable,
                    str(AGGREGATOR),
                    "summarize-heaptrack",
                    "--allocation-folded",
                    str(directory / "heaptrack-allocations.folded"),
                    "--peak-folded",
                    str(directory / "heaptrack-peak-bytes.folded"),
                    "--raw-heaptrack-data",
                    str(directory / "heaptrack.gz.zst"),
                    "--output",
                    str(directory / "heaptrack-contributors.json"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            if summary.returncode != 0:
                raise RuntimeError(summary.stderr)


def make_candidate(root: Path, name: str, expectation: dict[str, object]) -> None:
    for index in range(1, 4):
        document = baseline(
            workers=int(expectation["runtime_workers"]),
            pool=int(expectation["pool_capacity"]),
            allocator=str(expectation["wasmtime_allocator"]),
            cow=bool(expectation["wasmtime_copy_on_write_images"]),
            cache_enabled=bool(expectation["prepared_cache_enabled"]),
        )
        run = root / name / f"run-{index:02d}"
        write_json(run / "raw-results.json", document)
        write_json(run / "command.json", command("phase0-baseline", workload=None, poll_interval=0))


class AggregateHotPathProfilesTests(unittest.TestCase):
    def build_archive(self, temporary: Path) -> tuple[Path, Path, Path, Path, Path]:
        profiles = temporary / "profiles"
        candidates = temporary / "candidates"
        proof = temporary / "full-invariant-proof"
        make_full_proof(proof)
        for name in WORKLOAD_SEMANTICS:
            make_profile(profiles, name)
        expectations = {
            "worker-cell-1w-1c": (1, 1, "on_demand", True, True),
            "worker-cell-2w-2c": (2, 2, "on_demand", True, True),
            "worker-cell-2w-4c": (2, 4, "on_demand", True, True),
            "worker-cell-4w-2c": (4, 2, "on_demand", True, True),
            "on-demand-cow-disabled": (2, 2, "on_demand", False, True),
            "pooling-cow-disabled": (2, 2, "pooling", False, True),
            "pooling-cow-enabled": (2, 2, "pooling", True, True),
            "prepared-cache-disabled": (2, 2, "on_demand", True, False),
        }
        for name, (workers, pool, allocator, cow, cache_enabled) in expectations.items():
            make_candidate(
                candidates,
                name,
                {
                    "runtime_workers": workers,
                    "pool_capacity": pool,
                    "wasmtime_allocator": allocator,
                    "wasmtime_copy_on_write_images": cow,
                    "prepared_cache_enabled": cache_enabled,
                },
            )
        host = temporary / "host.json"
        write_json(
            host,
            {
                "schema_version": "latent.phase0.hot-path.host-observation.v1",
                "native_linux_reference": True,
                "source_commit": SOURCE_COMMIT,
                "source_tree": SOURCE_TREE,
                "published_source_ref": SOURCE_REF,
                "published_source_ref_head": SOURCE_REF_HEAD,
                "operating_system": "linux",
                "architecture": "x86_64",
                "kernel": "Linux test",
                "tools": {"rustc": "rustc test", "cargo": "cargo test"},
            },
        )
        calibration = temporary / "calibration.json"
        metrics = {}
        for name in (
            "component_preparation_micros",
            "warm_activation_elapsed_micros",
            "post_invocation_cleanup_micros",
            "at_capacity_activations_per_second",
            "bounded_queue_saturation_activations_per_second",
            "process_peak_rss_bytes",
            "process_peak_virtual_memory_bytes",
        ):
            metrics[name] = {
                "direction": "increase_is_regression",
                "comparison": {"reference_median": 100.0, "advisory_noise_band": 10.0},
            }
        reference_config = configuration()
        for key in ("profile_workload", "coordination_poll_interval_ms", "prepared_cache_enabled"):
            reference_config.pop(key)
        write_json(
            calibration,
            {
                "status": "pass",
                "source_commit": SOURCE_COMMIT,
                "source_tree": SOURCE_TREE,
                "minimum_required_run_count": 7,
                "reference_identity": {"config": reference_config, "environment": environment()},
                "metrics": metrics,
            },
        )
        return profiles, proof / "raw-results.json", candidates, host, calibration

    def run_aggregate(
        self,
        temporary: Path,
        archive: tuple[Path, Path, Path, Path, Path] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        profiles, proof, candidates, host, calibration = archive or self.build_archive(temporary)
        return subprocess.run(
            [
                sys.executable,
                str(AGGREGATOR),
                "aggregate",
                "--profiles-directory",
                str(profiles),
                "--full-invariant-proof",
                str(proof),
                "--candidates-directory",
                str(candidates),
                "--host-observation",
                str(host),
                "--calibration-aggregate",
                str(calibration),
                "--source-commit",
                SOURCE_COMMIT,
                "--source-tree",
                SOURCE_TREE,
                "--published-source-ref",
                SOURCE_REF,
                "--required-candidate-runs",
                "3",
                "--output-json",
                str(temporary / "aggregate.json"),
                "--output-report",
                str(temporary / "PROFILE.md"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_aggregate_accepts_targeted_profiles_and_quantifies_contributors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            result = self.run_aggregate(temporary)
            self.assertEqual(result.returncode, 0, result.stderr)
            aggregate = json.loads((temporary / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(len(aggregate["profiles"]), 8)
            self.assertEqual(len(aggregate["candidates"]), 8)
            envelope = aggregate["profiles"][0]["contributor_attribution"]["categories"][
                "activation envelope and metadata handling"
            ]
            self.assertEqual(envelope["allocation_calls"], 10)
            self.assertEqual(envelope["allocation_peak_bytes"], 100)
            self.assertEqual(envelope["cpu_self_percent"], 50.0)
            self.assertEqual(envelope["cpu_inclusive_percent"], 50.0)
            default = aggregate["candidates"]["worker-cell-2w-2c"]
            self.assertEqual(default["calibration_comparison_eligibility"]["status"], "inconclusive")
            self.assertEqual(
                default["calibration_comparison"]["at_capacity_activations_per_second"]["status"],
                "inconclusive",
            )
            report = (temporary / "PROFILE.md").read_text(encoding="utf-8")
            self.assertIn("Fixed RSS", report)
            self.assertIn("not observed at profiler resolution", report)
            self.assertIn("not a measured zero-cost result", report)

    def test_rejects_missing_canonical_hard_check_from_matrix_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            _, _, candidates, _, _ = archive
            broken = baseline(checks=[{"name": "cleanup_proven", "passed": True}])
            write_json(
                candidates / "worker-cell-2w-2c" / "run-02" / "raw-results.json", broken
            )
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("different hard-check set", result.stderr)

    def test_rejects_profile_without_its_named_selective_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            profiles, _, _, _, _ = archive
            command_path = profiles / "cleanup" / "perf" / "command.json"
            document = json.loads(command_path.read_text(encoding="utf-8"))
            arguments = document["command"]
            index = arguments.index("--profile-workload")
            del arguments[index : index + 2]
            write_json(command_path, document)
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not declare its exact profile workload", result.stderr)

    def test_rejects_profile_with_the_wrong_distinct_contention_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            profiles, _, _, _, _ = archive
            path = (
                profiles
                / "at-capacity-contention"
                / "perf"
                / "raw-results.json"
            )
            document = json.loads(path.read_text(encoding="utf-8"))
            document["targeted_contention"]["mode"]["mode"] = "bounded_queue_saturation"
            write_json(path, document)
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("wrong targeted contention mode", result.stderr)

    def test_rejects_command_with_execution_identity_different_from_full_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            profiles, _, _, _, _ = archive
            path = profiles / "warm-execution" / "allocation" / "command.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["execution_commit"] = "e" * 40
            write_json(path, document)
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("execution commit differs", result.stderr)

    def test_rejects_command_with_published_source_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            _, _, candidates, _, _ = archive
            path = candidates / "worker-cell-2w-2c" / "run-03" / "command.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["source_tree"] = "e" * 40
            write_json(path, document)
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source identity mismatch for source_tree", result.stderr)

    def test_rejects_duplicate_targeted_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            profiles, _, _, _, _ = archive
            for tool in ("perf", "allocation"):
                path = profiles / "cleanup" / tool / "raw-results.json"
                document = json.loads(path.read_text(encoding="utf-8"))
                document["workload_semantics"] = WORKLOAD_SEMANTICS["warm-execution"]
                document["selected_scenarios"] = WORKLOAD_SCENARIOS["warm-execution"]
                write_json(path, document)
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("canonical cleanup semantics", result.stderr)

    def test_rejects_candidate_without_fixed_memory_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            _, _, candidates, _, _ = archive
            path = candidates / "worker-cell-2w-2c" / "run-01" / "raw-results.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["process_snapshots"] = [
                snapshot
                for snapshot in document["process_snapshots"]
                if snapshot["label"] != "before_component_load"
            ]
            write_json(path, document)
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lacks required fixed/peak-memory", result.stderr)

    def test_rejects_candidate_without_matching_per_run_host_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            _, _, candidates, _, _ = archive
            path = candidates / "worker-cell-2w-2c" / "run-01" / "raw-results.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["environment"]["kernel"] = "different kernel"
            write_json(path, document)
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("per-run environment differs from host observation", result.stderr)

    def test_rejects_candidate_without_a_direct_cache_reuse_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            _, _, candidates, _, _ = archive
            path = candidates / "worker-cell-2w-2c" / "run-01" / "raw-results.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            del document["preparation_cache_reuse"]
            write_json(path, document)
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lacks an explicit prepared-cache reuse control", result.stderr)

    def test_rejects_one_run_experiment_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            result = self.run_aggregate(temporary)
            command = result.args
            assert isinstance(command, list)
            command[command.index("--required-candidate-runs") + 1] = "1"
            one_run_result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertNotEqual(one_run_result.returncode, 0)
            self.assertIn("at least 3", one_run_result.stderr)

    def test_rejects_unreadable_or_zero_allocation_folded_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            profiles, _, _, _, _ = archive
            report = profiles / "warm-execution" / "allocation" / "heaptrack-report.txt"
            report.write_text(
                "calls to allocation functions: 0 (0/s)\ntotal memory leaked: 0B\n",
                encoding="utf-8",
            )
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("non-zero Heaptrack allocation evidence", result.stderr)

    def test_rejects_compact_allocation_totals_not_bound_to_raw_heaptrack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            profiles, _, _, _, _ = archive
            path = (
                profiles
                / "queued-contention"
                / "allocation"
                / "heaptrack-contributors.json"
            )
            document = json.loads(path.read_text(encoding="utf-8"))
            document["raw_heaptrack_sha256"] = "sha256:" + "0" * 64
            write_json(path, document)
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not bound to its raw trace", result.stderr)

    def test_rejects_compact_allocation_with_non_owner_frame_method(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            profiles, _, _, _, _ = archive
            path = (
                profiles
                / "queued-contention"
                / "allocation"
                / "heaptrack-contributors.json"
            )
            document = json.loads(path.read_text(encoding="utf-8"))
            document["owner_selection"] = "first matching frame anywhere in the stack"
            write_json(path, document)
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected owner-selection method", result.stderr)

    def test_heaptrack_copy_attribution_requires_a_wit_or_canonical_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw_data = temporary / "heaptrack.gz.zst"
            allocations = temporary / "allocations.folded"
            peak_bytes = temporary / "peak-bytes.folded"
            output = temporary / "contributors.json"
            raw_data.write_bytes(b"heaptrack")
            # Generic libc copies and the word `component` occur in unrelated
            # compilation paths. Neither is evidence of a canonical WIT copy.
            allocations.write_text(
                "libc.so.6;__memcpy_avx_unaligned_erms 11\n"
                "unrelated_component_compilation;compile 13\n"
                "wasmtime::component::values::lift 17\n",
                encoding="utf-8",
            )
            peak_bytes.write_text(
                "libc.so.6;__memmove_avx_unaligned_erms 101\n"
                "unrelated_component_compilation;compile 103\n"
                "wasmtime::component::func::lower 107\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(AGGREGATOR),
                    "summarize-heaptrack",
                    "--allocation-folded",
                    str(allocations),
                    "--peak-folded",
                    str(peak_bytes),
                    "--raw-heaptrack-data",
                    str(raw_data),
                    "--output",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            categories = json.loads(output.read_text(encoding="utf-8"))["categories"]
            wit = categories["WIT lifting, lowering, and payload copies"]
            unknown = categories["unmatched_or_unknown"]
            self.assertEqual(wit["allocation_calls"], 17)
            self.assertEqual(wit["allocation_peak_bytes"], 107)
            self.assertEqual(unknown["allocation_calls"], 24)
            self.assertEqual(unknown["allocation_peak_bytes"], 204)

    def test_heaptrack_owner_attribution_ignores_outer_platform_error_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw_data = temporary / "heaptrack.gz.zst"
            allocations = temporary / "allocations.folded"
            peak_bytes = temporary / "peak-bytes.folded"
            output = temporary / "contributors.json"
            raw_data.write_bytes(b"heaptrack")
            # Folded Heaptrack stacks are root-to-leaf. The outer Result type
            # must not override the leaf-nearest concrete Cranelift owner.
            stack = (
                "phase0::run::<core::result::Result<(), PlatformError>>;"
                "wasmtime_internal_cranelift::compiler::Compiler::compile;"
                "alloc::raw_vec::RawVec::with_capacity;__rust_alloc"
            )
            allocations.write_text(f"{stack} 41\n", encoding="utf-8")
            peak_bytes.write_text(f"{stack} 410\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(AGGREGATOR),
                    "summarize-heaptrack",
                    "--allocation-folded",
                    str(allocations),
                    "--peak-folded",
                    str(peak_bytes),
                    "--raw-heaptrack-data",
                    str(raw_data),
                    "--output",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            categories = json.loads(output.read_text(encoding="utf-8"))["categories"]
            preparation = categories["Wasmtime engine and component preparation"]
            diagnostics = categories["result mapping and diagnostics"]
            self.assertEqual(preparation["allocation_calls"], 41)
            self.assertEqual(preparation["allocation_peak_bytes"], 410)
            self.assertIn("wasmtime_internal_cranelift", preparation["sample_owner_frames"][0])
            self.assertEqual(diagnostics["allocation_calls"], 0)
            self.assertEqual(diagnostics["allocation_peak_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
