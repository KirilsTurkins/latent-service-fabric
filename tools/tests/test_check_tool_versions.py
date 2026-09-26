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
            versions.extract(r"\bgo(\d+\.\d+\.\d+)\b", "go version go1.27.1 linux/amd64", "Go"),
            "1.27.1",
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
            java.runtime.version = 25.0.4.1+1-LTS
        """
        self.assertEqual(versions.java_runtime_version(output), "25.0.4.1+1-LTS")
        self.assertEqual(versions.normalize_temurin_runtime("25.0.4.1+1-LTS"), "25.0.4.1+1")

    def test_exact_version_mismatch_fails(self) -> None:
        with self.assertRaises(versions.VersionError):
            versions.require_exact("Zig", "0.15.2", "0.16.0")


class JavaQualificationTests(unittest.TestCase):
    expected = "25.0.4.1+1"

    @staticmethod
    def output(runtime="25.0.4.1+1-LTS", vendor="Eclipse Adoptium", compiler="25.0.4.1"):
        return f"    java.vendor = {vendor}\n    java.runtime.version = {runtime}\njavac {compiler}\n"

    def test_qualifies_exact_temurin_with_and_without_lts_suffix(self):
        for suffix in ("", "-LTS"):
            with self.subTest(suffix=suffix), mock.patch.object(
                versions, "run", return_value=self.output(runtime=self.expected + suffix)
            ) as run:
                versions.validate_java(self.expected)
                self.assertEqual(run.call_args_list, [
                    mock.call(["javac", "-J-XshowSettings:properties", "-version"], "javac"),
                    mock.call(["java", "-XshowSettings:properties", "-version"], "Java runtime"),
                ])

    def test_rejects_wrong_compiler_version_build_vendor_and_malformed_output(self):
        outputs = (
            self.output(runtime="21.0.11+10-LTS", compiler="21.0.11"),
            self.output(runtime="25.0.4.2+1-LTS", compiler="25.0.4.2"),
            self.output(runtime="25.0.4.1+2-LTS"),
            self.output(vendor="Oracle Corporation"),
            self.output(runtime="25.0.4.1+1-LTS-extra"),
            self.output().replace("java.runtime.version", "unknown.property"),
            self.output().replace("javac 25.0.4.1", "unknown compiler"),
        )
        for output in outputs:
            with self.subTest(output=output), mock.patch.object(versions, "run", return_value=output):
                with self.assertRaises(versions.VersionError):
                    versions.validate_java(self.expected)

    def test_rejects_mismatched_java_even_when_compiler_is_exact(self):
        for output in (
            self.output(runtime="21.0.11+10-LTS"),
            self.output(runtime="25.0.4.1+2-LTS"),
            self.output(vendor="Debian"),
        ):
            with self.subTest(output=output), mock.patch.object(
                versions, "run", side_effect=[self.output(), output]
            ):
                with self.assertRaises(versions.VersionError):
                    versions.validate_java(self.expected)

    def test_explicit_home_is_used_for_both_tools(self):
        home = Path("selected-temurin")
        with mock.patch.object(versions, "run", return_value=self.output()) as run:
            versions.validate_java(self.expected, home)
        suffix = ".exe" if versions.sys.platform == "win32" else ""
        self.assertEqual(run.call_args_list[0].args[0][0], str(home / "bin" / ("javac" + suffix)))
        self.assertEqual(run.call_args_list[1].args[0][0], str(home / "bin" / ("java" + suffix)))

    def test_default_validation_keeps_all_sdk_checks(self):
        baseline = versions.tomllib.loads(versions.BASELINE.read_text())
        sdk = baseline["sdk"]
        outputs = [f"go version go{sdk['go']} linux/amd64", f"v{sdk['node']}",
                   f"Version {sdk['typescript']}", sdk["dotnet"], sdk["zig"],
                   f"clang version {sdk['zig_clang']}"]
        with mock.patch.object(versions.platform, "python_version", return_value=baseline["contracts"]["python"]), \
                mock.patch.object(versions, "validate_java") as java, \
                mock.patch.object(versions, "run", side_effect=outputs) as run:
            versions.validate()
        java.assert_called_once_with(sdk["java"])
        self.assertEqual([call.args[1] for call in run.call_args_list],
                         ["Go", "Node", "TypeScript", ".NET", "Zig", "Zig C frontend"])


class VersionProbeTests(unittest.TestCase):
    def test_run_passes_finite_timeout(self) -> None:
        completed = subprocess.CompletedProcess(
            ["go", "version"],
            0,
            stdout="go version go1.27.1 linux/amd64\n",
        )
        with mock.patch.object(versions.subprocess, "run", return_value=completed) as run:
            self.assertEqual(
                versions.run(["go", "version"], "Go"),
                "go version go1.27.1 linux/amd64",
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

    def test_java_probe_keeps_finite_timeout(self):
        expired = subprocess.TimeoutExpired(cmd=["javac"], timeout=30)
        with mock.patch.object(versions.subprocess, "run", side_effect=expired):
            with self.assertRaisesRegex(versions.VersionError, "javac version probe timed out after 30 seconds"):
                versions.validate_java("25.0.4.1+1")

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
