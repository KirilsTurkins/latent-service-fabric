"""Real loopback peer controls; native smtplib is not six-port qualification."""
from __future__ import annotations

import hashlib
import json
import selectors
import smtplib
import socket
import threading
import time
import unittest
from unittest.mock import patch

from tools.outbound_stream_adversarial import (
    GatedSmtpPeer, MAX_EVENTS, MAX_RESPONSE_BYTES, RESPONSE_WINDOW,
)

MESSAGE = b"Subject: bounded\r\n\r\none mutation\r\n"
ENVELOPE = (b"EHLO local\r\nMAIL FROM:<a@owned.invalid>\r\n"
            b"RCPT TO:<b@owned.invalid>\r\nDATA\r\n")


class AdversarialPeerTests(unittest.TestCase):
    def setUp(self):
        self.selector = selectors.DefaultSelector()
        self.peers = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for peer in self.peers:
            peer.close()
        self.selector.close()

    def peer(self, **options):
        peer = GatedSmtpPeer(self.selector, **options)
        self.peers.append(peer)
        return peer

    def step(self):
        for key, events in self.selector.select(.002):
            key.data.event(key, events)
        for peer in self.peers:
            peer.check()

    def pump(self, ready):
        deadline = time.monotonic() + 3
        while not ready():
            self.assertLess(time.monotonic(), deadline, "watchdog is not a readiness witness")
            self.step()

    def client(self, peer):
        stream = socket.create_connection(("127.0.0.1", peer.port), timeout=1)
        self.addCleanup(stream.close)
        old = peer.attempts
        self.pump(lambda: peer.attempts == old + 1)
        return stream

    def barrier(self, peer):
        self.pump(lambda: bool(peer.observation()["barriers"]))
        return peer.observation()["barriers"][0]

    def release(self, peer, action):
        barrier = self.barrier(peer)
        self.pump(lambda: all(not row["output"] for row in peer.clients.values()))
        peer.release(barrier["attempt"], barrier["sequence"], action)
        return barrier

    def mutation(self, peer):
        stream = self.client(peer)
        stream.sendall(ENVELOPE + MESSAGE + b".\r\n")
        self.barrier(peer)
        return stream

    def smtp(self, peer, action):
        result = {}

        def ordinary_client():
            try:
                with smtplib.SMTP("127.0.0.1", peer.port, timeout=2) as client:
                    result["refused"] = client.sendmail("a@owned.invalid", "b@owned.invalid", MESSAGE)
            except BaseException as error:
                result["error"] = error

        thread = threading.Thread(target=ordinary_client, name="owned-gated-smtp-reference")
        thread.start()
        try:
            self.pump(lambda: bool(peer.observation()["barriers"]) or not thread.is_alive())
            self.assertTrue(thread.is_alive(), result)
            self.assertEqual(peer.observation()["sentMutationReplies"], 0)
            self.release(peer, action)
            self.pump(lambda: not thread.is_alive())
        finally:
            if thread.is_alive():
                peer.close()
            thread.join(3)
            self.assertFalse(thread.is_alive(), "original client thread must be joined")
        self.pump(lambda: not peer.clients)
        return result

    def test_invalid_scenario_is_rejected_before_descriptor_allocation(self):
        with patch("socket.socket") as create:
            for scenario in ("unknown", None, [], True, 1):
                with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                    self.peer(scenario=scenario)
            create.assert_not_called()

    def test_commit_is_observed_before_one_byte_fragmented_reply(self):
        peer = self.peer(fragment_bytes=1)
        self.assertEqual(self.smtp(peer, "reply"), {"refused": {}})
        observed = peer.observation()
        self.assertEqual((observed["acceptedConnections"], observed["acceptedMutations"],
                          observed["sentMutationReplies"], observed["peerDescriptorClosures"]), (1, 1, 1, 1))
        self.assertEqual(observed["mutationRecords"], [{"attempt": 1, "bytes": len(MESSAGE),
            "sha256": hashlib.sha256(MESSAGE).hexdigest(), "recipients": 1}])
        kinds = [event["kind"] for event in observed["events"]]
        self.assertLess(kinds.index("mutation-committed"), kinds.index("released-reply"))
        self.assertIsNone(observed["failure"])
        self.assertEqual(observed["clientConfirmation"], "not-observed")

    def test_lost_replies_preserve_mutation_without_library_reconnect(self):
        for action in ("close", "reset", "half-close"):
            with self.subTest(action=action):
                peer = self.peer()
                result = self.smtp(peer, action)
                self.assertIsInstance(result.get("error"), smtplib.SMTPServerDisconnected)
                observed = peer.observation()
                self.assertEqual((observed["acceptedConnections"], observed["acceptedMutations"],
                                  observed["sentMutationReplies"]), (1, 1, 0))
                self.assertEqual(observed["peerResets"], int(action == "reset"))
                self.assertEqual(observed["peerSendHalfCloses"], int(action == "half-close"))
                self.assertEqual(observed["peerDescriptorClosures"], 1)
                self.assertIsNone(observed["failure"])

    def test_a_second_explicit_library_call_is_a_second_mutation_not_rollback(self):
        peer = self.peer()
        self.assertIn("error", self.smtp(peer, "close"))
        original = peer.observation()
        self.assertEqual(self.smtp(peer, "reply"), {"refused": {}})
        observed = peer.observation()
        self.assertEqual(observed["acceptedConnections"], 2)
        self.assertEqual(observed["acceptedMutations"], 2)
        self.assertEqual(observed["sentMutationReplies"], 1)
        self.assertEqual([row["attempt"] for row in observed["mutationRecords"]], [1, 2])
        self.assertEqual(original["acceptedMutations"], 1)
        self.assertEqual(len(original["mutationRecords"]), 1)

    def test_partial_terminator_cannot_commit_or_open_a_gate(self):
        peer = self.peer()
        stream = self.client(peer)
        stream.sendall(ENVELOPE + b"partial\r\n.")
        self.pump(lambda: any(record["bytes"] == 9 for record in peer.clients.values()))
        self.assertEqual(peer.observation()["acceptedMutations"], 0)
        self.assertEqual(peer.observation()["barriers"], [])
        stream.sendall(b"\r")
        self.pump(lambda: any(record["input"] == b".\r" for record in peer.clients.values()))
        self.assertEqual(peer.observation()["acceptedMutations"], 0)
        stream.sendall(b"\n")
        self.barrier(peer)
        self.assertEqual(peer.observation()["acceptedMutations"], 1)
        self.release(peer, "close")

    def test_foreign_stale_and_boolean_gate_identities_have_no_side_effects(self):
        peer = self.peer()
        self.mutation(peer)
        barrier = self.barrier(peer)
        self.pump(lambda: all(not row["output"] for row in peer.clients.values()))
        for attempt, sequence, action in ((2, barrier["sequence"], "close"),
                (1, barrier["sequence"] + 1, "close"), (True, 1, "reply"),
                (1, True, "reply"), (1, barrier["sequence"], "terminate"),
                (1, barrier["sequence"], "invalid")):
            with self.subTest(attempt=attempt, sequence=sequence, action=action):
                before = peer.observation()
                with self.assertRaises(ValueError):
                    peer.release(attempt, sequence, action)
                self.assertEqual(peer.observation(), before)
        self.release(peer, "reply")
        with self.assertRaises(ValueError):
            peer.release(barrier["attempt"], barrier["sequence"], "close")

    def test_pipelined_prior_replies_must_drain_before_releasing_commit_reply(self):
        peer = self.peer(fragment_bytes=1)
        self.mutation(peer)
        barrier = self.barrier(peer)
        self.assertGreater(barrier["priorReplyBytes"], 0)
        with self.assertRaisesRegex(ValueError, "prior-replies-not-drained"):
            peer.release(barrier["attempt"], barrier["sequence"], "reply")
        self.assertEqual(peer.sent_replies, 0)
        self.release(peer, "reply")
        self.assertEqual(peer.sent_replies, 0)
        self.pump(lambda: peer.sent_replies == 1)
        self.assertEqual(peer.observation()["acceptedMutations"], 1)

    def test_half_close_keeps_original_descriptor_until_client_eof(self):
        peer = self.peer()
        stream = self.mutation(peer)
        owned = next(iter(peer.clients))
        self.release(peer, "half-close")
        self.assertGreaterEqual(owned.fileno(), 0)
        self.assertEqual(peer.observation()["openConnections"], 1)
        self.assertEqual(peer.observation()["peerDescriptorClosures"], 0)
        while stream.recv(4096):
            pass
        stream.shutdown(socket.SHUT_WR)
        self.pump(lambda: not peer.clients)
        self.assertEqual(owned.fileno(), -1)
        self.assertEqual(peer.observation()["peerDescriptorClosures"], 1)

    def test_control_release_does_not_extend_original_deadlines(self):
        peer = self.peer(scenario="greeting")
        self.client(peer)
        record = next(iter(peer.clients.values()))
        original = (record["idle"], record["absolute"])
        self.release(peer, "reply")
        self.assertEqual((record["idle"], record["absolute"]), original)
        peer.check(original[0] + .001)
        self.assertEqual(peer.observation()["failure"], "peer-watchdog-expired")

    def test_stalled_greeting_does_not_register_a_busy_write_interest(self):
        peer = self.peer(scenario="greeting")
        stream = self.client(peer)
        owned = next(iter(peer.clients))
        self.assertEqual(self.selector.get_key(owned).events, selectors.EVENT_READ)
        stream.setblocking(False)
        with self.assertRaises(BlockingIOError):
            stream.recv(1)
        self.release(peer, "reply")
        self.pump(lambda: all(not row["output"] for row in peer.clients.values()))
        self.assertEqual(stream.recv(4096), b"220 loopback.invalid SMTP\r\n")

    def test_watchdog_failure_survives_physical_close_and_repeated_cleanup(self):
        peer = self.peer()
        self.mutation(peer)
        owned = next(iter(peer.clients))
        peer.check(time.monotonic() + 2.1)
        first = peer.close()
        self.assertEqual(owned.fileno(), -1)
        self.assertEqual(first["failure"], "peer-watchdog-expired")
        self.assertEqual(first["acceptedMutations"], 1)
        self.assertEqual(first["sentMutationReplies"], 0)
        self.assertEqual(peer.close(), first)
        for name in ("guestReadPendingObserved", "providerRetirementObserved", "kernelFinalFreeObserved"):
            self.assertIs(first[name], False)

    def test_hostile_responses_have_bounded_windows_and_exact_finite_wire_bytes(self):
        for scenario in ("oversized-greeting", "unterminated-greeting"):
            with self.subTest(scenario=scenario):
                peer = self.peer(scenario=scenario, fragment_bytes=1024)
                stream = self.client(peer)
                stream.setblocking(False)
                wire = bytearray()

                def complete():
                    try:
                        wire.extend(stream.recv(4096))
                    except BlockingIOError:
                        pass
                    self.assertTrue(all(len(row["output"]) <= RESPONSE_WINDOW for row in peer.clients.values()))
                    self.assertLessEqual(len(wire), MAX_RESPONSE_BYTES)
                    return len(wire) == MAX_RESPONSE_BYTES

                self.pump(complete)
                self.assertEqual(wire[:4], b"220 ")
                self.assertEqual(wire.count(b"\r\n"), int(scenario == "oversized-greeting"))
                if scenario == "unterminated-greeting":
                    barrier = self.barrier(peer)
                    with self.assertRaises(ValueError):
                        peer.release(barrier["attempt"], barrier["sequence"], "reply")
                    self.release(peer, "terminate")
                    self.pump(lambda: all(not row["output"] for row in peer.clients.values()))
                    self.assertEqual(stream.recv(2), b"\r\n")
                self.assertEqual(peer.observation()["acceptedMutations"], 0)
                self.assertIsNone(peer.observation()["failure"])
                peer.close()

    def test_gate_releases_do_not_leak_payload_or_credentials_into_events(self):
        peer = self.peer()
        stream = self.client(peer)
        secret = b"PRIVATE-SMTP-CONTROL-CREDENTIAL"
        stream.sendall(b"AUTH PLAIN " + secret + b"\r\n")
        self.pump(lambda: any(row["commands"] for row in peer.clients.values()))
        self.assertNotIn(secret.decode(), json.dumps(peer.observation()))
        stream.sendall(ENVELOPE + MESSAGE + b".\r\n")
        self.release(peer, "close")
        observed = peer.observation()
        self.assertNotIn(MESSAGE.decode(), json.dumps(observed))
        self.assertEqual([event["sequence"] for event in observed["events"]],
                         list(range(1, len(observed["events"]) + 1)))
        times = [event["monotonicNs"] for event in observed["events"]]
        self.assertEqual(times, sorted(times))
        observed["events"][0]["kind"] = "tampered"
        self.assertEqual(peer.observation()["events"][0]["kind"], "connected")

    def test_event_capacity_failure_cannot_prevent_descriptor_cleanup(self):
        peer = self.peer(scenario="greeting")
        self.client(peer)
        owned = next(iter(peer.clients))
        # Fault injection into the diagnostic journal, not product evidence.
        peer.events = [{"sequence": index + 1} for index in range(MAX_EVENTS)]
        observed = peer.close()
        self.assertEqual(owned.fileno(), -1)
        self.assertEqual(observed["failure"], "peer-event-bound")
        self.assertEqual(len(observed["events"]), MAX_EVENTS)
        self.assertEqual(observed["openConnections"], 0)


if __name__ == "__main__":
    unittest.main()
