"""Descriptive recovery outcomes; retain raw calls and all source events separately."""
from decimal import Decimal

from tools.optimization_evidence.attempts import metrics as common_metrics
from tools.optimization_evidence.common import distribution, uint
from tools.phase1_paired.aggregate import delta
from .model import offers


def metrics(rows):
    value = common_metrics(rows)
    dropped = [row for row in rows if row["outcome"] == "client-disconnected"]
    if dropped:
        value["counts"]["outcomes"]["client-disconnected"] = str(len(dropped))
    value["outcome_latency_nanos"]["client-disconnected"] = distribution([uint(row["latency_nanos"]) for row in dropped]) if dropped else None
    value["latency_population"] = "all-dispatched-until-response-or-confirmed-client-task-destruction"
    return value


def aggregate(suite, checksum, builds, records, complete, failed):
    for record in records:
        if record["status"] != "passed":
            continue
        raw = record.pop("offers")
        definitions = offers()
        groups = list(dict.fromkeys((case, budget) for case, budget, _function in definitions))
        record["cases"] = [{"case": case, "budget_millis": str(budget), "metrics": metrics([
            row for index, row in enumerate(raw) if definitions[index][:2] == (case, budget)])} for case, budget in groups]
        record["outcomes"] = [{"ordinal": str(index), "case": definitions[index][0], "budget_millis": str(definitions[index][1]),
                               "outcome": row["outcome"], "code": row["code"], "overshoot_nanos": row["overshoot_nanos"]}
                              for index, row in enumerate(raw)]
        record["all_offers"] = metrics(raw)
        record["followup_successes"] = str(sum(row["outcome"] == "success" for index, row in enumerate(raw)
                                              if definitions[index][0] == "recovery"))
        record["actual_running_disconnects"] = str(sum(row["case"] == "running-disconnect" and row["disconnect"] is not None
                                                     and row["disconnect"]["aborted"] and row["running_at_drop_trigger"]
                                                     for row in record["coverage"]))
    indexed = {row["variant"]: row for row in records if row["status"] == "passed"}
    contrasts = {}
    if set(indexed) == {"control", "candidate"}:
        left, right = indexed["control"], indexed["candidate"]
        for name in ("followup_successes", "actual_running_disconnects"):
            contrasts[name] = delta(Decimal(right[name]), Decimal(left[name]))
        for name in ("user_ticks", "system_ticks"):
            contrasts["process_cpu_" + name] = (delta(Decimal(right["process_cpu"][name]), Decimal(left["process_cpu"][name]))
                if left["process_cpu"]["status"] == right["process_cpu"]["status"] == "available" else None)
    return {"schema": "latent.optimization.recovery-aggregate.v1", "profile": suite["profile"],
            "status": "failed" if failed else "complete" if complete and suite["profile"] == "full" else "incomplete",
            "suite_sha256": checksum, "builds": builds, "population_complete": complete, "attempt_count_complete": complete,
            "validated_calls": str(sum(uint(row["samples"]) for row in records if row["status"] == "passed")),
            "validated_commands": str(sum(uint(row["commands"]) for row in records if row["status"] == "passed")),
            "observed_failed_invoke_attempts": str(sum(uint(row.get("observed_invoke_attempts", "0")) for row in records if row["status"] == "failed")),
            "retained_failed_offer_rows": str(sum(uint(row.get("retained_offer_rows", "0")) for row in records if row["status"] == "failed")),
            "runs": records, "contrasts": contrasts,
            "limitations": [
                "One independent four-cell process per variant executes all 61 offers without restart or pool enlargement; this is recovery correctness evidence, not seven timing pairs.",
                "Every short expiry/disconnect request keeps its original 1/2/5/10 ms transport, caller and native budget. Early rejection is retained and does not prove a Running interruption.",
                "Five separate 1000 ms envelopes provide positive Running-triggered client-drop coverage beyond the four-cell capacity; they do not claim a 1 ms Running execution.",
                "Client-disconnected means the RPC task was aborted and joined with no response; a completed-response race remains its actual response outcome.",
                "The token/slot/generation handoff event observes the start of transferring the owned lifecycle and reserved slot, before queue commit or driver polling; it is not alone proof of native acknowledgement or cell reuse.",
                "Handoff cause cancelled denotes raw transport disconnect, not an accepted Cancel RPC. Explicit cancellation has a separate command/disposition and terminal-winner association.",
                "A terminal publication may precede supervisor future destruction/refund; transient snapshots retain real live charges, while final joined cleanup requires all live slots zero and every handoff completed.",
                "The 250 ms acknowledgement observer does not renew the 200 ms cleanup allowance or guest budget. Observation scheduling overshoot remains separate.",
                "Control supervisor observations are unavailable, not zero work. Its lost capacity and all planned follow-up failures remain in the qualified comparison population.",
                "Native cleanup disposition comes from the correlated source telemetry record; sampled RSS/threads/FDs are whole-process observations, not isolated runtime costs.",
                "CPU ticks cover the whole diagnostic population, controls and observers; manager sleep counters do not count all Tokio, Tonic or OS timers.",
                "All original offers, controls, source events, snapshots and cleanup logs remain in archived recovery.json; smoke never qualifies as full publication evidence."]}
