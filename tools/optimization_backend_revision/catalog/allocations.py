"""One verified public-resolve frame using the existing origin/live replay."""
import re

from tools.optimization_backend_revision.ownership.allocations import Attribution
from tools.optimization_cache_lookup import allocations as common
from tools.optimization_evidence.common import ratio, require
from . import model


def proof(value, binary, tool, artifacts, case):
    require(case in model.CASES, "catalog-allocation-case")
    return common.symbol_proof(value, binary, tool, artifacts,
                               frame=re.compile(re.escape(model.SYMBOLS[case]) + r"(?:::h[0-9a-f]{16})?\Z"))


def attribute(record, binary, symbols, tool, artifacts, whole, measured_calls):
    case = record["case"]
    require(type(measured_calls) is int and measured_calls in (64, 256), "catalog-frame-call-count")
    verified = proof(symbols, binary, tool, artifacts, case)
    names = () if verified is None else (verified["demangled"], verified["raw"])
    raw, state = common.replay_attribution(artifacts.path(record["profile_refs"]["interpreted"]),
                                          record["command"][3], [names], state_type=Attribution)
    require(raw == whole, "catalog-allocation-whole-replay-crossed")
    total, selected = common.folded_attribution(artifacts.path(record["profile_refs"]["allocations"]),
                                               state.folded_labels)
    observed = state.statistics[2]
    require(total == int(raw["allocation_count"])
            and selected == observed["allocation_count"] == state.named_count,
            "catalog-allocation-folded-origin-crossed")
    available = verified is not None and state.unresolved_count == 0
    counts = {key: str(value) if available else None for key, value in observed.items()}
    return {"status": "available" if available else "unavailable",
            "reason": None if available else "missing-or-ambiguous-symbol" if verified is None
            else "unresolved-allocation-frame", "symbol": model.SYMBOLS[case],
            "verified_symbol": verified, "scope": "public-resolve-and-result-drop-batch",
            "frame_invocations": "1", "contained_calls": str(measured_calls),
            "counts": counts,
            "per_operation": {key: ratio(observed[key], measured_calls) if available else None
                              for key in ("allocation_count", "allocated_bytes")},
            "peak_scope": "maximum-simultaneously-live-origin-attributed-bytes-not-divided-by-calls",
            "observed_named_allocation_count": str(state.named_count),
            "unresolved_allocation_count": str(state.unresolved_count)}
