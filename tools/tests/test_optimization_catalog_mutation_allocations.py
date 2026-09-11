"""Four named frame origins and an independent single reopen frame."""
import unittest

from tools.optimization_backend_revision.catalog_mutations import allocations, model
from tools.optimization_evidence.common import EvidenceError


class CatalogMutationAllocationTests(unittest.TestCase):
    def state(self):
        state = allocations.Attribution("/probe", (("a",), ("b",), ("c",), ("d",)))
        for row in (b"v 10400 3", b"X /probe", b"I 1000 100", b"s 6 /probe",
                    b"s 1 a", b"s 1 b", b"s 1 c", b"s 1 d",
                    b"i 1 1 2", b"i 2 1 3", b"i 3 1 4", b"i 4 1 5",
                    b"t 1 0", b"t 2 1", b"t 3 0", b"t 4 3", b"a a 2", b"a 14 4", b"c 1"):
            state.record(row)
        return state

    def test_fourth_frame_and_union_keep_origin_on_later_frees(self):
        state = self.state()
        for row in (b"+ 0", b"+ 1", b"- 0", b"- 1"):
            state.record(row)
        self.assertEqual([row["allocation_count"] for row in state.statistics], [1, 1, 1, 1, 2])
        self.assertEqual([row["allocated_bytes"] for row in state.statistics], [10, 10, 20, 20, 30])
        self.assertEqual(state.statistics[-1]["peak_live_bytes"], 30)
        self.assertTrue(all(row["live_bytes"] == row["remaining_allocations"] == 0 for row in state.statistics))
        self.assertNotEqual(sum(row["peak_live_bytes"] for row in state.statistics[:-1]), 30)
        with self.assertRaisesRegex(ValueError, "heaptrack-free-without-live-allocation"):
            state.record(b"- 1")

    def test_missing_trace_stays_unresolved_and_never_becomes_selected_zero_evidence(self):
        state = self.state()
        for row in (b"t 0 0", b"a a 5", b"+ 2"):
            state.record(row)
        self.assertEqual(state.unresolved_count, 1)
        self.assertEqual(state.named_count, 0)
        self.assertEqual(state.statistics[-1]["allocation_count"], 0)

    def test_only_profile_modes_select_bounded_actual_frame_sets(self):
        self.assertEqual(allocations.cases("allocation"), model.MUTATIONS)
        self.assertEqual(allocations.cases("allocation-reopen"), ("reopen",))
        self.assertEqual(len(allocations.Attribution("/probe", (("reopen",),)).statistics), 2)
        for mode in ("initial", "reopen", "unknown"):
            with self.subTest(mode=mode), self.assertRaises(EvidenceError):
                allocations.cases(mode)
        for groups in ((), ((),) * 5):
            with self.assertRaises(EvidenceError):
                allocations.Attribution("/probe", groups)


if __name__ == "__main__":
    unittest.main()
