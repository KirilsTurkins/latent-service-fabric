"""Bounded frame groups reuse the existing Heaptrack origin/lifetime replay."""
from array import array
import re

from tools.artifact_identity_evidence import heaptrack
from tools.optimization_cache_lookup import allocations as common
from tools.optimization_evidence.common import require
from . import model


class Attribution(common.Attribution):
    def __init__(self, binary_name, groups):
        require(1 <= len(groups) <= 4, "catalog-mutation-selected-frame-bound")
        self.groups = tuple(frozenset(group) for group in groups)
        super().__init__(binary_name, {name for group in self.groups for name in group})
        self.ip_masks, self.trace_masks = array("B", [0]), array("B", [0])
        self.statistics = [dict(allocation_count=0, allocated_bytes=0, live_bytes=0,
                                peak_live_bytes=0, remaining_allocations=0)
                           for _ in range(len(self.groups) + 1)]

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
            selected = [group for group in range(len(self.groups)) if mask & (1 << group)]
            if mask:
                selected.append(len(self.groups))
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
                            "catalog-mutation-origin-free-without-owner")


def cases(mode):
    require(model.profiled(mode), "catalog-mutation-unprofiled-attribution")
    return ("reopen",) if model.is_reopen(mode) else model.MUTATIONS


def proofs(value, binary, tool, artifacts, mode):
    return {case: common.symbol_proof(value, binary, tool, artifacts,
                frame=re.compile(re.escape(model.SYMBOLS[case]) + r"(?:::h[0-9a-f]{16})?\Z"))
            for case in cases(mode)}


def attribute(record, binary, symbols, tool, artifacts, whole):
    selected_cases = cases(record["mode"])
    verified = proofs(symbols, binary, tool, artifacts, record["mode"])
    groups = [() if verified[case] is None else (verified[case]["demangled"], verified[case]["raw"])
              for case in selected_cases]
    raw, state = common.replay_attribution(artifacts.path(record["profile_refs"]["interpreted"]),
        record["command"][3], groups, state_type=Attribution, maximum_records=model.MAX_PROFILE_RECORDS)
    require(raw == whole, "catalog-mutation-whole-profile-replay-crossed")
    total, selected = common.folded_attribution(artifacts.path(record["profile_refs"]["allocations"]),
        state.folded_labels, maximum_bytes=model.MAX_FOLDED_BYTES)
    union = state.statistics[-1]
    require(total == int(raw["allocation_count"]) and selected == union["allocation_count"] == state.named_count,
            "catalog-mutation-folded-origin-replay-crossed")
    available = all(value is not None for value in verified.values()) and state.unresolved_count == 0
    def project(row):
        return {key: str(value) if available else None for key, value in row.items()}
    return {"status": "available" if available else "unavailable",
            "reason": None if available else "missing-or-ambiguous-symbol"
            if any(value is None for value in verified.values()) else "unresolved-allocation-frame",
            "scope": "allocations-originating-under-verified-mutation-or-reopen-frames",
            "verified_symbols": verified,
            "frames": {case: {"symbol": model.SYMBOLS[case], "counts": project(state.statistics[index])}
                       for index, case in enumerate(selected_cases)},
            "union": project(union),
            "observed_named_allocation_count": str(state.named_count),
            "unresolved_allocation_count": str(state.unresolved_count),
            "peak_scope": "maximum-simultaneously-live-origin-attributed-bytes-not-sum-of-frame-peaks",
            "temporary_scratch_peak_bytes": None,
            "temporary_scratch_peak_unavailable_reason": "selected-origins-include-retained-catalog-ownership"}
