"""Probe integrity tests, not Java guest conformance or runtime qualification."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("java_feasibility_probe", PROJECT / "probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class VersionTests(unittest.TestCase):
    def test_pinned_wasm_tools_includes_upstream_build_identity(self):
        self.assertTrue(probe.version_matches("wasm-tools 1.254.0 (bb58fdf91 2026-07-20)\n",
                                              "wasm-tools 1.254.0"))

    def test_pinned_wasm_tools_without_optional_build_identity(self):
        self.assertTrue(probe.version_matches("wasm-tools 1.254.0\n", "wasm-tools 1.254.0"))

    def test_similar_version_or_prerelease_is_not_the_pin(self):
        for value in ("1.254.01", "1.254.0-dev", "1.253.0", "1.254.0 (unverified)"):
            with self.subTest(value=value):
                self.assertFalse(probe.version_matches("wasm-tools " + value, "wasm-tools 1.254.0"))

    def test_gradle_version_is_an_exact_line_not_a_substring(self):
        self.assertTrue(probe.version_matches("Welcome\nGradle 9.1.0\nJVM info", "Gradle 9.1.0"))
        self.assertFalse(probe.version_matches("Gradle 9.1.01\n", "Gradle 9.1.0"))


class EvidenceTests(unittest.TestCase):
    def test_child_records_nonzero_compiler_status_without_relabelling_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exit.json"
            with mock.patch.object(probe.subprocess, "run", return_value=subprocess.CompletedProcess([], 17)) as run:
                probe.child([str(path), "trusted-compiler", "input.java"])
            self.assertEqual(json.loads(path.read_text()), {"started": True, "returncode": 17})
            run.assert_called_once_with(["trusted-compiler", "input.java"], check=False)

    def test_missing_executable_is_environment_failure_not_language_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exit.json"
            with mock.patch.object(probe.subprocess, "run", side_effect=FileNotFoundError):
                probe.child([str(path), "missing-compiler"])
            self.assertEqual(json.loads(path.read_text()), {"started": False, "error": "FileNotFoundError"})

    def test_child_does_not_swallow_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exit.json"
            with mock.patch.object(probe.subprocess, "run", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    probe.child([str(path), "trusted-compiler"])
            self.assertFalse(path.exists())

    def test_digest_tracks_actual_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data"
            path.write_bytes(b"abc")
            self.assertEqual(probe.digest(path), "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
            before = probe.digest(path)
            path.write_bytes(b"abcd")
            self.assertNotEqual(probe.digest(path), before)

    def test_existing_attempt_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "receipt.json"
            marker.write_text("previous-attempt")
            with mock.patch.object(sys, "argv", ["probe.py", "--output", directory]):
                with self.assertRaises(FileExistsError):
                    probe.main()
            self.assertEqual(marker.read_text(), "previous-attempt")


if __name__ == "__main__":
    unittest.main()
