"""Five fresh owners per block; candidate configuration contrasts share D0."""
from copy import deepcopy

from tools.optimization_evidence.common import require

SCHEMA = "latent.optimization.engine-suite.v1"
COLLECTOR = "standalone::measurements::comparison::engine::phase1_engine_collector"
COMPONENTS = ("echo", "optimization", "generic", "capabilities", "engine-memory")
MAX_DOCUMENT_BYTES = 32 * 1024**2
MAX_ROW_BYTES = 256 * 1024
MAX_SAMPLES = 2048
MAX_TOTAL_BYTES = 1024**3
MAX_FILES = 4096
MAX_SECONDS = 300
SUITE_SECONDS = 10800
PROFILES = {
    "D0": {"allocator": "on-demand", "optimization": "speed"},
    "P0": {"allocator": "pooling", "optimization": "speed"},
    "D1": {"allocator": "on-demand", "optimization": "speed-and-size"},
    "P1": {"allocator": "pooling", "optimization": "speed-and-size"},
}
BASE_ROWS = (("control", "D0"), ("candidate", "D0"), ("candidate", "P0"),
             ("candidate", "D1"), ("candidate", "P1"))
CONTRASTS = (("default-preservation", ("control", "D0"), ("candidate", "D0")),
             ("pooling-speed", ("candidate", "D0"), ("candidate", "P0")),
             ("speed-and-size-on-demand", ("candidate", "D0"), ("candidate", "D1")),
             ("pooling-speed-and-size", ("candidate", "D0"), ("candidate", "P1")))


def repetitions(profile):
    require(profile in ("smoke", "full"), "engine-profile")
    return 7 if profile == "full" else 1


def population(profile):
    result = []
    for repetition in range(1, repetitions(profile) + 1):
        rotation = (repetition - 1) % len(BASE_ROWS)
        rows = BASE_ROWS[rotation:] + BASE_ROWS[:rotation]
        if repetition % 2 == 0:
            rows = tuple(reversed(rows))
        for ordinal, (variant, engine_profile_id) in enumerate(rows):
            result.append({"repetition": repetition, "sequence_ordinal": ordinal,
                           "variant": variant, "engine_profile_id": engine_profile_id})
    return result


def plan(profile, repetition=1, variant="control", engine_profile_id="D0", sequence_ordinal=0):
    row = {"repetition": repetition, "sequence_ordinal": sequence_ordinal,
           "variant": variant, "engine_profile_id": engine_profile_id}
    require(type(repetition) is int and type(sequence_ordinal) is int
            and row in population(profile), "engine-row-selection")
    return {"schema": "latent.optimization.engine-plan.v1", "profile": profile, **row,
            "requested_engine": None if variant == "control" else deepcopy(PROFILES[engine_profile_id])}


def phases(profile):
    repetitions(profile)
    full = profile == "full"
    return [{"name": name, "warmup": warmup, "measured": measured, "batch_size": batch}
            for name, warmup, measured, batch in (
                ("echo", 40 if full else 2, 400 if full else 4, 1),
                ("compute", 4 if full else 1, 128 if full else 4, 1),
                ("memory", 2 if full else 1, 64 if full else 4, 1),
                ("concurrent-echo", 4, 128 if full else 8, 4))]


def counts(profile):
    offers = sum(row["warmup"] + row["measured"] for row in phases(profile)) + 24
    return {"invokes": offers, "commands": 2 * offers + 5 + 16,
            "functional_invokes": 24, "functional_commands": 53, "setup_commands": 16}


def suite_plan(profile):
    return {"schema": "latent.optimization.engine-matrix-plan.v1", "profile": profile,
            "repetitions": repetitions(profile), "rows": population(profile),
            "phases": phases(profile), "per_process": counts(profile),
            "maximum_run_seconds": str(MAX_SECONDS), "maximum_suite_seconds": str(SUITE_SECONDS),
            "maximum_artifact_bytes": str(MAX_TOTAL_BYTES), "maximum_artifact_files": MAX_FILES,
            "maximum_document_bytes": str(MAX_DOCUMENT_BYTES), "maximum_row_bytes": str(MAX_ROW_BYTES),
            "maximum_samples": MAX_SAMPLES, "memory_checkpoints": 64,
            "functional_identity_limit": 24, "functional_record_limit": 1024,
            "order": "rotate-left-block-minus-one-reverse-even-blocks",
            "contrasts": [{"id": name, "baseline": {"variant": left[0], "engine_profile_id": left[1]},
                           "candidate": {"variant": right[0], "engine_profile_id": right[1]}}
                          for name, left, right in CONTRASTS]}


def run_id(row):
    return (f"block-{row['repetition']:02}-row-{row['sequence_ordinal']:02}-"
            f"{row['variant']}-{row['engine_profile_id']}")


def identity(builds, variant, environment):
    require(variant in ("control", "candidate"), "engine-identity-variant")
    source = builds["builds"][variant]["source"]
    binary = builds["builds"][variant]["executables"]["backend"]
    return {"schema": "latent.phase1.measurement-identity.v1",
            "source": {**{name: source[name] for name in ("commit", "tree", "cargo_lock_sha256")}, "dirty": False},
            "build": builds["build"], "environment": environment,
            "binary": {name: binary[name] for name in ("sha256", "bytes")},
            "fixtures": [{"name": row["id"], **{name: row["component"][name] for name in ("sha256", "bytes")}}
                         for row in builds["harness"]["components"]]}
