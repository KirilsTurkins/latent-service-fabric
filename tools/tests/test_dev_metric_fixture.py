"""Prevent uninitialized metrics, arbitrary diagnostics and incomplete export proofs."""
import copy
from pathlib import Path
import tempfile
import unittest

from tools.dev_workflow import metric_fixture, node_fixtures, paths, portable
from tools.dev_workflow.common import DevError, digest, encode


class MetricFixture(unittest.TestCase):
    def descriptor(self):
        return {"name": "dev.calls", "kind": "counter", "unit": "1", "histogramUpperBounds": [],
                "labels": [{"key": "region", "values": ["east"]}]}

    def receipt(self):
        return {**dict.fromkeys(metric_fixture.COUNTERS, 0), "retired": True, "truncated": False,
                "attempted": 1, "accepted": 1, "capturedRecords": 1,
                "records": [{"name": "latent.application.dev.calls", "unit": "1", "valueBits": "4000000000000000"}]}

    def test_registry_descriptor_contract_rejects_ambient_or_unbounded_metadata(self):
        metric_fixture.validate([self.descriptor()])
        for key, value in (("name", "HOST.hidden"), ("name", "dev/invalid"), ("kind", "unknown"),
                           ("labels", [{"key": "user", "values": ["a"] * 2}]),
                           ("labels", [{"key": "user", "values": ["private\nvalue"]}]),
                           ("histogramUpperBounds", [1]), ("labels", [{}] * 9), ("credential", "private")):
            changed = dict(self.descriptor(), **{key: value})
            with self.assertRaises(DevError):
                metric_fixture.validate([changed])
        for bounds in ([2, 1], [float("inf")], [10 ** 400], [True], [0] * 17):
            with self.assertRaises(DevError):
                metric_fixture.validate([dict(self.descriptor(), kind="histogram", histogramUpperBounds=bounds)])
        for rows in ([], [self.descriptor()] * 2, [dict(self.descriptor(), name=f"dev.n{i}") for i in range(17)]):
            with self.assertRaises(DevError):
                metric_fixture.validate(rows)

    def test_node_requires_matching_real_provider_and_native_uses_identical_descriptors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = {"metrics": [self.descriptor()]}
            raw = encode(selected)
            paths.write_new(root / "fixture.json", raw)
            case = {"fixtures": [{"id": "metrics", "kind": "real-provider", "identity": digest(raw),
                                  "configuration": "fixture.json"}]}
            actual = {"metrics": {"capability": metric_fixture.PROVIDER[0], "profile": metric_fixture.PROVIDER[1],
                                  "service": metric_fixture.SERVICE, "configurationEpoch": "1"}}
            self.assertEqual(node_fixtures.initialized(root, [case], selected), set())
            self.assertEqual(node_fixtures.initialized(root, [case], selected, providers=actual), {"metrics"})
            self.assertEqual(portable.fixture_inputs(root, case["fixtures"]), selected)
            actual["metrics"]["configurationEpoch"] = "2"
            self.assertEqual(node_fixtures.initialized(root, [case], selected, providers=actual), set())
            case["fixtures"][0]["identity"] = digest(b"changed")
            with self.assertRaisesRegex(DevError, "fixture-identity"):
                portable.fixture_inputs(root, case["fixtures"])

    def test_value_only_receipt_rejects_labels_arbitrary_fields_and_unbounded_or_malformed_values(self):
        self.assertEqual(metric_fixture.reclaimed(self.receipt()), self.receipt())
        for key, value in (("records", self.receipt()["records"] * 17), ("attempted", True),
                           ("retired", 1), ("attempted", -1), ("secret", "private")):
            with self.assertRaises(DevError):
                metric_fixture.observation(dict(self.receipt(), **{key: value}))
        for key, value in (("labels", [["private", "value"]]), ("valueBits", "NaN"), ("name", "host.counter")):
            changed = self.receipt()
            changed["records"][0][key] = value
            with self.assertRaises(DevError):
                metric_fixture.observation(changed)

    def test_queue_reservations_missing_exports_and_truncation_cannot_count_as_cleanup(self):
        for key, value in (("retired", False), ("queuedBytes", 1), ("sinkEvictedEntries", 1),
                           ("sinkDroppedOversized", 1), ("records", [])):
            with self.assertRaises(DevError):
                metric_fixture.reclaimed(dict(self.receipt(), **{key: value}))
        changed = copy.deepcopy(self.receipt())
        changed.update(capturedRecords=17, records=changed["records"] * 16, truncated=True, attempted=17, accepted=17)
        with self.assertRaises(DevError):
            metric_fixture.reclaimed(changed)


if __name__ == "__main__":
    unittest.main()
