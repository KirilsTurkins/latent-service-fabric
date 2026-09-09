"""Verified constructor/poll-frame union; frees retain their allocation origin."""
from array import array
import re

from tools.artifact_identity_evidence import heaptrack
from tools.optimization_cache_lookup import allocations as common
from tools.optimization_evidence.common import require
from .model import MAX_FOLDED_BYTES, SYMBOLS


class Attribution(common.Attribution):
    def __init__(self, binary_name, groups):
        self.groups = tuple(frozenset(names) for names in groups)
        super().__init__(binary_name, {name for group in self.groups for name in group})
        self.ip_masks = array("B", [0])
        self.trace_masks = array("B", [0])
        self.statistics = [dict(allocation_count=0, allocated_bytes=0, live_bytes=0,
                                peak_live_bytes=0, remaining_allocations=0) for _ in range(3)]

    def record(self, line):
        super().record(line)
        if len(line) < 3 or line[1:2] != b" ":
            return
        kind, body = line[:1], line[2:]
        if kind == b"i":
            values = heaptrack.numbers(body)
            positions = [2] if len(values) == 3 else range(2, len(values), 3)
            names = {self.names[values[index]] for index in positions}
            mask = sum(1 << index for index, group in enumerate(self.groups) if names & group)
            self.ip_masks.append(mask if self.names[values[1]] == self.binary_name else 0)
        elif kind == b"t":
            ip, parent = heaptrack.numbers(body, 2)
            self.trace_masks.append(self.ip_masks[ip] | self.trace_masks[parent])
        elif kind in (b"+", b"-"):
            index, = heaptrack.numbers(body, 1)
            mask = self.trace_masks[self.allocation_traces[index]]
            # A frame appearing twice or both measured frames appearing in one
            # allocation stack contributes once to the union.
            selected = [group for group in range(2) if mask & (1 << group)]
            if mask:
                selected.append(2)
            for group in selected:
                state, size = self.statistics[group], self.sizes[index]
                if kind == b"+":
                    state["allocation_count"] += 1
                    state["allocated_bytes"] += size
                    state["live_bytes"] += size
                    state["remaining_allocations"] += 1
                    state["peak_live_bytes"] = max(state["peak_live_bytes"], state["live_bytes"])
                else:
                    state["live_bytes"] -= size
                    state["remaining_allocations"] -= 1
                    require(state["live_bytes"] >= 0 and state["remaining_allocations"] >= 0,
                            "ownership-selected-allocation-free-without-owner")


def proofs(value, binary, tool, artifacts, *, symbols=SYMBOLS):
    return [common.symbol_proof(value, binary, tool, artifacts,
                                frame=re.compile(re.escape(symbol) + r"(?:::h[0-9a-f]{16})?\Z"))
            for symbol in symbols]


def attribute(record, binary, proof, tool, artifacts, whole, *, symbols=SYMBOLS,
              scope="allocations-with-verified-constructor-or-direct-poll-frame-union",
              maximum_records=heaptrack.MAX_RECORDS):
    maximum_records = heaptrack.record_limit(maximum_records)
    verified = proofs(proof, binary, tool, artifacts, symbols=symbols)
    groups = [() if row is None else (row["demangled"], row["raw"]) for row in verified]
    raw, state = common.replay_attribution(artifacts.path(record["profile_refs"]["interpreted"]),
                                           record["command"][3], groups, state_type=Attribution,
                                           maximum_records=maximum_records)
    require(raw == whole, "ownership-allocation-whole-replay-crossed")
    total, selected = common.folded_attribution(artifacts.path(record["profile_refs"]["allocations"]), state.folded_labels,
                                               maximum_bytes=MAX_FOLDED_BYTES)
    union = state.statistics[2]
    require(total == int(raw["allocation_count"]) and selected == union["allocation_count"] == state.named_count,
            "ownership-folded-union-attribution-crossed")
    available = all(row is not None for row in verified) and state.unresolved_count == 0
    def project(value):
        return {name: str(amount) if available else None for name, amount in value.items()}
    return {"status": "available" if available else "unavailable",
            "reason": None if available else "missing-or-ambiguous-symbol" if any(row is None for row in verified)
            else "unresolved-allocation-frame", "symbols": list(symbols), "verified_symbols": verified,
            "scope": scope,
            "union": project(union), "frames": {symbol: project(row) for symbol, row in zip(symbols, state.statistics)},
            "unresolved_allocation_count": str(state.unresolved_count),
            "observed_named_allocation_count": str(state.named_count),
            "peak_scope": "maximum-simultaneously-live-origin-attributed-bytes-not-sum-of-frame-peaks"}
