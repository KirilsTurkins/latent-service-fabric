"""Five unchanged external workloads, kept separate from codec-only probes."""
from .ownership import cache_warmth, cleanup
from .recovery import comparisons


def aggregate(value):
    value["schema"] = "latent.optimization.codec-rpc-aggregate.v1"
    value["scope"] = "lsf-revisions-shared-external-client-typed-codec"
    value["comparisons"] = comparisons(value["comparisons"], identifiers=None)
    value["limitations"] = [
        "The five existing workload cases are unchanged; compute includes actual compute work and is not codec-only time.",
        "The first retained warmup includes cold preparation; no hidden prewarm is added.",
        "All offered outcomes remain in their denominators; successful latency is conditional on success and distinct from all-offered elapsed time.",
        "Throughput spans first scheduled measured offer through last completion, including gaps.",
        "Server/client CPU and RSS cover observed batches including warmup and observation; they are not per-call CPU or instantaneous peak memory.",
        "The 120 KiB payload remains below the effective 128 KiB transfer limit; the configured RPC and string bounds are separate.",
        "Codec-only CPU/allocation/peak has a separate exact-source population; external RPC exposes no per-call decoder path or timer counter.",
        "The prior #104 warm latency/CPU tradeoff is a separate historical observation, not a number subtracted from this comparison.",
        "Build-only and collection each have independent 7200 s bounds; smoke is protocol validation, and seven pairs are descriptive."]
    return value
