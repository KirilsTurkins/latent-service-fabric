#!/usr/bin/env python3
"""Independently verify the retained Phase 0 evidence inputs.

The completion gate treats aggregate JSON as a cache of conclusions, never as
the source of truth.  This module validates the raw files retained beside (or
inside) each aggregate, regenerates the aggregate using the repository's
existing aggregation logic, and compares the result to the checked-in record.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from typing import Any, BinaryIO, Iterable

try:  # Support both ``python tools/...`` and package-style unit-test imports.
    from . import aggregate_phase0_calibration as calibration_aggregate
    from . import aggregate_phase0_hot_path_profiles as profile_aggregate
    from . import aggregate_phase0_resource_soak as soak_aggregate
    from . import reassemble_phase0_hot_path_profile_archive as profile_reassembly
except ImportError:  # pragma: no cover - exercised by the command-line entrypoint.
    import aggregate_phase0_calibration as calibration_aggregate
    import aggregate_phase0_hot_path_profiles as profile_aggregate
    import aggregate_phase0_resource_soak as soak_aggregate
    import reassemble_phase0_hot_path_profile_archive as profile_reassembly


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
OBJECT_ID_PATTERN = re.compile(r"^[0-9a-f]{40}$")
CHECKSUM_LINE_PATTERN = re.compile(r"^([0-9a-f]{64})  (.+)$")

CALIBRATION_SCHEMA = "latent.phase0.calibration.v1"
PROFILE_SCHEMA = "latent.phase0.hot-path.aggregate.v3"
SOAK_SCHEMA = "latent.phase0.resource-soak.aggregate.v1"
EXECUTION_IDENTITY_SCHEMA = "latent.phase0.execution-evidence.v1"

# These are the source, fixture, toolchain, and aggregation inputs that can
# change the executable path or the interpretation of its measurements.  The
# completion gate itself and prose are deliberately not included: their Git
# commit/tree are still retained in the receipt, while this narrower identity
# permits a documentation-only gate change to consume valid evidence.
EXECUTION_RELEVANT_PATHS = (
    ".cargo",
    "Cargo.lock",
    "Cargo.toml",
    "api",
    "apps/latentd",
    "crates",
    "examples/echo-contract",
    "schemas",
    "wit",
    "tools/aggregate_phase0_calibration.py",
    "tools/aggregate_phase0_hot_path_profiles.py",
    "tools/aggregate_phase0_resource_soak.py",
    "tools/build_echo_capsule.py",
    "tools/run_phase0_baselines.sh",
    "tools/run_phase0_calibration.sh",
    "tools/run_phase0_hot_path_profiles.sh",
    "tools/run_phase0_resource_soak.sh",
    "tools/run_phase0_spike.sh",
    "tools/validate_contracts.sh",
)

MAX_ARCHIVE_FILES = 5_000
MAX_ARCHIVE_BYTES = 1_073_741_824


class EvidenceValidationError(ValueError):
    """Raised when retained evidence cannot be independently verified."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _mapping(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    _require(isinstance(value, list), f"{label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    _require(isinstance(value, str) and value, f"{label} must be a non-empty string")
    return value


def _positive_int(value: Any, label: str) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value > 0,
        f"{label} must be a positive integer",
    )
    return value


def _object_id(value: Any, label: str) -> str:
    result = _string(value, label)
    _require(OBJECT_ID_PATTERN.fullmatch(result) is not None, f"{label} must be a lowercase Git object ID")
    return result


def load_json(path: Path, label: str) -> dict[str, Any]:
    _require_regular_file(path, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceValidationError(f"cannot read {label} {path}: {error}") from error
    return _mapping(payload, label)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise EvidenceValidationError(f"cannot hash {path}: {error}") from error
    return f"sha256:{digest.hexdigest()}"


def _require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise EvidenceValidationError(f"{label} is missing: {path} ({error})") from error
    _require(stat.S_ISREG(metadata.st_mode), f"{label} must be a regular file: {path}")
    _require(not path.is_symlink(), f"{label} must not be a link: {path}")
    _require(metadata.st_nlink == 1, f"{label} must not be a hard link: {path}")


def _require_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise EvidenceValidationError(f"{label} is missing: {path} ({error})") from error
    _require(stat.S_ISDIR(metadata.st_mode), f"{label} must be a directory: {path}")
    _require(not path.is_symlink(), f"{label} must not be a link: {path}")


def _safe_relative_path(value: str, label: str) -> str:
    _require("\\" not in value and "\x00" not in value, f"{label} has an unsafe path")
    candidate = value[2:] if value.startswith("./") else value
    _require(candidate and not candidate.startswith("/"), f"{label} has an absolute or empty path")
    _require(re.match(r"^[A-Za-z]:", candidate) is None, f"{label} has a drive-qualified path")
    parts = candidate.split("/")
    _require(all(part not in {"", ".", ".."} for part in parts), f"{label} has traversal or empty segments")
    posix = PurePosixPath(candidate)
    _require(not posix.is_absolute() and ".." not in posix.parts, f"{label} escapes the archive root")
    return "/".join(parts)


def parse_checksum_manifest(path: Path, label: str) -> dict[str, str]:
    _require_regular_file(path, label)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise EvidenceValidationError(f"cannot read {label}: {error}") from error
    _require(lines, f"{label} is empty")
    entries: dict[str, str] = {}
    for index, line in enumerate(lines, start=1):
        match = CHECKSUM_LINE_PATTERN.fullmatch(line)
        _require(match is not None, f"{label} line {index} has an invalid checksum format")
        digest, raw_path = match.groups()
        normalized = _safe_relative_path(raw_path, f"{label} line {index}")
        _require(normalized not in entries, f"{label} contains duplicate path {normalized!r}")
        entries[normalized] = f"sha256:{digest}"
    return entries


def verify_checksum_manifest(
    manifest_path: Path,
    root: Path,
    *,
    expected_paths: Iterable[str] | None = None,
    label: str,
) -> dict[str, str]:
    entries = parse_checksum_manifest(manifest_path, label)
    if expected_paths is not None:
        expected = set(expected_paths)
        observed = set(entries)
        _require(
            observed == expected,
            f"{label} paths do not match expected files missing={sorted(expected - observed)} extra={sorted(observed - expected)}",
        )
    root = root.resolve()
    for relative, expected_digest in entries.items():
        candidate = root.joinpath(*relative.split("/"))
        _require(candidate.resolve().is_relative_to(root), f"{label} path escapes its root: {relative}")
        _require_regular_file(candidate, f"{label} entry {relative}")
        _require(
            sha256_file(candidate) == expected_digest,
            f"{label} checksum mismatch for {relative}",
        )
    return entries


def _tar_member_relative(member: tarfile.TarInfo, label: str) -> str | None:
    if member.name in {"", ".", "./"}:
        _require(member.isdir(), f"{label} root member must be a directory")
        return None
    return _safe_relative_path(member.name, label)


def extract_tar_stream(stream: BinaryIO, destination: Path, label: str) -> set[str]:
    """Safely extract a tar stream and return its regular-file paths.

    The function deliberately does not use ``TarFile.extractall``: every
    member is checked before a destination is opened, and all links, devices,
    duplicate normalized paths, and escaping paths are rejected.
    """

    _require(not destination.exists(), f"{label} destination already exists: {destination}")
    destination.mkdir(parents=True)
    root = destination.resolve()
    seen_members: set[str] = set()
    files: set[str] = set()
    extracted_bytes = 0
    member_count = 0
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for member in archive:
                member_count += 1
                _require(member_count <= MAX_ARCHIVE_FILES, f"{label} exceeds {MAX_ARCHIVE_FILES} members")
                _require(
                    not member.issym() and not member.islnk(),
                    f"{label} contains a prohibited link: {member.name!r}",
                )
                _require(
                    member.isdir() or member.isfile(),
                    f"{label} contains a prohibited non-regular member: {member.name!r}",
                )
                relative = _tar_member_relative(member, label)
                if relative is None:
                    continue
                _require(relative not in seen_members, f"{label} contains duplicate path {relative!r}")
                seen_members.add(relative)
                destination_path = root.joinpath(*relative.split("/"))
                _require(
                    destination_path.resolve().is_relative_to(root),
                    f"{label} member escapes extraction root: {relative!r}",
                )
                if member.isdir():
                    destination_path.mkdir(parents=True, exist_ok=False)
                    continue
                _require(member.size >= 0, f"{label} member has an invalid size: {relative!r}")
                extracted_bytes += member.size
                _require(
                    extracted_bytes <= MAX_ARCHIVE_BYTES,
                    f"{label} exceeds the {MAX_ARCHIVE_BYTES}-byte extraction limit",
                )
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                _require(source is not None, f"{label} cannot read member {relative!r}")
                with source, destination_path.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                _require_regular_file(destination_path, f"{label} extracted member {relative}")
                files.add(relative)
    except (OSError, tarfile.TarError) as error:
        raise EvidenceValidationError(f"cannot extract {label}: {error}") from error
    return files


def extract_zstd_tar(archive_path: Path, destination: Path, label: str) -> set[str]:
    _require_regular_file(archive_path, label)
    try:
        process = subprocess.Popen(
            ["zstd", "--quiet", "--decompress", "--stdout", str(archive_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise EvidenceValidationError(f"{label} requires zstd: {error}") from error
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        files = extract_tar_stream(process.stdout, destination, label)
    except Exception:
        process.terminate()
        process.wait()
        process.stderr.close()
        raise
    finally:
        process.stdout.close()
    stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
    process.stderr.close()
    return_code = process.wait()
    _require(return_code == 0, f"{label} zstd extraction failed: {stderr or return_code}")
    return files


def verify_extracted_manifest(
    extraction_root: Path,
    manifest_path: Path,
    extracted_files: set[str],
    *,
    allowed_extra_files: set[str] | None = None,
    label: str,
) -> dict[str, str]:
    entries = parse_checksum_manifest(manifest_path, label)
    allowed_extra = allowed_extra_files or set()
    expected_files = set(entries)
    _require(
        extracted_files == expected_files | allowed_extra,
        f"{label} does not cover extracted files missing={sorted(expected_files - extracted_files)} extra={sorted(extracted_files - expected_files - allowed_extra)}",
    )
    for relative, expected_digest in entries.items():
        candidate = extraction_root.joinpath(*relative.split("/"))
        _require_regular_file(candidate, f"{label} entry {relative}")
        _require(
            sha256_file(candidate) == expected_digest,
            f"{label} checksum mismatch for {relative}",
        )
    return entries


def _without_paths(document: dict[str, Any], ignored_paths: Iterable[tuple[str, ...]]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    for path in ignored_paths:
        current: Any = result
        for key in path[:-1]:
            if not isinstance(current, dict):
                break
            current = current.get(key)
        if isinstance(current, dict):
            current.pop(path[-1], None)
    return result


def _normalize_portable_relative_paths(value: Any) -> Any:
    """Normalize aggregator-generated relative file locators across host OSes."""

    if isinstance(value, dict):
        return {key: _normalize_portable_relative_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_portable_relative_paths(item) for item in value]
    if isinstance(value, str) and re.fullmatch(r"[^\\/]+(?:\\[^\\/]+)+\\[^\\/]+", value):
        return value.replace("\\", "/")
    return value


def _first_difference(expected: Any, actual: Any, path: str = "$") -> str:
    if type(expected) is not type(actual):
        return f"{path} type expected={type(expected).__name__} observed={type(actual).__name__}"
    if isinstance(expected, dict):
        expected_keys = set(expected)
        actual_keys = set(actual)
        if expected_keys != actual_keys:
            return f"{path} keys missing={sorted(expected_keys - actual_keys)} extra={sorted(actual_keys - expected_keys)}"
        for key in sorted(expected_keys):
            difference = _first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return ""
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path} length expected={len(expected)} observed={len(actual)}"
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            difference = _first_difference(left, right, f"{path}[{index}]")
            if difference:
                return difference
        return ""
    if expected != actual:
        return f"{path} expected={expected!r} observed={actual!r}"
    return ""


def assert_regenerated_aggregate(
    retained: dict[str, Any],
    regenerated: dict[str, Any],
    label: str,
    *,
    ignored_paths: Iterable[tuple[str, ...]] = (),
) -> None:
    ignored = (("generated_at_utc",), *tuple(ignored_paths))
    expected = _normalize_portable_relative_paths(_without_paths(retained, ignored))
    actual = _normalize_portable_relative_paths(_without_paths(regenerated, ignored))
    _require(
        actual == expected,
        f"{label} aggregate does not match its regenerated raw evidence: {_first_difference(expected, actual)}",
    )


def _assert_directory_entries(root: Path, expected: set[str], label: str) -> None:
    _require_directory(root, label)
    observed = {path.name for path in root.iterdir()}
    _require(
        observed == expected,
        f"{label} entries do not match expected files missing={sorted(expected - observed)} extra={sorted(observed - expected)}",
    )


def _calibration_outer_files(root: Path) -> None:
    expected = {
        "aggregate.json",
        "CALIBRATION.md",
        "raw-evidence.manifest.sha256",
        "raw-evidence.tar.zst",
        "raw-evidence.tar.zst.sha256",
    }
    _assert_directory_entries(root, expected, "calibration evidence root")
    for file_name in expected:
        _require_regular_file(root / file_name, f"calibration evidence {file_name}")


def verify_calibration_evidence(aggregate_path: Path) -> dict[str, Any]:
    retained = load_json(aggregate_path, "calibration aggregate")
    _require(retained.get("schema_version") == CALIBRATION_SCHEMA, "unexpected calibration schema")
    root = aggregate_path.parent.resolve()
    _calibration_outer_files(root)
    archive_path = root / "raw-evidence.tar.zst"
    verify_checksum_manifest(
        root / "raw-evidence.tar.zst.sha256",
        root,
        expected_paths={archive_path.name},
        label="calibration archive checksum",
    )
    with tempfile.TemporaryDirectory(prefix="phase0-calibration-verify-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        extracted_root = temporary_root / "raw"
        extracted_files = extract_zstd_tar(archive_path, extracted_root, "calibration raw-evidence archive")
        extracted_manifest = extracted_root / "raw-evidence.manifest.sha256"
        _require_regular_file(extracted_manifest, "calibration archived manifest")
        _require(
            extracted_manifest.read_bytes() == (root / "raw-evidence.manifest.sha256").read_bytes(),
            "calibration archived manifest does not match the retained manifest",
        )
        verify_extracted_manifest(
            extracted_root,
            extracted_manifest,
            extracted_files,
            allowed_extra_files={"raw-evidence.manifest.sha256"},
            label="calibration raw-evidence manifest",
        )
        source_commit = _object_id(retained.get("source_commit"), "calibration source commit")
        source_tree = _object_id(retained.get("source_tree"), "calibration source tree")
        minimum_runs = _positive_int(retained.get("minimum_required_run_count"), "calibration minimum run count")
        try:
            regenerated = calibration_aggregate.build_aggregate(
                extracted_root / "runs", source_commit, source_tree, minimum_runs
            )
        except calibration_aggregate.CalibrationError as error:
            raise EvidenceValidationError(f"calibration raw evidence is invalid: {error}") from error
    assert_regenerated_aggregate(retained, regenerated, "calibration")
    return regenerated


def _profile_outer_files(root: Path) -> tuple[dict[str, Any], set[str]]:
    parts_manifest = load_json(root / "raw-evidence.parts.json", "profile fragment manifest")
    parts = _list(parts_manifest.get("parts"), "profile fragment manifest parts")
    part_names: set[str] = set()
    for entry in parts:
        item = _mapping(entry, "profile fragment")
        name = _safe_relative_path(_string(item.get("path"), "profile fragment path"), "profile fragment path")
        _require("/" not in name, "profile fragment must be a local filename")
        _require(name not in part_names, f"duplicate profile fragment {name!r}")
        _positive_int(item.get("bytes"), f"profile fragment {name} bytes")
        digest = _string(item.get("sha256"), f"profile fragment {name} checksum")
        _require(digest.startswith("sha256:") and SHA256_PATTERN.fullmatch(digest[7:]) is not None, f"profile fragment {name} checksum is malformed")
        part_names.add(name)
    _require(part_names, "profile fragment manifest has no parts")
    expected = {
        "README.md",
        "PROFILE.md",
        "aggregate.json",
        "host-before.json",
        "raw-evidence.manifest.sha256",
        "raw-evidence.parts.json",
        "raw-evidence.parts.sha256",
        "raw-evidence.tar.zst.sha256",
    } | part_names
    _assert_directory_entries(root, expected, "profile evidence root")
    for file_name in expected:
        _require_regular_file(root / file_name, f"profile evidence {file_name}")
    return parts_manifest, part_names


def _profile_required_candidate_runs(document: dict[str, Any]) -> int:
    candidates = _mapping(document.get("candidates"), "profile candidates")
    counts: set[int] = set()
    for name, candidate in candidates.items():
        _require(isinstance(name, str) and name, "profile candidate name is invalid")
        counts.add(_positive_int(_mapping(candidate, f"profile candidate {name}").get("run_count"), f"profile candidate {name} run count"))
    _require(len(counts) == 1, "profile candidates do not retain one common run count")
    return counts.pop()


def verify_profile_evidence(aggregate_path: Path, calibration_path: Path) -> dict[str, Any]:
    retained = load_json(aggregate_path, "profile aggregate")
    _require(retained.get("schema_version") == PROFILE_SCHEMA, "unexpected profiling schema")
    root = aggregate_path.parent.resolve()
    parts_manifest, part_names = _profile_outer_files(root)
    expected_parts = {"raw-evidence.parts.json", *part_names}
    verify_checksum_manifest(
        root / "raw-evidence.parts.sha256",
        root,
        expected_paths=expected_parts,
        label="profile fragment checksum manifest",
    )
    try:
        manifest_archive = _string(parts_manifest.get("archive"), "profile archive name")
        _require("/" not in _safe_relative_path(manifest_archive, "profile archive name"), "profile archive name must be local")
        _require(manifest_archive == "raw-evidence.tar.zst", "profile archive name is unexpected")
        archive_bytes = _positive_int(parts_manifest.get("archive_bytes"), "profile archive size")
        archive_digest = _string(parts_manifest.get("archive_sha256"), "profile archive digest")
        _require(archive_digest.startswith("sha256:") and SHA256_PATTERN.fullmatch(archive_digest[7:]) is not None, "profile archive digest is malformed")
        with tempfile.TemporaryDirectory(prefix="phase0-profile-verify-") as temporary_directory:
            temporary_root = Path(temporary_directory)
            archive_path = temporary_root / manifest_archive
            try:
                profile_reassembly.reassemble(root, archive_path)
            except profile_reassembly.ReassemblyError as error:
                raise EvidenceValidationError(f"profile archive fragments are invalid: {error}") from error
            _require(archive_path.stat().st_size == archive_bytes, "profile reassembled archive size does not match its manifest")
            _require(sha256_file(archive_path) == archive_digest, "profile reassembled archive digest does not match its manifest")
            verify_checksum_manifest(
                root / "raw-evidence.tar.zst.sha256",
                temporary_root,
                expected_paths={manifest_archive},
                label="profile archive checksum",
            )
            extracted_root = temporary_root / "raw"
            extracted_files = extract_zstd_tar(archive_path, extracted_root, "profile raw-evidence archive")
            extracted_manifest = extracted_root / "raw-evidence.manifest.sha256"
            _require_regular_file(extracted_manifest, "profile archived manifest")
            _require(
                extracted_manifest.read_bytes() == (root / "raw-evidence.manifest.sha256").read_bytes(),
                "profile archived manifest does not match the retained manifest",
            )
            verify_extracted_manifest(
                extracted_root,
                extracted_manifest,
                extracted_files,
                allowed_extra_files={"raw-evidence.manifest.sha256"},
                label="profile raw-evidence manifest",
            )
            _require(
                sha256_file(extracted_root / "aggregate.json") == sha256_file(aggregate_path),
                "profile archive aggregate does not match the retained aggregate",
            )
            _require(
                sha256_file(extracted_root / "PROFILE.md") == sha256_file(root / "PROFILE.md"),
                "profile archive report does not match the retained report",
            )
            calibration_reference = _mapping(retained.get("calibration_reference"), "profile calibration reference")
            _require(
                sha256_file(calibration_path) == _string(calibration_reference.get("sha256"), "profile calibration checksum"),
                "profile calibration reference does not match the calibration passed to the gate",
            )
            provenance = _mapping(retained.get("source_provenance"), "profile source provenance")
            required_runs = _profile_required_candidate_runs(retained)
            regenerated_path = extracted_root / "regenerated.json"
            arguments = argparse.Namespace(
                profiles_directory=extracted_root / "profiles",
                full_invariant_proof=extracted_root / "full-invariant-proof" / "raw-results.json",
                candidates_directory=extracted_root / "candidates",
                host_observation=extracted_root / "host-before.json",
                calibration_aggregate=calibration_path,
                source_commit=_object_id(retained.get("source_commit"), "profile source commit"),
                source_tree=_object_id(retained.get("source_tree"), "profile source tree"),
                published_source_ref=_string(provenance.get("published_source_ref"), "profile published source ref"),
                required_candidate_runs=required_runs,
                output_json=regenerated_path,
                output_report=extracted_root / "regenerated.md",
            )
            try:
                profile_aggregate.aggregate(arguments)
            except profile_aggregate.HotPathError as error:
                raise EvidenceValidationError(f"profile raw evidence is invalid: {error}") from error
            regenerated = load_json(regenerated_path, "regenerated profile aggregate")
    except OSError as error:
        raise EvidenceValidationError(f"cannot verify profile evidence: {error}") from error
    assert_regenerated_aggregate(
        retained,
        regenerated,
        "profile",
        ignored_paths=(("calibration_reference", "path"),),
    )
    return regenerated


def _soak_outer_files(root: Path) -> None:
    expected = {
        "README.md",
        "SOAK.md",
        "aggregate.json",
        "raw-evidence.manifest.sha256",
        "raw-evidence.tar.zst",
        "raw-evidence.tar.zst.sha256",
    }
    _assert_directory_entries(root, expected, "resource-soak evidence root")
    for file_name in expected:
        _require_regular_file(root / file_name, f"resource-soak evidence {file_name}")


def verify_resource_soak_evidence(aggregate_path: Path, calibration_path: Path) -> dict[str, Any]:
    retained = load_json(aggregate_path, "resource-soak aggregate")
    _require(retained.get("schema_version") == SOAK_SCHEMA, "unexpected resource-soak schema")
    root = aggregate_path.parent.resolve()
    _soak_outer_files(root)
    archive_path = root / "raw-evidence.tar.zst"
    verify_checksum_manifest(
        root / "raw-evidence.tar.zst.sha256",
        root,
        expected_paths={archive_path.name},
        label="resource-soak archive checksum",
    )
    raw_archive = _mapping(retained.get("raw_evidence_archive"), "resource-soak raw archive")
    _require(raw_archive.get("path") == archive_path.name, "resource-soak aggregate points at an unexpected archive")
    _require(raw_archive.get("manifest") == "raw-evidence.manifest.sha256", "resource-soak aggregate points at an unexpected manifest")
    _require(
        raw_archive.get("sha256") == sha256_file(archive_path),
        "resource-soak aggregate archive digest does not match its payload",
    )
    with tempfile.TemporaryDirectory(prefix="phase0-soak-verify-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        extracted_root = temporary_root / "raw"
        extracted_files = extract_zstd_tar(archive_path, extracted_root, "resource-soak raw-evidence archive")
        extracted_manifest = extracted_root / "raw-evidence.manifest.sha256"
        _require_regular_file(extracted_manifest, "resource-soak archived manifest")
        _require(
            extracted_manifest.read_bytes() == (root / "raw-evidence.manifest.sha256").read_bytes(),
            "resource-soak archived manifest does not match the retained manifest",
        )
        verify_extracted_manifest(
            extracted_root,
            extracted_manifest,
            extracted_files,
            allowed_extra_files={"raw-evidence.manifest.sha256"},
            label="resource-soak raw-evidence manifest",
        )
        # The existing aggregator insists that the archive and checksum are next
        # to its output.  Stage verified copies only in this temporary root.
        shutil.copy2(archive_path, extracted_root / archive_path.name)
        shutil.copy2(root / "raw-evidence.tar.zst.sha256", extracted_root / "raw-evidence.tar.zst.sha256")
        source_commit = _object_id(retained.get("source_commit"), "resource-soak source commit")
        source_tree = _object_id(retained.get("source_tree"), "resource-soak source tree")
        minimum_runs = _positive_int(retained.get("minimum_required_run_count"), "resource-soak minimum run count")
        investigation = retained.get("investigation")
        retaining_subsystem: str | None = None
        followup_issue: str | None = None
        if isinstance(investigation, dict):
            if isinstance(investigation.get("retaining_subsystem"), str):
                retaining_subsystem = investigation["retaining_subsystem"]
            if isinstance(investigation.get("followup_issue"), str):
                followup_issue = investigation["followup_issue"]
        regenerated_path = extracted_root / "regenerated.json"
        try:
            regenerated, _ = soak_aggregate.aggregate(
                extracted_root / "runs",
                regenerated_path,
                extracted_root / "regenerated.md",
                source_commit,
                source_tree,
                calibration_path,
                minimum_runs,
                retaining_subsystem,
                followup_issue,
            )
        except soak_aggregate.SoakError as error:
            raise EvidenceValidationError(f"resource-soak raw evidence is invalid: {error}") from error
    assert_regenerated_aggregate(
        retained,
        regenerated,
        "resource-soak",
        ignored_paths=(("calibration_noise", "path"),),
    )
    return regenerated


def _git(arguments: list[str], label: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), *arguments],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as error:
        raise EvidenceValidationError(f"cannot invoke git for {label}: {error}") from error
    _require(
        completed.returncode == 0,
        f"git could not resolve {label}: {completed.stderr.strip() or completed.stdout.strip()}",
    )
    return completed.stdout


def execution_evidence_identity(commit: str, tree: str) -> dict[str, Any]:
    commit = _object_id(commit, "execution-evidence commit")
    tree = _object_id(tree, "execution-evidence tree")
    actual_tree = _git(["rev-parse", f"{commit}^{{tree}}"], f"commit {commit}").strip()
    _require(actual_tree == tree, f"execution-evidence commit {commit} does not resolve to tree {tree}")
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(REPOSITORY_ROOT),
                "ls-tree",
                "-r",
                "-z",
                "--full-tree",
                tree,
                "--",
                *EXECUTION_RELEVANT_PATHS,
            ],
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise EvidenceValidationError(f"cannot list execution evidence for {tree}: {error}") from error
    _require(completed.returncode == 0, f"git could not list execution evidence for {tree}")
    entries: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as error:
            raise EvidenceValidationError(f"malformed Git tree entry for {tree}") from error
        _require(object_type == "blob" and OBJECT_ID_PATTERN.fullmatch(object_id) is not None, f"invalid execution evidence entry {path!r}")
        _require(path not in seen_paths, f"duplicate execution evidence path {path!r}")
        seen_paths.add(path)
        entries.append({"path": path, "mode": mode, "object": object_id})
    _require(entries, "execution evidence path set is empty")
    entries.sort(key=lambda entry: entry["path"])
    canonical = json.dumps(
        {"schema_version": EXECUTION_IDENTITY_SCHEMA, "paths": EXECUTION_RELEVANT_PATHS, "entries": entries},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema_version": EXECUTION_IDENTITY_SCHEMA,
        "commit": commit,
        "tree": tree,
        "paths": list(EXECUTION_RELEVANT_PATHS),
        "entry_count": len(entries),
        "sha256": f"sha256:{hashlib.sha256(canonical).hexdigest()}",
    }


def current_execution_evidence_identity() -> dict[str, Any]:
    commit = _git(["rev-parse", "HEAD"], "current commit").strip()
    tree = _git(["rev-parse", "HEAD^{tree}"], "current tree").strip()
    identity = execution_evidence_identity(commit, tree)
    dirty = _git(["status", "--porcelain", "--untracked-files=all"], "worktree status").splitlines()
    identity["worktree_clean"] = not dirty
    identity["worktree_changes"] = dirty
    return identity
