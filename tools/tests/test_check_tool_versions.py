from __future__ import annotations

import importlib.util
import subprocess
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "check_tool_versions.py"
SPEC = importlib.util.spec_from_file_location("check_tool_versions", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
versions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(versions)


class VersionParsingTests(unittest.TestCase):
    def test_extracts_versions(self) -> None:
        self.assertEqual(
            versions.extract(r"\bgo(\d+\.\d+\.\d+)\b", "go version go1.23.2 linux/amd64", "Go"),
            "1.23.2",
        )
        self.assertEqual(
            versions.extract(r"^Version\s+(\S+)$", "Version 5.8.3", "TypeScript"),
            "5.8.3",
        )
        self.assertEqual(
            versions.extract(
                r"^clang version (\d+\.\d+\.\d+)",
                "clang version 21.1.0 (Zig 0.16.0)",
                "Zig C frontend",
            ),
            "21.1.0",
        )

    def test_parses_temurin_runtime_version(self) -> None:
        output = """
            java.vendor = Eclipse Adoptium
            java.runtime.version = 21.0.11+10-LTS
        """
        self.assertEqual(versions.java_runtime_version(output), "21.0.11+10-LTS")
        self.assertEqual(versions.normalize_temurin_runtime("21.0.11+10-LTS"), "21.0.11+10")

    def test_exact_version_mismatch_fails(self) -> None:
        with self.assertRaises(versions.VersionError):
            versions.require_exact("Zig", "0.15.2", "0.16.0")


class VersionProbeTests(unittest.TestCase):
    def test_run_passes_finite_timeout(self) -> None:
        completed = subprocess.CompletedProcess(
            ["go", "version"],
            0,
            stdout="go version go1.23.2 linux/amd64\n",
        )
        with mock.patch.object(versions.subprocess, "run", return_value=completed) as run:
            self.assertEqual(
                versions.run(["go", "version"], "Go"),
                "go version go1.23.2 linux/amd64",
            )

        run.assert_called_once_with(
            ["go", "version"],
            cwd=versions.ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=versions.PROBE_TIMEOUT_SECONDS,
        )
        self.assertGreater(versions.PROBE_TIMEOUT_SECONDS, 0)

    def test_run_reports_timeout_without_captured_output(self) -> None:
        expired = subprocess.TimeoutExpired(
            cmd=["go", "version"],
            timeout=versions.PROBE_TIMEOUT_SECONDS,
            output="ignored tool output",
        )
        with mock.patch.object(versions.subprocess, "run", side_effect=expired):
            with self.assertRaisesRegex(
                versions.VersionError,
                r"^Go version probe timed out after 30 seconds$",
            ):
                versions.run(["go", "version"], "Go")

    def test_main_returns_one_for_probe_timeout(self) -> None:
        stderr = StringIO()
        with mock.patch.object(
            versions,
            "validate",
            side_effect=versions.VersionError("Go version probe timed out after 30 seconds"),
        ):
            with redirect_stderr(stderr):
                self.assertEqual(versions.main(), 1)

        self.assertEqual(
            stderr.getvalue(),
            "toolchain validation failed: Go version probe timed out after 30 seconds\n",
        )
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertNotIn("ignored tool output", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
