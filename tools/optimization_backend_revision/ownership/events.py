"""Bind the two flushed readiness/completion events to retained raw and inputs."""
from tools.optimization_evidence.common import decode, fields, require, uint


def parse(record, plan, manifest, artifacts):
    ready, result = (artifacts.json(record[key], 65536) for key in ("ready", "result"))
    common = "process_id mode plan_sha256 identity_sha256 elapsed_nanos observation_hold_millis"
    fields(ready, "schema event fixture_manifest_sha256 " + common)
    fields(result, "schema event raw outcome " + common)
    require(ready["schema"] == "latent.optimization.ownership-ready.v1" and ready["event"] == "ready"
            and result["schema"] == "latent.optimization.ownership-complete.v1"
            and result["event"] == "measurement-complete" and result["outcome"] == "passed", "ownership-events-not-successful")
    expected = {"process_id": record["probe_process"]["process_id"], "mode": plan["mode"],
                "plan_sha256": record["plan"]["sha256"], "identity_sha256": record["identity"]["sha256"],
                "observation_hold_millis": 100}
    require(all(ready[key] == result[key] == value for key, value in expected.items())
            and ready["fixture_manifest_sha256"] == manifest["sha256"] and result["raw"] == record["raw"],
            "ownership-events-input-or-process-crossed")
    require(uint(ready["elapsed_nanos"]) + 100_000_000 <= uint(result["elapsed_nanos"])
            <= (uint(record["finished_micros"]) - uint(record["started_micros"])) * 1000,
            "ownership-ready-hold-or-process-clock")
    observed, count = [], 0
    with artifacts.path(record["log"]).open("rb") as stream:
        while line := stream.readline(65537):
            count += len(line)
            require(count <= 1024**2 and len(line) <= 65536 and line.endswith(b"\n"), "ownership-probe-log-bound")
            if line.startswith(b"{"):
                value = decode(line, 65536)
                if isinstance(value, dict) and "event" in value:
                    observed.append(value)
                    require(len(observed) <= 2, "ownership-extra-process-event")
    require(observed == [ready, result], "ownership-events-not-retained-in-owned-log")
    return ready, result
