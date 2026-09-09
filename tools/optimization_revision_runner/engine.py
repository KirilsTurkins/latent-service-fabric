"""Default-preservation warm RPC slice, separate from the five-profile matrix."""
from tools.optimization_runner.plans import cases
from . import budget
from .model import population, run_id

EXPERIMENT = "engine"
SCHEMA = "latent.optimization.engine-warm-suite.v1"
BUILD_SCHEMA = "latent.optimization.engine-warm-builds.v1"
SOURCE_CONTROLS = (*budget.SOURCE_CONTROLS, "tools/optimization_revision_runner/engine.py")
HARNESS_RECIPE = budget.HARNESS_RECIPE
HARNESS_COMMAND = budget.HARNESS_COMMAND
node_config = budget.node_config


def plan(profile):
    if profile not in ("smoke", "full"):
        raise ValueError("invalid-engine-warm-profile")
    warm = next(row for row in cases(profile) if row["id"] == "warm-echo")
    return {"schema": "latent.optimization.engine-warm-plan.v1", "profile": profile,
            "repetitions": 7 if profile == "full" else 1, "scenarios": ["cold-restart"],
            "cases": [warm], "setup_cases": [], "maximum_run_seconds": "7200",
            "maximum_build_seconds": "7200", "maximum_artifact_bytes": str(1024**3),
            "build_profile": "release", "pair_order": "odd-control-candidate-even-candidate-control",
            "timer_observation": "unavailable-external-daemon-not-instrumented"}
