"""Named-frame attribution independently derived from interpreted allocations."""
from __future__ import annotations

from array import array
import gzip
from pathlib import Path
import re

from tools.artifact_identity_evidence import heaptrack
from tools.artifact_identity_evidence.common import MAX_FOLDED_BYTES
from tools.artifact_identity_evidence.identity import helper
from tools.optimization_evidence.common import require, uint
from .model import SYMBOL

FRAME = re.compile(re.escape(SYMBOL) + r"(?:::h[0-9a-f]{16})?\Z")


def symbol_proof(row, binary, tool, artifacts):
    require(isinstance(row["command"], list) and len(row["command"]) == 4
            and all(isinstance(value, str) for value in row["command"]), "lookup-symbol-command-shape")
    require(row["command"] == [tool["path"], "--defined-only", "--demangle", row["command"][-1]]
            and row["command"][-1].endswith("/" + binary["path"]), "lookup-symbol-command")
    helper(row["process"], tool["sha256"], row["log"], artifacts)
    count, bytes_read = 0, 0
    with artifacts.path(row["log"]).open("rb") as source:
        while line := source.readline(65537):
            bytes_read += len(line)
            require(bytes_read <= 16 * 1024**2 and len(line) <= 65536 and line.endswith(b"\n"), "lookup-symbol-output-bound")
            text = line.decode("utf-8").strip()
            match = re.fullmatch(r"[0-9a-fA-F]{1,16}\s+[tTwW]\s+(.+)", text)
            if match and FRAME.fullmatch(match[1]):
                count += 1
    # Absence is an unavailable metric, not proof of zero allocations.
    return count == 1


class Attribution(heaptrack.Replay):
    def __init__(self, binary_name):
        super().__init__()
        self.binary_name = binary_name
        self.names = [""]
        self.ip_flags = bytearray([2])
        self.trace_flags = bytearray([2])
        self.allocation_traces = array("I")
        self.named_count = self.named_bytes = self.unresolved_count = 0

    def record(self, line):
        super().record(line)
        if len(line) < 3 or line[1:2] != b" ":
            return
        kind, body = line[:1], line[2:]
        if kind == b"s":
            self.names.append(body.partition(b" ")[2].decode("utf-8"))
        elif kind == b"i":
            values = heaptrack.numbers(body)
            module = self.names[values[1]]
            functions = [self.names[values[2]]] if len(values) == 3 else [self.names[x] for x in values[2::3]]
            found = any(FRAME.fullmatch(name) for name in functions)
            probe = module == self.binary_name or module.endswith("/" + self.binary_name)
            unresolved = not module or (probe and (not functions or any(not name or name in ("??", "[unknown]") for name in functions)))
            self.ip_flags.append(int(found) | (2 if unresolved else 0))
        elif kind == b"t":
            ip, parent = heaptrack.numbers(body, 2)
            # A zero parent is the legitimate root, not a missing frame.
            self.trace_flags.append(self.ip_flags[ip] | (self.trace_flags[parent] if parent else 0))
        elif kind == b"a":
            _, trace = heaptrack.numbers(body, 2)
            self.allocation_traces.append(trace)
        elif kind == b"+":
            index, = heaptrack.numbers(body, 1)
            flags = self.trace_flags[self.allocation_traces[index]]
            if flags & 1:
                self.named_count += 1
                self.named_bytes += self.sizes[index]
            if flags & 2:
                self.unresolved_count += 1


def replay_attribution(path, binary_name):
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= heaptrack.MAX_BYTES, "lookup-profile-input-bound")
    state, total, records = Attribution(binary_name), 0, 0
    with path.open("rb") as source:
        while encoded := source.readline(heaptrack.MAX_LINE_BYTES + 1):
            total += len(encoded)
            records += 1
            require(total <= heaptrack.MAX_BYTES and records <= heaptrack.MAX_RECORDS
                    and len(encoded) <= heaptrack.MAX_LINE_BYTES and encoded.endswith(b"\n")
                    and b"\0" not in encoded and b"\r" not in encoded, "lookup-profile-stream-bound")
            state.record(encoded[:-1])
    return state.result(), state


def folded_attribution(path):
    opener = gzip.open if path.suffix == ".gz" else open
    total = rows = observed = count = 0
    with opener(path, "rb") as source:
        while encoded := source.readline(65537):
            total += len(encoded)
            rows += 1
            require(total <= MAX_FOLDED_BYTES and rows <= 100000 and len(encoded) <= 65536
                    and encoded.endswith(b"\n"), "lookup-folded-bound")
            stack, amount = encoded[:-1].decode("utf-8").rsplit(" ", 1)
            frames = stack.split(";")
            require(stack and len(frames) <= 512 and "\0" not in stack, "lookup-folded-stack")
            weight = uint(amount)
            count += weight
            if any(FRAME.fullmatch(frame) for frame in frames):
                observed += weight
    require(rows > 0 and count <= 2**64 - 1, "lookup-empty-or-overflowed-folded")
    return count, observed


def attribute(record, binary, proof, tool, artifacts, whole):
    present = symbol_proof(proof, binary, tool, artifacts)
    raw, state = replay_attribution(artifacts.path(record["profile_refs"]["interpreted"]), Path(binary["path"]).name)
    require(raw == whole, "lookup-profile-replay-disagrees")
    total, named = folded_attribution(artifacts.path(record["profile_refs"]["allocations"]))
    require(total == int(raw["allocation_count"]) and named == state.named_count, "lookup-folded-frame-attribution-mismatch")
    available = present and state.unresolved_count == 0
    return {"status": "available" if available else "unavailable", "symbol": SYMBOL,
            "reason": None if available else ("missing-or-ambiguous-symbol" if not present else "unresolved-allocation-frame"),
            "allocation_count": str(named) if available else None,
            "allocated_bytes": str(state.named_bytes) if available else None,
            "observed_named_allocation_count": str(named), "unresolved_allocation_count": str(state.unresolved_count)}
