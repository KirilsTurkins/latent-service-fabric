"""Verify the exact transmitted fixture metadata and named startup segments."""

from pathlib import Path
from typing import Any

from .common import fields, read_json, require, uint, verify_artifact

NAMES = ("echo", "generic", "capabilities")
BOUNDARIES = {
    "catalog_open": "directory-artifact-and-deployment-open",
    "node_start": "standalone-start-with-open-catalogs-to-accepting",
    "client_connect": "persistent-loopback-tonic-channel-connect",
}


def startup(value: Any, measurements) -> None:
    fields(value, "unit catalog_open_nanos node_start_nanos client_connect_nanos boundaries excluded")
    require(value["unit"] == "ns" and value["boundaries"] == BOUNDARIES
            and value["excluded"] == ["fixture-loading", "runtime-construction"], "invalid-startup-boundaries")
    for name, boundary in BOUNDARIES.items():
        measurements.add("startup." + name, boundary, "ns", [value[name + "_nanos"]])


def fixture_inputs(value: Any, root: Path, identity: dict[str, Any]) -> list[dict[str, Any]]:
    fields(value, "fixtures")
    rows = value["fixtures"]
    require(isinstance(rows, list) and len(rows) == 3, "missing-fixture-inputs")
    expected = {item["name"]: item for item in identity["fixtures"]}
    seen = set()
    references = []
    for row in rows:
        fields(row, "name tenant service component_sha256 component_bytes capsule contracts deployment")
        name = row["name"]
        require(name in NAMES and name not in seen, "invalid-fixture-input-name")
        seen.add(name)
        require(row["component_sha256"] == expected[name]["sha256"]
                and row["component_bytes"] == expected[name]["bytes"], "fixture-component-identity-mismatch")
        require(row["tenant"] == ("examples" if name == "echo" else "tests")
                and row["service"] == "measurement-" + name, "fixture-input-scope-mismatch")
        documents = {}
        for role in ("capsule", "contracts", "deployment"):
            ref = row[role]
            require(isinstance(ref, dict) and ref.get("path") == f"fixture-inputs/{name}-{role}.json",
                    "invalid-fixture-input-path")
            require(uint(ref.get("bytes")) <= 1024 * 1024, "fixture-input-byte-limit")
            documents[role] = read_json(verify_artifact(root, ref))
            references.append(ref)
        capsule, contracts, deployment = (documents[key] for key in ("capsule", "contracts", "deployment"))
        require(isinstance(capsule, dict) and isinstance(deployment, dict)
                and isinstance(contracts, dict), "invalid-fixture-input-document")
        scope = {"tenant": row["tenant"], "name": row["service"]}
        require(all(capsule.get("metadata", {}).get(key) == item
                    and deployment.get("metadata", {}).get(key) == item for key, item in scope.items()),
                "fixture-manifest-scope-mismatch")
        require(capsule.get("component", {}).get("digest") == row["component_sha256"]
                and deployment.get("spec", {}).get("release") == row["component_sha256"]
                and deployment.get("spec", {}).get("service") == row["service"], "fixture-manifest-release-mismatch")
        # The Rust codec validates complete type descriptors before publication.
        # This independent boundary binds the retained descriptors to the exports.
        descriptors = contracts.get("contracts")
        require(contracts.get("format_version") == 1 and isinstance(descriptors, list) and descriptors,
                "invalid-fixture-contract-metadata")
        interfaces = [interface for descriptor in descriptors if isinstance(descriptor, dict)
                      for interface in descriptor.get("interfaces", [])]
        ids = [item.get("id") for item in interfaces if isinstance(item, dict)]
        require(len(ids) == len(interfaces) and ids and all(isinstance(item, str) for item in ids)
                and set(capsule.get("exports", [])) <= set(ids),
                "fixture-contract-export-mismatch")
    return references
