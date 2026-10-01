"""External fixture retention and wire oracles; no platform admission evidence."""
import hashlib
import json
import socket
import tempfile
import time
import unittest
from pathlib import Path

from tools.java_transaction_qualification import provider


class RecipientTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.peer = provider.Recipient(self.root, "a" * 64, b"fixture-token")
        self.horizon = str(time.time_ns() // 1_000_000 + 590_000)

    def fields(self, effect="b" * 64):
        return {
            "authorization": "Bearer fixture-token", "idempotency-key": effect,
            "x-lsf-effect-contract": provider.CONTRACT,
            "x-lsf-effect-provider-incarnation": "a" * 64,
            "x-lsf-effect-body-sha256": hashlib.sha256(provider.PAYLOAD).hexdigest(),
            "x-lsf-effect-retain-until": self.horizon,
            "content-type": "application/octet-stream",
        }

    def call(self, peer=None, method="PUT", effect="b" * 64, fields=None, body=None):
        return (peer or self.peer).handle(
            method, provider.PREFIX + effect, fields or self.fields(effect),
            (provider.PAYLOAD if method == "PUT" else b"") if body is None else body)

    def mode(self, selected):
        (self.root / "mode").write_text(selected, encoding="ascii")

    def test_durable_acceptance_reopen_and_duplicate_preserve_original_receipt(self):
        status, original, disconnected = self.call()
        self.assertEqual((status, disconnected), (201, False))
        raw = (self.root / ("b" * 64 + ".json")).read_bytes()
        reopened = provider.Recipient(self.root, "a" * 64, b"fixture-token")
        self.assertEqual(self.call(reopened), (200, original, False))
        self.assertEqual(self.call(reopened, method="GET"), (200, original, False))
        self.assertEqual((reopened.accepted, reopened.applied, reopened.retained), (0, 0, 1))
        self.assertEqual((self.root / ("b" * 64 + ".json")).read_bytes(), raw)

    def test_reserved_record_finishes_once_without_overwriting_original_acceptance(self):
        self.mode("reserve-once")
        status, reserved, _ = self.call()
        self.assertEqual((status, reserved["state"], reserved["receipt"]), (202, "reserved", None))
        raw = (self.root / ("b" * 64 + ".json")).read_bytes()
        reopened = provider.Recipient(self.root, "a" * 64, b"fixture-token")
        self.assertEqual(self.call(reopened, method="GET"), (200, reserved, False))
        status, applied, _ = self.call(reopened)
        self.assertEqual((status, applied["state"]), (201, "applied"))
        self.assertEqual(self.call(reopened), (200, applied, False))
        self.assertEqual(reopened.applied, 1)
        self.assertEqual((self.root / ("b" * 64 + ".json")).read_bytes(), raw)
        reopened = provider.Recipient(self.root, "a" * 64, b"fixture-token")
        self.assertEqual(self.call(reopened, method="GET"), (200, applied, False))

    def test_accepted_disconnect_and_lookup_ambiguity_keep_external_fact_distinct(self):
        self.mode("accept-ambiguous")
        status, original, disconnected = self.call()
        self.assertEqual((status, disconnected), (201, True))
        self.assertEqual(self.call(method="GET"), (200, original, True))
        self.mode("reply")
        self.assertEqual(self.call(method="GET"), (200, original, False))
        self.assertEqual((self.peer.accepted, self.peer.applied), (1, 1))
        self.assertFalse(self.peer.observation()["recipientDeliveryQualified"])

    def test_wrong_credentials_conflicting_facts_and_payload_never_create_acceptance(self):
        fields = self.fields()
        fields["authorization"] = "Bearer foreign-token"
        self.assertEqual(self.call(fields=fields), (401, None, False))
        self.assertEqual(self.peer.retained, 0)
        with self.assertRaises(ValueError):
            self.call(body=b"another-body")
        self.call()
        original = (self.root / ("b" * 64 + ".json")).read_bytes()
        fields = self.fields()
        fields["x-lsf-effect-body-sha256"] = "f" * 64
        self.assertEqual(self.call(fields=fields), (409, None, False))
        with self.assertRaises(ValueError):
            provider.Recipient(self.root, "c" * 64, b"fixture-token")
        self.assertEqual((self.root / ("b" * 64 + ".json")).read_bytes(), original)

    def test_retained_cap_survives_reopen_and_expiry_never_readmits_original_effect(self):
        for index in range(32):
            self.call(effect=f"{index:064x}")
        reopened = provider.Recipient(self.root, "a" * 64, b"fixture-token")
        with self.assertRaises(ValueError):
            self.call(reopened, effect="f" * 64)
        fields = self.fields("0" * 64)
        fields["x-lsf-effect-retain-until"] = self.horizon
        from unittest.mock import patch
        with patch.object(provider.time, "time_ns", return_value=int(self.horizon) * 1_000_000):
            self.assertEqual(self.call(reopened, effect="0" * 64, fields=fields), (410, None, False))
        self.assertEqual(reopened.retained, 32)

    def test_malformed_present_retained_record_and_unknown_paths_refuse_reopen(self):
        self.call()
        path = self.root / ("b" * 64 + ".json")
        row = json.loads(path.read_bytes())
        row["grant"] = True
        path.write_text(json.dumps(row), encoding="utf-8")
        with self.assertRaises(ValueError):
            provider.Recipient(self.root, "a" * 64, b"fixture-token")
        path.unlink()
        (self.root / "unknown.json").write_text("{}", encoding="ascii")
        with self.assertRaises(ValueError):
            provider.Recipient(self.root, "a" * 64, b"fixture-token")

    def test_actual_socket_frame_parser_rejects_duplicate_and_unbounded_fields(self):
        for frame, accepted in [
            (b"GET /fixed HTTP/1.1\r\nContent-Length: 0\r\n\r\n", True),
            (b"GET /fixed HTTP/1.1\r\nX: a\r\nx: b\r\n\r\n", False),
            (b"GET /fixed HTTP/1.1\r\nContent-Length: 4097\r\n\r\n", False),
        ]:
            left, right = socket.socketpair()
            with left, right:
                left.sendall(frame)
                if accepted:
                    self.assertEqual(provider.request(right, time.monotonic() + 2),
                                     ("GET", "/fixed", {"content-length": "0"}, b""))
                else:
                    with self.assertRaises(ValueError):
                        provider.request(right, time.monotonic() + 2)


if __name__ == "__main__":
    unittest.main()
