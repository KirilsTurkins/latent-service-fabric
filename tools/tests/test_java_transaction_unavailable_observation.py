"""Retain actual unavailable-stage evidence without accepting its generic body."""
from pathlib import Path
import tempfile
import unittest

from tools.java_transaction_qualification import campaign, configuration as cfg
from tools.tests.test_java_transaction_refusal_observation import Client


class UnavailableObservationOracle(unittest.TestCase):
    def test_generic_503_keeps_transaction_header_failure_and_observes_one_root_page(self):
        root = {"phase": "admitted", "terminalState": "platform_failed", "principalKind": "user",
            "targetService": cfg.SERVICE, "diagnostic": {"stage": 1, "reason": 7},
            "diagnosticIsTerminal": True, "activationId": "private-identifier"}
        with tempfile.TemporaryDirectory() as temporary:
            client = Client(Path(temporary), {"category": "success", "data": {
                "nodes": [root], "nextPageToken": None}})
            subject = campaign.Campaign.__new__(campaign.Campaign)
            subject.client = client
            with self.assertRaisesRegex(ValueError, "host-owned-transaction-response-headers"):
                subject.result({"status": 503, "body": b"Unavailable\n", "headers": [
                    ("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")]})
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(client.calls[0][0][:2], ("activation", "roots"))
            raw = (client.evidence.directory / "http-refusal-stage-observation.json").read_text()
            self.assertIn('"rootCount":1', raw)
            self.assertIn('"stage":1,"reason":7', raw)
            self.assertNotIn("private-identifier", raw)
            self.assertLessEqual(client.calls[0][1]["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
