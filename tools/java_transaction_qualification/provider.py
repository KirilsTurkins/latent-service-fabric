"""Disposable bounded recipient for the existing native put-once wire contract.

This is an external synthetic recipient, never another LSF state owner or a
grant. Its accepted-record receipt is distinct from LSF commitment and delivery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import time

from .inputs import decode, require
from tools.rust_capsule_project import read_file

CONTRACT = "latent.http-effect.put-once.v1"
PREFIX = "/latent-effects/v1/"
PAYLOAD = b"java-aggregate-put-once-v1\0"
MODES = {"reply", "accept-disconnect", "accept-ambiguous", "reserve-once", "hold-status"}
FIELDS = {"contract", "effect", "bodySha256", "providerIncarnation", "retainUntilUnixMillis", "state", "receipt"}
HEX = re.compile(r"[0-9a-f]{64}")
STOPPING = False


def private_write(path: Path, raw: bytes):
    require(len(raw) <= 8192 and not path.exists(), "recipient-exclusive-record")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def mode(root: Path) -> str:
    path = root / "mode"
    if not path.exists():
        return "reply"
    require(path.is_file() and not path.is_symlink(), "recipient-mode-file")
    raw = read_file(path, 64)
    require(raw in {item.encode() for item in MODES}, "closed-recipient-mode")
    return raw.decode()


def request(connection, deadline: float):
    buffer = bytearray()
    while b"\r\n\r\n" not in buffer:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "recipient-original-deadline")
        connection.settimeout(min(2, remaining))
        chunk = connection.recv(min(1024, 8193 - len(buffer)))
        require(chunk and len(chunk) <= 8192 - len(buffer), "recipient-header-bound")
        buffer.extend(chunk)
    head, body = bytes(buffer).split(b"\r\n\r\n", 1)
    lines = head.decode("ascii").split("\r\n")
    require(len(lines) <= 17, "recipient-field-count")
    method, path, version = lines[0].split(" ")
    require(method in {"PUT", "GET"} and version == "HTTP/1.1", "recipient-wire-method")
    headers = {}
    for line in lines[1:]:
        name, value = line.split(":", 1)
        name = name.lower()
        require(name not in headers, "recipient-duplicate-field")
        headers[name] = value.strip()
    require("transfer-encoding" not in headers, "recipient-framing")
    length = headers.get("content-length", "0")
    require(re.fullmatch(r"0|[1-9][0-9]{0,3}", length) and int(length) <= 4096
            and len(body) <= int(length), "recipient-body-bound")
    while len(body) < int(length):
        remaining = deadline - time.monotonic()
        require(remaining > 0, "recipient-original-deadline")
        connection.settimeout(min(2, remaining))
        chunk = connection.recv(int(length) - len(body))
        require(chunk, "recipient-truncated-body")
        body += chunk
    return method, path, headers, body


def retained_record(path: Path, incarnation: str, effect: str):
    require(path.is_file() and not path.is_symlink(), "recipient-retained-file")
    row = decode(read_file(path, 2048), 2048)
    require(isinstance(row, dict) and set(row) == FIELDS, "recipient-retained-format")
    require(row["contract"] == CONTRACT and row["effect"] == effect
            and row["providerIncarnation"] == incarnation
            and isinstance(row["bodySha256"], str) and HEX.fullmatch(row["bodySha256"])
            and isinstance(row["retainUntilUnixMillis"], str)
            and re.fullmatch(r"[1-9][0-9]{0,19}", row["retainUntilUnixMillis"])
            and int(row["retainUntilUnixMillis"]) <= 2**64 - 1,
            "recipient-retained-original-facts")
    receipt = row["receipt"]
    require((row["state"] == "reserved" and receipt is None)
            or (row["state"] == "applied" and isinstance(receipt, str) and HEX.fullmatch(receipt)),
            "recipient-retained-disposition")
    return row


class Recipient:
    def __init__(self, root: Path, incarnation: str, token: bytes):
        require(root.is_absolute() and root.is_dir() and not root.is_symlink(), "recipient-private-root")
        require(HEX.fullmatch(incarnation) and 0 < len(token) <= 256,
                "recipient-fixed-installation")
        if os.name == "posix":
            require(root.stat().st_mode & 0o077 == 0, "recipient-private-root-mode")
        self.root, self.incarnation, self.token = root, incarnation, token
        self.requests = self.puts = self.gets = self.accepted = self.applied = self.disconnected = self.replays = 0
        self.retained = self._inspect()

    def _inspect(self):
        bases, applied = {}, {}
        for count, path in enumerate(self.root.iterdir(), 1):
            require(count <= 69 and path.is_file() and not path.is_symlink(), "recipient-retained-directory-bound")
            name = path.name
            if name == "mode" or re.fullmatch(r"recipient-stopped-[1-3]\.json", name):
                require(path.stat().st_size <= 8192, "recipient-control-byte-bound")
                continue
            match = re.fullmatch(r"([0-9a-f]{64})(\.applied)?\.json", name)
            require(match is not None, "recipient-retained-path")
            row = retained_record(path, self.incarnation, match[1])
            (applied if match[2] else bases)[match[1]] = row
        require(len(bases) <= 32 and set(applied) <= set(bases), "recipient-retention-count")
        for effect, row in applied.items():
            base = bases[effect]
            require(base["state"] == "reserved" and row["state"] == "applied"
                    and all(base[key] == row[key] for key in FIELDS - {"state", "receipt"}),
                    "recipient-original-reservation-transition")
        return len(bases)

    def _load(self, effect):
        path = self.root / (effect + ".json")
        if not path.exists():
            require(not path.is_symlink(), "recipient-retained-file")
            return None
        row = retained_record(path, self.incarnation, effect)
        applied = self.root / (effect + ".applied.json")
        if applied.exists() or applied.is_symlink():
            completed = retained_record(applied, self.incarnation, effect)
            require(row["state"] == "reserved" and completed["state"] == "applied"
                    and all(row[key] == completed[key] for key in FIELDS - {"state", "receipt"}),
                    "recipient-original-reservation-transition")
            row = completed
        return row

    def handle(self, method: str, path: str, fields: dict, body: bytes):
        self.requests += 1
        require(self.requests <= 64, "recipient-request-count")
        if fields.get("authorization", "").encode() != b"Bearer " + self.token:
            return 401, None, False
        require(path.startswith(PREFIX), "recipient-fixed-wire-path")
        effect = path[len(PREFIX):]
        require(HEX.fullmatch(effect) and fields.get("idempotency-key") == effect,
                "recipient-original-effect-identity")
        expected = fields.get("x-lsf-effect-body-sha256", "")
        horizon = fields.get("x-lsf-effect-retain-until", "")
        require(fields.get("x-lsf-effect-contract") == CONTRACT
                and fields.get("x-lsf-effect-provider-incarnation") == self.incarnation
                and HEX.fullmatch(expected)
                and re.fullmatch(r"[1-9][0-9]{0,19}", horizon)
                and int(horizon) <= 2**64 - 1, "recipient-original-contract-facts")
        selected = mode(self.root)
        path = self.root / (effect + ".json")
        retained = self._load(effect)
        if retained is not None and (retained["bodySha256"] != expected
                                      or retained["providerIncarnation"] != self.incarnation
                                      or retained["retainUntilUnixMillis"] != horizon):
            return 409, None, False
        now = time.time_ns() // 1_000_000
        if int(horizon) <= now or int(horizon) > now + 600_000:
            return 410, None, False
        if method == "GET":
            self.gets += 1
            require(not body, "recipient-query-body")
            return (404, None, False) if retained is None else (200, retained, selected in {"hold-status", "accept-ambiguous"})
        self.puts += 1
        require(method == "PUT" and body == PAYLOAD and fields.get("content-type") == "application/octet-stream"
                and hashlib.sha256(body).hexdigest() == expected, "recipient-exact-original-payload")
        if retained is not None:
            self.replays += 1
            if retained["state"] == "reserved":
                completed = dict(retained, state="applied", receipt=os.urandom(32).hex())
                private_write(self.root / (effect + ".applied.json"), json.dumps(completed, separators=(",", ":")).encode())
                self.applied += 1
                return 201, completed, selected == "accept-ambiguous"
            return 200, retained, selected == "accept-ambiguous"
        require(self.retained < 32, "recipient-retention-count")
        retained = {"contract": CONTRACT, "effect": effect, "bodySha256": expected,
                    "providerIncarnation": self.incarnation, "retainUntilUnixMillis": horizon,
                    "state": "reserved" if selected == "reserve-once" else "applied", "receipt": None}
        if selected != "reserve-once":
            retained["receipt"] = os.urandom(32).hex()
        private_write(path, json.dumps(retained, separators=(",", ":")).encode())
        self.accepted += 1
        self.retained += 1
        self.applied += selected != "reserve-once"
        if selected in {"accept-disconnect", "accept-ambiguous"}:
            self.disconnected += 1
            return 201, retained, True
        return (202 if selected == "reserve-once" else 201), retained, False

    def observation(self):
        return {"schemaVersion": "latent.synthetic.put-once-recipient.v1", "requests": self.requests,
                "puts": self.puts, "gets": self.gets, "acceptedRecords": self.accepted,
                "appliedRecords": self.applied, "retainedRecords": self.retained,
                "duplicatePuts": self.replays, "disconnectedAfterAcceptance": self.disconnected,
                "providerIncarnation": self.incarnation, "recipientDeliveryQualified": False}


def _stop(_signum, _frame):
    global STOPPING
    STOPPING = True


def run(root: Path, tls: Path, token_file: Path, incarnation: str, deadline: float, session: int):
    require(0 < deadline - time.monotonic() <= 1200, "recipient-original-lifetime")
    require(session in {1, 2, 3}, "recipient-bounded-session")
    stopped = root / f"recipient-stopped-{session}.json"
    require(not stopped.exists(), "recipient-original-session")
    require(token_file.is_file() and not token_file.is_symlink(), "recipient-credential-file")
    peer = Recipient(root, incarnation, read_file(token_file, 256))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(tls / "server.pem", tls / "key.pem")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        print(json.dumps({"port": listener.getsockname()[1], "providerIncarnation": incarnation}), flush=True)
        connections = refused = 0
        while not STOPPING and time.monotonic() < deadline and peer.requests < 64 and connections < 96:
            listener.settimeout(min(0.2, deadline - time.monotonic()))
            try:
                accepted, _ = listener.accept()
            except TimeoutError:
                continue
            connections += 1
            with accepted:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                accepted.settimeout(min(2, remaining))
                try:
                    with context.wrap_socket(accepted, server_side=True) as connection:
                        status, record, disconnected = peer.handle(*request(connection, deadline))
                        if disconnected:
                            # Original recipient acceptance is already durable;
                            # the platform must use its actual uncertainty path.
                            continue
                        raw = b"" if record is None else json.dumps(record, separators=(",", ":")).encode()
                        require(len(raw) <= 1024, "recipient-native-receipt-ceiling")
                        remaining = deadline - time.monotonic()
                        require(remaining > 0, "recipient-original-deadline")
                        connection.settimeout(min(2, remaining))
                        head = f"HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode()
                        connection.sendall(head + raw)
                except (ValueError, OSError):
                    refused += 1
    record = peer.observation()
    record.update(connections=connections, refusedConnections=refused)
    private_write(stopped, json.dumps(record, separators=(",", ":")).encode())
    print(json.dumps(record), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--tls", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--incarnation", required=True)
    parser.add_argument("--deadline", type=float, required=True)
    parser.add_argument("--session", type=int, default=1)
    args = parser.parse_args()
    run(args.root, args.tls, args.token_file, args.incarnation, args.deadline, args.session)


if __name__ == "__main__":
    main()
