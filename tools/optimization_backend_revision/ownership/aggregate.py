"""Compact paired distributions; raw outputs and owners remain in the archive."""
from decimal import Decimal

from tools.optimization_evidence.common import canonical, distribution, sha256, uint
from .model import SHAPES


def normal(result):
    rows = []
    for shape in SHAPES:
        measured = [row for row in result["calls"] if row["shape"] == shape and row["phase"] == "measured"]
        timing = [name for name in measured[0]["timing"]] if measured else []
        metrics = {name: distribution(Decimal(row[name]) for row in measured) for name in
                   ("construction_nanos", "invoke_nanos", "construction_through_return_nanos")}
        metrics.update({name: distribution(Decimal(row["timing"][name]) for row in measured) for name in timing})
        rows.append({"shape": shape, "measured_calls": str(len(measured)), "metrics": metrics})
    return rows


def aggregate(suite, checksum, build, records, complete, failed):
    indices = {(row["repetition"], row["variant"]): row for row in records
               if row["mode"] == "normal" and row["status"] == "passed"}
    comparisons = []
    for shape in SHAPES:
        pairs, differences = [], {}
        for repetition in range(1, 8):
            if any((repetition, variant) not in indices for variant in ("control", "candidate")):
                continue
            values = {variant: next(row for row in indices[repetition, variant]["timing"] if row["shape"] == shape)
                      for variant in ("control", "candidate")}
            deltas = {}
            for name in values["control"]["metrics"]:
                for quantile in ("median", "p95", "p99"):
                    key = name + "/" + quantile
                    change = Decimal(values["candidate"]["metrics"][name][quantile]) - Decimal(values["control"]["metrics"][name][quantile])
                    deltas[key] = str(change)
                    differences.setdefault(key, []).append(change)
            pairs.append({"repetition": repetition, **values, "candidate_minus_control": deltas})
        comparisons.append({"shape": shape, "pairs": pairs,
                            "paired_differences": {name: distribution(rows) for name, rows in differences.items()}})
    attempts = sum(uint(row.get("validated_invocations", "0")) for row in records)
    return {"schema": "latent.optimization.ownership-aggregate.v1", "profile": suite["profile"],
            "status": "failed" if failed else "complete" if complete and suite["profile"] == "full" else "incomplete",
            "population_complete": complete, "attempt_count_complete": complete,
            "validated_attempts": str(attempts), "validated_processes": str(sum(row["status"] == "passed" for row in records)),
            "suite_sha256": checksum, "plan_sha256": sha256(canonical(suite["plan"])),
            "scope": "direct-wasmtime-invocation-and-independent-input-ownership-and-allocation-populations",
            "builds": build, "runs": records, "comparisons": comparisons,
            "limitations": [
                "Normal direct timing, two observed pending-future proofs and one allocation pair per shape are distinct populations.",
                "Generation prepares capabilities once and performs at most 20 borrowed charge checks, with zero Invokes and zero guest Stores.",
                "Normal children prepare three components once; allocation children prepare only their selected component once.",
                "Construction includes owned request and boxed backend future; direct elapsed includes polling and actual future destruction.",
                "Backend total excludes outer context validation; reclamation timings are actual drop spans, not outcome classification.",
                "Profiler selected-frame totals include both warmup and measured calls; attribution counts a constructor/poll union once.",
                "Selected peak bytes are maximum simultaneously live allocation origins, not summed per-frame peaks or RSS.",
                "Missing symbols and unresolved allocation frames produce unavailable attribution, never inferred zero.",
                "Normal CPU is whole owned process CPU including setup, validation and holds; profiled resources are separately labeled.",
                "Direct future Drop proves backend-resource destruction; standalone transport supervision is a separate regression.",
                "Context charge is the actual conservative Rust-capacity charge, distinct from heap, guest linear memory and process RSS.",
                "Each build-only or collection stage has an independent 7200 s bound. Smoke is incomplete; seven normal pairs are descriptive."]}
