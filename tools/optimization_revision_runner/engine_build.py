"""Add four fixtures to the just-built shared optimization component, without Invokes.

build.collect calls this immediately after the engine external HARNESS_COMMAND
in the same owned source/target checkout. That command builds and validates the
optimization component at the harness ref; this helper retains those exact bytes.
"""
import os

from tools import run_optimization_benchmarks as legacy
from tools.artifact_identity_runner.helpers import command
from tools.optimization_runner import fixtures
from . import backend
from .build import source

SCHEMA = "latent.optimization.engine-builds.v1"
CONTROLS = (*backend.CONTROLS, *backend.COLD_CONTROLS,
            "apps/latentd/src/standalone/measurements/comparison.rs",
            "apps/latentd/src/standalone/measurements/fixtures.rs",
            "apps/latentd/src/standalone/measurements/fixtures",
            "tools/toolchain-smoke/examples/optimization_capsule",
            "tools/toolchain-smoke/examples/generic_capsule",
            "tools/toolchain-smoke/examples/capabilities_capsule",
            "tools/toolchain-smoke/examples/engine_memory",
            "tools/optimization-workloads", "tools/optimization_revision_runner/engine.py",
            "tools/optimization_revision_runner/engine_build.py", "Cargo.lock")
RECIPE = (
    "source tools/phase0_build_environment.sh; "
    "phase0_reject_inherited_build_overrides; phase0_reject_hidden_cargo_configuration; "
    "python3 tools/build_echo_capsule.py --verify-reproducible; "
    "cargo build -p latent-toolchain-smoke --example generic-capsule --example capabilities-capsule "
    "--target wasm32-unknown-unknown --release --locked; "
    'mkdir -p "${CARGO_TARGET_DIR}/capsules/generic" "${CARGO_TARGET_DIR}/capsules/capabilities" '
    '"${CARGO_TARGET_DIR}/capsules/engine-memory"; '
    'wasm-tools component new "${CARGO_TARGET_DIR}/wasm32-unknown-unknown/release/examples/generic_capsule.wasm" '
    '-o "${CARGO_TARGET_DIR}/capsules/generic/generic-capsule.wasm"; '
    'wasm-tools validate "${CARGO_TARGET_DIR}/capsules/generic/generic-capsule.wasm"; '
    'wasm-tools component new "${CARGO_TARGET_DIR}/wasm32-unknown-unknown/release/examples/capabilities_capsule.wasm" '
    '-o "${CARGO_TARGET_DIR}/capsules/capabilities/capabilities-capsule.wasm"; '
    'wasm-tools validate "${CARGO_TARGET_DIR}/capsules/capabilities/capabilities-capsule.wasm"; '
    'wasm-tools parse tools/toolchain-smoke/examples/engine_memory/component.wat '
    '-o "${CARGO_TARGET_DIR}/capsules/engine-memory/engine-memory-capsule.wasm"; '
    'wasm-tools validate "${CARGO_TARGET_DIR}/capsules/engine-memory/engine-memory-capsule.wasm"; '
    'wasm-tools component wit "${CARGO_TARGET_DIR}/capsules/engine-memory/engine-memory-capsule.wasm"'
)
HARNESS_RECIPE = RECIPE
COMMAND = ["/bin/bash", "-eu", "-o", "pipefail", "-c", RECIPE]
COMPONENTS = ("echo", "optimization", "generic", "capabilities", "engine-memory")


def generic(root, target, output, deadline):
    directory = output / "builds" / "harness"
    directory.mkdir(parents=True)
    before = source(root)
    inputs = backend.inputs(root, "harness", output, CONTROLS)
    owner = command(COMMAND, directory / "build.log", 3600, root, deadline,
                    dict(os.environ, CARGO_TARGET_DIR=str(target)))
    components = [{"id": name, "component": legacy.retain(
        target / f"capsules/{name}/{name}-capsule.wasm", output, f"components/{name}.wasm")}
        for name in COMPONENTS]
    contracts = output / "components" / "optimization-contracts.json"
    fixtures.write(contracts, fixtures.contracts())
    manifest = {"schema": "latent.optimization.engine-fixtures.v1", "components": [
        dict(row, contracts=legacy.ref(contracts, output) if row["id"] == "optimization" else None)
        for row in components]}
    fixtures.write(output / "engine-fixtures.json", manifest)
    after = source(root)
    if before != after:
        raise ValueError("engine-fixture-build-source-changed")
    return {"source": before, "source_after": after, "inputs": inputs, "components": components,
            "command": COMMAND, "process": owner, "log": legacy.ref(directory / "build.log", output),
            "source_path": str(root), "target_path": str(target)}
