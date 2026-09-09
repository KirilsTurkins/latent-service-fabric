"""Fixed #103 external population; existing client bytes and presets stay unchanged."""
from __future__ import annotations

from tools.optimization_runner.plans import cases
from .model import SOURCE_CONTROLS as REVISION_CONTROLS, population, run_id

EXPERIMENT = "budget"
SCHEMA = "latent.optimization.budget-suite.v1"
BUILD_SCHEMA = "latent.optimization.budget-builds.v1"
SOURCE_CONTROLS = (*REVISION_CONTROLS, "Cargo.lock",
                   "tools/optimization_revision_runner/budget.py")
HARNESS_RECIPE = (
    "source tools/phase0_build_environment.sh; "
    "phase0_reject_inherited_build_overrides; phase0_reject_hidden_cargo_configuration; "
    "phase0_release_cargo build -p latent -p latent-optimization-bench "
    "--bin latent --bin optimization-client --release --locked; "
    "cargo build -p latent-toolchain-smoke --example optimization-capsule "
    "--target wasm32-unknown-unknown --release --locked; "
    'mkdir -p "${CARGO_TARGET_DIR}/capsules/optimization"; '
    'wasm-tools component new "${CARGO_TARGET_DIR}/wasm32-unknown-unknown/release/examples/optimization_capsule.wasm" '
    '-o "${CARGO_TARGET_DIR}/capsules/optimization/optimization-capsule.wasm"; '
    'wasm-tools validate "${CARGO_TARGET_DIR}/capsules/optimization/optimization-capsule.wasm"'
)
HARNESS_COMMAND = ["/bin/bash", "-eu", "-o", "pipefail", "-c", HARNESS_RECIPE]


def plan(profile: str) -> dict:
    if profile not in ("smoke", "full"):
        raise ValueError("invalid-budget-profile")
    original = cases(profile)
    setup = {**original[0]["client_plan"], "warmup_attempts": 0, "measured_attempts": 1,
             "batch_size": 1}
    selected = [{"id": "prewarm-echo", "client_plan": setup}]
    selected.extend(item for item in original if item["id"] in {f"budget-{n}ms" for n in (1, 2, 5, 10)})
    return {"schema": "latent.optimization.budget-plan.v1", "profile": profile,
            "repetitions": 7 if profile == "full" else 1, "scenarios": ["cold-restart"],
            "cases": selected, "setup_cases": ["prewarm-echo"],
            "maximum_run_seconds": "3600" if profile == "full" else "600",
            "maximum_build_seconds": "10800", "maximum_artifact_bytes": str(1024**3),
            "build_profile": "release", "pair_order": "odd-control-candidate-even-candidate-control",
            "timer_observation": "unavailable-external-daemon-use-separate-lifecycle-diagnostic"}


def node_config(directory, data_directory):
    import json
    from tools.optimization_runner import fixtures
    path = fixtures.node_config(directory, data_directory)
    value = json.loads(path.read_bytes())
    value["workers"]["control"] = 4
    value["cache"].update(preparations=4, compilerWorkers=2)
    fixtures.write(path, value)
    return path
