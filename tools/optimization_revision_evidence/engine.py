"""Actual external warm defaults; never infer server CPU from the matrix."""
from .ownership import cache_warmth, cleanup
from .recovery import comparisons


def aggregate(value):
    value["schema"] = "latent.optimization.engine-warm-aggregate.v1"
    value["scope"] = "lsf-revisions-shared-external-client-engine-default-preservation"
    value["comparisons"] = comparisons(value["comparisons"])
    value["limitations"] = [
        "Only old-control D0 and candidate D0 run this unchanged external warm-echo slice.",
        "All warmup offers are retained, including first preparation; no hidden prewarm is added.",
        "Every offered outcome stays in its denominator; successful latency is conditional on success.",
        "Throughput spans first scheduled measured offer through final completion, including gaps.",
        "Server/client CPU and RSS cover their batches including warmup and observation, not per-call CPU or instantaneous peak memory.",
        "The separate five-profile collector combines node/client CPU in one process and cannot replace this external boundary.",
        "Other engine profiles require their own predeclared external slice before a warm-default performance claim.",
        "Historical #104 and #105 observations remain separate; their medians are not subtracted from this comparison.",
        "Build and collection have independent 7200 s bounds; smoke is incomplete evidence and seven pairs do not establish a universal SLO."]
    return value
