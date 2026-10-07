"""Actual SMTP exchanges, uncertainty and physical ownership of the local peer."""
from __future__ import annotations

import hashlib
import json
import selectors
import smtplib
import socket
import threading
import time
import unittest

from tools.outbound_stream_fixture import MAX_ATTEMPTS, MAX_MESSAGE_BYTES, SmtpPeer


class StreamFixture(unittest.TestCase):
    def setUp(self):
        self.selector = selectors.DefaultSelector()
        self.peers = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for peer in self.peers:
            peer.close()
        self.selector.close()

    def peer(self, **options):
        peer = SmtpPeer(self.selector, **options)
        self.peers.append(peer)
        return peer

    def pump(self, predicate, maximum=2):
        deadline = time.monotonic() + maximum
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "bounded real peer progress")
            for key, events in self.selector.select(.005):
                key.data.event(key, events)
            for peer in self.peers:
                peer.check()

    def client(self, peer):
        stream = socket.create_connection(("127.0.0.1", peer.port), timeout=1)
        self.addCleanup(stream.close)
        self.pump(lambda: bool(peer.clients))
        return stream

    def standard_client(self, peer, message):
        outcome = {}

        def run():
            try:
                with smtplib.SMTP("127.0.0.1", peer.port, timeout=2) as client:
                    outcome["refused"] = client.sendmail("from@owned.invalid", "to@owned.invalid", message)
            except BaseException as error:
                outcome["error"] = error

        thread = threading.Thread(target=run, name="owned-smtp-reference-client")
        thread.start()
        try:
            self.pump(lambda: not thread.is_alive())
        finally:
            if thread.is_alive():
                peer.close()
            thread.join(2)
            self.assertFalse(thread.is_alive(), "original owned client was reaped")
        self.pump(lambda: not peer.clients)
        return outcome

    def test_ordinary_smtp_library_handles_fragmented_replies_and_records_exact_data(self):
        peer = self.peer(fragment_bytes=1)
        message = "From: from@owned.invalid\r\nTo: to@owned.invalid\r\n\r\n..dot\r\nmessage\r\n"
        result = self.standard_client(peer, message)
        self.assertEqual(result, {"refused": {}})
        observed = peer.observation()
        self.assertEqual(observed["acceptedConnections"], 1)
        self.assertEqual(observed["acceptedMutations"], 1)
        self.assertEqual(observed["confirmedMutationReplies"], 1)
        self.assertEqual(observed["mutationRecords"], [{
            "attempt": 1, "bytes": len(message), "sha256": hashlib.sha256(message.encode()).hexdigest(), "recipients": 1}])
        self.assertEqual(observed["openConnections"], 0)

    def test_lost_reply_preserves_one_accepted_mutation_without_a_second_attempt(self):
        peer = self.peer(drop_mutation_reply=True)
        result = self.standard_client(peer, "Subject: controlled\r\n\r\none mutation\r\n")
        self.assertIsInstance(result.get("error"), smtplib.SMTPServerDisconnected)
        observed = peer.observation()
        self.assertEqual(observed["acceptedConnections"], 1)
        self.assertEqual(observed["acceptedMutations"], 1)
        self.assertEqual(observed["confirmedMutationReplies"], 0)
        self.assertEqual(observed["openConnections"], 0)

    def test_partial_data_and_eof_do_not_accept_a_mutation(self):
        peer = self.peer()
        stream = self.client(peer)
        stream.sendall(b"EHLO local\r\nMAIL FROM:<from@owned.invalid>\r\nRCPT TO:<to@owned.invalid>\r\nDATA\r\nuncommitted\r\n")
        self.pump(lambda: any(row["bytes"] for row in peer.clients.values()))
        stream.shutdown(socket.SHUT_WR)
        self.pump(lambda: not peer.clients)
        self.assertEqual(peer.observation()["acceptedMutations"], 0)
        self.assertEqual(peer.observation()["confirmedMutationReplies"], 0)

    def test_message_bound_rejects_before_mutation_and_recovers_for_fresh_work(self):
        peer = self.peer()
        too_large = "Subject: bounded\r\n\r\n" + "X" * 100 + "\r\n"
        too_large += ("X" * 100 + "\r\n") * (MAX_MESSAGE_BYTES // 100)
        result = self.standard_client(peer, too_large)
        self.assertIsInstance(result.get("error"), (smtplib.SMTPServerDisconnected, OSError))
        self.assertEqual(peer.observation()["acceptedMutations"], 0)
        self.assertEqual(peer.observation()["openConnections"], 0)
        self.assertEqual(self.standard_client(peer, "Subject: fresh\r\n\r\nready\r\n"), {"refused": {}})
        self.assertEqual(peer.observation()["acceptedMutations"], 1)

    def test_exact_message_ceiling_is_accepted_with_original_byte_hash(self):
        peer = self.peer()
        message = (b"X" * 254 + b"\r\n") * 256
        self.assertEqual(len(message), MAX_MESSAGE_BYTES)
        self.assertEqual(self.standard_client(peer, message), {"refused": {}})
        self.assertEqual(peer.observation()["mutationRecords"], [{
            "attempt": 1, "bytes": MAX_MESSAGE_BYTES,
            "sha256": hashlib.sha256(message).hexdigest(), "recipients": 1}])

    def test_live_listener_is_not_replaced_and_all_clients_are_owned_until_close(self):
        peer = self.peer()
        with self.assertRaises(OSError):
            SmtpPeer(self.selector, port=peer.port)
        self.assertEqual(peer.observation()["listenerOwners"], 1)
        self.assertEqual(self.standard_client(peer, b"Subject: original\r\n\r\nunchanged\r\n"), {"refused": {}})
        self.assertEqual(peer.observation()["acceptedMutations"], 1)

    def test_two_live_connections_reject_third_and_close_retains_no_descriptors(self):
        peer = self.peer()
        first = self.client(peer)
        second = socket.create_connection(("127.0.0.1", peer.port), timeout=1)
        self.addCleanup(second.close)
        self.pump(lambda: len(peer.clients) == 2)
        third = socket.create_connection(("127.0.0.1", peer.port), timeout=1)
        self.addCleanup(third.close)
        self.pump(lambda: peer.observation()["rejectedConnections"] == 1)
        self.assertEqual(third.recv(1), b"")
        owned = list(peer.clients)
        listener = peer.listener
        observed = peer.close()
        self.assertEqual(observed["openConnections"], 0)
        self.assertEqual(observed["listenerOwners"], 0)
        self.assertTrue(all(stream.fileno() == -1 for stream in owned))
        self.assertEqual(listener.fileno(), -1)
        self.assertEqual(peer.close(), observed)
        first.close()

    def test_expired_idle_connection_closes_physical_owner_without_mutation(self):
        peer = self.peer()
        stream = self.client(peer)
        owned = next(iter(peer.clients))
        peer.check(time.monotonic() + 2.1)
        self.assertEqual(owned.fileno(), -1)
        self.assertEqual(peer.observation()["expiredConnections"], 1)
        self.assertEqual(peer.observation()["acceptedMutations"], 0)
        self.assertEqual(peer.observation()["openConnections"], 0)
        stream.close()

    def test_unsupported_auth_input_never_appears_in_public_observation(self):
        peer = self.peer()
        stream = self.client(peer)
        secret = b"PRIVATE-SMTP-QUALIFICATION-CREDENTIAL"
        stream.sendall(b"AUTH PLAIN " + secret + b"\r\n")
        self.pump(lambda: any(row["commands"] for row in peer.clients.values()))
        self.assertNotIn(secret.decode(), json.dumps(peer.observation()))
        self.assertEqual(peer.observation()["acceptedMutations"], 0)
        stream.close()
        self.pump(lambda: not peer.clients)

    def test_attempt_ceiling_retires_listener_without_more_accepts(self):
        peer = self.peer()
        for _ in range(MAX_ATTEMPTS):
            stream = socket.create_connection(("127.0.0.1", peer.port), timeout=1)
            self.pump(lambda: bool(peer.clients))
            stream.close()
            self.pump(lambda: not peer.clients)
        observed = peer.observation()
        self.assertEqual(observed["acceptedConnections"], MAX_ATTEMPTS)
        self.assertEqual(observed["listenerOwners"], 0)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", peer.port), timeout=.2)
        self.assertEqual(peer.observation()["acceptedConnections"], MAX_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
