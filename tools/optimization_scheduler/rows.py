"""Replay each original offer without converting rejection into an enqueue."""
from collections import Counter
from tools.optimization_evidence.common import distribution, fields, require, text, uint
from . import model

TIMES = ("admission_started_nanos", "admission_finished_nanos", "admitted_nanos", "deadline_nanos", "deadline_unix_millis",
         "enqueue_called_nanos", "result_nanos", "release_started_nanos", "released_nanos", "cancel_requested_nanos", "cancel_finished_nanos")
OUTCOMES = ("released", "admission-error", "scheduler-error", "backpressure")


def error(value):
    fields(value, "code message retryable details")
    text(value["code"], 128)
    text(value["message"], 4096, empty=True)
    require(type(value["retryable"]) is bool and isinstance(value["details"], list) and len(value["details"]) <= 16,
            "scheduler-error-fields")
    for detail in value["details"]:
        fields(detail, "kind fields")
        text(detail["kind"], 256)
        require(isinstance(detail["fields"], dict) and len(detail["fields"]) <= 32, "scheduler-error-detail-bound")
        for key, item in detail["fields"].items():
            text(key, 256)
            text(item, 4096, empty=True)


def validate(value, selected, started, finished):
    planned = model.counts(selected)
    require(isinstance(value, list) and len(value) == planned["logical_offers"], "scheduler-offer-count")
    by_ordinal = {}
    storm = selected["case"].startswith("cancel-")
    for row in value:
        fields(row, "ordinal tenant activation_id role scheduled_nanos dispatched_nanos " + " ".join(TIMES)
               + " cancel_accepted cancel_error outcome error cleanup_reclaimed")
        ordinal, tenant = uint(row["ordinal"]), uint(row["tenant"])
        require(ordinal < len(value) and ordinal not in by_ordinal, "scheduler-offer-ordinal")
        by_ordinal[ordinal] = row
        index = ordinal - (4 if storm and ordinal >= 4 else planned["warmup_offers"] if not storm and ordinal >= 8 else 0)
        role = ("holder" if ordinal < 4 else "queued") if storm else ("warmup" if ordinal < 8 else "measured")
        require(row["activation_id"] == f"scheduler-{ordinal:05}" and row["role"] == role
                and tenant == index % model.tenants(selected), "scheduler-offer-identity-or-tenant")
        scheduled, dispatched = uint(row["scheduled_nanos"]), uint(row["dispatched_nanos"])
        require(scheduled <= dispatched <= finished and row["cleanup_reclaimed"] is False, "scheduler-offer-clock-or-reclaim")
        if role == "measured":
            require(started <= scheduled, "scheduler-measured-before-window")
            rate = model.settings(selected)["rate_per_second"]
            if rate:
                require(scheduled == started + index * 10**9 // rate, "scheduler-arrival-schedule")
        for name in TIMES:
            if row[name] is not None:
                uint(row[name])
        outcome = row["outcome"]
        require(outcome in OUTCOMES, "scheduler-incomplete-or-invalid-outcome")
        if outcome == "backpressure":
            require(not storm and role == "measured" and all(row[key] is None for key in TIMES)
                    and row["error"] is None, "scheduler-backpressure-has-server-work")
        else:
            admission_start, admission_finish = (uint(row[key]) for key in TIMES[:2])
            require(dispatched <= admission_start <= admission_finish <= finished, "scheduler-admission-clock")
            if outcome == "admission-error":
                require(not storm and all(row[key] is None for key in TIMES[2:9]), "scheduler-rejected-admission-has-enqueue")
            else:
                admitted, deadline, enqueue, result = (uint(row[key]) for key in
                                                       ("admitted_nanos", "deadline_nanos", "enqueue_called_nanos", "result_nanos"))
                require(admitted == admission_finish and admitted <= enqueue <= result <= finished
                        and admission_start + 10**9 <= deadline <= admission_finish + 10**9,
                        "scheduler-enqueue-or-original-deadline")
                require(uint(row["deadline_unix_millis"]) > 0, "scheduler-original-wall-deadline")
                if outcome == "released":
                    release_start, released = uint(row["release_started_nanos"]), uint(row["released_nanos"])
                    require(result <= release_start <= released <= finished and row["error"] is None,
                            "scheduler-release-clock")
                    require(storm or release_start - result >= 10_000_000, "scheduler-requested-hold-shortened")
                else:
                    require(row["release_started_nanos"] is None and row["released_nanos"] is None,
                            "scheduler-enqueue-error-has-release")
        if outcome.endswith("-error"):
            error(row["error"])
            if not storm:
                allowed = ("resource-exhausted", "deadline-exceeded", "admission-rejected") if outcome == "admission-error" else ("resource-exhausted", "deadline-exceeded")
                require(row["error"]["code"] in allowed, "scheduler-unexpected-platform-error")
        cancelled = storm and ordinal >= 4 and model.cancelled(ordinal - 4, model.tenants(selected))
        if cancelled:
            begin, end = uint(row["cancel_requested_nanos"]), uint(row["cancel_finished_nanos"])
            require(uint(row["enqueue_called_nanos"]) <= begin <= end <= uint(row["result_nanos"])
                    and row["cancel_accepted"] is True and row["cancel_error"] is None
                    and outcome == "scheduler-error" and row["error"]["code"] == "cancelled",
                    "scheduler-original-cancellation-not-settled")
        else:
            require(row["cancel_requested_nanos"] is None and row["cancel_finished_nanos"] is None
                    and row["cancel_accepted"] is None and row["cancel_error"] is None, "scheduler-unplanned-cancel")
            require(not storm or outcome == "released", "scheduler-storm-drain-failed")
        require(role != "warmup" or outcome == "released", "scheduler-warmup-failed")
        require(selected["case"] not in ("closed-one", "reference-many") or outcome == "released", "scheduler-reference-failed")
    return [by_ordinal[index] for index in range(len(value))]


def counts(rows):
    keys = {"admission_calls": "admission_started_nanos", "admitted": "admitted_nanos", "enqueue_calls": "enqueue_called_nanos",
            "enqueue_results": "result_nanos", "cancel_calls": "cancel_requested_nanos", "release_calls": "release_started_nanos",
            "released": "released_nanos"}
    result = {name: str(sum(row[key] is not None for row in rows)) for name, key in keys.items()}
    result.update(offers=str(len(rows)), cancel_accepted=str(sum(row["cancel_accepted"] is True for row in rows)),
                  cleanup_reclaims=str(sum(row["cleanup_reclaimed"] for row in rows)), shutdown_calls="1")
    return result


def summarize(rows):
    outcomes = Counter(row["outcome"] for row in rows)
    def deltas(end, begin, predicate=lambda row: True):
        values = [uint(row[end]) - uint(row[begin]) for row in rows
                  if predicate(row) and row[end] is not None and row[begin] is not None]
        return distribution(values) if values else None
    return {"offers": str(len(rows)), "outcomes": {name: str(outcomes[name]) for name in OUTCOMES},
            "scheduling_lag_nanos": deltas("dispatched_nanos", "scheduled_nanos"),
            "enqueue_to_result_all_nanos": deltas("result_nanos", "enqueue_called_nanos"),
            "enqueue_to_result_released_nanos": deltas("result_nanos", "enqueue_called_nanos", lambda row: row["outcome"] == "released"),
            "observed_hold_nanos": deltas("release_started_nanos", "result_nanos"),
            "cancel_to_original_settlement_nanos": deltas("result_nanos", "cancel_requested_nanos")}
