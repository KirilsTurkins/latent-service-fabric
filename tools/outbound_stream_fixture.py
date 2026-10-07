"""Finite loopback SMTP peer for separately owned outbound-stream observations.

This peer accepts ordinary SMTP clients. It neither installs a provider nor
grants network authority. Its caller drives the selector, retains observations
and closes it; no worker, retry, forwarding connection or credential is created.
"""
from __future__ import annotations

import hashlib
import selectors
import socket
import time


MAX_CONNECTIONS = 2
MAX_ATTEMPTS = 32
MAX_MESSAGE_BYTES = 65536
MAX_LINE_BYTES = 4096
MAX_COMMANDS = 128
MAX_OUTPUT_BYTES = 4096
IDLE_SECONDS = 2
CONNECTION_SECONDS = 10
LIFETIME_SECONDS = 900


class SmtpPeer:
    """A controlled mutation sink; lost replies do not erase accepted DATA."""

    def __init__(self, selector, *, port=0, drop_mutation_reply=False, fragment_bytes=7):
        if (type(port) is not int or not 0 <= port <= 65535
                or type(drop_mutation_reply) is not bool
                or type(fragment_bytes) is not int or not 1 <= fragment_bytes <= 1024):
            raise ValueError("invalid-outbound-stream-fixture")
        self.selector = selector
        self.drop_mutation_reply = drop_mutation_reply
        self.fragment_bytes = fragment_bytes
        self.clients = {}
        self.attempts = self.rejected = self.expired = self.replies = 0
        self.mutations = []
        self.deadline = time.monotonic() + LIFETIME_SECONDS
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.listener.bind(("127.0.0.1", port))
            self.listener.listen(MAX_CONNECTIONS)
            self.listener.setblocking(False)
            self.port = self.listener.getsockname()[1]
            selector.register(self.listener, selectors.EVENT_READ, self)
        except BaseException:
            self.listener.close()
            self.listener = None
            raise

    def observation(self):
        return {
            "kind": "controlled-loopback-smtp-peer",
            "state": "ready" if self.listener is not None else ("quiescing" if self.clients else "stopped"),
            "host": "127.0.0.1", "port": self.port,
            "acceptedConnections": self.attempts,
            "rejectedConnections": self.rejected,
            "expiredConnections": self.expired,
            "openConnections": len(self.clients),
            "listenerOwners": int(self.listener is not None),
            "acceptedMutations": len(self.mutations),
            "confirmedMutationReplies": self.replies,
            "mutationRecords": [dict(row) for row in self.mutations],
            "maximumConnections": MAX_CONNECTIONS,
            "maximumAttempts": MAX_ATTEMPTS,
            "maximumMessageBytes": MAX_MESSAGE_BYTES,
            "idleTimeoutMillis": IDLE_SECONDS * 1000,
            "absoluteTimeoutMillis": CONNECTION_SECONDS * 1000,
            "maximumSeconds": LIFETIME_SECONDS,
            "dropMutationReply": self.drop_mutation_reply,
            "fragmentBytes": self.fragment_bytes,
            "hostTlsOrGuestQualificationClaimed": False,
        }

    def _close_client(self, stream):
        if stream in self.clients:
            self.selector.unregister(stream)
            del self.clients[stream]
        stream.close()

    def close(self):
        for stream in list(self.clients):
            self._close_client(stream)
        if self.listener is not None:
            self.selector.unregister(self.listener)
            self.listener.close()
            self.listener = None
        return {**self.observation(), "cleanup": "owned-listener-and-connections-closed"}

    def check(self, now=None):
        now = time.monotonic() if now is None else now
        for stream, record in list(self.clients.items()):
            if now >= min(record["idle"], record["absolute"], self.deadline):
                self.expired += 1
                self._close_client(stream)
        if now >= self.deadline:
            self.close()

    def _reply(self, record, data):
        record["output"].extend(data)
        if len(record["output"]) > MAX_OUTPUT_BYTES:
            raise ValueError("outbound-stream-fixture-output-bound")

    def _line(self, stream, record, line):
        if record["data"]:
            if line == b".":
                self.mutations.append({
                    "attempt": record["attempt"], "bytes": record["bytes"],
                    "sha256": record["hash"].hexdigest(),
                    "recipients": record["recipients"],
                })
                record["data"] = False
                record["committed"] = True
                if self.drop_mutation_reply:
                    self._close_client(stream)
                    return
                self._reply(record, b"250 accepted\r\n")
                record["confirming"] = True
                return
            if line.startswith(b".."):
                line = line[1:]
            record["bytes"] += len(line) + 2
            if record["bytes"] > MAX_MESSAGE_BYTES:
                raise ValueError("outbound-stream-fixture-message-bound")
            record["hash"].update(line + b"\r\n")
            return
        record["commands"] += 1
        if record["commands"] > MAX_COMMANDS:
            raise ValueError("outbound-stream-fixture-command-bound")
        command, _, argument = line.partition(b" ")
        command = command.upper()
        if command in (b"EHLO", b"HELO") and argument and not record["mail"]:
            record["greeted"] = True
            self._reply(record, b"250-loopback.invalid\r\n250 8BITMIME\r\n")
        elif command == b"MAIL" and argument.upper().startswith(b"FROM:"):
            if record["greeted"] and not record["mail"] and not record["committed"]:
                record["mail"] = True
                self._reply(record, b"250 sender accepted\r\n")
            else:
                self._reply(record, b"503 sequence denied\r\n")
        elif command == b"RCPT" and argument.upper().startswith(b"TO:"):
            if record["mail"] and record["recipients"] < 8 and not record["committed"]:
                record["recipients"] += 1
                self._reply(record, b"250 recipient accepted\r\n")
            else:
                self._reply(record, b"503 sequence denied\r\n")
        elif command == b"DATA" and not argument:
            if record["mail"] and record["recipients"] and not record["committed"]:
                record["data"] = True
                self._reply(record, b"354 finish with dot\r\n")
            else:
                self._reply(record, b"503 sequence denied\r\n")
        elif command == b"QUIT" and not argument:
            self._reply(record, b"221 closed\r\n")
            record["closing"] = True
        elif command == b"NOOP" and not argument:
            self._reply(record, b"250 ready\r\n")
        else:
            # AUTH, STARTTLS and opaque input are never logged or forwarded.
            self._reply(record, b"502 command unsupported\r\n")

    def event(self, key, events):
        stream = key.fileobj
        if stream is self.listener:
            connection, _address = self.listener.accept()
            self.attempts += 1
            if self.attempts == MAX_ATTEMPTS:
                self.selector.unregister(self.listener)
                self.listener.close()
                self.listener = None
            if len(self.clients) >= MAX_CONNECTIONS or self.attempts > MAX_ATTEMPTS:
                self.rejected += 1
                connection.close()
                return
            connection.setblocking(False)
            now = time.monotonic()
            self.clients[connection] = {
                "attempt": self.attempts, "input": bytearray(),
                "output": bytearray(b"220 loopback.invalid SMTP\r\n"),
                "idle": now + IDLE_SECONDS, "absolute": now + CONNECTION_SECONDS,
                "greeted": False, "mail": False, "recipients": 0, "data": False,
                "bytes": 0, "hash": hashlib.sha256(), "commands": 0,
                "committed": False, "confirming": False, "closing": False,
            }
            self.selector.register(connection, selectors.EVENT_READ | selectors.EVENT_WRITE, self)
            return
        record = self.clients.get(stream)
        if record is None:
            return
        try:
            if events & selectors.EVENT_READ:
                raw = stream.recv(4096)
                if not raw:
                    self._close_client(stream)
                    return
                record["idle"] = time.monotonic() + IDLE_SECONDS
                record["input"].extend(raw)
                while b"\r\n" in record["input"]:
                    end = record["input"].index(b"\r\n")
                    if end > MAX_LINE_BYTES:
                        raise ValueError("outbound-stream-fixture-line-bound")
                    line = bytes(record["input"][:end])
                    del record["input"][:end + 2]
                    self._line(stream, record, line)
                    if stream not in self.clients:
                        return
                    if record["closing"]:
                        record["input"].clear()
                        break
                if len(record["input"]) > MAX_LINE_BYTES:
                    raise ValueError("outbound-stream-fixture-line-bound")
            if events & selectors.EVENT_WRITE and record["output"]:
                sent = stream.send(record["output"][:self.fragment_bytes])
                del record["output"][:sent]
                if not record["output"]:
                    if record["confirming"]:
                        self.replies += 1
                        record["confirming"] = False
                    if record["closing"]:
                        self._close_client(stream)
                        return
            interest = selectors.EVENT_READ
            if record["output"]:
                interest |= selectors.EVENT_WRITE
            self.selector.modify(stream, interest, self)
        except BlockingIOError:
            pass
        except (OSError, ValueError):
            self.rejected += 1
            self._close_client(stream)
