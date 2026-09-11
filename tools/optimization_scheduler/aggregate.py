"""Compact descriptive pairs, with completion and acceptance kept distinct."""
from decimal import Decimal
from tools.optimization_evidence.common import canonical, require, uint
from . import model


def differences(control, candidate):
    result = {}
    for key in sorted(set(control) & set(candidate)):
        left, right = control[key], candidate[key]
        if isinstance(left, dict) and isinstance(right, dict):
            nested = differences(left, right)
            if nested:
                result[key] = nested
        elif isinstance(left, str) and isinstance(right, str):
            try:
                before, after = Decimal(left), Decimal(right)
            except ArithmeticError:
                continue
            if before.is_finite() and after.is_finite():
                result[key] = {"control": left, "candidate": right, "difference": str(after - before),
                               "percent": None if before == 0 else str((after - before) * 100 / before)}
    return result


def aggregate(suite, suite_sha256, build, records, complete, failed):
    qualified = [row for row in records if row["status"] == "passed"]
    lookup = {(row["case"], row["mode"], row["variant"]): row for row in qualified}
    acceptance = {"saturation": {}, "reference": {}, "selected_allocation_coverage": {}}
    for variant in model.VARIANTS:
        for case in ("saturated-one", "saturated-many"):
            row = lookup.get((case, "normal", variant))
            acceptance["saturation"][case + "/" + variant] = bool(row and row["raw_summary"]["scheduler_rejected"] != "0"
                                                                  and row["raw_summary"]["observed_backlog"]
                                                                  and row["raw_summary"]["measured"]["outcomes"]["released"] != "0")
        row = lookup.get(("reference-many", "normal", variant))
        acceptance["reference"][variant] = bool(row and row["raw_summary"]["measured"]["outcomes"]["released"]
                                                == row["raw_summary"]["measured"]["offers"])
        row = lookup.get(("cancel-many", "allocation", variant))
        acceptance["selected_allocation_coverage"][variant] = bool(row and row["allocation_attribution"]["status"] == "available")
    full = complete and suite["profile"] == "full"
    comparisons = []
    for case, mode in [(case, "normal") for case in model.CASES] + [("cancel-many", "allocation")]:
        control, candidate = (lookup.get((case, mode, variant)) for variant in model.VARIANTS)
        if control and candidate:
            comparisons.append({"case": case, "mode": mode, "pairs": 1,
                                "order": [row["variant"] for row in qualified if row["case"] == case and row["mode"] == mode],
                                "metrics": differences(control["metrics"], candidate["metrics"]),
                                "raw_summary": differences(control["raw_summary"], candidate["raw_summary"])})
    result = {"schema": model.PREFIX + "aggregate.v1", "profile": suite["profile"],
              "status": "failed" if failed else "complete", "plan": suite["plan"],
              "completed_paired_run": complete, "full_population_completed": full,
              "acceptance_qualified": full and all(all(group.values()) for group in acceptance.values()),
              "acceptance_evidence": acceptance, "validated_attempts": len(qualified),
              "logical_offers": str(sum(uint(row["raw_summary"]["counts"]["offers"]) for row in qualified)),
              "load_offers": str(sum(uint(row["raw_summary"]["counts"]["offers"]) for row in qualified if not row["case"].startswith("cancel-"))),
              "storm_offers": str(sum(uint(row["raw_summary"]["counts"]["offers"]) for row in qualified if row["case"].startswith("cancel-") and row["mode"] == "normal")),
              "profile_offers": str(sum(uint(row["raw_summary"]["counts"]["offers"]) for row in qualified if row["mode"] == "allocation")),
              "source_revisions": build["requested_refs"], "suite_sha256": suite_sha256,
              "artifacts": suite["artifacts"], "builds": suite["builds"], "collection_elapsed_nanos": suite["elapsed_nanos"],
              "runs": records, "comparisons": comparisons,
              "scope": "one-pair-per-case-real-scheduler-four-cell-10ms-service-model-no-guest-invokes",
              "limitations": ["No replicated uncertainty estimate or production throughput claim.",
                              "Enqueue-to-result includes caller polling; exact per-tenant queue wait and mutex time are unavailable.",
                              "Work counters cover normal cancellation settlement only; profile process CPU is not normal CPU.",
                              "Selected peak is live allocation origins, not temporary scratch or whole-process peak."]}
    require(not complete or result["logical_offers"] == suite["plan"]["logical_offers"], "scheduler-complete-population-total")
    require(len(canonical(result)) + 1 <= model.MAX_AGGREGATE_BYTES, "scheduler-aggregate-byte-bound")
    return result
