#!/usr/bin/env python3
"""Canonical native collector/build identity for Phase 0 evidence."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any


COLLECTOR_SCHEMA = "latent.phase0.native-collector.v1"
BUILD_CONFIGURATION_SCHEMA = "latent.phase0.native-release-build.v1"
EXPECTED_RELEASE_BUILD_CONFIGURATION: dict[str, Any] = {
    "schema_version": BUILD_CONFIGURATION_SCHEMA,
    "cargo_profile": "release",
    "opt_level": "3",
    "debug_info": 1,
    "debug_assertions": False,
    "overflow_checks": False,
    "lto": False,
    "panic": "unwind",
    "incremental": False,
    "codegen_units": 16,
    "strip": "none",
}
COLLECTOR_FIELDS = {
    "schema_version",
    "collector",
    "executable_digest",
    "executable_bytes",
    "build_configuration",
}
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class CollectorIdentityError(ValueError):
    """The native collector cannot be admitted as Phase 0 evidence."""


def require_native_collector_identity(
    value: Any, label: str, expected_collector: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CollectorIdentityError(f"{label} must be an object")
    if set(value) != COLLECTOR_FIELDS:
        missing = sorted(COLLECTOR_FIELDS - set(value))
        unexpected = sorted(set(value) - COLLECTOR_FIELDS)
        raise CollectorIdentityError(
            f"{label} fields differ from the canonical collector identity "
            f"missing={missing} unexpected={unexpected}"
        )
    if value.get("schema_version") != COLLECTOR_SCHEMA:
        raise CollectorIdentityError(f"{label} has an unexpected schema")
    if value.get("collector") != expected_collector:
        raise CollectorIdentityError(
            f"{label} must identify the {expected_collector!r} executable"
        )
    digest = value.get("executable_digest")
    if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
        raise CollectorIdentityError(f"{label} executable digest must be SHA-256")
    byte_count = value.get("executable_bytes")
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count <= 0:
        raise CollectorIdentityError(f"{label} executable bytes must be a positive integer")
    build_configuration = value.get("build_configuration")
    if json.dumps(
        build_configuration, sort_keys=True, separators=(",", ":")
    ) != json.dumps(
        EXPECTED_RELEASE_BUILD_CONFIGURATION,
        sort_keys=True,
        separators=(",", ":"),
    ):
        raise CollectorIdentityError(
            f"{label} does not use the canonical Phase 0 native release build configuration"
        )
    return {
        "schema_version": COLLECTOR_SCHEMA,
        "collector": expected_collector,
        "executable_digest": digest,
        "executable_bytes": byte_count,
        "build_configuration": dict(EXPECTED_RELEASE_BUILD_CONFIGURATION),
    }


def same_identity(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def verify_retained_native_collector(
    evidence_root: Path, value: Any, label: str, expected_collector: str
) -> dict[str, Any]:
    identity = require_native_collector_identity(value, label, expected_collector)
    directory = evidence_root / "collector"
    try:
        directory_metadata = directory.lstat()
    except OSError as error:
        raise CollectorIdentityError(
            f"{label} retained collector directory is missing: {error}"
        ) from error
    if not stat.S_ISDIR(directory_metadata.st_mode) or directory.is_symlink():
        raise CollectorIdentityError(
            f"{label} retained collector directory must be a regular directory"
        )
    try:
        entries = {entry.name for entry in directory.iterdir()}
    except OSError as error:
        raise CollectorIdentityError(
            f"cannot inspect {label} retained collector directory: {error}"
        ) from error
    if entries != {expected_collector}:
        raise CollectorIdentityError(
            f"{label} retained collector directory must contain exactly "
            f"{expected_collector!r}; observed={sorted(entries)}"
        )
    path = directory / expected_collector
    try:
        metadata = path.lstat()
    except OSError as error:
        raise CollectorIdentityError(f"{label} retained executable is missing: {error}") from error
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise CollectorIdentityError(f"{label} retained executable must be a regular file")
    if metadata.st_size != identity["executable_bytes"]:
        raise CollectorIdentityError(f"{label} retained executable byte count does not match")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CollectorIdentityError(f"cannot hash {label} retained executable: {error}") from error
    if f"sha256:{digest.hexdigest()}" != identity["executable_digest"]:
        raise CollectorIdentityError(f"{label} retained executable digest does not match")
    return identity
