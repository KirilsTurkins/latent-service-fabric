"""Event fixture rejects ambient authority, preserves uncertainty and bounds state."""
import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from tools.dev_workflow import event_fixture, event_peer, node_fixtures, paths, state
from tools.dev_workflow.common import DevError, digest, encode


def fixture():
    return {"port": 44222, "exchanges": [{"topic": "dev.event", "payload": "eA==", "mode": "ack"}]}


class EventFixtureTests(unittest.TestCase):
    def test_failed_selector_registration_closes_the_owned_tls_socket(self):
        peer = object.__new__(event_peer.Peer)
        stream = Mock()
        peer.clients = {stream: {}}
        peer.selector = Mock()
        peer.selector.unregister.side_effect = KeyError("registration-did-not-complete")
        peer.close_client(stream)
        self.assertEqual(peer.clients, {})
        stream.close.assert_called_once_with()

    def test_closed_bounded_scope_rejects_wildcards_external_endpoints_and_private_values(self):
        value = fixture()
        self.assertEqual(event_fixture.validate(value), value)
        invalid = []
        for field in ("server", "credential", "certificate", "environment"):
            item = copy.deepcopy(value)
            item[field] = "ambient"
            invalid.append(item)
        for replacement in ("dev.*", "_INBOX.foo", "x" * 129, "dev..x"):
            item = copy.deepcopy(value)
            item["exchanges"][0]["topic"] = replacement
            invalid.append(item)
        for mode in ("retry", "external", None):
            item = copy.deepcopy(value)
            item["exchanges"][0]["mode"] = mode
            invalid.append(item)
        invalid.append({**value, "exchanges": value["exchanges"] * 2})
        invalid.append({**value, "port": True})
        item = copy.deepcopy(value)
        item["exchanges"][0]["payload"] = "eB=="
        invalid.append(item)
        for item in invalid:
            with self.assertRaises(DevError):
                event_fixture.validate(item)

    def test_private_material_is_owned_exactly_and_never_recreated_on_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "test-events"
            root.mkdir(mode=0o700)
            private = root / "event-fixture-private"
            private.mkdir(mode=0o700)
            value = fixture()
            material = {"authorization": b"a" * 64, "ca.der": b"public-ca", "server.pem": b"public-cert", "key.pem": b"private-key"}
            for name, raw in material.items():
                paths.write_new(private / name, raw)
            state.atomic(private, "owner.json", {"purpose": "disposable-event-peer", "fixture": digest(encode(value)),
                "signer": "sha256:" + "0" * 64, "toolInventory": "fixture", "files": {name: digest(raw) for name, raw in material.items()}})
            self.assertEqual(event_fixture.material(root, value)[1], material)
            (private / "key.pem").write_bytes(b"changed")
            with self.assertRaisesRegex(DevError, "private-material-changed"):
                event_fixture.material(root, value)
            self.assertEqual((private / "key.pem").read_bytes(), b"changed")

    def test_peer_counts_received_publish_once_before_dropping_ack(self):
        peer = object.__new__(event_peer.Peer)
        peer.fixture = fixture()
        peer.fixture["exchanges"][0]["mode"] = "drop-ack"
        peer.received = peer.acknowledged = 0
        peer.by_topic = {"dev.event": 0}
        record = {"output": bytearray()}
        headers = b"NATS/1.0\r\nNats-Expected-Stream: LSF_DEV\r\nNats-Msg-Id: lsf-" + b"a" * 64 + b"\r\nContent-Type: application/octet-stream\r\n\r\n"
        peer.publish(record, b"dev.event", b"_INBOX.LSF.test", headers, b"x")
        self.assertTrue(record["drop"])
        self.assertEqual(record["output"], b"")
        self.assertEqual(peer.received, 1)
        self.assertEqual(peer.by_topic, {"dev.event": 1})
        self.assertEqual(peer.acknowledged, 0)
        with self.assertRaisesRegex(DevError, "payload-mismatch"):
            peer.publish(record, b"dev.event", b"_INBOX.LSF.test", headers, b"wrong")
        self.assertEqual(peer.received, 1)

    def test_selected_fixture_requires_live_owned_tls_peer_evidence(self):
        value = {"events": fixture()}
        raw = encode(value)
        cases = [{"fixtures": [{"id": "events", "kind": "controlled-peer", "identity": digest(raw), "configuration": "fixture.json"}]}]
        ready = {"events": {"state": "ready", "kind": "controlled-peer", "authentication": "private-tls-provider-credential",
            "liveBroker": False, "configurationSha256": digest(encode(value["events"])), "failure": None}}
        with patch.object(paths, "read", return_value=raw):
            self.assertEqual(node_fixtures.initialized(Path("."), cases, value, ready), {"events"})
            for replacement in ({}, {"events": {**ready["events"], "state": "stopped"}},
                    {"events": {**ready["events"], "authentication": "none"}},
                    {"events": {**ready["events"], "configurationSha256": "wrong"}},
                    {"events": {**ready["events"], "failure": "listener-lost"}}):
                self.assertEqual(node_fixtures.initialized(Path("."), cases, value, replacement), set())

    def test_connect_rejects_wrong_token_before_accepting_any_publish(self):
        peer = object.__new__(event_peer.Peer)
        peer.authorization = b"a" * 64
        peer.rejected = 0
        record = {"authorized": False, "input": bytearray(b'CONNECT {"auth_token":"wrong"}\r\n'),
                  "commands": 0, "publish": None}
        with patch.object(peer, "close_client") as closed:
            peer.frame("socket", record)
            closed.assert_called_once_with("socket")
        self.assertFalse(record["authorized"])
        self.assertEqual(peer.rejected, 1)
        record["input"] = bytearray(b"HPUB dev.event _INBOX.LSF.1 10 20\r\n")
        with self.assertRaisesRegex(DevError, "authentication-required"):
            peer.frame("socket", record)


if __name__ == "__main__":
    unittest.main()
