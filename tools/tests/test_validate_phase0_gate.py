from __future__ import annotations

import copy
import unittest

from tools.validate_phase0_gate import (
    BASELINE_SCHEMA,
    REQUIRED_CHECKS,
    REQUIRED_OUTCOMES,
    GateValidationError,
    validate_baseline,
)


def passing_document() -> dict:
    return {
        "schema_version": BASELINE_SCHEMA,
        "status": "pass",
        "production_ready": False,
        "phase1_api_compatible": False,
        "config": {"mode": "smoke"},
        "checks": [
            {"name": name, "passed": True, "expected": "", "observed": ""}
            for name in sorted(REQUIRED_CHECKS)
        ],
        "activation_samples": [
            {"outcome": {"name": name}}
            for name in sorted(REQUIRED_OUTCOMES)
        ],
        "executable_harness": {
            "samples": [{"shutdown_clean": True, "topology_unchanged": True}],
            "failure_recovery_samples": [{"scenario": "trap"}],
        },
    }


class Phase0GateValidationTests(unittest.TestCase):
    def test_passing_baseline_emits_non_production_receipt(self) -> None:
        receipt = validate_baseline(passing_document(), "baseline.json")
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(receipt["required_checks_passed"], 19)
        self.assertFalse(receipt["production_ready"])
        self.assertFalse(receipt["phase1_api_compatible"])

    def test_missing_required_check_fails_closed(self) -> None:
        document = passing_document()
        document["checks"].pop()
        with self.assertRaisesRegex(GateValidationError, "required Phase 0 checks"):
            validate_baseline(document, "baseline.json")

    def test_missing_terminal_outcome_fails_closed(self) -> None:
        document = passing_document()
        document["activation_samples"] = document["activation_samples"][:-1]
        with self.assertRaisesRegex(GateValidationError, "required terminal outcomes"):
            validate_baseline(document, "baseline.json")

    def test_dirty_executable_shutdown_fails_closed(self) -> None:
        document = copy.deepcopy(passing_document())
        document["executable_harness"]["samples"][0]["shutdown_clean"] = False
        with self.assertRaisesRegex(GateValidationError, "shut down cleanly"):
            validate_baseline(document, "baseline.json")


if __name__ == "__main__":
    unittest.main()
