"""Finite observer privacy and failure preservation, without guest qualification."""
from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from tools.java_transaction_qualification import campaign, configuration as cfg, evidence, refusal_observation


class Client:
    def __init__(self, root, result):
        self.evidence = evidence.Evidence(root / "evidence")
        self.result, self.calls = result, []
        self.deadline = time.monotonic() + 30

    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class RefusalObservationOracle(unittest.TestCase):
    def test_one_read_records_only_closed_phase_and_reason_without_payload_or_identity(self):
        value = {"category": "success", "data": {"nodes": [{"phase": "queued",
            "terminalState": "rejected", "principalKind": "user", "targetService": cfg.SERVICE,
            "activationId": "private-identity", "diagnostic": {"stage": 1, "reason": 3,
                "message": "private-payload"}, "diagnosticIsTerminal": True}], "nextPageToken": None}}
        with tempfile.TemporaryDirectory() as temporary:
            client = Client(Path(temporary), value)
            refusal_observation.observe(client)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(client.calls[0][0][:2], ("activation", "roots"))
            self.assertLessEqual(client.calls[0][1]["timeout"], 5)
            raw = (client.evidence.directory / "http-refusal-stage-observation.json").read_text()
            self.assertIn('"rootCount":1', raw)
            self.assertIn('"stage":1,"reason":3', raw)
            self.assertNotIn("private", raw)
            self.assertLess(len(raw.encode()), 8192)

    def test_failed_read_does_not_replace_original_http_refusal_or_repeat_request(self):
        for failure in (ValueError("private-error"), {"category": "platform-failure", "data": {}}):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as temporary:
                client = Client(Path(temporary), failure)
                subject = campaign.Campaign.__new__(campaign.Campaign)
                subject.client = client
                with self.assertRaisesRegex(ValueError, "transaction-response-status"):
                    subject.result({"status": 403, "body": b"", "headers": []})
                self.assertEqual(len(client.calls), 1)
                raw = (client.evidence.directory / "http-refusal-stage-observation.json").read_text()
                self.assertIn('"observationAvailable":false', raw)
                self.assertNotIn("private-error", raw)

    def test_expired_original_deadline_starts_no_observer_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = Client(Path(temporary), {})
            client.deadline = time.monotonic() - 1
            refusal_observation.observe(client)
            self.assertEqual(client.calls, [])
            self.assertEqual(client.evidence.files, [])


if __name__ == "__main__":
    unittest.main()
