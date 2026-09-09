"""Fixed #104 payload populations using the unchanged external RPC client."""
from tools.optimization_runner.plans import cases
from . import budget
from .model import population, run_id

EXPERIMENT = "ownership"
SCHEMA = "latent.optimization.ownership-rpc-suite.v1"
BUILD_SCHEMA = "latent.optimization.ownership-rpc-builds.v1"
SOURCE_CONTROLS = (*budget.SOURCE_CONTROLS, "tools/optimization_revision_runner/ownership.py")
HARNESS_RECIPE = budget.HARNESS_RECIPE
HARNESS_COMMAND = budget.HARNESS_COMMAND
node_config = budget.node_config
CASE_IDS = ("warm-echo", "payload-64k", "payload-near-limit")


def plan(profile: str) -> dict:
    if profile not in ("smoke", "full"):
        raise ValueError("invalid-ownership-rpc-profile")
    selected = {row["id"]: row for row in cases(profile)}
    return {"schema": "latent.optimization.ownership-rpc-plan.v1", "profile": profile,
            "repetitions": 7 if profile == "full" else 1, "scenarios": ["cold-restart"],
            "cases": [selected[name] for name in CASE_IDS], "setup_cases": [],
            "maximum_run_seconds": "7200", "maximum_build_seconds": "7200",
            "maximum_artifact_bytes": str(1024**3), "build_profile": "release",
            "pair_order": "odd-control-candidate-even-candidate-control",
            "timer_observation": "unavailable-external-daemon-not-instrumented"}
