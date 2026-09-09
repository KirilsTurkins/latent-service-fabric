"""The generic-only lifecycle fixture in the shared exact-ref build pass."""
from __future__ import annotations

import os
from tools import run_optimization_benchmarks as legacy
from tools.artifact_identity_runner.helpers import command
from . import backend
from .build import source

SCHEMA = "latent.optimization.budget-lifecycle-builds.v1"
CONTROLS = (*backend.CONTROLS, *backend.COLD_CONTROLS,
            "apps/latentd/src/standalone/measurements/fixtures.rs",
            "apps/latentd/src/standalone/measurements/fixtures/generic.rs",
            "crates/latent-core/src/deadline_diagnostic_observer.rs",
            "crates/latent-core/src/deadline_wait_observer.rs",
            "apps/latentd/src/config/policy.rs", "apps/latentd/src/standalone/load.rs",
            "tools/toolchain-smoke/examples/generic_capsule", "Cargo.lock")
GENERIC_RECIPE = (
    "source tools/phase0_build_environment.sh; "
    "phase0_reject_inherited_build_overrides; phase0_reject_hidden_cargo_configuration; "
    "cargo build -p latent-toolchain-smoke --example generic-capsule "
    "--target wasm32-unknown-unknown --release --locked; "
    'mkdir -p "${CARGO_TARGET_DIR}/capsules/generic"; '
    'wasm-tools component new "${CARGO_TARGET_DIR}/wasm32-unknown-unknown/release/examples/generic_capsule.wasm" '
    '-o "${CARGO_TARGET_DIR}/capsules/generic/generic-capsule.wasm"; '
    'wasm-tools validate "${CARGO_TARGET_DIR}/capsules/generic/generic-capsule.wasm"'
)
GENERIC_COMMAND = ["/bin/bash", "-eu", "-o", "pipefail", "-c", GENERIC_RECIPE]


def generic(root, target, output, deadline):
    directory = output / "builds" / "harness"
    directory.mkdir(parents=True)
    before = source(root)
    inputs = backend.inputs(root, "harness", output, CONTROLS)
    owner = command(GENERIC_COMMAND, directory / "build.log", 3600, root, deadline,
                    dict(os.environ, CARGO_TARGET_DIR=str(target)))
    component = legacy.retain(target / "capsules/generic/generic-capsule.wasm", output,
                              "generic/generic-capsule.wasm")
    after = source(root)
    if before != after:
        raise ValueError("budget-generic-build-source-changed")
    return {"source": before, "source_after": after, "inputs": inputs, "component": component,
            "command": GENERIC_COMMAND, "process": owner, "log": legacy.ref(directory / "build.log", output),
            "source_path": str(root), "target_path": str(target)}
