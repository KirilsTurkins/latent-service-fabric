"""Reconstruct lookup work and bind both emitted events to immutable inputs."""
from tools.optimization_evidence.common import decode, fields, integer, require, sha256, uint
from . import model

IDENTITY = "process_id plan_sha256 identity_sha256 trace_sha256 thread_identity observation_hold_millis"
CACHE_FIELDS = ("entries source_bytes maximum_entries maximum_source_bytes metadata_bytes maximum_metadata_bytes "
                "compiled_image_bytes maximum_compiled_image_bytes preparing maximum_concurrent_preparations "
                "preparing_source_bytes preparing_metadata_bytes hits misses evictions invalidations")


def task(value, process_id):
    fields(value, "process_id thread_id start_time_ticks")
    require(value["process_id"] == process_id, "lookup-crossed-thread-process")
    integer(value["thread_id"], 1, 2**31 - 1)
    integer(value["start_time_ticks"], 1, 2**64 - 1)


def snapshot(value, capacity, hits):
    fields(value, CACHE_FIELDS)
    for item in value.values():
        integer(item, 0, 2**64 - 1)
    expected = {name: 0 for name in CACHE_FIELDS.split()}
    expected.update(entries=capacity, maximum_entries=capacity, source_bytes=capacity * 2,
                    maximum_source_bytes=capacity * 2, metadata_bytes=capacity * 3,
                    maximum_metadata_bytes=capacity * 3, compiled_image_bytes=capacity * 4,
                    maximum_compiled_image_bytes=capacity * 4, maximum_concurrent_preparations=1,
                    hits=hits, misses=capacity)
    require(value == expected, "lookup-cache-state-does-not-match-work")


def parse(record, selected, artifacts):
    ready, result = (artifacts.json(record[key], 65536) for key in ("ready", "result"))
    fields(ready, "schema event " + IDENTITY)
    fields(result, "schema event " + IDENTITY + " outcome warmup_hits measured_hits elapsed_nanos cpu coarse_thread_cpu "
           "before after checksum expected_checksum all_tags_verified trace_bytes")
    require(ready["schema"] == "latent.optimization.cache-lookup-ready.v1" and ready["event"] == "ready"
            and result["schema"] == "latent.optimization.cache-lookup-result.v1"
            and result["event"] == "measurement-complete" and result["outcome"] == "passed", "lookup-event-schema-or-status")
    trace, checksum = model.trace(selected)
    require(artifacts.path(record["trace"]).read_bytes() == trace, "lookup-trace-does-not-match-plan")
    expected = {"process_id": record["probe_process"]["process_id"], "plan_sha256": record["plan"]["sha256"].removeprefix("sha256:"),
                "identity_sha256": record["identity"]["sha256"].removeprefix("sha256:"),
                "trace_sha256": sha256(trace).removeprefix("sha256:"), "observation_hold_millis": 100}
    require(all(ready[key] == result[key] == value for key, value in expected.items()), "lookup-event-input-association")
    require(ready["thread_identity"] == result["thread_identity"], "lookup-event-thread-changed")
    task(result["thread_identity"], result["process_id"])
    require(result["warmup_hits"] == selected["warmup_hits"] and type(result["warmup_hits"]) is int
            and result["measured_hits"] == selected["measured_hits"] and type(result["measured_hits"]) is int
            and result["checksum"] == result["expected_checksum"] == str(checksum)
            and result["all_tags_verified"] is True and result["trace_bytes"] == str(len(trace)), "lookup-work-or-output-mismatch")
    require(0 < uint(result["elapsed_nanos"]) <= 180 * 10**9, "lookup-timed-bound")
    snapshot(result["before"], selected["capacity"], selected["warmup_hits"])
    snapshot(result["after"], selected["capacity"], selected["warmup_hits"] + selected["measured_hits"])
    cpu = fields(result["cpu"], "clock resolution_nanos before_nanos after_nanos")
    require(cpu["clock"] == "CLOCK_THREAD_CPUTIME_ID" and 0 < uint(cpu["resolution_nanos"]) <= 10**9
            and uint(cpu["before_nanos"]) <= uint(cpu["after_nanos"]), "lookup-invalid-thread-cpu")
    interval = fields(result["coarse_thread_cpu"], "before after")
    for row in interval.values():
        fields(row, "identity user_ticks system_ticks")
        require(row["identity"] == result["thread_identity"], "lookup-crossed-cpu-task")
        for name in ("user_ticks", "system_ticks"):
            integer(row[name], 0, 2**64 - 1)
    require(all(interval["before"][key] <= interval["after"][key] for key in ("user_ticks", "system_ticks")),
            "lookup-coarse-cpu-regressed")
    observed, size = [], 0
    with artifacts.path(record["log"]).open("rb") as stream:
        while line := stream.readline(65537):
            size += len(line)
            require(size <= 1024**2 and len(line) <= 65536 and line.endswith(b"\n"), "lookup-probe-log-bound")
            if line.startswith(b"{"):
                value = decode(line, 65536)
                if isinstance(value, dict) and "event" in value:
                    observed.append(value)
                    require(len(observed) <= 2, "lookup-extra-event")
    require(observed == [ready, result], "lookup-events-not-bound-to-log")
    return result
