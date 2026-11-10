"""Gated faults for the maintained loopback SMTP peer, not a network adapter.

The controller owns the selector and every descriptor. A gate witnesses only
peer state: it never claims that a guest read is pending, a Store is destroyed,
or provider/kernel memory is retired. No worker, service or retry is started.
"""
from __future__ import annotations

import selectors
import socket
import struct
import time

from tools.outbound_stream_fixture import MAX_ATTEMPTS, SmtpPeer

SCENARIOS = frozenset(("greeting", "mutation", "oversized-greeting", "unterminated-greeting"))
MAX_RESPONSE_BYTES = 32768
RESPONSE_WINDOW = 1024
MAX_EVENTS = MAX_ATTEMPTS * 8
GREETING = b"220 loopback.invalid SMTP\r\n"
MUTATION_REPLY = b"250 accepted\r\n"


class GatedSmtpPeer(SmtpPeer):
    """Hold greeting/commit replies or stream one finite hostile response.

    Use ``observation()['barriers']`` to obtain an attempt/sequence pair and
    release precisely that barrier. Gates do not extend the inherited original
    idle/absolute deadlines. Timeout remains a failure even after local close.
    """

    def __init__(self, selector, *, scenario="mutation", port=0, fragment_bytes=7):
        if type(scenario) is not str or scenario not in SCENARIOS:
            raise ValueError("invalid-outbound-adversarial-scenario")
        self.scenario = scenario
        self.events = []
        self.failure = None
        self.releases = self.descriptor_closures = self.half_closes = self.resets = 0
        super().__init__(selector, port=port, fragment_bytes=fragment_bytes)

    def _record(self, attempt, kind):
        if len(self.events) >= MAX_EVENTS:
            self.failure = self.failure or "peer-event-bound"
            return None
        sequence = len(self.events) + 1
        self.events.append({"sequence": sequence, "attempt": attempt,
                            "kind": kind, "monotonicNs": time.monotonic_ns()})
        return sequence

    def _hold(self, record, kind):
        sequence = self._record(record["attempt"], kind + "-held")
        record["barrier"] = {"attempt": record["attempt"], "sequence": sequence, "kind": kind}

    def _interest(self, stream, record):
        # EOF closes only the client's send half. Keep the original descriptor
        # and capacity while a reply or explicit gate still owns the write half.
        events = 0 if record.get("readEof") else selectors.EVENT_READ
        if record["output"]:
            events |= selectors.EVENT_WRITE
        if not events:
            if not record.get("barrier") and not record.get("hostileActive"):
                self._close_client(stream)
            else:
                # EOF is permanently readable. No queued output means neither
                # read nor write interest: park without a busy readiness loop.
                try:
                    self.selector.unregister(stream)
                except KeyError:
                    pass
            return
        try:
            self.selector.modify(stream, events, self)
        except KeyError:
            self.selector.register(stream, events, self)

    def _read_eof(self, stream, record):
        record["readEof"] = True
        self._record(record["attempt"], "client-send-eof")
        if record["data"] or record["input"]:
            # An incomplete command/DATA terminator is not a mutation. Do not
            # synthesize a successful protocol response for truncated input.
            self._close_client(stream)
            return
        self._interest(stream, record)

    def _fill_hostile(self, stream, record):
        # Generate at most one bounded window; never allocate the whole hostile
        # line, and never mistake writable readiness for bytes actually sent.
        if record["output"] or not record.get("hostileRemaining", 0):
            return
        remaining = record["hostileRemaining"]
        amount = min(RESPONSE_WINDOW, remaining)
        chunk = bytearray(b"x" * amount)
        if remaining == MAX_RESPONSE_BYTES:
            chunk[:4] = b"220 "
        if remaining == amount and self.scenario == "oversized-greeting":
            chunk[-2:] = b"\r\n"
        record["hostileRemaining"] -= amount
        record["output"].extend(chunk)
        self._interest(stream, record)

    def event(self, key, events):
        # A ready selector key can outlive its deadline. Check before accept,
        # recv (which renews idle time), parsing DATA or sending queued replies.
        # Keys retired by this check are harmless stale events in SmtpPeer.
        self.check()
        accepting = key.fileobj is self.listener
        before = set(self.clients) if accepting else set()
        record = self.clients.get(key.fileobj)
        if record is not None and record.get("readEof"):
            # Selector snapshots can contain the old read interest after EOF
            # or a now-parked key. Never read/recount EOF or rearm that interest.
            events &= selectors.EVENT_WRITE if record["output"] else 0
            if not events:
                return
        try:
            super().event(key, events)
        except BlockingIOError:
            return
        if accepting:
            for stream in self.clients.keys() - before:
                record = self.clients[stream]
                record["barrier"] = None
                record["writeClosed"] = False
                self._record(record["attempt"], "connected")
                if self.scenario == "greeting":
                    record["output"].clear()
                    self._hold(record, "greeting")
                elif self.scenario in ("oversized-greeting", "unterminated-greeting"):
                    record["output"].clear()
                    record["hostileRemaining"] = MAX_RESPONSE_BYTES
                    record["hostileActive"] = True
                    self._fill_hostile(stream, record)
                self._interest(stream, record)
            return
        stream = key.fileobj
        record = self.clients.get(stream)
        if record is None:
            return
        self._fill_hostile(stream, record)
        if record.get("hostileActive") and not record["output"] and not record["hostileRemaining"]:
            record["hostileActive"] = False
            self._record(record["attempt"], "hostile-response-sent")
            if self.scenario == "unterminated-greeting":
                self._hold(record, "unterminated")
        self._interest(stream, record)

    def _line(self, stream, record, line):
        if record.get("barrier") or record.get("writeClosed") or record.get("hostileActive"):
            raise ValueError("outbound-peer-command-before-gate-release")
        if self.scenario == "mutation" and record["data"] and line == b".":
            # The existing parser has already bounded and hashed DATA, including
            # dot unstuffing. Committing is independent of sending the reply.
            self.mutations.append({"attempt": record["attempt"], "bytes": record["bytes"],
                                   "sha256": record["hash"].hexdigest(),
                                   "recipients": record["recipients"]})
            record["data"] = False
            record["committed"] = True
            self._record(record["attempt"], "mutation-committed")
            self._hold(record, "mutation")
            return
        super()._line(stream, record, line)

    def release(self, attempt, sequence, action):
        """Release one original peer barrier, never an application retry.

        ``reply`` sends the ordinary withheld SMTP reply; ``terminate`` finishes
        an unterminated greeting. ``half-close`` keeps the real read descriptor
        owned; ``reset`` and ``close`` retire only this peer's descriptor.
        """
        if (type(attempt) is not int or type(sequence) is not int
                or not 1 <= attempt <= MAX_ATTEMPTS or not 1 <= sequence <= MAX_EVENTS
                or type(action) is not str
                or action not in ("reply", "terminate", "half-close", "reset", "close")):
            raise ValueError("invalid-outbound-peer-release")
        selected = [(stream, record) for stream, record in self.clients.items()
                    if record["attempt"] == attempt]
        if len(selected) != 1:
            raise ValueError("stale-outbound-peer-barrier")
        stream, record = selected[0]
        barrier = record.get("barrier")
        if not barrier or barrier["sequence"] != sequence or self.failure:
            raise ValueError("stale-outbound-peer-barrier")
        now = time.monotonic()
        if now >= min(record["idle"], record["absolute"], self.deadline):
            # A controller release cannot race ahead of its next check() and
            # resurrect work after the original connection deadline.
            self.check(now)
            raise ValueError("expired-outbound-peer-barrier")
        if record["output"]:
            raise ValueError("outbound-peer-prior-replies-not-drained")
        if ((action == "reply" and barrier["kind"] not in ("greeting", "mutation"))
                or (action == "terminate" and barrier["kind"] != "unterminated")):
            raise ValueError("outbound-peer-release-kind-mismatch")
        # A release succeeds only after its original write/read interest is
        # usable. In particular, re-registering a parked EOF owner can fail.
        try:
            if action == "reset":
                stream.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            elif action == "half-close":
                stream.shutdown(socket.SHUT_WR)
                record["writeClosed"] = True
                # This syscall is irreversible even if the following selector
                # update fails. Count it separately from a successful release.
                self.half_closes += 1
            elif action in ("reply", "terminate"):
                reply = b"\r\n" if action == "terminate" else (
                    GREETING if barrier["kind"] == "greeting" else MUTATION_REPLY)
                self._reply(record, reply)
                if barrier["kind"] == "mutation":
                    record["mutation_reply_end"] = len(record["output"])
            if action not in ("reset", "close"):
                record["barrier"] = None
                self._interest(stream, record)
        except (OSError, ValueError):
            self.failure = self.failure or "peer-control-failed"
            self._close_client(stream)
            raise
        record["barrier"] = None
        self.releases += 1
        self._record(attempt, "released-" + action)
        if action in ("reset", "close"):
            self.resets += int(action == "reset")
            self._close_client(stream)

    def _close_client(self, stream):
        record = self.clients.get(stream)
        if record is not None:
            attempt = record["attempt"]
            # Record only after the original close completed, not on request.
            super()._close_client(stream)
            self.descriptor_closures += 1
            self._record(attempt, "peer-descriptor-closed")
        else:
            super()._close_client(stream)

    def check(self, now=None):
        now = time.monotonic() if now is None else now
        expired = [record["attempt"] for record in self.clients.values()
                   if now >= min(record["idle"], record["absolute"], self.deadline)]
        if expired or now >= self.deadline and self.listener is not None:
            self.failure = self.failure or "peer-watchdog-expired"
            for attempt in expired:
                self._record(attempt, "watchdog-expired")
        super().check(now)

    def observation(self):
        barriers = [{**record["barrier"], "priorReplyBytes": len(record["output"])}
                    for record in self.clients.values() if record.get("barrier")]
        return {**super().observation(),
                "schemaVersion": "latent.outbound-stream-peer.v1", "scenario": self.scenario,
                "barriers": sorted(barriers, key=lambda row: row["attempt"]),
                "events": [dict(row) for row in self.events], "failure": self.failure,
                "releasedBarriers": self.releases, "peerDescriptorClosures": self.descriptor_closures,
                "peerSendHalfCloses": self.half_closes, "peerResets": self.resets,
                "maximumResponseBytes": MAX_RESPONSE_BYTES, "responseWindowBytes": RESPONSE_WINDOW,
                "guestReadPendingObserved": False, "providerRetirementObserved": False,
                "kernelFinalFreeObserved": False}
