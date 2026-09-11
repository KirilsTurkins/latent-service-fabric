"""Exact backend builds with a source-identical catalog work observer."""
from ..catalog.builds import CONTROLS as CATALOG_CONTROLS
from ..builds import validate_graph
from . import model

CONTROLS = (*CATALOG_CONTROLS,
            "apps/latentd/Cargo.toml",
            "apps/latentd/src/standalone/start.rs",
            "crates/latent-control-store/Cargo.toml",
            "crates/latent-control-store/src/lib.rs",
            "crates/latent-control-store/src/deployments/observation.rs",
            "crates/latent-control-store/src/deployments/observation")


def validate(value, artifacts, profile):
    validate_graph(value, artifacts, profile, schema=model.BUILD_SCHEMA,
                   source_controls=CONTROLS)
    from .fixtures import load
    load(value["harness"]["echo"], artifacts)
    return value
