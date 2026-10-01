"""Select original public package bytes and build metadata without signing them."""
from __future__ import annotations

import json
from pathlib import Path
import re

from tools.dev_workflow import paths, preflight
from tools.dev_workflow.common import digest, encode
from tools.phase2_operator_process import require


def _read(path: Path, maximum: int) -> bytes:
    return paths.read(path.parent, path.name, maximum)


def _layer(package: Path, manifest: dict, role: str, maximum: int):
    selected = [row for row in manifest["layers"]
                if row.get("annotations", {}).get("dev.latent.layer.role") == role]
    require(len(selected) == 1, "composition-probe-original-layer-required")
    row = selected[0]
    name = row["annotations"]["org.opencontainers.image.title"]
    # Package paths are validated by the ordinary publication owner. This
    # observer independently refuses traversals before opening original bytes.
    relative = paths.relative(name)
    raw = paths.read(package / "layers", relative, maximum)
    require(len(raw) == row["size"] and digest(raw) == row["digest"],
            "composition-probe-original-layer-changed")
    return raw, row["digest"]


def _exports(metadata: dict, names: list[str]):
    require(metadata["format_version"] == 1, "composition-probe-contract-format")
    result = []
    for name in names:
        declarations = [row for row in metadata["contracts"] if row["id"] == name]
        require(len(declarations) == 1, "composition-probe-original-contract-required")
        functions = [function["id"] for interface in declarations[0]["interfaces"]
                     for function in interface["functions"]]
        require(functions and len(set(functions)) == len(functions),
                "composition-probe-original-export-ambiguity")
        result.append({"contract": name, "functions": sorted(functions)})
    return result


def _imports(metadata: dict, surface: dict) -> list[str]:
    # The independent compiler surface lists callable interfaces. Nominal WIT
    # type owners are declared in the original signed contract metadata, and
    # the runtime's validated typeImports projection observes those same names.
    # Read declarations from those original bytes, never from the observation.
    result = set(surface["imports"])
    exported = set(surface["exports"])
    for name in surface["exports"]:
        declarations = [row for row in metadata["contracts"] if row["id"] == name]
        require(len(declarations) == 1, "composition-probe-original-contract-required")
        dependencies = declarations[0]["dependencies"]
        require(isinstance(dependencies, list) and len(dependencies) <= 64
                and all(isinstance(dependency, str) for dependency in dependencies)
                and len(set(dependencies)) == len(dependencies),
                "composition-probe-original-type-dependencies")
        for dependency in dependencies:
            preflight.contract(dependency)
        result.update(dependency for dependency in dependencies if dependency not in exported)
    require(len(result) <= 64, "composition-probe-original-import-bound")
    return sorted(result)


def java_component(package: Path, build: Path, target: dict, output: Path, identifier: str) -> dict:
    """Freeze a declaration from one independently built, already signed package.

    The caller selects the original deployment/publication/route tuple. The
    unsigned build surface is checked against the original manifest and build
    receipt, then compared with actual compiled preparation by the command.
    This function supplies neither admission nor invocation evidence.
    """
    require(re.fullmatch(r"[a-z][a-z0-9-]{0,31}", identifier) is not None,
            "composition-probe-component-slot")
    descriptor = _read(package / "manifest.json", 1024 * 1024)
    manifest = json.loads(descriptor)
    require(manifest["schemaVersion"] == 2
            and manifest["artifactType"] == "application/vnd.latent.capsule.v1"
            and len(manifest["layers"]) <= 64, "composition-probe-original-package-kind")
    component, component_digest = _layer(package, manifest, "component", 32 * 1024 * 1024)
    capsule_bytes, manifest_digest = _layer(package, manifest, "capsule-manifest", 256 * 1024)
    metadata_bytes, metadata_digest = _layer(package, manifest, "contracts", 1024 * 1024)
    capsule, metadata = json.loads(capsule_bytes), json.loads(metadata_bytes)
    built = json.loads(_read(build / "BUILD-COMPLETE.json", 262144))
    surface = json.loads(_read(build / "surface.json", 262144))
    require(built["packageAssembled"] is True
            and built["componentDigest"] == component_digest == capsule["component"]["digest"]
            and surface["world"] == capsule["component"]["world"]
            and surface["exports"] == capsule["exports"]
            and digest(_read(build / "contracts.json", 1024 * 1024)) == metadata_digest
            and set(row["contract"] for row in capsule["imports"]) <= set(surface["imports"]),
            "composition-probe-build-and-original-package-mismatch")
    budget = {name: None if value is None else str(value)
              for name, value in capsule["execution"]["limits"].items()}
    exports = _exports(metadata, surface["exports"])
    imports = _imports(metadata, surface)
    selected = {"id": identifier, "packageDigest": digest(descriptor),
                "componentDigest": component_digest, "releaseDigest": component_digest,
                "contractMetadataDigest": metadata_digest, "language": "java",
                "witShape": "nested-values-v1", "publicationKind": "capsule",
                "target": target, "imports": imports,
                "exports": exports, "budget": budget,
                "componentPath": identifier + "/component.wasm",
                "manifestPath": identifier + "/capsule.json", "manifestDigest": manifest_digest,
                "metadataPath": identifier + "/contracts.json"}
    preflight._component(selected)
    destination = output / identifier
    destination.mkdir(mode=0o700)
    for name, raw in (("component.wasm", component), ("capsule.json", capsule_bytes),
                      ("contracts.json", metadata_bytes)):
        with (destination / name).open("xb") as stream:
            stream.write(raw)
        (destination / name).chmod(0o600)
    with (destination / "original-identities.json").open("xb") as stream:
        stream.write(encode({"packageDigest": selected["packageDigest"],
            "componentDigest": component_digest, "contractMetadataDigest": metadata_digest,
            "manifestDigest": manifest_digest, "buildObservationDigest": built["observationDigest"]}))
    return selected
