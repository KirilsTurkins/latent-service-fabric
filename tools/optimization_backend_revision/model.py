"""Finite diagnostic population and supplied identity construction."""
from tools.optimization_revision_runner.model import population
from tools.run_phase1_paired import plan

COLLECTOR = "standalone::measurements::comparison::revision::phase1_revision_backend_collector"


def identity(builds, variant, environment):
    source = builds["builds"][variant]["source"]
    binary = builds["builds"][variant]["executables"]["backend"]
    echo = builds["harness"]["echo"]["component"]
    return {"schema": "latent.phase1.measurement-identity.v1",
            "source": {**{name: source[name] for name in ("commit", "tree", "cargo_lock_sha256")}, "dirty": False},
            "build": builds["build"], "environment": environment,
            "binary": {name: binary[name] for name in ("sha256", "bytes")},
            "fixtures": [{"name": "echo", **{name: echo[name] for name in ("sha256", "bytes")}}]}
