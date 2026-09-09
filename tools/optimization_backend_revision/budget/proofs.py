"""Bind positive lifecycle witnesses to the exact offers and control commands."""
from tools.optimization_evidence.attempts import CONSUMPTION, PLATFORM_CODES
from tools.optimization_evidence.common import fields, integer, require, uint
from .observer import instant, TERMINALS

CHECKPOINTS = ("after-prewarm", "after-queued", "after-delayed-body", "after-runaway", "after-cancellation", "after-recovery")


def status(value, offer):
    code = integer(value.get("grpc_code"), 0, 16)
    if code:
        fields(value, "grpc_code")
        require(code == 5 and offer["outcome"] != "success", "budget-retained-status-missing")
        return
    fields(value, "grpc_code activation_id phase terminal_state outcome code metadata consumption")
    require(value["activation_id"] == offer["activation_id"] and value["terminal_state"] is not None
            and value["terminal_state"].replace("_", "-") in TERMINALS, "budget-retained-terminal-crossed")
    require(value["outcome"] in ("success", "platform-failure"), "budget-retained-terminal-pending")
    if value["consumption"] is not None:
        for number in fields(value["consumption"], CONSUMPTION).values():
            uint(number)
    if value["outcome"] == "platform-failure":
        require(value["code"] in PLATFORM_CODES, "budget-retained-code")
    else:
        require(value["code"] is None and value["terminal_state"] == "completed", "budget-retained-success")
    response = offer["response"]
    if response is not None:
        require(value["outcome"] == offer["outcome"] and value["code"] == response["code"]
                and value["consumption"] == response["consumption"], "budget-retained-response-disagrees")
        if response["release_digest"]:
            require(response["release_digest"] == offer["release_digest"] and response["route_generation"] == "1"
                    and isinstance(value["metadata"], dict) and all(value["metadata"].get(name) == item for name, item in (
                        ("release", response["release_digest"]), ("revision", response["revision_id"]), ("route-generation", "1"))),
                    "budget-retained-route-crossed")


def command_order():
    rows = [("status", 0)] + [("status", index) for index in range(5, 9)]
    rows += [(operation, index) for index in range(1, 5) for operation in ("cancel", "status")]
    rows += [("status", index) for index in range(9, 17)]
    rows += [(operation, index) for index in range(17, 22) for operation in ("cancel", "status")]
    return rows + [("status", 22)]


def commands(rows, offers, observer):
    require(len(rows) == len(command_order()), "budget-control-population")
    previous, cancel_results = 0, []
    for ordinal, (row, (operation, index)) in enumerate(zip(rows, command_order(), strict=True)):
        fields(row, "kind ordinal operation target started_nanos finished_nanos response trigger")
        offer = offers[index]
        begin, end = uint(row["started_nanos"]), uint(row["finished_nanos"])
        require(row["kind"] == "command" and row["ordinal"] == str(ordinal) and row["operation"] == operation
                and row["target"] == offer["activation_id"] and previous <= begin <= end, "budget-control-order-or-clock")
        previous = end
        if operation == "status":
            require(row["trigger"] is None and uint(offer["completed_nanos"]) <= begin
                    and offer["retained_observed_nanos"] == row["finished_nanos"]
                    and offer["retained_status"] == row["response"], "budget-status-not-bound-to-offer")
            status(row["response"], offer)
            continue
        value = fields(row["response"], "grpc_code", "disposition terminal_state")
        require(value["grpc_code"] == 0 and set(value) == {"grpc_code", "disposition", "terminal_state"}
                and type(value["disposition"]) is int and value["disposition"] in (1, 2, 3), "budget-cancel-control-failed")
        trigger = row["trigger"]
        if trigger is not None:
            fields(trigger, "observed_nanos phase_record_sequence")
            sequence = uint(trigger["phase_record_sequence"])
            require(sequence in observer.records, "budget-cancel-trigger-record-missing")
            record = observer.records[sequence]
            event = record["observation"]
            require(record["token"] == offer["diagnostic_token"] and event["kind"] == "lifecycle-phase"
                    and event["phase"] == "running" and instant(event["observed_at_nanos"])
                    <= uint(trigger["observed_nanos"]) <= begin, "budget-cancel-trigger-crossed")
        if index == 21:
            require(trigger is not None and value["disposition"] == 1, "budget-positive-cancel-not-accepted-running")
        if value["disposition"] == 1:
            token_rows = observer.by_token[uint(offer["diagnostic_token"])]
            require(any(event["kind"] == "terminal-winner" and event["terminal_state"] == "cancelled"
                        and begin <= instant(event["observed_at_nanos"]) for event in token_rows)
                    and begin <= uint(offer["completed_nanos"]), "budget-accepted-cancel-after-terminal-or-response")
        cancel_results.append({"ordinal": offer["ordinal"], "case": offer["case"], "budget_millis": offer["budget_millis"],
                               "disposition": value["disposition"], "running_trigger_observed": trigger is not None,
                               "elapsed_nanos": str(end - begin)})
    return cancel_results


def case_windows(offers, commands_rows, checkpoints):
    require([row["label"] for row in checkpoints] == list(CHECKPOINTS), "budget-checkpoint-population")
    prior = 0
    for checkpoint, indices in zip(checkpoints, ((0,), tuple(range(1, 9)), tuple(range(9, 13)),
                                               tuple(range(13, 17)), tuple(range(17, 22)), (22,)), strict=True):
        finish = uint(checkpoint["observed_nanos"])
        require(prior <= finish, "budget-checkpoint-clock-regressed")
        for index in indices:
            row = offers[index]
            require(prior <= uint(row["scheduled_nanos"]) <= uint(row["completed_nanos"])
                    <= uint(row["retained_observed_nanos"]) <= finish, "budget-offer-outside-case-window")
            for command in commands_rows:
                if command["target"] == row["activation_id"]:
                    require(prior <= uint(command["started_nanos"]) <= uint(command["finished_nanos"]) <= finish,
                            "budget-command-outside-case-window")
        prior = max(finish, uint(checkpoint["node"]["finished_micros"]) * 1000)


def coverage(offers, observer):
    queue, runaway, body = [], [], []
    holders = offers[1:5]
    for offer in offers:
        index = uint(offer["ordinal"])
        token = offer["diagnostic_token"]
        records = observer.by_token[uint(token)] if token is not None else []
        if offer["case"] == "queued":
            witness = offer["queue_witness"]
            if witness is not None:
                fields(witness, "started_nanos finished_nanos queue_depth active_leases holder_ids")
                begin, end = uint(witness["started_nanos"]), uint(witness["finished_nanos"])
                require(witness["queue_depth"] == 1 and type(witness["queue_depth"]) is int
                        and witness["active_leases"] == 4 and type(witness["active_leases"]) is int
                        and witness["holder_ids"] == [row["activation_id"] for row in holders]
                        and uint(offer["dispatch_nanos"]) <= begin <= end <= uint(offer["completed_nanos"]), "budget-queue-witness-crossed")
                for holder in holders:
                    events = observer.by_token[uint(holder["diagnostic_token"])]
                    require(any(row["kind"] == "lifecycle-phase" and row["phase"] == "running"
                                and instant(row["observed_at_nanos"]) <= begin for row in events)
                            and not any(row["kind"] == "terminal-winner" and instant(row["observed_at_nanos"]) <= end for row in events),
                            "budget-queue-holder-not-running")
                require(any(row["kind"] == "admitted-ledger" for row in records), "budget-queue-target-not-admitted")
            queue.append({"budget_millis": offer["budget_millis"], "actual_queue_observed": witness is not None})
        elif offer["case"] == "runaway":
            running = any(row["kind"] == "lifecycle-phase" and row["phase"] == "running" for row in records)
            runaway.append({"budget_millis": offer["budget_millis"], "actual_running_observed": running})
        elif offer["case"] == "delayed-body":
            gate = fields(offer["body_gate"], "ingress_token intended_release_nanos released_nanos release_delivered response_before_release")
            require(gate["ingress_token"] == token and records and records[0]["kind"] == "ingress", "budget-body-gate-token")
            ingress = records[0]
            expiry = instant(ingress["expires_at_nanos"])
            release = uint(gate["released_nanos"])
            require(uint(gate["intended_release_nanos"]) == expiry + 1_000_000
                    and release >= uint(gate["intended_release_nanos"])
                    and type(gate["release_delivered"]) is bool and type(gate["response_before_release"]) is bool
                    and (uint(offer["completed_nanos"]) < release) == gate["response_before_release"], "budget-body-gate-clock")
            decoded = [row for row in records if row["kind"] == "body-decoded"]
            require(all(instant(row["observed_at_nanos"]) >= release for row in decoded)
                    and not any(row["kind"] in ("admitted-ledger", "execution-deadline") for row in records)
                    and offer["outcome"] != "success", "budget-delayed-body-admitted-or-not-actually-delayed")
            body.append({"budget_millis": offer["budget_millis"], "body_decoded": bool(decoded),
                         "release_delivered": gate["release_delivered"], "response_before_release": gate["response_before_release"]})
    require(all(row["actual_queue_observed"] for row in queue if row["budget_millis"] in ("5", "10")), "budget-positive-queue-coverage-missing")
    require(all(row["actual_running_observed"] for row in runaway if row["budget_millis"] in ("5", "10")), "budget-positive-runaway-coverage-missing")
    return {"queue": queue, "runaway": runaway, "delayed_body": body}
