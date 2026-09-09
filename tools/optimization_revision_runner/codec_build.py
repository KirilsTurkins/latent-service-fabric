"""Retain the codec-only libtest inputs without building unused guest binaries."""
from . import backend
from .build import source

SCHEMA = "latent.optimization.codec-builds.v1"
CONTROLS = ("crates/latent-wasmtime/src/values/tests/measurement.rs",
            "crates/latent-wasmtime/src/values/tests/measurement",
            "crates/latent-wasmtime/src/values/types.wasm",
            "crates/latent-wasmtime/src/values/types.wat",
            "crates/latent-wasmtime/src/preparation_observer.rs",
            *backend.COLD_CONTROLS, "crates/latent-wasmtime/Cargo.toml", "Cargo.lock",
            "rust-toolchain.toml", ".cargo/config.toml", "tools/phase0_build_environment.sh",
            "tools/optimization_revision_runner/codec.py", "tools/optimization_revision_runner/codec_build.py",
            "tools/optimization_codec/model.py", "tools/optimization_codec/fixtures.py")
PYTHON_INPUTS = ("tools/optimization_codec", "tools/optimization_revision_runner",
                 "tools/optimization_revision_evidence", "tools/optimization_backend_revision",
                 "tools/artifact_identity_runner", "tools/artifact_identity_evidence",
                 "tools/optimization_cache_lookup", "tools/run_optimization_backend_revision.py",
                 "tools/validate_optimization_backend_revision.py")


def harness(root, target, output, deadline):
    before = source(root)
    retained = backend.inputs(root, "harness", output, (*CONTROLS, *PYTHON_INPUTS))
    after = source(root)
    if before != after:
        raise ValueError("codec-harness-source-changed")
    return {"source": before, "source_after": after, "inputs": retained,
            "source_path": str(root), "target_path": str(target)}
