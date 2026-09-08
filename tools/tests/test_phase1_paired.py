"""Bounded synthetic tests exercise evidence associations after rehashing."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase1_evidence.common import EvidenceError, canonical, write_json
from tools.phase1_paired.aggregate import aggregate, delta
from tools.phase1_paired.common import identity, plan
from tools.phase1_paired.suite import validate
from tools.tests.phase1_paired_fixtures import refresh, suite
from tools.validate_phase1_paired import replay


class PairedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = suite(self.root)

    def test_matched_smoke_retains_both_arms_without_completing_gate(self):
        result = aggregate(self.path, self.root)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["population"]["complete_pairs"], "1")
        self.assertEqual(len(result["arms"]), 2)
        metric = next(item for item in result["pairs"][0]["metrics"] if item["name"] == "semantic_invoke_elapsed_micros")
        self.assertEqual(metric["control"]["count"], "4")
        self.assertEqual(metric["control"]["maximum"], "25")
        self.assertEqual(metric["contrasts"]["median"]["absolute"], "10")

    def test_replay_recomputes_every_statistic(self):
        path = self.root / "aggregate.json"
        result = aggregate(self.path, self.root)
        write_json(path, result)
        self.assertEqual(replay(path), result)
        result["pairs"][0]["metrics"][0]["contrasts"]["median"]["absolute"] = "0"
        path.write_bytes(canonical(result))
        with self.assertRaisesRegex(EvidenceError, "does-not-match"):
            replay(path)

    def test_rehashed_malformed_success_payload_rejected(self):
        self.mutate("control/baseline.json", lambda doc: doc["activation_samples"][0]["outcome"].update(output_utf8="other"))

    def test_rehashed_missing_or_reordered_population_rejected(self):
        self.mutate("candidate/candidate.json", lambda doc: doc["samples"].reverse())

    def test_rehashed_crossed_release_rejected(self):
        self.mutate("candidate/candidate.json", lambda doc: doc["samples"][0]["receipt"].update(release_digest="sha256:" + "0" * 64))

    def test_rehashed_other_process_probe_rejected(self):
        def cross(doc):
            for row in doc["samples"]:
                row["post_call"]["resources"]["identity"]["processId"] = 999
                row["post_call"]["resources"]["process"]["processId"] = 999
            doc["after_release"]["resources"]["identity"]["processId"] = 999
            doc["after_release"]["resources"]["process"]["processId"] = 999
        self.mutate("candidate/candidate.json", cross)

    def test_rehashed_live_store_or_cache_miss_rejected(self):
        self.mutate("candidate/candidate.json", lambda doc: doc["samples"][0]["post_call"]["backend"].update(live_stores="1"))

    def test_rehashed_unreaped_parent_rejected(self):
        self.mutate("candidate/process.json", lambda doc: doc.update(reaped=False))

    def test_rehashed_changed_engine_option_rejected(self):
        self.mutate("candidate/candidate.json", lambda doc: doc["effective_options"].update(fuel_async_yield_interval=None))

    def test_host_change_is_not_accepted_as_paired_treatment(self):
        value = json.loads(self.path.read_bytes())
        value["runs"][1]["identity"]["environment"]["cpu_model"] = "different host"
        self.path.write_bytes(canonical(value))
        with self.assertRaisesRegex(EvidenceError, "confound"):
            validate(self.path)

    def test_partial_failed_attempt_is_retained_and_never_qualifies(self):
        value = json.loads(self.path.read_bytes())
        row = value["runs"][1]
        row.update(status="failed", reason="collector-failed")
        (self.root / row["raw"]["path"]).write_bytes(b'{"unfinished":')
        self.path.write_bytes(canonical(value))
        refresh(self.path)
        result = aggregate(self.path, self.root)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["arms"]), 2)
        self.assertEqual(result["pairs"], [])

    def test_full_cannot_hide_smoke_population(self):
        value = json.loads(self.path.read_bytes())["plan"]
        value["profile"] = "full"
        with self.assertRaisesRegex(EvidenceError, "preset"):
            plan(value)

    def test_dirty_smoke_allowed_but_full_rejected(self):
        value = json.loads(self.path.read_bytes())["runs"][1]["identity"]
        value["source"]["dirty"] = True
        identity(value, "candidate", full=False)
        with self.assertRaisesRegex(EvidenceError, "unclean"):
            identity(value, "candidate", full=True)

    def test_zero_control_never_creates_infinite_percentage(self):
        from decimal import Decimal
        self.assertEqual(delta(Decimal(2), Decimal(0)), {"absolute": "2", "percent": None, "percent_status": "undefined-zero-control"})

    def test_shape_schemas_cover_plan_suite_candidate_and_aggregate(self):
        import jsonschema
        base = Path(__file__).resolve().parents[2] / "benchmarks/phase1"
        suite_value = json.loads(self.path.read_bytes())
        documents = {"plan": suite_value["plan"], "suite": suite_value,
                     "arm": json.loads((self.root / "pair-01/candidate/candidate.json").read_bytes()),
                     "aggregate": aggregate(self.path, self.root)}
        for name, document in documents.items():
            schema = json.loads((base / f"paired-{name}.schema.json").read_bytes())
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.validate(document, schema)

    def test_rehashed_unmatched_whole_startup_cannot_be_claimed(self):
        self.mutate("candidate/candidate.json", lambda doc: doc["startup"].update(comparable_to_historical_startup=True))

    def test_rehashed_missing_live_counter_is_not_measured_zero(self):
        self.mutate("control/baseline.json", lambda doc: doc["activation_samples"][0]["backend_resources_after"].pop("live_stores"))

    def test_rehashed_observed_runtime_threads_must_finish(self):
        self.mutate("control/baseline.json", lambda doc: doc["process_snapshots"][-1].update(thread_count=4))

    def mutate(self, relative, callback):
        path = self.root / "pair-01" / relative
        value = json.loads(path.read_bytes())
        callback(value)
        path.write_bytes(canonical(value))
        refresh(self.path)
        with self.assertRaises((EvidenceError, ValueError)):
            validate(self.path)


if __name__ == "__main__":
    unittest.main()
