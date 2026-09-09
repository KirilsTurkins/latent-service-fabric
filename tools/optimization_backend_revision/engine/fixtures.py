"""One immutable five-component manifest; tenant variants are collector outputs."""
from tools.optimization_evidence.common import fields, read_json, require, sha256, uint
from tools.optimization_runner.fixtures import contracts
from . import model, namespace


def load(reference, artifacts, components):
    value = fields(artifacts.json(reference), "schema components")
    require(value["schema"] == "latent.optimization.engine-fixtures.v1", "engine-fixture-schema")
    rows = value["components"]
    require(isinstance(rows, list) and [row.get("id") for row in rows] == list(model.COMPONENTS),
            "engine-fixture-population")
    require(isinstance(components, list) and [row.get("id") for row in components] == list(model.COMPONENTS),
            "engine-build-fixture-population")
    for row, component in zip(rows, components, strict=True):
        fields(row, "id component contracts")
        fields(component, "id component")
        require(row["component"] == component["component"], "engine-fixture-component-crossed")
        maximum = 64 * 1024 if row["id"] == "engine-memory" else 16 * 1024**2
        require(8 <= uint(row["component"]["bytes"]) <= maximum, "engine-component-byte-bound")
        with artifacts.path(row["component"]).open("rb") as raw:
            require(raw.read(8) == b"\0asm\r\0\1\0", "engine-fixture-not-component")
        require((row["contracts"] is not None) == (row["id"] == "optimization"),
                "engine-fixture-contract-presence")
        if row["contracts"] is not None:
            require(artifacts.json(row["contracts"]) == contracts(), "engine-optimization-contracts-crossed")
    return value


def publication(rows, manifest, artifacts, parent, profile):
    from .schedule import TARGETS
    require(isinstance(rows, list) and len(rows) == 8, "engine-publication-population")
    components = {row["id"]: row for row in manifest["components"]}
    digests, shared = [], {}
    for index, (row, (tenant, service, contract, family)) in enumerate(zip(rows, TARGETS, strict=True)):
        fields(row, "index directory target artifact component publication preparation_key")
        require(row["index"] == str(index) and row["directory"] == f"fixtures/target-{index}", "engine-fixture-order")
        directory = parent / row["directory"]
        base = namespace.component(artifacts.path(components[family]["component"]).read_bytes(), family, tenant)
        require(row["component"]["path"] == "component.wasm"
                and artifacts.nested(directory, row["component"]).read_bytes() == base, "engine-tenant-component-not-exact")
        digest = sha256(base)
        digests.append(digest)
        require(row["target"] == {"tenant": tenant, "service": service, "contract": contract, "release_digest": digest},
                "engine-fixture-target-crossed")
        artifact = fields(row["artifact"], "component_sha256 component_bytes stored_descriptor_reference capsule contracts deployment")
        require(artifact["component_sha256"] == digest and uint(artifact["component_bytes"]) == len(base)
                and artifact["stored_descriptor_reference"] == "local:release:" + digest, "engine-fixture-published-release")
        documents = {}
        for name in ("capsule", "contracts", "deployment"):
            ref = artifact[name]
            require(ref["path"] == f"echo-{name}.json" and uint(ref["bytes"]) <= 1024**2, "engine-fixture-metadata-bound")
            documents[name] = read_json(artifacts.nested(directory, ref), 1024**2)
        capsule, metadata, deployment = (documents[name] for name in ("capsule", "contracts", "deployment"))
        require(capsule["component"]["digest"] == deployment["spec"]["release"] == digest
                and capsule["metadata"]["tenant"] == deployment["metadata"]["tenant"] == tenant
                and capsule["metadata"]["name"] == deployment["spec"]["service"] == service
                and deployment["metadata"]["name"] == tenant + "-" + service, "engine-fixture-scope-crossed")
        original, package, _ = namespace.PACKAGES[family]
        world = f"{tenant}:{package}/service@0.1.0"
        exports = namespace.exports(family, tenant)
        require(capsule["component"]["world"] == world and sorted(capsule["exports"]) == sorted(exports), "engine-fixture-world-or-exports-crossed")
        for budget in (capsule["execution"]["limits"], deployment["spec"]["resources"]):
            require(budget["cpuFuel"] == 10_000_000_000 and budget["memoryBytes"] == 67_108_864
                    and budget["logBytes"] == 16384 and budget["wallTimeLimitMillis"] == 5000, "engine-persisted-grant-crossed")
        fields(metadata, "format_version contracts")
        require(metadata["format_version"] == 1 and isinstance(metadata["contracts"], list)
                and sorted(item.get("id", "") for item in metadata["contracts"]) == sorted(exports),
                "engine-contract-surface-crossed")
        require(namespace.contracts(metadata, tenant, tenant) == metadata, "engine-contract-digest-crossed")
        normalized = namespace.contracts(metadata, tenant, original)
        if family == "optimization":
            require(normalized == contracts(), "engine-optimization-metadata-crossed")
        require(shared.setdefault(family, normalized) == normalized, "engine-tenant-contracts-diverged")
        receipt = fields(row["publication"], "release_digest deployment_id object_generation catalog_generation")
        require(receipt["release_digest"] == digest and receipt["deployment_id"] == tenant + "-" + service
                and receipt["catalog_generation"] == str(index + 1) and uint(receipt["object_generation"]) > 0,
                "engine-publication-receipt-crossed")
        require(row["preparation_key"] == {"release": digest, "engine_version": profile["wasmtime_version"],
                "engine_configuration_digest": profile["configuration"]["configuration-digest"],
                "target_triple": profile["target_triple"], "cpu_feature_set": profile["cpu_feature_set"]},
                "engine-preparation-policy-crossed")
    require(len(set(digests)) == 8, "engine-distinct-fixture-release-collapsed")
    return digests
