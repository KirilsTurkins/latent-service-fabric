"""Exact-source libtests, three fixtures and an owned control-only setup graph."""
from tools.artifact_identity_evidence.identity import helper
from tools.optimization_evidence.common import fields, require
from tools.optimization_revision_runner import ownership_build
from ..builds import validate_graph
from . import fixtures, model


def validate(value, artifacts, profile):
    validate_graph(value, artifacts, profile, schema=ownership_build.SCHEMA,
                   source_controls=ownership_build.CONTROLS, fixture_field="components",
                   harness_command=ownership_build.COMMAND, extra_fields="fixture_generation")
    generation = fields(value["fixture_generation"], "variant plan identity input manifest raw command process log")
    require(generation["variant"] == "control", "ownership-generation-must-use-control")
    selected = artifacts.json(generation["plan"])
    require(selected == model.plan(selected["profile"], mode="fixtures"), "ownership-generation-plan")
    supplied = artifacts.json(generation["identity"])
    require(supplied == model.identity(value, "control", supplied["environment"]), "ownership-generation-source-or-binary-crossed")
    binary = value["builds"]["control"]["executables"]["backend"]
    argv = generation["command"]
    require(isinstance(argv, list) and len(argv) == 6 and argv[0].endswith("/" + binary["path"])
            and argv[1:] == ["--ignored", "--exact", model.COLLECTOR, "--nocapture", "--test-threads=1"],
            "ownership-generation-command")
    helper(generation["process"], binary["sha256"], generation["log"], artifacts)
    bootstrap = fields(artifacts.json(generation["input"]), "schema components payloads")
    require(bootstrap["schema"] == "latent.optimization.ownership-fixture-input.v1"
            and [row["id"] for row in bootstrap["components"]] == list(model.ARTIFACTS), "ownership-generation-input-population")
    for row, component in zip(bootstrap["components"], value["harness"]["components"], strict=True):
        fields(row, "id component contracts")
        require(row["component"] == component["component"] and (row["contracts"] is not None) == (row["id"] == "optimization"),
                "ownership-generation-input-crossed")
        if row["contracts"] is not None:
            from tools.optimization_runner.fixtures import contracts
            require(artifacts.json(row["contracts"]) == contracts(), "ownership-optimization-contract-changed")
    manifest = fixtures.load(generation["manifest"], artifacts, value["harness"]["components"])
    require(manifest["generation"] == generation["raw"] and manifest["payloads"] == bootstrap["payloads"],
            "ownership-generation-manifest-crossed")
    from .parse import parse
    raw = artifacts.json(generation["raw"], model.MAX_DOCUMENT_BYTES)
    parse(raw, selected, supplied, manifest, generation["input"]["sha256"], artifacts, "control")
    return value
