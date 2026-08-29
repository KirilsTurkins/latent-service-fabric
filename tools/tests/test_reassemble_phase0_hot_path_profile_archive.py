from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REASSEMBLER = ROOT / "tools" / "reassemble_phase0_hot_path_profile_archive.py"


def checksum(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


class ReassembleHotPathArchiveTests(unittest.TestCase):
    def test_reassembles_verified_parts_without_overwriting_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_directory = root / "archive"
            archive_directory.mkdir()
            source = b"phase0-evidence-" * 100
            parts = [source[:400], source[400:]]
            manifest_parts = []
            for index, part in enumerate(parts, start=1):
                name = f"raw-evidence.tar.zst.part-{index:03d}"
                (archive_directory / name).write_bytes(part)
                manifest_parts.append({"path": name, "bytes": len(part), "sha256": checksum(part)})
            (archive_directory / "raw-evidence.parts.json").write_text(
                json.dumps(
                    {
                        "schema_version": "latent.phase0.hot-path.raw-evidence.parts.v1",
                        "archive": "raw-evidence.tar.zst",
                        "archive_bytes": len(source),
                        "archive_sha256": checksum(source),
                        "parts": manifest_parts,
                    }
                ),
                encoding="utf-8",
            )
            output = root / "reassembled.tar.zst"
            command = [
                sys.executable,
                str(REASSEMBLER),
                "--archive-directory",
                str(archive_directory),
                "--output",
                str(output),
            ]
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_bytes(), source)
            retry = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertNotEqual(retry.returncode, 0)
            self.assertIn("refusing to overwrite", retry.stderr)

    def test_checked_in_zstd_archive_and_manifest_are_valid(self) -> None:
        archive_roots = sorted(
            directory
            for directory in (ROOT / "benchmarks" / "phase0" / "profiling").glob("native-linux-*")
            if (directory / "raw-evidence.parts.json").is_file()
        )
        self.assertGreaterEqual(len(archive_roots), 1, archive_roots)
        self.assertIsNotNone(shutil.which("zstd"), "zstd is required for evidence integrity")
        for archive_root in archive_roots:
            with self.subTest(archive_root=archive_root.name):
                with tempfile.TemporaryDirectory() as directory:
                    temporary = Path(directory)
                    archive = temporary / "raw-evidence.tar.zst"
                    reassembled = subprocess.run(
                        [
                            sys.executable,
                            str(REASSEMBLER),
                            "--archive-directory",
                            str(archive_root),
                            "--output",
                            str(archive),
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(reassembled.returncode, 0, reassembled.stderr)
                    integrity = subprocess.run(
                        ["zstd", "--test", str(archive)], text=True, capture_output=True, check=False
                    )
                    self.assertEqual(integrity.returncode, 0, integrity.stderr)
                    extracted = temporary / "extracted"
                    extracted.mkdir()
                    extraction = subprocess.run(
                        ["tar", "--use-compress-program=zstd", "-xf", str(archive), "-C", str(extracted)],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(extraction.returncode, 0, extraction.stderr)
                    manifest = subprocess.run(
                        ["sha256sum", "--check", "raw-evidence.manifest.sha256"],
                        cwd=extracted,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(manifest.returncode, 0, manifest.stderr)
