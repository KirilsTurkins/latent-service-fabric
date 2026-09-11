"""One observed mutation per state and one paired process per size/layout."""
from tools.optimization_backend_revision.catalog.aggregate import contrast
from tools.optimization_evidence.common import require, uint
from . import model


def summarize(result):
    metrics = {}
    for key in ("catalog_open_nanos", "node_start_nanos", "client_connect_nanos"):
        metrics["startup." + key] = result["startup"][key]
    for category, row in [("opening", result["opening"]), ("seed", result["seed"]),
                          *(("mutation." + item["label"], item) for item in result["mutations"])]:
        if row is None:
            continue
        metrics[category + ".elapsed_nanos"] = str(uint(row["finished_nanos"]) - uint(row["started_nanos"]))
        metrics[category + ".cpu_ticks"] = row["cpu_ticks"]
        for key, value in row["work_counts"].items():
            metrics[category + ".work." + key] = None if value is None else str(value)
        for key in ("rss_max_bytes", "vm_hwm_max_bytes"):
            metrics[category + ".sampled." + key] = None if row["sampled_memory"] is None else row["sampled_memory"][key]
    checkpoints = []
    for row in result["checkpoints"]:
        for key, value in row["memory_values"].items():
            metrics["checkpoint." + row["label"] + "." + key] = value
        checkpoints.append({key: row[key] for key in ("label", "count", "old_pin", "memory_values", "cpu", "verification", "node")})
    return {**result, "metrics": metrics, "checkpoints": checkpoints}


def _paired_metrics(left, right):
    require(set(left) == set(right), "catalog-mutation-paired-metric-schema")
    return {key: contrast(left[key], right[key]) for key in left}


def aggregate(suite, suite_sha256, build, records, complete, failed):
    passed = [row for row in records if row["status"] == "passed"]
    normal_pairs, allocation_pairs = [], []
    for size_index, size in enumerate(model.scales(suite["profile"])):
        for shape in model.SHAPES:
            arms = {variant: {row["mode"]: row for row in passed if row["variant"] == variant
                    and row["shape"] == shape and row["populated_size"] == size and not model.profiled(row["mode"])}
                    for variant in ("control", "candidate")}
            if any(set(rows) != {"initial", "reopen"} for rows in arms.values()):
                continue
            metrics = {}
            for mode in ("initial", "reopen"):
                metrics.update({mode + "." + key: value for key, value in _paired_metrics(
                    arms["control"][mode]["metrics"], arms["candidate"][mode]["metrics"]).items()})
            normal_pairs.append({"populated_size": size, "shape": shape,
                "order": list(model.variants(size_index, shape)), "pairs": 1,
                "owner_ordinals": {variant: [arms[variant][mode]["sequence_ordinal"] for mode in ("initial", "reopen")]
                                   for variant in ("control", "candidate")}, "metrics": metrics})
    for shape in model.SHAPES:
        for mode in ("allocation", "allocation-reopen"):
            arms = {row["variant"]: row for row in passed if row["shape"] == shape and row["mode"] == mode}
            if set(arms) != {"control", "candidate"}:
                continue
            cases = ("reopen",) if model.is_reopen(mode) else model.MUTATIONS
            selected, union, whole = {}, {}, {}
            for case in cases:
                selected[case] = _paired_metrics(
                    arms["control"]["allocation_attribution"]["frames"][case]["counts"],
                    arms["candidate"]["allocation_attribution"]["frames"][case]["counts"])
            for key in ("allocation_count", "allocated_bytes", "peak_live_bytes", "remaining_allocations", "live_bytes"):
                union[key] = contrast(*(arms[variant]["allocation_attribution"]["union"][key]
                                        for variant in ("control", "candidate")))
                whole[key] = contrast(*(arms[variant]["whole_process_allocations"]["remaining_live_bytes" if key == "live_bytes" else key]
                                        for variant in ("control", "candidate")))
            allocation_pairs.append({"populated_size": model.allocation_size(suite["profile"]), "shape": shape,
                "mode": mode, "order": list(model.variants(0, shape)), "pairs": 1,
                "owner_ordinals": {variant: arms[variant]["sequence_ordinal"] for variant in ("control", "candidate")},
                "selected": selected, "union": union, "whole_process": whole,
                "temporary_scratch_peak_bytes": None,
                "temporary_scratch_peak_unavailable_reason": "selected-origins-include-retained-catalog-ownership"})
    full = bool(complete and not failed and suite["profile"] == "full")
    totals = {key: str(sum(uint(row[key]) for row in passed))
              for key in ("validated_commands", "validated_resolves", "validated_invocations", "validated_mutations", "validated_reopens")}
    return {"schema": "latent.optimization.catalog-mutation-aggregate.v1", "profile": suite["profile"],
            "status": "failed" if failed else "complete" if full else "incomplete",
            "population_complete": complete, "attempt_count_complete": complete, "qualifying_full_population": full,
            "scope": "zero-invoke-public-versioned-mutations-adjacent-reopen-and-separate-allocation",
            "suite": {"path": "suite.json", "sha256": suite_sha256}, "builds": suite["builds"], "plan": suite["plan"],
            "sources": {variant: build["builds"][variant]["source"] for variant in ("control", "candidate")},
            **totals, "validated_collectors": str(len(passed)),
            "planned_collectors": str(len(model.population(suite["profile"]))),
            "elapsed_nanos": suite["elapsed_nanos"], "normal_elapsed_nanos": suite["normal_elapsed_nanos"],
            "allocation_elapsed_nanos": suite["allocation_elapsed_nanos"], "runs": records,
            "normal_pairs": normal_pairs, "allocation_pairs": allocation_pairs,
            "comparison_scope": "one-paired-observation-per-size-shape-operation-no-process-quantiles"}
