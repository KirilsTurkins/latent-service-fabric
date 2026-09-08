"""Observations and qualified deltas across explicitly identified populations."""

from decimal import Decimal

from .compatibility import reasons
from .common import require
from .phase0 import WARM_FIELDS, number
from .statistics import decimal_string


def compare(candidate, reference, matched_warm=None):
    matched_warm = matched_warm or {}
    comparisons = []
    common_reasons = reasons(candidate, reference)
    activation_reasons = reasons(candidate, reference, activation=True)
    metrics = candidate["kinds"]["benchmark"]["metrics"]
    # Incomplete/smoke groups may still contain valid per-run observations.
    if not metrics:
        metrics = next((run["metrics"] for run in candidate["runs"]
                        if run["kind"] == "benchmark" and run["status"] == "passed"), [])
    require(bool(metrics), "missing-candidate-benchmark-observations")
    for metric in metrics:
        name, unit = metric["name"], metric["unit"]
        value = Decimal(metric["statistics"]["median"])
        old_name, old_value, extra = None, None, []
        incompatible = list(activation_reasons if name.startswith("warm_rpc.") else common_reasons)
        if name == "prepare.initial":
            old_name = "component_preparation_micros"
        elif name == "prepare.cold":
            old_name = "component_preparation_micros"
            extra.append("engine-cold-versus-warmed-cache-reset-population")
        elif name == "warm_rpc.rpc_latency":
            old_name = "warm_activation_elapsed_micros"
            extra.append("rpc-versus-direct-invocation-boundary")
        elif name.startswith("warm_rpc.") and name.removeprefix("warm_rpc.") in WARM_FIELDS:
            field = name.removeprefix("warm_rpc.")
            old_name = "warm_echo." + field
            if old_name in matched_warm:
                old_value = Decimal(matched_warm[old_name]["value"])
                if unit != matched_warm[old_name]["unit"]:
                    extra.append("metric-unit-mismatch")
            else:
                old_name = field if field in reference["metrics"] else old_name
                extra.append("matched-phase0-warm-raw-population-required")
        else:
            extra.append("no-equivalent-phase0-boundary")
        if old_value is None and old_name in reference["metrics"]:
            prior = reference["metrics"][old_name]
            if prior.get("run_level_outliers"):
                extra.append("reference-metric-material-run-outlier")
            old_value = number(prior["run_representatives"]["median"])
            old_unit = {"microseconds": "us", "nanoseconds": "ns"}.get(prior["unit"], prior["unit"])
            if unit != old_unit:
                extra.append("metric-unit-mismatch")
        if old_value is None:
            extra.append("missing-reference-metric")
        incompatible = sorted(set(incompatible + extra))
        delta = value - old_value if not incompatible else None
        ratio = delta * 100 / old_value if delta is not None and old_value else None
        comparisons.append({"phase1_metric": name, "phase0_metric": old_name, "unit": unit,
            "phase1_value": decimal_string(value), "phase0_value": decimal_string(old_value) if old_value is not None else None,
            "status": "not_comparable" if incompatible else "comparable", "reasons": incompatible,
            "delta": decimal_string(delta) if delta is not None else None,
            "relative_change_percent": decimal_string(ratio.quantize(Decimal("0.000001"))) if ratio is not None else None})
    comparable = sum(item["status"] == "comparable" for item in comparisons)
    return {"comparisons": comparisons, "summary": {"comparable_metrics": comparable,
        "not_comparable_metrics": len(comparisons)-comparable,
        "all_requested_metrics_comparable": bool(comparisons) and comparable == len(comparisons)}}
