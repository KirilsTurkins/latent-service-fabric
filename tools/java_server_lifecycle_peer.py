"""Owned loopback HTTP rendezvous for actual invocation lifetime observations."""
from __future__ import annotations

import select
import socket
import threading
import time

from tools.dev_workflow.common import require


class GatePeer:
    """One request, no redirects/retries, and separate sent/physical-close facts."""
    def __init__(self, deadline: float, *, port=0):
        require(time.monotonic() < deadline <= time.monotonic() + 125,
                "server-lifecycle-peer-deadline")
        self.deadline = deadline
        self.started, self.release, self.closed, self.stop = (threading.Event() for _ in range(4))
        self.accepted = self.sent = 0
        self.failure = None
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        require(type(port) is int and 0 <= port <= 65535, "server-lifecycle-peer-port")
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", port))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._run, name="java-server-owned-gate", daemon=False)
        self.thread.start()

    def remaining(self, maximum: float) -> float:
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "server-lifecycle-peer-expired")
        return min(remaining, maximum)

    def _run(self):
        try:
            connection = None
            while connection is None and not self.stop.is_set():
                self.listener.settimeout(self.remaining(.05))
                try:
                    connection, _ = self.listener.accept()
                except TimeoutError:
                    pass
            if connection is None:
                return
            with connection:
                self.accepted += 1
                data = bytearray()
                while b"\r\n\r\n" not in data:
                    connection.settimeout(self.remaining(2))
                    part = connection.recv(min(1024, 8193 - len(data)))
                    require(part and len(data) + len(part) <= 8192,
                            "server-lifecycle-peer-header-bound")
                    data.extend(part)
                head, body = bytes(data).split(b"\r\n\r\n", 1)
                lines = head.split(b"\r\n")
                require(lines[0] == b"GET /gate HTTP/1.1" and not body and len(lines) <= 17,
                        "server-lifecycle-peer-request")
                fields = {}
                for line in lines[1:]:
                    key, value = line.split(b":", 1)
                    key = key.lower()
                    require(key not in fields, "server-lifecycle-peer-duplicate-header")
                    fields[key] = value.strip()
                require(b"transfer-encoding" not in fields
                        and fields.get(b"content-length", b"0") == b"0"
                        and fields.get(b"host") == f"127.0.0.1:{self.port}".encode(),
                        "server-lifecycle-peer-framing-or-authority")
                self.started.set()
                while not self.stop.is_set():
                    readable, _, _ = select.select([connection], [], [], self.remaining(.025))
                    if readable:
                        try:
                            extra = connection.recv(1)
                        except ConnectionResetError:
                            extra = b""
                        require(extra == b"", "server-lifecycle-peer-extra-request")
                        self.closed.set()
                        return
                    if self.release.is_set():
                        connection.settimeout(self.remaining(2))
                        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\nConnection: close\r\n\r\nG")
                        self.sent += 1
                        # sendall proves submission, not remote receipt. A normal
                        # handler response is independently checked by ingress.
                        return
        except BaseException as error:
            self.failure = error
        finally:
            self.listener.close()

    def wait(self, event: threading.Event, maximum=5):
        require(event.wait(self.remaining(maximum)), "server-lifecycle-peer-rendezvous")
        if self.failure is not None:
            raise self.failure

    def snapshot(self):
        return {"acceptedRequests": self.accepted, "sentReplies": self.sent,
                "remoteReceiptConfirmed": False, "physicalPeerCloseObserved": self.closed.is_set()}

    def close(self):
        self.stop.set()
        self.thread.join(max(.05, min(2, self.deadline - time.monotonic())))
        require(not self.thread.is_alive(), "server-lifecycle-peer-thread-not-reaped")
        if self.failure is not None:
            raise self.failure

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()
