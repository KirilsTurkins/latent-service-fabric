#!/usr/bin/env python3
"""Verify and reassemble a sharded Phase 0 raw-evidence archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


PROFILE_SCHEMA = "latent.phase0.hot-path.raw-evidence.parts.v1"
PORTABLE_SCHEMA = "latent.phase0.raw-evidence.parts.v1"
SUPPORTED_SCHEMAS = frozenset({PROFILE_SCHEMA, PORTABLE_SCHEMA})
MAX_PART_BYTES = 716_800
CHUNK_BYTES = 1024 * 1024


class ReassemblyError(Exception):
    """The checked-in fragment manifest or a fragment is invalid."""


def sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, f"sha256:{digest.hexdigest()}"


def load_manifest(archive_directory: Path) -> dict[str, Any]:
    manifest_path = archive_directory / "raw-evidence.parts.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReassemblyError(f"cannot read fragment manifest {manifest_path}: {error}") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") not in SUPPORTED_SCHEMAS
    ):
        raise ReassemblyError(f"fragment manifest has unexpected schema: {manifest_path}")
    if not isinstance(manifest.get("archive"), str) or not isinstance(
        manifest.get("archive_sha256"), str
    ):
        raise ReassemblyError("fragment manifest lacks an archive name or checksum")
    if not isinstance(manifest.get("archive_bytes"), int) or manifest["archive_bytes"] < 0:
        raise ReassemblyError("fragment manifest has an invalid archive size")
    parts = manifest.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ReassemblyError("fragment manifest has no parts")
    return manifest


def validated_part_path(archive_directory: Path, part: Any) -> tuple[Path, int, str]:
    if not isinstance(part, dict):
        raise ReassemblyError("fragment manifest contains a non-object part")
    name = part.get("path")
    size = part.get("bytes")
    checksum = part.get("sha256")
    if not isinstance(name, str) or Path(name).name != name:
        raise ReassemblyError(f"fragment path is not a local filename: {name!r}")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or size > MAX_PART_BYTES
        or not isinstance(checksum, str)
    ):
        raise ReassemblyError(f"fragment metadata is invalid: {name!r}")
    path = archive_directory / name
    observed_size, observed_checksum = sha256_file(path)
    if observed_size != size or observed_checksum != checksum:
        raise ReassemblyError(
            f"fragment verification failed for {path}: "
            f"size={observed_size} checksum={observed_checksum}"
        )
    return path, size, checksum


def reassemble(archive_directory: Path, output: Path) -> None:
    manifest = load_manifest(archive_directory)
    archive_name = manifest["archive"]
    if Path(archive_name).name != archive_name:
        raise ReassemblyError(f"archive name is not a local filename: {archive_name!r}")
    if output.exists():
        raise ReassemblyError(f"refusing to overwrite existing output: {output}")

    parts = [validated_part_path(archive_directory, part) for part in manifest["parts"]]
    part_paths = [path for path, _, _ in parts]
    if len(part_paths) != len(set(part_paths)):
        raise ReassemblyError("fragment manifest contains duplicate part paths")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        for path, _, _ in parts:
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
                    destination.write(chunk)

    observed_size, observed_checksum = sha256_file(output)
    if (
        observed_size != manifest["archive_bytes"]
        or observed_checksum != manifest["archive_sha256"]
    ):
        raise ReassemblyError(
            f"reassembled archive verification failed for {output}: "
            f"size={observed_size} checksum={observed_checksum}"
        )
    print(f"reassembled and verified {output} from {len(parts)} fragments")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        reassemble(arguments.archive_directory.resolve(), arguments.output)
    except ReassemblyError as error:
        print(f"phase0 archive reassembly failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
