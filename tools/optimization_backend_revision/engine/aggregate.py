"""Compact process statistics; three profile contrasts share each block's D0."""
from decimal import Decimal

from tools.optimization_evidence.common import canonical, distribution, require, sha256, uint
from . import model


def summarize(result):
    return {name: result[name] for name in (
        "validated_attempts", "validated_commands", "attempt_count_complete", "process_identity",
        "elapsed_nanos", "engine_profile", "effective_policy", "configuration_digest",
        "phases", "metrics", "memory", "preparation", "functional", "shutdown")}


def comparisons(records, profile):
    indices = {(row["repetition"], row["variant"], row["engine_profile_id"]): row
               for row in records if row["status"] == "passed"}
    require(len(indices) == sum(row["status"] == "passed" for row in records), "engine-comparison-duplicate-owner")
    result = []
    for label, baseline, candidate in model.CONTRASTS:
        pairs, measurements = [], {}
        for repetition in range(1, model.repetitions(profile) + 1):
            left = indices.get((repetition, *baseline))
            right = indices.get((repetition, *candidate))
            if left is None or right is None:
                continue
            require(set(left["metrics"]) == set(right["metrics"]), "engine-contrast-metric-population-crossed")
            deltas = {}
            for name in left["metrics"]:
                a, b = left["metrics"][name], right["metrics"][name]
                delta = None if a is None or b is None else Decimal(b) - Decimal(a)
                deltas[name] = None if delta is None else str(delta)
                measurements.setdefault(name, []).append((a, b, delta))
            pair = {"repetition": repetition, "candidate_minus_baseline": deltas}
            for name, row in (("baseline", left), ("candidate", right)):
                pair[name] = {**{key: row[key] for key in ("repetition", "sequence_ordinal", "variant", "engine_profile_id")},
                              "source_commit": row["source"]["commit"], "binary_sha256": row["binary"]["sha256"],
                              "configuration_digest": row["configuration_digest"], "metrics": row["metrics"]}
            pairs.append(pair)
        summary = {}
        for name, rows in measurements.items():
            observed = [row for row in rows if row[2] is not None]
            summary[name] = {
                "available_pairs": len(observed), "unavailable_pairs": len(rows) - len(observed),
                "baseline": distribution([Decimal(row[0]) for row in observed]) if observed else None,
                "candidate": distribution([Decimal(row[1]) for row in observed]) if observed else None,
                "paired_difference": distribution([row[2] for row in observed]) if observed else None,
                "lower": sum(row[2] < 0 for row in observed), "equal": sum(row[2] == 0 for row in observed),
                "higher": sum(row[2] > 0 for row in observed)}
        result.append({"id": label, "shared_baseline": label != "default-preservation", "pairs": pairs,
                       "metrics": summary})
    return result


def aggregate(suite, checksum, build, records, complete, failed):
    attempts = sum(uint(row.get("validated_attempts", "0")) for row in records)
    commands = sum(uint(row.get("validated_commands", "0")) for row in records)
    if complete:
        counts = model.counts(suite["profile"])
        require(attempts == counts["invokes"] * len(model.population(suite["profile"]))
                and commands == counts["commands"] * len(model.population(suite["profile"])),
                "engine-complete-population-count-crossed")
    return {"schema": "latent.optimization.engine-aggregate.v1", "profile": suite["profile"],
            "status": "failed" if failed else "complete" if complete and suite["profile"] == "full" else "incomplete",
            "population_complete": complete, "attempt_count_complete": complete,
            "validated_attempts": str(attempts), "validated_commands": str(commands),
            "validated_processes": str(sum(row["status"] == "passed" for row in records)),
            "suite_sha256": checksum, "plan_sha256": sha256(canonical(suite["plan"])),
            "scope": "five-owned-node-engine-profiles-with-shared-within-block-D0-baselines",
            "builds": build, "runs": records, "comparisons": comparisons(records, suite["profile"]),
            "limitations": [
                "Each block has one old-control D0 and four candidate profiles; configuration contrasts share its actual candidate D0.",
                "All offered outcomes and functional work remain counted; functional cases are excluded from performance distributions.",
                "The first Echo warmup is the fresh-engine first RPC; subsequent fixture compilations are not engine-cold repeats.",
                "Successful-response quantiles are conditional on success; all-offered elapsed and throughput retain scheduling gaps.",
                "Process CPU combines node, client and observation work; separate external warm evidence retains server/client CPU.",
                "Pooling changes both allocator and declared memory layout; its contrast is not an isolated allocator implementation effect.",
                "VmSize/VmPeak virtual mappings, RSS/VmHWM, smaps fields and compiled-image charges remain distinct; unavailable values are not zero.",
                "The four-cell queued fifth call proves scheduler capacity, not native Wasmtime pool exhaustion or identical physical-slot reuse.",
                "Functional memory reads every byte before dirtying; native one-slot reuse is established by separate focused correctness tests.",
                "Terminal publication alone does not prove reclamation; final native owners, quarantine and joined cleanup are independently checked.",
                "No Heaptrack population is part of this matrix. Seven blocks and their small order strata are descriptive, not a universal SLO."]}
