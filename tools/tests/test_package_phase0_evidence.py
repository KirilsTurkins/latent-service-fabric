from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

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

    def test_packages_a_verified_calibration_without_changing_collector_output(self) -> None:
        source_commit, source_tree = source_identity(CALIBRATION_ROOT / "aggregate.json")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw = temporary / "calibration-raw"
            extract_zstd_archive(CALIBRATION_ROOT / "raw-evidence.tar.zst", raw)
            for name in ("aggregate.json", "CALIBRATION.md"):
                shutil.copyfile(CALIBRATION_ROOT / name, raw / name)
            original_aggregate = (raw / "aggregate.json").read_bytes()
            original_report = (raw / "CALIBRATION.md").read_bytes()
            package = temporary / "calibration-package"

            result = self.package("calibration", raw, package, source_commit, source_tree)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((raw / "aggregate.json").read_bytes(), original_aggregate)
            self.assertEqual((raw / "CALIBRATION.md").read_bytes(), original_report)
            self.assertEqual(
                {path.name for path in package.iterdir()},
                {
                    "aggregate.json",
                    "CALIBRATION.md",
                    "raw-evidence.manifest.sha256",
                    "raw-evidence.tar.zst",
                    "raw-evidence.tar.zst.sha256",
                },
            )
            verified = verify_calibration_evidence(package / "aggregate.json")
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
            self.assertIn(
                "calibration aggregate source commit does not match the declared source commit",
                result.stderr,
            )
            self.assertEqual((raw / "aggregate.json").read_bytes(), original_aggregate)
            self.assertEqual((raw / "PROFILE.md").read_bytes(), original_report)
            self.assertFalse(package.exists())

    def test_packages_unarchived_soak_by_reaggregating_through_the_existing_tool(self) -> None:
        source_commit, source_tree = source_identity(SOAK_ROOT / "aggregate.json")
        calibration = CALIBRATION_ROOT / "aggregate.json"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw = temporary / "soak-raw"
            extract_zstd_archive(SOAK_ROOT / "raw-evidence.tar.zst", raw)
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

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((raw / "aggregate.json").read_bytes(), original_aggregate)
            self.assertEqual((raw / "SOAK.md").read_bytes(), original_report)
            verified = verify_resource_soak_evidence(package / "aggregate.json", calibration)
            self.assertEqual(verified["raw_evidence_archive"]["path"], "raw-evidence.tar.zst")
            self.assertEqual(verified["source_commit"], source_commit)

    def test_refuses_to_overwrite_an_existing_destination(self) -> None:
        source_commit, source_tree = source_identity(CALIBRATION_ROOT / "aggregate.json")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            raw = temporary / "calibration-raw"
            extract_zstd_archive(CALIBRATION_ROOT / "raw-evidence.tar.zst", raw)
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
            for name in ("aggregate.json", "SOAK.md"):
                shutil.copyfile(SOAK_ROOT / name, raw / name)
            package = temporary / "soak-package"

            result = self.package(
                "soak", raw, package, source_commit, source_tree, PROFILE_CALIBRATION
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "calibration aggregate source commit does not match the declared source commit",
                result.stderr,
            )
            self.assertFalse(package.exists())


if __name__ == "__main__":
    unittest.main()
