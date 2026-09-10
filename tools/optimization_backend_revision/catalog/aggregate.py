"""Paired catalog quantities; one full pair per shape is not a repeated trial."""
from decimal import Decimal

from tools.optimization_evidence.common import require, uint
from . import model


def summarize(result):
    metrics = {}
    for key in ("catalog_open_nanos", "node_start_nanos", "client_connect_nanos"):
        metrics["startup." + key] = result["startup"][key]
    metrics["population_and_observation.cpu_ticks"] = result["normal_cpu_ticks"]
    checkpoints = []
    for row in result["checkpoints"]:
        prefix = "checkpoint." + row["count"] + "." + row["label"] + "."
        for key, item in row["memory_values"].items():
            metrics[prefix + key] = item
        checkpoints.append({"label": row["label"], "count": row["count"], "old_pin": row["old_pin"],
            "memory": row["memory_values"], "cpu": row["cpu"], "verification": row["verification"],
            "process": row["node"]["resources"]})
    for row in result["resolves"]:
        prefix = "resolve." + row["count"] + "." + row["case"] + "."
        for key in ("median", "p95", "p99"):
            metrics[prefix + key + "_nanos"] = row["elapsed_nanos"][key]
    for row in result["applies"]:
        count = uint(row["catalog_count"]) if row["mode"] == "weight-update" else uint(row["first"]) + uint(row["count"])
        prefix = "update" if row["mode"] == "weight-update" else "apply"
        metrics[f"{prefix}.{count}.elapsed_nanos"] = str(uint(row["finished_nanos"]) - uint(row["started_nanos"]))
        if row["sampled_memory"] is not None:
            metrics[f"{prefix}.{count}.sampled_rss_max_bytes"] = row["sampled_memory"]["rss_max_bytes"]
    return {**{key: result[key] for key in ("validated_commands", "validated_resolves", "validated_invocations", "attempt_count_complete",
            "process_identity", "elapsed_nanos", "operations", "effective_engine", "data_identity", "startup", "resolves", "applies", "proofs",
            "allocation_frame", "sampler", "before_node_memory", "after_shutdown_memory", "shutdown", "final_verification")},
            "metrics": metrics, "checkpoints": checkpoints}


def contrast(left, right):
    if left is None or right is None:
        return {"control": left, "candidate": right, "candidate_minus_control": None, "percent": None}
    a, b = Decimal(left), Decimal(right)
    return {"control": left, "candidate": right, "candidate_minus_control": str(b - a),
            "percent": None if a == 0 else str((b - a) * 100 / a)}


def aggregate(suite, suite_sha256, build, records, complete, failed):
    passed = [row for row in records if row["status"] == "passed"]
    normal_pairs, allocation_pairs = [], []
    for repetition in range(1, model.repetitions(suite["profile"]) + 1):
        for shape in model.SHAPES:
            pair = {variant: {row["mode"]: row for row in passed if row["repetition"] == repetition and row["shape"] == shape
                              and row["variant"] == variant and row["mode"] != "allocation"}
                    for variant in ("control", "candidate")}
            if any(set(rows) != {"initial", "reopen"} for rows in pair.values()):
                continue
            values = {}
            for mode in ("initial", "reopen"):
                left, right = pair["control"][mode]["metrics"], pair["candidate"][mode]["metrics"]
                require(set(left) == set(right), "catalog-paired-metric-schema")
                values.update({mode + "." + key: contrast(left[key], right[key]) for key in left})
            normal_pairs.append({"repetition": repetition, "shape": shape, "order": list(model.variants(shape)), "metrics": values})
    for shape in model.SHAPES:
        for case in model.CASES:
            pair = {row["variant"]: row for row in passed if row["mode"] == "allocation" and row["shape"] == shape and row["case"] == case}
            if set(pair) != {"control", "candidate"}:
                continue
            selected, whole = {}, {}
            for key in ("allocation_count", "allocated_bytes", "peak_live_bytes", "remaining_allocations", "live_bytes"):
                selected[key] = contrast(*(pair[variant]["allocation_attribution"]["counts"][key] for variant in ("control", "candidate")))
                whole[key] = contrast(*(pair[variant]["whole_process_allocations"]["remaining_live_bytes" if key == "live_bytes" else key]
                                        for variant in ("control", "candidate")))
            allocation_pairs.append({"shape": shape, "case": case, "order": list(model.variants(shape)),
                                     "measured_calls_per_child": str(model.counts(suite["profile"], "allocation")["measured_resolves"]),
                                     "selected": selected, "whole_process": whole})
    full = complete and suite["profile"] == "full"
    targets = None
    if full:
        pair = next(row for row in normal_pairs if row["shape"] == "distinct")
        rss = pair["metrics"]["initial.checkpoint.100000.post-publication-idle.rss_bytes"]
        known = rss["control"] is not None and rss["candidate"] is not None
        targets = {"scope": "matched-distinct-100000-after-apply-request-drop-before-resolver-oracle",
                   "maximum_candidate_rss_bytes": "1750000000", "minimum_relative_reduction_percent": "25",
                   "control_rss_bytes": rss["control"], "candidate_rss_bytes": rss["candidate"],
                   "absolute_met": uint(rss["candidate"]) <= 1750000000 if known else None,
                   "relative_met": uint(rss["candidate"]) * 4 <= uint(rss["control"]) * 3 if known else None}
    return {"schema": "latent.optimization.catalog-aggregate.v1", "profile": suite["profile"],
            "status": "failed" if failed else "complete" if full else "incomplete", "population_complete": complete,
            "attempt_count_complete": complete, "qualifying_full_population": full,
            "scope": "zero-invoke-catalog-publication-public-resolve-pin-reopen-and-separate-tiny-allocation",
            "suite": {"path": "suite.json", "sha256": suite_sha256}, "builds": suite["builds"], "plan": suite["plan"],
            "sources": {variant: build["builds"][variant]["source"] for variant in ("control", "candidate")},
            "validated_commands": str(sum(uint(row["validated_commands"]) for row in passed)),
            "validated_resolves": str(sum(uint(row["validated_resolves"]) for row in passed)), "validated_invocations": "0",
            "validated_collectors": str(len(passed)), "planned_collectors": str(len(model.population(suite["profile"]))),
            "elapsed_nanos": suite["elapsed_nanos"], "normal_elapsed_nanos": suite["normal_elapsed_nanos"],
            "allocation_elapsed_nanos": suite["allocation_elapsed_nanos"], "runs": records,
            "normal_pairs": normal_pairs, "allocation_pairs": allocation_pairs, "targets": targets}
