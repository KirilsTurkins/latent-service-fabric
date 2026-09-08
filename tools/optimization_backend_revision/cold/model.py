"""Fixed common-control populations for cold readiness and compiler evidence."""
from tools.optimization_evidence.common import require

COLLECTOR = "standalone::measurements::comparison::cold::phase1_cold_preparation_collector"


def plan(profile, repetition=1, variant="control"):
    require(profile in ("smoke", "full") and variant in ("control", "candidate"), "cold-plan-selection")
    require(type(repetition) is int and 1 <= repetition <= (7 if profile == "full" else 1), "cold-repetition")
    return {"schema": "latent.optimization.cold-plan.v1", "profile": profile,
            "repetition": repetition, "compiler_workers": 2 if variant == "candidate" else None}


def phases(profile):
    full = profile == "full"
    return [("warmup", 40 if full else 2), ("baseline", 400 if full else 4),
            ("same-key", 136 if full else 24), ("distinct", 133 if full else 21),
            ("cancel", 136 if full else 24), ("healthy", 8 if full else 2)]


def population(profile):
    attempts = sum(count for _, count in phases(profile))
    return attempts, 2 * attempts + 23


def maximum_seconds(profile):
    return 300 if profile == "full" else 120
