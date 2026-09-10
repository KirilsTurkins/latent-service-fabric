"""Bind actual log events to the selected child, immutable inputs and raw bytes."""
from tools.optimization_evidence.common import decode, fields, require, uint


def parse(record, artifacts, owner, raw):
    events, total = [], 0
    with artifacts.path(record["log"]).open("rb") as source:
        while line := source.readline(65537):
            total += len(line)
            require(total <= 1024**2 and len(line) <= 65536 and line.endswith(b"\n"), "catalog-event-log-bound")
            if line.startswith(b"{"):
                value = decode(line, 65536)
                if isinstance(value, dict) and "event" in value:
                    events.append(value)
                    require(len(events) <= 2, "catalog-extra-event")
    require(len(events) == 2, "catalog-event-population")
    ready, result = events
    common = "schema event process_id mode plan_sha256 identity_sha256 elapsed_nanos observation_hold_millis"
    fields(ready, common)
    fields(result, common + " raw outcome")
    require(ready["schema"] == "latent.optimization.catalog-ready.v1" and ready["event"] == "ready"
            and result["schema"] == "latent.optimization.catalog-complete.v1" and result["event"] == "measurement-complete"
            and result["outcome"] == "passed", "catalog-event-status")
    expected = {"process_id": owner[0], "mode": record["mode"], "plan_sha256": record["plan"]["sha256"],
                "identity_sha256": record["identity"]["sha256"], "observation_hold_millis": 100}
    require(all(ready[key] == result[key] == value for key, value in expected.items())
            and type(ready["process_id"]) is type(result["process_id"]) is int and result["raw"] == record["raw"],
            "catalog-event-input-association")
    require(uint(ready["elapsed_nanos"]) + 100_000_000 <= uint(raw["before_node_memory"]["collector_started_nanos"])
            and uint(raw["elapsed_nanos"]) <= uint(result["elapsed_nanos"]), "catalog-event-clock-boundary")
    if record["mode"] == "allocation":
        require(artifacts.json(record["ready"]) == ready and artifacts.json(record["result"]) == result,
                "catalog-event-retained-sidecars")
    else:
        require(record["ready"] is record["result"] is None, "catalog-normal-fabricated-probe-sidecars")
    return ready, result
