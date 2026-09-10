"""Exact backend-only build provenance with the common catalog helper closure."""
from tools.optimization_revision_runner import backend
from ..builds import validate_graph
from . import model

CONTROLS = (*backend.CONTROLS, *backend.COLD_CONTROLS,
            "apps/latentd/src/standalone/measurements.rs",
            "apps/latentd/src/standalone/measurements",
            "tools/optimization_backend_revision", "tools/artifact_identity_runner",
            "tools/artifact_identity_evidence", "tools/optimization_cache_lookup",
            "tools/optimization_evidence", "tools/optimization_runner",
            "tools/optimization_revision_runner/backend.py", "tools/optimization_revision_runner/build.py",
            "tools/optimization_revision_runner/collect.py", "tools/optimization_revision_evidence/identity.py",
            "tools/phase1_measurement_environment.py", "tools/run_optimization_benchmarks.py",
            "tools/build_optimization_backend_revision.py", "tools/run_optimization_backend_revision.py",
            "tools/validate_optimization_backend_revision.py", "tools/validate_phase1_archive.py",
            "tools/package_phase1_evidence.py", "tools/phase1_evidence", "Cargo.lock")


def validate(value, artifacts, profile):
    validate_graph(value, artifacts, profile, schema=model.BUILD_SCHEMA, source_controls=CONTROLS)
    from .fixtures import load
    load(value["harness"]["echo"], artifacts)
    return value
