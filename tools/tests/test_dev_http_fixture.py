"""Real socket ownership and private authority for disposable HTTP fixtures."""
from __future__ import annotations

import copy
from pathlib import Path
import selectors
import socket
import tempfile
import time
import unittest

from tools.dev_workflow import http_fixture, http_peer, node_fixtures, paths, state
from tools.dev_workflow.common import DevError, digest, encode


class HttpFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "test-http"
        paths.new_directory(self.root)
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        self.fixture = {"port": port, "exchanges": [{"method": "POST", "path": "/fixture",
            "requestBody": "aW4=", "status": 200, "responseBody": "cHJpdmF0ZS1yZXBseQ=="}]}
        self.authorization = http_fixture.credential(self.root, self.fixture, create=True)

    def peer(self):
        selector = selectors.DefaultSelector()
        self.addCleanup(selector.close)
        peer = http_peer.Peer(self.root, self.fixture, selector)
        self.addCleanup(peer.close)
        return peer, selector

    def exchange(self, peer, selector, authorization):
        stream = socket.create_connection(("127.0.0.1", self.fixture["port"]), timeout=1)
        self.addCleanup(stream.close)
        stream.sendall(b"POST /fixture HTTP/1.1\r\nHost: 127.0.0.1:" + str(self.fixture["port"]).encode()
            + b"\r\nContent-Length: 2\r\nAuthorization: " + authorization + b"\r\n\r\nin")
        stream.setblocking(False)
        reply = bytearray()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            peer.check()
            for key, events in selector.select(.01):
                peer.event(key, events)
            try:
                raw = stream.recv(4096)
                if not raw:
                    return bytes(reply)
                reply.extend(raw)
            except BlockingIOError:
                pass
        self.fail("fixture exchange exceeded its owned test deadline")

    def test_unauthenticated_client_receives_no_fixture_and_valid_client_still_works(self):
        peer, selector = self.peer()
        reply = self.exchange(peer, selector, b"Bearer wrong-workspace")
        self.assertTrue(reply.startswith(b"HTTP/1.1 401"))
        self.assertNotIn(b"private-reply", reply)
        self.assertEqual(peer.completed, 0)
        reply = self.exchange(peer, selector, self.authorization)
        self.assertTrue(reply.endswith(b"private-reply"))
        self.assertEqual(peer.completed, 1)
        self.assertEqual(peer.rejected, 1)
        self.assertNotIn(self.authorization, encode(peer.observation()))

    def test_other_workspace_has_distinct_credential_and_cannot_contact_peer(self):
        other = self.root.parent / "test-other"
        paths.new_directory(other)
        second = http_fixture.credential(other, self.fixture, create=True)
        self.assertNotEqual(second, self.authorization)
        peer, selector = self.peer()
        self.assertTrue(self.exchange(peer, selector, second).startswith(b"HTTP/1.1 401"))

    def test_live_listener_cannot_be_replaced_and_clean_shutdown_allows_restart(self):
        peer, selector = self.peer()
        with self.assertRaisesRegex(DevError, "port-unavailable"):
            http_peer.Peer(self.root, self.fixture, selector)
        self.exchange(peer, selector, self.authorization)
        self.assertEqual(peer.close()["openConnections"], 0)
        restarted = http_peer.Peer(self.root, self.fixture, selector)
        self.addCleanup(restarted.close)
        self.assertTrue(self.exchange(restarted, selector, self.authorization).endswith(b"private-reply"))

    def test_partial_unauthenticated_request_times_out_without_stopping_owned_peer(self):
        peer, selector = self.peer()
        stream = socket.create_connection(("127.0.0.1", self.fixture["port"]), timeout=1)
        self.addCleanup(stream.close)
        stream.sendall(b"POST /fixture")
        for key, events in selector.select(1):
            peer.event(key, events)
        self.assertEqual(len(peer.clients), 1)
        next(iter(peer.clients.values()))["deadline"] = time.monotonic() - 1
        peer.check()
        self.assertEqual(len(peer.clients), 0)
        self.assertIsNone(peer.failure)

    def test_changed_selection_and_credential_are_not_silently_rotated(self):
        changed = copy.deepcopy(self.fixture)
        changed["exchanges"][0]["status"] = 201
        with self.assertRaisesRegex(DevError, "credential-changed"):
            http_fixture.credential(self.root, changed, create=True)
        state.atomic(self.root / "http-fixture-private", "owner.json", {
            "purpose": "disposable-http-fixture", "fixture": digest(encode(self.fixture)),
            "credentialSha256": "sha256:" + "0" * 64})
        with self.assertRaisesRegex(DevError, "credential-changed"):
            http_fixture.credential(self.root, self.fixture, create=True)

    def test_fixture_needs_matching_running_peer_observation(self):
        selected = {"http": self.fixture}
        raw = encode(selected)
        paths.write_new(self.root / "fixture.json", raw)
        cases = [{"fixtures": [{"id": "http", "kind": "controlled-peer", "identity": digest(raw),
                               "configuration": "fixture.json"}]}]
        self.assertEqual(node_fixtures.initialized(self.root, cases, selected), set())
        peer, _selector = self.peer()
        self.assertEqual(node_fixtures.initialized(self.root, cases, selected, {"http": peer.observation()}), {"http"})
        self.assertEqual(node_fixtures.initialized(self.root, cases, selected, {"http": peer.close()}), set())

    def test_fixture_rejects_redirects_ambient_hosts_and_duplicate_exchanges(self):
        for changed in ({**self.fixture, "host": "example.com"}, {**self.fixture, "port": 80},
                        {**self.fixture, "exchanges": self.fixture["exchanges"] * 2},
                        {**self.fixture, "exchanges": [{**self.fixture["exchanges"][0], "status": 302}]}):
            with self.assertRaises(DevError):
                http_fixture.validate(changed)


if __name__ == "__main__":
    unittest.main()
