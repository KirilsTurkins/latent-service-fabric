"""Two bounded flushed events bind the retained codec document to its owned process."""
from tools.optimization_evidence.common import decode, fields, require, uint


def parse(record, plan, artifacts):
    ready, complete = (artifacts.json(record[key], 65536) for key in ("ready", "result"))
    common = "process_id plan_sha256 identity_sha256 family mode repetition variant thread_identity observation_hold_millis elapsed_nanos"
    fields(ready, "schema event " + common)
    fields(complete, "schema event outcome raw " + common)
    require(ready["schema"] == "latent.optimization.codec-ready.v1" and ready["event"] == "ready"
            and complete["schema"] == "latent.optimization.codec-complete.v1"
            and complete["event"] == "measurement-complete" and complete["outcome"] == "passed", "codec-process-event-shape")
    expected = {key: plan[key] for key in ("family", "mode", "repetition", "variant", "observation_hold_millis")}
    expected.update(process_id=record["probe_process"]["process_id"], plan_sha256=record["plan"]["sha256"],
                    identity_sha256=record["identity"]["sha256"])
    require(all(ready[key] == complete[key] == value for key, value in expected.items()), "codec-event-input-crossed")
    parent = artifacts.path(record["raw"]).parent
    require(complete["raw"]["path"] == "codec.json" and artifacts.nested(parent, complete["raw"]) == artifacts.path(record["raw"]),
            "codec-completion-raw-crossed")
    require(uint(ready["elapsed_nanos"]) + 100_000_000 <= uint(complete["elapsed_nanos"])
            <= (uint(record["finished_micros"]) - uint(record["started_micros"])) * 1000, "codec-ready-hold-or-owned-clock")
    observed, size = [], 0
    with artifacts.path(record["log"]).open("rb") as stream:
        while line := stream.readline(65537):
            size += len(line)
            require(size <= 1024**2 and len(line) <= 65536 and line.endswith(b"\n"), "codec-probe-log-bound")
            if line.startswith(b"{"):
                value = decode(line, 65536)
                if isinstance(value, dict) and "event" in value:
                    observed.append(value)
                    require(len(observed) <= 2, "codec-extra-process-event")
    require(observed == [ready, complete], "codec-events-not-in-owned-log")
    return ready, complete
