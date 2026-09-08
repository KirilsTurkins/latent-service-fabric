"""The fixed five-component/four-slot population; legacy presets are unchanged."""
from tools.optimization_evidence.common import require, uint

COLLECTOR = "standalone::measurements::comparison::cache::phase1_cache_collector"
DIRECT = {"readiness_acquisitions": "2", "materializations": "1", "executions": "1", "releases": "9"}


def plan(profile, repetition=1, variant=None):
    require(profile in ("smoke", "full") and (variant is None or variant in ("control", "candidate")), "cache-behavior-plan")
    require(type(repetition) is int and 1 <= repetition <= (7 if profile == "full" else 1), "cache-behavior-repetition")
    return {"schema": "latent.optimization.cache-behavior-plan.v1", "profile": profile, "repetition": repetition}


def population(profile):
    plan(profile)
    attempts = 802 if profile == "full" else 80
    return attempts, 2 * attempts + 13


def maximum_seconds(profile):
    plan(profile)
    return 300


def sequences(profile):
    full = profile == "full"
    return [("warmup", [0], 40 if full else 2), ("baseline", [0], 400 if full else 4),
            ("round-robin-warmup", list(range(5)), 5), ("round-robin", list(range(5)), 100 if full else 10),
            ("locality-warmup", [n for n in range(5) for _ in range(2)], 10),
            ("locality", [n for n in range(5) for _ in range(2)], 100 if full else 20)]


def tokens(profile):
    result = [("checkpoint", "empty")]
    for phase, _, count in sequences(profile):
        for index in range(count):
            result.append(("invoke", phase, index))
            if (index + 1) % 16 == 0 or index + 1 == count:
                result.append(("preparation-events", phase))
        result.append(("checkpoint", "after-" + phase))
    result.extend(("explicit-release", "ownership-reset", key) for key in range(5))
    result.extend([("checkpoint", "ownership-empty"), ("direct-readiness",), ("checkpoint", "held-two-ready"),
                   ("checkpoint", "held-ready-and-active"), ("preparation-events", "held-prepared")])
    result.extend(("invoke", "ownership-evict", index) for index in range(4))
    result.extend([("checkpoint", "evicted-held-ready-and-active"), ("preparation-events", "held-evicted"),
                   ("direct-execution",), ("checkpoint", "evicted-held-ready"), ("invoke", "ownership-recompile", 0),
                   ("checkpoint", "resident-new-and-evicted-old"), ("checkpoint", "released-old-ready"),
                   ("invoke", "ownership-invalid", 0), ("failed-refill-accounting",), ("invoke", "ownership-healthy", 0),
                   ("preparation-events", "ownership-complete"), ("checkpoint", "ownership-complete")])
    result.extend(("explicit-release", "concurrent-reset", key) for key in range(1, 5))
    result.extend([("checkpoint", "before-concurrent"), ("burst",), ("preparation-events", "after-concurrent"),
                   ("checkpoint", "after-concurrent")])
    result.extend(("invoke", "healthy", index) for index in range(8 if profile == "full" else 2))
    result.extend([("preparation-events", "healthy"), ("preparation-events", "complete"), ("checkpoint", "after-healthy")])
    return result


def expected(profile, anchor):
    result = {}
    for phase, keys, count in [*sequences(profile), ("ownership-evict", [1, 2, 3, 4], 4),
                             ("ownership-recompile", [0], 1), ("ownership-invalid", [5], 1),
                             ("ownership-healthy", [0], 1), ("healthy", [0], 8 if profile == "full" else 2)]:
        for index in range(count):
            result[f"cache-{phase}-{index:04}"] = phase, index, keys[index % len(keys)], None
    origin, due = uint(anchor["origin_nanos"]), uint(anchor["cold_due_nanos"])
    require(due == origin + 16_000_000, "cache-concurrent-cold-offset")
    for index in range(128 if profile == "full" else 16):
        result[f"cold-concurrent-warm-{index:04}"] = "concurrent", index, 0, origin + index * 2_000_000
    for index, key in enumerate(range(1, 5)):
        result[f"cold-concurrent-cold-{index:04}"] = "concurrent", index, key, due
    return result
