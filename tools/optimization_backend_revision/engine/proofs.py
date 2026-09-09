"""Actual occupied cells and Pending tasks precede each permitted cancellation."""
from tools.optimization_evidence.common import fields, require, uint
from tools.phase1_evidence.resources import idle
from . import calls, policy, schedule

WITNESSES = {"functional-running": (15,), "memory-dirty": (17,), "four-live": (19, 20, 21, 22),
             "fifth-queued": (19, 20, 21, 22, 23), "three-live": (20, 21, 22)}
IDLE = tuple(f"functional-{n:02}" for n in range(1, 19)) + ("functional-holders-drained", "functional-final")


def functional(rows, by_id, statuses, cancels, observer, elapsed):
    relevant = [row for row in rows if row.get("kind") == "proof" and row.get("label") != "batch-window"]
    require(len(relevant) == len(WITNESSES) + len(IDLE)
            and len({row["label"] for row in relevant}) == len(relevant)
            and {row["label"] for row in relevant} == set(WITNESSES) | set(IDLE), "engine-functional-proof-population")
    witness = {}
    for row in relevant:
        label = row["label"]
        if label in IDLE:
            fields(row, "kind label observed_nanos node native")
            native = policy.native(row["native"], 0)
            idle(row["node"])
            end = uint(row["observed_nanos"])
            require(uint(row["node"]["finished_micros"]) * 1000 <= end <= elapsed,
                    "engine-idle-proof-outside-sample")
            if label == "functional-holders-drained":
                ids = [f"engine-fn-{n:02}" for n in range(19, 24)]
            elif label == "functional-final":
                ids = ["engine-fn-24"]
            else:
                ids = ["engine-fn-" + label[-2:]]
            require(all(uint(statuses[name]["finished_nanos"]) <= uint(row["node"]["started_micros"]) * 1000 + 999
                        for name in ids), "engine-idle-before-terminal-status")
            require(native == row["node"]["backend"], "engine-idle-native-projection-crossed")
            continue
        fields(row, "kind label started_nanos finished_nanos maximum_millis matched observation")
        begin, finish = uint(row["started_nanos"]), uint(row["finished_nanos"])
        maximum = 250 if label == "fifth-queued" else 500
        require(row["maximum_millis"] == str(maximum) and row["matched"] is True
                and begin <= finish <= elapsed and finish - begin <= (maximum + 100) * 1_000_000, "engine-functional-witness-window")
        observed = fields(row["observation"], "collector_started_nanos collector_finished_nanos jobs native scheduler guest_logs baseline_stores_created")
        start, end = uint(observed["collector_started_nanos"]), uint(observed["collector_finished_nanos"])
        require(begin <= start <= end <= finish, "engine-functional-snapshot-window")
        expected_ids = [f"engine-fn-{n:02}" for n in WITNESSES[label]]
        jobs = observed["jobs"]
        require(isinstance(jobs, list) and [job.get("activation_id") for job in jobs] == expected_ids, "engine-witness-task-population")
        for job in jobs:
            fields(job, "activation_id pending running_sequence")
            call = by_id[job["activation_id"]]
            require(job["pending"] is True and uint(call["row"]["scheduled_nanos"]) <= start
                    and end <= uint(call["row"]["completed_nanos"]), "engine-witness-not-live-task")
            if job["running_sequence"] is not None:
                observer.running(job["running_sequence"], call, end)
            require(job["running_sequence"] is not None if job["activation_id"] != "engine-fn-23" else
                    label == "fifth-queued" and job["running_sequence"] is None, "engine-witness-running-coverage")
        native = policy.native(observed["native"])
        scheduler = fields(observed["scheduler"], "queue_depth active_leases")
        live = 4 if label == "fifth-queued" else len(jobs)
        require(uint(native["live_stores"]) == uint(native["live_component_instances"]) == live
                and uint(scheduler["active_leases"]) == live
                and uint(scheduler["queue_depth"]) == (1 if label == "fifth-queued" else 0), "engine-witness-cell-or-store-capacity")
        if label == "fifth-queued":
            require(native["stores_created"] == observed["baseline_stores_created"], "engine-queued-call-created-fifth-store")
        if label == "memory-dirty":
            values = calls.guest_logs(observed["guest_logs"], by_id["engine-fn-17"]["row"])
            require(len(values) == 1 and values[0]["record"]["message"] == schedule.DIRTY
                    and values == by_id["engine-fn-17"]["row"]["guest_logs"], "engine-cancel-before-memory-dirty")
        else:
            require(observed["guest_logs"] == [], "engine-unexpected-witness-log")
        witness[label] = row
    expected_cancel = ["engine-fn-17"] + [f"engine-fn-{n:02}" for n in range(19, 23)]
    require([row["target"] for row in cancels] == expected_cancel, "engine-cancel-population")
    for command in cancels:
        call = by_id[command["target"]]
        response = fields(command["response"], "grpc_code disposition terminal_state")
        require(response["grpc_code"] == 0 and type(response["disposition"]) is int and response["disposition"] == 1,
                "engine-cancel-not-accepted")
        token_rows = observer.by_token[uint(call["row"]["diagnostic_token"])]
        winner = next(event for event in token_rows if event["kind"] == "terminal-winner")
        trigger = witness["memory-dirty" if command["target"] == "engine-fn-17" else
                          "fifth-queued" if command["target"] == "engine-fn-19" else "three-live"]
        require(uint(trigger["finished_nanos"]) <= uint(command["started_nanos"])
                <= int(winner["observed_at_nanos"]) <= uint(call["row"]["completed_nanos"])
                and winner["terminal_state"] == "cancelled", "engine-cancel-trigger-or-winner-crossed")
    require(uint(witness["four-live"]["finished_nanos"]) <= uint(by_id["engine-fn-23"]["row"]["scheduled_nanos"])
            and uint(statuses["engine-fn-23"]["finished_nanos"]) <= uint(witness["three-live"]["started_nanos"]),
            "engine-fifth-queue-and-three-live-order")
    first = uint(by_id["engine-fn-01"]["row"]["scheduled_nanos"])
    final = max(uint(row["observed_nanos"]) for row in relevant if row["label"] == "functional-final")
    require(final - first <= 30_000_000_000, "engine-functional-watchdog-bound")
    return {"invokes": "24", "commands": "53", "successes": "15", "expected_platform_failures": "9",
            "accepted_cancellations": "5", "guest_logs": "10", "diagnostic_records": str(len(observer.records)),
            "actual_running": "24", "elapsed_nanos": str(final - first),
            "four_live_before_fifth": True, "fifth_queued_without_store": True, "three_live_after_fifth_success": True,
            "memory_after_trap_and_cancel": "zero-checked-before-dirty", "all_idle_proofs": str(len(IDLE))}
