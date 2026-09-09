"""Three maintained fixtures and one neutral-control generation in one build pass."""
import os

from tools import run_optimization_benchmarks as legacy
from tools.artifact_identity_runner.helpers import command, DirectoryLimits
from tools.optimization_evidence.workload import framed
from tools.optimization_runner import fixtures
from tools.optimization_runner.plans import cases
from tools.phase1_measurement_environment import host
from tools.optimization_backend_revision.ownership import model
from . import backend
from .build import source

SCHEMA = "latent.optimization.ownership-builds.v1"
CONTROLS = (*backend.CONTROLS, *backend.COLD_CONTROLS,
            "apps/latentd/src/standalone/measurements/fixtures.rs",
            "apps/latentd/src/standalone/measurements/fixtures",
            "crates/latent-wasmtime/src/invocation_input_observer.rs",
            "crates/latent-wasmtime/src/invocation_input_observer",
            "tools/toolchain-smoke/examples/optimization_capsule",
            "tools/toolchain-smoke/examples/generic_capsule",
            "tools/toolchain-smoke/examples/capabilities_capsule",
            "tools/optimization_revision_runner/ownership.py",
            "tools/optimization_revision_runner/ownership_build.py", "Cargo.lock")
RECIPE = (
    "source tools/phase0_build_environment.sh; "
    "phase0_reject_inherited_build_overrides; phase0_reject_hidden_cargo_configuration; "
    "cargo build -p latent-toolchain-smoke --example generic-capsule --example capabilities-capsule "
    "--target wasm32-unknown-unknown --release --locked; "
    'mkdir -p "${CARGO_TARGET_DIR}/capsules/generic" "${CARGO_TARGET_DIR}/capsules/capabilities"; '
    'wasm-tools component new "${CARGO_TARGET_DIR}/wasm32-unknown-unknown/release/examples/generic_capsule.wasm" '
    '-o "${CARGO_TARGET_DIR}/capsules/generic/generic-capsule.wasm"; '
    'wasm-tools validate "${CARGO_TARGET_DIR}/capsules/generic/generic-capsule.wasm"; '
    'wasm-tools component new "${CARGO_TARGET_DIR}/wasm32-unknown-unknown/release/examples/capabilities_capsule.wasm" '
    '-o "${CARGO_TARGET_DIR}/capsules/capabilities/capabilities-capsule.wasm"; '
    'wasm-tools validate "${CARGO_TARGET_DIR}/capsules/capabilities/capabilities-capsule.wasm"'
)
COMMAND = ["/bin/bash", "-eu", "-o", "pipefail", "-c", RECIPE]


def generic(root, target, output, deadline):
    directory = output / "builds" / "harness"
    directory.mkdir(parents=True)
    before = source(root)
    inputs = backend.inputs(root, "harness", output, CONTROLS)
    owner = command(COMMAND, directory / "build.log", 3600, root, deadline,
                    dict(os.environ, CARGO_TARGET_DIR=str(target)))
    components = [{"id": name, "component": legacy.retain(
        target / f"capsules/{name}/{name}-capsule.wasm", output, f"components/{name}.wasm")}
        for name in model.ARTIFACTS]
    after = source(root)
    if before != after:
        raise ValueError("ownership-fixture-build-source-changed")
    return {"source": before, "source_after": after, "inputs": inputs, "components": components,
            "command": COMMAND, "process": owner, "log": legacy.ref(directory / "build.log", output),
            "source_path": str(root), "target_path": str(target)}


def generate(output, builds, deadline, profile):
    """Only the retained control collector can size and freeze shared contexts."""
    directory = output / "fixtures"
    generated = directory / "generated"
    generated.mkdir(parents=True)
    contracts = directory / "optimization-contracts.json"
    fixtures.write(contracts, fixtures.contracts())
    payloads = []
    for row in cases(profile):
        if row["id"] not in model.SHAPES[:3]:
            continue
        path = directory / (row["id"] + ".bin")
        with path.open("xb") as stream:
            stream.write(framed(row["client_plan"]["payload"]))
        payloads.append({"shape": row["id"], "artifact": legacy.ref(path, output)})
    bootstrap = {"schema": "latent.optimization.ownership-fixture-input.v1",
                 "components": [dict(row, contracts=legacy.ref(contracts, output) if row["id"] == "optimization" else None)
                                for row in builds["harness"]["components"]], "payloads": payloads}
    input_path, plan_path, identity_path = (output / name for name in
                                         ("ownership-fixture-input.json", "fixture-plan.json", "fixture-identity.json"))
    for path, value in ((input_path, bootstrap), (plan_path, model.plan(profile, mode="fixtures")),
                        (identity_path, model.identity(builds, "control", host()))):
        fixtures.write(path, value)
    binary = builds["builds"]["control"]["executables"]["backend"]
    argv = [str(output / binary["path"]), "--ignored", "--exact", model.COLLECTOR, "--nocapture", "--test-threads=1"]
    env = dict(os.environ, LSF_PHASE1_COMPARISON_PLAN=str(plan_path), LSF_PHASE1_COMPARISON_IDENTITY=str(identity_path),
               LSF_PHASE1_COMPARISON_OUTPUT=str(generated), LSF_PHASE1_COMPARISON_DATA_ROOT=str(generated / "data"),
               LSF_OWNERSHIP_FIXTURES=str(input_path))
    owner = command(argv, directory / "generation.log", 90, output, deadline, env,
                    maximum=1024**2, watched=generated, remaining=32 * 1024**2,
                    directory_limits=DirectoryLimits(maximum_depth=2, maximum_files=32, maximum_entries=40,
                                                     maximum_file_bytes=model.MAX_DOCUMENT_BYTES))
    return {"variant": "control", "plan": legacy.ref(plan_path, output), "identity": legacy.ref(identity_path, output),
            "input": legacy.ref(input_path, output), "manifest": legacy.ref(output / "ownership-fixtures.json", output),
            "raw": legacy.ref(generated / "ownership.json", output), "command": argv, "process": owner,
            "log": legacy.ref(directory / "generation.log", output)}
