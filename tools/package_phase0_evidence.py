#!/usr/bin/env python3
"""Package externally collected Phase 0 runner output for the completion gate.

The native-Linux collectors intentionally write loose, inspectable output.  A
completion-gate input has a smaller outer layout and a checksumed raw archive.
This helper makes that transition without editing JSON: it copies a complete
collector output into a fresh destination, builds the archive and manifests,
and invokes the same independent verifiers used by the gate before publishing
the destination directory.

The input directory is never modified.  The destination must not exist.  Keep
both collection and packaging output outside the source worktree until the
verified package is ready to be added as evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Iterable, NoReturn

try:  # Support both ``python tools/...`` and package-style unit-test imports.
    from . import aggregate_phase0_calibration as calibration_aggregate
    from . import aggregate_phase0_resource_soak as soak_aggregate
    from . import phase0_evidence
except ImportError:  # pragma: no cover - exercised by the command-line entrypoint.
    import aggregate_phase0_calibration as calibration_aggregate
    import aggregate_phase0_resource_soak as soak_aggregate
    import phase0_evidence


OBJECT_ID_LENGTH = 40
PROFILE_PART_SCHEMA = "latent.phase0.hot-path.raw-evidence.parts.v1"
PORTABLE_PART_SCHEMA = "latent.phase0.raw-evidence.parts.v1"
# Keep each Base64-encoded fragment below the GitHub connector's retained
# payload limit while preserving a lossless byte-for-byte zstd stream.
MAX_TRANSPORT_PART_BYTES = 716_800
DEFAULT_PROFILE_PART_BYTES = MAX_TRANSPORT_PART_BYTES
COPY_CHUNK_BYTES = 1024 * 1024

CALIBRATION_INPUT_ENTRIES = {"aggregate.json", "CALIBRATION.md", "collector", "runs"}
PROFILE_INPUT_ENTRIES = {
    "aggregate.json",
    "PROFILE.md",
    "host-before.json",
    "bootstrap.log",
    "bootstrap",
    "full-invariant-proof",
    "profiles",
    "candidates",
    "collector",
}
SOAK_INPUT_ENTRIES = {"aggregate.json", "SOAK.md", "collector", "runs"}


class PackagingError(ValueError):
    """The supplied collector output cannot become gate evidence safely."""


def fail(message: str) -> NoReturn:
    raise PackagingError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(COPY_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError as error:
        fail(f"cannot hash {path}: {error}")
    return f"sha256:{digest.hexdigest()}"


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        fail(f"{label} is missing: {path} ({error})")
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        fail(f"{label} must be a regular, non-link file: {path}")
    if metadata.st_nlink != 1:
        fail(f"{label} must not be a hard link: {path}")


def require_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        fail(f"{label} is missing: {path} ({error})")
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        fail(f"{label} must be a directory, not a link: {path}")


def absolute_path(path: Path) -> Path:
    """Make a lexical absolute path without following a symbolic link."""

    return Path(os.path.abspath(path))


def reject_symlinked_components(path: Path, label: str) -> None:
    """Reject a path whose existing lexical components contain a link."""

    if not path.is_absolute():
        fail(f"{label} must be absolute before checking path components: {path}")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            fail(f"cannot inspect {label} path component {current}: {error}")
        if stat.S_ISLNK(metadata.st_mode):
            fail(f"{label} must not contain a symbolic-link path component: {current}")


def existing_directory_path(path: Path, label: str) -> Path:
    result = absolute_path(path)
    reject_symlinked_components(result, label)
    require_directory(result, label)
    return result


def existing_regular_file_path(path: Path, label: str) -> Path:
    result = absolute_path(path)
    reject_symlinked_components(result, label)
    require_regular_file(result, label)
    return result


def absent_output_path(path: Path) -> Path:
    result = absolute_path(path)
    reject_symlinked_components(result, "output directory")
    try:
        result.lstat()
    except FileNotFoundError:
        return result
    except OSError as error:
        fail(f"cannot inspect output directory {result}: {error}")
    fail(f"output directory must not already exist: {result}")


def require_object_id(value: str, label: str) -> str:
    if len(value) != OBJECT_ID_LENGTH or any(character not in "0123456789abcdef" for character in value):
        fail(f"{label} must be a 40-character lowercase Git object ID")
    return value


def directory_entries(path: Path, label: str) -> set[str]:
    require_directory(path, label)
    try:
        return {entry.name for entry in path.iterdir()}
    except OSError as error:
        fail(f"cannot list {label}: {error}")


def require_exact_entries(path: Path, expected: set[str], label: str) -> None:
    observed = directory_entries(path, label)
    if observed != expected:
        fail(
            f"{label} has unexpected entries "
            f"missing={sorted(expected - observed)} extra={sorted(observed - expected)}"
        )


def regular_files(root: Path, label: str) -> list[Path]:
    """Return every file below *root* after rejecting links and special files."""

    require_directory(root, label)
    files: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        require_directory(directory, label)
        try:
            children = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError as error:
            fail(f"cannot list {label} directory {directory}: {error}")
        for child in children:
            try:
                metadata = child.lstat()
            except OSError as error:
                fail(f"cannot inspect {label} entry {child}: {error}")
            if stat.S_ISDIR(metadata.st_mode):
                if child.is_symlink():
                    fail(f"{label} contains a directory link: {child}")
                pending.append(child)
            elif stat.S_ISREG(metadata.st_mode):
                require_regular_file(child, label)
                files.append(child)
            else:
                fail(f"{label} contains a non-regular entry: {child}")
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def copy_file(source: Path, destination: Path, label: str) -> None:
    require_regular_file(source, label)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer, COPY_CHUNK_BYTES)
    except OSError as error:
        fail(f"cannot copy {label} {source}: {error}")
    require_regular_file(destination, f"copied {label}")


def copy_directory(source: Path, destination: Path, label: str) -> None:
    require_directory(source, label)
    try:
        destination.mkdir()
    except OSError as error:
        fail(f"cannot create staged {label} directory {destination}: {error}")
    for child in sorted(source.iterdir(), key=lambda entry: entry.name):
        target = destination / child.name
        try:
            metadata = child.lstat()
        except OSError as error:
            fail(f"cannot inspect {label} entry {child}: {error}")
        if stat.S_ISDIR(metadata.st_mode):
            if child.is_symlink():
                fail(f"{label} contains a directory link: {child}")
            copy_directory(child, target, label)
        elif stat.S_ISREG(metadata.st_mode):
            copy_file(child, target, label)
        else:
            fail(f"{label} contains a non-regular entry: {child}")


def copy_collector_output(input_directory: Path, stage: Path, expected: set[str], label: str) -> None:
    require_exact_entries(input_directory, expected, f"{label} collector output")
    for name in sorted(expected):
        source = input_directory / name
        try:
            metadata = source.lstat()
        except OSError as error:
            fail(f"cannot inspect {label} collector output {source}: {error}")
        if stat.S_ISDIR(metadata.st_mode):
            if source.is_symlink():
                fail(f"{label} collector output contains a directory link: {source}")
            copy_directory(source, stage / name, f"{label} collector output")
        elif stat.S_ISREG(metadata.st_mode):
            copy_file(source, stage / name, f"{label} collector output")
        else:
            fail(f"{label} collector output contains a non-regular entry: {source}")


def load_aggregate(path: Path, label: str) -> dict[str, Any]:
    try:
        document = phase0_evidence.load_json(path, f"{label} aggregate")
    except phase0_evidence.EvidenceValidationError as error:
        fail(str(error))
    return document


def require_aggregate_identity(
    aggregate: dict[str, Any], source_commit: str, source_tree: str, label: str
) -> None:
    if aggregate.get("source_commit") != source_commit:
        fail(f"{label} aggregate source commit does not match the declared source commit")
    if aggregate.get("source_tree") != source_tree:
        fail(f"{label} aggregate source tree does not match the declared source tree")


def verify_packaged_calibration(calibration_path: Path) -> dict[str, Any]:
    try:
        calibration = phase0_evidence.verify_calibration_evidence(calibration_path)
    except phase0_evidence.EvidenceValidationError as error:
        fail(f"calibration package is not integrity-verifiable: {error}")
    if calibration.get("schema_version") != phase0_evidence.CALIBRATION_SCHEMA:
        fail(
            "calibration package is historical integrity-only evidence and cannot "
            "be used to package current gate evidence"
        )
    return calibration


def write_new_text(path: Path, contents: str, label: str) -> None:
    try:
        with path.open("x", encoding="utf-8") as output:
            output.write(contents)
    except OSError as error:
        fail(f"cannot write {label}: {error}")
    require_regular_file(path, label)


def write_manifest(stage: Path, archive_files: Iterable[Path]) -> Path:
    lines: list[str] = []
    normalized: list[tuple[str, Path]] = []
    for path in archive_files:
        require_regular_file(path, "raw evidence file")
        try:
            relative = path.relative_to(stage).as_posix()
        except ValueError:
            fail(f"raw evidence file escapes packaging root: {path}")
        if not relative or relative.startswith("../"):
            fail(f"raw evidence path is unsafe: {path}")
        normalized.append((relative, path))
    paths = [relative for relative, _ in normalized]
    if len(paths) != len(set(paths)):
        fail("raw evidence archive contains duplicate paths")
    for relative, path in sorted(normalized):
        lines.append(f"{sha256_file(path).removeprefix('sha256:')}  {relative}\n")
    manifest = stage / "raw-evidence.manifest.sha256"
    write_new_text(manifest, "".join(lines), "raw evidence checksum manifest")
    return manifest


def create_zstd_tar(stage: Path, archive_files: Iterable[Path], output: Path) -> None:
    entries: list[tuple[str, Path]] = []
    for path in archive_files:
        require_regular_file(path, "raw evidence archive member")
        try:
            relative = path.relative_to(stage).as_posix()
        except ValueError:
            fail(f"raw evidence archive member escapes packaging root: {path}")
        entries.append((relative, path))
    entries.sort()
    if len({relative for relative, _ in entries}) != len(entries):
        fail("raw evidence archive has duplicate member paths")
    try:
        with output.open("xb") as compressed:
            process = subprocess.Popen(
                ["zstd", "--quiet", "--compress", "--stdout", "-"],
                stdin=subprocess.PIPE,
                stdout=compressed,
                stderr=subprocess.PIPE,
            )
            assert process.stdin is not None
            assert process.stderr is not None
            try:
                with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
                    for relative, path in entries:
                        metadata = path.stat()
                        info = tarfile.TarInfo(relative)
                        info.size = metadata.st_size
                        info.mode = stat.S_IMODE(metadata.st_mode)
                        info.mtime = 0
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        with path.open("rb") as source:
                            archive.addfile(info, source)
            finally:
                process.stdin.close()
            stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
            return_code = process.wait()
            process.stderr.close()
    except OSError as error:
        fail(f"cannot create zstd raw evidence archive: {error}")
    if return_code != 0:
        fail(f"zstd could not create raw evidence archive: {stderr or return_code}")
    require_regular_file(output, "raw evidence archive")


def write_archive_checksum(stage: Path, archive: Path) -> None:
    write_new_text(
        stage / "raw-evidence.tar.zst.sha256",
        f"{sha256_file(archive).removeprefix('sha256:')}  raw-evidence.tar.zst\n",
        "raw evidence archive checksum",
    )


def ensure_archive_checksum(stage: Path, archive: Path) -> None:
    checksum = stage / "raw-evidence.tar.zst.sha256"
    expected = (
        f"{sha256_file(archive).removeprefix('sha256:')}  raw-evidence.tar.zst\n"
    )
    if checksum.exists() or checksum.is_symlink():
        require_regular_file(checksum, "raw evidence archive checksum")
        try:
            observed = checksum.read_text(encoding="utf-8")
        except OSError as error:
            fail(f"cannot read raw evidence archive checksum: {error}")
        if observed != expected:
            fail("raw evidence archive checksum does not match the archive before splitting")
        return
    write_new_text(checksum, expected, "raw evidence archive checksum")


def split_raw_evidence_archive(
    stage: Path,
    archive: Path,
    part_bytes: int,
    schema_version: str,
) -> None:
    if part_bytes <= 0:
        fail("raw-evidence part size must be a positive number of bytes")
    if part_bytes > MAX_TRANSPORT_PART_BYTES:
        fail(
            "raw-evidence part size exceeds the 716800-byte retained transport limit; "
            "use the default or a smaller value"
        )
    archive_size = archive.stat().st_size
    archive_digest = sha256_file(archive)
    parts: list[dict[str, Any]] = []
    try:
        with archive.open("rb") as source:
            index = 1
            while chunk := source.read(part_bytes):
                name = f"raw-evidence.tar.zst.part-{index:03d}"
                destination = stage / name
                with destination.open("xb") as output:
                    output.write(chunk)
                require_regular_file(destination, f"profile archive fragment {name}")
                parts.append(
                    {
                        "path": name,
                        "bytes": len(chunk),
                        "sha256": sha256_file(destination),
                    }
                )
                index += 1
    except OSError as error:
        fail(f"cannot split profile raw archive: {error}")
    if not parts:
        fail("profile raw archive is empty")
    parts_manifest = stage / "raw-evidence.parts.json"
    write_new_text(
        parts_manifest,
        json.dumps(
            {
                "schema_version": schema_version,
                "archive": "raw-evidence.tar.zst",
                "archive_bytes": archive_size,
                "archive_sha256": archive_digest,
                "parts": parts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "raw-evidence fragment manifest",
    )
    checksum_paths = [parts_manifest, *(stage / part["path"] for part in parts)]
    lines = [
        f"{sha256_file(path).removeprefix('sha256:')}  {path.name}\n"
        for path in checksum_paths
    ]
    write_new_text(
        stage / "raw-evidence.parts.sha256",
        "".join(lines),
        "raw-evidence fragment checksum manifest",
    )
    ensure_archive_checksum(stage, archive)
    try:
        archive.unlink()
    except OSError as error:
        fail(f"cannot remove staging raw-evidence archive: {error}")


def split_profile_archive(stage: Path, archive: Path, part_bytes: int) -> None:
    split_raw_evidence_archive(
        stage,
        archive,
        part_bytes,
        PROFILE_PART_SCHEMA,
    )


def write_readme(stage: Path, title: str, aggregate: dict[str, Any]) -> None:
    source_commit = aggregate.get("source_commit")
    source_tree = aggregate.get("source_tree")
    write_new_text(
        stage / "README.md",
        "\n".join(
            [
                f"# {title}",
                "",
                "This archive-backed package was assembled from an externally collected native-Linux runner output by `tools/package_phase0_evidence.py`.",
                "The helper copies raw files, creates checksums, and re-runs the gate's independent evidence verifier; it does not make an authorization decision.",
                "",
                f"- Declared source commit: `{source_commit}`",
                f"- Declared source tree: `{source_tree}`",
                "- `aggregate.json` and the retained report are the machine-readable and human-readable collector results.",
                "- `raw-evidence.manifest.sha256` verifies every extracted raw file.",
                "",
            ]
        ),
        "evidence README",
    )


def remove_staged_entry(path: Path) -> None:
    """Remove only a path created in the private staging directory."""

    try:
        metadata = path.lstat()
    except OSError as error:
        fail(f"cannot inspect staging path {path}: {error}")
    try:
        if stat.S_ISDIR(metadata.st_mode):
            shutil.rmtree(path)
        elif stat.S_ISREG(metadata.st_mode):
            path.unlink()
        else:
            fail(f"staging path has an unsafe type: {path}")
    except OSError as error:
        fail(f"cannot remove staging path {path}: {error}")


def prepare_stage(
    input_directory: Path, output_directory: Path
) -> tuple[Path, tempfile.TemporaryDirectory[str], Path]:
    input_root = existing_directory_path(input_directory, "collector output directory")
    output = absent_output_path(output_directory)
    if output == input_root or output.is_relative_to(input_root):
        fail("output directory must be outside the collector output directory")
    parent = output.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        fail(f"cannot create output parent {parent}: {error}")
    reject_symlinked_components(output, "output directory")
    require_directory(parent, "output parent directory")
    temporary = tempfile.TemporaryDirectory(prefix=f".{output.name}.package-", dir=parent)
    stage = Path(temporary.name) / "evidence"
    stage.mkdir()
    return stage, temporary, output


def publish_stage(stage: Path, temporary: tempfile.TemporaryDirectory[str], output: Path) -> None:
    absent_output_path(output)
    try:
        os.rename(stage, output)
    except OSError as error:
        fail(f"cannot publish packaged evidence to {output}: {error}")
    temporary.cleanup()


def package_calibration(arguments: argparse.Namespace) -> None:
    source_commit = require_object_id(arguments.source_commit, "source commit")
    source_tree = require_object_id(arguments.source_tree, "source tree")
    input_root = existing_directory_path(arguments.input_directory, "collector output directory")
    stage, temporary, output = prepare_stage(input_root, arguments.output_directory)
    try:
        copy_collector_output(input_root, stage, CALIBRATION_INPUT_ENTRIES, "calibration")
        aggregate = load_aggregate(stage / "aggregate.json", "calibration")
        require_aggregate_identity(aggregate, source_commit, source_tree, "calibration")
        try:
            calibration_aggregate.verify_aggregate(stage / "aggregate.json", source_commit, source_tree)
        except calibration_aggregate.CalibrationError as error:
            fail(f"calibration collector output is not a verified raw aggregate: {error}")
        raw_files = [
            *regular_files(stage / "collector", "calibration retained collector"),
            *regular_files(stage / "runs", "calibration raw runs"),
        ]
        manifest = write_manifest(stage, raw_files)
        archive = stage / "raw-evidence.tar.zst"
        create_zstd_tar(stage, [*raw_files, manifest], archive)
        write_archive_checksum(stage, archive)
        remove_staged_entry(stage / "runs")
        remove_staged_entry(stage / "collector")
        split_raw_evidence_archive(
            stage,
            archive,
            MAX_TRANSPORT_PART_BYTES,
            PORTABLE_PART_SCHEMA,
        )
        try:
            phase0_evidence.verify_calibration_evidence(stage / "aggregate.json")
        except phase0_evidence.EvidenceValidationError as error:
            fail(f"calibration package did not pass the gate verifier: {error}")
        publish_stage(stage, temporary, output)
    except Exception:
        temporary.cleanup()
        raise


def package_profile(arguments: argparse.Namespace) -> None:
    source_commit = require_object_id(arguments.source_commit, "source commit")
    source_tree = require_object_id(arguments.source_tree, "source tree")
    input_root = existing_directory_path(arguments.input_directory, "collector output directory")
    calibration_path = existing_regular_file_path(
        arguments.calibration_aggregate, "calibration aggregate"
    )
    calibration = verify_packaged_calibration(calibration_path)
    require_aggregate_identity(calibration, source_commit, source_tree, "calibration")
    stage, temporary, output = prepare_stage(input_root, arguments.output_directory)
    try:
        copy_collector_output(input_root, stage, PROFILE_INPUT_ENTRIES, "profile")
        aggregate = load_aggregate(stage / "aggregate.json", "profile")
        require_aggregate_identity(aggregate, source_commit, source_tree, "profile")
        raw_files = regular_files(stage, "profile collector output")
        manifest = write_manifest(stage, raw_files)
        archive = stage / "raw-evidence.tar.zst"
        create_zstd_tar(stage, [*raw_files, manifest], archive)
        split_profile_archive(stage, archive, arguments.profile_part_bytes)
        write_readme(stage, "Phase 0 native-Linux hot-path profile evidence", aggregate)
        for name in ("bootstrap.log", "bootstrap", "collector", "full-invariant-proof", "profiles", "candidates"):
            remove_staged_entry(stage / name)
        try:
            phase0_evidence.verify_profile_evidence(stage / "aggregate.json", calibration_path)
        except phase0_evidence.EvidenceValidationError as error:
            fail(f"profile package did not pass the gate verifier: {error}")
        publish_stage(stage, temporary, output)
    except Exception:
        temporary.cleanup()
        raise


def soak_options(aggregate: dict[str, Any]) -> tuple[int, str | None, str | None]:
    minimum_runs = aggregate.get("minimum_required_run_count")
    if not isinstance(minimum_runs, int) or isinstance(minimum_runs, bool) or minimum_runs < 3:
        fail("resource-soak aggregate has an invalid minimum required run count")
    investigation = aggregate.get("investigation")
    retaining_subsystem: str | None = None
    followup_issue: str | None = None
    if isinstance(investigation, dict):
        candidate = investigation.get("retaining_subsystem")
        if isinstance(candidate, str):
            retaining_subsystem = candidate
        candidate = investigation.get("followup_issue")
        if isinstance(candidate, str):
            followup_issue = candidate
    return minimum_runs, retaining_subsystem, followup_issue


def reaggregate_soak(
    stage: Path,
    output_json: Path,
    output_report: Path,
    source_commit: str,
    source_tree: str,
    calibration_path: Path,
    minimum_runs: int,
    retaining_subsystem: str | None,
    followup_issue: str | None,
) -> dict[str, Any]:
    try:
        document, status = soak_aggregate.aggregate(
            stage / "runs",
            output_json,
            output_report,
            source_commit,
            source_tree,
            calibration_path,
            minimum_runs,
            retaining_subsystem,
            followup_issue,
        )
    except soak_aggregate.SoakError as error:
        fail(f"resource-soak collector output is invalid: {error}")
    if status != 0 or document.get("status") != "pass":
        fail("resource-soak aggregate is not passing and cannot be packaged for the gate")
    return document


def package_soak(arguments: argparse.Namespace) -> None:
    source_commit = require_object_id(arguments.source_commit, "source commit")
    source_tree = require_object_id(arguments.source_tree, "source tree")
    input_root = existing_directory_path(arguments.input_directory, "collector output directory")
    calibration_path = existing_regular_file_path(
        arguments.calibration_aggregate, "calibration aggregate"
    )
    calibration = verify_packaged_calibration(calibration_path)
    require_aggregate_identity(calibration, source_commit, source_tree, "calibration")
    stage, temporary, output = prepare_stage(input_root, arguments.output_directory)
    try:
        copy_collector_output(input_root, stage, SOAK_INPUT_ENTRIES, "resource-soak")
        input_aggregate = load_aggregate(stage / "aggregate.json", "resource-soak")
        require_aggregate_identity(input_aggregate, source_commit, source_tree, "resource-soak")
        if input_aggregate.get("raw_evidence_archive") is not None:
            fail(
                "resource-soak input must be the original unarchived runner output; "
                "its raw_evidence_archive field must be null"
            )
        minimum_runs, retaining_subsystem, followup_issue = soak_options(input_aggregate)
        with tempfile.TemporaryDirectory(prefix="phase0-soak-prearchive-") as verification_directory:
            regenerated = reaggregate_soak(
                stage,
                Path(verification_directory) / "aggregate.json",
                Path(verification_directory) / "SOAK.md",
                source_commit,
                source_tree,
                calibration_path,
                minimum_runs,
                retaining_subsystem,
                followup_issue,
            )
        try:
            phase0_evidence.assert_regenerated_aggregate(
                input_aggregate,
                regenerated,
                "resource-soak collector output",
                ignored_paths=(("calibration_noise", "path"),),
            )
        except phase0_evidence.EvidenceValidationError as error:
            fail(str(error))
        raw_files = [
            *regular_files(stage / "collector", "resource-soak retained collector"),
            *regular_files(stage / "runs", "resource-soak raw runs"),
        ]
        manifest = write_manifest(stage, raw_files)
        archive = stage / "raw-evidence.tar.zst"
        create_zstd_tar(stage, [*raw_files, manifest], archive)
        write_archive_checksum(stage, archive)
        aggregate = reaggregate_soak(
            stage,
            stage / "aggregate.json",
            stage / "SOAK.md",
            source_commit,
            source_tree,
            calibration_path,
            minimum_runs,
            retaining_subsystem,
            followup_issue,
        )
        write_readme(stage, "Phase 0 native-Linux resource-soak evidence", aggregate)
        remove_staged_entry(stage / "runs")
        remove_staged_entry(stage / "collector")
        split_raw_evidence_archive(
            stage,
            archive,
            MAX_TRANSPORT_PART_BYTES,
            PORTABLE_PART_SCHEMA,
        )
        try:
            phase0_evidence.verify_resource_soak_evidence(stage / "aggregate.json", calibration_path)
        except phase0_evidence.EvidenceValidationError as error:
            fail(f"resource-soak package did not pass the gate verifier: {error}")
        publish_stage(stage, temporary, output)
    except Exception:
        temporary.cleanup()
        raise


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subcommands = result.add_subparsers(dest="kind", required=True)
    for name, help_text in (
        ("calibration", "package complete calibration collector output"),
        ("profile", "package complete hot-path profile collector output"),
        ("soak", "package complete resource-soak collector output"),
    ):
        command = subcommands.add_parser(name, help=help_text)
        command.add_argument("--input-directory", type=Path, required=True)
        command.add_argument("--output-directory", type=Path, required=True)
        command.add_argument("--source-commit", required=True)
        command.add_argument("--source-tree", required=True)
        if name in {"profile", "soak"}:
            command.add_argument("--calibration-aggregate", type=Path, required=True)
        if name == "profile":
            command.add_argument(
                "--profile-part-bytes",
                type=int,
                default=DEFAULT_PROFILE_PART_BYTES,
                help=f"maximum retained profile fragment size (default: {DEFAULT_PROFILE_PART_BYTES})",
            )
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.kind == "calibration":
            package_calibration(arguments)
        elif arguments.kind == "profile":
            package_profile(arguments)
        else:
            package_soak(arguments)
    except (PackagingError, OSError) as error:
        print(f"phase0 evidence packaging failed: {error}", file=sys.stderr)
        return 2
    print(f"packaged and independently verified {arguments.kind} evidence: {arguments.output_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
