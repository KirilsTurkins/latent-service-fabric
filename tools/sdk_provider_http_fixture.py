"""Bounded provider peer with explicit request-start and physical-close rendezvous."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import socket
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase3_management_scenario import PROVIDER_CREDENTIAL

STOPPING = False
DEFAULT_LIFETIME_SECONDS = 300
MAX_LIFETIME_SECONDS = 1200


class ProviderDeadlineExpired(ValueError):
    """Closed fixture-lifecycle diagnostic, never a host/provider error rewrite."""


def expiry(deadline=None):
    now = time.monotonic()
    if deadline is None:
        return now + DEFAULT_LIFETIME_SECONDS
    if (type(deadline) not in (int, float) or not math.isfinite(deadline)
            or not now < deadline <= now + MAX_LIFETIME_SECONDS):
        raise ValueError("invalid provider fixture deadline")
    return deadline


def remaining(deadline, maximum):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise ProviderDeadlineExpired("provider fixture deadline expired")
    return min(maximum, seconds)


def stop(_signal, _frame):
    global STOPPING
    STOPPING = True


def mode(directory):
    path = directory / "mode"
    if not path.exists():
        return "reply"
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid rendezvous mode file")
    with path.open("rb") as source:
        value = source.read(65)
    if not re.fullmatch(rb"(?:reply|hold-[a-z0-9-]{1,48})", value):
        raise ValueError("invalid rendezvous mode")
    return value.decode("ascii")


def marker(directory, name):
    # Readers treat existence as the rendezvous. Publish the fully closed
    # payload atomically so none can observe an empty buffered file.
    temporary = directory / (name + ".pending")
    try:
        with temporary.open("xb") as output:
            output.write(b"observed\n")
        # A hard link also preserves exclusive creation: a repeated event
        # must fail instead of replacing an existing acknowledgement.
        os.link(temporary, directory / name)
    finally:
        temporary.unlink(missing_ok=True)


def request(connection, deadline):
    def receive(maximum):
        connection.settimeout(remaining(deadline, 2))
        return connection.recv(maximum)
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = receive(min(1024, 8193 - len(data)))
        if not chunk or len(chunk) > 8192 - len(data):
            raise ValueError("request header bound")
        data.extend(chunk)
    head, body = bytes(data).split(b"\r\n\r\n", 1)
    lines = head.split(b"\r\n")
    method, path, version = lines[0].split(b" ")
    fields = {}
    if len(lines) > 17:
        raise ValueError("request header count")
    for line in lines[1:]:
        name, value = line.split(b":", 1)
        name = name.lower()
        if name in fields:
            raise ValueError("duplicate request header")
        fields[name] = value.strip()
    if b"transfer-encoding" in fields:
        raise ValueError("unsupported request framing")
    length = int(fields.get(b"content-length", b"0"))
    if not 0 <= length <= 4096 or len(body) > length:
        raise ValueError("request body bound")
    while len(body) < length:
        chunk = receive(length - len(body))
        if not chunk:
            raise ValueError("truncated request body")
        body += chunk
    return (method, fields.get(b"authorization") == PROVIDER_CREDENTIAL,
            path == b"/allowed" and version == b"HTTP/1.1" and method in (b"GET", b"HEAD", b"POST"))


def hold(connection, directory, selected, owner_deadline):
    marker(directory, f"started-{selected}")
    deadline = min(owner_deadline, time.monotonic() + 3)
    while time.monotonic() < deadline and not STOPPING:
        timeout = min(remaining(owner_deadline, 0.05), max(0, deadline - time.monotonic()))
        readable, _, _ = select.select([connection], [], [], timeout)
        if readable:
            hold_remaining = deadline - time.monotonic()
            if hold_remaining <= 0:
                break
            connection.settimeout(min(remaining(owner_deadline, 2), hold_remaining))
            try:
                extra = connection.recv(1)
            except ConnectionResetError:
                extra = b""
            if extra != b"":
                raise ValueError("unexpected held request bytes")
            marker(directory, f"closed-{selected}")
            return
    if time.monotonic() >= owner_deadline:
        raise ProviderDeadlineExpired("provider fixture deadline expired")
    raise ValueError("held provider socket did not physically close")


def run(directory, *, deadline=None):
    counts = {"requests": 0, "authorized": 0, "unexpected": 0, "holds": 0, "closedHolds": 0}
    # An explicit absolute owner deadline cannot be extended by process startup.
    # Validate before opening the listener; ordinary standalone use keeps 300 s.
    deadline = expiry(deadline)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
        while not STOPPING and time.monotonic() < deadline and counts["requests"] < 32:
            try:
                listener.settimeout(remaining(deadline, 0.1))
                connection, _address = listener.accept()
            except TimeoutError:
                continue
            with connection:
                method, authorized, expected = request(connection, deadline)
                counts["requests"] += 1
                counts["authorized"] += int(authorized)
                counts["unexpected"] += int(not expected)
                selected = mode(directory)
                if authorized and expected and selected.startswith("hold-"):
                    counts["holds"] += 1
                    hold(connection, directory, selected, deadline)
                    counts["closedHolds"] += 1
                else:
                    successful = authorized and expected
                    status = b"201 Created" if successful else b"403 Forbidden"
                    body = b"ok" if successful else b"denied"
                    connection.settimeout(remaining(deadline, 2))
                    connection.sendall(b"HTTP/1.1 " + status + b"\r\nContent-Type: text/plain\r\nContent-Length: "
                                       + str(len(body)).encode("ascii") + b"\r\nConnection: close\r\n\r\n"
                                       + (b"" if method == b"HEAD" else body))
    if not STOPPING:
        if time.monotonic() >= deadline:
            raise ProviderDeadlineExpired("provider fixture deadline expired")
        raise ValueError("provider fixture bound expired")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--deadline-monotonic", type=float)
    args = parser.parse_args()
    directory = args.control.resolve(strict=True)
    if not directory.is_dir() or directory.stat().st_mode & 0o077:
        raise ValueError("protected rendezvous directory required")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(json.dumps(run(directory, deadline=args.deadline_monotonic)), flush=True)


if __name__ == "__main__":
    try:
        main()
    except ProviderDeadlineExpired:
        print("sdk-provider-fixture-deadline-expired", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError):
        print("sdk-provider-fixture-failed", file=sys.stderr)
        raise SystemExit(1)
