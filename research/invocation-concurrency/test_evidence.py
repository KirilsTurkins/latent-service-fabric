"""Receipt validation tests; synthetic data here is NOT execution evidence."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.run_invocation_concurrency import CASE_NAMES, SCHEMA, verify_measurements


def valid():
    rows = [{"name": name, "hostOperationsAfterStoreDrop": 0,
             "storeDataDropped": True, "linearMemoryPeakBytes": 65536}
            for name in CASE_NAMES]
    rows[0]["peakHostOperations"] = 1
    rows[1]["peakHostOperations"] = 8
    rows[2]["cancelAcceptedBeforeRetirementWitness"] = True
    for i in [3, 4]:
        rows[i]["hostOperationsStarted"] = 0
    rows[7]["outcome"] = "unsupported-thread-trap"
    rows[8]["outcome"] = "out-of-fuel"
    rows[9]["outcome"] = "epoch-deadline-trap"
    rows[10]["expected"] = (1 << 32) + 35
    pair = [{"name": name, "outcome": "returned", "expected": 9216}
            for name in ["cpu-sequential", "cpu-cooperative"]]
    return {"schemaVersion": SCHEMA, "status": "passed", "productionQualified": False,
            "measurements": rows, "cpuPairedSamples": [copy.deepcopy(pair) for _ in range(7)]}


class EvidenceTests(unittest.TestCase):
    def test_complete_shape_is_accepted(self):
        verify_measurements(valid())

    def test_missing_duplicate_or_reordered_cases_fail(self):
        for kind in ["missing", "duplicate", "reordered"]:
            data = valid()
            if kind == "missing":
                data["measurements"].pop()
            elif kind == "duplicate":
                data["measurements"][1] = data["measurements"][0]
            else:
                data["measurements"].reverse()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify_measurements(data)

    def test_live_owner_and_unmeasured_memory_fail(self):
        for key, value in [("hostOperationsAfterStoreDrop", 1), ("storeDataDropped", False),
                           ("linearMemoryPeakBytes", 0), ("linearMemoryPeakBytes", 17 * 1024 * 1024)]:
            data = valid()
            data["measurements"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                verify_measurements(data)

    def test_serialization_disguised_as_fanout_fails(self):
        data = valid()
        data["measurements"][1]["peakHostOperations"] = 1
        with self.assertRaises(ValueError):
            verify_measurements(data)

    def test_early_cancellation_refund_fails(self):
        data = valid()
        data["measurements"][2]["cancelAcceptedBeforeRetirementWitness"] = False
        with self.assertRaises(ValueError):
            verify_measurements(data)

    def test_successful_fake_thread_and_inline_execution_fail(self):
        for index in [7, 8, 9]:
            data = valid()
            data["measurements"][index]["outcome"] = "returned"
            with self.subTest(index=index), self.assertRaises(ValueError):
                verify_measurements(data)

    def test_missing_samples_and_unequal_work_fail(self):
        data = valid()
        data["cpuPairedSamples"].pop()
        with self.assertRaises(ValueError):
            verify_measurements(data)
        data = valid()
        data["cpuPairedSamples"][0][1]["expected"] = 42
        with self.assertRaises(ValueError):
            verify_measurements(data)

    def test_research_is_not_production_qualification(self):
        data = valid()
        data["productionQualified"] = True
        with self.assertRaises(ValueError):
            verify_measurements(data)
