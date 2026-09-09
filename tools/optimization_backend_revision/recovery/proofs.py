"""Bind explicit controls, published terminal states and native cell disposition."""
from tools.optimization_evidence.attempts import CONSUMPTION, PLATFORM_CODES
from tools.optimization_evidence.common import fields, integer, require, text, uint
from ..budget.lineage import TERMINAL_CODES
from ..budget.observer import instant, PHASES


def status(value, offer, observer, variant, revision):
    code = integer(value.get("grpc_code"), 0, 16)
    token_rows = observer.by_token[uint(offer["diagnostic_token"])]
    winners = [event for event in token_rows if event["kind"] == "terminal-winner"]
    decisions = [event for event in token_rows if event["kind"] == "terminal-decision"]
    phases = [event["phase"] for event in token_rows if event["kind"] == "lifecycle-phase"]
    if code:
        fields(value, "grpc_code")
        require(code == 5 and offer["outcome"] != "success" and not winners, "recovery-hidden-terminal-status")
        return
    fields(value, "grpc_code activation_id phase terminal_state outcome code metadata consumption")
    require(value["activation_id"] == offer["activation_id"] and isinstance(value["metadata"], dict)
            and value["phase"].replace("_", "-") == (phases[-1] if phases else "received"), "recovery-status-identity-or-phase")
    if value["consumption"] is not None:
        for number in fields(value["consumption"], CONSUMPTION).values():
            uint(number)
    if value["outcome"] == "pending":
        require(variant == "control" and value["terminal_state"] is None and value["code"] is None
                and value["consumption"] is None and not winners, "recovery-pending-hides-terminal")
        return
    require(value["outcome"] in ("success", "platform-failure") and len(winners) == 1, "recovery-terminal-winner-missing")
    require(variant != "candidate" or len(decisions) == 1, "recovery-required-terminal-decision-missing")
    state = value["terminal_state"]
    require(isinstance(state, str) and state.replace("_", "-") == winners[0]["terminal_state"]
            and instant(winners[0]["observed_at_nanos"]) <= uint(offer["retained_observed_nanos"]), "recovery-terminal-winner-crossed")
    if value["outcome"] == "success":
        require(state == "completed" and value["code"] is None and len(decisions) == 1
                and decisions[0]["decision"] in ("accepted", "completed"), "recovery-false-success")
    else:
        require(value["code"] in PLATFORM_CODES and TERMINAL_CODES.get(value["code"]) == state.replace("_", "-"),
                "recovery-terminal-code-state-crossed")
    if decisions:
        require(len(decisions) == 1 and instant(decisions[0]["observed_at_nanos"])
                <= instant(winners[0]["observed_at_nanos"]), "recovery-terminal-decision-after-publication")
        terminal_precedence(value, offer, decisions[0], observer.handoffs.get(uint(offer["diagnostic_token"])))
    response = offer["response"]
    if response is not None and uint(offer["diagnostic_token"]) not in observer.handoffs:
        require(value["outcome"] == offer["outcome"] and value["code"] == response["code"]
                and value["consumption"] == response["consumption"], "recovery-terminal-response-crossed")
    if value["outcome"] == "success":
        require(value["metadata"].get("release") == offer["release_digest"]
                and value["metadata"].get("route-generation") == "1", "recovery-terminal-release-crossed")
    if any(row["kind"] in ("admitted-ledger", "execution-deadline") for row in token_rows) or value["metadata"]:
        require(value["metadata"] == {"release": offer["release_digest"], "revision": revision, "route-generation": "1"},
                "recovery-terminal-pinned-revision-crossed")


def terminal_precedence(value, offer, decision, handoff):
    """Raw stop is provisional; checked expiry and accepted Cancel keep priority.

    A non-deadline resource violation may still replace raw cancellation during
    ledger finalization. The diagnostic does not expose the violation's private
    latch, so it cannot exclude that legal resource-exhausted outcome.
    """
    explicit = offer["cancel_response"]
    accepted_cancel = explicit is not None and explicit.get("grpc_code") == 0 and explicit.get("disposition") == 1
    state = value["terminal_state"].replace("_", "-")
    if accepted_cancel:
        require(state == "cancelled", "recovery-accepted-cancel-winner-crossed")
    elif decision["decision"] == "deadline-exceeded":
        require(state == "deadline-exceeded", "recovery-expired-deadline-winner-crossed")
    elif handoff is not None and handoff["cause"] == "cancelled" and decision["decision"] in ("accepted", "completed"):
        require(state in ("cancelled", "resource-exhausted"), "recovery-unexpired-disconnect-winner-crossed")


def commands(rows, offers, observer, variant, revision):
    expected = [("status", index) for index in range(59)] + [("cancel", 59), ("status", 59), ("status", 60)]
    require(len(rows) == 62, "recovery-command-population")
    previous, cancellation = 0, None
    for ordinal, (row, (operation, index)) in enumerate(zip(rows, expected, strict=True)):
        fields(row, "kind ordinal operation target started_nanos finished_nanos response trigger")
        offer = offers[index]
        begin, end = uint(row["started_nanos"]), uint(row["finished_nanos"])
        require(row["kind"] == "command" and row["ordinal"] == str(ordinal) and row["operation"] == operation
                and row["target"] == offer["activation_id"] and previous <= begin <= end, "recovery-command-order-or-clock")
        previous = end
        if operation == "status":
            require(row["trigger"] is None and uint(offer["acknowledgement"]["finished_nanos"]) <= begin
                    and offer["retained_status"] == row["response"] and offer["retained_observed_nanos"] == row["finished_nanos"],
                    "recovery-status-command-crossed")
            status(row["response"], offer, observer, variant, revision)
        else:
            value = fields(row["response"], "grpc_code disposition terminal_state")
            require(value["grpc_code"] == 0 and type(value["disposition"]) is int and value["disposition"] in (1, 2, 3)
                    and row["response"] == offer["cancel_response"] and row["trigger"] == offer["running_witness"],
                    "recovery-cancel-response-crossed")
            running = observer.running(row["trigger"], offer, uint(offer["dispatch_nanos"]), begin)
            require(variant != "candidate" or running and value["disposition"] == 1, "recovery-positive-cancel-not-running-and-accepted")
            if value["disposition"] == 1:
                records = observer.by_token[uint(offer["diagnostic_token"])]
                require(any(event["kind"] == "terminal-winner" and event["terminal_state"] == "cancelled"
                            and begin <= instant(event["observed_at_nanos"]) for event in records)
                        and begin <= uint(offer["completed_nanos"]), "recovery-accepted-cancel-after-terminal-or-response")
            cancellation = {"disposition": value["disposition"], "running_trigger_observed": running,
                            "elapsed_nanos": str(end - begin)}
    return cancellation


def cleanup_log(value, offer, running, variant, origin, checkpoint, revision):
    if value is None:
        require(not (variant == "candidate" and running), "recovery-native-cleanup-disposition-missing")
        return None
    fields(value, "body attributes observed_at_unix_millis")
    require(value["body"] == "activation cleanup", "recovery-cleanup-log-kind")
    attributes = fields(value["attributes"], "activation_id root_activation_id tenant service contract function stage elapsed_micros cleanup",
                        "parent_activation_id release revision route_generation")
    for item in attributes.values():
        text(item, 512)
    require(attributes["activation_id"] == attributes["root_activation_id"] == offer["activation_id"]
            and attributes["tenant"] == "tests" and attributes["service"] == "measurement-generic"
            and attributes["contract"] == "tests:generic/values@0.1.0" and attributes["function"] == offer["function"]
            and attributes["stage"] == "cleanup" and attributes["cleanup"] in
                ("no_cell", "released", "quarantined", "reclaimed_before_execution", "abandoned", "failed"), "recovery-cleanup-log-identity")
    require("release" not in attributes or attributes["release"] == offer["release_digest"], "recovery-cleanup-release-crossed")
    require("route_generation" not in attributes or attributes["route_generation"] == "1", "recovery-cleanup-route-crossed")
    if running or "revision" in attributes:
        require(attributes.get("revision") == revision and attributes.get("release") == offer["release_digest"]
                and attributes.get("route_generation") == "1", "recovery-cleanup-pinned-revision-crossed")
    uint(attributes["elapsed_micros"])
    at = uint(value["observed_at_unix_millis"]) * 1_000_000
    require(origin + uint(offer["dispatch_nanos"]) <= at + 999_999
            and at <= origin + uint(checkpoint["observed_nanos"]) + 999_999, "recovery-cleanup-log-outside-offer")
    require(variant != "candidate" or not running or attributes["cleanup"] == "released", "recovery-running-cell-not-released")
    return {"disposition": attributes["cleanup"], "elapsed_micros": attributes["elapsed_micros"],
            "observed_at_unix_millis": value["observed_at_unix_millis"]}
