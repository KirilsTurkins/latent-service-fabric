"""The new diagnostic must preserve complete warmup, cache and owner evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.phase1_evidence.common import EvidenceError
from tools.phase1_paired.artifacts import Artifacts
from tools.phase1_paired.candidate import parse
from tools.tests.phase1_paired_fixtures import suite


class BackendRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        original = json.loads(suite(self.root).read_bytes())
        row = original["runs"][1]
        self.path = self.root / row["raw"]["path"]
        self.plan = original["plan"]
        self.identity = row["identity"]
        self.artifacts = Artifacts(self.root, original["artifacts"])
        self.value = json.loads(self.path.read_bytes())
        self.value.update(schema="latent.optimization.backend-revision-arm.v1", arm="lsf",
                          warmup_method="first-rpc-empty-cache-in-declared-warmup")
        self.value.pop("preparation_elapsed_micros")
        self.value.pop("preparation_cache_after")
        self.value.pop("prepared_release_elapsed_micros")
        final = self.value.pop("after_release")
        for index, sample in enumerate(self.value["samples"]):
            sample["post_call"]["inventory"]["cacheSummary"]["hits"] = str(index)
        final["inventory"]["cacheSummary"] = copy.deepcopy(self.value["samples"][-1]["post_call"]["inventory"]["cacheSummary"])
        self.value["before_shutdown"] = final

    def replay(self):
        return parse(self.value, self.plan, self.identity, self.artifacts, self.path, revision=True)

    def test_first_real_rpc_is_distinct_from_backend_preparation_and_warm_population(self):
        result = self.replay()
        metrics = {row["name"]: row for row in result["metrics"]}
        self.assertNotIn("initial_preparation_micros", metrics)
        self.assertEqual(metrics["first_rpc_empty_cache_micros"]["statistics"]["count"], "1")
        rpc = metrics["semantic_invoke_elapsed_micros"]
        self.assertEqual(rpc["statistics"]["count"], "4")
        self.assertEqual(rpc["boundary"]["control"], rpc["boundary"]["candidate"])
        self.assertEqual(result["samples"], "6")

    def test_old_method_cannot_accept_revision_rows(self):
        with self.assertRaises((ValueError, EvidenceError)):
            parse(self.value, self.plan, self.identity, self.artifacts, self.path)

    def test_current_repository_preparation_cannot_be_labelled_as_old_direct_prepare(self):
        value = json.loads(self.path.read_bytes())
        value["preparation_scope"] = "repository-acquisition-including-verified-refill"
        result = parse(value, self.plan, self.identity, self.artifacts, self.path)
        metric = next(row for row in result["metrics"] if row["name"] == "initial_preparation_micros")
        self.assertEqual(metric["boundary"]["candidate"], value["preparation_scope"])
        self.assertNotEqual(metric["boundary"]["candidate"], metric["boundary"]["control"])
        value["preparation_scope"] = "unrecorded-boundary"
        with self.assertRaisesRegex(EvidenceError, "preparation-scope"):
            parse(value, self.plan, self.identity, self.artifacts, self.path)

    def test_hidden_initial_preparation_or_extra_refill_rejected(self):
        for key, value in [("hits", "1"), ("misses", "2")]:
            with self.subTest(key=key):
                original = copy.deepcopy(self.value)
                self.value["samples"][0]["post_call"]["inventory"]["cacheSummary"][key] = value
                with self.assertRaisesRegex(EvidenceError, "cache-not-reused"):
                    self.replay()
                self.value = original

    def test_last_cache_snapshot_cannot_hide_late_invalidation(self):
        self.value["before_shutdown"]["inventory"]["cacheSummary"]["invalidations"] = "1"
        with self.assertRaisesRegex(EvidenceError, "final-cache-mismatch"):
            self.replay()

    def test_failed_terminal_or_unclean_owner_never_contributes_latency(self):
        for section, key, value in [("receipt", "terminal_state", "cancelled"),
                                    ("post_call", "backend", {"live_stores": "1"})]:
            with self.subTest(section=section):
                original = copy.deepcopy(self.value)
                self.value["samples"][2][section][key] = value
                with self.assertRaises((ValueError, EvidenceError)):
                    self.replay()
                self.value = original

    def test_dropped_or_reordered_warmup_is_rejected(self):
        self.value["samples"].reverse()
        with self.assertRaisesRegex(EvidenceError, "reordered-candidate"):
            self.replay()


if __name__ == "__main__":
    unittest.main()
