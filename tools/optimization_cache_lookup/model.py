"""Fixed common cache-get populations and independently reconstructible traces."""
from tools.optimization_evidence.common import require

COLLECTOR = "cache::measurement::cache_lookup_collector"
SYMBOL = "latent_wasmtime::cache::measurement::measured_cache_hits"
SEED = 0x4C53464341434845
CAPACITIES = (4, 64, 4096)
PATTERNS = ("mru-hot", "seeded-uniform")
MODES = ("normal", "allocation")


def plan(profile, repetition=1, variant="control", mode="normal", capacity=4, pattern="mru-hot"):
    require(profile in ("smoke", "full") and variant in ("control", "candidate"), "lookup-plan-selection")
    require(type(repetition) is int and 1 <= repetition <= (7 if profile == "full" else 1), "lookup-repetition")
    require(mode in MODES and type(capacity) is int and capacity in CAPACITIES and pattern in PATTERNS,
            "lookup-cell-selection")
    return {"schema": "latent.optimization.cache-lookup-plan.v1", "profile": profile,
            "repetition": repetition, "variant": variant, "mode": mode, "capacity": capacity,
            "pattern": pattern, "warmup_hits": 128 if profile == "full" else 16,
            "measured_hits": 16384 if profile == "full" else 256, "trace_seed": str(SEED),
            "maximum_output_bytes": "8388608", "observation_hold_millis": 100}


def suite_plan(profile):
    plan(profile)
    return {"schema": "latent.optimization.cache-lookup-suite-plan.v1", "profile": profile,
            "pairs": 7 if profile == "full" else 1, "capacities": list(CAPACITIES),
            "patterns": list(PATTERNS), "modes": list(MODES),
            "pair_order": "odd-control-candidate-even-candidate-control",
            "normal_timeout_seconds": 60, "allocation_timeout_seconds": 180,
            "profile_report_timeout_seconds": 120, "suite_timeout_seconds": 3600,
            "maximum_total_bytes": str(1024**3), "maximum_files": 4096,
            "measured_symbol": SYMBOL,
            "boundary": "cache-get-returned-tag-store-checksum-and-arc-drop-batch"}


def population(profile):
    for repetition in range(1, suite_plan(profile)["pairs"] + 1):
        arms = ("control", "candidate") if repetition % 2 else ("candidate", "control")
        for capacity in CAPACITIES:
            for pattern in PATTERNS:
                for mode in MODES:
                    for variant in arms:
                        yield repetition, variant, mode, capacity, pattern


def trace(selected):
    state, values = SEED, []
    for _ in range(selected["measured_hits"]):
        if selected["pattern"] == "mru-hot":
            index = selected["capacity"] - 1
        else:
            state ^= (state << 13) & (2**64 - 1)
            state ^= state >> 7
            state ^= (state << 17) & (2**64 - 1)
            index = state & (selected["capacity"] - 1)
        values.append(index)
    encoded = b"".join(value.to_bytes(2, "little") for value in values)
    checksum = sum((index + 1) * (value + 1) for index, value in enumerate(values))
    return encoded, checksum
