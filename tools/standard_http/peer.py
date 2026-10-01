"""A selector-owned peer with bounded concurrent, explicitly gated scenarios."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import selectors
import socket
import time
import uuid
from dataclasses import dataclass, field

from .protocol import FixtureError, Request, require
from .vectors import BY_PATH, PROFILE, Vector, response

MAX_CONNECTIONS = 4
MAX_CONTACTS = 32
MAX_EVENTS = 512
MAX_RECEIVED = 2 * 1024 * 1024
MAX_SECONDS = 300
READ_WINDOW = 4096


@dataclass(frozen=True)
class Gate:
    generation: str
    request: int
    phase: str


@dataclass
class Connection:
    identity: int
    role: str
    deadline: float
    parser: Request = field(default_factory=Request)
    vector: Vector | None = None
    registered: bool = True
    phase: str = "receiving"
    output: bytes = b""
    suffix: bytes = b""
    offset: int = 0
    gate: Gate | None = None
    observation: dict = field(default_factory=dict)


class Peer:
    """No worker thread, sleeps, replay or application transport injection.

    A supervisor can pass its selector and call event()/tick(). Without one,
    poll() drives this peer's private selector. Gates are generation-bound and
    released once. All connections and queued bytes remain owned until close.
    Observed remote FIN is not a proof that a provider's physical owner retired.
    """

    def __init__(self, authorization: bytes, *, selector=None, maximum_seconds=60,
                 clock=time.monotonic):
        require(isinstance(authorization, bytes)
                and re.fullmatch(rb"Bearer [a-f0-9]{64}", authorization),
                "private-fixture-credential-required")
        require(type(maximum_seconds) is int and 1 <= maximum_seconds <= MAX_SECONDS,
                "fixture-lifetime-bound")
        self._authorization = authorization
        self.clock = clock
        self.deadline = clock() + maximum_seconds
        self.generation = uuid.uuid4().hex
        self.selector_owned = selector is None
        self.selector = selectors.DefaultSelector() if selector is None else selector
        self.listeners: dict[socket.socket, str] = {}
        self.clients: dict[socket.socket, Connection] = {}
        self.ports = {}
        self.rows: list[dict] = []
        self.events: list[dict] = []
        self.accepted = self.started = self.completed = self.mutations = 0
        self.rejected = self.bound_rejections = self.received = 0
        self.failure = None
        self.closed = False
        try:
            for role in ("primary", "secondary"):
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    if os.name == "posix":
                        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    else:
                        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    listener.bind(("127.0.0.1", 0))
                    listener.listen(MAX_CONNECTIONS)
                    listener.setblocking(False)
                    self.selector.register(listener, selectors.EVENT_READ, (self, "listener"))
                except BaseException:
                    listener.close()
                    raise
                self.listeners[listener] = role
                self.ports[role] = listener.getsockname()[1]
        except OSError:
            self.close()
            raise FixtureError("fixture-listener-unavailable") from None
        except BaseException:
            self.close()
            raise

    def origin(self, role="primary") -> dict:
        require(role in self.ports, "fixture-role")
        return {"scheme": "http", "host": "127.0.0.1", "port": self.ports[role]}

    def url(self, identity: str) -> str:
        from .vectors import BY_ID

        require(identity in BY_ID, "fixture-vector")
        value = BY_ID[identity]
        return f"http://127.0.0.1:{self.ports[value.role]}" + value.path.decode("ascii")

    def provider_destinations(self) -> list[dict]:
        """Installation inputs only; callers separately grant exact HTTP resources.

        No limits, stream grants, redirect allowance or credentials are invented.
        Install the primary credential through the maintained private store. The
        secondary destination has none. Named reference APIs decide whether a
        second independently authorized redirect call is supported.
        """
        return [{"origin": self.origin(role),
                 "addresses": {"networks": ["127.0.0.1/32"], "specialAddresses": ["127.0.0.1"]},
                 "resolution": {"kind": "static", "addresses": ["127.0.0.1"]},
                 "allowedRequestHeaders": ["accept", "user-agent", "x-conformance"], "redirectDestinations": []}
                for role in ("primary", "secondary")]

    def _event(self, kind: str, connection: Connection | None = None, **fields) -> None:
        if len(self.events) == MAX_EVENTS:
            self.failure = "fixture-observation-limit"
            return
        item = {"sequence": len(self.events) + 1, "kind": kind, **fields}
        if connection is not None:
            item["request"] = connection.identity
        self.events.append(item)

    def observation(self) -> dict:
        return {"schemaVersion": PROFILE, "kind": "controlled-peer-observation",
                "evidenceScope": "peer-protocol-only", "generation": self.generation,
                "state": "stopped" if self.closed else "ready", "failure": self.failure,
                "origins": {role: self.origin(role) for role in self.ports},
                "limits": {"connections": MAX_CONNECTIONS, "contacts": MAX_CONTACTS,
                           "events": MAX_EVENTS, "receivedBytes": MAX_RECEIVED,
                           "maximumSeconds": MAX_SECONDS},
                "acceptedConnections": self.accepted, "startedRequests": self.started,
                "listeningOrigins": len(self.listeners),
                "completedResponseWrites": self.completed, "committedMutations": self.mutations,
                "rejectedRequests": self.rejected, "connectionBoundRejections": self.bound_rejections,
                "openConnections": len(self.clients), "receivedBytes": self.received,
                "requests": [dict(row) for row in self.rows],
                "events": [dict(event) for event in self.events]}

    def gates(self) -> tuple[Gate, ...]:
        return tuple(record.gate for record in self.clients.values() if record.gate is not None)

    def release(self, gate: Gate) -> None:
        require(type(gate) is Gate and gate.generation == self.generation and not self.closed,
                "fixture-stale-or-foreign-gate")
        selected = [(stream, value) for stream, value in self.clients.items() if value.gate == gate]
        require(len(selected) == 1, "fixture-gate-not-pending")
        stream, record = selected[0]
        record.gate = None
        self._event("gate-released", record, phase=gate.phase)
        if gate.phase == "upload":
            try:
                record.phase = "receiving"
                record.parser.consume()
                self._set_events(stream, record, selectors.EVENT_READ)
                if record.parser.complete:
                    self._complete_request(stream, record)
            except (FixtureError, OSError):
                self._event("request-rejected", record, reason="released-upload-invalid")
                self.rejected += 1
                self._close_client(stream, record, "released-upload-invalid")
                raise FixtureError("released-upload-invalid") from None
        else:
            if gate.phase == "body":
                record.output, record.suffix, record.offset = record.suffix, b"", 0
            record.phase = "sending"
            self._set_events(stream, record, selectors.EVENT_READ | selectors.EVENT_WRITE)

    def owns(self, key) -> bool:
        return isinstance(key.data, tuple) and len(key.data) == 2 and key.data[0] is self

    def poll(self, timeout=0) -> int:
        require(self.selector_owned, "fixture-shared-selector-must-use-event")
        require(isinstance(timeout, (int, float)) and not isinstance(timeout, bool)
                and 0 <= timeout <= 1, "fixture-poll-timeout")
        self.tick()
        if self.closed or not self.selector.get_map():
            return 0
        ready = self.selector.select(min(timeout, max(0, self.deadline - self.clock())))
        for key, mask in ready:
            self.event(key, mask)
        self.tick()
        return len(ready)

    def tick(self) -> None:
        if self.closed:
            return
        now = self.clock()
        if now >= self.deadline or self.failure is not None:
            self.failure = self.failure or "fixture-lifetime-exhausted"
            self.close()
            return
        for stream, record in list(self.clients.items()):
            if now >= record.deadline:
                self._event("peer-request-deadline", record)
                self._close_client(stream, record, "peer-request-deadline")

    def event(self, key, mask) -> None:
        require(self.owns(key), "fixture-foreign-selector-event")
        if self.closed:
            return
        stream = key.fileobj
        if stream in self.listeners:
            self._accept(stream)
            return
        record = self.clients.get(stream)
        if record is None:  # A previous ready event may have closed it.
            return
        try:
            if mask & selectors.EVENT_READ:
                raw = stream.recv(READ_WINDOW)
                if not raw:
                    self._event("remote-write-half-ended", record)
                    self._close_client(stream, record, "remote-write-half-ended")
                    return
                self.received += len(raw)
                require(self.received <= MAX_RECEIVED, "fixture-received-byte-limit")
                require(record.phase == "receiving", "request-additional-bytes")
                record.parser.feed(raw, consume_body=False)
                if record.parser.headers_ready and record.vector is None:
                    self._start_request(stream, record)
                    if record.phase == "held-upload":
                        return
                if record.parser.headers_ready:
                    record.parser.consume()
                if record.parser.complete:
                    self._complete_request(stream, record)
            if stream in self.clients and mask & selectors.EVENT_WRITE:
                self._write(stream, record)
        except BlockingIOError:
            return
        except FixtureError as error:
            self.rejected += 1
            self._event("request-rejected", record, reason=error.code)
            self._close_client(stream, record, error.code)
            if error.code == "fixture-received-byte-limit":
                self.failure = error.code
                self.close()
        except OSError:
            self._event("connection-lost", record)
            self._close_client(stream, record, "connection-lost")

    def _accept(self, listener) -> None:
        try:
            stream, _ = listener.accept()
        except BlockingIOError:
            return
        except OSError:
            self.failure = "fixture-accept-failed"
            self.close()
            return
        self.accepted += 1
        role = self.listeners[listener]
        record = Connection(self.accepted, role, min(self.deadline, self.clock() + 30))
        record.observation = {"request": record.identity, "role": role, "state": "accepted",
                              "responseBytesWritten": 0}
        self.rows.append(record.observation)
        self._event("connection-accepted", record, role=role)
        if len(self.clients) == MAX_CONNECTIONS:
            self.bound_rejections += 1
            record.observation.update(state="closed", closeReason="fixture-connection-bound")
            self._event("peer-connection-closed", record, reason="fixture-connection-bound")
            stream.close()
        else:
            try:
                # Bounded peer buffers are observed separately from host/provider
                # accounting; no peer socket value can prove a host refund.
                stream.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
                stream.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
                receive = stream.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
                send = stream.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
                require(0 < receive <= 128 * 1024 and 0 < send <= 128 * 1024,
                        "fixture-kernel-buffer-bound")
                record.observation.update(receiveBufferBytes=receive, sendBufferBytes=send)
                stream.setblocking(False)
                self.selector.register(stream, selectors.EVENT_READ, (self, "connection"))
                self.clients[stream] = record
            except (OSError, FixtureError):
                stream.close()
                record.observation.update(state="closed", closeReason="fixture-socket-setup-failed")
                self.failure = "fixture-socket-setup-failed"
                self.close()
                return
        if self.accepted == MAX_CONTACTS:
            self._close_listeners()

    def _start_request(self, stream, record: Connection) -> None:
        request = record.parser
        require(request.headers[b"host"] == f"127.0.0.1:{self.ports[record.role]}".encode(),
                "request-origin")
        credential_bits = {"authorizationPresent": b"authorization" in request.headers,
                           "cookiePresent": b"cookie" in request.headers,
                           "proxyAuthorizationPresent": b"proxy-authorization" in request.headers}
        record.observation.update(credential_bits)
        if record.role == "primary":
            require(hmac.compare_digest(request.headers.get(b"authorization", b""), self._authorization),
                    "request-unauthenticated")
        else:
            require(not any(credential_bits.values()), "redirect-credential-forwarded")
        vector = BY_PATH.get((record.role, request.path))
        require(vector is not None and request.method in vector.methods, "request-vector-or-method")
        record.vector = vector
        self.started += 1
        record.observation.update(vector=vector.identity, method=request.method.decode("ascii"),
                                  state="request-started", requestFraming="chunked" if request.chunked else "length")
        self._event("request-started", record, vector=vector.identity)
        if vector.gate == "upload":
            record.phase = "held-upload"
            self.selector.unregister(stream)
            record.registered = False
            self._gate(record, "upload")

    def _complete_request(self, stream, record: Connection) -> None:
        record.observation.update(state="request-complete", bodyBytes=len(record.parser.body),
                                  bodySha256="sha256:" + hashlib.sha256(record.parser.body).hexdigest())
        self._event("request-complete", record, bodyBytes=len(record.parser.body))
        if record.vector.mutation:
            self.mutations += 1
            record.observation["mutationCommitted"] = True
            self._event("mutation-committed", record, total=self.mutations)
        if record.vector.identity == "commit-close":
            self._close_client(stream, record, "response-withheld-after-commit")
            return
        record.output, record.suffix = response(record.vector, record.parser, self.ports["secondary"])
        if record.vector.gate == "headers":
            record.phase = "held-headers"
            self._gate(record, "headers")
            self._set_events(stream, record, selectors.EVENT_READ)
        else:
            record.phase = "sending-prefix" if record.suffix else "sending"
            self._set_events(stream, record, selectors.EVENT_READ | selectors.EVENT_WRITE)

    def _gate(self, record: Connection, phase: str) -> None:
        record.gate = Gate(self.generation, record.identity, phase)
        record.observation["state"] = "held-" + phase
        self._event("gate-pending", record, phase=phase)

    def _set_events(self, stream, record: Connection, events: int) -> None:
        if record.registered:
            self.selector.modify(stream, events, (self, "connection"))
        else:
            self.selector.register(stream, events, (self, "connection"))
            record.registered = True

    def _write(self, stream, record: Connection) -> None:
        require(record.phase in {"sending", "sending-prefix"}, "fixture-write-state")
        sent = stream.send(record.output[record.offset:record.offset + READ_WINDOW])
        require(sent > 0, "fixture-write-no-progress")
        record.offset += sent
        record.observation["responseBytesWritten"] += sent
        if record.offset != len(record.output):
            return
        if record.phase == "sending-prefix":
            record.output, record.offset = b"", 0
            record.phase = "held-body"
            self._gate(record, "body")
            self._set_events(stream, record, selectors.EVENT_READ)
        else:
            self.completed += 1
            self._event("response-write-complete", record)
            self._close_client(stream, record, "response-write-complete")

    def _close_client(self, stream, record: Connection, reason: str) -> None:
        if stream not in self.clients:
            return
        if record.registered:
            self.selector.unregister(stream)
            record.registered = False
        del self.clients[stream]
        stream.close()
        record.observation.update(state="closed", closeReason=reason)
        self._event("peer-connection-closed", record, reason=reason)

    def _close_listeners(self) -> None:
        for listener in list(self.listeners):
            self.selector.unregister(listener)
            listener.close()
            del self.listeners[listener]

    def close(self) -> dict:
        if not self.closed:
            for stream, record in list(self.clients.items()):
                self._close_client(stream, record, "peer-stop")
            self._close_listeners()
            if self.selector_owned:
                self.selector.close()
            self.closed = True
            self._authorization = b""
        return self.observation()
