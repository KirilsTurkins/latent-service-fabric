"""Fixed direct populations; generation performs no invocation or guest Store."""
from tools.optimization_evidence.common import require
from tools.optimization_revision_runner.model import population as pairs

COLLECTOR = "standalone::measurements::comparison::ownership::phase1_ownership_collector"
SCHEMA = "latent.optimization.ownership-suite.v1"
SHAPES = ("warm-echo", "payload-64k", "payload-near-limit",
          "context-small", "context-64k", "context-near-limit")
ARTIFACTS = ("optimization", "capabilities", "generic")
MAX_DOCUMENT_BYTES = 8 * 1024**2
MAX_TOTAL_BYTES = 1024**3
MAX_FILES = 4096
STAGE_SECONDS = 7200
SYMBOLS = ("latentd::standalone::measurements::comparison::ownership::call::construct_invocation",
           "latentd::standalone::measurements::comparison::ownership::call::poll_invocation")


def plan(profile, repetition=1, mode="normal", shape=None):
    require(profile in ("smoke", "full") and mode in ("fixtures", "normal", "allocation"),
            "ownership-plan-selection")
    require(type(repetition) is int and 1 <= repetition <= (7 if profile == "full" and mode == "normal" else 1),
            "ownership-plan-repetition")
    require((shape in SHAPES) if mode == "allocation" else shape is None, "ownership-plan-shape")
    full = profile == "full"
    warmup = (4 if full else 1) if mode == "normal" else 1 if mode == "allocation" else 0
    measured = (32 if full else 3) if mode == "normal" else (8 if full else 2) if mode == "allocation" else 0
    return {"schema": "latent.optimization.ownership-plan.v1", "profile": profile, "mode": mode,
            "repetition": repetition, "shapes": list(SHAPES) if mode == "normal" else [shape] if mode == "allocation" else [],
            "warmup_per_shape": warmup, "measured_per_shape": measured,
            "proofs": ["cancel-pending", "drop-pending"] if mode == "normal" else [],
            "maximum_run_seconds": "180" if mode == "allocation" else "90",
            "maximum_output_bytes": str(MAX_DOCUMENT_BYTES)}


def suite_plan(profile):
    plan(profile)
    return {"schema": "latent.optimization.ownership-population.v1", "profile": profile,
            "normal_pairs": 7 if profile == "full" else 1, "allocation_pairs_per_shape": 1,
            "shapes": list(SHAPES), "normal": plan(profile),
            "allocation": [plan(profile, mode="allocation", shape=shape) for shape in SHAPES],
            "maximum_run_seconds": "7200", "maximum_artifact_bytes": str(MAX_TOTAL_BYTES),
            "maximum_artifact_files": MAX_FILES}


def population(profile):
    plan(profile)
    for repetition, variant in pairs(profile):
        yield repetition, variant, "normal", None
    for index, shape in enumerate(SHAPES):
        order = ("control", "candidate") if index % 2 == 0 else ("candidate", "control")
        for variant in order:
            yield 1, variant, "allocation", shape


def identity(builds, variant, environment):
    from ..model import identity as common
    components = builds["harness"]["components"]
    value = common(dict(builds, harness={"echo": {"component": components[0]["component"]}}), variant, environment)
    value["fixtures"] = [{"name": row["id"], **{key: row["component"][key] for key in ("sha256", "bytes")}}
                         for row in components]
    return value
