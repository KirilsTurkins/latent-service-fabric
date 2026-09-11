"""One verified poll frame, original allocation origins and explicit coverage."""
import re

from tools.optimization_cache_lookup import allocations as common
from tools.optimization_backend_revision.ownership.allocations import Attribution
from tools.optimization_evidence.common import require
from .model import MAX_FOLDED_BYTES, SYMBOL


def symbol_proof(proof, binary, tool, artifacts):
    return common.symbol_proof(proof, binary, tool, artifacts,
                               frame=re.compile(re.escape(SYMBOL) + r"(?:::h[0-9a-f]{16})?\Z"))


def attribute(record, binary, proof, tool, artifacts, whole):
    verified = symbol_proof(proof, binary, tool, artifacts)
    group = () if verified is None else (verified["demangled"], verified["raw"])
    raw, state = common.replay_attribution(artifacts.path(record["profile_refs"]["interpreted"]), record["command"][3],
                                           [group], state_type=Attribution)
    require(raw == whole, "scheduler-allocation-whole-replay-crossed")
    total, selected = common.folded_attribution(artifacts.path(record["profile_refs"]["allocations"]), state.folded_labels,
                                               maximum_bytes=MAX_FOLDED_BYTES)
    union = state.statistics[2]
    require(total == int(raw["allocation_count"]) and selected == union["allocation_count"] == state.named_count,
            "scheduler-folded-origin-attribution-crossed")
    available = verified is not None and state.unresolved_count == 0 and state.named_count > 0
    reason = None if available else "missing-or-ambiguous-symbol" if verified is None else (
        "unresolved-allocation-frame" if state.unresolved_count else "no-observed-named-allocation-origin")
    return {"status": "available" if available else "unavailable", "reason": reason, "symbol": SYMBOL,
            "verified_symbol": verified, "scope": "32-cancel-and-original-future-settlement-poll-frame",
            "statistics": {name: str(value) if available else None for name, value in union.items()},
            "observed_named_allocation_count": str(state.named_count), "unresolved_allocation_count": str(state.unresolved_count),
            "peak_scope": "maximum-simultaneously-live-origin-attributed-bytes-not-temporary-scratch"}
