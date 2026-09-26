"""Finite TLS NATS-protocol peer owned by the supervisor; not a live broker."""
from __future__ import annotations

import base64
import hmac
import os
import re
import selectors
import socket
import ssl
import time

from . import event_fixture, paths
from .common import DevError, decode, digest, encode, require


class Peer:
    def __init__(self, root, fixture, selector):
        self.fixture = event_fixture.validate(fixture)
        directory, material, _ = event_fixture.material(root, fixture)
        self.authorization = material["authorization"]
        self.selector = selector
        self.clients = {}
        self.accepted = self.rejected = self.received = self.acknowledged = 0
        self.by_topic = {row["topic"]: 0 for row in fixture["exchanges"]}
        self.failure = None
        self.deadline = time.monotonic() + 900
        self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.tls.minimum_version = ssl.TLSVersion.TLSv1_2
        with paths.opened(directory, "server.pem"), paths.opened(directory, "key.pem"):
            self.tls.load_cert_chain(directory / "server.pem", directory / "key.pem")
        event_fixture.material(root, fixture)
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "posix":
                self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            else:
                self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.listener.bind(("127.0.0.1", fixture["port"]))
            self.listener.listen(4)
            self.listener.setblocking(False)
            selector.register(self.listener, selectors.EVENT_READ, "event-fixture")
        except BaseException:
            self.listener.close()
            raise DevError("event-fixture-port-or-listener-unavailable") from None

    def observation(self):
        return {"kind": "controlled-peer", "protocol": "tls-nats-publish", "liveBroker": False,
            "state": "ready" if self.listener is not None and self.failure is None else "stopped",
            "configurationSha256": digest(encode(self.fixture)), "authentication": "private-tls-provider-credential",
            "credentialReference": "dev-event-peer", "receivedPublishes": self.received,
            "sentAcknowledgements": self.acknowledged, "receivedByTopic": dict(self.by_topic),
            "rejectedUnauthenticatedConnections": self.rejected, "acceptedConnections": self.accepted,
            "openConnections": len(self.clients), "maximumConnections": 4, "maximumPublishes": 128,
            "maximumCommandsPerConnection": 128, "maximumSeconds": 900, "frameTimeoutMillis": 2000,
            "failure": self.failure}

    def close_client(self, stream):
        if stream in self.clients:
            del self.clients[stream]
            try:
                self.selector.unregister(stream)
            except (KeyError, ValueError):
                # A failed selector registration still leaves an owned socket.
                pass
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
            self.failure = "event-fixture-lifetime-exhausted"
        for stream, record in list(self.clients.items()):
            if time.monotonic() >= record["deadline"]:
                if record["authorized"]:
                    self.failure = "event-fixture-frame-deadline"
                else:
                    self.rejected += 1
                self.close_client(stream)
        require(self.failure is None, self.failure or "event-fixture-failed")

    def event(self, key, _events):
        stream = key.fileobj
        if stream is self.listener:
            connection, _ = self.listener.accept()
            self.accepted += 1
            if len(self.clients) >= 4 or self.accepted > 128:
                connection.close()
                self.failure = "event-fixture-connection-bound"
                return
            wrapped = None
            try:
                connection.setblocking(False)
                wrapped = self.tls.wrap_socket(connection, server_side=True, do_handshake_on_connect=False)
                stream = wrapped
                self.clients[stream] = {"handshake": False, "authorized": False, "input": bytearray(),
                    "output": bytearray(), "deadline": time.monotonic() + 2, "commands": 0,
                    "inbox": None, "publish": None, "unsubscribed": False}
                self.selector.register(stream, selectors.EVENT_READ, "event-fixture")
            except BaseException:
                if wrapped is not None:
                    self.close_client(wrapped)
                else:
                    connection.close()
                raise
            return
        record = self.clients[stream]
        try:
            if not record["handshake"]:
                stream.do_handshake()
                record["handshake"] = True
                record["output"].extend(b'INFO {"headers":true,"tls_required":true,"auth_required":true,"max_payload":65536}\r\n')
            if record["output"]:
                sent = stream.send(record["output"])
                del record["output"][:sent]
                if record["output"]:
                    self.selector.modify(stream, selectors.EVENT_WRITE, "event-fixture")
                    return
                self.acknowledged += record.pop("acknowledgementsPending", 0)
            raw = stream.recv(4096)
            if not raw:
                self.close_client(stream)
                return
            if not record["input"]:
                record["deadline"] = time.monotonic() + 2
            record["input"].extend(raw)
            require(len(record["input"]) <= 4096 + 32768 + 1024, "event-fixture-frame-bound")
            for _ in range(16):
                if not self.frame(stream, record):
                    break
                if stream not in self.clients:
                    return
            if not record["input"] and record["publish"] is None and record["authorized"]:
                record["deadline"] = self.deadline
            self.selector.modify(stream, selectors.EVENT_WRITE if record["output"] else selectors.EVENT_READ, "event-fixture")
        except ssl.SSLWantReadError:
            self.selector.modify(stream, selectors.EVENT_READ, "event-fixture")
        except ssl.SSLWantWriteError:
            self.selector.modify(stream, selectors.EVENT_WRITE, "event-fixture")
        except BlockingIOError:
            pass
        except (OSError, DevError) as error:
            if record["authorized"]:
                self.failure = error.code if isinstance(error, DevError) else "event-fixture-connection-failed"
            else:
                self.rejected += 1
            self.close_client(stream)

    def frame(self, stream, record):
        raw = record["input"]
        if record["publish"] is not None:
            topic, inbox, headers, total = record["publish"]
            if len(raw) < total + 2:
                return False
            require(raw[total:total + 2] == b"\r\n", "event-fixture-payload-framing")
            self.publish(record, topic, inbox, bytes(raw[:headers]), bytes(raw[headers:total]))
            del raw[:total + 2]
            record["publish"] = None
            record["inbox"] = None
            if record.pop("drop", False):
                self.close_client(stream)
            return True
        end = raw.find(b"\r\n")
        if end < 0:
            require(len(raw) <= 1024, "event-fixture-command-bound")
            return False
        require(end <= 1024, "event-fixture-command-bound")
        line = bytes(raw[:end])
        del raw[:end + 2]
        record["commands"] += 1
        require(record["commands"] <= 128, "event-fixture-command-count")
        if line.startswith(b"CONNECT "):
            require(not record["authorized"], "event-fixture-duplicate-connect")
            connect = decode(line[8:], 1024)
            token = connect.get("auth_token") if isinstance(connect, dict) else None
            if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self.authorization):
                self.rejected += 1
                self.close_client(stream)
            else:
                record["authorized"] = True
            return True
        require(record["authorized"], "event-fixture-authentication-required")
        parts = line.split(b" ")
        if line == b"PING":
            record["output"].extend(b"PONG\r\n")
        elif len(parts) == 3 and parts[0] == b"SUB" and parts[2] == b"1":
            require(record["inbox"] is None and re.fullmatch(rb"_INBOX\.LSF\.[A-Za-z0-9.]{1,100}", parts[1]),
                    "event-fixture-subscription")
            record["inbox"] = parts[1]
            record["unsubscribed"] = False
        elif line == b"UNSUB 1 1":
            require(record["inbox"] is not None and not record["unsubscribed"], "event-fixture-unsubscribe")
            record["unsubscribed"] = True
        elif len(parts) == 5 and parts[0] == b"HPUB":
            require(record["inbox"] == parts[2] and record["unsubscribed"]
                    and all(re.fullmatch(rb"[0-9]{1,5}", item) for item in parts[3:]), "event-fixture-publish-command")
            headers, total = map(int, parts[3:])
            require(0 < headers <= 4096 and headers <= total <= headers + 32768, "event-fixture-publish-bound")
            record["publish"] = (parts[1], parts[2], headers, total)
        else:
            raise DevError("event-fixture-unexpected-command")
        return True

    def publish(self, record, topic, inbox, headers, body):
        entries = [row for row in self.fixture["exchanges"] if row["topic"].encode() == topic]
        require(len(entries) == 1 and self.received < 128, "event-fixture-unmatched-or-exhausted-publish")
        entry = entries[0]
        require(body == base64.b64decode(entry["payload"], validate=True), "event-fixture-payload-mismatch")
        require(headers.startswith(b"NATS/1.0\r\n") and headers.endswith(b"\r\n\r\n"), "event-fixture-headers")
        fields = {}
        for line in headers[10:-4].split(b"\r\n"):
            require(b": " in line, "event-fixture-header-field")
            name, value = line.split(b": ", 1)
            require(name not in fields and len(fields) < 20, "event-fixture-header-count")
            fields[name] = value
        require(fields.get(b"Nats-Expected-Stream") == b"LSF_DEV"
                and re.fullmatch(rb"lsf-[a-f0-9]{64}", fields.get(b"Nats-Msg-Id", b""))
                and fields.get(b"Content-Type") == b"application/octet-stream", "event-fixture-header-scope")
        self.received += 1
        self.by_topic[entry["topic"]] += 1
        mode = entry["mode"]
        if mode == "drop-ack":
            record["drop"] = True
            return
        if mode == "no-responders":
            reply = b"NATS/1.0 503 No Responders\r\n\r\n"
            record["output"].extend(b"HMSG " + inbox + b" 1 " + str(len(reply)).encode() + b" " + str(len(reply)).encode() + b"\r\n" + reply + b"\r\n")
            return
        reply = b"{malformed" if mode == "malformed-ack" else encode({"stream": "WRONG" if mode == "wrong-stream" else "LSF_DEV",
            "seq": self.received, "duplicate": mode == "duplicate"})
        record["output"].extend(b"MSG " + inbox + b" 1 " + str(len(reply)).encode() + b"\r\n" + reply + b"\r\n")
        if mode in {"ack", "duplicate"}:
            record["acknowledgementsPending"] = record.get("acknowledgementsPending", 0) + 1
