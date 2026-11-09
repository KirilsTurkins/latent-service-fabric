"""Controls for the lost-rejection qualification sequence; not runtime evidence."""
import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import campaign


class LostRejectionControls(unittest.TestCase):
    def run_case(self, lost, *, changed_key=False):
        events = []
        rejection = {"disposition": "rejected", "effect-ids": [], "result": {
            "body-base64": base64.b64encode(json.dumps([{"err": "rejected"}]).encode()).decode()}}
        committed = {"disposition": "committed", "effect-ids": ["effect"]}
        subject = campaign.Campaign.__new__(campaign.Campaign)
        subject.originals = {}
        subject.client = SimpleNamespace(evidence=SimpleNamespace(passed=Mock()))
        query_results = iter([{"none": None}, {"some": [1]} if changed_key else {"none": None}, {"some": [2]}])
        subject.query = Mock(side_effect=lambda count: (None, {"key-version": next(query_results)}))
        def socket(mode, **kwargs):
            events.append((mode, kwargs.get("original_key"), kwargs.get("lose_body", False)))
            if kwargs.get("lose_body"):
                return lost
            return committed if kwargs["original_key"] == "java-original-2" else rejection
        subject.socket = socket
        subject.result = lambda value: value
        subject.wait_effect = Mock()
        def original(key):
            events.append(("original", key, False))
            return rejection
        subject.original = original
        with patch.object(campaign.http, "aggregate", return_value={"count": "3"}), \
             patch.object(campaign.http, "replay"), \
             patch.object(campaign.lifecycle, "lookup", return_value={}), \
             patch.object(campaign, "rpc_result"):
            subject._rejection("publication")
        return events, subject

    def test_recovers_only_after_a_later_committed_command(self):
        events, subject = self.run_case({"status": 422, "bodyLost": True})
        self.assertEqual(events[0], ("command", "java-original-rejection", True))
        self.assertLess(events.index(("command", "java-original-2", False)),
                        events.index(("original", "java-original-rejection", False)))
        self.assertIn("java-original-rejection", subject.originals)
        self.assertTrue(subject.client.evidence.passed.call_args.args[1]["originalResponseBodyLost"])

    def test_rejection_must_preserve_the_business_key_version(self):
        with self.assertRaises(ValueError):
            self.run_case({"status": 422, "bodyLost": True}, changed_key=True)

    def test_success_status_cannot_qualify_as_business_rejection(self):
        with self.assertRaises(ValueError):
            self.run_case({"status": 200, "bodyLost": True})

    def test_received_body_cannot_qualify_as_lost(self):
        with self.assertRaises(ValueError):
            self.run_case({"status": 422, "bodyLost": False})


if __name__ == "__main__":
    unittest.main()
