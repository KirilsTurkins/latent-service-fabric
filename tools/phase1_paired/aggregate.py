"""Deterministic paired process statistics; no sample trimming or causal isolation."""

from decimal import Decimal, localcontext

from ..phase1_evidence.common import reference
from ..phase1_evidence.statistics import decimal_string, distribution
from .common import INPUT, METHOD, PREFIX
from .suite import validate

LIMITATIONS = [
    "A paired process is the independent unit; all predeclared measured calls are retained without trimming.",
    "This is a productionization treatment bundle, not isolated attribution to one code change or a universal SLO.",
    "Historical native-binary versus current libtest/RPC instrumentation and two versus three runtime workers are explicit treatment differences.",
    "Historical typed ABI versus current dynamic ABI, routing, admission, context, logging and accounting are explicit treatment differences.",
    "Identical maintained guest source does not imply identical component bytes; both exact ABI-compatible components are retained.",
    "Historical collector retains sample vectors; current collector streams JSON. Process RSS includes different diagnostic retention and is not an isolated runtime saving.",
    "Guest-call timing includes automatic canonical post-return in both arms; host-call timing is a subset, never added to it.",
    "The named post-return interval is host accounting after the call. Historical summed cleanup and current unmeasured codec gaps are not compared as cleanup totals.",
    "Semantic invocation elapsed contrasts historical prepared-envelope execution with current persistent-loopback RPC; the physical entrypoints intentionally differ.",
    "Startup, throughput, RSS causal deltas, August 30 calibration replacement and full historical invariant requalification are outside this selected experiment.",
    "Same-host observations include virtualization and instantaneous load; alternating order reduces but does not eliminate temporal confounding.",
    "Different probe, serialization and retained-vector costs affect spacing between calls and possible cache/thermal state; no statistical significance is claimed from seven descriptive pairs.",
]


def delta(candidate, control):
    with localcontext() as context:
        context.prec = 40
        absolute = candidate - control
        percent = None if control == 0 else decimal_string((absolute * 100 / control).quantize(Decimal("0.000001")))
    return {"absolute": decimal_string(absolute), "percent": percent,
            "percent_status": "undefined-zero-control" if control == 0 else "defined"}


def aggregate(path, root):
    checked = validate(path)
    source = checked["suite"]
    pairs = []
    for repetition in range(1, (7 if source["profile"] == "full" else 1) + 1):
        rows = {row["arm"]: row for row in checked["records"] if row["repetition"] == repetition}
        if set(rows) != {"control", "candidate"} or any(row["status"] != "passed" for row in rows.values()):
            continue
        metrics = []
        left = {row["name"]: row for row in rows["control"]["metrics"]}
        for right in rows["candidate"]["metrics"]:
            prior = left[right["name"]]
            metrics.append({"name": right["name"], "unit": right["unit"],
                            "boundary": right["boundary"],
                            "control": prior["statistics"], "candidate": right["statistics"],
                            "contrasts": {quantile: delta(Decimal(right["statistics"][quantile]), Decimal(prior["statistics"][quantile]))
                                          for quantile in ("median", "p95", "p99")}})
        pairs.append({"repetition": repetition, "metrics": metrics})
    across = []
    if pairs:
        for index, metric in enumerate(pairs[0]["metrics"]):
            per_pair = [pair["metrics"][index] for pair in pairs]
            values = [Decimal(row["contrasts"]["median"]["absolute"]) for row in per_pair]
            across.append({"name": metric["name"], "unit": metric["unit"],
                           "boundary": metric["boundary"],
                           "paired_median_differences": distribution(values),
                           "candidate_lower_pairs": str(sum(value < 0 for value in values)),
                           "equal_pairs": str(sum(value == 0 for value in values)),
                           "candidate_higher_pairs": str(sum(value > 0 for value in values)),
                           "control_process_medians": distribution([Decimal(row["control"]["median"]) for row in per_pair]),
                           "candidate_process_medians": distribution([Decimal(row["candidate"]["median"]) for row in per_pair])})
    failed = any(row["status"] == "failed" for row in checked["records"])
    status = "failed" if failed else "passed" if checked["complete"] and source["profile"] == "full" else "incomplete"
    return {"schema": PREFIX + "aggregate.v1", "method": METHOD, "profile": source["profile"],
            "status": status, "phase1_completion": "incomplete", "observational_only": True,
            "source": reference(path, root), "controls": checked["controls"],
            "population": {"semantic_input": INPUT, "warmup_samples_per_arm": str(source["plan"]["warmup_samples"]),
                           "measured_samples_per_arm": str(source["plan"]["measured_samples"]), "required_pairs": "7",
                           "complete_pairs": str(len(pairs)), "warmup_selection": "fixed-leading-prefix",
                           "measured_selection": "all-remaining-sequential-calls-no-exclusions"},
            "arms": checked["records"], "pairs": pairs, "across_pairs": across, "limitations": LIMITATIONS}
