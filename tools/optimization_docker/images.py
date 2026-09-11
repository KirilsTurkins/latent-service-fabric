"""Pure bounded image contexts and actual Docker inspect projections."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

from tools.artifact_identity_runner.files import fingerprint, retain, total_bytes
from tools.optimization_evidence.common import verify_artifact
from .model import BASE_IMAGE, MAX_FILE_BYTES, MAX_TOTAL_BYTES

BASE = BASE_IMAGE
KINDS = ("lsf", "native", "client")
BINARIES = {"lsf": "latentd", "cli": "latent", "native": "optimization-native",
            "client": "optimization-client", "wrapper": "optimization-container"}


def prepare_contexts(build_receipt: dict, output_root: Path, repository: Path) -> dict:
    """The owner executes these contexts; this function invokes no Docker command."""
    if set(build_receipt["executables"]) != set(BINARIES):
        raise ValueError("docker-image-executable-set")
    sources = {key: verify_artifact(output_root, row, 256 * 1024**2)
               for key, row in build_receipt["executables"].items()}
    recipes = {}
    for name in ("app.Dockerfile", "client.Dockerfile"):
        relative = "tools/optimization-docker/" + name
        recipes[name] = verify_artifact(output_root, build_receipt["inputs"][relative], 64 * 1024)
        if fingerprint(repository / relative, 64 * 1024) != fingerprint(recipes[name], 64 * 1024):
            raise ValueError("docker-image-recipe-source-mismatch")
    # Two wrapper copies, one copy of each other retained executable, and the
    # three small recipes are the entire added context set. Check before writes.
    added = sum(fingerprint(path, MAX_FILE_BYTES)[1] for path in sources.values())
    added += fingerprint(sources["wrapper"], MAX_FILE_BYTES)[1]
    added += sum(fingerprint(recipes[name], 64 * 1024)[1]
                 for name in ("app.Dockerfile", "app.Dockerfile", "client.Dockerfile"))
    if total_bytes(output_root) + added > MAX_TOTAL_BYTES:
        raise ValueError("docker-image-context-total-bound")
    directory = output_root / "images" / "contexts"
    if directory.exists() or directory.is_symlink():
        raise ValueError("docker-image-contexts-not-fresh")
    result = {}
    for kind in KINDS:
        context = directory / kind
        context.mkdir(parents=True)
        recipe = recipes["client.Dockerfile" if kind == "client" else "app.Dockerfile"]
        recipe_ref = retain(recipe, context / "Dockerfile", output_root)
        selected = {"client": "optimization-client"} if kind == "client" else {
            "wrapper": "optimization-container", kind: "app/" + BINARIES[kind]}
        if kind == "lsf":
            selected["cli"] = "app/latent"
        files = {}
        for key, name in selected.items():
            destination = context / name
            files[key] = retain(sources[key], destination, output_root)
            destination.chmod(0o755)
        result[kind] = {"kind": kind, "base": BASE, "context": context.relative_to(output_root).as_posix(),
                        "dockerfile": recipe_ref, "executables": files,
                        "build_arguments": ["build", "--network=none", "--pull=false", "--file",
                                            str(context / "Dockerfile"), str(context)]}
    total_bytes(output_root)
    return result


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def inspect_receipt(kind: str, raw_image_inspect: dict | list, context: dict) -> dict:
    """Keep Engine IDs and OCI descriptors distinct; local RepoDigests may be empty."""
    if isinstance(raw_image_inspect, list):
        if len(raw_image_inspect) != 1:
            raise ValueError("docker-image-inspect-count")
        raw_image_inspect = raw_image_inspect[0]
    if (kind not in KINDS or not isinstance(raw_image_inspect, dict)
            or len(json.dumps(raw_image_inspect, ensure_ascii=False, allow_nan=False).encode()) > 2 * 1024**2
            or context.get("kind") != kind or context.get("base") != BASE):
        raise ValueError("docker-image-inspect-bound-or-context")
    row = raw_image_inspect
    config, rootfs, descriptor = row.get("Config"), row.get("RootFS"), row.get("Descriptor")
    digests = row.get("RepoDigests", [])
    if (not _digest(row.get("Id")) or row.get("Os") != "linux" or row.get("Architecture") != "amd64"
            or not isinstance(config, dict) or not isinstance(rootfs, dict) or rootfs.get("Type") != "layers"
            or not isinstance(rootfs.get("Layers"), list) or not 1 <= len(rootfs["Layers"]) <= 64
            or any(not _digest(value) for value in rootfs["Layers"])
            or not isinstance(digests, list) or len(digests) > 32
            or any(not isinstance(value, str) or len(value.encode()) > 1024
                   or re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", value) is None for value in digests)
            or type(row.get("Size")) is not int or not 0 < row["Size"] <= 1024**3):
        raise ValueError("docker-image-inspect-identity")
    executable = "optimization-client" if kind == "client" else "optimization-container"
    if config.get("Entrypoint") != ["/opt/lsf/" + executable]:
        raise ValueError("docker-image-entrypoint")
    if descriptor is not None and (not isinstance(descriptor, dict) or not _digest(descriptor.get("digest"))
                                   or descriptor.get("mediaType") not in (
                                       "application/vnd.oci.image.index.v1+json",
                                       "application/vnd.oci.image.manifest.v1+json",
                                       "application/vnd.docker.distribution.manifest.v2+json",
                                       "application/vnd.docker.distribution.manifest.list.v2+json")
                                   or type(descriptor.get("size")) is not int or not 0 < descriptor["size"] <= 2 * 1024**2):
        raise ValueError("docker-image-descriptor")
    return {"schema": "latent.optimization.docker-image.v1", "kind": kind, "image_id": row["Id"],
            "os": row["Os"], "architecture": row["Architecture"], "size_bytes": str(row["Size"]),
            "config": copy.deepcopy(config), "rootfs": copy.deepcopy(rootfs),
            "descriptor": copy.deepcopy(descriptor), "repo_digests": list(digests),
            "context": copy.deepcopy(context)}
