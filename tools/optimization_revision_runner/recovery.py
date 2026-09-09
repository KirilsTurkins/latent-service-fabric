"""Fixed #119 warm overhead population, separate from recovery correctness."""
from tools.optimization_runner.plans import cases
from . import budget
from .model import population, run_id

EXPERIMENT = "recovery"
SCHEMA = "latent.optimization.transport-warm-suite.v1"
BUILD_SCHEMA = "latent.optimization.transport-warm-builds.v1"
SOURCE_CONTROLS = (*budget.SOURCE_CONTROLS, "tools/optimization_revision_runner/recovery.py")
HARNESS_RECIPE = budget.HARNESS_RECIPE
HARNESS_COMMAND = budget.HARNESS_COMMAND
node_config = budget.node_config


def plan(profile: str) -> dict:
    if profile not in ("smoke", "full"):
        raise ValueError("invalid-transport-warm-profile")
    warm = cases(profile)[0]
    setup = {**warm["client_plan"], "warmup_attempts": 0, "measured_attempts": 1,
             "batch_size": 1}
    return {"schema": "latent.optimization.transport-warm-plan.v1", "profile": profile,
            "repetitions": 7 if profile == "full" else 1, "scenarios": ["cold-restart"],
            "cases": [{"id": "prewarm-echo", "client_plan": setup}, warm],
            "setup_cases": ["prewarm-echo"],
            "maximum_run_seconds": "1800" if profile == "full" else "600",
            "maximum_build_seconds": "10800", "maximum_artifact_bytes": str(1024**3),
            "build_profile": "release", "pair_order": "odd-control-candidate-even-candidate-control",
            "timer_observation": "unavailable-external-daemon-use-separate-recovery-diagnostic"}
