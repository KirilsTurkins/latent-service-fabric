"""Actual inventory counter witnesses outside timed client phases."""
from tools.optimization_evidence.common import fields, require, uint

INTERVAL = "before-warmup-through-after-measured-includes-node-get-observation"
COUNTERS = ("hits", "misses", "evictions", "invalidations")


def validate(value, artifacts, owner, plan, case, run_start, run_finish, prior):
    fields(value, "server_process_id start_time_ticks endpoint interval started_micros finished_micros before after")
    require((value["server_process_id"], value["start_time_ticks"]) == owner
            and value["endpoint"] == plan["endpoint"] and value["interval"] == INTERVAL,
            "crossed-cache-observation-owner")
    start, finish = uint(value["started_micros"]), uint(value["finished_micros"])
    require(run_start <= prior <= start <= finish <= run_finish, "overlapping-cache-observation-window")
    summaries = {}
    for phase in ("before", "after"):
        response = artifacts.json(value[phase])
        require(response.get("schemaVersion") == "latent.cli.result.v1" and response.get("command") == "node get"
                and response.get("category") == "success" and response.get("error") is None
                and response.get("requestDispatched") is True and response.get("outcomeKnown") is True,
                "invalid-cache-inventory-response")
        inventory = response["data"]["inventory"]
        require(inventory["node"]["id"] == "optimization-node"
                and inventory["node"]["endpoint"].removeprefix("http://") == value["endpoint"].removeprefix("http://"),
                "crossed-cache-node-endpoint")
        cache = inventory["cacheSummary"]
        fields(cache, "available entries maximumEntries sourceBytes maximumSourceBytes metadataBytes maximumMetadataBytes "
                     "compiledImageBytes maximumCompiledImageBytes preparing maximumConcurrentPreparations preparingSourceBytes "
                     "preparingMetadataBytes hits misses evictions invalidations")
        require(cache["available"] is True and uint(cache["maximumEntries"]) == 4
                and uint(cache["entries"]) <= 4 and uint(cache["preparing"]) == 0, "cache-unavailable-or-unbounded")
        for key, item in cache.items():
            if key != "available":
                uint(item)
        cells = inventory["cellCapacity"]
        require(isinstance(cells, list) and len(cells) == 1 and cells[0]["total"] == 4
                and uint(inventory["queueDepth"]) == 0
                and cells[0]["active"] == cells[0]["queueDepth"] == 0,
                "cache-sampled-with-active-work")
        for actual, maximum in (("entries", "maximumEntries"), ("sourceBytes", "maximumSourceBytes"),
                                ("metadataBytes", "maximumMetadataBytes"), ("compiledImageBytes", "maximumCompiledImageBytes")):
            require(uint(cache[actual]) <= uint(cache[maximum]), "cache-accounting-exceeds-limit")
        summaries[phase] = cache
    delta = {}
    for name in COUNTERS:
        before, after = (uint(summaries[phase][name]) for phase in ("before", "after"))
        require(after >= before, "cache-counter-regressed")
        delta[name] = str(after - before)
    if case == "cache-mixed":
        require(uint(delta["hits"]) > 0 and uint(delta["misses"]) > 0, "mixed-cache-not-observed")
    if case == "cache-working-set":
        require(uint(delta["misses"]) > 0, "cache-refill-not-observed")
    return {"interval": INTERVAL, "before": summaries["before"], "after": summaries["after"], "delta": delta}, finish
