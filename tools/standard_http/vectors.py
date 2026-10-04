"""Fixed scenarios selected by operation, never by a dependency's identity."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
from dataclasses import dataclass

from .protocol import FixtureError

PROFILE = "latent.standard-http.conformance.v1"
DOMAIN = {"id": 7, "name": "caf\u00e9", "items": ["first", "\u03bb"], "empty": ""}
PARTIAL = b"first-second-" + b"x" * 4096
MAX_RESPONSE = 64 * 1024


@dataclass(frozen=True)
class Vector:
    identity: str
    path: bytes
    methods: frozenset[bytes]
    role: str = "primary"
    gate: str | None = None
    mutation: bool = False


GET = frozenset({b"GET", b"HEAD"})
POST = frozenset({b"POST"})
VECTORS = (
    Vector("domain-json", b"/conformance/json", GET),
    Vector("http-404", b"/conformance/status/404", GET),
    Vector("http-500", b"/conformance/status/500", GET),
    Vector("method-bytes", b"/conformance/echo",
           frozenset({b"GET", b"HEAD", b"POST", b"PUT", b"PATCH", b"DELETE", b"OPTIONS"})),
    Vector("pending-headers", b"/conformance/hold/headers", GET, gate="headers"),
    Vector("partial-body", b"/conformance/body/partial", GET, gate="body"),
    Vector("pending-upload", b"/conformance/hold/upload", POST, gate="upload"),
    Vector("truncated-body", b"/conformance/body/truncated", GET),
    Vector("malformed-framing", b"/conformance/body/malformed", GET),
    Vector("malformed-json", b"/conformance/body/malformed-json", GET),
    Vector("oversized-body", b"/conformance/body/oversized", GET),
    Vector("gzip-json", b"/conformance/body/gzip", GET),
    Vector("redirect", b"/conformance/redirect", GET),
    Vector("redirect-target", b"/conformance/redirect-target", GET, role="secondary"),
    Vector("redirect-denied", b"/conformance/redirect-denied", GET),
    Vector("denied-target", b"/conformance/denied-target", GET, role="secondary"),
    Vector("commit-pending", b"/conformance/mutation/pending", POST,
           gate="headers", mutation=True),
    Vector("commit-close", b"/conformance/mutation/close", POST, mutation=True),
)
BY_PATH = {(value.role, value.path): value for value in VECTORS}
BY_ID = {value.identity: value for value in VECTORS}


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def head(status: int, length: int, *, headers: tuple[tuple[bytes, bytes], ...] = ()) -> bytes:
    raw = (f"HTTP/1.1 {status} Fixture\r\nContent-Length: {length}\r\n"
           "Connection: close\r\n").encode("ascii")
    return raw + b"".join(name + b": " + value + b"\r\n" for name, value in headers) + b"\r\n"


def response(vector: Vector, request, secondary_port: int) -> tuple[bytes, bytes]:
    """Return a prefix and optional gated suffix; never retry a request."""
    status = 200
    body = json_bytes(DOMAIN)
    fields = ((b"Content-Type", b"application/json; charset=utf-8"),)
    declared = None
    if vector.identity in {"http-404", "http-500"}:
        status = int(vector.identity[-3:])
        body = json_bytes({"status": status, "message": "domain-error"})
    elif vector.identity == "method-bytes":
        body = json_bytes({"method": request.method.decode("ascii"),
                          "bodyBase64": base64.b64encode(request.body).decode("ascii"),
                          "contentLengthPresent": b"content-length" in request.headers,
                          "contentTypePresent": b"content-type" in request.headers,
                          "customHeaderBase64": (base64.b64encode(request.headers[b"x-conformance"]).decode()
                                                 if b"x-conformance" in request.headers else None)})
    elif vector.identity == "pending-upload":
        body = json_bytes({"bodyBytes": len(request.body),
                          "bodySha256": "sha256:" + hashlib.sha256(request.body).hexdigest()})
    elif vector.identity == "partial-body":
        body = PARTIAL
        fields = ((b"Content-Type", b"application/octet-stream"),)
    elif vector.identity == "truncated-body":
        body, declared = b"short", 32
    elif vector.identity == "malformed-framing":
        return (b"HTTP/1.1 200 Fixture\r\nContent-Length: 1\r\n"
                b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n0\r\n\r\n", b"")
    elif vector.identity == "malformed-json":
        body = b'{"id":'
    elif vector.identity == "oversized-body":
        body = b"x" * MAX_RESPONSE
    elif vector.identity == "gzip-json":
        body = gzip.compress(body, mtime=0)
        fields += ((b"Content-Encoding", b"gzip"),)
    elif vector.identity in {"redirect", "redirect-denied"}:
        status, body = 302, b""
        target = "redirect-target" if vector.identity == "redirect" else "denied-target"
        fields = ((b"Location", f"http://127.0.0.1:{secondary_port}/conformance/{target}".encode()),)
    elif vector.identity == "redirect-target":
        body = json_bytes({"redirected": True})
    elif vector.identity == "denied-target":
        # A contact is observable even when a language/host violates its grant.
        status, body = 403, b"denied-target-contacted"
    elif vector.mutation:
        body = json_bytes({"committed": True})
    raw_head = head(status, len(body) if declared is None else declared, headers=fields)
    if request.method == b"HEAD":
        return raw_head, b""
    if len(body) > MAX_RESPONSE:
        raise FixtureError("fixture-response-limit")
    if vector.identity == "partial-body":
        return raw_head + body[:5], body[5:]
    return raw_head + body, b""
