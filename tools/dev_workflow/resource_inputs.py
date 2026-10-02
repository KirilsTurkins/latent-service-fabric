"""Keep declared resource selection inside trust, watch and backend snapshots."""
from __future__ import annotations

import copy
import os
from pathlib import Path

from tools import guest_resources as resources

from . import dependencies, paths
from .common import DevError, digest, members, require, sha


def validate(value: dict) -> dict:
    members(value, {"manifestDigest"})
    sha(value["manifestDigest"])
    return value


def selected(root: Path) -> tuple[dict, list[dict]]:
    if not os.path.lexists(root / resources.MANIFEST):
        return {}, []
    raw = paths.read(root, resources.MANIFEST, resources.MAX_DOCUMENT)
    try:
        rows = resources.declarations({resources.MANIFEST: raw})
    except resources.ResourceError as error:
        raise DevError(error.code) from None
    return {"manifestDigest": digest(raw)}, rows


def bind(root: Path, descriptor: dict) -> dict:
    binding, rows = selected(root)
    supplied = descriptor.get("resourceInputs", {})
    require(not supplied or supplied == binding, "resource-trust-binding-drift")
    result = copy.deepcopy(descriptor)
    if not binding:
        require("resourceInputs" not in descriptor, "resource-trust-binding-without-declaration")
        return result
    result["resourceInputs"] = binding
    for name in [resources.MANIFEST, *(row["source"] for row in rows)]:
        paths.relative(name)
        require(not paths.excluded(name, tuple(result["exclude"])), "resource-input-excluded")
        if not dependencies.covered(name, result["inputRoots"]):
            result["inputRoots"].append(name)
    return result


def verify(root: Path, descriptor: dict) -> None:
    binding, rows = selected(root)
    require(descriptor.get("resourceInputs", {}) == binding, "resource-trust-binding-drift")
    spellings, leaves, total = {}, set(), 0
    for name in [resources.MANIFEST, *(row["source"] for row in rows)] if binding else []:
        require(dependencies.covered(name, descriptor["inputRoots"])
                and not paths.excluded(name, tuple(descriptor["exclude"])), "resource-input-not-snapshotted")
    try:
        for row in rows:
            resources.register(row["path"], spellings, leaves)
            total += len(paths.read(root, row["source"], resources.MAX_FILE))
            resources.require(total <= resources.MAX_TOTAL, "resource-byte-limit", "exhausted")
    except resources.ResourceError as error:
        raise DevError(error.code) from None
    if binding:
        require(digest(paths.read(root, resources.MANIFEST, resources.MAX_DOCUMENT)) == binding["manifestDigest"],
                "resource-trust-binding-drift")
