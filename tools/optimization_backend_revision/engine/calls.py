"""Bind each retained request, receipt, status and guest log to one fixed offer."""
import json
import re

from tools.optimization_evidence.attempts import CONSUMPTION
from tools.optimization_evidence.common import fields, integer, require, sha256, text, uint
from tools.optimization_evidence.workload import framed
from tools.phase1_paired.common import TIMINGS
from . import policy, schedule

BASE = ("kind ordinal command_ordinal phase phase_kind index activation_id target release_digest route_generation request "
        "scheduled_nanos deadline_nanos deadline_unix_millis absolute_deadline_quantization_nanos dispatch_nanos "
        "dispatch_lag_nanos grpc_timeout_header rpc_received response valid_response outcome completed_nanos overshoot_nanos "
        "timing guest_logs native_after_response diagnostic_token semantic_validated")


def blob(value, payload=None, *, response=False):
    fields(value, "utf8 sha256 bytes" + (" value media_type" if response else ""))
    raw = text(value["utf8"], 16 * 1024, empty=True).encode("utf-8")
    require(value["sha256"] == sha256(raw) and uint(value["bytes"]) == len(raw), "engine-payload-byte-identity")
    try:
        decoded = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise ValueError("engine-payload-json") from error
    require(payload is None or decoded == payload, "engine-payload-semantic-or-request-crossed")
    if response:
        require(value["media_type"] == schedule.MEDIA and value["value"] == decoded, "engine-response-projection-crossed")
    else:
        require(raw == framed(payload), "engine-request-not-canonical")
    return decoded


def validate(row, expected, ordinal, fixtures, origin, elapsed, pins):
    fields(row, BASE + (" cleanup_log" if expected["phase"] == "functional" else ""))
    require(row["kind"] == "invoke" and row["ordinal"] == str(ordinal)
            and all(row[name] == expected[name] for name in ("phase", "phase_kind", "activation_id"))
            and row["index"] == str(expected["index"]), "engine-offer-population-crossed")
    integer(uint(row["command_ordinal"]), 1, 1609)
    fixture = fixtures[expected["target_index"]]
    target = {**{key: fixture["target"][key] for key in ("tenant", "service", "contract")}, "function": expected["function"]}
    release = fixture["target"]["release_digest"]
    require(row["target"] == target and row["release_digest"] == release and row["route_generation"] == "8", "engine-offer-target-crossed")
    request = fields(row["request"], "payload budget root parent metadata")
    marker = "a" if target["tenant"] == "engine-a" else "b"
    require(request["budget"] == expected["budget"] and request["root"] == f"engine-root-{marker}"
            and request["parent"] == f"engine-parent-{marker}"
            and request["metadata"] == {"guest.marker": marker, "internal.secret": f"private-{marker}"}, "engine-request-context-crossed")
    blob(request["payload"], expected["payload"])
    scheduled, dispatch, completed, deadline = (uint(row[key]) for key in
                                               ("scheduled_nanos", "dispatch_nanos", "completed_nanos", "deadline_nanos"))
    require(0 <= scheduled <= dispatch <= completed <= elapsed and deadline == scheduled + 5_000_000_000
            and dispatch < deadline and uint(row["dispatch_lag_nanos"]) == dispatch - scheduled
            and uint(row["overshoot_nanos"]) == max(0, completed - deadline), "engine-offer-clock-crossed")
    absolute = (origin + deadline + 999_999) // 1_000_000
    require(uint(row["deadline_unix_millis"]) == absolute
            and uint(row["absolute_deadline_quantization_nanos"]) == absolute * 1_000_000 - origin - deadline,
            "engine-outer-deadline-crossed")
    header = row["grpc_timeout_header"]
    require(isinstance(header, str) and re.fullmatch(r"[0-9]{1,8}[HMSmun]", header), "engine-timeout-header")
    unit = {"H": 3_600_000_000_000, "M": 60_000_000_000, "S": 1_000_000_000, "m": 1_000_000, "u": 1000, "n": 1}[header[-1]]
    require(0 <= deadline - dispatch - int(header[:-1]) * unit < unit, "engine-timeout-not-remaining-outer-budget")
    require(row["rpc_received"] is True and row["valid_response"] is True and row["semantic_validated"] is True
            and row["outcome"] == ("success" if expected["code"] is None else "platform-failure"), "engine-qualified-offer-not-semantic")
    response = fields(row["response"], "activation_id release_digest revision_id route_generation code details payload consumption")
    require(response["activation_id"] == row["activation_id"] and response["release_digest"] == release
            and response["route_generation"] == "8" and response["code"] == expected["code"], "engine-response-target-or-code-crossed")
    revision = text(response["revision_id"], 512)
    require(re.fullmatch(r"revision-v1:sha256:[0-9a-f]{64}", revision), "engine-revision-id")
    prior = pins.setdefault(expected["target_index"], revision)
    require(prior == revision, "engine-pinned-revision-changed")
    if expected["code"] is None:
        require(response["details"] is None, "engine-success-with-failure-details")
        output = blob(response["payload"], expected["output"], response=True)
    else:
        require(response["payload"] is None and isinstance(response["details"], list) and len(response["details"]) <= 16,
                "engine-failure-payload-or-details")
        for detail in response["details"]:
            fields(detail, "kind fields")
            text(detail["kind"], 256)
            require(isinstance(detail["fields"], dict) and len(detail["fields"]) <= 64, "engine-detail-field-bound")
        output = None
    consumption = fields(response["consumption"], CONSUMPTION)
    numbers = {name: uint(item) for name, item in consumption.items()}
    require(0 < numbers["cpu_fuel"] <= uint(expected["budget"]["cpu_fuel"])
            and 0 < numbers["peak_memory_bytes"] <= uint(expected["budget"]["memory_bytes"])
            and numbers["log_bytes"] <= uint(expected["budget"]["log_bytes"])
            and all(numbers[name] == 0 for name in numbers if name not in ("cpu_fuel", "peak_memory_bytes", "wall_time_micros", "log_bytes")),
            "engine-consumption-outside-grant")
    timing = fields(row["timing"], " ".join(TIMINGS))
    measured = {name: uint(item) for name, item in timing.items()}
    require(measured["host_call_micros"] <= measured["guest_call_micros"]
            and measured["backend_total_micros"] * 1000 <= completed - dispatch + 1000, "engine-backend-clock-outside-rpc")
    policy.native(row["native_after_response"])
    logs = guest_logs(row["guest_logs"], row)
    require(sum(uint(item["encoded_bytes"]) for item in logs) == numbers["log_bytes"], "engine-log-accounting-crossed")
    if expected["phase"] != "functional":
        require(row["diagnostic_token"] is None, "engine-diagnostic-enabled-in-performance-population")
    else:
        uint(row["diagnostic_token"])
        released(row["cleanup_log"], row)
    return {"row": row, "expected": expected, "output": output, "latency_nanos": completed - dispatch,
            "all_offered_nanos": completed - scheduled, "timing": measured, "consumption": numbers}


def guest_logs(values, row):
    require(isinstance(values, list) and len(values) <= 2, "engine-guest-log-count")
    for value in values:
        fields(value, "record encoded_bytes sha256")
        record = fields(value["record"], "activation_id level message fields")
        require(record["activation_id"] == row["activation_id"], "engine-guest-log-identity")
        # CapturedLog's declared serde order; its Metadata is a BTreeMap.
        encoded = framed({"activation_id": record["activation_id"], "level": record["level"],
                          "message": record["message"], "fields": dict(sorted(record["fields"].items()))})
        require(value["sha256"] == sha256(encoded) and uint(value["encoded_bytes"]) == len(encoded), "engine-guest-log-byte-binding")
        attrs = record.get("fields")
        require(isinstance(attrs, dict) and attrs.get("latent.activation_id") == row["activation_id"]
                and re.fullmatch(r"[0-9a-f]{32}", attrs.get("latent.trace_id", ""))
                and re.fullmatch(r"[0-9a-f]{16}", attrs.get("latent.span_id", "")), "engine-guest-log-context-crossed")
    return values


def released(value, row):
    fields(value, "body attributes observed_at_unix_millis")
    attrs = value["attributes"]
    require(isinstance(attrs, dict) and attrs.get("activation_id") == row["activation_id"]
            and attrs.get("stage") == "cleanup" and attrs.get("cleanup") == "released"
            and attrs.get("revision") == row["response"]["revision_id"], "engine-cleanup-not-pinned-reusable")
    text(value["body"], 4096)
    uint(value["observed_at_unix_millis"])


def status(command, call, elapsed):
    row = call["row"]
    response = command["response"]
    fields(response, "grpc_code activation_id phase terminal_state outcome code metadata consumption")
    require(command["target"] == row["activation_id"] and command["tenant"] == row["target"]["tenant"]
            and uint(row["completed_nanos"]) <= uint(command["started_nanos"]) <= uint(command["finished_nanos"]) <= elapsed,
            "engine-status-before-response-or-crossed")
    expected_state = "completed" if row["response"]["code"] is None else row["response"]["code"].replace("-", "_")
    require(response["grpc_code"] == 0 and response["activation_id"] == row["activation_id"]
            and response["outcome"] == row["outcome"] and response["code"] == row["response"]["code"]
            and response["terminal_state"] == expected_state and response["consumption"] == row["response"]["consumption"],
            "engine-status-response-disagrees")
    metadata = response["metadata"]
    require(isinstance(metadata, dict) and all(metadata.get(key) == item for key, item in
            (("release", row["release_digest"]), ("revision", row["response"]["revision_id"]), ("route-generation", "8"))),
            "engine-status-release-crossed")
    return response
