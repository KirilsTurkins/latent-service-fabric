#!/usr/bin/env python3
"""Reset only recognized echo fixtures owned by the repository validator."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_echo_capsule import resolve_target_root
from tools.build_observation import file_identity
from tools.build_process_signals import owned_cancellation
from tools.build_snapshot import SnapshotError, is_reparse, owned_child, remove_owned_directory


LEGACY_REQUIRED = frozenset({"build.json", "capsule.json", "echo-capsule.wasm", "interface.json",
    "sha256.txt", "interface/component.wit", "interface/deps/context.wit",
    "interface/deps/echo.wit", "interface/deps/log.wit"})
LEGACY_OPTIONAL = frozenset({"contracts.json", "deployment.json", "input.json"})
PACKAGE_REQUIRED = frozenset({"observation.json", "package-source.json", "echo-capsule.wasm",
    "capsule.json", "contracts.json", "wit-lock.json", "wit/context.wit", "wit/echo.wit", "wit/log.wit"})


def _inventory(directory: Path, required: frozenset[str], optional: frozenset[str],
               allowed_directories: set[str]) -> None:
    pending = [directory]
    files = set()
    entries = 0
    total = 0
    while pending:
        with os.scandir(pending.pop()) as children:
            for child in children:
                entries += 1
                if entries > 32:
                    raise SnapshotError("validator fixture contains unexpected entries")
                path = Path(child.path)
                owned_child(path, directory)
                if is_reparse(path):
                    raise SnapshotError("validator fixture contains a filesystem link")
                name = path.relative_to(directory).as_posix()
                if child.is_dir(follow_symlinks=False) and name in allowed_directories:
                    pending.append(path)
                elif child.is_file(follow_symlinks=False) and name in required | optional:
                    size = child.stat(follow_symlinks=False).st_size
                    maximum = 64 * 1024 * 1024 if name == "echo-capsule.wasm" else 256 * 1024
                    total += size
                    if not 0 < size <= maximum or total > 66 * 1024 * 1024:
                        raise SnapshotError("validator fixture exceeds its retained byte limits")
                    files.add(name)
                else:
                    raise SnapshotError("validator fixture contains an unknown file or directory")
    if not required <= files:
        raise SnapshotError("validator fixture is incomplete")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise SnapshotError("validator fixture has duplicate metadata fields")
        result[key] = value
    return result


def _metadata(directory: Path, name: str) -> dict:
    with (directory / name).open("rb") as source:
        data = source.read(256 * 1024 + 1)
    if len(data) > 256 * 1024:
        raise SnapshotError("validator fixture metadata exceeds its byte limit")
    result = json.loads(data, object_pairs_hook=_pairs)
    if not isinstance(result, dict):
        raise SnapshotError("validator fixture metadata is not an object")
    return result


def _recognized(directory: Path, package: bool) -> None:
    if package:
        _inventory(directory, PACKAGE_REQUIRED, frozenset(), {"wit"})
        marker = _metadata(directory, "observation.json")
        recipe = _metadata(directory, "package-source.json")
        if (type(marker.get("formatVersion")) is not int or marker["formatVersion"] != 1
                or marker.get("buildType") != "https://latent.dev/build/echo-capsule/v1"
                or type(recipe.get("formatVersion")) is not int or recipe["formatVersion"] != 1
                or recipe.get("name") != "echo-provenance" or recipe.get("kind") != "capsule"
                or recipe.get("entrypoint") != "echo-capsule.wasm"):
            raise SnapshotError("validator fixture is not the maintained observed echo profile")
        expected_digest, expected_size = marker.get("componentDigest"), marker.get("componentSize")
    else:
        _inventory(directory, LEGACY_REQUIRED, LEGACY_OPTIONAL, {"interface", "interface/deps"})
        marker = _metadata(directory, "build.json")
        if (type(marker.get("schemaVersion")) is not int or marker["schemaVersion"] != 1
                or marker.get("artifact") != "echo-capsule.wasm"
                or marker.get("cargoPackage") != "latent-toolchain-smoke"
                or marker.get("cargoTarget") != "echo-capsule"):
            raise SnapshotError("validator fixture is not the maintained legacy echo profile")
        expected_digest, expected_size = marker.get("contentDigest"), marker.get("sizeBytes")
    actual = file_identity(directory / "echo-capsule.wasm", "component", 64 * 1024 * 1024)
    capsule = _metadata(directory, "capsule.json")
    if (type(expected_size) is not int or expected_size != actual["size"]
            or expected_digest != actual["digest"] or not isinstance(capsule.get("component"), dict)
            or capsule["component"].get("digest") != actual["digest"]):
        raise SnapshotError("validator fixture component association has changed")


def reset_validation_echo(target_root: Path) -> int:
    """No configurable output paths: validate both fixed owners before deleting."""
    target_root = target_root.absolute()
    if not target_root.exists():
        return 0
    target_root = target_root.resolve(strict=True)
    retained = []
    with owned_cancellation() as cancellation:
        for name, package in (("echo", False), ("echo-provenance", True)):
            directory = target_root / "capsules" / name
            owned_child(directory, target_root)
            if os.path.lexists(directory):
                if not directory.is_dir():
                    raise SnapshotError("validator fixture path is not a directory")
                _recognized(directory, package)
                retained.append(directory)
            cancellation.check()
        with cancellation.defer():
            for directory in retained:
                remove_owned_directory(directory, target_root)
    return len(retained)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path)
    arguments = parser.parse_args()
    try:
        removed = reset_validation_echo(arguments.target_root or resolve_target_root())
    except (SnapshotError, OSError, ValueError, TypeError, KeyError, RecursionError):
        parser.exit(1, "error: echo reset refused; inspect the retained generated fixtures\n")
    print(json.dumps({"resetGeneratedEchoDirectories": removed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
