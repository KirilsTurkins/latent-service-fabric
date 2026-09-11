"""Reuse the established outcome and statistical rules for every cold offer."""
import re

from tools.optimization_evidence import attempts as common
from tools.optimization_evidence.common import fields, require, sha256, uint
from tools.phase1_paired.common import INPUT
from tools.phase1_paired.metrics import timing

PAYLOAD = ('[{"ok":"' + INPUT + '"}]').encode()


def validate(row, origin_unix, components, expected, pins, route_generation="8"):
    fields(row, "kind phase index key activation_id release_digest scheduled_nanos deadline_nanos deadline_unix_millis "
           "absolute_deadline_quantization_nanos dispatch_nanos dispatch_lag_nanos grpc_timeout_header rpc_received response "
           "outcome completed_nanos overshoot_nanos retained_status retained_observed_nanos backend_timing retained_valid",
           "valid_response grpc_code")
    require(row["kind"] == "invoke" and row["activation_id"] in expected, "unexpected-cold-offer")
    phase, index, key, due = expected[row["activation_id"]]
    require(row["phase"] == phase and row["index"] == str(index) and row["key"] == str(key)
            and row["release_digest"] == components[key], "crossed-cold-offer-identity")
    scheduled, completed = uint(row["scheduled_nanos"]), uint(row["completed_nanos"])
    require((due is None or scheduled == due) and scheduled <= completed, "cold-offer-schedule")
    deadline = scheduled + 1_000_000_000
    absolute = (origin_unix + deadline + 999_999) // 1_000_000
    require(uint(row["deadline_nanos"]) == deadline and uint(row["deadline_unix_millis"]) == absolute
            and uint(row["absolute_deadline_quantization_nanos"]) == absolute * 1_000_000 - origin_unix - deadline
            and uint(row["overshoot_nanos"]) == max(0, completed-deadline), "cold-deadline-rewritten")
    normalized = dict(row, service=f"cold-key-{key}", code=None, semantic_match=None,
                      latency_nanos=None, response=None)
    response = row["response"]
    if response is not None:
        fields(response, "activation_id release_digest revision_id route_generation code payload consumption")
        require(row.get("valid_response") is True, "cold-invalid-response")
        payload = response["payload"]
        normalized["response"] = {name: response[name] for name in (
            "activation_id", "revision_id", "release_digest", "route_generation", "consumption")}
        normalized["response"].update(media_type=payload["media_type"] if payload else None,
                                      payload_sha256=payload["sha256"] if payload else None,
                                      payload_bytes=payload["bytes"] if payload else None)
        normalized["code"] = response["code"]
        if row["outcome"] == "success":
            normalized["semantic_match"] = True
    elif row["outcome"] == "transport-failure":
        normalized["code"] = "grpc-" + str(row["grpc_code"])
    elif row["outcome"] == "client-timeout":
        normalized["code"] = "response-observation-timeout"
    require(row["outcome"] in common.OUTCOMES and type(row["rpc_received"]) is bool, "cold-outcome")
    require(row["outcome"] not in ("declared-error","invalid-response"), "cold-echo-semantic-failure")
    if row["dispatch_nanos"] is None:
        require(row["outcome"] in common.UNSENT and row["dispatch_lag_nanos"] is None
                and row["grpc_timeout_header"] is None and response is None and row["rpc_received"] is False, "cold-undispatched-response")
        require(row["outcome"] != "client-deadline-before-dispatch" or completed >= deadline, "cold-premature-client-deadline")
    else:
        dispatch = uint(row["dispatch_nanos"])
        require(scheduled <= dispatch < deadline and completed >= dispatch
                and uint(row["dispatch_lag_nanos"]) == dispatch-scheduled, "cold-dispatch-clock")
        header = row["grpc_timeout_header"]
        require(isinstance(header, str) and re.fullmatch(r"[0-9]{1,8}[HMSmun]", header), "cold-timeout-header")
        scale = {"H":3_600_000_000_000,"M":60_000_000_000,"S":1_000_000_000,"m":1_000_000,"u":1000,"n":1}[header[-1]]
        require(abs(int(header[:-1])*scale-(deadline-dispatch)) < scale, "cold-timeout-extended")
        normalized["latency_nanos"] = str(completed-dispatch)
        common.response(normalized, {"arm":"lsf","cpu_fuel":10_000_000_000,"memory_bytes":16_777_216,"log_bytes":16384},
                        {"sha256":sha256(PAYLOAD),"bytes":len(PAYLOAD)}, {f"cold-key-{key}":components[key]})
    require(row["retained_valid"] is True and uint(row["retained_observed_nanos"]) >= completed, "cold-retained-witness")
    retained = row["retained_status"]
    if retained.get("grpc_code") == 0:
        fields(retained,"grpc_code activation_id phase terminal_state outcome code metadata consumption")
        require(retained["activation_id"] == row["activation_id"], "cold-crossed-retained-activation")
    else:
        fields(retained,"grpc_code")
    if row["outcome"] == "success":
        require(retained["activation_id"] == row["activation_id"] and retained["grpc_code"] == 0
                and retained["terminal_state"] == "completed" and retained["outcome"] == "success"
                and retained["consumption"] == response["consumption"] and response["route_generation"] == route_generation, "cold-crossed-terminal")
        pin = response["revision_id"]
        require(isinstance(retained["metadata"],dict) and all(retained["metadata"].get(name) == item for name,item in
                (("release",response["release_digest"]),("revision",pin),("route-generation",route_generation))), "cold-retained-pin-crossed")
        require(0 < uint(response["consumption"]["cpu_fuel"]) < 10_000_000_000
                and 0 < uint(response["consumption"]["log_bytes"]) <= 16384
                and uint(response["consumption"]["wall_time_micros"]) <= 1_000_000, "cold-success-accounting")
        require(key not in pins or pins[key] == pin, "cold-revision-changed")
        pins[key] = pin
        require(row["backend_timing"] is not None, "cold-success-timing-missing")
        timing(row["backend_timing"])
    elif response is not None and retained.get("grpc_code") == 0:
        require(retained["activation_id"] == row["activation_id"] and retained["consumption"] == response["consumption"]
                and retained["code"] == response["code"] and retained["terminal_state"] is not None, "cold-failure-accounting-crossed")
        if response["release_digest"]:
            require(response["release_digest"] == components[key] and response["route_generation"] == route_generation
                    and all(retained["metadata"].get(name) == item for name,item in
                    (("release",response["release_digest"]),("revision",response["revision_id"]),("route-generation",route_generation))),
                    "cold-failure-pin-crossed")
    else:
        require(retained.get("grpc_code") in (0,5), "cold-terminal-observation-failed")
    if phase in ("warmup","baseline","healthy"):
        require(row["outcome"] == "success", "cold-baseline-or-recovery-failed")
    return normalized


def expected(profile, starts):
    full, result = profile == "full", {}
    for phase, count in (("warmup",40 if full else 2),("baseline",400 if full else 4),("healthy",8 if full else 2)):
        for index in range(count):
            result[f"cold-{phase}-{index:04}"] = phase,index,0,None
    for phase, keys in (("same-key",[1]*8),("distinct",list(range(2,7))),("cancel",[7]*8)):
        start = starts[phase]
        origin, cold_due = uint(start["origin_nanos"]), uint(start["cold_due_nanos"])
        require(cold_due-origin == (16 if full else 4)*1_000_000, "cold-burst-offset")
        for index in range(128 if full else 16):
            result[f"cold-{phase}-warm-{index:04}"] = phase,index,0,origin+index*2_000_000
        for index,key in enumerate(keys):
            result[f"cold-{phase}-cold-{index:04}"] = phase,index,key,cold_due
    return result
