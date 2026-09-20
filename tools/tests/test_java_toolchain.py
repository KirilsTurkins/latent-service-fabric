"""Small compiler-free regressions; header fixtures are not real-node evidence."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
JAVA_TOOLS = ROOT / "sdk/java-client/tools"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


toolchain = load("java_toolchain", JAVA_TOOLS / "java_toolchain.py")
with mock.patch.dict(sys.modules, java_toolchain=toolchain):
    build = load("java_build", JAVA_TOOLS / "build.py")


class BytecodeTests(unittest.TestCase):
    @staticmethod
    def header(major=69, minor=0, magic=0xCAFEBABE):
        return struct.pack(">IHH", magic, minor, major)

    def test_accepts_java25_and_rejects_old_new_preview_truncated_and_bad_magic(self):
        toolchain.check_header(self.header(), "valid", 25)
        for header in (self.header(65), self.header(70), self.header(minor=65535),
                       self.header(magic=0), self.header()[:7]):
            with self.subTest(header=header), self.assertRaises(ValueError):
                toolchain.check_header(header, "fixture", 25)

    def test_directory_requires_classes_and_checks_every_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaisesRegex(ValueError, "no Java classes"):
                toolchain.verify_classes(directory)
            (directory / "A.class").write_bytes(self.header())
            self.assertEqual(toolchain.verify_classes(directory), 1)
            (directory / "nested").mkdir()
            (directory / "nested/B.class").write_bytes(self.header(65))
            with self.assertRaisesRegex(ValueError, "B.class"):
                toolchain.verify_classes(directory)

    def test_jar_requires_classes_and_rejects_mixed_target_or_preview(self):
        with tempfile.TemporaryDirectory() as temporary:
            jar = Path(temporary) / "sdk.jar"
            for headers in ([], [self.header()], [self.header(), self.header(65)],
                            [self.header(minor=65535)]):
                with zipfile.ZipFile(jar, "w") as archive:
                    archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
                    for index, header in enumerate(headers):
                        archive.writestr(f"sdk/Class{index}.class", header)
                with self.subTest(headers=headers):
                    if headers == [self.header()]:
                        self.assertEqual(toolchain.verify_jar(jar), 1)
                    else:
                        with self.assertRaises(ValueError):
                            toolchain.verify_jar(jar)


class BuildWiringTests(unittest.TestCase):
    def test_selected_java_home_never_falls_back_to_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = str(Path(temporary) / "missing")
            with mock.patch.dict(os.environ, JAVA_HOME=missing), mock.patch.object(toolchain.shutil, "which") as which:
                with self.assertRaises(OSError):
                    toolchain.check_jdk()
            which.assert_not_called()

    def test_wrong_jdk_fails_before_dependency_download_or_generation(self):
        with mock.patch.object(sys, "argv", ["build.py", "build"]), \
                mock.patch.object(build, "check_jdk", side_effect=ValueError("wrong JDK")), \
                mock.patch.object(build, "prepare") as prepare:
            with self.assertRaisesRegex(ValueError, "wrong JDK"):
                build.main()
        prepare.assert_not_called()

    def test_compiler_receives_release25_and_result_is_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "build"
            output.mkdir()
            (output / "generated-sources.json").write_text("[]")
            with mock.patch.object(build, "SDK", root), mock.patch.object(build, "BUILD", output), \
                    mock.patch.object(build, "jars", return_value=[]), \
                    mock.patch.object(build, "run") as run, \
                    mock.patch.object(build, "verify_classes", return_value=1) as verify:
                for tests, name in ((False, "classes"), (True, "test-classes")):
                    build.compile_java(tests, Path("pinned-jdk"))
                    args = [json.loads(line) for line in (output / "javac.args").read_text().splitlines()]
                    self.assertEqual(args[:2], ["--release", "25"])
                    self.assertEqual(run.call_args.args[0][0], toolchain.executable(Path("pinned-jdk"), "javac"))
                    verify.assert_called_with(output / name)

    def test_baseline_is_exact_and_ci_selectors_match_the_release(self):
        sdk = toolchain.baseline()
        match = re.fullmatch(r"(25)\.(\d+)\.(\d+)\.(\d+)\+(\d+)", sdk["java"])
        self.assertIsNotNone(match)
        major, minor, security, patch, build_number = map(int, match.groups())
        expected = f"{major}.{minor}.{security}+{100 * patch + build_number}.0.LTS"
        self.assertEqual(sdk["java_setup"], expected)
        java_workflows = []
        for path in sorted((ROOT / ".github/workflows").glob("*.y*ml")):
            selectors = re.findall(r"java-version:\s*[\"']([^\"']+)[\"']", path.read_text())
            if selectors:
                java_workflows.append(path.name)
                self.assertEqual(set(selectors), {expected}, str(path))
        self.assertIn("ci.yml", java_workflows)
        self.assertIn("phase0-full-validation.yml", java_workflows)
        self.assertIn(sdk["java"], (ROOT / ".github/workflows/ci.yml").read_text())

    def test_gradle_test_requires_both_main_suites_without_ignoring_failures(self):
        gradle = (ROOT / "sdk/java-client/build.gradle.kts").read_text()
        task = re.search(r"tasks\.test\s*\{([^}]+)\}", gradle).group(1)
        self.assertIn("dependsOn(semanticTest, transportTest)", task)
        self.assertIn("failOnNoDiscoveredTests.set(false)", task)
        self.assertNotIn("ignoreFailures", gradle)
        self.assertNotIn("isIgnoreExitValue", gradle)
        self.assertIn("tasks.check { dependsOn(semanticTest, transportTest, verifyJavaBytecode) }", gradle)

    def test_gradle_and_shell_targets_cannot_drift_to_java21(self):
        gradle = (ROOT / "sdk/java-client/build.gradle.kts").read_text()
        self.assertEqual(set(re.findall(r"JavaLanguageVersion.of\((\d+)\)", gradle)), {"25"})
        self.assertEqual(re.findall(r"options.release.set\((\d+)\)", gradle), ["25", "25"])
        self.assertIn("javaLauncher.set(sdkLauncher)", gradle)
        self.assertIn("verifyJavaBytecode", gradle)
        self.assertIn("verifyJavaToolchain", gradle)
        shell = (ROOT / "tools/validate_sdks.sh").read_text()
        self.assertEqual(re.findall(r"javac --release (\d+)", shell), ["25"])
        self.assertIn("java_toolchain.py classes", shell)


if __name__ == "__main__":
    unittest.main()
