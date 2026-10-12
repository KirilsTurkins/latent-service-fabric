"""Finite HTTP/1.1 request framing for a disposable loopback test peer."""
from __future__ import annotations

import re

METHODS = frozenset({b"GET", b"HEAD", b"POST", b"PUT", b"PATCH", b"DELETE", b"OPTIONS"})
MAX_HEADERS = 32
MAX_HEADER_BYTES = 8192
MAX_BODY = 256 * 1024
MAX_WINDOW = 8192
MAX_CHUNKS = 1024
TOKEN = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


class FixtureError(ValueError):
    """A static diagnostic; never includes a request, secret or OS exception."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(condition: object, code: str) -> None:
    if not condition:
        raise FixtureError(code)


def header(line: bytes) -> tuple[bytes, bytes]:
    require(b":" in line, "request-header")
    name, value = line.split(b":", 1)
    require(TOKEN.fullmatch(name), "request-header-name")
    value = value.strip(b" \t")
    require(all(byte == 9 or byte >= 32 and byte != 127 for byte in value), "request-header-value")
    return name.lower(), value


class Request:
    """Incremental framing; at most one body and a finite unread window.

    A caller may pause immediately after headers without consuming the body.
    This permits a real upload wait while other connections continue to run.
    Chunk extensions, request trailers, expect/upgrade and pipelining are outside
    this peer's profile and fail explicitly. Empty chunks do not mean pending.
    """

    def __init__(self):
        self.buffer = bytearray()
        self.body = bytearray()
        self.method = self.path = None
        self.headers: dict[bytes, bytes] = {}
        self.complete = False
        self.chunked = False
        self.remaining = 0
        self.chunk_remaining: int | None = None
        self.chunk_count = 0
        self.framing_bytes = 0
        self.chunk_end = False
        self.chunk_terminal = False

    @property
    def headers_ready(self) -> bool:
        return self.method is not None

    def feed(self, raw: bytes, *, consume_body: bool = True) -> None:
        require(not self.complete and raw, "request-extra-or-empty-input")
        require(len(self.buffer) + len(raw) <= MAX_HEADER_BYTES + MAX_WINDOW,
                "request-window-limit")
        self.buffer.extend(raw)
        if not self.headers_ready:
            self._headers()
        if self.headers_ready and consume_body:
            self.consume()

    def _headers(self) -> None:
        end = self.buffer.find(b"\r\n\r\n")
        if end < 0:
            require(len(self.buffer) < MAX_HEADER_BYTES, "request-header-limit")
            return
        require(end + 4 <= MAX_HEADER_BYTES, "request-header-limit")
        lines = bytes(self.buffer[:end]).split(b"\r\n")
        parts = lines[0].split(b" ")
        require(len(parts) == 3 and parts[0] in METHODS and parts[2] == b"HTTP/1.1",
                "request-line")
        require(re.fullmatch(rb"/[A-Za-z0-9/_.%-]{0,255}", parts[1]), "request-target")
        fields = {}
        for line in lines[1:]:
            name, value = header(line)
            require(len(fields) < MAX_HEADERS and name not in fields,
                    "request-header-count-or-duplicate")
            fields[name] = value
        require(b"host" in fields, "request-host-required")
        require(not {b"expect", b"upgrade", b"trailer"} & fields.keys(),
                "request-unsupported-feature")
        require(not (b"content-length" in fields and b"transfer-encoding" in fields),
                "request-ambiguous-framing")
        self.chunked = b"transfer-encoding" in fields
        if self.chunked:
            require(fields[b"transfer-encoding"] == b"chunked", "request-transfer-encoding")
        else:
            length = fields.get(b"content-length", b"0")
            require(re.fullmatch(rb"0|[1-9][0-9]{0,9}", length), "request-content-length")
            self.remaining = int(length)
            require(self.remaining <= MAX_BODY, "request-body-limit")
        self.method, self.path, self.headers = parts[0], parts[1], fields
        del self.buffer[:end + 4]

    def consume(self) -> None:
        require(self.headers_ready, "request-headers-not-ready")
        if self.complete:
            require(not self.buffer, "request-additional-bytes")
            return
        if not self.chunked:
            count = min(self.remaining, len(self.buffer))
            self.body.extend(self.buffer[:count])
            del self.buffer[:count]
            self.remaining -= count
            if self.remaining == 0:
                self._finish()
            return
        while self.buffer:
            if self.chunk_terminal:
                if len(self.buffer) < 2:
                    return
                require(self.buffer[:2] == b"\r\n", "request-trailers-unsupported")
                del self.buffer[:2]
                self._finish()
                return
            if self.chunk_end:
                if len(self.buffer) < 2:
                    return
                require(self.buffer[:2] == b"\r\n", "request-chunk-terminator")
                del self.buffer[:2]
                self.chunk_end = False
                self.chunk_remaining = None
                continue
            if self.chunk_remaining is None:
                end = self.buffer.find(b"\r\n")
                if end < 0:
                    require(len(self.buffer) <= 8, "request-chunk-size")
                    return
                text = bytes(self.buffer[:end])
                require(re.fullmatch(rb"[0-9a-fA-F]{1,8}", text), "request-chunk-size")
                self.chunk_count += 1
                self.framing_bytes += end + 4
                require(self.chunk_count <= MAX_CHUNKS and self.framing_bytes <= MAX_HEADER_BYTES,
                        "request-chunk-framing-limit")
                self.chunk_remaining = int(text, 16)
                require(self.chunk_remaining <= MAX_BODY - len(self.body), "request-body-limit")
                del self.buffer[:end + 2]
                if self.chunk_remaining == 0:
                    self.chunk_terminal = True
                    continue
            count = min(self.chunk_remaining, len(self.buffer))
            self.body.extend(self.buffer[:count])
            del self.buffer[:count]
            self.chunk_remaining -= count
            if self.chunk_remaining == 0:
                self.chunk_end = True

    def _finish(self) -> None:
        require(not self.buffer, "request-additional-bytes")
        self.complete = True
