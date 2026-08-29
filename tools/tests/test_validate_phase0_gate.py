from __future__ import annotations

import io
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from tools.phase0_evidence import (
    EvidenceValidationError,
    extract_tar_stream,
    verify_calibration_evidence,
    verify_profile_evidence,
    verify_resource_soak_evidence,
)
from tools.validate_phase0_gate import (
    GateValidationError,
    build_gate_receipt,
    validate_calibration,
    validate_profiling,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CALIBRATION = REPOSITORY_ROOT / "benchmarks/phase0/calibration/native-linux-2026-08-28-6a64f063/aggregate.json"
PROFILE_CALIBRATION = REPOSITORY_ROOT / "benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/aggregate.json"
PROFILE = REPOSITORY_ROOT / "benchmarks/phase0/profiling/native-linux-2026-08-27-de2337906/aggregate.json"
SOAK = REPOSITORY_ROOT / "benchmarks/phase0/soak/native-linux-2026-08-28-6a64f063/aggregate.json"


def tar_bytes(members: list[tuple[str, bytes, str]]) -> io.BytesIO:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, contents, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                info.size = len(contents)
                archive.addfile(info, io.BytesIO(contents))
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "outside"
                archive.addfile(info)
            else:
                raise AssertionError(f"unknown member kind {kind}")
    stream.seek(0)
    return stream


class Phase0GateEvidenceTests(unittest.TestCase):
    def test_checked_in_calibration_is_regenerated_from_raw_runs(self) -> None:
        document = verify_calibration_evidence(CALIBRATION)
        self.assertEqual(document["status"], "pass")
        self.assertGreaterEqual(document["run_count"], 7)
        self.assertGreater(len(document["metrics"]), 0)

    def test_gate_accepts_the_retained_calibration_hard_check_set(self) -> None:
        document = verify_calibration_evidence(CALIBRATION)
        receipt = validate_calibration(document, str(CALIBRATION))
        self.assertEqual(receipt["status"], "pass")

    @unittest.skipUnless(shutil.which("zstd"), "zstd is required for archive integration verification")
    def test_checked_in_calibration_archive_is_lossless(self) -> None:
        archive = CALIBRATION.parent / "raw-evidence.tar.zst"
        manifest = CALIBRATION.parent / "raw-evidence.manifest.sha256"
        self.assertEqual(
            (CALIBRATION.parent / "raw-evidence.tar.zst.sha256").read_text(encoding="utf-8"),
            f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  raw-evidence.tar.zst\n",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            extracted = Path(temporary_directory)
            result = subprocess.run(
                ["tar", "--use-compress-program=zstd", "-xf", str(archive), "-C", str(extracted)],
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (extracted / "raw-evidence.manifest.sha256").read_bytes(),
                manifest.read_bytes(),
            )
            checks = subprocess.run(
                ["sha256sum", "--check", "raw-evidence.manifest.sha256"],
                cwd=extracted,
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(checks.returncode, 0, checks.stderr)

    def test_safe_extractor_rejects_path_traversal_and_links(self) -> None:
        for name, contents, kind, expected in (
            ("../outside.json", b"bad", "file", "traversal"),
            ("C:/outside.json", b"bad", "file", "drive-qualified"),
            ("runs/run-01/raw.json", b"bad", "symlink", "prohibited link"),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary_directory:
                destination = Path(temporary_directory) / "extract"
                with self.assertRaisesRegex(EvidenceValidationError, expected):
                    extract_tar_stream(tar_bytes([(name, contents, kind)]), destination, "test archive")

    def test_safe_extractor_rejects_duplicate_normalized_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "extract"
            archive = tar_bytes(
                [
                    ("runs/run-01/raw.json", b"first", "file"),
                    ("./runs/run-01/raw.json", b"second", "file"),
                ]
            )
            with self.assertRaisesRegex(EvidenceValidationError, "duplicate path"):
                extract_tar_stream(archive, destination, "test archive")

    def test_arbitrary_archive_bytes_cannot_substitute_for_raw_soak_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "raw-evidence.tar.zst").write_bytes(b"synthetic evidence")
            (root / "raw-evidence.tar.zst.sha256").write_text(
                "00" * 32 + "  raw-evidence.tar.zst\n", encoding="utf-8"
            )
            (root / "raw-evidence.manifest.sha256").write_text(
                "00" * 32 + "  runs/run-01/raw.json\n", encoding="utf-8"
            )
            (root / "aggregate.json").write_text(
                json.dumps(
                    {
                        "schema_version": "latent.phase0.resource-soak.aggregate.v1",
                        "raw_evidence_archive": {
                            "path": "raw-evidence.tar.zst",
                            "manifest": "raw-evidence.manifest.sha256",
                            "sha256": "sha256:" + "00" * 32,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "README.md").write_text("evidence", encoding="utf-8")
            (root / "SOAK.md").write_text("evidence", encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                verify_resource_soak_evidence(root / "aggregate.json", CALIBRATION)

    def test_passing_summary_fields_cannot_authorize_without_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            calibration = root / "calibration.json"
            profile = root / "profile.json"
            soak = root / "soak.json"
            calibration.write_text(
                json.dumps(
                    {
                        "schema_version": "latent.phase0.calibration.v1",
                        "status": "pass",
                        "minimum_required_run_count": 7,
                        "raw_runs": [],
                    }
                ),
                encoding="utf-8",
            )
            profile.write_text(
                json.dumps({"schema_version": "latent.phase0.hot-path.aggregate.v3", "status": "pass"}),
                encoding="utf-8",
            )
            soak.write_text(
                json.dumps({"schema_version": "latent.phase0.resource-soak.aggregate.v1", "status": "pass"}),
                encoding="utf-8",
            )
            with self.assertRaises(GateValidationError):
                build_gate_receipt({}, "placeholder-baseline.json", calibration, profile, soak)

    def test_profile_decisions_are_not_free_form_strings(self) -> None:
        document = json.loads(PROFILE.read_text(encoding="utf-8"))
        document["decisions"][0]["decision"] = "whatever seems reasonable"
        with self.assertRaisesRegex(GateValidationError, "not permitted"):
            validate_profiling(document, str(PROFILE))

    @unittest.skipUnless(shutil.which("zstd"), "zstd is required for archive integration verification")
    def test_checked_in_profile_and_soak_archives_are_verified_and_regenerated(self) -> None:
        calibration = verify_calibration_evidence(CALIBRATION)
        profile_calibration = verify_calibration_evidence(PROFILE_CALIBRATION)
        profile = verify_profile_evidence(PROFILE, PROFILE_CALIBRATION)
        soak = verify_resource_soak_evidence(SOAK, CALIBRATION)
        self.assertEqual(calibration["status"], "pass")
        self.assertEqual(profile_calibration["status"], "pass")
        self.assertEqual(profile["status"], "pass")
        self.assertEqual(soak["status"], "pass")


if __name__ == "__main__":
    unittest.main()
