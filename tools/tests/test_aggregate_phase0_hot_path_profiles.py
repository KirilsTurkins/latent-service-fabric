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


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def baseline(
    *,
    workers: int = 2,
    pool: int = 2,
    allocator: str = "on_demand",
    cow: bool = True,
    checks: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "latent.phase0.baseline.v2",
        "status": "pass",
        "checks": checks
        or [
            {"name": "cleanup_proven", "passed": True},
            {"name": "fixed_topology", "passed": True},
        ],
        "config": {
            "runtime_workers": workers,
            "pool_capacity": pool,
            "wasmtime_allocator": allocator,
            "wasmtime_copy_on_write_images": cow,
        },
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
        "process_snapshots": [
            {
                "rss_bytes": 1024,
                "virtual_memory_bytes": 2048,
                "file_descriptor_count": 5,
                "thread_count": 3,
                "open_socket_count": 0,
                "listening_socket_count": 0,
            }
        ],
    }


def make_profile(root: Path, name: str, document: dict[str, object]) -> None:
    for tool, report in (
        (
            "perf",
            "Overhead  Command  Shared Object  Symbol\n"
            "  50.00%  phase0-baseline  phase0-baseline  phase0_activation_envelope\n",
        ),
        (
            "allocation",
            "heaptrack: call_echo memcpy FixedCellPool\n"
            "calls to allocation functions: 10 (10/s)\n"
            "total memory leaked: 0B\n",
        ),
    ):
        directory = root / name / tool
        directory.mkdir(parents=True, exist_ok=True)
        write_json(
            directory / "command.json",
            {
                "command": ["phase0-baseline", "--mode", "full"],
                "tool": tool,
            },
        )
        write_json(directory / "raw-results.json", document)
        if tool == "perf":
            (directory / "perf.data").write_bytes(b"perf")
            (directory / "perf-report.txt").write_text(report, encoding="utf-8")
        else:
            (directory / "heaptrack.gz.zst").write_bytes(b"heaptrack")
            (directory / "heaptrack-report.txt").write_text(report, encoding="utf-8")
            (directory / "heaptrack-leaks.txt").write_text(
                "MEMORY LEAKS\ntotal memory leaked: 0B\n", encoding="utf-8"
            )


def make_candidate(root: Path, name: str, expectation: dict[str, object]) -> None:
    document = baseline(
        workers=int(expectation["runtime_workers"]),
        pool=int(expectation["pool_capacity"]),
        allocator=str(expectation["wasmtime_allocator"]),
        cow=bool(expectation["wasmtime_copy_on_write_images"]),
    )
    write_json(root / name / "run-01" / "raw-results.json", document)


class AggregateHotPathProfilesTests(unittest.TestCase):
    def build_archive(self, temporary: Path) -> tuple[Path, Path, Path, Path]:
        profiles = temporary / "profiles"
        candidates = temporary / "candidates"
        document = baseline()
        for name in (
            "cold-preparation",
            "first-activation",
            "warm-execution",
            "failure-containment",
            "cleanup",
            "contention",
        ):
            make_profile(profiles, name, document)
        expectations = {
            "worker-cell-1w-1c": (1, 1, "on_demand", True),
            "worker-cell-2w-2c": (2, 2, "on_demand", True),
            "worker-cell-2w-4c": (2, 4, "on_demand", True),
            "worker-cell-4w-2c": (4, 2, "on_demand", True),
            "on-demand-cow-disabled": (2, 2, "on_demand", False),
            "pooling-cow-disabled": (2, 2, "pooling", False),
            "pooling-cow-enabled": (2, 2, "pooling", True),
        }
        for name, (workers, pool, allocator, cow) in expectations.items():
            make_candidate(
                candidates,
                name,
                {
                    "runtime_workers": workers,
                    "pool_capacity": pool,
                    "wasmtime_allocator": allocator,
                    "wasmtime_copy_on_write_images": cow,
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
        write_json(calibration, {"status": "pass", "metrics": metrics})
        return profiles, candidates, host, calibration

    def run_aggregate(
        self,
        temporary: Path,
        archive: tuple[Path, Path, Path, Path] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        profiles, candidates, host, calibration = archive or self.build_archive(temporary)
        return subprocess.run(
            [
                sys.executable,
                str(AGGREGATOR),
                "aggregate",
                "--profiles-directory",
                str(profiles),
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
                "--output-json",
                str(temporary / "aggregate.json"),
                "--output-report",
                str(temporary / "PROFILE.md"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_aggregate_accepts_complete_profile_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            result = self.run_aggregate(temporary)
            self.assertEqual(result.returncode, 0, result.stderr)
            aggregate = json.loads((temporary / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["status"], "pass")
            self.assertEqual(len(aggregate["profiles"]), 6)
            self.assertEqual(len(aggregate["candidates"]), 7)
            self.assertEqual(aggregate["host_observation"]["path"], "host.json")
            first_profile = aggregate["profiles"][0]
            self.assertEqual(
                first_profile["perf"]["report"],
                "profiles/cold-preparation/perf/perf-report.txt",
            )
            self.assertNotIn("report_text", first_profile["perf"])
            self.assertNotIn("report_text", first_profile["allocation"])
            self.assertNotIn("leak_report_text", first_profile["allocation"])
            self.assertEqual(first_profile["top_cpu_samples"][0]["percent"], 50.0)
            self.assertEqual(
                first_profile["metrics"]["component_preparation_micros"], 100.0
            )
            self.assertIn("Wasmtime pooling allocator", (temporary / "PROFILE.md").read_text())

    def test_aggregate_rejects_missing_hard_check_in_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            profiles, candidates, host, calibration = self.build_archive(temporary)
            broken = baseline(checks=[{"name": "cleanup_proven", "passed": True}])
            write_json(profiles / "cleanup" / "allocation" / "raw-results.json", broken)
            result = subprocess.run(
                [
                    sys.executable,
                    str(AGGREGATOR),
                    "aggregate",
                    "--profiles-directory",
                    str(profiles),
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
                    "--output-json",
                    str(temporary / "aggregate.json"),
                    "--output-report",
                    str(temporary / "PROFILE.md"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("different hard-check set", result.stderr)

    def test_aggregate_rejects_an_unreadable_zero_allocation_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = self.build_archive(temporary)
            profiles, _, _, _ = archive
            report = profiles / "warm-execution" / "allocation" / "heaptrack-report.txt"
            report.write_text(
                "calls to allocation functions: 0 (0/s)\ntotal memory leaked: 0B\n",
                encoding="utf-8",
            )
            result = self.run_aggregate(temporary, archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("non-zero Heaptrack allocation evidence", result.stderr)


if __name__ == "__main__":
    unittest.main()
