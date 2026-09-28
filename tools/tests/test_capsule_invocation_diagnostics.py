"""Failure evidence must never turn a failed invocation into a retry or pass."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.phase2_operator_process import Client, WorkflowError
from tools.rust_capsule_node import RecordingClient, assert_value


class InvocationDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.client = RecordingClient("unused", root, None, 0, evidence=root / "evidence")
        self.result = {"activation": "failed-invocation", "startedAtUnixMillis": "5000",
                       "exitCode": 4, "decoded": None, "response": {"outcomeKnown": True}}
        self.requests = []

    def page(self, client, *arguments, **_kwargs):
        self.requests.append(arguments)
        client.calls += 1
        return {"category": "success", "data": {"page": {"nextPageToken": None}}}

    def receipt(self):
        return json.loads((self.client.evidence / "unexpected-invocation-diagnostics.json").read_text())

    def assert_failed(self):
        with self.assertRaisesRegex(WorkflowError, "authoring-application-result"):
            assert_value(self.client, self.result, [1])

    def test_failed_result_stays_unchanged_and_only_recent_audit_is_read(self):
        original = copy.deepcopy(self.result)
        with patch.object(Client, "call", lambda client, *args, **kwargs: self.page(client, *args, **kwargs)):
            self.assert_failed()
        self.assertEqual(self.result, original)
        self.assertEqual(self.requests, [("audit", "query", "--scope", "tenant", "--page-size", "64",
                                          "--from-unix-millis", "4000")])
        self.assertTrue(self.receipt()["auditComplete"])

    def test_success_performs_no_diagnostic_io(self):
        self.result.update(exitCode=0, decoded=[1])
        with patch.object(Client, "call", side_effect=AssertionError("unexpected diagnostic")):
            assert_value(self.client, self.result, [1])
        self.assertFalse((self.client.evidence / "unexpected-invocation-diagnostics.json").exists())

    def test_audit_failure_keeps_original_failure_and_redacts_exception_text(self):
        with patch.object(Client, "call", side_effect=RuntimeError("private diagnostic text")):
            self.assert_failed()
        self.assertEqual(self.receipt()["diagnosticFailure"], "RuntimeError")
        self.assertNotIn("private diagnostic text", json.dumps(self.receipt()))

    def test_repeated_cursor_stops_and_does_not_hide_original_failure(self):
        def cyclic(client, *arguments, **kwargs):
            value = self.page(client, *arguments, **kwargs)
            value["data"]["page"]["nextPageToken"] = "cycle"
            return value
        with patch.object(Client, "call", cyclic):
            self.assert_failed()
        self.assertEqual(len(self.requests), 2)
        self.assertFalse(self.receipt()["auditComplete"])

    def test_page_limit_preserves_incomplete_evidence(self):
        def pages(client, *arguments, **kwargs):
            value = self.page(client, *arguments, **kwargs)
            value["data"]["page"]["nextPageToken"] = str(client.calls)
            return value
        with patch.object(Client, "call", pages):
            self.assert_failed()
        self.assertEqual(len(self.requests), 8)
        self.assertFalse(self.receipt()["auditComplete"])

    def test_byte_limit_preserves_original_failure_without_oversized_output(self):
        with patch.object(Client, "call", return_value={"oversized": "x" * 262145}):
            self.assert_failed()
        self.assertEqual(self.receipt()["audit"], [])
        self.assertEqual(self.receipt()["diagnosticFailure"], "WorkflowError")

    def test_exhausted_original_call_budget_never_starts_another_process(self):
        self.client.control_attempts = 384
        with patch.object(Client, "call", side_effect=AssertionError("unexpected process")):
            self.assert_failed()
        self.assertFalse(self.receipt()["auditComplete"])


if __name__ == "__main__":
    unittest.main()
