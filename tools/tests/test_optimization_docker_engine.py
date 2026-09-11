"""Synthetic sockets exercise exact HTTP bytes; no Docker daemon is contacted."""
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from tools.optimization_docker import engine


def http(body=b"", status=200, headers=None):
    values = {"Content-Length": str(len(body)), **(headers or {})}
    return (f"HTTP/1.1 {status} OK\r\n" + "".join(f"{key}: {value}\r\n" for key, value in values.items())
            + "\r\n").encode() + body


def version(**changes):
    return http(json.dumps({"Version": "29.7.2", "ApiVersion": "1.55", "MinAPIVersion": "1.40",
                            **changes}).encode())


def upgrade(data=b""):
    return b"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n" + data


def frame(stream, body):
    return bytes([stream, 0, 0, 0]) + len(body).to_bytes(4, "big") + body


class FakeSocket:
    def __init__(self, *chunks):
        self.chunks, self.sent, self.closed, self.timeouts, self.connected = list(chunks), bytearray(), False, [], None

    def connect(self, path):
        self.connected = path

    def settimeout(self, value):
        self.timeouts.append(value)

    def send(self, value):
        # Force the owner to handle partial writes of both headers and bodies.
        count = min(len(value), 17)
        self.sent.extend(value[:count])
        return count

    def recv(self, maximum):
        if not self.chunks:
            return b""
        value = self.chunks.pop(0)
        if isinstance(value, BaseException):
            raise value
        if len(value) > maximum:
            self.chunks.insert(0, value[maximum:])
        return value[:maximum]

    def close(self):
        self.closed = True


class EngineRequests(unittest.TestCase):
    def test_versioned_request_preserves_entity_bytes_and_closes_socket(self):
        probe, request = FakeSocket(version()), FakeSocket(http(b'{ "answer": 7 }\n'))
        with patch.object(engine.socket, "socket", side_effect=[probe, request]) as factory:
            client = engine.Engine()
            value, receipt = client.request("POST", "/containers/create?name=owned", {"Env": ["FIXTURE=value"]}, expected=(200, 201))
        self.assertEqual(value, {"answer": 7})
        self.assertEqual(client.last_body, b'{ "answer": 7 }\n')
        self.assertEqual(client.api_version, "1.54")
        self.assertEqual(client.server_version, "29.7.2")
        self.assertTrue(request.sent.startswith(b"POST /v1.54/containers/create?name=owned HTTP/1.1\r\n"))
        self.assertTrue(probe.sent.startswith(b"GET /version HTTP/1.1\r\n"))
        self.assertEqual(receipt["response_sha256"], "sha256:" + hashlib.sha256(client.last_body).hexdigest())
        self.assertTrue(receipt["connection_closed"] and receipt["response_complete"])
        self.assertTrue(probe.closed and request.closed)
        self.assertNotIn("FIXTURE=value", json.dumps(receipt))
        self.assertTrue(all(call.args == (socket.AF_UNIX, socket.SOCK_STREAM) for call in factory.call_args_list))

    def test_unsupported_api_does_not_silently_downgrade(self):
        sock = FakeSocket(version(ApiVersion="1.53"))
        with patch.object(engine.socket, "socket", return_value=sock):
            with self.assertRaisesRegex(engine.EngineError, "unsupported") as caught:
                engine.Engine()
        self.assertTrue(sock.closed)
        self.assertTrue(caught.exception.receipt["connection_closed"])

    def test_delete204_and_chunked_json(self):
        chunked = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                   b"4\r\n{\"a\"\r\n3\r\n:1}\r\n0\r\n\r\n")
        sockets = [FakeSocket(version()), FakeSocket(http(status=204)), FakeSocket(chunked)]
        with patch.object(engine.socket, "socket", side_effect=sockets):
            client = engine.Engine()
            self.assertIsNone(client.request("DELETE", "/containers/" + "a" * 64, expected=(204,))[0])
            self.assertEqual(client.request("GET", "/info")[0], {"a": 1})
        self.assertTrue(all(sock.closed for sock in sockets))

    def test_failed_status_and_malformed_json_keep_bounded_failure_body(self):
        for raw, reason in ((http(b'{"message":"missing"}', 404), "http-status"),
                            (http(b'{"a":1,"a":2}'), "invalid-json")):
            sock = FakeSocket(raw)
            with self.subTest(reason=reason), patch.object(engine.socket, "socket", side_effect=[FakeSocket(version()), sock]):
                client = engine.Engine()
                with self.assertRaisesRegex(engine.EngineError, reason) as caught:
                    client.request("GET", "/missing")
                self.assertEqual(caught.exception.body, client.last_body)
                self.assertTrue(caught.exception.receipt["connection_closed"])
            self.assertTrue(sock.closed)

    def test_response_bound_and_timeout_close_and_do_not_claim_complete(self):
        responses = [FakeSocket(http(b"12345")), FakeSocket(TimeoutError("timed out"))]
        for sock in responses:
            with self.subTest(sock=sock), patch.object(engine.socket, "socket", side_effect=[FakeSocket(version()), sock]):
                client = engine.Engine()
                with self.assertRaises(engine.EngineError) as caught:
                    client.request("GET", "/info", maximum=4)
                self.assertFalse(caught.exception.receipt["response_complete"])
                self.assertTrue(sock.closed)

    def test_tcp_and_header_injection_never_connect(self):
        with patch.object(engine.socket, "socket") as factory:
            with self.assertRaises(ValueError):
                engine.Engine("tcp://localhost:2375")
            factory.assert_not_called()
        with patch.object(engine.socket, "socket", return_value=FakeSocket(version())):
            client = engine.Engine()
        with patch.object(engine.socket, "socket") as factory:
            with self.assertRaises(ValueError):
                client.request("GET", "/info\r\nInjected: value")
            factory.assert_not_called()

    def test_partial_request_send_receipt_counts_actual_accepted_body_bytes(self):
        class BrokenBodySocket(FakeSocket):
            def send(self, value):
                if b"\r\n\r\n" in self.sent and self.sent.split(b"\r\n\r\n", 1)[1]:
                    raise OSError("synthetic connection loss")
                return super().send(value)
        sock = BrokenBodySocket()
        with patch.object(engine.socket, "socket", side_effect=[FakeSocket(version()), sock]):
            client = engine.Engine()
            with self.assertRaises(engine.EngineError) as caught:
                client.request("POST", "/containers/create", {"long": "x" * 100})
        actual = bytes(sock.sent).split(b"\r\n\r\n", 1)[1]
        self.assertEqual(len(actual), 17)
        self.assertEqual(caught.exception.receipt["request_bytes"], "17")
        self.assertEqual(caught.exception.receipt["request_sha256"], "sha256:" + hashlib.sha256(actual).hexdigest())
        self.assertTrue(sock.closed)


class EngineBuildAndArchive(unittest.TestCase):
    def test_build_streams_exact_tar_and_detects_error_even_with_http200(self):
        body = b'{"stream":"starting\\n"}\n{"errorDetail":{"message":"failed"},"error":"failed"}\n'
        sock = FakeSocket(http(body))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "context.tar"
            path.write_bytes(b"bounded synthetic tar request")
            with patch.object(engine.socket, "socket", side_effect=[FakeSocket(version()), sock]):
                client = engine.Engine()
                with self.assertRaisesRegex(engine.EngineError, "stream-error") as caught:
                    client.build(path, {"t": "owned:test"})
            self.assertEqual(bytes(sock.sent).split(b"\r\n\r\n", 1)[1], path.read_bytes())
            self.assertIn(b"networkmode=none", sock.sent)
            self.assertIn(b"pull=0", sock.sent)
            self.assertEqual(caught.exception.body, body)
            self.assertTrue(caught.exception.receipt["connection_closed"])

    def test_build_success_returns_actual_messages_and_network_override_rejects(self):
        body = b'{"stream":"step done\\n"}\n{"aux":{"ID":"sha256:' + b"a" * 64 + b'"}}\n'
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "context.tar"
            path.write_bytes(b"tar")
            with patch.object(engine.socket, "socket", side_effect=[FakeSocket(version()), FakeSocket(http(body))]) as factory:
                client = engine.Engine()
                rows, receipt = client.build(path, {"labels": {"owned": "yes"}})
                self.assertEqual(rows[-1]["aux"]["ID"], "sha256:" + "a" * 64)
                self.assertEqual(receipt["response_bytes"], str(len(body)))
                with self.assertRaisesRegex(ValueError, "network-or-recipe"):
                    client.build(path, {"networkmode": "host"})
                self.assertEqual(factory.call_count, 2)

    def test_archive_streams_exclusive_file_with_exact_hash_and_path_quote(self):
        body = b"actual tar entity bytes\0\xff"
        sock = FakeSocket(http(body, headers={"X-Docker-Container-Path-Stat": "bounded-metadata"}))
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "download.tar"
            with patch.object(engine.socket, "socket", side_effect=[FakeSocket(version()), sock]) as factory:
                client = engine.Engine()
                receipt = client.download_archive("a" * 64, "/retained/build root", destination)
                self.assertEqual(destination.read_bytes(), body)
                self.assertEqual(receipt["response_sha256"], "sha256:" + hashlib.sha256(body).hexdigest())
                self.assertTrue(receipt["file_closed"] and receipt["connection_closed"])
                self.assertEqual(receipt["archive_stat_header"], "bounded-metadata")
                self.assertIn(b"path=%2Fretained%2Fbuild+root", sock.sent)
                with self.assertRaises(FileExistsError):
                    client.download_archive("a" * 64, "/same", destination)
                self.assertEqual(factory.call_count, 2)

    def test_archive_bound_is_enforced_before_any_overflow_write(self):
        sock = FakeSocket(http(b"12345"))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "download.tar"
            with patch.object(engine.socket, "socket", side_effect=[FakeSocket(version()), sock]):
                client = engine.Engine()
                with self.assertRaisesRegex(engine.EngineError, "byte-bound") as caught:
                    client.download_archive("a" * 64, "/source", path, maximum=4)
            self.assertEqual(path.read_bytes(), b"")
            self.assertTrue(caught.exception.receipt["file_closed"])
            self.assertTrue(sock.closed)


class EngineAttach(unittest.TestCase):
    def test_buffered_upgrade_frames_demux_and_raw_files_are_exact(self):
        out = b'{"event":"ready"}\n'
        err = b"diagnostic bytes\0"
        sock = FakeSocket(upgrade(frame(2, err) + frame(1, out)))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(engine.socket, "socket", side_effect=[FakeSocket(version()), sock]):
                client = engine.Engine()
                attached = client.attach("a" * 64, root / "stdout", root / "stderr")
                attached.send_line('{"command":"start"}')
                self.assertEqual(attached.next_line(1), '{"event":"ready"}')
                with self.assertRaises(EOFError):
                    attached.next_line(1)
                receipt = attached.close()
                self.assertIs(attached.close(), receipt)
            self.assertEqual((root / "stdout").read_bytes(), out)
            self.assertEqual((root / "stderr").read_bytes(), err)
            self.assertEqual(receipt["stdout_sha256"], "sha256:" + hashlib.sha256(out).hexdigest())
            self.assertEqual(receipt["stderr_sha256"], "sha256:" + hashlib.sha256(err).hexdigest())
            self.assertTrue(receipt["eof"] and receipt["files_closed"] and receipt["connection_closed"])
            self.assertTrue(sock.sent.endswith(b'{"command":"start"}\n'))

    def test_partial_frame_survives_nonfatal_poll_timeout(self):
        body = b'{"event":"ready"}\n'
        first = frame(1, body)
        sock = FakeSocket(upgrade(), first[:11], TimeoutError("poll timeout"), first[11:])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(engine.socket, "socket", side_effect=[FakeSocket(version()), sock]):
                attached = engine.Engine().attach("a" * 64, root / "stdout", root / "stderr")
                with self.assertRaises(TimeoutError):
                    attached.next_line(1)
                self.assertFalse(sock.closed)
                self.assertEqual(attached.next_line(1), '{"event":"ready"}')
                self.assertIsNone(attached.close()["failure"])

    def test_malformed_or_oversized_stream_closes_with_failure_receipt(self):
        cases = [b"\x03\0\0\0" + (1).to_bytes(4, "big") + b"x",
                 b"\x01\0\0\0" + (engine.MAXIMUM_ATTACH + 1).to_bytes(4, "big"),
                 b"\x02\0\0\0" + (engine.MAXIMUM_STDERR + 1).to_bytes(4, "big"),
                 frame(1, b"x" * 4096 + b"\n")]
        for data in cases:
            with self.subTest(size=len(data)), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                sock = FakeSocket(upgrade(data))
                with patch.object(engine.socket, "socket", side_effect=[FakeSocket(version()), sock]):
                    attached = engine.Engine().attach("a" * 64, root / "stdout", root / "stderr")
                    with self.assertRaises(engine.EngineError) as caught:
                        attached.next_line(1)
                    self.assertTrue(caught.exception.receipt["connection_closed"])
                    self.assertTrue(caught.exception.receipt["files_closed"])
                    self.assertFalse(caught.exception.receipt["eof"])
                self.assertTrue(sock.closed)

    def test_partial_frame_eof_and_input_line_bounds_are_explicit(self):
        sock = FakeSocket(upgrade(frame(1, b"test\n")[:-1]))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(engine.socket, "socket", side_effect=[FakeSocket(version()), sock]):
                attached = engine.Engine().attach("a" * 64, root / "stdout", root / "stderr")
                for value in ("two\nlines", "x" * 65536):
                    with self.assertRaises(ValueError):
                        attached.send_line(value)
                with self.assertRaisesRegex(engine.EngineError, "truncated-frame"):
                    attached.next_line(1)
                self.assertTrue(sock.closed)
                self.assertEqual((root / "stdout").read_bytes(), b"test")


if __name__ == "__main__":
    unittest.main()
