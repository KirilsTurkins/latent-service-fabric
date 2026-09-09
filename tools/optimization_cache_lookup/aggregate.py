"""Descriptive pairs of whole measured batches; no invented per-hit tails."""
from decimal import Decimal
from tools.optimization_evidence.common import distribution
from tools.phase1_paired.aggregate import delta
from . import model


def aggregate(suite, checksum, builds, records, complete, failed):
    indexed = {(row["repetition"], row["variant"], row["capacity"], row["pattern"], row["mode"]): row
               for row in records if row["status"] == "passed"}
    pairs, across = [], []
    for capacity in model.CAPACITIES:
        for pattern in model.PATTERNS:
            for mode in model.MODES:
                cell = []
                for repetition in range(1, suite["plan"]["pairs"] + 1):
                    arms = [indexed.get((repetition, arm, capacity, pattern, mode)) for arm in ("control", "candidate")]
                    if any(row is None for row in arms):
                        continue
                    left, right = arms
                    metrics = {name: {"control": left["metrics"][name], "candidate": right["metrics"][name],
                                      "difference": delta(Decimal(right["metrics"][name]), Decimal(left["metrics"][name]))}
                               for name in sorted(set(left["metrics"]) & set(right["metrics"]))}
                    pair = {"capacity": capacity, "pattern": pattern, "mode": mode, "repetition": repetition,
                            "metrics": metrics, "allocation_attribution_available": mode == "normal" or all(
                                row["allocation_attribution"]["status"] == "available" for row in arms)}
                    pairs.append(pair)
                    cell.append(pair)
                if not cell:
                    continue
                names = sorted(set.intersection(*(set(row["metrics"]) for row in cell)))
                metrics = {name: {"pairs": len(cell),
                                  "control_process_values": distribution([Decimal(row["metrics"][name]["control"]) for row in cell]),
                                  "candidate_process_values": distribution([Decimal(row["metrics"][name]["candidate"]) for row in cell]),
                                  "paired_differences": distribution([Decimal(row["metrics"][name]["difference"]["absolute"]) for row in cell])}
                           for name in names}
                across.append({"capacity": capacity, "pattern": pattern, "mode": mode, "metrics": metrics})
    return {"schema": "latent.optimization.cache-lookup-aggregate.v1", "profile": suite["profile"],
            "status": "failed" if failed else ("complete" if complete and suite["profile"] == "full" else "incomplete"),
            "suite_sha256": checksum, "builds": builds, "population_complete": complete, "attempt_count_complete": complete,
            "attempted_processes": len(records),
            "validated_measured_gets": str(sum(int(row.get("validated_measured_hits", "0")) for row in records)),
            "validated_warmup_gets": str(sum(int(row.get("validated_warmup_hits", "0")) for row in records)),
            "runs": records, "pairs": pairs, "across_pairs": across,
            "limitations": [
                "Each latency/CPU value is an average over a fixed batch; no per-get p95 or p99 was sampled.",
                "Batch work includes actual cache get, preallocated returned-tag stores, checksum accumulation and returned Arc drop.",
                "Thread CPU is an actual CLOCK_THREAD_CPUTIME_ID interval, distinct from elapsed and whole-child RUSAGE_CHILDREN CPU.",
                "Normal and Heaptrack processes are separate; profiler RSS/timing is not an unprofiled performance result.",
                "Whole-process allocations include setup and warmup; only independently replayed named-frame attribution isolates measured hit allocations.",
                "Missing or unresolved attribution is unavailable, never inferred zero; absent metrics are not a performance improvement.",
                "Generic tagged cache values measure bookkeeping, not 4096 compiled Wasmtime components or guest stores.",
                "Seven independent pairs provide descriptive variability, not significance or an SLO; smoke never completes full evidence."]}
