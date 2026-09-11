"""Replay actual scheduler/permit ownership, fixed offers and cancellation witnesses."""
from decimal import Decimal

from tools.optimization_evidence.common import canonical, fields, integer, require, uint
from . import model, rows

WORK = ("tenant_linear_visits", "winner_comparisons", "cancel_entry_visits", "entry_shifted_slots",
        "tenant_shifted_slots", "entry_unlinks", "tenant_index_lookups")
SCHEDULER = ("capacity", "available", "active_leases", "quarantined", "queue_depth", "queued_tenants", "rejected",
             "cancellations", "expired", "granted", "total_wait_micros", "max_wait_micros", "oldest_lease_age_micros")
QUOTA = ("active_activations", "queued_activations", "reserved_cpu_fuel", "reserved_memory_bytes", "retained_tenants")


def checkpoint(value, selected, elapsed):
    fields(value, "label started_nanos finished_nanos scheduler quota work")
    begin, end = uint(value["started_nanos"]), uint(value["finished_nanos"])
    require(begin <= end <= elapsed, "scheduler-checkpoint-clock")
    state = fields(value["scheduler"], "accepting " + " ".join(SCHEDULER))
    require(type(state["accepting"]) is bool, "scheduler-accepting-type")
    numeric = {name: uint(state[name]) for name in SCHEDULER}
    require(numeric["capacity"] == 4 and numeric["available"] + numeric["active_leases"] + numeric["quarantined"] == 4
            and numeric["quarantined"] == 0 and numeric["queue_depth"] <= model.settings(selected)["queue_capacity"]
            and numeric["queued_tenants"] <= min(numeric["queue_depth"], model.tenants(selected)), "scheduler-checkpoint-pool-conservation")
    quota = fields(value["quota"], " ".join(QUOTA))
    usage = {name: uint(quota[name]) for name in QUOTA}
    require(usage["queued_activations"] <= usage["active_activations"] <= 68
            and usage["retained_tenants"] <= model.tenants(selected)
            and usage["reserved_cpu_fuel"] == usage["active_activations"] * 100
            and usage["reserved_memory_bytes"] == usage["active_activations"] * 65536, "scheduler-quota-conservation")
    work = fields(value["work"], "enabled overflowed " + " ".join(WORK))
    require(type(work["enabled"]) is bool and work["overflowed"] is False, "scheduler-work-flags")
    for name in WORK:
        uint(work[name])
    enabled = selected["mode"] == "normal" and selected["case"].startswith("cancel-") and value["label"] in ("cancel-before", "cancel-after")
    require(work["enabled"] is enabled, "scheduler-counter-scope")
    require(enabled and value["label"] == "cancel-after" or all(work[name] == "0" for name in WORK), "scheduler-work-outside-window")
    return begin, end


def idle(value, accepting):
    state = value["scheduler"]
    require(state["accepting"] is accepting and state["available"] == "4"
            and all(state[key] == "0" for key in ("active_leases", "quarantined", "queue_depth", "queued_tenants"))
            and all(value["quota"][key] == "0" for key in QUOTA), "scheduler-final-owners-not-idle")


def parse(value, selected, identity, process_id, plan_sha256, identity_sha256):
    fields(value, "schema plan identity process_id plan_sha256 identity_sha256 settings started_nanos finished_nanos elapsed_nanos "
                  "outcome failure counts rows checkpoints frame runtime_dropped fixture_dropped invokes")
    model.validate_plan(selected)
    require(value["schema"] == model.PREFIX + "arm.v1" and canonical(value["plan"]) == canonical(selected)
            and value["identity"] == identity and integer(value["process_id"], 2, 2**31 - 1) == process_id
            and value["plan_sha256"] == plan_sha256 and value["identity_sha256"] == identity_sha256,
            "scheduler-raw-input-crossed")
    require(canonical(value["settings"]) == canonical(model.settings(selected)), "scheduler-effective-settings")
    require(value["outcome"] == "passed" and value["failure"] is None and value["runtime_dropped"] is True
            and value["fixture_dropped"] is True and value["invokes"] == "0", "scheduler-raw-incomplete-cleanup")
    started, finished, elapsed = (uint(value[key]) for key in ("started_nanos", "finished_nanos", "elapsed_nanos"))
    require(0 < started <= finished <= elapsed <= (180 if selected["mode"] == "allocation" else 60) * 10**9, "scheduler-raw-clock-bound")
    original = rows.validate(value["rows"], selected, started, finished)
    require([row["ordinal"] for row in value["rows"]] == [str(index) for index in range(len(original))], "scheduler-raw-row-order")
    expected_counts = rows.counts(original)
    require(value["counts"] == expected_counts, "scheduler-observed-counts-crossed")
    checkpoints = value["checkpoints"]
    storm = selected["case"].startswith("cancel-")
    labels = (["ready", "four-holders", "queued", "cancel-before", "cancel-after", "storm-drained", "shutdown"] if storm else
              ["ready", "after-warmup", *[f"load-{index:05}" for index in range(31, model.counts(selected)["measured_offers"], 32)], "load-finished", "shutdown"])
    require(isinstance(checkpoints, list) and len(checkpoints) == len(labels), "scheduler-checkpoint-population")
    previous = 0
    monotonic = {name: 0 for name in ("rejected", "cancellations", "expired", "granted", "total_wait_micros", "max_wait_micros")}
    for label, item in zip(labels, checkpoints):
        require(item["label"] == label, "scheduler-checkpoint-order")
        begin, end = checkpoint(item, selected, elapsed)
        require(previous <= begin, "scheduler-checkpoint-overlap")
        previous = end
        for name in monotonic:
            observed = uint(item["scheduler"][name])
            require(monotonic[name] <= observed, "scheduler-cumulative-counter-regressed")
            monotonic[name] = observed
    indexed = {item["label"]: item for item in checkpoints}
    idle(checkpoints[0], True)
    idle(checkpoints[-2], True)
    idle(checkpoints[-1], False)
    require(all(checkpoints[0]["scheduler"][name] == "0" for name in monotonic), "scheduler-initial-hidden-work")
    require(uint(checkpoints[0]["finished_nanos"]) <= started and finished <= uint(checkpoints[-2]["started_nanos"]),
            "scheduler-window-checkpoint-clock")
    require(monotonic["granted"] == int(expected_counts["released"])
            and monotonic["cancellations"] == (32 if storm else 0), "scheduler-final-outcomes-crossed")
    if storm:
        for label, depth, active in (("four-holders", 0, 4), ("queued", 64, 68), ("cancel-before", 64, 68), ("cancel-after", 32, 36)):
            state, quota = indexed[label]["scheduler"], indexed[label]["quota"]
            require(state["active_leases"] == "4" and state["available"] == "0" and state["queue_depth"] == str(depth)
                    and quota["active_activations"] == str(active) and quota["queued_activations"] == str(depth),
                    "scheduler-cancel-ownership-witness")
        require(indexed["queued"]["scheduler"]["queued_tenants"] == str(model.tenants(selected)), "scheduler-storm-tenants")
        frame = fields(value["frame"], "symbol polls started_nanos finished_nanos cancel_calls settled scope")
        require(frame["symbol"] == model.SYMBOL and uint(frame["polls"]) > 0 and frame["cancel_calls"] == frame["settled"] == "32"
                and frame["scope"] == "cancel-and-original-enqueue-future-settlement", "scheduler-cancellation-frame")
        begin, end = uint(frame["started_nanos"]), uint(frame["finished_nanos"])
        require(uint(indexed["cancel-before"]["finished_nanos"]) <= begin <= end
                <= uint(indexed["cancel-after"]["started_nanos"]), "scheduler-frame-clock")
        for row in original:
            if row["cancel_requested_nanos"] is not None:
                require(begin <= uint(row["cancel_requested_nanos"]) <= uint(row["result_nanos"]) <= end,
                        "scheduler-cancel-settlement-outside-frame")
            elif row["role"] == "holder":
                require(uint(row["result_nanos"]) <= uint(indexed["four-holders"]["started_nanos"])
                        and uint(row["release_started_nanos"]) >= uint(indexed["cancel-after"]["finished_nanos"]),
                        "scheduler-holder-not-retained-through-cancel")
    else:
        require(value["frame"] is None, "scheduler-frame-in-load")
        idle(indexed["after-warmup"], True)
        require(uint(indexed["after-warmup"]["finished_nanos"]) <= started
                and indexed["after-warmup"]["scheduler"]["granted"] == "8", "scheduler-warmup-boundary")
        for row in original[:8]:
            require(uint(row["released_nanos"]) <= uint(indexed["after-warmup"]["started_nanos"]), "scheduler-warmup-clock")
    measured = [row for row in original if row["role"] != "warmup"]
    duration = finished - started
    return {"counts": expected_counts, "settings": value["settings"], "started_nanos": str(started), "finished_nanos": str(finished),
            "elapsed_nanos": str(duration), "whole_raw_elapsed_nanos": str(elapsed),
            "measured": rows.summarize(measured), "warmup": rows.summarize(original[:8]) if not storm else None,
            "per_tenant": {str(tenant): rows.summarize([row for row in measured if uint(row["tenant"]) == tenant])
                           for tenant in range(model.tenants(selected))},
            "offered_per_second": None if duration == 0 else str(Decimal(len(measured)) * 10**9 / duration),
            "released_per_second": None if duration == 0 else str(Decimal(sum(row["outcome"] == "released" for row in measured)) * 10**9 / duration),
            "scheduler_rejected": str(monotonic["rejected"]),
            "observed_backlog": any(uint(item["scheduler"]["queue_depth"]) > 0 for item in checkpoints),
            "checkpoints": checkpoints, "frame": value["frame"],
            "work": indexed["cancel-after"]["work"] if storm and selected["mode"] == "normal" else None}
