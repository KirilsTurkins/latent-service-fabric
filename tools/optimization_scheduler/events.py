"""Two exact bounded events bind raw bytes to the actual owned probe."""
from pathlib import PurePosixPath
from tools.optimization_evidence.common import decode, fields, require, uint


def parse(record, plan, artifacts):
    ready, complete = (artifacts.json(record[key], 65536) for key in ("ready", "result"))
    common = "process_id plan_sha256 identity_sha256 case mode variant observation_hold_millis elapsed_nanos"
    fields(ready, "schema event " + common)
    fields(complete, "schema event outcome raw " + common)
    require(ready["schema"] == "latent.optimization.scheduler-ready.v1" and ready["event"] == "ready"
            and complete["schema"] == "latent.optimization.scheduler-complete.v1"
            and complete["event"] == "measurement-complete" and complete["outcome"] == "passed", "scheduler-event-shape")
    expected = {key: plan[key] for key in ("case", "mode", "variant", "observation_hold_millis")}
    expected.update(process_id=record["probe_process"]["process_id"], plan_sha256=record["plan"]["sha256"],
                    identity_sha256=record["identity"]["sha256"])
    require(type(ready["observation_hold_millis"]) is int and type(complete["observation_hold_millis"]) is int
            and all(ready[key] == complete[key] == value for key, value in expected.items()), "scheduler-event-input-crossed")
    fields(complete["raw"], "path sha256 bytes")
    require(complete["raw"]["path"] == "scheduler.json", "scheduler-completion-raw-name")
    relative = (PurePosixPath(record["log"]["path"]).parent / "scheduler.json").as_posix()
    require(record["raw"] == dict(complete["raw"], path=relative), "scheduler-completion-raw-crossed")
    artifacts.path(record["raw"])
    require(uint(ready["elapsed_nanos"]) + 100_000_000 <= uint(complete["elapsed_nanos"])
            <= (uint(record["finished_micros"]) - uint(record["started_micros"])) * 1000,
            "scheduler-event-hold-or-owned-clock")
    observed, size = [], 0
    with artifacts.path(record["log"]).open("rb") as stream:
        while line := stream.readline(65537):
            size += len(line)
            require(size <= 1024**2 and len(line) <= 65536 and line.endswith(b"\n"), "scheduler-probe-log-bound")
            if line.startswith(b"{"):
                value = decode(line, 65536)
                if isinstance(value, dict) and "event" in value:
                    observed.append(value)
                    require(len(observed) <= 2, "scheduler-extra-event")
    require(observed == [ready, complete], "scheduler-events-not-in-owned-log")
    return ready, complete
