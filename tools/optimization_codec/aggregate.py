"""Descriptive paired batch averages and allocation-origin totals; no per-call tails."""
from decimal import Decimal
from tools.optimization_evidence.common import distribution
from tools.phase1_paired.aggregate import delta
from . import model


def aggregate(suite, checksum, builds, records, complete, failed):
    indexed = {(row["repetition"], row["variant"], row["family"], row["mode"]): row
               for row in records if row["status"] == "passed"}
    pairs, across = [], []
    for family in model.FAMILIES:
        for mode in ("normal", "allocation"):
            cell = []
            for repetition in range(1, suite["plan"]["pairs"] + 1):
                arms = [indexed.get((repetition, arm, family, mode)) for arm in ("control", "candidate")]
                if any(row is None for row in arms):
                    continue
                left, right = arms
                metrics = {name: {"control": left["metrics"][name], "candidate": right["metrics"][name],
                                  "difference": delta(Decimal(right["metrics"][name]), Decimal(left["metrics"][name]))}
                           for name in sorted(set(left["metrics"]) & set(right["metrics"]))}
                pair = {"family": family, "mode": mode, "repetition": repetition,
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
            across.append({"family": family, "mode": mode, "metrics": metrics})
    return {"schema": "latent.optimization.codec-aggregate.v1", "profile": suite["profile"],
            "status": "failed" if failed else "complete" if complete and suite["profile"] == "full" else "incomplete",
            "suite_sha256": checksum, "builds": builds, "population_complete": complete, "attempt_count_complete": complete,
            "attempted_processes": len(records), "validated_processes": str(sum(row["status"] == "passed" for row in records)),
            **{name: str(sum(int(row.get(name, "0")) for row in records)) for name in
               ("validated_codec_operations", "validated_preflight_operations", "validated_warmup_operations", "validated_measured_operations")},
            "guest_invocations": "0", "runs": records, "pairs": pairs, "across_pairs": across,
            "limitations": [
                "Each direction measures one batch frame containing actual codec calls, O(1) outcome/arity/length checks and result destruction; there are no per-call p50/p95/p99 observations.",
                "Semantic preflight performs three decode and three encode calls outside timing and validates public/diagnostic/legacy parity against fixed canonical bytes.",
                "Each timed success is checked for outcome and shape; large timed values are not deeply hashed or re-encoded on every iteration.",
                "Candidate successful public decoding implies the typed path by the bound source invariant; rejection-compatible legacy work may not silently turn into an accepted typed success.",
                "Legacy-owned values supply identical encoding input capacity provenance in both arms and remain outside the measured decode allocation frame.",
                "Warmup and preflight never enter the selected measured frames; selected per-operation values, when available, are batch averages over contained calls.",
                "Thread CPU is CLOCK_THREAD_CPUTIME_ID with same-task raw ticks; normal whole-child CPU/RSS includes type extraction, fixtures, validation and holds.",
                "Profiled and normal children are separate; instrumented timing/RSS is not normal performance evidence.",
                "Allocation origins and their frees determine simultaneous selected peak; frame peaks are not summed. Missing/ambiguous symbols or unresolved frames give unavailable, never zero.",
                "The owned type-only component creates no guest Store, Instance or Invoke; no compiler-pool/node shutdown is invented.",
                "Seven alternating pairs are descriptive. Smoke verifies the bounded protocol and never qualifies as full evidence."]}
