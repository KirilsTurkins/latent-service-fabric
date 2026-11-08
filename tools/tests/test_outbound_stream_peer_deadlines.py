"""Real peer descriptors at injected clock boundaries, not provider timing proof."""
from __future__ import annotations

import selectors
import socket
import time
import unittest
from unittest.mock import patch

from tools.outbound_stream_adversarial import GatedSmtpPeer


class PeerDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.selector = selectors.DefaultSelector()
        self.addCleanup(self.selector.close)
        self.peer = GatedSmtpPeer(self.selector, fragment_bytes=1024)
        self.addCleanup(self.peer.close)

    def connect(self):
        client = socket.create_connection(("127.0.0.1", self.peer.port), timeout=1)
        self.addCleanup(client.close)
        self.peer.event(self.selector.get_key(self.peer.listener), selectors.EVENT_READ)
        owned, record = next(iter(self.peer.clients.items()))
        return client, owned, record

    def ready(self, owned, interest=selectors.EVENT_READ):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            for key, events in self.selector.select(.002):
                if key.fileobj is owned and events & interest:
                    return key
        self.fail("actual socket readiness was not observed")

    def assert_expired(self, owned):
        observed = self.peer.observation()
        self.assertEqual(owned.fileno(), -1)
        self.assertEqual(observed["openConnections"], 0)
        self.assertEqual(observed["expiredConnections"], 1)
        self.assertEqual(observed["peerDescriptorClosures"], 1)
        self.assertEqual(observed["failure"], "peer-watchdog-expired")
        self.assertFalse(observed["providerRetirementObserved"])
        self.assertFalse(observed["kernelFinalFreeObserved"])

    def test_readable_input_cannot_refresh_an_expired_idle_deadline(self):
        client, owned, record = self.connect()
        original = record["idle"]
        client.sendall(b"NOOP\r\n")
        key = self.ready(owned)
        with patch("tools.outbound_stream_adversarial.time.monotonic", return_value=original):
            self.peer.event(key, selectors.EVENT_READ)
            self.peer.check()
        self.assert_expired(owned)
        self.assertEqual(record["idle"], original)
        self.assertEqual(record["commands"], 0)

    def test_readable_input_cannot_commit_after_the_absolute_deadline(self):
        client, owned, record = self.connect()
        # Inject only time, not parser state: all protocol bytes traverse TCP.
        client.sendall(b"EHLO local\r\nMAIL FROM:<a@owned.invalid>\r\n"
                       b"RCPT TO:<b@owned.invalid>\r\nDATA\r\nlate\r\n.\r\n")
        key = self.ready(owned)
        with patch("tools.outbound_stream_adversarial.time.monotonic",
                   return_value=record["absolute"]):
            self.peer.event(key, selectors.EVENT_READ)
            self.peer.check()
        self.assert_expired(owned)
        self.assertEqual(self.peer.observation()["acceptedMutations"], 0)
        self.assertEqual(record["commands"], 0)

    def test_writable_event_cannot_send_a_committed_reply_after_expiry(self):
        client, owned, record = self.connect()
        client.sendall(b"EHLO local\r\nMAIL FROM:<a@owned.invalid>\r\n"
                       b"RCPT TO:<b@owned.invalid>\r\nDATA\r\naccepted\r\n.\r\n")
        # Read/short-write boundaries are chosen by TCP, not by sendall().
        deadline = time.monotonic() + 1
        while not self.peer.observation()["barriers"]:
            self.assertLess(time.monotonic(), deadline)
            self.peer.event(self.ready(owned), selectors.EVENT_READ)
        self.assertEqual(self.peer.observation()["acceptedMutations"], 1)
        # Drain only the earlier bounded replies, then release the held 250.
        while record["output"]:
            self.assertLess(time.monotonic(), deadline)
            self.peer.event(self.ready(owned, selectors.EVENT_WRITE), selectors.EVENT_WRITE)
        barrier, = self.peer.observation()["barriers"]
        self.peer.release(barrier["attempt"], barrier["sequence"], "reply")
        key = self.selector.get_key(owned)
        with patch("tools.outbound_stream_adversarial.time.monotonic",
                   return_value=record["idle"]):
            self.peer.event(key, selectors.EVENT_WRITE)
            self.peer.check()
        self.assert_expired(owned)
        observed = self.peer.observation()
        self.assertEqual(observed["acceptedMutations"], 1)
        self.assertEqual(observed["sentMutationReplies"], 0)
        self.assertEqual(observed["clientConfirmation"], "not-observed")

    def test_listener_expiry_precedes_accept_even_for_a_queued_connection(self):
        listener = self.peer.listener
        key = self.selector.get_key(listener)
        client = socket.create_connection(("127.0.0.1", self.peer.port), timeout=1)
        self.addCleanup(client.close)
        with patch("tools.outbound_stream_adversarial.time.monotonic",
                   return_value=self.peer.deadline):
            self.peer.event(key, selectors.EVENT_READ)
        observed = self.peer.observation()
        self.assertEqual(listener.fileno(), -1)
        # TCP may already have completed its handshake; this asserts no accept,
        # not denial before network contact by a node or provider.
        self.assertEqual(observed["acceptedConnections"], 0)
        self.assertEqual(observed["openConnections"], 0)
        self.assertEqual(observed["failure"], "peer-watchdog-expired")

    def test_stale_ready_keys_after_close_do_not_reopen_or_recount_owners(self):
        _client, owned, _record = self.connect()
        keys = [self.selector.get_key(owned), self.selector.get_key(self.peer.listener)]
        before = self.peer.close()
        for key in keys:
            self.peer.event(key, selectors.EVENT_READ | selectors.EVENT_WRITE)
        self.assertEqual(self.peer.close(), before)

    def test_live_input_still_progresses_without_extending_absolute_lifetime(self):
        client, owned, record = self.connect()
        original_idle, original_absolute = record["idle"], record["absolute"]
        client.sendall(b"N")
        key = self.ready(owned)
        with patch("tools.outbound_stream_adversarial.time.monotonic",
                   return_value=original_idle - 1):
            self.peer.event(key, selectors.EVENT_READ)
        self.assertEqual(record["input"], b"N")
        self.assertGreater(record["idle"], original_idle)
        self.assertEqual(record["absolute"], original_absolute)
        self.assertIsNone(self.peer.observation()["failure"])
        self.assertGreaterEqual(owned.fileno(), 0)


if __name__ == "__main__":
    unittest.main()
