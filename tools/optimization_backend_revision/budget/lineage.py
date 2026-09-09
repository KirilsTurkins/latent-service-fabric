"""Required source stages and the actual published terminal stamp are one graph."""
from tools.optimization_evidence.common import require, uint

TERMINAL_CODES = {
    "deadline-exceeded": "deadline-exceeded", "cancelled": "cancelled", "resource-exhausted": "resource-exhausted",
    "guest-trap": "guest-trap", "state-conflict": "state-conflict", "dependency-failed": "dependency-failed",
    "unavailable": "dependency-failed", "route-unavailable": "dependency-failed", "internal": "platform-failed",
    **{name: "rejected" for name in ("permission-denied", "unauthenticated", "invalid-argument", "not-found",
                                    "already-exists", "incompatible-contract", "corrupt-artifact", "admission-rejected")},
}


def check(rows, offer, variant):
    stages = {kind: [(index, row) for index, row in enumerate(rows) if row["kind"] == kind]
              for kind in ("body-decoded", "admission-check", "admitted-ledger", "execution-deadline", "terminal-decision", "terminal-winner")}
    phases = [row for row in rows if row["kind"] == "lifecycle-phase"]
    for kind, found in stages.items():
        require(len(found) <= 1, "budget-lineage-duplicate-stage")
    admitted_phase = any(row["phase"] in ("admitted", "queued", "materializing", "running") for row in phases)
    if offer["outcome"] == "success" or admitted_phase or stages["execution-deadline"]:
        require(len(stages["admission-check"]) == len(stages["admitted-ledger"]) == 1,
                "budget-required-deadline-lineage-missing")
    if offer["outcome"] == "success":
        require(len(stages["execution-deadline"]) == 1, "budget-success-execution-lineage-missing")
    for _, event in stages["admission-check"]:
        require(stages["body-decoded"] and stages["body-decoded"][0][0] < stages["admission-check"][0][0],
                "budget-admission-before-decoded-body")
        # Fixed standalone policy: one millisecond execution floor, no external
        # queue estimate/margin; four holders add one one-millisecond wave.
        if event["decision"] in ("accepted", "queue-infeasible", "missing-deadline"):
            require(event["required_nanos"] == ("2000000" if offer["case"] == "queued" else "1000000"),
                    "budget-required-feasibility-policy-changed")
        else:
            require(event["required_nanos"] is None, "budget-uncomputed-required-time")
    if stages["admitted-ledger"]:
        require(stages["admission-check"], "budget-ledger-without-admission-check")
        check_index, checked = stages["admission-check"][0]
        ledger_index, ledger = stages["admitted-ledger"][0]
        require(checked["decision"] == "accepted" and checked["deadline"] == ledger["deadline"]
                and check_index < ledger_index
                and int(checked["observed_at_nanos"]) <= int(ledger["observed_at_nanos"]), "budget-admission-ledger-crossed")
        if stages["execution-deadline"]:
            execution_index, execution = stages["execution-deadline"][0]
            require(ledger_index < execution_index and int(ledger["observed_at_nanos"]) <= int(execution["observed_at_nanos"])
                    and ledger["budget"] == execution["budget"], "budget-execution-before-ledger")
    retained = offer.get("retained_status")
    if retained is None:
        return  # Small observer unit fixtures; complete replay requires status.
    winners = stages["terminal-winner"]
    if retained["grpc_code"] == 5:
        require(not winners, "budget-retained-missing-published-terminal")
        return
    needs_decision = variant == "candidate" or bool(stages["admitted-ledger"]) or retained["outcome"] == "success"
    require(retained["grpc_code"] == 0 and len(winners) == 1
            and (not needs_decision or len(stages["terminal-decision"]) == 1),
            "budget-published-terminal-lineage-missing")
    winner_index, winner = winners[0]
    decision_index, decision = stages["terminal-decision"][0] if stages["terminal-decision"] else (None, None)
    state = retained["terminal_state"].replace("_", "-") if isinstance(retained.get("terminal_state"), str) else None
    require(state == winner["terminal_state"] and int(winner["observed_at_nanos"]) <= uint(offer["retained_observed_nanos"])
            and (decision is None or decision_index < winner_index
                 and int(decision["observed_at_nanos"]) <= int(winner["observed_at_nanos"])),
            "budget-terminal-winner-crossed")
    expected_phase = phases[-1]["phase"] if phases else "received"
    require(retained["phase"].replace("_", "-") == expected_phase, "budget-retained-phase-crossed")
    if retained["outcome"] == "success":
        require(state == "completed" and retained["code"] is None
                and decision["decision"] in ("accepted", "completed"), "budget-terminal-success-crossed")
    else:
        require(retained["outcome"] == "platform-failure" and TERMINAL_CODES.get(retained["code"]) == state,
                "budget-terminal-code-state-crossed")
