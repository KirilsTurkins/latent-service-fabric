"""The separate, fixed #100 population; the #98 presets remain unchanged."""
from __future__ import annotations

from tools.optimization_runner.plans import SERVICES, cases

CONTROL = "07739c63d23cd57e86d21c5c129fa263208ad2fc"
VARIANTS = ("control", "candidate")
SOURCE_CONTROLS = (
    "rust-toolchain.toml", ".cargo/config.toml", "tools/phase0_build_environment.sh",
    "tools/build_optimization_bench.sh", "tools/optimization-bench/Cargo.toml",
    "tools/optimization-bench/src/client", "tools/optimization-bench/src/bin/optimization-client.rs",
    "tools/optimization-bench/src/lib.rs",
    "tools/optimization-workloads", "tools/toolchain-smoke/examples/optimization_capsule",
    "tools/toolchain-smoke/Cargo.toml", "api/proto", "examples/echo-contract/capsule.json",
    "examples/echo-contract/deployment.json", "apps/latent/src", "apps/latent/Cargo.toml",
)
SERVER_RECIPE = ("source tools/phase0_build_environment.sh; "
                 "phase0_reject_inherited_build_overrides; phase0_reject_hidden_cargo_configuration; "
                 "phase0_release_cargo build -p latentd --bin latentd --release --locked")
HARNESS_COMMAND = ["/bin/bash", "tools/build_optimization_bench.sh", "full"]


def plan(profile: str) -> dict:
    if profile not in ("smoke", "full"):
        raise ValueError("invalid-revision-profile")
    identifiers = {"warm-echo", "compute", "transform", "cache-working-set",
                   *(f"budget-{n}ms" for n in (1, 2, 5, 10))}
    selected = [case for case in cases(profile) if case["id"] in identifiers]
    mixed = {**selected[0]["client_plan"], "services": [name for name in SERVICES for _ in range(2)],
             "warmup_attempts": 10, "measured_attempts": 100 if profile == "full" else 20}
    selected.append({"id": "cache-mixed", "client_plan": mixed})
    return {"schema": "latent.optimization.revision-plan.v1", "profile": profile,
            "repetitions": 7 if profile == "full" else 1, "scenarios": ["cold-restart"],
            "cases": selected, "maximum_run_seconds": "7200" if profile == "full" else "600",
            "maximum_build_seconds": "10800", "maximum_artifact_bytes": str(2 * 1024**3),
            "build_profile": "release", "pair_order": "odd-control-candidate-even-candidate-control"}


def population(profile: str):
    for repetition in range(1, plan(profile)["repetitions"] + 1):
        for variant in VARIANTS if repetition % 2 else reversed(VARIANTS):
            yield repetition, variant


def run_id(repetition: int, variant: str, case: str) -> str:
    return f"p{repetition:02}-v{VARIANTS.index(variant)}-{case}"
