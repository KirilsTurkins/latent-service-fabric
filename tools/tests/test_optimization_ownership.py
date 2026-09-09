"""Finite populations and allocation lifetimes, without benchmark execution."""
import unittest

from tools.optimization_revision_runner import ownership, recovery
from tools.optimization_runner.plans import cases
from tools.optimization_backend_revision.ownership import model
from tools.optimization_backend_revision.ownership.allocations import Attribution


class PopulationTests(unittest.TestCase):
    def test_external_cases_are_exact_original_frames_and_no_hidden_prewarm(self):
        for profile, expected in (("smoke", 38), ("full", 924)):
            selected = ownership.plan(profile)
            originals = {row["id"]: row for row in cases(profile)}
            self.assertEqual(selected["cases"], [originals[name] for name in ownership.CASE_IDS])
            self.assertEqual(selected["setup_cases"], [])
            self.assertEqual(sum(row["client_plan"]["warmup_attempts"] + row["client_plan"]["measured_attempts"]
                                 for row in selected["cases"]), expected)
        self.assertEqual(recovery.plan("full")["setup_cases"], ["prewarm-echo"])

    def test_all_explicit_populations_include_proofs_and_profile_warmup(self):
        for profile, expected, children in (("smoke", 164, 14), ("full", 16096, 26)):
            external = ownership.plan(profile)
            total = external["repetitions"] * 2 * sum(row["client_plan"]["warmup_attempts"]
                + row["client_plan"]["measured_attempts"] for row in external["cases"])
            rows = list(model.population(profile))
            self.assertEqual(len(rows), children)
            for repetition, _, mode, shape in rows:
                plan = model.plan(profile, repetition, mode, shape)
                total += len(plan["shapes"]) * (plan["warmup_per_shape"] + plan["measured_per_shape"]) + len(plan["proofs"])
            self.assertEqual(total, expected)
        setup = model.plan("full", mode="fixtures")
        self.assertEqual((setup["shapes"], setup["proofs"], setup["warmup_per_shape"], setup["measured_per_shape"]), ([], [], 0, 0))

    def test_invalid_shape_repetition_or_mode_cannot_expand_profile(self):
        for kwargs in ({"mode": "allocation", "shape": "unknown"}, {"mode": "allocation", "shape": model.SHAPES[0], "repetition": 2},
                       {"mode": "normal", "shape": model.SHAPES[0]}, {"repetition": True}, {"mode": "adaptive"}):
            with self.assertRaises(ValueError):
                model.plan("full", **kwargs)


class AllocationTests(unittest.TestCase):
    def state(self):
        state = Attribution("/probe", (("constructor",), ("poll",)))
        rows = [b"v 10400 3", b"X /probe", b"I 1000 100", b"s 6 /probe", b"s b constructor", b"s 4 poll",
                b"i 1 1 2", b"i 2 1 3", b"t 1 0", b"t 2 1", b"t 2 0", b"a a 2", b"a 14 3", b"c 1"]
        for row in rows:
            state.record(row)
        return state

    def test_union_counts_once_and_frees_after_frame_exit_refund_origin(self):
        state = self.state()
        for row in (b"+ 0", b"+ 0", b"- 0", b"+ 1", b"- 0", b"- 1"):
            state.record(row)
        constructor, poll, union = state.statistics
        self.assertEqual(constructor["allocation_count"], 2)
        self.assertEqual(poll["allocation_count"], 3)
        self.assertEqual(union["allocation_count"], 3)
        self.assertEqual((union["allocated_bytes"], union["peak_live_bytes"], union["live_bytes"]), (40, 30, 0))
        self.assertEqual(union["remaining_allocations"], 0)
        self.assertNotEqual(union["peak_live_bytes"], constructor["peak_live_bytes"] + poll["peak_live_bytes"])

    def test_unresolved_origin_is_never_proved_zero(self):
        state = self.state()
        for row in (b"t 0 0", b"a a 4", b"+ 2"):
            state.record(row)
        self.assertEqual(state.unresolved_count, 1)
        self.assertEqual(state.statistics[2]["allocation_count"], 0)

    def test_repeated_free_rejects_even_after_the_frame_is_gone(self):
        state = self.state()
        for row in (b"+ 0", b"- 0"):
            state.record(row)
        with self.assertRaises(ValueError):
            state.record(b"- 0")


if __name__ == "__main__":
    unittest.main()
