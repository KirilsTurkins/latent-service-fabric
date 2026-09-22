"""Owned bounded HTTP peer for the actual Angular reference application."""
from __future__ import annotations

import json
from pathlib import Path
import selectors
import signal
import socket
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase3_management_scenario import PROVIDER_CREDENTIAL

STOPPING = False
RELEASING = False
BODY = b'{"message":"Hello from the scoped provider","private":"lsf-private-reference-upstream"}'


def decode_request(data):
    if len(data) > 8192:
        raise ValueError("reference-peer-header-bound")
    if b"\r\n\r\n" not in data:
        return None
    header, body = bytes(data).split(b"\r\n\r\n", 1)
    lines = header.split(b"\r\n")
    if len(lines) > 25 or body:
        raise ValueError("reference-peer-request-bound")
    method, path, version = lines[0].split(b" ")
    fields = {}
    for line in lines[1:]:
        name, value = line.split(b":", 1)
        name = name.lower()
        if name in fields:
            raise ValueError("reference-peer-duplicate-header")
        fields[name] = value.strip()
    if (method != b"GET" or path not in (b"/message", b"/slow") or version != b"HTTP/1.1"
            or b"transfer-encoding" in fields or fields.get(b"content-length", b"0") != b"0"):
        raise ValueError("reference-peer-request-profile")
    return path, fields.get(b"authorization") == PROVIDER_CREDENTIAL


def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)


def stop(_signal, _frame):
    global STOPPING
    STOPPING = True


def release(_signal, _frame):
    global RELEASING
    RELEASING = True


def respond(connection):
    connection.settimeout(0.25)
    connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                       + str(len(BODY)).encode("ascii") + b"\r\nConnection: close\r\n\r\n" + BODY)


def main():
    global RELEASING
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGUSR1, release)
    deadline = time.monotonic() + 1200
    counts = {"requests": 0, "authorized": 0, "deniedConnections": 0, "held": 0, "closedHeld": 0, "releasedHeld": 0}
    connections = {}
    listeners = []
    with selectors.DefaultSelector() as selector:
        try:
            for port in (19090, 19091):
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listeners.append(listener)
                listener.bind(("127.0.0.1", port))
                listener.listen(4)
                listener.setblocking(False)
                selector.register(listener, selectors.EVENT_READ, port)
            emit({"event": "ready", "allowedPort": 19090, "deniedPort": 19091})
            while not STOPPING:
                if time.monotonic() >= deadline or counts["requests"] > 32:
                    raise ValueError("reference-peer-lifetime-bound")
                for key, _events in selector.select(0.025):
                    if isinstance(key.data, int):
                        connection, _address = key.fileobj.accept()
                        if len(connections) >= 4:
                            connection.close()
                            raise ValueError("reference-peer-connection-bound")
                        if key.data == 19091:
                            counts["deniedConnections"] += 1
                            connection.close()
                            raise ValueError("reference-peer-denied-connection")
                        connection.setblocking(False)
                        state = {"port": key.data, "data": bytearray(), "held": False,
                                 "deadline": time.monotonic() + 6}
                        connections[connection] = state
                        selector.register(connection, selectors.EVENT_READ, state)
                        continue
                    connection, state = key.fileobj, key.data
                    try:
                        chunk = connection.recv(min(1024, 8193 - len(state["data"])))
                    except BlockingIOError:
                        continue
                    except ConnectionResetError:
                        if not state["held"]:
                            raise
                        chunk = b""
                    if state["held"]:
                        if chunk:
                            raise ValueError("reference-peer-held-input")
                        counts["closedHeld"] += 1
                        emit({"event": "closed", "ordinal": state["ordinal"]})
                    elif not chunk:
                        raise ValueError("reference-peer-incomplete-request")
                    else:
                        state["data"].extend(chunk)
                        parsed = decode_request(state["data"])
                        if parsed is None:
                            continue
                        path, authorized = parsed
                        if counts["requests"] >= 32:
                            raise ValueError("reference-peer-request-count")
                        counts["requests"] += 1
                        state["ordinal"] = counts["requests"]
                        counts["authorized"] += int(authorized)
                        if not authorized or state["port"] != 19090:
                            raise ValueError("reference-peer-authority-boundary")
                        if path == b"/slow":
                            state["held"] = True
                            counts["held"] += 1
                            emit({"event": "held", "ordinal": counts["requests"]})
                            continue
                        respond(connection)
                        emit({"event": "response", "ordinal": counts["requests"]})
                    selector.unregister(connection)
                    connections.pop(connection)
                    connection.close()
                if RELEASING:
                    RELEASING = False
                    held = [(connection, state) for connection, state in connections.items() if state["held"]]
                    if len(held) != 1:
                        raise ValueError("reference-peer-release-bound")
                    for connection, state in held:
                        respond(connection)
                        counts["releasedHeld"] += 1
                        emit({"event": "released", "ordinal": state["ordinal"]})
                        selector.unregister(connection)
                        connections.pop(connection)
                        connection.close()
                if any(time.monotonic() >= state["deadline"] for state in connections.values()):
                    raise ValueError("reference-peer-connection-deadline")
            if connections:
                raise ValueError("reference-peer-outstanding-connections")
        finally:
            for connection in connections:
                connection.close()
            for listener in listeners:
                listener.close()
    emit({"event": "stopped", **counts})


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        print("reference-peer-failed", file=sys.stderr)
        raise SystemExit(1)
