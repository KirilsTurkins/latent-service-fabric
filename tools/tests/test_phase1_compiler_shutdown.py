"""Missing, forged and unjoined compiler ownership must not replay as clean."""
import copy
import unittest

from tools.phase1_compiler_shutdown import COUNTERS, ZERO, validate_compiler_shutdown
from tools.phase1_evidence.common import EvidenceError, require
from tools.phase1_evidence.resources import ZERO_SHUTDOWN_FIELDS, shutdown
from tools.optimization_evidence.suite import shutdown as external_shutdown
from tools.validate_phase1_conformance import verify_shutdown


def compiler():
    return dict.fromkeys(ZERO + COUNTERS, 0) | {
        "maximum_jobs": 4, "maximum_workers": 2, "maximum_queued_jobs": 2,
        "maximum_waiters": 68, "maximum_waiters_per_job": 68,
        "maximum_ready_preparations": 68, "maximum_document_bytes": 21_233_664,
        "workers_quiescent": 2, "workers_joined": 2, "accepting": False, "failed": False,
    }


def report():
    return dict.fromkeys(ZERO_SHUTDOWN_FIELDS, 0) | {
        "clean": True, "telemetryFlushed": True, "epochHelperJoined": True,
        "quarantinedCells": 0, "telemetryRetainedEntries": 2,
    }


def validate_all(value):
    shutdown(value)
    verify_shutdown(value)
    external_shutdown({"schemaVersion": "latent.standalone.status.v1", "event": "stopped",
                       "clean": True, "report": value}, "lsf")


class CompilerShutdownTests(unittest.TestCase):
    def test_original_reports_and_actual_joined_extension_are_accepted(self):
        value = report()
        validate_all(value)
        value["compiler"] = compiler()
        validate_all(value)

    def test_every_live_owner_prevents_clean_replay(self):
        for key in ZERO:
            with self.subTest(key=key):
                value = compiler()
                value[key] = 1
                with self.assertRaises(EvidenceError):
                    validate_compiler_shutdown(value, require)

    def test_quiescence_without_join_or_closed_admission_is_rejected(self):
        for changes in ({"workers_joined": 0}, {"workers_quiescent": 1},
                        {"accepting": True}, {"failed": True}, {"workers_joined": 3}):
            with self.subTest(changes=changes):
                with self.assertRaises(EvidenceError):
                    validate_all(report() | {"compiler": compiler() | changes})

    def test_missing_null_extra_and_boolean_counts_are_not_zero(self):
        for value in (None, {}, compiler() | {"jobs_started": True},
                      compiler() | {"extra": 0}, compiler() | {"jobs_failed": -1}):
            with self.subTest(value=value):
                with self.assertRaises(EvidenceError):
                    validate_all(report() | {"compiler": value})
        for key in compiler():
            value = compiler()
            del value[key]
            with self.assertRaises(EvidenceError):
                validate_compiler_shutdown(value, require)

    def test_capacity_algebra_is_verified(self):
        for changes in ({"maximum_workers": 0}, {"maximum_workers": 9},
                        {"maximum_queued_jobs": 3}, {"maximum_jobs": 1025},
                        {"maximum_waiters_per_job": 69}, {"maximum_ready_preparations": 0},
                        {"maximum_document_bytes": 0}):
            with self.subTest(changes=changes):
                with self.assertRaises(EvidenceError):
                    validate_compiler_shutdown(compiler() | changes, require)

    def test_validated_input_is_not_mutated(self):
        value = report() | {"compiler": compiler()}
        original = copy.deepcopy(value)
        validate_all(value)
        self.assertEqual(value, original)
