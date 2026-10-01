"""Bind captured dependency selection to approval and immutable source snapshots."""
from __future__ import annotations

import copy
import os
from pathlib import Path

from tools import application_dependencies as capture
from tools.application_dependency_store import DependencyError

from . import paths
from .common import DevError, decode, digest, encode, members, require, sha

OBJECTS = "dependency-inputs/objects"


def validate(value: dict) -> dict:
    members(value, {"applicationManifest", "applicationLock", "selection", "executableInputs"})
    sha(value["applicationManifest"])
    sha(value["applicationLock"])
    require(isinstance(value["selection"], dict), "dependency-selection-required")
    try:
        capture.metadata(value["selection"])
        require(isinstance(value["executableInputs"], list)
                and len(value["executableInputs"]) <= capture.MAX_ARTIFACTS, "dependency-executable-input-limit")
        for name in value["executableInputs"]:
            capture.label(name)
        require(len(set(value["executableInputs"])) == len(value["executableInputs"]),
                "dependency-executable-input-duplicate")
    except DependencyError as error:
        raise DevError(str(error)) from None
    # Apply the controller's document depth and item limits to derived fields too.
    decode(encode(value))
    return value


def selected(root: Path, language: str) -> tuple[dict, list[str]]:
    """Read only captured inputs; original repositories and source paths are unused."""
    manifest_present = os.path.lexists(root / capture.MANIFEST)
    lock_present = os.path.lexists(root / capture.LOCK)
    if not manifest_present:
        require(not lock_present, "dependency-manifest-missing")
        return {}, []
    require(lock_present, "dependency-lock-missing-resolve-and-review")
    manifest_bytes = paths.read(root, capture.MANIFEST, capture.MAX_LOCK)
    lock_bytes = paths.read(root, capture.LOCK, capture.MAX_LOCK)
    try:
        manifest = capture.validate_manifest(decode(manifest_bytes, capture.MAX_LOCK), language)
        lock = decode(lock_bytes, capture.MAX_LOCK)
        members(lock, {"formatVersion", "language", "manifestDigest", "selection", "nativeLocks", "artifacts",
                       "transformations", "completeness", "executableInputs"})
        require(type(lock["formatVersion"]) is int and lock["formatVersion"] == 1
                and lock["language"] == language and lock["manifestDigest"] == digest(manifest_bytes)
                and lock["selection"] == manifest["selection"]
                and lock["completeness"] == "selected-declared-closure", "dependency-lock-drift-resolve-and-review")
        executables = [item["id"] for item in manifest["artifacts"] if item["role"] == "build-tool"]
        require(lock["executableInputs"] == executables, "dependency-executable-input-drift")
        binding = validate({"applicationManifest": digest(manifest_bytes), "applicationLock": digest(lock_bytes),
                            "selection": manifest["selection"], "executableInputs": executables})
    except DependencyError as error:
        raise DevError(str(error)) from None
    inputs = [capture.MANIFEST, capture.LOCK, *manifest["nativeLocks"]]
    if manifest["artifacts"] or manifest["nativeLocks"]:
        inputs.append(OBJECTS)
    for name in inputs:
        paths.relative(name)
    return binding, inputs


def covered(name: str, roots: list[str]) -> bool:
    key = paths.alias(name)
    return any(key == paths.alias(root) or key.startswith(paths.alias(root) + "/") for root in roots)


def bind(root: Path, descriptor: dict) -> dict:
    """Derive approval inputs without making callers maintain digest fields by hand."""
    binding, inputs = selected(root, descriptor["language"])
    supplied = descriptor.get("dependencyInputs", {})
    require(not supplied or supplied == binding, "dependency-trust-binding-drift")
    result = copy.deepcopy(descriptor)
    if not binding:
        require("dependencyInputs" not in result, "dependency-trust-binding-without-capture")
        return result
    result["dependencyInputs"] = binding
    for name in inputs:
        require(not paths.excluded(name, tuple(result["exclude"])), "dependency-input-excluded")
        if not covered(name, result["inputRoots"]):
            result["inputRoots"].append(name)
    return result


def verify(root: Path, descriptor: dict) -> None:
    """Reject omitted, stale or corrupt capture before association and build reuse."""
    binding, inputs = selected(root, descriptor["language"])
    require(descriptor.get("dependencyInputs", {}) == binding, "dependency-trust-binding-drift")
    for name in inputs:
        require(covered(name, descriptor["inputRoots"])
                and not paths.excluded(name, tuple(descriptor["exclude"])), "dependency-input-not-snapshotted")
    if binding:
        try:
            verified = capture.verify_inputs(root, descriptor["language"])
            require(verified is not None and digest(verified.manifest_bytes) == binding["applicationManifest"]
                    and digest(verified.lock_bytes) == binding["applicationLock"], "dependency-trust-binding-drift")
        except DependencyError as error:
            raise DevError(str(error)) from None
