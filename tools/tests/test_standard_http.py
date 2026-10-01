"""Actual bounded peer protocol controls; these are not guest-client qualification."""
from __future__ import annotations

import base64
import copy
import gzip
import hashlib
import json
import selectors
import socket
import time
import unittest

from tools.standard_http import FixtureError, Gate, Peer
from tools.standard_http import observations, protocol, vectors

# A test-only value. Real qualification runners use their private credential
# store; neither peer observations nor source qualification receipts contain it.
CREDENTIAL = b"Bearer " + b"a" * 64


class RequestFraming(unittest.TestCase):
    def parse(self, raw, width=4096):
        value = protocol.Request()
        for start in range(0, len(raw), width):
            value.feed(raw[start:start + width])
        return value

    def test_byte_fragmented_chunked_body_preserves_binary_and_utf8(self):
        body = b"\x00\xffcaf\xc3\xa9"
        raw = (b"POST /conformance/echo HTTP/1.1\r\nHost: example\r\nTransfer-Encoding: chunked\r\n"
               b"X-Conformance: caf\xc3\xa9\r\n\r\n" + f"{len(body):x}\r\n".encode()
               + body + b"\r\n0\r\n\r\n")
        value = self.parse(raw, 1)
        self.assertTrue(value.complete)
        self.assertEqual(value.body, body)
        self.assertEqual(value.headers[b"x-conformance"], b"caf\xc3\xa9")
        self.assertEqual(value.buffer, b"")

    def test_absent_length_and_present_zero_length_remain_distinguishable(self):
        for length in (b"", b"Content-Length: 0\r\n"):
            value = self.parse(b"GET /conformance/echo HTTP/1.1\r\nHost: example\r\n" + length + b"\r\n")
            self.assertTrue(value.complete)
            self.assertEqual(value.body, b"")
            self.assertEqual(b"content-length" in value.headers, bool(length))

    def test_headers_can_pause_before_body_and_resume_the_same_original_parser(self):
        value = protocol.Request()
        value.feed(b"POST /conformance/hold/upload HTTP/1.1\r\nHost: example\r\nContent-Length: 3\r\n\r\nabc",
                   consume_body=False)
        self.assertTrue(value.headers_ready)
        self.assertFalse(value.complete)
        self.assertEqual(value.body, b"")
        value.consume()
        self.assertTrue(value.complete)
        self.assertEqual(value.body, b"abc")

    def test_ambiguous_framing_and_pipelining_are_rejected(self):
        failures = (
            b"Content-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
            b"Content-Length: 0\r\ncontent-length: 0\r\n\r\n",
            b"Content-Length: 00\r\n\r\n",
            b"Content-Length: +1\r\n\r\nx",
            b"Transfer-Encoding: gzip, chunked\r\n\r\n",
            b"Content-Length: 1\r\n\r\nab",
            b"\r\nGET /second HTTP/1.1\r\nHost: example\r\n\r\n",
        )
        for failure in failures:
            with self.subTest(failure=failure):
                with self.assertRaises(FixtureError):
                    self.parse(b"POST /conformance/echo HTTP/1.1\r\nHost: example\r\n" + failure)

    def test_unsupported_features_and_control_bytes_fail_explicitly(self):
        for field in (b"Expect: 100-continue", b"Upgrade: websocket", b"Trailer: x-value",
                      b" bad: folded", b"bad name: value", b"bad: value\x00", b"bad: value\x7f"):
            with self.subTest(field=field), self.assertRaises(FixtureError):
                self.parse(b"GET /conformance/json HTTP/1.1\r\nHost: example\r\n" + field + b"\r\n\r\n")

    def test_bad_chunks_and_trailers_cannot_manufacture_eof(self):
        for body in (b"+1\r\na\r\n0\r\n\r\n", b"1;extra=yes\r\na\r\n0\r\n\r\n",
                     b"1\r\naXX0\r\n\r\n", b"0\r\nx-value: trailer\r\n\r\n",
                     b"0\r\n\r\nextra"):
            with self.subTest(body=body), self.assertRaises(FixtureError):
                self.parse(b"POST /conformance/echo HTTP/1.1\r\nHost: example\r\n"
                           b"Transfer-Encoding: chunked\r\n\r\n" + body)

    def test_request_body_header_window_and_chunk_count_are_finite(self):
        head = b"POST /conformance/echo HTTP/1.1\r\nHost: example\r\n"
        with self.assertRaisesRegex(FixtureError, "request-body-limit"):
            self.parse(head + f"Content-Length: {protocol.MAX_BODY + 1}\r\n\r\n".encode())
        with self.assertRaisesRegex(FixtureError, "request-header-limit"):
            self.parse(head + b"X: " + b"x" * protocol.MAX_HEADER_BYTES)
        with self.assertRaisesRegex(FixtureError, "request-header-count"):
            self.parse(head + b"".join(f"X-{number}: x\r\n".encode() for number in range(32)) + b"\r\n")
        with self.assertRaisesRegex(FixtureError, "request-chunk-framing-limit"):
            self.parse(head + b"Transfer-Encoding: chunked\r\n\r\n"
                       + b"1\r\nx\r\n" * protocol.MAX_CHUNKS + b"0\r\n\r\n")

    def test_incomplete_content_never_reports_a_complete_request(self):
        for framing, body in ((b"Content-Length: 2", b"x"),
                              (b"Transfer-Encoding: chunked", b"2\r\nx"),
                              (b"Transfer-Encoding: chunked", b"0\r\n")):
            value = self.parse(b"POST /conformance/echo HTTP/1.1\r\nHost: example\r\n" + framing + b"\r\n\r\n" + body)
            self.assertFalse(value.complete)


class ControlledPeer(unittest.TestCase):
    def setUp(self):
        self.peer = Peer(CREDENTIAL, maximum_seconds=30)
        self.addCleanup(self.peer.close)
        self.replies = {}
        self.closed = set()

    def connect(self, role="primary"):
        stream = socket.create_connection(("127.0.0.1", self.peer.ports[role]), timeout=1)
        self.addCleanup(stream.close)
        stream.setblocking(False)
        self.replies[stream] = bytearray()
        return stream

    def send(self, identity, *, method=b"GET", body=None, fields=(), credential=True):
        vector = vectors.BY_ID[identity]
        stream = self.connect(vector.role)
        raw = method + b" " + vector.path + b" HTTP/1.1\r\nHost: 127.0.0.1:" + str(self.peer.ports[vector.role]).encode() + b"\r\n"
        if credential:
            raw += b"Authorization: " + CREDENTIAL + b"\r\n"
        raw += b"".join(name + b": " + value + b"\r\n" for name, value in fields)
        if body is not None:
            raw += f"Content-Length: {len(body)}\r\n".encode()
        stream.sendall(raw + b"\r\n" + (body or b""))
        return stream

    def pump(self, condition):
        deadline = time.monotonic() + 2
        while not condition():
            self.assertLess(time.monotonic(), deadline, "peer did not reach current observed readiness")
            self.peer.poll(0.01)
            for stream in self.replies.keys() - self.closed:
                try:
                    raw = stream.recv(8192)
                except BlockingIOError:
                    continue
                except ConnectionResetError:
                    raw = b""
                if raw:
                    self.replies[stream].extend(raw)
                else:
                    self.closed.add(stream)

    def reply(self, stream):
        self.pump(lambda: stream in self.closed)
        return bytes(self.replies[stream])

    def body(self, stream):
        return self.reply(stream).split(b"\r\n\r\n", 1)[1]

    def test_success_json_and_error_statuses_are_actual_finite_http_responses(self):
        self.assertEqual(json.loads(self.body(self.send("domain-json"))), vectors.DOMAIN)
        for status in (404, 500):
            raw = self.reply(self.send("http-" + str(status)))
            self.assertTrue(raw.startswith(f"HTTP/1.1 {status} ".encode()))
            self.assertEqual(json.loads(raw.split(b"\r\n\r\n")[1])["status"], status)
        observations.validate(self.peer.observation())

    def test_seven_methods_byte_bodies_empty_header_and_utf8_header(self):
        for method in sorted(protocol.METHODS):
            body = b"" if method == b"HEAD" else b"\x00\xffcaf\xc3\xa9"
            for value in (b"", b"caf\xc3\xa9"):
                raw = self.reply(self.send("method-bytes", method=method, body=body,
                                           fields=((b"X-Conformance", value),)))
                if method == b"HEAD":
                    self.assertEqual(raw.split(b"\r\n\r\n")[1], b"")
                else:
                    result = json.loads(raw.split(b"\r\n\r\n")[1])
                    self.assertEqual(result["method"], method.decode())
                    self.assertEqual(base64.b64decode(result["bodyBase64"]), body)
                    self.assertEqual(base64.b64decode(result["customHeaderBase64"]), value)

    def test_held_headers_coexist_with_an_independently_ready_response(self):
        pending = self.send("pending-headers")
        self.pump(lambda: bool(self.peer.gates()))
        gate = self.peer.gates()[0]
        ready = self.send("domain-json")
        self.assertEqual(json.loads(self.body(ready)), vectors.DOMAIN)
        self.assertEqual(self.replies[pending], b"")
        self.assertNotIn(pending, self.closed)
        self.assertEqual(self.peer.observation()["openConnections"], 1)
        self.peer.release(gate)
        self.assertEqual(json.loads(self.body(pending)), vectors.DOMAIN)

    def test_partial_response_stays_owned_until_explicit_release_and_real_eof(self):
        pending = self.send("partial-body")
        self.pump(lambda: bool(self.peer.gates()) and self.replies[pending].endswith(b"first"))
        gate = self.peer.gates()[0]
        self.assertEqual(gate.phase, "body")
        self.assertNotIn(pending, self.closed)
        self.assertEqual(self.peer.observation()["completedResponseWrites"], 0)
        self.assertEqual(json.loads(self.body(self.send("domain-json"))), vectors.DOMAIN)
        self.peer.release(gate)
        self.assertEqual(self.body(pending), vectors.PARTIAL)
        self.assertEqual(self.peer.observation()["openConnections"], 0)

    def test_incomplete_chunked_upload_keeps_original_owner_and_does_not_block_ready_response(self):
        pending = self.send("pending-upload", method=b"POST", fields=((b"Transfer-Encoding", b"chunked"),))
        self.pump(lambda: bool(self.peer.gates()))
        gate = self.peer.gates()[0]
        self.assertEqual(gate.phase, "upload")
        self.assertNotIn("bodyBytes", self.peer.observation()["requests"][0])
        self.assertEqual(json.loads(self.body(self.send("domain-json"))), vectors.DOMAIN)
        self.peer.release(gate)
        body = b"\x00\xffcaf\xc3\xa9"
        pending.sendall(f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n")
        result = json.loads(self.body(pending))
        self.assertEqual(result, {"bodyBytes": len(body), "bodySha256": "sha256:" + hashlib.sha256(body).hexdigest()})
        observations.validate(self.peer.observation())

    def test_foreign_stale_and_repeated_gate_cannot_release_another_owner(self):
        pending = self.send("pending-headers")
        self.pump(lambda: bool(self.peer.gates()))
        gate = self.peer.gates()[0]
        before = self.peer.observation()
        with self.assertRaisesRegex(FixtureError, "stale-or-foreign"):
            self.peer.release(Gate("other-generation", gate.request, gate.phase))
        self.assertEqual(self.peer.observation(), before)
        self.peer.release(gate)
        with self.assertRaisesRegex(FixtureError, "not-pending"):
            self.peer.release(gate)
        self.body(pending)
        self.peer.close()
        with self.assertRaisesRegex(FixtureError, "stale-or-foreign"):
            self.peer.release(gate)

    def test_committed_mutation_and_lost_response_are_once_observable_without_peer_replay(self):
        before = self.peer.observation()
        pending = self.send("commit-pending", method=b"POST", body=b"change-once")
        self.pump(lambda: self.peer.observation()["committedMutations"] == 1)
        self.assertEqual(self.replies[pending], b"")
        pending.close()
        self.closed.add(pending)
        self.pump(lambda: self.peer.observation()["openConnections"] == 0)
        after = self.peer.observation()
        observations.require_one_committed_request(before, after)
        self.assertEqual(after["completedResponseWrites"], 0)
        self.assertTrue(any(item["kind"] == "remote-write-half-ended" for item in after["events"]))
        # An independently issued second call remains visible; the peer neither
        # hides nor authorizes it, and the once-only predicate must fail.
        second = self.send("commit-close", method=b"POST", body=b"again")
        self.reply(second)
        with self.assertRaisesRegex(FixtureError, "replayed-or-not-committed"):
            observations.require_one_committed_request(before, self.peer.observation())

    def test_commit_then_close_does_not_return_a_successful_response(self):
        before = self.peer.observation()
        self.assertEqual(self.reply(self.send("commit-close", method=b"POST", body=b"change")), b"")
        after = self.peer.observation()
        observations.require_one_committed_request(before, after, "commit-close")
        self.assertEqual(after["requests"][0]["closeReason"], "response-withheld-after-commit")

    def test_zero_contact_requires_live_current_listeners_and_detects_even_empty_connection(self):
        before = self.peer.observation()
        self.peer.poll(0)
        observations.require_zero_contact(before, self.peer.observation())
        self.connect()
        self.pump(lambda: self.peer.observation()["acceptedConnections"] == 1)
        with self.assertRaisesRegex(FixtureError, "contacted-peer"):
            observations.require_zero_contact(before, self.peer.observation())
        stopped = self.peer.close()
        with self.assertRaisesRegex(FixtureError, "live-listeners"):
            observations.require_zero_contact(stopped, stopped)

    def test_redirect_target_has_separate_origin_and_observes_credentials_stripped(self):
        before = self.peer.observation()
        raw = self.reply(self.send("redirect"))
        self.assertIn(self.peer.url("redirect-target").encode(), raw)
        target = self.send("redirect-target", credential=False)
        self.assertEqual(json.loads(self.body(target)), {"redirected": True})
        observations.require_stripped_redirect(before, self.peer.observation())
        self.assertNotEqual(self.peer.ports["primary"], self.peer.ports["secondary"])

    def test_redirect_credential_forwarding_is_rejected_without_exposing_secret(self):
        before = self.peer.observation()
        self.assertEqual(self.reply(self.send("redirect-target")), b"")
        after = self.peer.observation()
        self.assertEqual(after["rejectedRequests"], 1)
        self.assertEqual(after["requests"][0]["closeReason"], "redirect-credential-forwarded")
        self.assertNotIn(CREDENTIAL.decode(), json.dumps(after))
        with self.assertRaisesRegex(FixtureError, "not-stripped"):
            observations.require_stripped_redirect(before, after)

    def test_truncation_malformed_framing_and_malformed_json_are_distinct_fixture_outcomes(self):
        truncated = self.reply(self.send("truncated-body"))
        self.assertIn(b"Content-Length: 32\r\n", truncated)
        self.assertEqual(truncated.split(b"\r\n\r\n")[1], b"short")
        malformed = self.reply(self.send("malformed-framing"))
        self.assertIn(b"Content-Length: 1\r\nTransfer-Encoding: chunked", malformed)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(self.body(self.send("malformed-json")))

    def test_oversized_and_compressed_bodies_are_real_wire_bytes(self):
        self.assertEqual(len(self.body(self.send("oversized-body"))), vectors.MAX_RESPONSE)
        raw = self.reply(self.send("gzip-json"))
        self.assertIn(b"Content-Encoding: gzip\r\n", raw)
        self.assertEqual(json.loads(gzip.decompress(raw.split(b"\r\n\r\n")[1])), vectors.DOMAIN)

    def test_failed_authentication_does_not_mutate_and_a_fresh_request_still_succeeds(self):
        self.assertEqual(self.reply(self.send("commit-close", method=b"POST", body=b"change", credential=False)), b"")
        self.assertEqual(self.peer.observation()["committedMutations"], 0)
        self.assertEqual(json.loads(self.body(self.send("domain-json"))), vectors.DOMAIN)
        self.assertNotIn(CREDENTIAL.decode(), json.dumps(self.peer.observation()))

    def test_connection_bound_preserves_existing_owners_and_rejects_only_extra_contact(self):
        for number in range(4):
            self.connect()
            self.pump(lambda: self.peer.observation()["acceptedConnections"] == number + 1)
        extra = self.connect()
        self.reply(extra)
        observation = self.peer.observation()
        self.assertEqual(observation["openConnections"], 4)
        self.assertEqual(observation["connectionBoundRejections"], 1)
        self.assertEqual(observation["acceptedConnections"], 5)

    def test_stop_closes_held_upload_response_and_listener_with_no_late_gate(self):
        self.send("pending-headers")
        self.send("pending-upload", method=b"POST", fields=((b"Transfer-Encoding", b"chunked"),))
        self.pump(lambda: len(self.peer.gates()) == 2)
        gates = self.peer.gates()
        result = self.peer.close()
        self.assertEqual(result["openConnections"], 0)
        self.assertEqual(result["listeningOrigins"], 0)
        self.assertEqual(result["state"], "stopped")
        self.assertEqual(self.peer.close(), result)
        for gate in gates:
            with self.assertRaisesRegex(FixtureError, "stale-or-foreign"):
                self.peer.release(gate)

    def test_snapshots_detect_generation_changes_erased_commit_and_history_mutation(self):
        before = self.peer.observation()
        self.reply(self.send("commit-close", method=b"POST", body=b"change"))
        after = self.peer.observation()
        for field, changed in (("generation", "different"), ("committedMutations", 0)):
            damaged = copy.deepcopy(after)
            damaged[field] = changed
            with self.subTest(field=field), self.assertRaises(FixtureError):
                observations.delta(before, damaged)
        checkpoint = self.peer.observation()
        after["events"][0]["role"] = "secondary"
        with self.assertRaisesRegex(FixtureError, "history-changed"):
            observations.delta(checkpoint, after)

    def test_observations_reject_malformed_nested_members_and_invented_owner_counts(self):
        self.reply(self.send("domain-json"))
        value = self.peer.observation()
        for field, changed in (("requests", [None]), ("events", [None]), ("generation", ""),
                               ("openConnections", True), ("openConnections", 1),
                               ("listeningOrigins", 1), ("origins", {}), ("limits", {})):
            damaged = copy.deepcopy(value)
            damaged[field] = changed
            with self.subTest(field=field, changed=changed), self.assertRaises(FixtureError):
                observations.validate(damaged)

    def test_origin_changes_and_reopened_closed_owners_cannot_support_a_delta(self):
        self.reply(self.send("domain-json"))
        before = self.peer.observation()
        damaged = copy.deepcopy(before)
        damaged["origins"]["primary"]["port"] = (self.peer.ports["primary"] % 65535) + 1
        with self.assertRaises(FixtureError):
            observations.delta(before, damaged)
        damaged = copy.deepcopy(before)
        damaged["requests"][0]["state"] = "request-complete"
        del damaged["requests"][0]["closeReason"]
        damaged["openConnections"] = 1
        with self.assertRaises(FixtureError):
            observations.delta(before, damaged)

    def test_total_contact_ceiling_closes_listeners_without_erasing_completed_contacts(self):
        for _ in range(32):
            self.assertEqual(json.loads(self.body(self.send("domain-json"))), vectors.DOMAIN)
        result = self.peer.observation()
        observations.validate(result)
        self.assertEqual(result["acceptedConnections"], 32)
        self.assertEqual(result["completedResponseWrites"], 32)
        self.assertEqual(result["openConnections"], 0)
        self.assertEqual(result["listeningOrigins"], 0)
        with self.assertRaisesRegex(FixtureError, "live-listeners"):
            observations.require_zero_contact(result, result)

    def test_deadline_closes_owned_waits_without_fake_guest_completion(self):
        self.send("pending-headers")
        self.pump(lambda: bool(self.peer.gates()))
        self.peer.clock = lambda: self.peer.deadline + 1
        self.peer.tick()
        result = self.peer.observation()
        self.assertEqual(result["openConnections"], 0)
        self.assertEqual(result["failure"], "fixture-lifetime-exhausted")
        self.assertEqual(result["completedResponseWrites"], 0)
        with self.assertRaisesRegex(FixtureError, "observation-failed"):
            observations.validate(result)

    def test_external_selector_is_owned_by_supervisor_and_foreign_events_are_rejected(self):
        with selectors.DefaultSelector() as selector:
            peer = Peer(CREDENTIAL, selector=selector)
            try:
                with self.assertRaisesRegex(FixtureError, "shared-selector"):
                    peer.poll(0)
                with self.assertRaisesRegex(FixtureError, "foreign-selector"):
                    peer.event(selectors.SelectorKey(None, -1, selectors.EVENT_READ, "foreign"), selectors.EVENT_READ)
            finally:
                peer.close()
            self.assertEqual(dict(selector.get_map()), {})


if __name__ == "__main__":
    unittest.main()
