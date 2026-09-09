"""Payload RPC results retain both successful and all-offered populations."""
from tools.optimization_evidence.common import require, uint
from tools.phase1_cleanup_shutdown import validate_cleanup_shutdown
from .recovery import comparisons


def cleanup(value, variant):
    report = value["report"]
    require("cleanup" in report, "ownership-rpc-cleanup-unavailable")
    validate_cleanup_shutdown(report["cleanup"], require)
    require(report["cleanup"]["capacity"] == 68, "ownership-rpc-cleanup-capacity")
    return report["cleanup"]


def cache_warmth(value, identifier):
    before, after, change = (value[key] for key in ("before", "after", "delta"))
    require(uint(before["maximumConcurrentPreparations"]) == uint(after["maximumConcurrentPreparations"]) == 4,
            "ownership-rpc-preparation-bound")
    require(uint(before["entries"]) == (0 if identifier == "warm-echo" else 1)
            and uint(after["entries"]) == 1
            and uint(change["misses"]) == (1 if identifier == "warm-echo" else 0),
            "ownership-rpc-cache-population-changed")
    require(uint(change["evictions"]) == uint(change["invalidations"]) == 0,
            "ownership-rpc-cache-residency-changed")


def aggregate(value):
    value["schema"] = "latent.optimization.ownership-rpc-aggregate.v1"
    value["scope"] = "lsf-revisions-shared-external-client-request-payload-ownership"
    value["comparisons"] = comparisons(value["comparisons"], identifiers=None)
    value["limitations"] = [
        "The three existing payload cases are unchanged; no extra prewarm invocation is added.",
        "The first case's retained warmup includes the one cold preparation; warmup is excluded from measured latency distributions.",
        "All offered outcomes remain in their denominators; successful-response latency is conditional on success.",
        "The 120 KiB payload is below the effective 128 KiB per-transfer lifting allowance, independently of the configured 1 MiB RPC ceiling.",
        "Throughput uses first scheduled offer through last completion, not reciprocal latencies or build time.",
        "Server and client CPU/RSS cover the observed batch including warmup and observation; they are not per-call CPU or instantaneous peak memory.",
        "Direct backend timing, input-owner proofs and allocation profiles are separate evidence populations.",
        "Timer and raw-input ownership observations are unavailable in the external daemon; no zero values are inferred.",
        "Build-only and collection each have an independent 7200 s deadline; collection excludes already completed builds.",
        "Cgroup observations describe the shared runner. Smoke is incomplete evidence; seven pairs are descriptive observations."]
    return value
