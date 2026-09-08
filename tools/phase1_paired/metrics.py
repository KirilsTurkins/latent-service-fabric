"""Common semantic outcomes and independently measured timing populations."""

from ..phase1_evidence.common import fields, integer, require, uint
from ..phase1_evidence.statistics import distribution
from .common import TIMINGS


def observed(value, *, legacy=False):
    return integer(value, 0, 2**64-1) if legacy else uint(value)


def timing(value, *, legacy=False):
    require(isinstance(value, dict) and set(TIMINGS) <= value.keys(), "missing-paired-backend-timing")
    result = {key: observed(value[key], legacy=legacy) for key in TIMINGS}
    require(result["host_call_micros"] <= result["guest_call_micros"], "host-timing-not-subset")
    return result


def consumption(value, *, legacy=False):
    fields(value, "cpu_fuel peak_memory_bytes wall_time_micros log_bytes")
    result = {key: observed(item, legacy=legacy) for key, item in value.items()}
    require(0 < result["cpu_fuel"] <= 10_000_000_000 and 0 < result["peak_memory_bytes"] <= 16_777_216
            and result["log_bytes"] <= 16_384, "paired-consumption-exceeds-control")
    return result


def summarize(samples, warmup, preparation):
    selected = samples[warmup:]
    require(bool(selected), "missing-paired-measured-samples")
    values = {"initial_preparation_micros": [preparation],
              "semantic_invoke_elapsed_micros": [sample["elapsed"] for sample in selected]}
    for key in TIMINGS:
        values[key] = [sample["timing"][key] for sample in selected]
    return [{"name": name, "unit": "count" if name == "host_call_count" else "us",
             "boundary": boundary(name), "statistics": distribution(numbers)} for name, numbers in sorted(values.items())]


def boundary(name):
    if name == "semantic_invoke_elapsed_micros":
        return {"category": "wider-productionization-path", "control": "prepared-envelope-through-outcome-and-cell-disposition",
                "candidate": "persistent-loopback-rpc-invoke-through-terminal-receipt"}
    if name == "initial_preparation_micros":
        return {"category": "backend-api", "control": "component-prepare-after-engine-construction-empty-cache",
                "candidate": "component-prepare-after-engine-construction-empty-cache"}
    if name == "guest_call_micros":
        detail = "component-call-including-automatic-canonical-post-return"
    elif name == "component_post_return_micros":
        detail = "post-call-host-accounting-not-canonical-post-return"
    elif name == "host_call_micros":
        detail = "host-import-calls-subset-of-guest-call"
    elif name == "host_call_count":
        detail = "actual-host-import-call-count"
    elif name == "activation_resource_reclamation_micros":
        detail = "actual-activation-resource-drop-interval"
    else:
        detail = name.removesuffix("_micros").replace("_", "-")
    return {"category": "backend-internal-productionization-bundle", "control": detail, "candidate": detail}
