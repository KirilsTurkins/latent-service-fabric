"""Bind fixed codec bytes, semantic preflight and actual same-task batch clocks."""
from tools.optimization_cache_lookup.events import task
from tools.optimization_evidence.common import fields, integer, require, uint
from . import model
from .fixtures import fixtures


DIRECTION_FIELDS = ("direction warmup_attempted warmup_completed warmup_successes measured_attempted measured_completed "
                    "measured_successes started_nanos finished_nanos elapsed_nanos cpu coarse_thread_cpu "
                    "observed_arity_or_bytes failure")


def direction(value, selected, process_id, identity, expected, previous, elapsed):
    fields(value, DIRECTION_FIELDS)
    require(value["direction"] in ("decode", "encode"), "codec-direction")
    for phase, count in (("warmup", selected["warmup_iterations"]), ("measured", selected["measured_iterations"])):
        require(all(uint(value[phase + "_" + key]) == count for key in ("attempted", "completed", "successes")),
                "codec-incomplete-or-failed-operations")
    require(value["failure"] is None and uint(value["observed_arity_or_bytes"]) == expected * selected["measured_iterations"],
            "codec-measured-shape-or-outcome-crossed")
    start, finish = uint(value["started_nanos"]), uint(value["finished_nanos"])
    require(previous <= start < finish <= elapsed and uint(value["elapsed_nanos"]) == finish - start,
            "codec-batch-clock-or-order")
    cpu = fields(value["cpu"], "clock resolution_nanos before_nanos after_nanos")
    require(cpu["clock"] == "CLOCK_THREAD_CPUTIME_ID" and 0 < uint(cpu["resolution_nanos"]) <= 10**9
            and uint(cpu["before_nanos"]) <= uint(cpu["after_nanos"]), "codec-thread-cpu-clock")
    interval = fields(value["coarse_thread_cpu"], "before after")
    for sample in interval.values():
        fields(sample, "identity user_ticks system_ticks")
        require(sample["identity"] == identity, "codec-crossed-cpu-task")
        task(sample["identity"], process_id)
        for key in ("user_ticks", "system_ticks"):
            integer(sample[key], 0, 2**64 - 1)
    require(all(interval["before"][key] <= interval["after"][key] for key in ("user_ticks", "system_ticks")),
            "codec-coarse-thread-cpu-regressed")
    return finish


def parse(raw, selected, supplied, record, artifacts, type_fixture, ready, complete):
    fields(raw, "schema plan identity process_id thread_identity plan_sha256 identity_sha256 input expected_output type_fixture "
           "limits preflight directions types_dropped guest_stores invokes elapsed_nanos outcome")
    require(raw["schema"] == "latent.optimization.codec-arm.v1" and raw["plan"] == selected and raw["identity"] == supplied,
            "codec-raw-plan-or-identity-crossed")
    require(raw["plan_sha256"] == record["plan"]["sha256"] and raw["identity_sha256"] == record["identity"]["sha256"],
            "codec-raw-input-hash-crossed")
    process_id = integer(raw["process_id"], 1, 2**31 - 1)
    require(process_id == record["probe_process"]["process_id"] and raw["thread_identity"] == ready["thread_identity"]
            == complete["thread_identity"], "codec-raw-process-or-task-crossed")
    task(raw["thread_identity"], process_id)
    expected_fixture = {key: type_fixture[key] for key in ("sha256", "bytes")}
    require(raw["type_fixture"] == expected_fixture, "codec-type-fixture-crossed")
    require(raw["limits"] == {key: str(value) for key, value in model.LIMITS.items()}, "codec-value-limits-changed")
    source, output, arity = fixtures()[selected["family"]]
    parent = artifacts.path(record["raw"]).parent
    for key, name, expected in (("input", "input.json", source), ("expected_output", "expected-output.json", output)):
        require(raw[key]["path"] == name, "codec-fixture-path-changed")
        require(artifacts.nested(parent, raw[key]).read_bytes() == expected, "codec-input-or-canonical-output-changed")
    preflight = fields(raw["preflight"], "started_nanos finished_nanos decode_path legacy_equivalent canonical_output_matches "
                       "decoded_arity encoded_bytes decode_calls encode_calls")
    begin, end, elapsed = uint(preflight["started_nanos"]), uint(preflight["finished_nanos"]), uint(raw["elapsed_nanos"])
    require(begin <= end <= uint(ready["elapsed_nanos"]) < elapsed <= uint(complete["elapsed_nanos"]),
            "codec-preflight-or-completion-clock")
    require(preflight["legacy_equivalent"] is True and preflight["canonical_output_matches"] is True
            and uint(preflight["decoded_arity"]) == arity and uint(preflight["encoded_bytes"]) == len(output)
            and uint(preflight["decode_calls"]) == uint(preflight["encode_calls"]) == 3,
            "codec-semantic-preflight-incomplete")
    expected_path = "legacy-only" if selected["variant"] == "control" else "typed-success"
    require(preflight["decode_path"] == expected_path, "codec-success-path-crossed")
    require(isinstance(raw["directions"], list) and [item.get("direction") for item in raw["directions"]] == ["decode", "encode"],
            "codec-direction-population")
    previous = uint(ready["elapsed_nanos"]) + 100_000_000
    previous_cpu, previous_coarse = None, None
    for row, expected in zip(raw["directions"], (arity, len(output)), strict=True):
        previous = direction(row, selected, process_id, raw["thread_identity"], expected, previous, elapsed)
        if previous_cpu is not None:
            require(uint(row["cpu"]["before_nanos"]) >= previous_cpu,
                    "codec-between-direction-cpu-regressed")
            require(all(row["coarse_thread_cpu"]["before"][key] >= previous_coarse[key]
                        for key in ("user_ticks", "system_ticks")),
                    "codec-between-direction-coarse-cpu-regressed")
        previous_cpu = uint(row["cpu"]["after_nanos"])
        previous_coarse = row["coarse_thread_cpu"]["after"]
    require(raw["types_dropped"] is True and raw["guest_stores"] == raw["invokes"] == "0" and raw["outcome"] == "passed",
            "codec-type-owner-or-no-guest-boundary")
    return {"process_id": process_id, "thread_identity": raw["thread_identity"], "preflight": preflight,
            "directions": raw["directions"], "elapsed_nanos": str(elapsed), "types_dropped": True,
            "validated_preflight_operations": "6", "validated_warmup_operations": str(2 * selected["warmup_iterations"]),
            "validated_measured_operations": str(2 * selected["measured_iterations"]),
            "validated_codec_operations": str(6 + 2 * (selected["warmup_iterations"] + selected["measured_iterations"]))}
