"""Bounded Docker Engine HTTP over one owned Unix socket per operation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import time
from urllib.parse import urlencode

API_VERSION = "1.54"
MAXIMUM_JSON = 8 * 1024**2
MAXIMUM_TAR = 512 * 1024**2
MAXIMUM_ATTACH = 1024**2
MAXIMUM_STDERR = 256 * 1024
MAXIMUM_LINE = 4096


class EngineError(ValueError):
    """A failed operation still owns its bounded response and closure receipt."""
    def __init__(self, reason, *, receipt=None, body=b""):
        super().__init__(reason)
        self.receipt, self.body = receipt, body


def _json(data):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate-json-key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid-json-number")))


def _limit(value, maximum, name):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("engine-" + name + "-bound")
    return value


def _deadline(timeout, maximum=600):
    if type(timeout) not in (int, float) or not 0 < timeout <= maximum:
        raise ValueError("engine-timeout-bound")
    return time.monotonic() + timeout


def _container(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("engine-requires-full-container-id")
    return value


def _path(value):
    if (not isinstance(value, str) or not value.startswith("/") or value.startswith("//")
            or len(value.encode()) > 16384 or any(ord(character) < 33 or ord(character) > 126 for character in value)
            or "#" in value):
        raise ValueError("engine-relative-request-path")
    return value


class _Wire:
    def __init__(self, path, deadline):
        self.deadline, self.buffer, self.closed = deadline, bytearray(), False
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self._timeout()
            self.socket.connect(path)
        except BaseException:
            self.close()
            raise

    def _timeout(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("engine-operation-deadline")
        self.socket.settimeout(remaining)

    def send(self, data, observed=None):
        view = memoryview(data)
        while view:
            self._timeout()
            count = self.socket.send(view)
            if type(count) is not int or not 0 < count <= len(view):
                raise OSError("engine-socket-short-write")
            if observed is not None:
                observed(view[:count])
            view = view[count:]

    def receive(self, maximum=65536):
        self._timeout()
        return self.socket.recv(maximum)

    def exact(self, length):
        while len(self.buffer) < length:
            block = self.receive(min(65536, length - len(self.buffer)))
            if not block:
                raise EOFError("engine-truncated-response")
            self.buffer.extend(block)
        result = bytes(self.buffer[:length])
        del self.buffer[:length]
        return result

    def some(self, maximum):
        if self.buffer:
            return self.exact(min(maximum, len(self.buffer)))
        return self.receive(maximum)

    def line(self, maximum):
        while True:
            index = self.buffer.find(b"\r\n")
            if index >= 0:
                if index + 2 > maximum:
                    raise ValueError("engine-http-line-bound")
                return self.exact(index + 2)[:-2]
            if len(self.buffer) >= maximum:
                raise ValueError("engine-http-line-bound")
            block = self.receive(min(4096, maximum - len(self.buffer)))
            if not block:
                raise EOFError("engine-truncated-http-line")
            self.buffer.extend(block)

    def headers(self):
        line = self.line(8192)
        match = re.fullmatch(rb"HTTP/1\.[01] ([0-9]{3})(?: [^\r\n]*)?", line)
        if match is None:
            raise ValueError("engine-http-status-line")
        headers, size = {}, len(line) + 2
        for _ in range(100):
            line = self.line(8192)
            size += len(line) + 2
            if size > 65536:
                raise ValueError("engine-http-header-bound")
            if not line:
                return int(match[1]), headers
            key, colon, value = line.partition(b":")
            if not colon or re.fullmatch(rb"[A-Za-z0-9!#$%&'*+.^_`|~-]+", key) is None:
                raise ValueError("engine-http-header")
            key = key.decode("ascii").lower()
            if key in headers:
                raise ValueError("engine-duplicate-http-header")
            headers[key] = value.strip().decode("latin-1")
        raise ValueError("engine-http-header-count")

    def close(self):
        if not self.closed:
            self.closed = True
            self.socket.close()


def _body(wire, status, headers, maximum):
    """Yield decoded HTTP entity bytes; never decompress arbitrary content."""
    if headers.get("content-encoding", "identity") != "identity":
        raise ValueError("engine-response-content-encoding")
    transfer, length = headers.get("transfer-encoding"), headers.get("content-length")
    if transfer is not None and length is not None:
        raise ValueError("engine-ambiguous-http-body")
    if status in (204, 304):
        if transfer is not None or length not in (None, "0"):
            raise ValueError("engine-unexpected-empty-response-body")
        return
    total = 0
    if transfer is not None:
        if transfer.lower() != "chunked":
            raise ValueError("engine-http-transfer-encoding")
        while True:
            line = wire.line(8192)
            if re.fullmatch(rb"[0-9A-Fa-f]+(?:;[^\r\n]*)?", line) is None:
                raise ValueError("engine-http-chunk-size")
            count = int(line.split(b";", 1)[0], 16)
            if count == 0:
                trailers = 0
                for _ in range(100):
                    trailer = wire.line(8192)
                    trailers += len(trailer) + 2
                    if trailers > 32768:
                        raise ValueError("engine-http-trailer-bound")
                    if not trailer:
                        return
                raise ValueError("engine-http-trailer-count")
            if total + count > maximum:
                raise ValueError("engine-response-byte-bound")
            while count:
                block = wire.some(min(count, 65536))
                if not block:
                    raise EOFError("engine-truncated-response")
                count -= len(block)
                total += len(block)
                yield block
            if wire.exact(2) != b"\r\n":
                raise ValueError("engine-http-chunk-terminator")
    elif length is not None:
        if re.fullmatch(r"[0-9]+", length) is None or int(length) > maximum:
            raise ValueError("engine-response-byte-bound")
        remaining = int(length)
        while remaining:
            block = wire.some(min(remaining, 65536))
            if not block:
                raise EOFError("engine-truncated-response")
            remaining -= len(block)
            yield block
    else:
        while True:
            if wire.buffer:
                block = bytes(wire.buffer)
                wire.buffer.clear()
            else:
                block = wire.receive(min(65536, maximum - total + 1))
            if not block:
                return
            if total + len(block) > maximum:
                raise ValueError("engine-response-byte-bound")
            total += len(block)
            yield block


class Engine:
    def __init__(self, socket_path="/var/run/docker.sock"):
        path = os.fspath(socket_path)
        if not isinstance(path, str) or not path.startswith("/") or "\0" in path or len(path.encode()) > 107:
            raise ValueError("engine-unix-socket-path")
        self.socket_path, self.api_version, self.last_body = path, API_VERSION, b""
        value, receipt = self._request("GET", "/version", None, (200,), 30, MAXIMUM_JSON, versioned=False)
        def version(item):
            if not isinstance(item, str) or re.fullmatch(r"[0-9]+\.[0-9]+", item) is None:
                raise ValueError("engine-api-version")
            return tuple(map(int, item.split(".")))
        if (not isinstance(value, dict) or not isinstance(value.get("Version"), str)
                or not version(value.get("MinAPIVersion")) <= version(API_VERSION) <= version(value.get("ApiVersion"))):
            raise EngineError("engine-api-1.54-unsupported", receipt=receipt, body=self.last_body)
        self.server_version, self.version, self.version_receipt = value["Version"], value, receipt
        self.version_body = self.last_body

    def _exchange(self, method, path, chunks, length, *, expected, timeout, maximum,
                  content_type="application/json", sink=None):
        path = _path(path)
        if method not in ("GET", "POST", "PUT", "DELETE", "HEAD"):
            raise ValueError("engine-http-method")
        if not expected or any(type(status) is not int or not 200 <= status <= 599 for status in expected):
            raise ValueError("engine-expected-status")
        deadline = _deadline(timeout)
        begin, wire, response, output_hash = time.monotonic_ns(), None, bytearray(), hashlib.sha256()
        input_hash, sent, received, status, complete = hashlib.sha256(), 0, 0, None, False
        failure, headers = None, {}
        self.last_body = b""
        def sent_body(block):
            nonlocal sent
            sent += len(block)
            input_hash.update(block)
        try:
            wire = _Wire(self.socket_path, deadline)
            header = (f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n"
                      f"Content-Type: {content_type}\r\nContent-Length: {length}\r\n\r\n").encode("ascii")
            wire.send(header)
            for block in chunks:
                if sent + len(block) > length:
                    raise ValueError("engine-request-size-changed")
                wire.send(block, sent_body)
            if sent != length:
                raise ValueError("engine-request-size-changed")
            status, headers = wire.headers()
            for block in (() if method == "HEAD" else _body(wire, status, headers, maximum)):
                if sink is None or status not in expected:
                    if len(response) + len(block) > MAXIMUM_JSON:
                        raise ValueError("engine-error-response-byte-bound")
                    response.extend(block)
                else:
                    sink.write(block)
                received += len(block)
                output_hash.update(block)
            if sink is not None:
                sink.flush()
            complete = True
            if status not in expected:
                raise ValueError("engine-http-status")
        except (OSError, ValueError, EOFError) as error:
            failure = "engine-operation-timeout" if isinstance(error, TimeoutError) else str(error)
        finally:
            if wire is not None:
                wire.close()
            self.last_body = bytes(response)
            receipt = {"method": method, "path": path, "begin_nanos": str(begin),
                       "end_nanos": str(time.monotonic_ns()), "status": status,
                       "request_bytes": str(sent), "request_sha256": "sha256:" + input_hash.hexdigest(),
                       "response_bytes": str(received), "response_sha256": "sha256:" + output_hash.hexdigest(),
                       "response_complete": complete, "connection_closed": wire is None or wire.closed,
                       "failure": failure}
            if "x-docker-container-path-stat" in headers:
                receipt["archive_stat_header"] = headers["x-docker-container-path-stat"]
            self.last_receipt = receipt
        if failure is not None:
            raise EngineError(failure, receipt=receipt, body=self.last_body)
        return self.last_body, receipt

    def _request(self, method, path, body, expected, timeout, maximum, *, versioned=True):
        _limit(maximum, MAXIMUM_JSON, "json-response")
        encoded = b"" if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False,
                                                     separators=(",", ":")).encode()
        if len(encoded) > MAXIMUM_JSON:
            raise ValueError("engine-json-request-bound")
        path = _path(path)
        if versioned:
            path = "/v" + self.api_version + path
        raw, receipt = self._exchange(method, path, [encoded], len(encoded), expected=expected,
                                      timeout=timeout, maximum=maximum)
        try:
            value = _json(raw) if raw else None
        except (ValueError, RecursionError) as error:
            receipt["failure"] = "engine-invalid-json-response"
            raise EngineError("engine-invalid-json-response", receipt=receipt, body=raw) from error
        return value, receipt

    def request(self, method, path, body=None, *, expected=(200,), timeout=30, maximum=MAXIMUM_JSON):
        return self._request(method, path, body, expected, timeout, maximum)

    def build(self, tar_path, query, timeout=600):
        if not isinstance(query, dict) or set(query) - {"t", "labels", "dockerfile", "networkmode", "pull", "rm", "forcerm", "version", "platform"}:
            raise ValueError("engine-build-query")
        fixed = {"dockerfile": "Dockerfile", "networkmode": "none", "pull": "0", "rm": "1", "forcerm": "1", "version": "1", "platform": "linux/amd64"}
        if any(key in query and query[key] != value for key, value in fixed.items()):
            raise ValueError("engine-build-network-or-recipe")
        parameters = {**fixed, **query}
        if "t" in parameters and (not isinstance(parameters["t"], str)
                                  or re.fullmatch(r"[a-z0-9][a-z0-9._:/-]{0,255}", parameters["t"]) is None):
            raise ValueError("engine-build-tag")
        if "labels" in parameters:
            labels = parameters["labels"]
            labels = _json(labels) if isinstance(labels, str) else labels
            if not isinstance(labels, dict) or len(labels) > 32 or any(
                    not isinstance(key, str) or not isinstance(value, str) for key, value in labels.items()):
                raise ValueError("engine-build-labels")
            parameters["labels"] = json.dumps(labels, sort_keys=True, separators=(",", ":"))
        path = Path(tar_path)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink() or not 0 < info.st_size <= MAXIMUM_TAR:
            raise ValueError("engine-build-tar-bound")
        with path.open("rb") as stream:
            raw, receipt = self._exchange("POST", "/v" + self.api_version + "/build?" + urlencode(parameters),
                                          iter(lambda: stream.read(65536), b""), info.st_size,
                                          expected=(200,), timeout=timeout, maximum=MAXIMUM_JSON,
                                          content_type="application/x-tar")
        try:
            rows = []
            for line in raw.splitlines():
                if not line or len(line) > 256 * 1024 or len(rows) >= 65536:
                    raise ValueError("engine-build-stream-bound")
                row = _json(line)
                if not isinstance(row, dict):
                    raise ValueError("engine-build-stream-object")
                rows.append(row)
                if row.get("error") or row.get("errorDetail"):
                    raise ValueError("engine-build-stream-error")
            if not rows:
                raise ValueError("engine-build-stream-empty")
        except (ValueError, RecursionError) as error:
            receipt["failure"] = str(error)
            raise EngineError(str(error), receipt=receipt, body=raw) from error
        return rows, receipt

    def download_archive(self, container_id, source_path, destination, *, timeout=300, maximum=MAXIMUM_TAR):
        _container(container_id)
        _limit(maximum, MAXIMUM_TAR, "archive-response")
        if (not isinstance(source_path, str) or not source_path.startswith("/") or "\0" in source_path
                or len(source_path.encode()) > 4096):
            raise ValueError("engine-archive-source-path")
        destination = Path(destination)
        output = destination.open("xb")
        try:
            with output:
                _, receipt = self._exchange("GET", "/v" + self.api_version + "/containers/" + container_id
                                            + "/archive?" + urlencode({"path": source_path}), [], 0,
                                            expected=(200,), timeout=timeout, maximum=maximum, sink=output)
        except EngineError as error:
            error.receipt.update(destination=str(destination), file_closed=output.closed)
            raise
        except OSError as error:
            receipt = {**self.last_receipt, "destination": str(destination), "file_closed": output.closed,
                       "failure": "engine-archive-file-close-failed"}
            raise EngineError("engine-archive-file-close-failed", receipt=receipt, body=self.last_body) from error
        receipt["destination"] = str(destination)
        receipt["file_closed"] = True
        return receipt

    def attach(self, container_id, stdout_path, stderr_path):
        return Attach(self, _container(container_id), Path(stdout_path), Path(stderr_path))


class Attach:
    """One full-duplex hijacked connection, with no detached thread or process."""
    def __init__(self, engine, container_id, stdout_path, stderr_path):
        self.container_id, self.begin = container_id, time.monotonic_ns()
        self.wire, self.stdout, self.stderr = None, None, None
        self.stdout_path, self.stderr_path = stdout_path, stderr_path
        self.stdout_hash, self.stderr_hash, self.stdin_hash = (hashlib.sha256() for _ in range(3))
        self.stdout_bytes = self.stderr_bytes = self.stdin_bytes = 0
        self.pending, self.tail_length = bytearray(), 0
        self.frame_left, self.frame_stream, self.status, self.frames = 0, None, None, 0
        self.upgrade_body = b""
        self.eof, self.closed, self.failure, self.receipt = False, False, None, None
        self.until = time.monotonic() + 7200
        try:
            self.stdout = stdout_path.open("xb")
            self.stderr = stderr_path.open("xb")
            self.wire = _Wire(engine.socket_path, _deadline(30))
            path = "/v" + engine.api_version + "/containers/" + container_id + "/attach?stream=1&stdin=1&stdout=1&stderr=1"
            self.wire.send((f"POST {path} HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\n"
                            "Upgrade: tcp\r\nContent-Length: 0\r\n\r\n").encode("ascii"))
            self.status, headers = self.wire.headers()
            if (self.status != 101 or headers.get("upgrade", "").lower() != "tcp"
                    or "upgrade" not in [part.strip().lower() for part in headers.get("connection", "").split(",")]):
                if self.status != 101:
                    self.upgrade_body = b"".join(_body(self.wire, self.status, headers, MAXIMUM_JSON))
                    engine.last_body = self.upgrade_body
                raise ValueError("engine-attach-upgrade-rejected")
        except (OSError, ValueError, EOFError) as error:
            self.failure = str(error)
            receipt = self.close()
            raise EngineError("engine-attach-failed", receipt=receipt, body=self.upgrade_body) from error

    def _set_deadline(self, timeout):
        if self.closed:
            raise ValueError("engine-attach-closed")
        self.wire.deadline = min(_deadline(timeout), self.until)

    def send_line(self, value):
        if not isinstance(value, str) or "\n" in value or "\r" in value:
            raise ValueError("engine-attach-input-line")
        data = (value + "\n").encode()
        if len(data) > 65536:
            raise ValueError("engine-attach-input-line-bound")
        self._set_deadline(30)
        def sent(block):
            self.stdin_bytes += len(block)
            self.stdin_hash.update(block)
        try:
            self.wire.send(data, sent)
        except OSError as error:
            self.failure = "engine-attach-send-failed"
            raise EngineError(self.failure, receipt=self.close()) from error

    def _frame(self):
        if not self.frame_left:
            if not self.wire.buffer:
                block = self.wire.receive(8)
                if not block:
                    self.eof = True
                    if self.pending:
                        raise ValueError("engine-attach-unterminated-stdout")
                    raise EOFError("engine-attach-eof")
                self.wire.buffer.extend(block)
            header = self.wire.exact(8)
            self.frames += 1
            if self.frames > 65536:
                raise ValueError("engine-attach-frame-count-bound")
            self.frame_stream, self.frame_left = header[0], int.from_bytes(header[4:], "big")
            if self.frame_stream not in (1, 2) or header[1:4] != b"\0\0\0":
                raise ValueError("engine-attach-multiplex-header")
            if self.stdout_bytes + self.stderr_bytes + self.frame_left > MAXIMUM_ATTACH:
                raise ValueError("engine-attach-output-bound")
            if self.frame_stream == 2 and self.stderr_bytes + self.frame_left > MAXIMUM_STDERR:
                raise ValueError("engine-attach-stderr-bound")
            if not self.frame_left:
                return
        block = self.wire.some(min(self.frame_left, 4096))
        if not block:
            raise EOFError("engine-attach-truncated-payload")
        self.frame_left -= len(block)
        if self.frame_stream == 1:
            lengths = block.split(b"\n")
            tail = self.tail_length
            for index, piece in enumerate(lengths):
                tail += len(piece) + (index < len(lengths) - 1)
                if tail > MAXIMUM_LINE:
                    raise ValueError("engine-attach-stdout-line-bound")
                if index < len(lengths) - 1:
                    tail = 0
            self.tail_length = tail
            self.stdout.write(block)
            self.stdout.flush()
            self.stdout_hash.update(block)
            self.stdout_bytes += len(block)
            self.pending.extend(block)
        else:
            self.stderr.write(block)
            self.stderr.flush()
            self.stderr_hash.update(block)
            self.stderr_bytes += len(block)

    def next_line(self, timeout):
        self._set_deadline(timeout)
        try:
            while True:
                index = self.pending.find(b"\n")
                if index >= 0:
                    line = bytes(self.pending[:index])
                    del self.pending[:index + 1]
                    return line.decode("utf-8")
                self._frame()
        except TimeoutError:
            # A caller may poll again; the incomplete frame/header remains owned.
            raise
        except EOFError:
            if not self.eof:
                self.failure = "engine-attach-truncated-frame"
                raise EngineError(self.failure, receipt=self.close())
            raise
        except (OSError, ValueError) as error:
            self.failure = str(error)
            raise EngineError(self.failure, receipt=self.close()) from error

    def close(self):
        if self.closed:
            return self.receipt
        self.closed = True
        if self.wire is not None:
            self.wire.close()
        for output in (self.stdout, self.stderr):
            if output is not None:
                try:
                    output.close()
                except OSError:
                    self.failure = self.failure or "engine-attach-file-close-failed"
        self.receipt = {"container_id": self.container_id, "begin_nanos": str(self.begin),
                        "end_nanos": str(time.monotonic_ns()), "status": self.status,
                        "stdin_bytes": str(self.stdin_bytes), "stdin_sha256": "sha256:" + self.stdin_hash.hexdigest(),
                        "stdout_path": str(self.stdout_path), "stdout_bytes": str(self.stdout_bytes),
                        "stdout_sha256": "sha256:" + self.stdout_hash.hexdigest(),
                        "stderr_path": str(self.stderr_path), "stderr_bytes": str(self.stderr_bytes),
                        "stderr_sha256": "sha256:" + self.stderr_hash.hexdigest(),
                        "eof": self.eof, "frames": self.frames,
                        "upgrade_response_bytes": str(len(self.upgrade_body)),
                        "upgrade_response_sha256": "sha256:" + hashlib.sha256(self.upgrade_body).hexdigest(),
                        "connection_closed": self.wire is None or self.wire.closed,
                        "files_closed": all(output is None or output.closed for output in (self.stdout, self.stderr)),
                        "failure": self.failure}
        return self.receipt

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
