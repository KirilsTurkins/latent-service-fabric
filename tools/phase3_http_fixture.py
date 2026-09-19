"""One bounded, separately owned loopback HTTP peer; no diagnostic request echo."""
from __future__ import annotations

import json
from pathlib import Path
import signal
import socket
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase3_management_scenario import PROVIDER_CREDENTIAL

STOPPING = False


def stop(_signal, _frame):
    global STOPPING
    STOPPING = True


def request(connection):
    connection.settimeout(2)
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(min(1024, 8193 - len(data)))
        if not chunk or len(data) + len(chunk) > 8192:
            raise ValueError("http-fixture-request-bound")
        data.extend(chunk)
    headers, body = bytes(data).split(b"\r\n\r\n", 1)
    lines = headers.split(b"\r\n")
    method, path, version = lines[0].split(b" ")
    fields = {}
    for line in lines[1:]:
        name, value = line.split(b":", 1)
        name = name.lower()
        if name in fields:
            raise ValueError("http-fixture-duplicate-header")
        fields[name] = value.strip()
    length = int(fields.get(b"content-length", b"0"))
    if not 0 <= length <= 4096:
        raise ValueError("http-fixture-body-bound")
    while len(body) < length:
        chunk = connection.recv(length - len(body))
        if not chunk:
            raise ValueError("http-fixture-incomplete-body")
        body += chunk
    authorized = fields.get(b"authorization") == PROVIDER_CREDENTIAL
    expected = path == b"/allowed" and version == b"HTTP/1.1" and method in (b"GET", b"HEAD", b"POST")
    successful = authorized and expected
    status = b"201 Created" if successful else b"403 Forbidden"
    response = b"ok" if successful else b"denied"
    connection.sendall(b"HTTP/1.1 " + status + b"\r\nContent-Type: text/plain\r\nContent-Length: "
                       + str(len(response)).encode("ascii") + b"\r\nConnection: close\r\n\r\n"
                       + (b"" if method == b"HEAD" else response))
    return authorized, expected


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    counts = {"requests": 0, "authorized": 0, "unexpected": 0}
    deadline = time.monotonic() + 600
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        listener.settimeout(0.1)
        print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
        while not STOPPING and time.monotonic() < deadline and counts["requests"] < 32:
            try:
                connection, _address = listener.accept()
            except TimeoutError:
                continue
            with connection:
                authorized, expected = request(connection)
            counts["requests"] += 1
            counts["authorized"] += int(authorized)
            counts["unexpected"] += int(not expected)
    if not STOPPING:
        raise ValueError("http-fixture-limit")
    print(json.dumps(counts), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        print("http-fixture-failed", file=sys.stderr)
        raise SystemExit(1)
