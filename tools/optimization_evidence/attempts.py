"""Reconstruct every offered request, nominal budget and wire quantization."""

import re

from .common import OUTCOMES, counters, digest, distribution, fields, ratio, require, text, uint
from .workload import MEDIA

CONSUMPTION = ("cpu_fuel peak_memory_bytes wall_time_micros child_calls outbound_requests state_read_bytes "
               "state_write_bytes blob_read_bytes blob_write_bytes log_bytes effect_count")
PLATFORM_CODES = {
    "invalid-argument", "not-found", "already-exists", "permission-denied", "unauthenticated",
    "resource-exhausted", "deadline-exceeded", "cancelled", "unavailable", "internal",
    "state-conflict", "incompatible-contract", "corrupt-artifact", "route-unavailable",
    "dependency-failed", "guest-trap", "admission-rejected",
}
UNSENT = {"client-overload", "client-deadline-before-dispatch"}


def attempt(row, plan, phase, origin_unix_nanos, input_output, components):
    fields(row, "schema phase index batch activation_id service scheduled_nanos dispatch_nanos completed_nanos "
                "dispatch_lag_nanos request_deadline_unix_millis deadline_nanos overshoot_nanos latency_nanos "
                "outcome code semantic_match response rpc_received absolute_deadline_quantization_nanos "
                "grpc_timeout_header grpc_timeout_nanos")
    require(row["schema"] == "latent.optimization.attempt.v1" and row["phase"] == phase,
            "crossed-attempt-phase")
    index = uint(row["index"])
    count = plan[phase + "_attempts"]
    require(index < count and uint(row["batch"]) == index // plan["batch_size"], "invalid-attempt-ordinal")
    require(row["activation_id"] == f"{plan['run_id']}-{phase}-{index}"
            and row["service"] == plan["services"][index % len(plan["services"])], "crossed-attempt-identity")
    scheduled, completed = uint(row["scheduled_nanos"]), uint(row["completed_nanos"])
    require(completed >= scheduled, "completion-before-offer")
    if phase == "measured" and plan["schedule"]["mode"] == "scheduled":
        require(scheduled == index * plan["schedule"]["interval_nanos"], "changed-offered-schedule")
    expected_deadline = scheduled + plan["budget_millis"] * 1_000_000
    expected_absolute = (origin_unix_nanos + expected_deadline + 999_999) // 1_000_000
    require(uint(row["request_deadline_unix_millis"]) == expected_absolute
            and uint(row["deadline_nanos"]) == expected_deadline
            and uint(row["overshoot_nanos"]) == max(0, completed - expected_deadline)
            and uint(row["absolute_deadline_quantization_nanos"])
            == expected_absolute * 1_000_000 - origin_unix_nanos - expected_deadline,
            "changed-wire-deadline")
    require(type(row["rpc_received"]) is bool, "invalid-receipt-marker")
    require(row["outcome"] in OUTCOMES and (row["semantic_match"] is None
            or type(row["semantic_match"]) is bool), "invalid-attempt-class")
    if row["code"] is not None:
        text(row["code"], 128)
    if row["dispatch_nanos"] is None:
        require(row["dispatch_lag_nanos"] is None and row["latency_nanos"] is None
                and row["outcome"] in UNSENT and row["response"] is None
                and row["semantic_match"] is None and row["code"] is None
                and row["rpc_received"] is False and row["grpc_timeout_header"] is None
                and row["grpc_timeout_nanos"] is None,
                "fabricated-undispatched-response")
        if row["outcome"] == "client-deadline-before-dispatch":
            require(completed >= expected_deadline, "premature-client-deadline")
        return
    dispatched = uint(row["dispatch_nanos"])
    require(scheduled <= dispatched < expected_deadline and completed >= dispatched
            and uint(row["dispatch_lag_nanos"]) == dispatched - scheduled
            and uint(row["latency_nanos"]) == completed - dispatched
            and row["outcome"] not in UNSENT, "invalid-dispatch-timing")
    header = row["grpc_timeout_header"]
    require(isinstance(header, str) and re.fullmatch(r"[0-9]{1,8}[HMSmun]", header),
            "invalid-grpc-timeout-header")
    unit = {"H": 3_600_000_000_000, "M": 60_000_000_000, "S": 1_000_000_000,
            "m": 1_000_000, "u": 1000, "n": 1}[header[-1]]
    actual = int(header[:-1]) * unit
    require(uint(row["grpc_timeout_nanos"]) == actual and actual > 0
            and abs(actual - (expected_deadline - dispatched)) < unit,
            "grpc-timeout-does-not-cover-nominal-budget")
    response(row, plan, input_output, components)


def response(row, plan, output, components):
    value = row["response"]
    if value is None:
        require(row["outcome"] in {"transport-failure", "client-timeout", "invalid-response"}
                and row["semantic_match"] is None, "hidden-response")
        require(row["rpc_received"] == (row["outcome"] == "invalid-response"), "crossed-rpc-receipt-marker")
        if row["outcome"] == "transport-failure":
            require(isinstance(row["code"], str) and re.fullmatch(r"grpc-(?:[0-9]|1[0-6])", row["code"]),
                    "unbounded-transport-code")
        if row["outcome"] == "client-timeout":
            require(row["code"] == "response-observation-timeout", "invalid-client-timeout-code")
        return
    require(row["rpc_received"], "response-without-received-rpc")
    fields(value, "activation_id revision_id release_digest route_generation consumption media_type payload_sha256 payload_bytes")
    for key in ("activation_id", "revision_id", "release_digest"):
        text(value[key], 512, empty=True)
    uint(value["route_generation"])
    if value["consumption"] is not None:
        consumption = fields(value["consumption"], CONSUMPTION)
        for number in consumption.values():
            uint(number)
    if value["payload_sha256"] is not None:
        digest(value["payload_sha256"])
        require(uint(value["payload_bytes"]) <= 2 * 1024 * 1024, "oversized-response-payload")
    else:
        require(value["payload_bytes"] is None and value["media_type"] is None, "incomplete-payload-identity")
    if row["outcome"] == "invalid-response":
        # Actual malformed replies remain evidence; they never qualify as
        # successes or pass correctness merely because a report was rehashed.
        require(row["semantic_match"] is not True, "invalid-response-marked-matching")
        return
    require(value["activation_id"] == row["activation_id"]
            and (value["consumption"] is not None or plan["arm"] == "native"),
            "crossed-response-activation")
    if row["outcome"] == "success":
        require(row["code"] is None and row["semantic_match"] is True
                and value["media_type"] == MEDIA and value["payload_sha256"] == output["sha256"]
                and uint(value["payload_bytes"]) == output["bytes"], "false-semantic-success")
        if plan["arm"] == "native":
            require(value["release_digest"] == value["revision_id"] == "native-reference-v1"
                    and value["route_generation"] == "1", "native-pretends-component-execution")
            if value["consumption"] is not None:
                require(all(consumption[key] == "0" for key in consumption if key != "wall_time_micros"),
                        "native-claims-unsupported-budget-accounting")
        else:
            expected = components[row["service"]]
            require(value["release_digest"] == expected and value["revision_id"]
                    and uint(value["route_generation"]) > 0, "crossed-lsf-release")
            require(0 < uint(consumption["cpu_fuel"]) <= plan["cpu_fuel"]
                    and 0 < uint(consumption["peak_memory_bytes"]) <= plan["memory_bytes"]
                    and uint(consumption["log_bytes"]) <= plan["log_bytes"], "lsf-exceeds-granted-budget")
    elif row["outcome"] == "platform-failure":
        require(row["code"] in PLATFORM_CODES and row["semantic_match"] is None
                and value["payload_sha256"] is None, "invalid-platform-failure")
    else:
        require(row["outcome"] == "declared-error" and row["code"] == "declared-error"
                and row["semantic_match"] is None, "invalid-response-classification")


def counts(rows):
    count = len(rows)
    dispatched = sum(row["dispatch_nanos"] is not None for row in rows)
    received = sum(row["rpc_received"] for row in rows)
    successful = sum(row["outcome"] == "success" for row in rows)
    first = min((uint(row["scheduled_nanos"]) for row in rows), default=None)
    last = max((uint(row["completed_nanos"]) for row in rows), default=0)
    elapsed = last - (first or 0)
    return {
        "attempts": str(count), "dispatched": str(dispatched), "undispatched": str(count - dispatched),
        "received": str(received), "successful": str(successful),
        "semantic_mismatches": str(sum(row["semantic_match"] is False for row in rows)),
        "outcomes": {name: value for name, value in counters(rows).items() if value != "0"},
        "first_scheduled_nanos": None if first is None else str(first),
        "last_completed_nanos": str(last), "elapsed_nanos": str(elapsed),
        "throughput": {"completed_attempts": str(count), "successful_responses": str(successful),
                       "elapsed_nanos": str(elapsed)},
    }


def metrics(rows):
    elapsed = uint(counts(rows)["elapsed_nanos"])
    successful = sum(row["outcome"] == "success" for row in rows)
    budget_success = sum(row["outcome"] == "success" and row["overshoot_nanos"] == "0" for row in rows)
    latency = [uint(row["latency_nanos"]) for row in rows if row["latency_nanos"] is not None]
    return {
        "counts": counts(rows),
        "latency_nanos": distribution(latency) if latency else None,
        "dispatch_lag_nanos": distribution([uint(row["dispatch_lag_nanos"]) for row in rows
                                            if row["dispatch_lag_nanos"] is not None]) if latency else None,
        "overshoot_nanos": distribution([uint(row["overshoot_nanos"]) for row in rows]) if rows else None,
        "budget_successes": str(budget_success), "budget_misses": str(len(rows) - budget_success),
        "successes_per_second": ratio(successful * 1_000_000_000, elapsed),
        "attempts_per_second": ratio(len(rows) * 1_000_000_000, elapsed),
    }
