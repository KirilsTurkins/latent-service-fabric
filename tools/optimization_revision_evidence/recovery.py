"""Warm overhead replay for #119; recovery correctness has a separate graph."""
from decimal import Decimal

from tools.optimization_evidence.common import distribution, require
from tools.phase1_cleanup_shutdown import validate_cleanup_shutdown
from .budget import cache_warmth, configuration, failed_batches, failed_ownership


def cleanup(value, variant):
    """A missing new supervisor is unavailable only for the exact control arm."""
    value = value["report"]
    require(("cleanup" in value) == (variant == "candidate"), "transport-warm-cleanup-presence")
    if variant == "control":
        return None
    validate_cleanup_shutdown(value["cleanup"], require)
    require(value["cleanup"]["capacity"] == 68, "transport-warm-cleanup-configured-capacity")
    return value["cleanup"]


def aggregate(value):
    value["schema"] = "latent.optimization.transport-warm-aggregate.v1"
    value["scope"] = "lsf-revisions-shared-external-client-warm-transport-cleanup-overhead"
    value["comparisons"] = comparisons(value["comparisons"])
    value["timer_observation"] = {"status": "unavailable", "reason": "external-daemon-not-instrumented",
                                  "evidence": "separate-recovery-experiment"}
    value["limitations"] = [
        "The one-call prewarm and forty full-profile warmup calls remain retained but are excluded from measured distributions.",
        "Both variants execute LSF with the identical client, payload, 1000 ms envelope and one outstanding request.",
        "Every measured offer remains in outcome, all-offered elapsed and useful-success counts; successful-response latency is conditional on success.",
        "Throughput uses the first scheduled offer through the last completion, not reciprocal latencies or build time.",
        "Warm ordinary completions are not transport cleanup handoffs; disconnect recovery requires the separate 61-offer experiment.",
        "Control cleanup instrumentation is unavailable; its absence is never interpreted as zero work.",
        "External timer counts are unavailable; no OS or Tonic timer total is inferred from requests.",
        "Server/client CPU ticks and RSS cover the batch including warmup and observation overhead, not per-call CPU or instantaneous peak memory.",
        "Validated process counts include seed servers; provisioning and inventory CLI helpers are separate bounded overhead.",
        "Cgroup counters describe the shared runner, not isolated service resource use.",
        "Smoke remains incomplete evidence; seven pairs are descriptive observations, not significance or a production SLO."]
    return value


def comparisons(rows):
    rows = [row for row in rows if row["id"] == "warm-echo"]
    for row in rows:
        differences = {}
        for pair in row["pairs"]:
            contrasts = {}
            for metric in ("successful_response_latency_nanos", "all_offered_elapsed_nanos"):
                for quantile in ("median", "p95", "p99"):
                    key = f"{metric}_{quantile}"
                    left, right = (pair[arm][metric] for arm in ("control", "candidate"))
                    delta = None if left is None or right is None else Decimal(right[quantile]) - Decimal(left[quantile])
                    contrasts[key] = None if delta is None else str(delta)
                    if delta is not None:
                        differences.setdefault(key, []).append(delta)
            pair["candidate_minus_control_nanos"] = contrasts
        row["paired_differences_nanos"] = {key: distribution(values) for key, values in differences.items()}
    return rows
