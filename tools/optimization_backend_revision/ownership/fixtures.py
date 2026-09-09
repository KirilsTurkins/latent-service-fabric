"""The one control-generated manifest, immutable across all measured children."""
from tools.optimization_evidence.common import fields, require, uint
from tools.optimization_evidence.workload import framed
from tools.optimization_runner.plans import cases
from . import model


def charge(value, *, near=False):
    fields(value, "maximum_bytes charged_bytes remaining_bytes")
    maximum, charged, remaining = (uint(value[key]) for key in ("maximum_bytes", "charged_bytes", "remaining_bytes"))
    require(maximum == 1048576 and charged + remaining == maximum and charged > 0, "ownership-context-charge-conservation")
    if near:
        require(512 <= remaining <= 1024, "ownership-near-context-headroom")
    return value


def load(reference, artifacts, components):
    value = artifacts.json(reference, 1024**2)
    fields(value, "schema artifacts payloads contexts generation")
    require(value["schema"] == "latent.optimization.ownership-fixtures.v1", "ownership-fixture-schema")
    require(isinstance(value["artifacts"], list) and [row.get("id") for row in value["artifacts"]] == list(model.ARTIFACTS),
            "ownership-fixture-component-population")
    for row, component in zip(value["artifacts"], components, strict=True):
        fields(row, "id component capsule contracts")
        require(row["component"] == component["component"], "ownership-fixture-build-component-crossed")
        for role in ("component", "capsule", "contracts"):
            artifacts.path(row[role])
        capsule = artifacts.json(row["capsule"], 1024**2)
        contracts = artifacts.json(row["contracts"], 1024**2)
        require(capsule["component"]["digest"] == row["component"]["sha256"]
                and contracts["format_version"] == 1, "ownership-fixture-metadata-identity")
        contract = {"optimization": "optimization:benchmark/workloads@0.1.0", "capabilities": "tests:capabilities/api@0.1.0",
                    "generic": "tests:generic/values@0.1.0"}[row["id"]]
        require(capsule["exports"] == ([contract, "tests:generic/alternate@0.1.0"] if row["id"] == "generic" else [contract]),
                "ownership-fixture-export-contract")
        require(any(interface["id"] == contract for item in contracts["contracts"] for interface in item["interfaces"]),
                "ownership-fixture-contract-missing")
    require(isinstance(value["payloads"], list) and [row.get("shape") for row in value["payloads"]] == list(model.SHAPES[:3]),
            "ownership-payload-population")
    original = {row["id"]: framed(row["client_plan"]["payload"]) for row in cases("full") if row["id"] in model.SHAPES}
    for row in value["payloads"]:
        fields(row, "shape artifact")
        require(uint(row["artifact"]["bytes"]) <= 131072
                and artifacts.path(row["artifact"]).read_bytes() == original[row["shape"]], "ownership-payload-not-external-frame")
    require(isinstance(value["contexts"], list) and [row.get("shape") for row in value["contexts"]] == list(model.SHAPES[3:]),
            "ownership-context-population")
    for row in value["contexts"]:
        fields(row, "shape artifact charge")
        charge(row["charge"], near=row["shape"] == "context-near-limit")
        context = artifacts.json(row["artifact"], 1024**2)
        fields(context, "schema shape claims baggage metadata")
        require(context["schema"] == "latent.optimization.ownership-context.v1" and context["shape"] == row["shape"],
                "ownership-context-fixture-crossed")
        expected = {"claims": {"role": "reader", "private.claim": "hidden"},
                    "baggage": {"locale": "en", "private.baggage": "hidden"},
                    "metadata": {"guest.visible": "ownership-invocation-000000000000", "internal.context": "hidden"}}
        content = 0
        for name, template in expected.items():
            require(isinstance(context[name], dict) and context[name].keys() == template.keys(), "ownership-context-map-keys")
            for key, item in context[name].items():
                require(isinstance(item, str) and "\0" not in item, "ownership-context-string")
                if key in ("role", "locale", "guest.visible") or row["shape"] == "context-small":
                    require(item == template[key], "ownership-context-visible-or-small-values")
                content += len(key.encode()) + len(item.encode())
        if row["shape"] == "context-64k":
            require(content == 65536, "ownership-context-64k-content")
        require(content <= uint(row["charge"]["charged_bytes"]), "ownership-context-content-exceeds-charge")
    artifacts.path(value["generation"])
    return value
