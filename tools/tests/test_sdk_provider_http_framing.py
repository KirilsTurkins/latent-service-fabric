"""Real socket framing controls for the bounded SDK qualification peer."""
import socket
import time
import unittest
from unittest.mock import patch

from tools import sdk_provider_http_fixture as fixture


class FragmentedSocket:
    """Cap individual real reads; transport ownership stays with socketpair."""
    def __init__(self, connection, maximum):
        self.connection, self.maximum = connection, maximum
        self.received, self.timeouts = 0, []

    def settimeout(self, seconds):
        self.timeouts.append(seconds)
        self.connection.settimeout(seconds)

    def recv(self, maximum):
        value = self.connection.recv(min(maximum, self.maximum))
        self.received += len(value)
        return value

    def fileno(self):
        return self.connection.fileno()


class ProviderHttpFramingTests(unittest.TestCase):
    def wire(self, framing=b"", body=b"", *, method=b"GET", path=b"/allowed", credential=None):
        credential = fixture.PROVIDER_CREDENTIAL if credential is None else credential
        return (method + b" " + path + b" HTTP/1.1\r\nAuthorization: " + credential
                + b"\r\n" + framing + b"\r\n" + body)

    def check_request(self, payload, fragment=1024, deadline=None):
        sender, receiver = socket.socketpair()
        try:
            sender.settimeout(1)
            sender.sendall(payload)
            sender.shutdown(socket.SHUT_WR)
            selected = FragmentedSocket(receiver, fragment)
            value = fixture.request(selected, time.monotonic() + 1 if deadline is None else deadline)
            return value, selected
        finally:
            receiver.close()
            sender.close()

    def test_content_length_and_absent_body_preserve_existing_results_and4096_boundary(self):
        for method, framing, body in ((b"GET", b"", b""), (b"HEAD", b"Content-Length: 0\r\n", b""),
                                      (b"POST", b"Content-Length: 4\r\n", b"data"),
                                      (b"POST", b"Content-Length: 4096\r\n", b"a" * 4096)):
            for fragment in (1, 2, 1024):
                with self.subTest(method=method, fragment=fragment, size=len(body)):
                    result, selected = self.check_request(self.wire(framing, body, method=method), fragment)
                    self.assertEqual(result, (method, True, True))
                    self.assertLessEqual(selected.received, 8192)

    def test_valid_empty_chunked_get_and_head_accept_fragmented_canonical_framing(self):
        for method in (b"GET", b"HEAD"):
            for coding in (b"chunked", b"CHUNKED"):
                for fragment in (1, 2, 7, 1024):
                    with self.subTest(method=method, coding=coding, fragment=fragment):
                        result, _selected = self.check_request(self.wire(
                            b"Transfer-Encoding: " + coding + b"\r\n", b"0\r\n\r\n", method=method), fragment)
                        self.assertEqual(result, (method, True, True))

    def test_chunked_post_accepts_binary_and_exact4096_bytes_in16_chunks(self):
        bodies = (b"3\r\n\x00a\xff\r\n0\r\n\r\n",
                  (b"100\r\n" + b"a" * 256 + b"\r\n") * 16 + b"0\r\n\r\n",
                  b"0000000000001000\r\n" + b"a" * 4096 + b"\r\n0000000000000000\r\n\r\n")
        for body in bodies:
            for fragment in (1, 7, 1024):
                with self.subTest(size=len(body), fragment=fragment):
                    result, selected = self.check_request(self.wire(
                        b"Transfer-Encoding: chunked\r\n", body, method=b"POST"), fragment)
                    self.assertEqual(result, (b"POST", True, True))
                    self.assertLessEqual(selected.received, 8192)

    def test_duplicate_and_ambiguous_framing_reject_case_insensitive_and_both_orders(self):
        headers = (b"Content-Length: 0\r\ncontent-length: 0\r\n",
                   b"Transfer-Encoding: chunked\r\nTRANSFER-ENCODING: chunked\r\n",
                   b"Transfer-Encoding: chunked\r\nContent-Length: 0\r\n",
                   b"Content-Length: 0\r\nTransfer-Encoding: chunked\r\n")
        for framing in headers:
            with self.subTest(framing=framing), self.assertRaisesRegex(ValueError, "duplicate|ambiguous"):
                self.check_request(self.wire(framing, b"0\r\n\r\n"), 1)

    def test_unknown_stacked_repeated_and_empty_transfer_codings_reject(self):
        for coding in (b"", b"identity", b"gzip", b"gzip, chunked", b"chunked, chunked", b"chunked,gzip"):
            with self.subTest(coding=coding), self.assertRaisesRegex(ValueError, "unsupported request framing"):
                self.check_request(self.wire(b"Transfer-Encoding: " + coding + b"\r\n", b"0\r\n\r\n"))

    def test_chunk_size_extensions_nonhex_signs_and_overlong_lines_reject(self):
        for encoded in (b"", b" ", b"+1", b"-1", b"0x1", b"g", b"1;name=value", b"0" * 17):
            for fragment in (1, 1024):
                with self.subTest(size=encoded, fragment=fragment), self.assertRaises(ValueError):
                    self.check_request(self.wire(b"Transfer-Encoding: chunked\r\n",
                        encoded + b"\r\na\r\n0\r\n\r\n", method=b"POST"), fragment)

    def test_malformed_data_terminators_and_bare_linefeeds_reject(self):
        for body in (b"1\r\naXX0\r\n\r\n", b"1\na\r\n0\r\n\r\n", b"0\r\nx\n", b"0\n\n"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.check_request(self.wire(b"Transfer-Encoding: chunked\r\n", body, method=b"POST"), 1)

    def test_truncated_chunk_size_payload_terminator_and_zero_chunk_reject(self):
        for body in (b"1", b"1\r\n", b"2\r\na", b"1\r\na\r", b"1\r\na\r\n", b"0\r\n", b"0\r\n\r"):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, "truncated request chunks"):
                self.check_request(self.wire(b"Transfer-Encoding: chunked\r\n", body, method=b"POST"), 1)

    def test_trailers_and_queued_bytes_after_final_chunk_reject_even_across_one_byte_reads(self):
        for body in (b"0\r\nTrailer: no\r\n\r\n", b"0\r\n\r\nextra", b"0\r\n\r\n0\r\n\r\n"):
            for fragment in (1, 1024):
                with self.subTest(body=body, fragment=fragment), self.assertRaisesRegex(ValueError, "trailers|payload"):
                    self.check_request(self.wire(b"Transfer-Encoding: chunked\r\n", body), fragment)

    def test_seventeenth_data_chunk_and_decoded4097_bytes_reject_at_original_body_cap(self):
        bodies = ((b"1\r\na\r\n") * 17 + b"0\r\n\r\n",
                  b"1001\r\n" + b"a" * 4097 + b"\r\n0\r\n\r\n",
                  b"1000\r\n" + b"a" * 4096 + b"\r\n1\r\nb\r\n0\r\n\r\n")
        for index, body in enumerate(bodies):
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "chunk count bound|body bound"):
                self.check_request(self.wire(b"Transfer-Encoding: chunked\r\n", body, method=b"POST"), 7)

    def test_get_head_and_undeclared_payload_reject_for_both_framings(self):
        for method in (b"GET", b"HEAD"):
            for framing, body in ((b"Content-Length: 1\r\n", b"a"),
                                  (b"Transfer-Encoding: chunked\r\n", b"1\r\na\r\n0\r\n\r\n"),
                                  (b"Content-Length: 0\r\n", b"extra"), (b"", b"extra")):
                for fragment in (1, 1024):
                    with self.subTest(method=method, framing=framing, fragment=fragment), self.assertRaises(ValueError):
                        self.check_request(self.wire(framing, body, method=method), fragment)
        with self.assertRaisesRegex(ValueError, "payload"):
            self.check_request(self.wire(b"Content-Length: 3\r\n", b"data", method=b"POST"), 1)

    def test_content_length_numeric_ambiguity_overflow_and_truncation_reject(self):
        for encoded in (b"", b"0,0", b"+0", b"-0", b"1.0", b"1_0", b"0x0", b"4097"):
            with self.subTest(encoded=encoded), self.assertRaises(ValueError):
                self.check_request(self.wire(b"Content-Length: " + encoded + b"\r\n", method=b"POST"))
        with self.assertRaisesRegex(ValueError, "truncated request body"):
            self.check_request(self.wire(b"Content-Length: 2\r\n", b"a", method=b"POST"), 1)

    def test_original8192_header_bytes_and16_fields_remain_hard_bounds(self):
        base = self.wire()
        prefix = base[:-2] + b"X-Pad: "
        edge = prefix + b"a" * (8192 - len(prefix) - 4) + b"\r\n\r\n"
        self.assertEqual(len(edge), 8192)
        self.assertEqual(self.check_request(edge)[0], (b"GET", True, True))
        with self.assertRaisesRegex(ValueError, "request header bound"):
            self.check_request(edge[:-4] + b"a\r\n\r\n")
        allowed = b"".join(b"X-" + str(index).encode() + b": a\r\n" for index in range(15))
        self.assertEqual(self.check_request(self.wire(allowed))[0], (b"GET", True, True))
        with self.assertRaisesRegex(ValueError, "request header count"):
            self.check_request(self.wire(allowed + b"X-16: a\r\n"))

    def test_framing_header_whitespace_folding_and_control_bytes_reject(self):
        for header in (b"Content-Length : 0\r\n", b" Transfer-Encoding: chunked\r\n",
                       b"Content\t-Length: 0\r\n", b"X: a\x00b\r\n", b"X: a\x7fb\r\n",
                       b"X: first\r\n second\r\n"):
            with self.subTest(header=header), self.assertRaises(ValueError):
                self.check_request(self.wire(header))

    def test_credentials_and_route_decisions_remain_independent_of_framing(self):
        for framing, body in ((b"Content-Length: 0\r\n", b""),
                              (b"Transfer-Encoding: chunked\r\n", b"0\r\n\r\n")):
            with self.subTest(framing=framing):
                self.assertEqual(self.check_request(self.wire(framing, body, credential=b"wrong"))[0],
                                 (b"GET", False, True))
                self.assertEqual(self.check_request(self.wire(framing, body, path=b"/wrong"))[0],
                                 (b"GET", True, False))

    def test_fragmented_chunk_reads_keep_original_absolute_deadline_and_two_second_cap(self):
        with patch.object(fixture.time, "monotonic", return_value=100):
            result, selected = self.check_request(self.wire(b"Transfer-Encoding: chunked\r\n", b"0\r\n\r\n"),
                                                  1, deadline=100.025)
        self.assertEqual(result, (b"GET", True, True))
        self.assertTrue(selected.timeouts)
        self.assertTrue(all(0 < seconds <= 0.02500000001 for seconds in selected.timeouts))
        with patch.object(fixture.time, "monotonic", return_value=100.025), \
             self.assertRaises(fixture.ProviderDeadlineExpired):
            self.check_request(self.wire(b"Transfer-Encoding: chunked\r\n", b"0\r\n\r\n"), 1, deadline=100.025)


if __name__ == "__main__":
    unittest.main()
