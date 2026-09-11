from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from tools.phase1_evidence.aggregate import aggregate_suites
from tools.phase1_evidence.common import EvidenceError, canonical, read_json, reference
from tools.phase1_evidence.comparison import compare
from tools.phase1_evidence.compatibility import BUILD_FIELDS
from tools.phase1_evidence.phase0 import load_reference
from tools.phase1_evidence.replay import validate_aggregate, validate_comparison
from tools.tests.phase1_benchmark_fixtures import input_record
from tools.tests.phase1_measurement_fixtures import identity, suite

REFERENCE = Path(__file__).resolve().parents[2] / "benchmarks/phase0/calibration/native-linux-2026-08-30-52ac4754/aggregate.json"


def comparable_candidate(prior):
    """Synthetic compatibility fixture, never a measured full-profile report."""
    previous = prior["reference_identity"]
    current = identity()
    current["build"].update(profile="release", rustc=previous["environment"]["rustc"], cargo=previous["environment"]["cargo"])
    current["build"]["overrides"] = {new: str(previous["collector"]["build_configuration"][old]).lower() for new, old in BUILD_FIELDS.items()}
    environment = current["environment"]
    for new, old in (("os", "operating_system"), ("arch", "architecture"), ("kernel", "kernel"), ("cpu_model", "cpu_model"),
                     ("logical_cpus", "logical_cpu_count"), ("memory_total_bytes", "total_memory_bytes")):
        environment[new] = str(previous["environment"][old])
    observed = prior["host_observations"]["runs"][0]
    environment["virtualization"] = observed["virtualization"]
    environment["allocator"] = {"LD_PRELOAD": observed["allocator"]["ld_preload"], "MALLOC_CONF": observed["allocator"]["malloc_conf"]}
    environment["cpu_policy"] = observed["cpu_frequency_policy"]["observed"]
    inputs = input_record()
    # Supply explicitly synthetic observations for the compatibility unit case.
    # The real retained reference omits these and remains not_comparable.
    previous["config"].update({key: inputs["backend_options"][key] for key in
        ("fuel_async_yield_interval", "maximum_wasm_stack_bytes", "async_stack_bytes", "hostcall_fuel")})
    previous["config"].update({key: inputs["budget"][key] for key in ("wall_time_limit_millis", "log_bytes")})
    inputs.update(component_digest=previous["artifact"]["component_digest"], component_size_bytes=str(previous["artifact"]["component_bytes"]))
    inputs["budget"]["cpu_fuel"] = str(previous["config"]["fuel"])
    metric = {"name": "prepare.initial", "boundary": "wasmtime.prepare-for-use.v1", "unit": "us", "statistics": {"median": "50000"}}
    run = {"kind": "benchmark", "identity": current, "benchmark_input": inputs, "status": "passed", "metrics": [metric]}
    return {"profile": "full", "kinds": {"benchmark": {"status": "passed", "metrics": [metric]}}, "runs": [copy.deepcopy(run) for _ in range(7)]}


class MeasurementComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.prior = load_reference(REFERENCE)[0]

    def test_exact_engine_cold_population_can_compare(self):
        result = compare(comparable_candidate(self.prior), self.prior)["comparisons"][0]
        self.assertEqual(result["status"], "comparable")
        self.assertEqual(result["delta"], "391")

    def test_same_cpu_does_not_remove_component_mismatch(self):
        candidate = comparable_candidate(self.prior)
        candidate["runs"][0]["benchmark_input"]["component_digest"] = "sha256:" + "a"*64
        result = compare(candidate, self.prior)["comparisons"][0]
        self.assertEqual(result["status"], "not_comparable")
        self.assertIn("component-input-mismatch", result["reasons"])
        self.assertEqual(result["phase0_value"], "49609")
        self.assertIsNone(result["delta"])

    def test_missing_engine_options_never_imply_historical_defaults(self):
        candidate = comparable_candidate(self.prior)
        self.prior["reference_identity"]["config"].pop("fuel_async_yield_interval")
        result = compare(candidate, self.prior)["comparisons"][0]
        self.assertIn("unobserved-reference-engine-fuel-async-yield-interval", result["reasons"])
        self.assertEqual(result["status"], "not_comparable")
        self.assertIsNone(result["delta"])

    def test_rpc_boundary_cannot_be_relabelled_as_direct_latency(self):
        candidate = comparable_candidate(self.prior)
        candidate["kinds"]["benchmark"]["metrics"][0]["name"] = "warm_rpc.rpc_latency"
        result = compare(candidate, self.prior)["comparisons"][0]
        self.assertIn("rpc-versus-direct-invocation-boundary", result["reasons"])
        self.assertIsNone(result["relative_change_percent"])

    def test_matched_warm_population_requires_matching_budget(self):
        candidate = comparable_candidate(self.prior)
        candidate["kinds"]["benchmark"]["metrics"][0]["name"] = "warm_rpc.guest_call_micros"
        warm = {"warm_echo.guest_call_micros": {"unit": "us", "value": "10"}}
        self.assertEqual(compare(candidate, self.prior, warm)["comparisons"][0]["status"], "comparable")
        candidate["runs"][0]["benchmark_input"]["budget"]["cpu_fuel"] = "10000000000"
        self.assertIn("activation-fuel-budget-mismatch", compare(candidate, self.prior, warm)["comparisons"][0]["reasons"])

    def test_zero_reference_has_absolute_delta_but_no_ratio(self):
        candidate = comparable_candidate(self.prior)
        candidate["kinds"]["benchmark"]["metrics"][0]["name"] = "warm_rpc.component_post_return_micros"
        result = compare(candidate, self.prior, {"warm_echo.component_post_return_micros": {"unit": "us", "value": "0"}})["comparisons"][0]
        self.assertEqual(result["status"], "comparable")
        self.assertIsNone(result["relative_change_percent"])
        self.assertEqual(result["delta"], "50000")

    def test_unverified_forged_reference_is_rejected(self):
        value = copy.deepcopy(self.prior)
        value["metrics"]["component_preparation_micros"]["run_representatives"]["median"] = 1
        path = self.root / "reference.json"
        path.write_bytes(canonical(value))
        with self.assertRaisesRegex(EvidenceError, "unverified-phase0-reference"):
            load_reference(path)

    def test_replayed_aggregate_rejects_changed_statistic(self):
        source = suite(self.root)
        aggregate = aggregate_suites([source], self.root)
        path = self.root / "aggregate.json"
        path.write_bytes(canonical(aggregate))
        validate_aggregate(path)
        aggregate["runs"][0]["metrics"][0]["statistics"]["median"] = "999"
        path.write_bytes(canonical(aggregate))
        with self.assertRaisesRegex(EvidenceError, "aggregate-does-not-match"):
            validate_aggregate(path)

    def test_smoke_comparison_replays_and_retains_noncomparability(self):
        source = suite(self.root, ("benchmark",))
        candidate = aggregate_suites([source], self.root)
        path = self.root / "aggregate.json"
        path.write_bytes(canonical(candidate))
        prior_path = self.root / "phase0-reference.json"
        prior_path.write_bytes(REFERENCE.read_bytes())
        value = {"schema": "latent.phase1.measurement-comparison.v1", "phase1_completion": "incomplete", "observational_only": True,
            "candidate": reference(path, self.root), "reference": reference(prior_path, self.root), "reference_validation": "retained-aggregate",
            **compare(candidate, self.prior)}
        comparison = self.root / "comparison.json"
        comparison.write_bytes(canonical(value))
        validate_comparison(comparison)
        self.assertEqual(value["summary"]["comparable_metrics"], 0)
        value["comparisons"][0]["delta"] = "123"
        comparison.write_bytes(canonical(value))
        with self.assertRaisesRegex(EvidenceError, "comparison-does-not-match"):
            validate_comparison(comparison)


if __name__ == "__main__":
    unittest.main()
