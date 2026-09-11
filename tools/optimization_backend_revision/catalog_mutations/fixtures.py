"""The unchanged #107 Echo fixtures; new evidence retains its own input refs."""
from tools.optimization_backend_revision.catalog.fixtures import (
    COMPONENT_HEADER, CONTRACT, NAME, TENANT, Fixture, component, contract_schema,
    load, name, normalize, selection_word, service,
)

__all__ = ["COMPONENT_HEADER", "CONTRACT", "NAME", "TENANT", "Fixture", "component",
           "contract_schema", "load", "name", "normalize", "selection_word", "service"]
