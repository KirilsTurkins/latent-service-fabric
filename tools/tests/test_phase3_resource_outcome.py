"""Typed probe failures remain failures even when the guest returned normally."""
import unittest
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_workload import blob_diagnostic, success
from tools.phase3_resource_analysis import churn_outcomes

class ResourceProbeOutcomeTests(unittest.TestCase):
    def test_typed_error_is_not_counted_as_successful_provider_work(self):
        rows = [
            {"ordinal": 0, "disposition": "completed", "result": {"category": "success", "value": ["2201"]}},
            {"ordinal": 1, "disposition": "completed", "result": {"category": "success", "value": ["3006"]},
             "providerDiagnostic": blob_diagnostic(["3006"])},
            {"ordinal": 2, "disposition": "not-started"},
            {"ordinal": 3, "disposition": "completed", "result": {"category": "success", "value": ["4"]}},
        ]
        counts = churn_outcomes([{"arrivals": rows}])
        self.assertEqual(counts["blob"], {"arrivals": 2, "successfulProviderWork": 1,
                                        "providerDiagnostic": 1, "otherFailureOrUnfinished": 0})
        self.assertEqual(counts["http"], {"arrivals": 2, "successfulProviderWork": 1,
                                        "providerDiagnostic": 0, "otherFailureOrUnfinished": 1})

    def test_resource_pressure_is_retained_as_provider_failure(self):
        observed = blob_diagnostic(["3006"])
        self.assertEqual(observed["operation"], "write")
        self.assertEqual(observed["error"], "budget-exhausted")
        self.assertFalse(observed["successfulProviderWork"])

    def test_success_and_unknown_values_are_not_interpreted_as_typed_errors(self):
        for value in (["4"], ["2201"], ["9999"], ["3000"], ["3011"], ["03007"], [3007], ["3007", "4"], None):
            with self.subTest(value=value):
                self.assertIsNone(blob_diagnostic(value))

    def test_recovery_requires_the_original_success_value(self):
        for value in ("1006", "3007", "4008", "7010"):
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                success({"result": {"category": "success", "value": [value], "outcomeKnown": True}}, 4)
        success({"result": {"category": "success", "value": ["4"], "outcomeKnown": True}}, 4)
