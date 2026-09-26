"""A bounded authenticated loopback peer driven by the node supervisor's selector."""
from __future__ import annotations

import base64
import hmac
import os
import selectors
import socket
import time

from . import http_fixture
from .common import DevError, digest, encode, require


class Peer:
    def __init__(self, root, fixture, selector):
        self.fixture = http_fixture.validate(fixture)
        self.authorization = http_fixture.credential(root, fixture)
        self.selector = selector
        self.clients = {}
        self.completed = self.rejected = self.accepted = 0
        self.failure = None
        self.deadline = time.monotonic() + 900
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Linux permits a retained restart over closed TIME_WAIT sockets,
            # but still rejects another live listener (SO_REUSEPORT is absent).
            if os.name == "posix":
                self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            else:
                self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.listener.bind(("127.0.0.1", fixture["port"]))
            self.listener.listen(4)
            self.listener.setblocking(False)
            selector.register(self.listener, selectors.EVENT_READ, "http-fixture")
        except OSError:
            self.listener.close()
            raise DevError("http-fixture-port-unavailable") from None
        except BaseException:
            self.listener.close()
            raise

    def observation(self):
        return {"kind": "controlled-peer", "state": "ready" if self.listener is not None and self.failure is None else "stopped",
            "configurationSha256": digest(encode(self.fixture)), "authentication": "private-provider-credential",
            "credentialReference": "dev-http-peer", "completedRequests": self.completed,
            "rejectedUnauthenticatedRequests": self.rejected, "acceptedConnections": self.accepted,
            "openConnections": len(self.clients), "maximumConnections": 4, "maximumRequests": 128,
            "maximumSeconds": 900, "requestTimeoutMillis": 2000, "failure": self.failure}

    def close_client(self, stream):
        if stream in self.clients:
            self.selector.unregister(stream)
            del self.clients[stream]
        stream.close()

    def close(self):
        for stream in list(self.clients):
            self.close_client(stream)
        if self.listener is not None:
            self.selector.unregister(self.listener)
            self.listener.close()
            self.listener = None
        return {**self.observation(), "cleanup": "owned-listener-and-connections-closed"}

    def check(self):
        if time.monotonic() >= self.deadline:
            self.failure = "http-fixture-lifetime-exhausted"
        for stream, record in list(self.clients.items()):
            if time.monotonic() >= record["deadline"]:
                self.close_client(stream)
                if record["authorized"]:
                    self.failure = "http-fixture-request-deadline"
                else:
                    self.rejected += 1
        require(self.failure is None, self.failure or "http-fixture-failed")

    def event(self, key, events):
        stream = key.fileobj
        if stream is self.listener:
            connection, _ = self.listener.accept()
            self.accepted += 1
            if len(self.clients) >= 4 or self.accepted > 128:
                connection.close()
                self.failure = "http-fixture-connection-bound"
                return
            connection.setblocking(False)
            self.clients[connection] = {"input": bytearray(), "output": None, "offset": 0,
                                        "deadline": time.monotonic() + 2, "authorized": False}
            self.selector.register(connection, selectors.EVENT_READ, "http-fixture")
            return
        record = self.clients[stream]
        try:
            if events & selectors.EVENT_READ:
                raw = stream.recv(4096)
                require(raw, "http-fixture-request-truncated")
                record["input"].extend(raw)
                require(len(record["input"]) <= 8192 + 32768, "http-fixture-request-bound")
                reply = self.response(record)
                if reply is not None:
                    record["output"] = reply
                    self.selector.modify(stream, selectors.EVENT_WRITE, "http-fixture")
            elif events & selectors.EVENT_WRITE:
                record["offset"] += stream.send(record["output"][record["offset"]:])
                if record["offset"] == len(record["output"]):
                    if record["authorized"]:
                        self.completed += 1
                    self.close_client(stream)
        except BlockingIOError:
            pass
        except (OSError, DevError) as error:
            if record["authorized"]:
                self.failure = error.code if isinstance(error, DevError) else "http-fixture-connection-failed"
            else:
                self.rejected += 1
            self.close_client(stream)

    def response(self, record):
        raw = record["input"]
        end = raw.find(b"\r\n\r\n")
        if end < 0:
            require(len(raw) < 8192, "http-fixture-header-bound")
            return None
        require(end + 4 <= 8192, "http-fixture-header-bound")
        lines = bytes(raw[:end]).split(b"\r\n")
        request = lines[0].split(b" ")
        require(len(request) == 3 and request[2] == b"HTTP/1.1", "http-fixture-request-line")
        headers = {}
        for line in lines[1:]:
            require(b":" in line, "http-fixture-header")
            name, value = line.split(b":", 1)
            name = name.lower()
            require(name not in headers and len(headers) < 32, "http-fixture-header-count-or-duplicate")
            headers[name] = value.strip()
        if not hmac.compare_digest(headers.get(b"authorization", b""), self.authorization):
            self.rejected += 1
            return b"HTTP/1.1 401 Fixture\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        record["authorized"] = True
        require(headers.get(b"host") == f'127.0.0.1:{self.fixture["port"]}'.encode()
                and b"transfer-encoding" not in headers, "http-fixture-origin-or-framing")
        selected = [entry for entry in self.fixture["exchanges"]
                    if request[:2] == [entry["method"].encode(), entry["path"].encode()]]
        require(len(selected) == 1, "http-fixture-unmatched-request")
        entry = selected[0]
        expected = base64.b64decode(entry["requestBody"], validate=True)
        length = headers.get(b"content-length", b"0")
        require(length == str(len(expected)).encode(), "http-fixture-body-length")
        if len(raw) < end + 4 + len(expected):
            return None
        require(raw[end + 4:] == expected, "http-fixture-body-mismatch")
        body = base64.b64decode(entry["responseBody"], validate=True)
        head = (f'HTTP/1.1 {entry["status"]} Fixture\r\nContent-Length: {len(body)}\r\n'
                'Content-Type: application/octet-stream\r\nConnection: close\r\n\r\n').encode()
        return head + (body if entry["method"] != "HEAD" else b"")
