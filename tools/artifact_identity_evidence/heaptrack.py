"""Bounded counter replay of Heaptrack 1.4.0 interpreted format 3.

Input is the original interpreted stream, decompressed with a separately checked
zstd process by the collector. This module never launches a retained executable.
The event semantics follow the versioned upstream reader and interpreter:
https://github.com/KDE/heaptrack/blob/v1.4.0/src/analyze/accumulatedtracedata.cpp
https://github.com/KDE/heaptrack/blob/v1.4.0/src/interpret/heaptrack_interpret.cpp

Allocation-info indices are zero-based; string/IP/trace indices are one-based
with zero reserved. Multiple live allocations can share one allocation-info
index. Remaining allocations/bytes are raw, without leak suppressions. Footer
counts detect missing interpreter completion; process exit and artifact hashes
remain necessary because format 3 has no independent allocation-event footer.
"""
from __future__ import annotations

from array import array
import os
from pathlib import Path
import re
import stat

MAX_BYTES = 256 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
MAX_RECORDS = 4_000_000
MAX_TABLE_ENTRIES = 250_000
MAX_COUNTER = 2**64 - 1
HEX = re.compile(rb"(?:0|[1-9a-f][0-9a-f]{0,15})\Z")
DECIMAL = re.compile(rb"(?:0|[1-9][0-9]{0,19})\Z")


def require(condition, reason):
    if not condition:
        raise ValueError("heaptrack-" + reason)


def hexadecimal(value):
    require(HEX.fullmatch(value) is not None, "invalid-hexadecimal")
    return int(value, 16)


def numbers(body, count=None):
    values = [hexadecimal(value) for value in body.split(b" ")]
    require(count is None or len(values) == count, "invalid-record-fields")
    return values


def add(left, right):
    total = left + right
    require(total <= MAX_COUNTER, "counter-overflow")
    return total


class Replay:
    def __init__(self):
        self.version = False
        self.command = None
        self.system = False
        self.body_started = False
        self.strings = self.ips = self.traces = 0
        self.sizes, self.live = array("Q"), array("Q")
        self.allocations = self.frees = self.allocated_bytes = 0
        self.live_bytes = self.live_count = self.peak_bytes = 0
        self.timestamp = None
        self.footer = 0

    def table_count(self, value):
        require(value < MAX_TABLE_ENTRIES, "table-bound")
        return value + 1

    def record(self, line):
        if not line:
            return
        if line.startswith(b"# strings:") or line.startswith(b"# ips:"):
            return self.finish_record(line)
        require(self.footer == 0, "data-after-footer")
        if line.startswith(b"#"):
            return
        require(len(line) >= 3 and line[1:2] == b" ", "invalid-record")
        kind, body = line[:1], line[2:]
        if kind in (b"v", b"X", b"I"):
            return self.header(kind, body)
        require(self.version and self.command is not None and self.system, "missing-header")
        self.body_started = True
        if kind == b"s":
            length, separator, value = body.partition(b" ")
            require(separator and hexadecimal(length) == len(value) and value, "invalid-sized-string")
            self.strings = self.table_count(self.strings)
        elif kind == b"i":
            self.instruction(body)
        elif kind == b"t":
            ip, parent = numbers(body, 2)
            require(ip <= self.ips and parent <= self.traces, "invalid-trace-reference")
            self.traces = self.table_count(self.traces)
        elif kind == b"a":
            size, trace = numbers(body, 2)
            require(trace <= self.traces, "invalid-allocation-trace")
            self.table_count(len(self.sizes))
            self.sizes.append(size)
            self.live.append(0)
        elif kind in (b"+", b"-"):
            self.allocation(kind, body)
        elif kind == b"c":
            timestamp, = numbers(body, 1)
            require(self.timestamp is None or timestamp >= self.timestamp, "backwards-timestamp")
            self.timestamp = timestamp
        elif kind == b"R":
            numbers(body, 1)
            require(self.timestamp is not None, "rss-without-timestamp")
        elif kind == b"S":
            # Suppressions affect reported leaks, never raw allocation/peak totals.
            require(body.startswith(b"leak:") and len(body) > 5, "invalid-suppression")
        else:
            # Attached/raw/future formats must not masquerade as full recordings.
            raise ValueError("heaptrack-unsupported-record")

    def header(self, kind, body):
        require(not self.body_started and self.footer == 0, "late-header")
        if kind == b"v":
            require(not self.version and self.command is None and not self.system, "duplicate-version")
            require(numbers(body, 2) == [0x10400, 3], "unsupported-version")
            self.version = True
        elif kind == b"X":
            require(self.version and self.command is None, "duplicate-or-missing-command")
            require(0 < len(body) <= 4096 and not any(value < 32 or value == 127 for value in body),
                    "invalid-command")
            try:
                self.command = body.decode("utf-8")
            except UnicodeError as error:
                raise ValueError("heaptrack-invalid-command") from error
        else:
            require(self.version and not self.system, "duplicate-or-missing-system")
            page_size, pages = numbers(body, 2)
            require(page_size > 0 and page_size & (page_size - 1) == 0 and pages > 0, "invalid-system")
            self.system = True

    def instruction(self, body):
        values = numbers(body)
        require(len(values) in (2, 3) or (5 <= len(values) <= 2 + 3 * 256
                                        and (len(values) - 2) % 3 == 0), "invalid-ip-fields")
        require(values[0] != 0 and values[1] <= self.strings, "invalid-ip-reference")
        if len(values) == 3:
            require(0 < values[2] <= self.strings, "invalid-frame-reference")
        else:
            for index in range(2, len(values), 3):
                function, file, line = values[index:index + 3]
                require(function <= self.strings and file <= self.strings and line <= 2**32 - 1,
                        "invalid-frame-reference")
        self.ips = self.table_count(self.ips)

    def allocation(self, kind, body):
        index, = numbers(body, 1)
        require(index < len(self.sizes), "invalid-allocation-reference")
        size = self.sizes[index]
        if kind == b"+":
            self.allocations = add(self.allocations, 1)
            self.allocated_bytes = add(self.allocated_bytes, size)
            self.live[index] = add(self.live[index], 1)
            self.live_count = add(self.live_count, 1)
            self.live_bytes = add(self.live_bytes, size)
            self.peak_bytes = max(self.peak_bytes, self.live_bytes)
        else:
            require(self.live[index] > 0, "free-without-live-allocation")
            self.live[index] -= 1
            self.frees = add(self.frees, 1)
            self.live_count -= 1
            self.live_bytes -= size

    def finish_record(self, line):
        require(self.version and self.command is not None and self.system
                and self.timestamp is not None, "incomplete-recording")
        name = b"# strings: " if self.footer == 0 else b"# ips: "
        require(self.footer < 2 and line.startswith(name), "invalid-footer-order")
        amount = line[len(name):]
        require(DECIMAL.fullmatch(amount) is not None, "invalid-footer-count")
        expected = self.strings if self.footer == 0 else self.ips
        require(int(amount) == expected, "footer-count-mismatch")
        self.footer += 1

    def result(self):
        require(self.footer == 2, "missing-completion-footer")
        return {
            "heaptrack_version": "1.4.0", "format_version": "3", "command": self.command,
            "allocation_count": str(self.allocations), "deallocation_count": str(self.frees),
            "allocated_bytes": str(self.allocated_bytes), "peak_live_bytes": str(self.peak_bytes),
            "remaining_live_bytes": str(self.live_bytes), "remaining_allocations": str(self.live_count),
        }


def replay(path):
    """Replay a retained regular interpreted text file, without subprocesses."""
    path = Path(path)
    require(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), "not-regular-file")
    require(path.stat().st_size <= MAX_BYTES, "byte-bound")
    state, total, records = Replay(), 0, 0
    with path.open("rb") as source:
        require(stat.S_ISREG(os.fstat(source.fileno()).st_mode), "not-regular-file")
        while encoded := source.readline(MAX_LINE_BYTES + 1):
            total += len(encoded)
            records += 1
            require(total <= MAX_BYTES, "byte-bound")
            require(len(encoded) <= MAX_LINE_BYTES and encoded.endswith(b"\n"), "line-bound-or-truncated")
            require(records <= MAX_RECORDS, "record-bound")
            require(b"\0" not in encoded and b"\r" not in encoded, "invalid-record-byte")
            state.record(encoded[:-1])
    return state.result()
