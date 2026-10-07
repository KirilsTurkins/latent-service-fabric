"""Authored compiler receipt boundaries, without claiming guest execution."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.compile_transaction_guests import check_surface, compile_guests
from tools.transaction_guest_variants import HTTP


def contract():
    state = {"types": {"transaction": {"resource": "latent:state/key-value@0.2.0/transaction"}},
             "functions": {"get": {"kind": "async-freestanding", "params": ["borrow-transaction"], "result": "option-value"}}}
    intents = {"types": copy.deepcopy(state["types"]),
               "functions": {"stage": {"kind": "async-freestanding", "params": ["borrow-transaction"], "result": "result-sequence"}}}
    return {"imports": {"latent:state/key-value@0.2.0": state, "latent:intents/staging@0.1.0": intents},
            "exports": {"api": {"update": "async-business-result", "query": "async-fresh-value", "scan": "async-page"}}}


class TransactionGuestCompilerTests(unittest.TestCase):
    def test_authored_surface_keeps_declared_results_and_canonical_async_owners(self):
        expected = contract()
        check_surface(expected, copy.deepcopy(expected), "aggregate")
        for change in ("missing-intents", "sync-get", "forged-owner", "new-export"):
            actual = copy.deepcopy(expected)
            if change == "missing-intents":
                actual["imports"].pop("latent:intents/staging@0.1.0")
            elif change == "sync-get":
                actual["imports"]["latent:state/key-value@0.2.0"]["functions"]["get"]["kind"] = "freestanding"
            elif change == "forged-owner":
                actual["imports"]["latent:intents/staging@0.1.0"]["types"]["transaction"] = "caller-string"
            else:
                actual["exports"]["commit"] = "guest-early-commit"
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_surface(expected, actual, "aggregate")

    def test_forbidden_fixture_requires_an_actual_declared_async_http_import(self):
        expected = contract()
        expected["imports"][HTTP] = {"types": {}, "functions": {"send": {"kind": "async-freestanding", "result": "typed-http-result"}}}
        check_surface(expected, copy.deepcopy(expected), "forbidden-http")
        for change in ("removed", "sync", "other-authority", "positive", "future"):
            actual = copy.deepcopy(expected)
            variant = "forbidden-http"
            if change == "removed":
                actual["imports"].pop(HTTP)
            elif change == "sync":
                actual["imports"][HTTP]["functions"]["send"]["kind"] = "freestanding"
            elif change == "other-authority":
                actual["imports"]["wasi:sockets/tcp@0.2.0"] = {"types": {}, "functions": {}}
            else:
                variant = "aggregate" if change == "positive" else "future"
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_surface(expected, actual, variant)

    def test_failed_capture_retains_failure_and_cannot_claim_compilation_or_signed_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "receipt"
            with patch("tools.compile_transaction_guests.authored_project", side_effect=ValueError("controlled-source-failure")):
                with self.assertRaisesRegex(ValueError, "controlled-source-failure"):
                    compile_guests("rust", output)
            report = json.loads((output / "aggregate/report.json").read_bytes())
            self.assertEqual(report["status"], "failed")
            self.assertFalse(report["compiled"])
            self.assertFalse(report["signedNodeExecutionQualified"])
            self.assertFalse(report["admissionRejectionQualified"])
            self.assertEqual(report["reason"], "controlled-source-failure")
            self.assertFalse((output / "forbidden-http").exists())


if __name__ == "__main__":
    unittest.main()
