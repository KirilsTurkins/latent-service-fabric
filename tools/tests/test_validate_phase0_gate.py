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
from unittest.mock import patch

from tools.phase0_evidence import (
    EvidenceValidationError,
    PROFILE_SCHEMA,
    _profile_required_candidate_runs,
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
HISTORICAL_CALIBRATION = (
    REPOSITORY_ROOT / "benchmarks/phase0/calibration/native-linux-2026-08-28-6a64f063/aggregate.json"
)
HISTORICAL_PROFILE_CALIBRATION = (
    REPOSITORY_ROOT
    / "benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/aggregate.json"
)
HISTORICAL_PROFILE = (
    REPOSITORY_ROOT / "benchmarks/phase0/profiling/native-linux-2026-08-27-de2337906/aggregate.json"
)
HISTORICAL_SOAK = (
    REPOSITORY_ROOT / "benchmarks/phase0/soak/native-linux-2026-08-28-6a64f063/aggregate.json"
)


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
    def test_profile_reverification_preserves_reference_and_experiment_run_counts(self) -> None:
        document = {
            "candidates": {
                "worker-cell-2w-2c": {"run_count": 7},
                "worker-cell-1w-1c": {"run_count": 3},
                "worker-cell-2w-4c": {"run_count": 3},
            }
        }
        self.assertEqual(_profile_required_candidate_runs(document), (3, 7))

        document["candidates"]["worker-cell-2w-4c"]["run_count"] = 4
        with self.assertRaisesRegex(
            EvidenceValidationError, "bounded experiment candidates do not retain one common"
        ):
            _profile_required_candidate_runs(document)

    def test_checked_in_calibration_is_regenerated_from_raw_runs(self) -> None:
        document = verify_calibration_evidence(HISTORICAL_CALIBRATION)
        self.assertEqual(document["status"], "pass")
        self.assertGreaterEqual(document["run_count"], 7)
        self.assertGreater(len(document["metrics"]), 0)

    def test_historical_calibration_fixture_is_not_gate_eligible_without_capsule_identity(self) -> None:
        document = verify_calibration_evidence(HISTORICAL_CALIBRATION)
        with self.assertRaisesRegex(GateValidationError, "calibration capsule digest"):
            validate_calibration(document, str(HISTORICAL_CALIBRATION))

        document["reference_identity"]["artifact"]["capsule_digest"] = "sha256:" + "a" * 64
        document["reference_identity"]["artifact"]["capsule_bytes"] = 1
        receipt = validate_calibration(document, str(HISTORICAL_CALIBRATION))
        self.assertEqual(receipt["status"], "pass")

    @unittest.skipUnless(shutil.which("zstd"), "zstd is required for archive integration verification")
    def test_checked_in_calibration_archive_is_lossless(self) -> None:
        archive = HISTORICAL_CALIBRATION.parent / "raw-evidence.tar.zst"
        manifest = HISTORICAL_CALIBRATION.parent / "raw-evidence.manifest.sha256"
        self.assertEqual(
            (HISTORICAL_CALIBRATION.parent / "raw-evidence.tar.zst.sha256").read_text(
                encoding="utf-8"
            ),
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
                verify_resource_soak_evidence(root / "aggregate.json", HISTORICAL_CALIBRATION)

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

    def test_historical_profile_fixture_is_not_gate_eligible_under_v5_schema(self) -> None:
        document = json.loads(HISTORICAL_PROFILE.read_text(encoding="utf-8"))
        self.assertNotEqual(document["schema_version"], PROFILE_SCHEMA)
        with self.assertRaisesRegex(GateValidationError, "unexpected hot-path profile schema"):
            validate_profiling(document, str(HISTORICAL_PROFILE))

    def test_checksums_validated_profile_calibration_with_different_identity_blocks_gate(self) -> None:
        """A separately verified profile calibration must still match the current tree.

        The verifier stubs deliberately represent already checksummed and
        regenerated evidence.  The regression isolates the public gate
        behavior: the optional ``--profile-calibration`` input cannot bypass
        canonical execution-identity binding merely because the profile
        archive references its checksum.
        """

        current_digest = "sha256:" + "1" * 64
        stale_digest = "sha256:" + "2" * 64
        current_commit = "a" * 40
        current_tree = "b" * 40
        stale_commit = "c" * 40
        stale_tree = "d" * 40
        calibration_path = Path("calibration.json")
        profile_calibration_path = Path("profile-calibration.json")
        profiling_path = Path("profiling.json")
        soak_path = Path("soak.json")
        calibration_document = {"archive_checksum_verified": True}
        profile_calibration_document = {"archive_checksum_verified": True}
        profiling_document = {"archive_checksum_verified": True}
        soak_document = {"archive_checksum_verified": True}

        configuration = {
            "pool_capacity": 2,
            "pool_queue_capacity": 4,
            "runtime_workers": 2,
            "prepared_cache_enabled": True,
            "wasmtime_instance_allocator": "on_demand",
            "wasmtime_copy_on_write_images": True,
        }
        toolchain = {
            "rustc": "rustc",
            "cargo": "cargo",
            "rust_target": "x86_64-unknown-linux-gnu",
            "build_profile": "release",
            "wasmtime_version": "wasmtime",
        }
        baseline_receipt = {
            "fixture": {"component_digest": "sha256:" + "e" * 64},
            "configuration": configuration,
            "toolchain": toolchain,
        }
        soak_receipt = {
            "source_commit": current_commit,
            "source_tree": current_tree,
            "configuration": {
                "artifact": {"component_digest": "sha256:" + "e" * 64, "component_bytes": 1},
                "config": configuration,
                "environment": toolchain,
            },
        }
        calibration_receipt = {"source_commit": current_commit, "source_tree": current_tree}
        profile_calibration_receipt = {"source_commit": stale_commit, "source_tree": stale_tree}
        profiling_receipt = {"source_commit": current_commit, "source_tree": current_tree}
        current_identity = {
            "sha256": current_digest,
            "worktree_clean": True,
            "commit": current_commit,
            "tree": current_tree,
        }

        def verified_calibration(path: Path) -> dict[str, bool]:
            if path == calibration_path:
                return calibration_document
            self.assertEqual(path, profile_calibration_path)
            return profile_calibration_document

        def validated_calibration(document: dict[str, bool], _path: str) -> dict[str, str]:
            if document is calibration_document:
                return calibration_receipt
            self.assertIs(document, profile_calibration_document)
            return profile_calibration_receipt

        def evidence_identity(commit: str, tree: str) -> dict[str, str]:
            if (commit, tree) == (stale_commit, stale_tree):
                return {"sha256": stale_digest}
            self.assertEqual((commit, tree), (current_commit, current_tree))
            return {"sha256": current_digest}

        with (
            patch(
                "tools.validate_phase0_gate.verify_calibration_evidence",
                side_effect=verified_calibration,
            ),
            patch(
                "tools.validate_phase0_gate.verify_profile_evidence",
                return_value=profiling_document,
            ) as verify_profile,
            patch(
                "tools.validate_phase0_gate.verify_resource_soak_evidence",
                return_value=soak_document,
            ),
            patch(
                "tools.validate_phase0_gate.current_execution_evidence_identity",
                return_value=current_identity,
            ),
            patch(
                "tools.validate_phase0_gate.validate_baseline",
                return_value=baseline_receipt,
            ),
            patch(
                "tools.validate_phase0_gate.validate_calibration",
                side_effect=validated_calibration,
            ),
            patch(
                "tools.validate_phase0_gate.validate_profiling",
                return_value=profiling_receipt,
            ),
            patch(
                "tools.validate_phase0_gate.validate_resource_soak",
                return_value=(soak_receipt, []),
            ),
            patch(
                "tools.validate_phase0_gate.execution_evidence_identity",
                side_effect=evidence_identity,
            ),
        ):
            receipt = build_gate_receipt(
                {},
                "baseline.json",
                calibration_path,
                profiling_path,
                soak_path,
                profile_calibration_path,
            )

        verify_profile.assert_called_once_with(profiling_path, profile_calibration_path)
        self.assertEqual(receipt["authorization_status"], "blocked")
        self.assertFalse(receipt["phase1_authorized"])
        self.assertEqual(
            receipt["blockers"],
            [
                "profile calibration execution evidence identity does not match "
                "the current executable implementation"
            ],
        )
        self.assertEqual(
            receipt["execution_evidence"]["retained"]["profile calibration"]["sha256"],
            stale_digest,
        )

    @unittest.skipUnless(shutil.which("zstd"), "zstd is required for archive integration verification")
    def test_historical_calibration_and_soak_archives_are_verified_but_profile_is_not_gate_eligible(self) -> None:
        calibration = verify_calibration_evidence(HISTORICAL_CALIBRATION)
        profile_calibration = verify_calibration_evidence(HISTORICAL_PROFILE_CALIBRATION)
        soak = verify_resource_soak_evidence(HISTORICAL_SOAK, HISTORICAL_CALIBRATION)
        self.assertEqual(calibration["status"], "pass")
        self.assertEqual(profile_calibration["status"], "pass")
        self.assertEqual(soak["status"], "pass")
        with self.assertRaisesRegex(EvidenceValidationError, "unexpected profiling schema"):
            verify_profile_evidence(HISTORICAL_PROFILE, HISTORICAL_PROFILE_CALIBRATION)


if __name__ == "__main__":
    unittest.main()
