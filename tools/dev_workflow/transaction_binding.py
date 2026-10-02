"""Finite structural compatibility checks; namespace admission remains host-owned."""
from __future__ import annotations

from pathlib import Path

from . import paths
from .common import MAX_DOCUMENT, decode, members, require, sha

MAX_BINDING = 128 * 1024
HOST_ABI_DIGEST = "sha256:3b85f790f85ab23d36e492d7bd4a04a1b8aab87fc6f67dd7d7498bcf28129d35"
MEDIA_TYPE = "application/vnd.latent.transaction-binding.v1+json"


def identity(value: object) -> str:
    require(isinstance(value, str) and "\0" not in value, "transaction-binding-identity")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise ValueError("transaction-binding-identity") from error
    require(0 < size <= 256, "transaction-binding-identity")
    return value


def validate(raw: bytes, *, capsule: str, deployment: str, binding: str) -> dict:
    value = members(decode(raw, MAX_BINDING), {"apiVersion", "kind", "capsule", "deployment", "binding",
        "profile", "hostAbiDigest", "namespace", "stateSchema", "operations"})
    require(value["apiVersion"] == "latent.dev/v1" and value["kind"] == "TransactionBinding",
            "transaction-binding-format")
    require(value["profile"] == "lsf-transaction-v1" and value["hostAbiDigest"] == HOST_ABI_DIGEST,
            "transaction-binding-profile")
    for key in ("capsule", "deployment", "binding", "namespace"):
        identity(value[key])
    require((value["capsule"], value["deployment"], value["binding"]) == (capsule, deployment, binding),
            "transaction-binding-link-mismatch")
    sha(value["stateSchema"])
    require(isinstance(value["operations"], list) and 0 < len(value["operations"]) <= 128,
            "transaction-binding-operations")
    names = set()
    for operation in value["operations"]:
        members(operation, {"operation", "mode", "inputFormat", "resultFormat"})
        for key in ("operation", "inputFormat", "resultFormat"):
            identity(operation[key])
        require(operation["mode"] in ("strict-command", "fresh-query")
                and operation["operation"] not in names, "transaction-binding-operations")
        names.add(operation["operation"])
    return value


def check_package(source: Path, artifacts: dict, capsule: dict) -> None:
    if "transactionBinding" not in artifacts:
        return
    deployment = decode(paths.read(source, artifacts["deployment"], MAX_DOCUMENT))
    require(deployment.get("spec", {}).get("service") == capsule.get("metadata", {}).get("name")
            and deployment.get("spec", {}).get("release") == capsule.get("component", {}).get("digest"),
            "transaction-binding-deployment-mismatch")
    name = deployment.get("metadata", {}).get("name")
    raw = paths.read(source, artifacts["transactionBinding"], MAX_BINDING)
    validate(raw, capsule=capsule.get("metadata", {}).get("name"), deployment=name, binding=name)
    recipe = decode(paths.read(source, artifacts["packageSource"], MAX_DOCUMENT))
    entries = [layer for layer in recipe.get("layers", []) if isinstance(layer, dict)
               and layer.get("role") == "asset" and layer.get("mediaType") == MEDIA_TYPE]
    require(len(entries) == 1 and entries[0].get("path") == "transaction-binding.json",
            "transaction-binding-package-asset-required")
    selected = entries[0].get("source")
    require(isinstance(selected, str), "transaction-binding-package-source")
    require(paths.read(source / Path(artifacts["packageSource"]).parent, selected, MAX_BINDING) == raw,
            "transaction-binding-package-bytes-mismatch")
