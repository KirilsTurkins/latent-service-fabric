"""Named-frame attribution independently derived from interpreted allocations."""
from __future__ import annotations

from array import array
import gzip
import re

from tools.artifact_identity_evidence import heaptrack
from tools.artifact_identity_evidence.common import MAX_FOLDED_BYTES
from tools.artifact_identity_evidence.identity import helper
from tools.optimization_evidence.common import fields, require, uint
from .model import SYMBOL

FRAME = re.compile(re.escape(SYMBOL) + r"(?:::h[0-9a-f]{16})?\Z")


def nm_rows(path):
    bytes_read = records = 0
    with path.open("rb") as source:
        while line := source.readline(65537):
            bytes_read += len(line)
            records += 1
            require(bytes_read <= 16 * 1024**2 and records <= 500000 and len(line) <= 65536
                    and line.endswith(b"\n") and b"\0" not in line, "lookup-symbol-output-bound")
            match = re.fullmatch(r"([0-9a-fA-F]{1,16})\s+([tTwW])\s+(.+)", line.decode("utf-8").strip())
            if match:
                yield int(match[1], 16), match[2], match[3]


def symbol_proof(row, binary, tool, artifacts):
    fields(row, "command process log raw")
    require(isinstance(row["command"], list) and len(row["command"]) == 4
            and all(isinstance(value, str) for value in row["command"]), "lookup-symbol-command-shape")
    require(row["command"] == [tool["path"], "--defined-only", "--demangle", row["command"][-1]]
            and row["command"][-1].endswith("/" + binary["path"]), "lookup-symbol-command")
    helper(row["process"], tool["sha256"], row["log"], artifacts)
    raw = fields(row["raw"], "command process log")
    require(raw["command"] == [tool["path"], "--defined-only", row["command"][-1]], "lookup-raw-symbol-command-crossed")
    helper(raw["process"], tool["sha256"], raw["log"], artifacts)
    matches = [entry for entry in nm_rows(artifacts.path(row["log"])) if FRAME.fullmatch(entry[2])]
    # Absence/ambiguity remains unavailable, never inferred zero. The raw proof
    # must still be bounded and valid even in that case.
    if len(matches) != 1:
        for _ in nm_rows(artifacts.path(raw["log"])):
            pass
        return None
    address, kind, demangled = matches[0]
    names = [entry[2] for entry in nm_rows(artifacts.path(raw["log"])) if entry[:2] == (address, kind)]
    require(len(names) == 1 and names[0] and not any(char.isspace() for char in names[0]),
            "lookup-raw-symbol-address-type-missing-or-ambiguous")
    return {"address": format(address, "x"), "type": kind, "demangled": demangled, "raw": names[0]}


class Attribution(heaptrack.Replay):
    def __init__(self, binary_name, symbols):
        super().__init__()
        self.binary_name = binary_name
        self.symbols = frozenset(symbols)
        self.folded_labels = set(symbols)
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
            positions = [2] if len(values) == 3 else list(range(2, len(values), 3))
            functions = [self.names[values[index]] for index in positions]
            named = any(name in self.symbols for name in functions)
            probe = module == self.binary_name
            found = probe and named
            unresolved = (not module or (named and not probe)
                          or (probe and (not functions or any(not name or name in ("??", "[unknown]") for name in functions))))
            if found:
                for index in positions:
                    if self.names[values[index]] not in self.symbols or index + 2 >= len(values):
                        continue
                    filename = self.names[values[index + 1]].replace("\\", "/").rsplit("/", 1)[-1]
                    if filename:
                        # heaptrack_print appends the actual source-file label;
                        # accepting that spelling is not Rust demangling.
                        self.folded_labels.update(name + " (" + filename + ")" for name in self.symbols)
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


def replay_attribution(path, binary_name, symbols=()):
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= heaptrack.MAX_BYTES, "lookup-profile-input-bound")
    state, total, records = Attribution(binary_name, symbols), 0, 0
    with path.open("rb") as source:
        while encoded := source.readline(heaptrack.MAX_LINE_BYTES + 1):
            total += len(encoded)
            records += 1
            require(total <= heaptrack.MAX_BYTES and records <= heaptrack.MAX_RECORDS
                    and len(encoded) <= heaptrack.MAX_LINE_BYTES and encoded.endswith(b"\n")
                    and b"\0" not in encoded and b"\r" not in encoded, "lookup-profile-stream-bound")
            state.record(encoded[:-1])
    return state.result(), state


def folded_attribution(path, labels=()):
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
            if any(frame in labels for frame in frames):
                observed += weight
    require(rows > 0 and count <= 2**64 - 1, "lookup-empty-or-overflowed-folded")
    return count, observed


def attribute(record, binary, proof, tool, artifacts, whole):
    verified = symbol_proof(proof, binary, tool, artifacts)
    names = () if verified is None else (verified["demangled"], verified["raw"])
    raw, state = replay_attribution(artifacts.path(record["profile_refs"]["interpreted"]), record["command"][3], names)
    require(raw == whole, "lookup-profile-replay-disagrees")
    total, named = folded_attribution(artifacts.path(record["profile_refs"]["allocations"]), state.folded_labels)
    require(total == int(raw["allocation_count"]) and named == state.named_count, "lookup-folded-frame-attribution-mismatch")
    available = verified is not None and state.unresolved_count == 0
    return {"status": "available" if available else "unavailable", "symbol": SYMBOL,
            "reason": None if available else ("missing-or-ambiguous-symbol" if verified is None else "unresolved-allocation-frame"),
            "verified_symbol": verified,
            "allocation_count": str(named) if available else None,
            "allocated_bytes": str(state.named_bytes) if available else None,
            "observed_named_allocation_count": str(named), "unresolved_allocation_count": str(state.unresolved_count)}
