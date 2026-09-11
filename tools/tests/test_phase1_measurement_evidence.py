from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.phase1_evidence.aggregate import aggregate_suites
from tools.phase1_evidence.common import EvidenceError, canonical, decode, read_json, reference
from tools.phase1_evidence.policy import RSS_ALLOWANCE, reclamation
from tools.phase1_evidence.raw import read_raw
from tools.phase1_evidence.suite import validate_suite
from tools.tests.phase1_measurement_fixtures import refresh, rows, sample, save_rows, suite


class Phase1MeasurementEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_scale_and_soak_smoke_are_observations_not_full_gate(self):
        path = suite(self.root, ("scale", "soak"))
        result = aggregate_suites([path], self.root)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["phase1_completion"], "incomplete")
        self.assertEqual(result["kinds"]["scale"]["status"], "passed")
        self.assertEqual(result["kinds"]["benchmark"]["status"], "incomplete")
        soak = next(run for run in result["runs"] if run["kind"] == "soak")
        self.assertEqual(soak["reclamation"]["status"], "observed-only")

    def test_all_extra_repetitions_are_retained(self):
        path = suite(self.root, repetitions=3)
        result = aggregate_suites([path], self.root)
        self.assertEqual(result["kinds"]["scale"]["attempted_runs"], 3)
        self.assertEqual(len(result["kinds"]["scale"]["metrics"][0]["representatives"]), 3)

    def test_benchmark_populations_and_concurrent_elapsed_are_separate(self):
        result = aggregate_suites([suite(self.root, ("benchmark",))], self.root)
        run = result["runs"][0]
        metrics = {item["name"]: item for item in run["metrics"]}
        self.assertEqual(metrics["prepare.initial"]["statistics"]["count"], "1")
        self.assertEqual(metrics["prepare.cold"]["statistics"]["count"], "4")
        self.assertEqual(metrics["cancel_released_queue_rpc.rpc_latency"]["statistics"]["count"], "20")
        self.assertEqual(run["throughput"]["cancel_released_queue_rpc"]["successful_invocations"], "12")
        self.assertEqual(run["summary"]["work"]["invoke_attempts"], "85")

    def test_rehashed_wrong_scheduler_sum_is_rejected(self):
        def cross(data):
            event = next(row for row in data if row["kind"] == "benchmark-batch")
            event["payload"]["scheduler"]["wait_sum_micros"] = "11"
        self.mutate_raw(cross, "benchmark")

    def test_rehashed_success_cannot_impersonate_fault_population(self):
        def cross(data):
            event = next(row for row in data if row["kind"] == "benchmark-call" and row["payload"]["boundary"] == "fault_fuel")
            event["payload"]["invocation"].update(case="success", outcome="success")
        self.mutate_raw(cross, "benchmark")

    def test_rehashed_crossed_management_release_is_rejected(self):
        def cross(data):
            event = next(row for row in data if row["kind"] == "benchmark-management")
            event["payload"]["release_digest"] = data[0]["payload"]["identity"]["fixtures"][1]["sha256"]
        self.mutate_raw(cross, "benchmark")

    def test_rehashed_duplicate_initial_preparation_is_rejected(self):
        def cross(data):
            event = next(row for row in data if row["kind"] == "benchmark-prepare" and row["payload"]["operation"] == "cold")
            event["payload"]["operation"] = "initial"
        self.mutate_raw(cross, "benchmark")

    def test_rehashed_benchmark_metadata_cannot_cross_fixture(self):
        def cross(data):
            event = next(row for row in data if row["kind"] == "benchmark-input")
            event["payload"]["manifest_sha256"] = data[1]["payload"]["fixtures"][1]["capsule"]["sha256"]
        self.mutate_raw(cross, "benchmark")

    def mutate_raw(self, mutation, kind="scale"):
        path = suite(self.root, (kind,))
        document = read_json(path)
        raw_path = self.root / document["runs"][0]["report"]["path"]
        data = [json.loads(line) for line in raw_path.read_text().splitlines()]
        mutation(data)
        save_rows(raw_path, data)
        refresh(self.root, document)
        with self.assertRaises(EvidenceError):
            validate_suite(path)

    def test_rehashed_scale_counts_cannot_replace_missing_scale(self):
        self.mutate_raw(lambda data: data[5]["payload"].update(registered_deployments="2"))

    def test_rehashed_dormant_store_is_rejected(self):
        self.mutate_raw(lambda data: data[5]["payload"]["sample"]["backend"].update(stores_created="1"))

    def test_rehashed_thread_growth_is_rejected(self):
        def grow(data):
            observed = data[5]["payload"]["sample"]["resources"]
            observed["taskCount"] = observed["process"]["threadCount"] = "5"
        self.mutate_raw(grow)

    def test_rehashed_live_cancellation_owner_is_rejected(self):
        self.mutate_raw(lambda data: data[5]["payload"]["sample"]["ownership"]["cancellation"].update(active_registrations="1"))

    def test_rehashed_mixed_outcome_omission_is_rejected(self):
        def omit(data):
            batch = next(row["payload"] for row in data if row["kind"] == "soak-batch" and row["payload"]["stage"] == "measured")
            batch["outcome_counts"].pop("malformed")
            batch["outcome_counts"]["success"] = "10"
        self.mutate_raw(omit, "soak")

    def test_missing_inner_cleanup_cannot_be_hidden_by_footer(self):
        def omit(data):
            data.pop(-2)
            data[-1]["sequence"] = str(len(data)-1)
            data[-1]["payload"]["event_count"] = str(len(data)-2)
        self.mutate_raw(omit)

    def test_shutdown_requires_zero_live_owners(self):
        self.mutate_raw(lambda data: data[-1]["payload"]["shutdown"].update(liveStores=1))

    def test_passed_parent_must_reap_same_process(self):
        path = suite(self.root)
        document = read_json(path)
        process = self.root / "scale-01/process.json"
        value = read_json(process)
        value["process_id"] = 124
        process.write_bytes(canonical(value))
        refresh(self.root, document)
        with self.assertRaisesRegex(EvidenceError, "crossed-parent-process"):
            validate_suite(path)

    def test_failed_truncated_attempt_is_retained_not_filtered(self):
        path = suite(self.root, repetitions=2)
        document = read_json(path)
        run = document["runs"][1]
        run.update(status="failed", reason="collector-failed")
        (self.root / run["report"]["path"]).write_bytes(b'{"partial":')
        refresh(self.root, document)
        aggregate = aggregate_suites([path], self.root)
        self.assertEqual(aggregate["kinds"]["scale"]["status"], "failed")
        self.assertEqual(len(aggregate["runs"]), 2)
        self.assertEqual(aggregate["kinds"]["scale"]["metrics"], [])

    def test_load_changes_do_not_rewrite_per_run_identity(self):
        path = suite(self.root)
        document = read_json(path)
        raw_path = self.root / "scale-01/measurements.jsonl"
        data = [json.loads(line) for line in raw_path.read_text().splitlines()]
        per_run = data[0]["payload"]["identity"]
        per_run["environment"]["load_before"] = [0.1, 0.2, 0.3]
        save_rows(raw_path, data)
        (raw_path.parent / "identity.json").write_bytes(canonical(per_run))
        refresh(self.root, document)
        self.assertEqual(validate_suite(path)["runs"][0]["identity"]["environment"]["load_before"], [0.1, 0.2, 0.3])

    def test_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        for data in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.subTest(data=data), self.assertRaises(EvidenceError):
                decode(data)

    def test_rehashed_artifact_path_escape_is_rejected(self):
        path = suite(self.root)
        document = read_json(path)
        document["artifacts"][0]["path"] = "../outside.json"
        path.write_bytes(canonical(document))
        with self.assertRaisesRegex(EvidenceError, "invalid-artifact-path"):
            validate_suite(path)

    def test_schema_documents_accept_selected_realistic_smoke_rows(self):
        from jsonschema import Draft202012Validator
        root = Path(__file__).resolve().parents[2] / "benchmarks/phase1"
        for path in root.glob("*.schema.json"):
            Draft202012Validator.check_schema(read_json(path, 1024*1024))
        schema = read_json(root / "raw.schema.json", 1024*1024)
        validator = Draft202012Validator(schema)
        for kind in ("scale", "soak", "benchmark"):
            for row in rows(kind):
                errors = list(validator.iter_errors(row))
                self.assertFalse(errors, f"schema rejected {kind}/{row['kind']}")
        failed = rows("benchmark")[-1]
        failed["payload"].update(status="failed", reason="measurement-workload-failed", workload_result=None)
        self.assertFalse(list(validator.iter_errors(failed)), "schema rejected retained failed workload")

    def test_rss_allowance_is_fixed_and_includes_all_batches(self):
        baseline = sample("after-warmup", 1, rss=1024)
        measured = [sample("measured", index+2, rss=1024) for index in range(12)]
        final = sample("final", 15, rss=1024)
        values = [baseline, *measured, final]
        observed = reclamation(values, "full")
        self.assertEqual(observed["first_batches"]["count"], "10")
        self.assertEqual(observed["last_batches"]["count"], "10")
        measured[3]["resources"]["process"]["residentMemoryBytes"] = str(1024+RSS_ALLOWANCE+1)
        with self.assertRaisesRegex(EvidenceError, "reclamation-allowance-exceeded"):
            reclamation(values, "full")


if __name__ == "__main__":
    unittest.main()
