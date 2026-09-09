"""Validate each actual generic request using the unchanged client wire rules."""
import re

from tools.optimization_evidence import attempts as common
from tools.optimization_evidence.common import fields, require, sha256, uint
from tools.optimization_evidence.workload import MEDIA
from . import model


def payload(data):
    return {"sha256": sha256(data), "bytes": str(len(data)), "media_type": MEDIA}


def validate(row, origin, release):
    fields(row, "kind ordinal case budget_millis transport_budget_millis function activation_id release_digest scheduled_nanos deadline_nanos "
           "deadline_unix_millis absolute_deadline_quantization_nanos request_payload expected_payload diagnostic_token "
           "body_gate rpc_received response dispatch_nanos dispatch_lag_nanos grpc_timeout_header outcome completed_nanos overshoot_nanos",
           "valid_response grpc_code retained_status retained_observed_nanos retained_valid queue_witness")
    index = uint(row["ordinal"])
    require(row["kind"] == "invoke" and index < 23, "budget-lifecycle-offer-ordinal")
    case, budget, function = model.offers()[index]
    require(row["case"] == case and row["budget_millis"] == str(budget) and row["function"] == function
            and row["activation_id"] == f"budget-{index:02}-{case}-{budget}" and row["release_digest"] == release,
            "budget-lifecycle-offer-population-changed")
    transport_budget = model.transport_budget(case, budget)
    require(row["transport_budget_millis"] == str(transport_budget), "budget-lifecycle-transport-boundary-changed")
    require(row["request_payload"] == payload(b"[]")
            and row["expected_payload"] == (payload(b"[11]") if function == "identify" else None), "budget-generic-payload-changed")
    normalized = {"schema": "latent.optimization.attempt.v1", "phase": "measured", "index": "0", "batch": "0",
                  "activation_id": row["activation_id"], "service": "measurement-generic",
                  "request_deadline_unix_millis": row["deadline_unix_millis"], "latency_nanos": None,
                  "grpc_timeout_nanos": None, "code": None, "semantic_match": None, "response": None}
    for name in ("scheduled_nanos", "dispatch_nanos", "completed_nanos", "dispatch_lag_nanos", "deadline_nanos",
                 "overshoot_nanos", "outcome", "rpc_received", "absolute_deadline_quantization_nanos", "grpc_timeout_header"):
        normalized[name] = row[name]
    require(row["dispatch_nanos"] is not None and row["outcome"] in ("success", "platform-failure", "transport-failure"),
            "budget-diagnostic-offer-not-actually-dispatched")
    normalized["latency_nanos"] = str(uint(row["completed_nanos"]) - uint(row["dispatch_nanos"]))
    header = row["grpc_timeout_header"]
    require(isinstance(header, str) and re.fullmatch(r"[0-9]{1,8}[HMSmun]", header), "budget-diagnostic-grpc-header")
    units = {"H": 3_600_000_000_000, "M": 60_000_000_000, "S": 1_000_000_000, "m": 1_000_000, "u": 1000, "n": 1}
    normalized["grpc_timeout_nanos"] = str(int(header[:-1]) * units[header[-1]])
    response = row["response"]
    if response is not None:
        fields(response, "activation_id release_digest revision_id route_generation code payload consumption")
        require(row.get("valid_response") is True, "budget-invalid-response")
        normalized["response"] = {name: response[name] for name in (
            "activation_id", "release_digest", "revision_id", "route_generation", "consumption")}
        value = response["payload"]
        if value is not None:
            fields(value, "sha256 bytes media_type")
        normalized["response"].update(media_type=value["media_type"] if value else None,
                                      payload_sha256=value["sha256"] if value else None,
                                      payload_bytes=value["bytes"] if value else None)
        normalized["code"] = response["code"]
        if row["outcome"] == "success":
            require(function == "identify" and response["route_generation"] == "1", "budget-spin-or-crossed-route-success")
            normalized["semantic_match"] = True
    else:
        normalized["code"] = "grpc-" + str(row.get("grpc_code"))
    # The established validator checks ceil wire conversion, timeout header,
    # all response fields and actual consumption. Only its synthetic run/index
    # identity is projected; source row identity is checked above.
    normalized["activation_id"] = "budget-measured-0"
    if normalized["response"] is not None:
        require(normalized["response"]["activation_id"] == row["activation_id"], "budget-crossed-rpc-response")
        normalized["response"]["activation_id"] = normalized["activation_id"]
    common.attempt(normalized, {"run_id": "budget", "arm": "lsf", "measured_attempts": 1,
                              "batch_size": 1, "services": ["measurement-generic"], "schedule": {"mode": "closed-loop"},
                              "budget_millis": transport_budget, "cpu_fuel": 10_000_000_000, "memory_bytes": 67_108_864, "log_bytes": 16384},
                   "measured", origin, {"sha256": sha256(b"[11]"), "bytes": 4}, {"measurement-generic": release})
    normalized["activation_id"] = row["activation_id"]
    if normalized["response"] is not None:
        normalized["response"]["activation_id"] = row["activation_id"]
    if case in ("prewarm", "recovery"):
        require(row["outcome"] == "success", "budget-prewarm-or-recovery-failed")
    require((case == "delayed-body") == (row["body_gate"] is not None), "budget-body-gate-case")
    require((case == "queued") == ("queue_witness" in row), "budget-queue-witness-case")
    return normalized
