"""Reusable bounded HTTP peer; uses the shared provider harness's actual wire parser."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import select
import signal
import socket
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.sdk_provider_http_fixture import request
from tools.phase2_operator_process import read_json, require, write_json

STOPPING = False


def stop(_signal, _frame):
    global STOPPING
    STOPPING = True


def run(directory, maximum, seconds):
    counts = {"requests": 0, "authorized": 0, "unexpected": 0, "holds": 0, "closedHolds": 0,
              "disconnected": 0, "replied": 0}
    deadline = time.monotonic() + seconds
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        listener.settimeout(0.05)
        print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
        while not STOPPING:
            require(time.monotonic() < deadline and counts["requests"] < maximum, "resource-peer-bound")
            try:
                connection, _address = listener.accept()
            except TimeoutError:
                continue
            with connection:
                method, authorized, expected = request(connection)
                counts["requests"] += 1
                counts["authorized"] += int(authorized)
                counts["unexpected"] += int(not expected)
                require(authorized and expected, "resource-peer-authority")
                mode = read_json(directory / "mode.json")
                require(mode["kind"] in ("reply", "disconnect", "hold"), "resource-peer-mode")
                if mode["kind"] == "hold":
                    counts["holds"] += 1
                    marker = mode["ordinal"]
                    require(type(marker) is int and 0 <= marker <= 256, "resource-peer-marker")
                    if not (directory / f"started-{marker}.json").exists():
                        write_json(directory / f"started-{marker}.json", {"request": counts["requests"]})
                    until = min(deadline, time.monotonic() + 5)
                    closed = False
                    while not STOPPING and time.monotonic() < until:
                        readable, _, _ = select.select([connection], [], [], 0.02)
                        if readable:
                            try:
                                extra = connection.recv(1)
                            except ConnectionResetError:
                                extra = b""
                            require(extra == b"", "resource-peer-extra-held-bytes")
                            closed = True
                            break
                    require(closed, "resource-peer-unreclaimed-socket")
                    counts["closedHolds"] += 1
                    if not (directory / f"closed-{marker}.json").exists():
                        write_json(directory / f"closed-{marker}.json", {"request": counts["requests"]})
                elif mode["kind"] == "disconnect":
                    counts["disconnected"] += 1
                else:
                    connection.sendall(b"HTTP/1.1 201 Created\r\nContent-Type: text/plain\r\n"
                                       b"Content-Length: 2\r\nConnection: close\r\n\r\n"
                                       + (b"" if method == b"HEAD" else b"ok"))
                    counts["replied"] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--maximum", type=int, default=512, choices=range(1, 513))
    parser.add_argument("--seconds", type=int, default=1000, choices=range(1, 1201))
    args = parser.parse_args()
    require(args.control.is_dir() and not args.control.is_symlink()
            and args.control.stat().st_mode & 0o077 == 0, "resource-peer-protected-directory")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(json.dumps(run(args.control, args.maximum, args.seconds)), flush=True)


if __name__ == "__main__":
    main()
