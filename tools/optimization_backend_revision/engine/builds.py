"""Validate the existing libtest provenance and the exact five input components."""
from tools.optimization_evidence.common import fields, require
from ..builds import validate_graph
from . import fixtures, model


def validate(value, artifacts, profile):
    from tools.optimization_revision_runner import engine_build
    fields(value, "schema requested_refs build builds harness cleanup fixtures")
    components = value["harness"]["components"]
    require(isinstance(components, list) and [row.get("id") for row in components] == list(model.COMPONENTS),
            "engine-build-five-components")
    # Reuse the unchanged source/build/owner checks and its maintained three-input
    # contract. Both additional inputs and the complete original list are checked
    # independently below; no retained receipt or artifact bytes are rewritten.
    by_id = {row["id"]: row for row in components}
    projected = dict(value, harness=dict(value["harness"], components=[by_id[name] for name in
                                                                    ("optimization", "capabilities", "generic")]))
    validate_graph(projected, artifacts, profile, schema=engine_build.SCHEMA,
                   source_controls=engine_build.CONTROLS, fixture_field="components",
                   harness_command=engine_build.COMMAND, extra_fields="fixtures")
    fixtures.load(value["fixtures"], artifacts, components)
    return value
