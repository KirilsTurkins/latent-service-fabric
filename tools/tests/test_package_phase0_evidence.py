from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import package_phase0_evidence as packager
from tools.phase0_evidence import (
    verify_calibration_evidence,
    verify_resource_soak_evidence,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGER = ROOT / "tools" / "package_phase0_evidence.py"
REASSEMBLER = ROOT / "tools" / "reassemble_phase0_hot_path_profile_archive.py"
SOAK_AGGREGATOR = ROOT / "tools" / "aggregate_phase0_resource_soak.py"

CALIBRATION_ROOT = ROOT / "benchmarks/phase0/calibration/native-linux-2026-08-28-6a64f063"
PROFILE_CALIBRATION = (
    ROOT / "benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/aggregate.json"
)
PROFILE_ROOT = ROOT / "benchmarks/phase0/profiling/native-linux-2026-08-27-de2337906"
SOAK_ROOT = ROOT / "benchmarks/phase0/soak/native-linux-2026-08-28-6a64f063"


def source_identity(aggregate_path: Path) -> tuple[str, str]:
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    return aggregate["source_commit"], aggregate["source_tree"]


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def extract_zstd_archive(archive: Path, destination: Path) -> None:
    destination.mkdir()
    result = run(
        ["tar", "--use-compress-program=zstd", "-xf", str(archive), "-C", str(destination)]
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    (destination / "raw-evidence.manifest.sha256").unlink()


def reassemble_sharded_archive(package: Path, output: Path) -> None:
    result = run(
        [
            sys.executable,
            str(REASSEMBLER),
            "--archive-directory",
            str(package),
            "--output",
            str(output),
        ]
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)


def add_retained_collector(directory: Path, executable: str) -> Path:
    collector = directory / "collector"
    collector.mkdir(exist_ok=True)
    binary = collector / executable
    binary.write_bytes(f"retained {executable}\n".encode())
    return binary


@unittest.skipUnless(
    shutil.which("zstd") and shutil.which("tar"),
    "zstd and tar are required for Phase 0 packaging integration tests",
)
class PackagePhase0EvidenceTests(unittest.TestCase):
    def package(
        self,
        kind: str,
        input_directory: Path,
        output_directory: Path,
        source_commit: str,
        source_tree: str,
        calibration: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(PACKAGER),
            kind,
            "--input-directory",
            str(input_directory),
            "--output-directory",
            str(output_directory),
            "--source-commit",
            source_commit,
            "--source-tree",
            source_tree,
        ]
        if calibration is not None:
            command.extend(["--calibration-aggregate", str(calibration)])
        return run(command)

    def test_historical_calibration_is_integrity_verifiable_but_not_packaged_as_current_evidence(self) -> None:
        source_commit, source_tree = source_identity(CALIBRATION_ROOT / "aggregate.json")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw = temporary / "calibration-raw"
            extract_zstd_archive(CALIBRATION_ROOT / "raw-evidence.tar.zst", raw)
            add_retained_collector(raw, "phase0-baseline")
            for name in ("aggregate.json", "CALIBRATION.md"):
                shutil.copyfile(CALIBRATION_ROOT / name, raw / name)
            original_aggregate = (raw / "aggregate.json").read_bytes()
            original_report = (raw / "CALIBRATION.md").read_bytes()
            package = temporary / "calibration-package"

            result = self.package("calibration", raw, package, source_commit, source_tree)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected schema", result.stderr)
            self.assertEqual((raw / "aggregate.json").read_bytes(), original_aggregate)
            self.assertEqual((raw / "CALIBRATION.md").read_bytes(), original_report)
            self.assertFalse(package.exists())
            verified = verify_calibration_evidence(CALIBRATION_ROOT / "aggregate.json")
            self.assertEqual(verified["source_commit"], source_commit)

    def test_refuses_profile_with_a_valid_differently_identified_calibration(self) -> None:
        source_commit, source_tree = source_identity(PROFILE_ROOT / "aggregate.json")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            assembled = temporary / "profile.tar.zst"
            reassembled = run(
                [
                    sys.executable,
                    str(REASSEMBLER),
                    "--archive-directory",
                    str(PROFILE_ROOT),
                    "--output",
                    str(assembled),
                ]
            )
            self.assertEqual(reassembled.returncode, 0, reassembled.stderr)
            raw = temporary / "profile-raw"
            extract_zstd_archive(assembled, raw)
            add_retained_collector(raw, "phase0-baseline")
            original_aggregate = (raw / "aggregate.json").read_bytes()
            original_report = (raw / "PROFILE.md").read_bytes()
            package = temporary / "profile-package"

            result = self.package(
                "profile",
                raw,
                package,
                source_commit,
                source_tree,
                PROFILE_CALIBRATION,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("historical integrity-only evidence", result.stderr)
            self.assertEqual((raw / "aggregate.json").read_bytes(), original_aggregate)
            self.assertEqual((raw / "PROFILE.md").read_bytes(), original_report)
            self.assertFalse(package.exists())

    def test_historical_soak_can_be_reaggregated_for_integrity_but_not_packaged_as_current_evidence(self) -> None:
        source_commit, source_tree = source_identity(SOAK_ROOT / "aggregate.json")
        calibration = CALIBRATION_ROOT / "aggregate.json"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw = temporary / "soak-raw"
            extract_zstd_archive(SOAK_ROOT / "raw-evidence.tar.zst", raw)
            add_retained_collector(raw, "phase0-soak")
            initial = run(
                [
                    sys.executable,
                    str(SOAK_AGGREGATOR),
                    "aggregate",
                    "--runs-directory",
                    str(raw / "runs"),
                    "--output-json",
                    str(raw / "aggregate.json"),
                    "--output-report",
                    str(raw / "SOAK.md"),
                    "--source-commit",
                    source_commit,
                    "--source-tree",
                    source_tree,
                    "--calibration",
                    str(calibration),
                    "--minimum-runs",
                    "3",
                ]
            )
            self.assertEqual(initial.returncode, 0, initial.stderr)
            original_aggregate = (raw / "aggregate.json").read_bytes()
            original_report = (raw / "SOAK.md").read_bytes()
            package = temporary / "soak-package"

            result = self.package(
                "soak", raw, package, source_commit, source_tree, calibration
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("historical integrity-only evidence", result.stderr)
            self.assertEqual((raw / "aggregate.json").read_bytes(), original_aggregate)
            self.assertEqual((raw / "SOAK.md").read_bytes(), original_report)
            self.assertFalse(package.exists())
            verified = verify_resource_soak_evidence(SOAK_ROOT / "aggregate.json", calibration)
            self.assertEqual(verified["raw_evidence_archive"]["path"], "raw-evidence.tar.zst")
            self.assertEqual(verified["source_commit"], source_commit)

    def test_sharded_historical_calibration_remains_integrity_verifiable(self) -> None:
        source_commit, _ = source_identity(CALIBRATION_ROOT / "aggregate.json")
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "calibration"
            shutil.copytree(CALIBRATION_ROOT, package)
            packager.split_raw_evidence_archive(
                package,
                package / "raw-evidence.tar.zst",
                1024,
                packager.PORTABLE_PART_SCHEMA,
            )

            verified = verify_calibration_evidence(package / "aggregate.json")

            self.assertEqual(verified["source_commit"], source_commit)
            self.assertFalse((package / "raw-evidence.tar.zst").exists())

    def test_sharded_historical_soak_remains_integrity_verifiable(self) -> None:
        source_commit, _ = source_identity(SOAK_ROOT / "aggregate.json")
        calibration = CALIBRATION_ROOT / "aggregate.json"
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "soak"
            shutil.copytree(SOAK_ROOT, package)
            packager.split_raw_evidence_archive(
                package,
                package / "raw-evidence.tar.zst",
                1024,
                packager.PORTABLE_PART_SCHEMA,
            )

            verified = verify_resource_soak_evidence(
                package / "aggregate.json", calibration
            )

            self.assertEqual(verified["source_commit"], source_commit)
            self.assertFalse((package / "raw-evidence.tar.zst").exists())

    def test_refuses_to_overwrite_an_existing_destination(self) -> None:
        source_commit, source_tree = source_identity(CALIBRATION_ROOT / "aggregate.json")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw = temporary / "calibration-raw"
            extract_zstd_archive(CALIBRATION_ROOT / "raw-evidence.tar.zst", raw)
            add_retained_collector(raw, "phase0-baseline")
            for name in ("aggregate.json", "CALIBRATION.md"):
                shutil.copyfile(CALIBRATION_ROOT / name, raw / name)
            package = temporary / "already-there"
            package.mkdir()
            marker = package / "keep.txt"
            marker.write_text("do not overwrite\n", encoding="utf-8")

            result = self.package("calibration", raw, package, source_commit, source_tree)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not already exist", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "do not overwrite\n")

    def test_refuses_a_dangling_symlink_destination(self) -> None:
        source_commit, source_tree = source_identity(CALIBRATION_ROOT / "aggregate.json")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw = temporary / "calibration-raw"
            extract_zstd_archive(CALIBRATION_ROOT / "raw-evidence.tar.zst", raw)
            add_retained_collector(raw, "phase0-baseline")
            for name in ("aggregate.json", "CALIBRATION.md"):
                shutil.copyfile(CALIBRATION_ROOT / name, raw / name)
            target = temporary / "redirected-package"
            package = temporary / "package-link"
            os.symlink(target, package)

            result = self.package("calibration", raw, package, source_commit, source_tree)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symbolic-link path component", result.stderr)
            self.assertTrue(package.is_symlink())
            self.assertFalse(target.exists())

    def test_refuses_soak_with_a_valid_differently_identified_calibration(self) -> None:
        source_commit, source_tree = source_identity(SOAK_ROOT / "aggregate.json")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw = temporary / "soak-raw"
            extract_zstd_archive(SOAK_ROOT / "raw-evidence.tar.zst", raw)
            add_retained_collector(raw, "phase0-soak")
            for name in ("aggregate.json", "SOAK.md"):
                shutil.copyfile(SOAK_ROOT / name, raw / name)
            package = temporary / "soak-package"

            result = self.package(
                "soak", raw, package, source_commit, source_tree, PROFILE_CALIBRATION
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("historical integrity-only evidence", result.stderr)
            self.assertFalse(package.exists())

    def test_calibration_raw_archive_retains_the_native_collector(self) -> None:
        source_commit = "1" * 40
        source_tree = "2" * 40
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw = temporary / "calibration-raw"
            raw.mkdir()
            (raw / "runs").mkdir()
            (raw / "runs" / "run-01.json").write_text("{}\n", encoding="utf-8")
            add_retained_collector(raw, "phase0-baseline")
            (raw / "aggregate.json").write_text(
                json.dumps(
                    {
                        "source_commit": source_commit,
                        "source_tree": source_tree,
                    }
                ),
                encoding="utf-8",
            )
            (raw / "CALIBRATION.md").write_text("calibration\n", encoding="utf-8")
            package = temporary / "calibration-package"

            with (
                mock.patch.object(packager.calibration_aggregate, "verify_aggregate"),
                mock.patch.object(
                    packager.phase0_evidence,
                    "verify_calibration_evidence",
                    return_value={},
                ),
            ):
                packager.package_calibration(
                    SimpleNamespace(
                        input_directory=raw,
                        output_directory=package,
                        source_commit=source_commit,
                        source_tree=source_tree,
                    )
                )

            archive = temporary / "calibration.tar.zst"
            reassemble_sharded_archive(package, archive)
            extracted = temporary / "extracted"
            extract_zstd_archive(archive, extracted)
            self.assertEqual(
                (extracted / "collector" / "phase0-baseline").read_bytes(),
                b"retained phase0-baseline\n",
            )
            self.assertTrue((extracted / "runs" / "run-01.json").is_file())
            self.assertFalse((package / "collector").exists())
            parts = json.loads(
                (package / "raw-evidence.parts.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                parts["schema_version"], packager.PORTABLE_PART_SCHEMA
            )
            self.assertTrue(
                all(
                    part["bytes"] <= packager.MAX_TRANSPORT_PART_BYTES
                    for part in parts["parts"]
                )
            )
            self.assertFalse((package / "raw-evidence.tar.zst").exists())

    def test_profile_raw_archive_manifest_retains_the_native_collector(self) -> None:
        source_commit = "1" * 40
        source_tree = "2" * 40
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw = temporary / "profile-raw"
            raw.mkdir()
            aggregate = {
                "source_commit": source_commit,
                "source_tree": source_tree,
            }
            (raw / "aggregate.json").write_text(
                json.dumps(aggregate), encoding="utf-8"
            )
            for name in ("PROFILE.md", "host-before.json", "bootstrap.log"):
                (raw / name).write_text(f"{name}\n", encoding="utf-8")
            for name in (
                "bootstrap",
                "full-invariant-proof",
                "profiles",
                "candidates",
            ):
                evidence = raw / name
                evidence.mkdir()
                (evidence / "retained.dat").write_text(
                    f"{name}\n", encoding="utf-8"
                )
            add_retained_collector(raw, "phase0-baseline")
            calibration = temporary / "calibration.json"
            calibration.write_text("{}\n", encoding="utf-8")
            package = temporary / "profile-package"

            with (
                mock.patch.object(
                    packager,
                    "verify_packaged_calibration",
                    return_value=aggregate,
                ),
                mock.patch.object(
                    packager.phase0_evidence,
                    "verify_profile_evidence",
                    return_value={},
                ),
            ):
                packager.package_profile(
                    SimpleNamespace(
                        input_directory=raw,
                        output_directory=package,
                        source_commit=source_commit,
                        source_tree=source_tree,
                        calibration_aggregate=calibration,
                        profile_part_bytes=1024,
                    )
                )

            manifest = (package / "raw-evidence.manifest.sha256").read_text(
                encoding="utf-8"
            )
            self.assertIn("  collector/phase0-baseline\n", manifest)
            self.assertFalse((package / "collector").exists())

    def test_soak_raw_archive_retains_the_native_collector(self) -> None:
        source_commit = "1" * 40
        source_tree = "2" * 40
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw = temporary / "soak-raw"
            raw.mkdir()
            aggregate = {
                "source_commit": source_commit,
                "source_tree": source_tree,
                "minimum_required_run_count": 3,
                "raw_evidence_archive": None,
            }
            (raw / "aggregate.json").write_text(
                json.dumps(aggregate), encoding="utf-8"
            )
            (raw / "SOAK.md").write_text("soak\n", encoding="utf-8")
            (raw / "runs").mkdir()
            (raw / "runs" / "run-01.json").write_text("{}\n", encoding="utf-8")
            add_retained_collector(raw, "phase0-soak")
            calibration = temporary / "calibration.json"
            calibration.write_text("{}\n", encoding="utf-8")
            package = temporary / "soak-package"

            with (
                mock.patch.object(
                    packager,
                    "verify_packaged_calibration",
                    return_value=aggregate,
                ),
                mock.patch.object(
                    packager, "reaggregate_soak", return_value=aggregate
                ),
                mock.patch.object(
                    packager.phase0_evidence, "assert_regenerated_aggregate"
                ),
                mock.patch.object(
                    packager.phase0_evidence,
                    "verify_resource_soak_evidence",
                    return_value={},
                ),
            ):
                packager.package_soak(
                    SimpleNamespace(
                        input_directory=raw,
                        output_directory=package,
                        source_commit=source_commit,
                        source_tree=source_tree,
                        calibration_aggregate=calibration,
                    )
                )

            archive = temporary / "soak.tar.zst"
            reassemble_sharded_archive(package, archive)
            extracted = temporary / "extracted"
            extract_zstd_archive(archive, extracted)
            self.assertEqual(
                (extracted / "collector" / "phase0-soak").read_bytes(),
                b"retained phase0-soak\n",
            )
            self.assertTrue((extracted / "runs" / "run-01.json").is_file())
            self.assertFalse((package / "collector").exists())
            parts = json.loads(
                (package / "raw-evidence.parts.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                parts["schema_version"], packager.PORTABLE_PART_SCHEMA
            )
            self.assertTrue(
                all(
                    part["bytes"] <= packager.MAX_TRANSPORT_PART_BYTES
                    for part in parts["parts"]
                )
            )
            self.assertFalse((package / "raw-evidence.tar.zst").exists())

    def test_packaging_input_contract_names_each_retained_collector_directory(self) -> None:
        self.assertEqual(
            packager.CALIBRATION_INPUT_ENTRIES,
            {"aggregate.json", "CALIBRATION.md", "collector", "runs"},
        )
        self.assertIn("collector", packager.PROFILE_INPUT_ENTRIES)
        self.assertEqual(
            packager.SOAK_INPUT_ENTRIES,
            {"aggregate.json", "SOAK.md", "collector", "runs"},
        )


if __name__ == "__main__":
    unittest.main()
