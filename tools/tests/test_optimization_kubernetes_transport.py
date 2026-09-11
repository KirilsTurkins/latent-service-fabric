"""Reject crossed or incomplete original API/observer bytes without infrastructure."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.optimization_kubernetes import node, transport


class Response:
    status = 200

    def __init__(self, data=b'{"kind":"Pod"}'):
        self.data = data

    def getheader(self, name, default):
        return default

    def read(self, length):
        result, self.data = self.data[:length], self.data[length:]
        return result


class Connection:
    def __init__(self, response):
        self.response, self.closed = response, False

    def request(self, *args):
        self.args = args

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class TransportTests(unittest.TestCase):
    def test_original_success_bytes_and_closed_connection(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "api.ndjson"
            connection = Connection(Response(b'{ "kind" : "Pod" }\n'))
            with patch.object(transport.http.client, "HTTPSConnection", return_value=connection):
                client = transport.Kubernetes("lsf-112-123456abcdef-control-plane", object(), transport.Journal(path))
                value, call = client.call("GET", "/api/v1/namespaces/test/pods/app")
            self.assertEqual((value, call), ({"kind": "Pod"}, 0))
            row = json.loads(path.read_bytes())
            self.assertEqual(base64.b64decode(row["response"]["base64"]), b'{ "kind" : "Pod" }\n')
            self.assertTrue(row["response_complete"] and row["connection_closed"] and connection.closed)

    def test_failed_status_keeps_original_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "api.ndjson"
            response = Response(b'{"reason":"AlreadyExists"}')
            response.status = 409
            connection = Connection(response)
            with patch.object(transport.http.client, "HTTPSConnection", return_value=connection):
                client = transport.Kubernetes("lsf-112-123456abcdef-control-plane", object(), transport.Journal(path))
                with self.assertRaisesRegex(ValueError, "kubernetes-api-status"):
                    client.call("POST", "/api/v1/namespaces", {"kind": "Namespace"})
            row = json.loads(path.read_bytes())
            self.assertEqual(row["status"], 409)
            self.assertIsNotNone(row["failure"])
            self.assertTrue(row["response_complete"] and connection.closed)
            self.assertEqual(base64.b64decode(row["response"]["base64"]), b'{"reason":"AlreadyExists"}')

    def test_pod_log_is_original_text_not_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            connection = Connection(Response(b'{"event":"ready"}\n'))
            with patch.object(transport.http.client, "HTTPSConnection", return_value=connection):
                client = transport.Kubernetes("lsf-112-123456abcdef-control-plane", object(),
                                               transport.Journal(Path(temporary) / "api.ndjson"))
                value, _ = client.call("GET", "/api/v1/namespaces/test/pods/client/log", json_response=False)
            self.assertEqual(value, b'{"event":"ready"}\n')

    def test_partial_or_oversized_response_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "api.ndjson"
            connection = Connection(Response(b"x" * 33))
            with patch.object(transport.http.client, "HTTPSConnection", return_value=connection), \
                    patch.object(transport, "MAX_RESPONSE", 32):
                client = transport.Kubernetes("lsf-112-123456abcdef-control-plane", object(), transport.Journal(path))
                with self.assertRaisesRegex(ValueError, "response-bound"):
                    client.call("GET", "/api/v1/nodes")
            row = json.loads(path.read_bytes())
            self.assertFalse(row["response_complete"])
            self.assertTrue(connection.closed)

    def test_api_owner_and_path_not_redirectable(self):
        with tempfile.TemporaryDirectory() as temporary:
            journal = transport.Journal(Path(temporary) / "api.ndjson")
            for host in ("localhost", "lsf-112-123456abcdef-control-plane.evil", "https://example.com"):
                with self.assertRaises(ValueError):
                    transport.Kubernetes(host, object(), journal)
            client = transport.Kubernetes("lsf-112-123456abcdef-control-plane", object(), journal)
            for path in ("//example.com/", "/api/v1/nodes\r\nHost: other", "https://example.com"):
                with self.assertRaises(ValueError):
                    client.call("GET", path)
            self.assertEqual(journal.count, 0)

    def test_exec_stream_retains_both_channels(self):
        first = b"\x01\0\0\0\0\0\0\x03one"
        second = b"\x02\0\0\0\0\0\0\x03err"
        self.assertEqual(transport.multiplexed(first + second + first), (b"oneone", b"err"))

    def test_exec_stream_rejects_truncation_and_wrong_channel(self):
        for raw in (b"\x01", b"\x01\0\0\0\0\0\0\x03on", b"\x03\0\0\0\0\0\0\0",
                    b"\x01\x01\0\0\0\0\0\0"):
            with self.assertRaises(ValueError):
                transport.multiplexed(raw)

    def test_observer_rejects_ambiguous_or_unbounded_bytes(self):
        for raw in (b"pid\tMQ==\npid\tMg==\n", b"pid\t$\n", b"../pid\tMQ==\n",
                    b"stat\t" + base64.b64encode(b"x" * 65537) + b"\n"):
            with self.assertRaises(ValueError):
                node.fields(raw)

    def test_observer_preserves_missing_fields_as_missing(self):
        value = node.fields(b"memory.max\t-\nstat\tYWJjCg==\n")
        self.assertEqual(value["memory.max"], {"value": None, "unavailable_reason": "open-failed"})
        self.assertEqual(value["stat"], {"value": "abc\n", "unavailable_reason": None})


if __name__ == "__main__":
    unittest.main()
