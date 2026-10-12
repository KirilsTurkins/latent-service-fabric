"""Finite synthetic recipient for the current native deferred POST/GET contract.

This external test recipient is distinct from the historical PUT fixture and
from platform commitment or recipient delivery. Records are never rewritten.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import time

from .inputs import decode, require
from .provider import private_write
from tools.rust_capsule_project import read_file

CONTRACT = "lsf-atomic-idempotent-http-v1"
OPERATION_PATH = "/effect"
LOOKUP_PREFIX = "/receipts/"
RETENTION_MILLIS = 600000
MAXIMUM_PAYLOAD_BYTES = 27
MAXIMUM_REQUESTS = 64
MAXIMUM_CONNECTIONS = 96
MAXIMUM_RECORDS = 32
MAXIMUM_REPLY_BYTES = 2048
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
KEY = re.compile(r"lsf-effect-[0-9a-f]{64}\Z")
MODES = {"reply", "accept-disconnect", "reject"}
OBSERVATION = "current-recipient-observation.json"
COUNTERS = {"requests", "posts", "gets", "profileProbes", "originalRecords", "retainedRecords",
            "mutations", "duplicatePosts", "lostRepliesAfterAcceptance"}
FIELDS = {"formatVersion", "endpointIncarnation", "idempotencyKey", "bodyDigest",
          "sequence", "createdAtMillis", "payloadBase64"}


def endpoint(origin: dict, incarnation: str) -> dict:
    require(set(origin) == {"scheme", "host", "port"} and origin["scheme"] == "https"
            and origin["host"] == "localhost" and type(origin["port"]) is int
            and 1 <= origin["port"] <= 65535 and DIGEST.fullmatch(incarnation),
            "current-recipient-fixed-endpoint")
    return {"formatVersion": 1, "origin": origin, "operationPath": OPERATION_PATH,
            "lookupPrefix": LOOKUP_PREFIX, "endpointIncarnation": incarnation,
            "retentionMillis": RETENTION_MILLIS, "mediaType": "application/octet-stream",
            "maximumPayloadBytes": MAXIMUM_PAYLOAD_BYTES}


def request(connection, deadline: float):
    buffer = bytearray()
    while b"\r\n\r\n" not in buffer:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "current-recipient-deadline")
        connection.settimeout(min(2, remaining))
        chunk = connection.recv(min(1024, 8193 - len(buffer)))
        require(chunk and len(chunk) <= 8192 - len(buffer), "current-recipient-header-bound")
        buffer.extend(chunk)
    head, body = bytes(buffer).split(b"\r\n\r\n", 1)
    lines = head.decode("ascii").split("\r\n")
    require(len(lines) <= 33, "current-recipient-header-count")
    method, path, version = lines[0].split(" ")
    require(method in {"POST", "GET"} and version == "HTTP/1.1", "current-recipient-method")
    headers = {}
    for line in lines[1:]:
        name, value = line.split(":", 1)
        name = name.lower()
        require(name and name not in headers, "current-recipient-duplicate-header")
        headers[name] = value.strip()
    require("transfer-encoding" not in headers, "current-recipient-framing")
    length = headers.get("content-length", "0")
    require(re.fullmatch(r"0|[1-9][0-9]{0,3}", length)
            and int(length) <= MAXIMUM_PAYLOAD_BYTES and len(body) <= int(length),
            "current-recipient-payload-bound")
    while len(body) < int(length):
        remaining = deadline - time.monotonic()
        require(remaining > 0, "current-recipient-deadline")
        connection.settimeout(min(2, remaining))
        chunk = connection.recv(int(length) - len(body))
        require(chunk, "current-recipient-truncated-body")
        body += chunk
    return method, path, headers, body


def response(status: int, record: dict, incarnation: str) -> bytes:
    raw = json.dumps(record, separators=(",", ":")).encode("utf-8")
    require(0 < len(raw) <= MAXIMUM_REPLY_BYTES, "current-recipient-reply-bound")
    head = (f"HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\n"
            f"Lsf-Endpoint-Contract: {CONTRACT}\r\n"
            f"Lsf-Endpoint-Incarnation: {incarnation}\r\n"
            f"Lsf-Idempotency-Retention-Millis: {RETENTION_MILLIS}\r\n"
            f"Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n")
    return head.encode("ascii") + raw


class Recipient:
    def __init__(self, root: Path, declaration: dict, credential: bytes):
        require(root.is_absolute() and root.is_dir() and not root.is_symlink(),
                "current-recipient-private-root")
        if os.name == "posix":
            require(root.stat().st_mode & 0o077 == 0, "current-recipient-private-root-mode")
        require(type(declaration.get("formatVersion")) is int
                and type(declaration.get("retentionMillis")) is int
                and type(declaration.get("maximumPayloadBytes")) is int
                and declaration == endpoint(declaration["origin"], declaration["endpointIncarnation"]),
                "current-recipient-original-declaration")
        require(0 < len(credential) <= 4096 and all(32 <= byte < 127 for byte in credential),
                "current-recipient-credential")
        self.root, self.declaration, self.credential = root, declaration, credential
        self.incarnation = declaration["endpointIncarnation"]
        retained_declaration = root / "current-endpoint.json"
        if retained_declaration.exists():
            require(retained_declaration.is_file() and not retained_declaration.is_symlink()
                    and decode(read_file(retained_declaration, 8192), 8192) == declaration,
                    "current-recipient-retained-endpoint")
        else:
            private_write(retained_declaration, json.dumps(declaration, separators=(",", ":")).encode())
        self.records = {}
        self.requests = self.posts = self.gets = self.probes = self.duplicates = self.lost = 0
        paths = []
        with os.scandir(root) as entries:
            for ordinal, entry in enumerate(entries):
                require(ordinal < MAXIMUM_RECORDS + 8, "current-recipient-directory-bound")
                name = entry.name
                require(name in {"current-endpoint.json", "recipient.lock", "mode", OBSERVATION,
                                 "current-recipient-observation.next",
                                 *(f"current-recipient-stopped-{n}.json" for n in range(1, 4))}
                        or (name.endswith(".json") and KEY.fullmatch(name[:-5])),
                        "current-recipient-directory-member")
                if name.startswith("lsf-effect-"):
                    paths.append(root / name)
        for path in sorted(paths):
            require(path.is_file() and not path.is_symlink(), "current-recipient-record-file")
            row = decode(read_file(path, 8192), 8192)
            require(set(row) == FIELDS and type(row["formatVersion"]) is int and row["formatVersion"] == 1
                    and row["endpointIncarnation"] == self.incarnation
                    and KEY.fullmatch(row["idempotencyKey"])
                    and path.name == row["idempotencyKey"] + ".json"
                    and DIGEST.fullmatch(row["bodyDigest"])
                    and type(row["sequence"]) is int and 1 <= row["sequence"] <= MAXIMUM_RECORDS
                    and type(row["createdAtMillis"]) is int and 0 < row["createdAtMillis"] < 2**64,
                    "current-recipient-record-identity")
            payload = base64.b64decode(row["payloadBase64"], validate=True)
            require(len(payload) <= MAXIMUM_PAYLOAD_BYTES
                    and hashlib.sha256(payload).hexdigest() == row["bodyDigest"],
                    "current-recipient-record-payload")
            self.records[row["idempotencyKey"]] = row
        require(len(self.records) <= MAXIMUM_RECORDS
                and {row["sequence"] for row in self.records.values()} == set(range(1, len(self.records) + 1)),
                "current-recipient-sequence-census")
        self.original_records = len(self.records)

    def receipt(self, key: str, digest: str, outcome: str, sequence=0, duplicate=False):
        return {"formatVersion": 1, "endpointIncarnation": self.incarnation,
                "idempotencyKey": key, "bodyDigest": digest, "outcome": outcome,
                "sequence": sequence, "duplicate": duplicate}

    def handle(self, method: str, path: str, headers: dict, body: bytes):
        self.requests += 1
        require(self.requests <= MAXIMUM_REQUESTS, "current-recipient-request-count")
        if not hmac.compare_digest(headers.get("authorization", "").encode(), self.credential):
            return 403, {}, False
        if (headers.get("lsf-endpoint-contract") != CONTRACT
                or headers.get("lsf-endpoint-incarnation") != self.incarnation
                or headers.get("lsf-idempotency-retention-millis") != str(RETENTION_MILLIS)):
            return 421, {}, False
        key, digest = headers.get("idempotency-key", ""), headers.get("lsf-body-sha256", "")
        if not KEY.fullmatch(key) or not DIGEST.fullmatch(digest):
            return 400, {}, False
        if method == "GET":
            self.gets += 1
            require(not body, "current-recipient-get-body")
            if path == OPERATION_PATH:
                self.probes += 1
                return 200, {"formatVersion": 1, "contract": CONTRACT,
                    "endpointIncarnation": self.incarnation, "retentionMillis": RETENTION_MILLIS,
                    "maximumPayloadBytes": MAXIMUM_PAYLOAD_BYTES}, False
            if path != LOOKUP_PREFIX + key:
                return 404, {}, False
        elif method == "POST":
            self.posts += 1
            if (path != OPERATION_PATH or len(body) > MAXIMUM_PAYLOAD_BYTES
                    or headers.get("content-type") != self.declaration["mediaType"]
                    or hashlib.sha256(body).hexdigest() != digest):
                return 400, {}, False
        else:
            return 405, {}, False
        retained = self.records.get(key)
        now = time.time_ns() // 1000000
        if retained is not None:
            if retained["bodyDigest"] != digest:
                return 409, self.receipt(key, retained["bodyDigest"], "conflict"), False
            if now >= retained["createdAtMillis"] + RETENTION_MILLIS:
                return 410, self.receipt(key, digest, "expired"), False
            self.duplicates += method == "POST"
            return 200, self.receipt(key, digest, "accepted", retained["sequence"], True), False
        if method == "GET":
            return 404, self.receipt(key, digest, "absent"), False
        selected = "reply"
        mode = self.root / "mode"
        if mode.exists():
            require(mode.is_file() and not mode.is_symlink(), "current-recipient-mode-file")
            selected = read_file(mode, 64).decode("ascii")
        require(selected in MODES, "current-recipient-mode")
        if selected == "reject":
            return 422, self.receipt(key, digest, "rejected"), False
        require(len(self.records) < MAXIMUM_RECORDS, "current-recipient-record-count")
        sequence = len(self.records) + 1
        row = {"formatVersion": 1, "endpointIncarnation": self.incarnation,
               "idempotencyKey": key, "bodyDigest": digest, "sequence": sequence,
               "createdAtMillis": now, "payloadBase64": base64.b64encode(body).decode("ascii")}
        private_write(self.root / (key + ".json"), json.dumps(row, separators=(",", ":")).encode())
        self.records[key] = row
        disconnected = selected == "accept-disconnect"
        self.lost += disconnected
        return 201, self.receipt(key, digest, "accepted", sequence), disconnected

    def observation(self):
        return {"schemaVersion": "latent.synthetic.current-post-recipient.v1",
                "endpointIncarnation": self.incarnation, "requests": self.requests,
                "posts": self.posts, "gets": self.gets, "profileProbes": self.probes,
                "originalRecords": self.original_records, "retainedRecords": len(self.records),
                "mutations": len(self.records),
                "duplicatePosts": self.duplicates, "lostRepliesAfterAcceptance": self.lost,
                "recipientDeliveryQualified": False}

    def publish_observation(self):
        observed = self.root / OBSERVATION
        if observed.exists():
            bounded_observation(decode(read_file(observed, 8192), 8192), self.incarnation)
        next_record = self.root / "current-recipient-observation.next"
        private_write(next_record, json.dumps(self.observation(), separators=(",", ":")).encode())
        os.replace(next_record, observed)


def bounded_observation(value: dict, incarnation: str) -> dict:
    require(isinstance(value, dict) and set(value) == COUNTERS | {
            "schemaVersion", "endpointIncarnation", "recipientDeliveryQualified"}
            and value["schemaVersion"] == "latent.synthetic.current-post-recipient.v1"
            and value["endpointIncarnation"] == incarnation
            and value["recipientDeliveryQualified"] is False
            and all(type(value[name]) is int and 0 <= value[name] <= MAXIMUM_REQUESTS for name in COUNTERS)
            and value["retainedRecords"] <= MAXIMUM_RECORDS
            and value["mutations"] == value["retainedRecords"]
            and value["originalRecords"] <= value["retainedRecords"]
            and value["gets"] + value["posts"] <= value["requests"]
            and value["profileProbes"] <= value["gets"]
            and value["duplicatePosts"] <= value["posts"]
            and value["lostRepliesAfterAcceptance"] <= value["mutations"],
            "current-recipient-bounded-observation")
    return value


def stopped_observation(value: dict, incarnation: str) -> dict:
    extra = {"connections", "refusedConnections", "activeConnections", "workerThreads", "listenerClosed"}
    require(isinstance(value, dict) and set(value) == COUNTERS | extra | {
            "schemaVersion", "endpointIncarnation", "recipientDeliveryQualified"},
            "current-recipient-stopped-fields")
    bounded_observation({name: data for name, data in value.items() if name not in extra}, incarnation)
    require(type(value["connections"]) is int and value["requests"] <= value["connections"] <= MAXIMUM_CONNECTIONS
            and type(value["refusedConnections"]) is int and 0 <= value["refusedConnections"] <= value["connections"]
            and type(value["activeConnections"]) is int and value["activeConnections"] == 0
            and type(value["workerThreads"]) is int and value["workerThreads"] == 0
            and value["listenerClosed"] is True, "current-recipient-physical-retirement")
    return value


def run(root: Path, tls: Path, declaration_path: Path, credential_path: Path, deadline: float, session: int):
    import fcntl
    require(0 < deadline - time.monotonic() <= 1200 and type(session) is int and 1 <= session <= 3,
            "current-recipient-finite-lifetime")
    declaration = decode(read_file(declaration_path, 8192), 8192)
    stopped = root / f"current-recipient-stopped-{session}.json"
    require(not stopped.exists() and not stopped.is_symlink(), "current-recipient-original-session")
    peer = Recipient(root, declaration, read_file(credential_path, 4096))
    stop = False
    def stopping(_signal, _frame):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(tls / "server.pem", tls / "key.pem")
    connections = refused = 0
    if session > 1:
        previous = stopped_observation(decode(read_file(root / f"current-recipient-stopped-{session - 1}.json", 8192), 8192),
                                       peer.incarnation)
        require(previous["retainedRecords"] == len(peer.records),
                "current-recipient-retired-original-session")
        limits = {"requests": MAXIMUM_REQUESTS, "posts": MAXIMUM_REQUESTS, "gets": MAXIMUM_REQUESTS,
                  "profileProbes": MAXIMUM_REQUESTS, "duplicatePosts": MAXIMUM_REQUESTS,
                  "lostRepliesAfterAcceptance": MAXIMUM_REQUESTS,
                  "connections": MAXIMUM_CONNECTIONS, "refusedConnections": MAXIMUM_CONNECTIONS}
        require(all(type(previous.get(name)) is int and 0 <= previous[name] <= maximum
                    for name, maximum in limits.items()), "current-recipient-cumulative-bounds")
        peer.requests, peer.posts, peer.gets = (previous[name] for name in ("requests", "posts", "gets"))
        peer.probes, peer.duplicates, peer.lost = (previous[name] for name in
            ("profileProbes", "duplicatePosts", "lostRepliesAfterAcceptance"))
        connections, refused = previous["connections"], previous["refusedConnections"]
    lock = root / "recipient.lock"
    with lock.open("a+b") as held, socket.socket() as listener:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        peer.publish_observation()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", declaration["origin"]["port"]))
        listener.listen(4)
        print(json.dumps({"schemaVersion": "latent.synthetic.current-post-recipient-started.v1",
            "port": listener.getsockname()[1], "endpointIncarnation": peer.incarnation}), flush=True)
        while not stop and time.monotonic() < deadline and peer.requests < MAXIMUM_REQUESTS and connections < MAXIMUM_CONNECTIONS:
            listener.settimeout(min(.2, deadline - time.monotonic()))
            try:
                accepted, _address = listener.accept()
            except TimeoutError:
                continue
            connections += 1
            with accepted:
                accepted.settimeout(min(2, max(.001, deadline - time.monotonic())))
                try:
                    with context.wrap_socket(accepted, server_side=True) as connection:
                        try:
                            status, body, disconnected = peer.handle(*request(connection, deadline))
                        finally:
                            peer.publish_observation()
                        if not disconnected:
                            connection.sendall(response(status, body, peer.incarnation))
                except (ValueError, OSError):
                    refused += 1
    observation = peer.observation()
    observation.update(connections=connections, refusedConnections=refused,
                       activeConnections=0, workerThreads=0, listenerClosed=True)
    stopped_observation(observation, peer.incarnation)
    private_write(stopped, json.dumps(observation, separators=(",", ":")).encode())
    print(json.dumps(observation), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "tls", "declaration", "credential-file"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--deadline", type=float, required=True)
    parser.add_argument("--session", type=int, default=1)
    args = parser.parse_args()
    run(args.root, args.tls, args.declaration, args.credential_file, args.deadline, args.session)


if __name__ == "__main__":
    main()
