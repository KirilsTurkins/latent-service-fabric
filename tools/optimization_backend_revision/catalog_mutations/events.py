"""Bind both actual collector events to the child and retained input hashes."""
from tools.optimization_evidence.common import decode, fields, require, uint
from . import model


def parse(record, artifacts, owner, raw):
    events, total = [], 0
    with artifacts.path(record["log"]).open("rb") as source:
        while line := source.readline(65537):
            total += len(line)
            require(total <= model.MAX_LOG_BYTES and len(line) <= 65536 and line.endswith(b"\n"),
                    "catalog-mutation-event-log-bound")
            if line.startswith(b"{"):
                value = decode(line, 65536)
                if isinstance(value, dict) and "event" in value:
                    events.append(value)
                    require(len(events) <= 2, "catalog-mutation-extra-event")
    require(len(events) == 2, "catalog-mutation-event-population")
    ready, result = events
    common = "schema event process_id mode plan_sha256 identity_sha256 elapsed_nanos observation_hold_millis"
    fields(ready, common)
    fields(result, common + " raw outcome")
    require(ready["schema"] == "latent.optimization.catalog-mutation-ready.v1" and ready["event"] == "ready"
            and result["schema"] == "latent.optimization.catalog-mutation-complete.v1"
            and result["event"] == "measurement-complete" and result["outcome"] == "passed",
            "catalog-mutation-event-status")
    expected = {"process_id": owner[0], "mode": record["mode"], "plan_sha256": record["plan"]["sha256"],
                "identity_sha256": record["identity"]["sha256"], "observation_hold_millis": 100}
    require(all(ready[key] == result[key] == value for key, value in expected.items())
            and type(ready["process_id"]) is type(result["process_id"]) is int
            and result["raw"] == record["raw"], "catalog-mutation-event-input-association")
    require(uint(ready["elapsed_nanos"]) + 100_000_000 <= uint(raw["before_node_memory"]["collector_started_nanos"])
            and uint(raw["elapsed_nanos"]) <= uint(result["elapsed_nanos"]), "catalog-mutation-event-clock")
    if model.profiled(record["mode"]):
        require(artifacts.json(record["ready"]) == ready and artifacts.json(record["result"]) == result,
                "catalog-mutation-profile-event-sidecars")
    else:
        require(record["ready"] is record["result"] is None, "catalog-mutation-unexpected-event-sidecars")
    return ready, result
