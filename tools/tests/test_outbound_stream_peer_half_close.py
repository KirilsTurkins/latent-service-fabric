"""Real TCP send-half-close controls for the gated peer, not guest qualification."""
from __future__ import annotations

import hashlib
import selectors
import socket
import time
import unittest
from unittest.mock import patch

from tools.outbound_stream_adversarial import (
    GREETING, MUTATION_REPLY, MAX_RESPONSE_BYTES, RESPONSE_WINDOW, GatedSmtpPeer,
)
from tools.outbound_stream_fixture import SmtpPeer

ENVELOPE = (b"EHLO local\r\nMAIL FROM:<a@owned.invalid>\r\n"
            b"RCPT TO:<b@owned.invalid>\r\nDATA\r\n")
MESSAGE = b"Subject: half-close\r\n\r\none mutation\r\n"


class PeerHalfCloseTests(unittest.TestCase):
    def setUp(self):
        self.selector = selectors.DefaultSelector()
        self.peers = []
        self.addCleanup(self.selector.close)
        self.addCleanup(self.close_peers)

    def close_peers(self):
        for peer in self.peers:
            peer.close()

    def peer(self, *, peer_type=GatedSmtpPeer, **options):
        peer = peer_type(self.selector, **options)
        self.peers.append(peer)
        return peer

    def step(self, *, read_only=False):
        for key, events in self.selector.select(.005):
            if read_only:
                events &= selectors.EVENT_READ
            if events:
                key.data.event(key, events)
        for peer in self.peers:
            peer.check()

    def pump(self, ready, *, read_only=False):
        deadline = time.monotonic() + 3
        while not ready():
            self.assertLess(time.monotonic(), deadline, "peer progress watchdog failed")
            self.step(read_only=read_only)

    def client(self, peer):
        attempt = peer.attempts + 1
        stream = socket.create_connection(("127.0.0.1", peer.port), timeout=1)
        self.addCleanup(stream.close)
        self.pump(lambda: peer.attempts == attempt, read_only=True)
        return stream

    def owned(self, peer):
        return next(iter(peer.clients))

    def half_close(self, peer, stream, owned):
        # Drive a real FIN to recv() == b"". A timeout cannot stand in for EOF.
        key = self.selector.get_key(owned)
        stream.shutdown(socket.SHUT_WR)
        self.pump(lambda: owned not in peer.clients or peer.clients[owned].get("readEof"),
                  read_only=True)
        return key

    def park(self, peer, stream, owned):
        key = self.half_close(peer, stream, owned)
        self.assertIn(owned, peer.clients, "send half-close discarded a pending reply")
        self.pump(lambda: not peer.clients[owned]["output"])
        self.assertGreaterEqual(owned.fileno(), 0)
        with self.assertRaises(KeyError):
            self.selector.get_key(owned)
        return key

    def mutation(self, peer):
        stream = self.client(peer)
        owned = self.owned(peer)
        stream.sendall(ENVELOPE + MESSAGE + b".\r\n")
        # Keep earlier replies queued so the EOF path must retain their owner.
        self.pump(lambda: peer.observation()["acceptedMutations"] == 1, read_only=True)
        return stream, owned

    def release(self, peer, action):
        barrier, = peer.observation()["barriers"]
        peer.release(barrier["attempt"], barrier["sequence"], action)

    def wire_to_eof(self, stream, *, maximum=MAX_RESPONSE_BYTES + 1024):
        stream.setblocking(False)
        wire = bytearray()

        def finished():
            try:
                chunk = stream.recv(4096)
            except BlockingIOError:
                return False
            wire.extend(chunk)
            self.assertLessEqual(len(wire), maximum, "peer response exceeded its finite bound")
            return not chunk

        self.pump(finished)
        return bytes(wire)

    def test_committed_mutation_survives_client_fin_until_fragmented_reply_is_sent(self):
        peer = self.peer(fragment_bytes=1)
        stream, owned = self.mutation(peer)
        before = peer.observation()
        record = peer.clients[owned]
        original = record["idle"], record["absolute"]
        self.half_close(peer, stream, owned)
        self.assertIn(owned, peer.clients, "client FIN must not discard the committed reply")
        self.assertEqual((record["idle"], record["absolute"]), original)
        self.assertEqual(self.selector.get_key(owned).events, selectors.EVENT_WRITE)
        with self.assertRaisesRegex(ValueError, "prior-replies-not-drained"):
            self.release(peer, "reply")
        self.pump(lambda: not record["output"])
        with self.assertRaises(KeyError):
            self.selector.get_key(owned)
        self.assertEqual(peer.observation()["peerDescriptorClosures"], 0)
        self.release(peer, "reply")
        self.assertEqual(self.selector.get_key(owned).events, selectors.EVENT_WRITE)
        self.assertEqual(peer.sent_replies, 0)
        wire = self.wire_to_eof(stream)
        self.assertTrue(wire.startswith(GREETING))
        self.assertTrue(wire.endswith(MUTATION_REPLY))
        self.assertEqual(wire.count(MUTATION_REPLY), 1)
        observed = peer.observation()
        self.assertEqual(observed["acceptedConnections"], 1)
        self.assertEqual(observed["acceptedMutations"], 1)
        self.assertEqual(observed["sentMutationReplies"], 1)
        self.assertEqual(observed["peerDescriptorClosures"], 1)
        self.assertEqual(observed["mutationRecords"], before["mutationRecords"])
        self.assertEqual(observed["mutationRecords"][0]["sha256"], hashlib.sha256(MESSAGE).hexdigest())
        self.assertEqual(owned.fileno(), -1)
        self.assertIsNone(observed["failure"])

    def test_half_closed_greeting_gate_parks_without_read_or_write_spin(self):
        peer = self.peer(scenario="greeting", fragment_bytes=1)
        stream = self.client(peer)
        owned = self.owned(peer)
        self.park(peer, stream, owned)
        self.assertEqual(self.selector.select(0), [])
        self.assertEqual(peer.observation()["openConnections"], 1)
        self.release(peer, "reply")
        self.assertEqual(self.wire_to_eof(stream), GREETING)
        self.assertEqual(owned.fileno(), -1)
        self.assertEqual(peer.observation()["peerDescriptorClosures"], 1)

    def test_client_fin_during_hostile_response_preserves_finite_output_and_gate(self):
        for scenario in ("oversized-greeting", "unterminated-greeting"):
            with self.subTest(scenario=scenario):
                peer = self.peer(scenario=scenario, fragment_bytes=1024)
                stream = self.client(peer)
                owned = self.owned(peer)
                self.half_close(peer, stream, owned)
                self.assertIn(owned, peer.clients, "FIN truncated the controlled response")
                def output_finished():
                    if owned not in peer.clients:
                        return True
                    self.assertLessEqual(len(peer.clients[owned]["output"]), RESPONSE_WINDOW)
                    return not peer.clients[owned].get("hostileActive")

                self.pump(output_finished)
                if scenario == "unterminated-greeting":
                    self.assertIn(owned, peer.clients)
                    with self.assertRaises(KeyError):
                        self.selector.get_key(owned)
                    self.release(peer, "terminate")
                wire = self.wire_to_eof(stream)
                expected = b"220 " + b"x" * (MAX_RESPONSE_BYTES - 4)
                if scenario == "oversized-greeting":
                    expected = expected[:-2] + b"\r\n"
                else:
                    expected += b"\r\n"
                self.assertEqual(wire, expected)
                self.assertEqual(owned.fileno(), -1)
                self.assertEqual(peer.observation()["peerDescriptorClosures"], 1)
                self.assertIsNone(peer.observation()["failure"])
                peer.close()

    def test_lost_reply_actions_remain_explicit_after_client_fin(self):
        for action in ("close", "reset", "half-close"):
            with self.subTest(action=action):
                peer = self.peer()
                stream, owned = self.mutation(peer)
                self.park(peer, stream, owned)
                self.release(peer, action)
                self.assertEqual(owned.fileno(), -1)
                observed = peer.observation()
                self.assertEqual(observed["acceptedMutations"], 1)
                self.assertEqual(observed["sentMutationReplies"], 0)
                self.assertEqual(observed["releasedBarriers"], 1)
                self.assertEqual(observed["peerDescriptorClosures"], 1)
                self.assertEqual(observed["peerSendHalfCloses"], int(action == "half-close"))
                self.assertEqual(observed["peerResets"], int(action == "reset"))
                self.assertIsNone(observed["failure"])
                peer.close()

    def test_incomplete_data_or_terminator_at_eof_never_commits(self):
        for suffix in (b"uncommitted\r\n", b"uncommitted\r\n.", b"uncommitted\r\n.\r"):
            with self.subTest(suffix=suffix):
                peer = self.peer()
                stream = self.client(peer)
                owned = self.owned(peer)
                stream.sendall(ENVELOPE + suffix)
                self.half_close(peer, stream, owned)
                self.assertNotIn(owned, peer.clients)
                self.assertEqual(peer.observation()["acceptedMutations"], 0)
                self.assertEqual(peer.observation()["barriers"], [])
                self.assertEqual(owned.fileno(), -1)
                peer.close()

    def test_parked_owner_expires_without_refunding_or_claiming_a_reply_early(self):
        peer = self.peer()
        stream, owned = self.mutation(peer)
        self.park(peer, stream, owned)
        record = peer.clients[owned]
        self.assertEqual(peer.observation()["openConnections"], 1)
        self.assertEqual(peer.observation()["peerDescriptorClosures"], 0)
        peer.check(min(record["idle"], record["absolute"], peer.deadline))
        self.assertEqual(owned.fileno(), -1)
        observed = peer.close()
        self.assertEqual(observed["failure"], "peer-watchdog-expired")
        self.assertEqual(observed["expiredConnections"], 1)
        self.assertEqual(observed["acceptedMutations"], 1)
        self.assertEqual(observed["sentMutationReplies"], 0)
        self.assertEqual(observed["peerDescriptorClosures"], 1)
        self.assertEqual(peer.close(), observed)

    def test_stale_ready_key_cannot_reopen_or_recount_a_parked_owner(self):
        peer = self.peer(scenario="greeting")
        stream = self.client(peer)
        owned = self.owned(peer)
        key = self.park(peer, stream, owned)
        before = peer.observation()
        peer.event(key, selectors.EVENT_READ | selectors.EVENT_WRITE)
        self.assertEqual(peer.observation(), before)
        self.release(peer, "reply")
        self.assertEqual(self.wire_to_eof(stream), GREETING)
        after = peer.observation()
        peer.event(key, selectors.EVENT_READ | selectors.EVENT_WRITE)
        self.assertEqual(peer.observation(), after)
        self.assertEqual([row["kind"] for row in after["events"]].count("client-send-eof"), 1)

    def test_two_parked_owners_still_exhaust_original_connection_capacity(self):
        peer = self.peer(scenario="greeting")
        first = self.client(peer)
        first_owned = self.owned(peer)
        self.park(peer, first, first_owned)
        second = self.client(peer)
        second_owned = next(stream for stream in peer.clients if stream is not first_owned)
        self.park(peer, second, second_owned)
        third = self.client(peer)
        self.assertEqual(third.recv(1), b"")
        self.assertEqual(peer.observation()["openConnections"], 2)
        self.assertEqual(peer.observation()["rejectedConnections"], 1)
        barrier = next(row for row in peer.observation()["barriers"] if row["attempt"] == 1)
        peer.release(barrier["attempt"], barrier["sequence"], "close")
        self.assertEqual(peer.observation()["openConnections"], 1)
        fourth = self.client(peer)
        fourth_owned = next(stream for stream in peer.clients if stream is not second_owned)
        self.assertEqual(peer.clients[fourth_owned]["attempt"], 4)
        self.park(peer, fourth, fourth_owned)
        barrier = next(row for row in peer.observation()["barriers"] if row["attempt"] == 4)
        peer.release(barrier["attempt"], barrier["sequence"], "reply")
        self.assertEqual(self.wire_to_eof(fourth), GREETING)
        self.assertIn(second_owned, peer.clients, "fresh work retired the wrong owner")
        self.assertEqual(peer.observation()["openConnections"], 1)

    def test_failed_reset_of_parked_owner_closes_it_without_successful_release(self):
        peer = self.peer(scenario="greeting")
        stream = self.client(peer)
        owned = self.owned(peer)
        self.park(peer, stream, owned)
        with patch.object(socket.socket, "setsockopt", side_effect=OSError("controlled failure")):
            with self.assertRaises(OSError):
                self.release(peer, "reset")
        self.assertEqual(owned.fileno(), -1)
        observed = peer.observation()
        self.assertEqual(observed["failure"], "peer-control-failed")
        self.assertEqual(observed["releasedBarriers"], 0)
        self.assertEqual(observed["peerResets"], 0)
        self.assertEqual(observed["peerDescriptorClosures"], 1)

    def test_teardown_closes_parked_descriptors_once_and_preserves_mutation(self):
        peer = self.peer()
        stream, owned = self.mutation(peer)
        self.park(peer, stream, owned)
        observed = peer.close()
        self.assertEqual(owned.fileno(), -1)
        self.assertEqual(observed["acceptedMutations"], 1)
        self.assertEqual(observed["sentMutationReplies"], 0)
        self.assertEqual(observed["peerDescriptorClosures"], 1)
        self.assertEqual(observed["openConnections"], 0)
        self.assertEqual(observed["listenerOwners"], 0)
        self.assertEqual(peer.close(), observed)
        for name in ("guestReadPendingObserved", "providerRetirementObserved", "kernelFinalFreeObserved"):
            self.assertIs(observed[name], False)

    def test_existing_ungated_peer_eof_policy_is_unchanged(self):
        peer = self.peer(peer_type=SmtpPeer)
        stream = self.client(peer)
        owned = self.owned(peer)
        self.half_close(peer, stream, owned)
        self.assertEqual(owned.fileno(), -1)
        self.assertEqual(peer.observation()["openConnections"], 0)
        self.assertEqual(peer.observation()["acceptedMutations"], 0)


if __name__ == "__main__":
    unittest.main()
