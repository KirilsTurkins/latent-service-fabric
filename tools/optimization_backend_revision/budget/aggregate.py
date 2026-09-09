"""Compact descriptive lifecycle summaries; raw event streams remain archived."""
from decimal import Decimal

from tools.optimization_evidence.attempts import metrics
from tools.optimization_evidence.common import distribution, uint
from tools.phase1_paired.aggregate import delta
from .model import offers


def aggregate(suite, checksum, builds, records, complete, failed):
    for row in records:
        if row["status"] != "passed":
            continue
        raw = row.pop("offers")
        row["cases"] = [{"case": case, "metrics": metrics([value for index, value in enumerate(raw) if offers()[index][0] == case])}
                        for case in dict.fromkeys(value[0] for value in offers())]
        row["outcomes"] = [{"ordinal": str(index), "case": offers()[index][0], "budget_millis": str(offers()[index][1]),
                             "outcome": value["outcome"], "code": value["code"], "overshoot_nanos": value["overshoot_nanos"]}
                            for index, value in enumerate(raw)]
    indexed = {(row["repetition"], row["variant"]): row for row in records if row["status"] == "passed"}
    pairs = []
    for repetition in range(1, 8):
        if any((repetition, variant) not in indexed for variant in ("control", "candidate")):
            continue
        left, right = (indexed[repetition, variant] for variant in ("control", "candidate"))
        values = {"waits_" + name: delta(Decimal(right["waits"]["final"][name]), Decimal(left["waits"]["final"][name]))
                  for name in ("armed", "completed", "dropped", "maximum_live", "rechecks")}
        for name in ("user_ticks", "system_ticks"):
            values["process_cpu_" + name] = (delta(Decimal(right["process_cpu"][name]), Decimal(left["process_cpu"][name]))
                                             if left["process_cpu"]["status"] == right["process_cpu"]["status"] == "available" else None)
        pairs.append({"repetition": repetition, "contrasts": values})
    across = {name: distribution([Decimal(row["contrasts"][name]["absolute"]) for row in pairs if row["contrasts"][name] is not None])
              for name in (pairs[0]["contrasts"] if pairs else [])
              if any(row["contrasts"][name] is not None for row in pairs)}
    return {"schema": "latent.optimization.budget-lifecycle-aggregate.v1", "profile": suite["profile"],
            "status": "failed" if failed else "complete" if complete and suite["profile"] == "full" else "incomplete",
            "suite_sha256": checksum, "builds": builds, "population_complete": complete, "attempt_count_complete": complete,
            "validated_calls": str(sum(uint(row["samples"]) for row in records if row["status"] == "passed")),
            "validated_commands": str(sum(uint(row["commands"]) for row in records if row["status"] == "passed")),
            "observed_failed_invoke_attempts": str(sum(uint(row.get("observed_invoke_attempts", "0")) for row in records if row["status"] == "failed")),
            "retained_failed_offer_rows": str(sum(uint(row.get("retained_offer_rows", "0")) for row in records if row["status"] == "failed")),
            "runs": records, "pairs": pairs, "across_pairs": across,
            "limitations": ["Exactly 23 fixed diagnostic offers per arm, separate from external short-call performance samples.",
                "Wait counters cover the observed manager-owned sleep guards, not all Tokio, transport or operating-system timers.",
                "Actual process CPU ticks cover node, client, controls and observers; they are never divided into per-request CPU.",
                "Runaway and cancellation diagnostics keep a 1000 ms caller/transport allowance around the short native wall grant; their outer overshoot is separate from actual admitted-deadline overshoot.",
                "Lifecycle and terminal-winner events observe completed commits; terminal-decision retains the actual checked timestamp.",
                "Early budget rejection remains visible and does not establish queued, running or cancellation coverage.",
                "Checkpoints include fixed diagnostic overhead and retained bounded history; process RSS is not isolated runtime memory.",
                "All original offers, commands and deadline records remain in archived budget.json; this aggregate keeps derived summaries.",
                "Seven paired processes are descriptive evidence; smoke never completes the full profile."]}
