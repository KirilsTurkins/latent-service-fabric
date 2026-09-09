"""Actual client drop is distinct from an RPC response reporting cancellation."""
import re

from tools.optimization_evidence import attempts as common
from tools.optimization_evidence.common import fields, require, sha256, uint
from ..budget.attempts import payload
from .model import offers

BASE = ("kind ordinal case budget_millis transport_budget_millis function activation_id release_digest scheduled_nanos deadline_nanos "
        "deadline_unix_millis absolute_deadline_quantization_nanos request_payload expected_payload diagnostic_token "
        "body_gate rpc_received response dispatch_nanos dispatch_lag_nanos grpc_timeout_header outcome completed_nanos overshoot_nanos")
RECOVERY = ("round running_witness running_witness_final disconnect disconnect_scheduled_nanos cancel_response "
            "acknowledgement retained_status retained_observed_nanos cleanup_log")


def round_number(index):
    return (index - 1) // 16 if 1 <= index <= 48 else (index - 49) // 2 if 49 <= index <= 58 else 0


def validate(row, origin, release):
    fields(row, BASE + " " + RECOVERY, "valid_response grpc_code")
    index = uint(row["ordinal"])
    require(row["kind"] == "invoke" and index < 61, "recovery-offer-ordinal")
    case, budget, function = offers()[index]
    require(row["case"] == case and row["budget_millis"] == row["transport_budget_millis"] == str(budget)
            and row["function"] == function and row["round"] == str(round_number(index))
            and row["activation_id"] == f"budget-{index:02}-{case}-{budget}"
            and row["release_digest"] == release, "recovery-offer-or-original-envelope-changed")
    require(row["request_payload"] == payload(b"[]") and row["body_gate"] is None
            and row["expected_payload"] == (payload(b"[11]") if function == "identify" else None), "recovery-generic-payload")
    scheduled, dispatch, completed = (uint(row[name]) for name in ("scheduled_nanos", "dispatch_nanos", "completed_nanos"))
    deadline = scheduled + budget * 1_000_000
    absolute = (origin + deadline + 999_999) // 1_000_000
    require(scheduled <= dispatch < deadline and dispatch <= completed
            and uint(row["deadline_nanos"]) == deadline and uint(row["deadline_unix_millis"]) == absolute
            and uint(row["absolute_deadline_quantization_nanos"]) == absolute * 1_000_000 - origin - deadline
            and uint(row["overshoot_nanos"]) == max(0, completed - deadline)
            and uint(row["dispatch_lag_nanos"]) == dispatch - scheduled, "recovery-request-clock-or-deadline")
    header = row["grpc_timeout_header"]
    require(isinstance(header, str) and re.fullmatch(r"[0-9]{1,8}[HMSmun]", header), "recovery-grpc-timeout-header")
    unit = {"H": 3_600_000_000_000, "M": 60_000_000_000, "S": 1_000_000_000,
            "m": 1_000_000, "u": 1000, "n": 1}[header[-1]]
    actual = int(header[:-1]) * unit
    require(actual > 0 and abs(actual - (deadline - dispatch)) < unit, "recovery-grpc-budget-changed")
    outcome = row["outcome"]
    require(outcome in ("success", "platform-failure", "transport-failure", "client-disconnected")
            and type(row["rpc_received"]) is bool, "recovery-offer-outcome")
    normalized = {"activation_id": row["activation_id"], "service": "measurement-generic",
                  "scheduled_nanos": row["scheduled_nanos"], "dispatch_nanos": row["dispatch_nanos"],
                  "dispatch_lag_nanos": row["dispatch_lag_nanos"], "completed_nanos": row["completed_nanos"],
                  "latency_nanos": str(completed - dispatch), "overshoot_nanos": row["overshoot_nanos"],
                  "outcome": outcome, "rpc_received": row["rpc_received"], "semantic_match": None,
                  "response": None, "code": None}
    response = row["response"]
    if response is not None:
        fields(response, "activation_id release_digest revision_id route_generation code payload consumption")
        require(row.get("valid_response") is True, "recovery-invalid-rpc-response")
        normalized["response"] = {name: response[name] for name in (
            "activation_id", "release_digest", "revision_id", "route_generation", "consumption")}
        output = response["payload"]
        if output is not None:
            fields(output, "sha256 bytes media_type")
        normalized["response"].update(media_type=output["media_type"] if output else None,
            payload_sha256=output["sha256"] if output else None, payload_bytes=output["bytes"] if output else None)
        normalized["code"] = response["code"]
        if outcome == "success":
            require(function == "identify", "recovery-spin-claimed-semantic-success")
            normalized["semantic_match"] = True
    elif outcome == "transport-failure":
        require(type(row.get("grpc_code")) is int, "recovery-transport-code-unobserved")
        normalized["code"] = "grpc-" + str(row["grpc_code"])
    if outcome == "client-disconnected":
        require(response is None and row["rpc_received"] is False and row.get("valid_response") is False
                and "grpc_code" not in row, "recovery-drop-fabricates-rpc-response")
    else:
        common.response(normalized, {"arm": "lsf", "cpu_fuel": 10_000_000_000,
            "memory_bytes": 67_108_864, "log_bytes": 16384},
            {"sha256": sha256(b"[11]"), "bytes": 4}, {"measurement-generic": release})
    disconnect(row, case, scheduled, dispatch, completed, outcome)
    return normalized


def disconnect(row, case, scheduled, dispatch, completed, outcome):
    target = scheduled + uint(row["budget_millis"]) * 500_000 if case == "disconnect" else None
    require(row["disconnect_scheduled_nanos"] == (None if target is None else str(target)), "recovery-disconnect-target")
    value = row["disconnect"]
    if value is None:
        require(outcome != "client-disconnected", "recovery-disconnect-without-joined-client")
        return
    fields(value, "requested_nanos joined_nanos aborted")
    requested, joined = uint(value["requested_nanos"]), uint(value["joined_nanos"])
    require(case in ("disconnect", "running-disconnect") and dispatch <= requested <= joined <= completed
            and (target is None or target <= requested) and type(value["aborted"]) is bool
            and value["aborted"] == (outcome == "client-disconnected"), "recovery-client-drop-not-actual-or-joined")
