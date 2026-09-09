"""Old receipts remain valid; forged cleanup capacity/joins cannot qualify."""
import copy
import unittest

from tools.phase1_cleanup_shutdown import (
    FLAGS, LIVE, NUMBERS, validate_cleanup_shutdown, validate_cleanup_snapshot,
)
from tools.phase1_evidence.common import EvidenceError, require
from tools.phase1_evidence.resources import shutdown
from tools.optimization_evidence.suite import shutdown as external_shutdown
from tools.validate_phase1_conformance import verify_shutdown
from tools.tests.test_phase1_compiler_shutdown import compiler, report, validate_all


def cleanup():
    return {"capacity": 68, "accepting": False, "driverAlive": False,
            "driverJoined": True, "reserved": 0, "queued": 0, "running": 0,
            "handoffs": 7, "completed": 7, "timedOut": 0, "panicked": 0,
            "fallbacks": 0, "failed": False}


class CleanupShutdownTests(unittest.TestCase):
    def rejected_by_every_adapter(self, value):
        validators = (shutdown, verify_shutdown,
                      lambda item: external_shutdown({"schemaVersion": "latent.standalone.status.v1",
                          "event": "stopped", "clean": True, "report": item}, "lsf"))
        for validator in validators:
            with self.subTest(adapter=validator.__name__), self.assertRaises(ValueError):
                validator(value)

    def test_original_receipts_and_independent_compiler_extension_remain_valid(self):
        for extension in ({}, {"compiler": compiler()}, {"cleanup": cleanup()},
                          {"compiler": compiler(), "cleanup": cleanup()}):
            value = report() | extension
            original = copy.deepcopy(value)
            validate_all(value)
            self.assertEqual(value, original)
        # Safe quarantine and reclaimed ownership remain distinct old claims.
        validate_all(report() | {"quarantinedCells": 2})

    def test_each_adapter_rejects_a_present_incomplete_or_false_join(self):
        for changes in ({"driverJoined": False}, {"driverAlive": True},
                        {"accepting": True}, {"failed": True}):
            with self.subTest(changes=changes):
                self.rejected_by_every_adapter(report() | {"cleanup": cleanup() | changes})
        for value in (None, {}, cleanup() | {"unexpected": 0}):
            with self.subTest(value=value):
                self.rejected_by_every_adapter(report() | {"cleanup": value})
        for key in cleanup():
            value = cleanup()
            del value[key]
            with self.subTest(missing=key), self.assertRaises(EvidenceError):
                validate_cleanup_shutdown(value, require)

    def test_native_types_and_u64_bounds_cannot_be_faked(self):
        for key in NUMBERS:
            for value in (True, -1, 2**64, 0.0, "0"):
                with self.subTest(key=key, value=value), self.assertRaises(EvidenceError):
                    validate_cleanup_shutdown(cleanup() | {key: value}, require)
        for key in FLAGS:
            for value in (0, 1, None, "false"):
                with self.subTest(key=key, value=value), self.assertRaises(EvidenceError):
                    validate_cleanup_shutdown(cleanup() | {key: value}, require)

    def test_live_slot_remains_charged_even_after_a_claimed_join(self):
        for key in LIVE:
            value = cleanup() | {key: 1}
            if key != "reserved":
                value["handoffs"] += 1
            with self.subTest(key=key):
                self.rejected_by_every_adapter(report() | {"cleanup": value})

    def test_transient_snapshot_conserves_slots_and_distinct_outcomes(self):
        value = cleanup() | {"capacity": 4, "accepting": True, "driverAlive": True,
                             "driverJoined": False, "reserved": 1, "queued": 1,
                             "running": 2, "handoffs": 10}
        validate_cleanup_snapshot(value, require)
        for changes in ({"capacity": 0}, {"capacity": 1025}, {"reserved": 2},
                        {"handoffs": 9}, {"completed": 8}, {"driverJoined": True}):
            with self.subTest(changes=changes), self.assertRaises(EvidenceError):
                validate_cleanup_snapshot(value | changes, require)

    def test_conservative_disposal_is_retained_but_never_clean_acknowledgement(self):
        for outcome in ("timedOut", "panicked", "fallbacks"):
            value = cleanup() | {"completed": 6, outcome: 1, "failed": True}
            validate_cleanup_snapshot(value, require)
            with self.subTest(outcome=outcome), self.assertRaises(EvidenceError):
                validate_cleanup_shutdown(value, require)
            # Erasing only the failed flag cannot disguise conservative loss.
            self.rejected_by_every_adapter(report() | {"cleanup": value | {"failed": False}})


if __name__ == "__main__":
    unittest.main()
