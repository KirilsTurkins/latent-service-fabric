"""Generic-only recovery inputs in the existing single exact-ref build pass."""
from . import budget_build

SCHEMA = "latent.optimization.recovery-builds.v1"
CONTROLS = (*budget_build.CONTROLS, "tools/optimization_revision_runner/recovery.py",
            "crates/latent-wire/src/invocation/cleanup/snapshot.rs")
GENERIC_COMMAND = budget_build.GENERIC_COMMAND


def generic(root, target, output, deadline):
    return budget_build.generic(root, target, output, deadline, controls=CONTROLS)
