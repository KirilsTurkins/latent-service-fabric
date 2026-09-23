"""Harness tests only: no test here establishes Java guest conformance."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("java_capsule_probe", Path(__file__).with_name("probe.py"))
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

CONFIG = {"sdk": {"java": "25.0.4.1+1", "gradle": "9.1.0", "zig": "0.16.0"},
          "rust": {"dependencies": {"wit-bindgen": "0.62.0", "wasmtime": "47.0.4"}},
          "contracts": {"wasm-tools": "1.254.0"}}


class Runner:
    def __init__(self, code=0, stdout=b"", stderr=b"", error=None):
        self.code, self.stdout, self.stderr, self.error = code, stdout, stderr, error
        self.commands = []

    def __call__(self, command, cwd, env, timeout, maximum):
        self.commands.append(command)
        if self.error:
            raise self.error
        Path(command[3]).write_text(json.dumps({"exitCode": self.code}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, self.stdout, self.stderr)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "target/attempt"

    def make_probe(self, runner=None):
        return probe.Probe(self.root, self.output, runner or Runner())

    def test_output_must_be_below_target(self):
        with self.assertRaises(ValueError):
            probe.Probe(self.root, self.root / "research/new", Runner())

    def test_output_cannot_be_target_itself(self):
        with self.assertRaises(ValueError):
            probe.Probe(self.root, self.root / "target", Runner())

    def test_existing_attempt_is_preserved(self):
        self.output.mkdir(parents=True)
        receipt = self.output / "report.json"
        receipt.write_text("previous attempt")
        with self.assertRaises(FileExistsError):
            self.make_probe()
        self.assertEqual(receipt.read_text(), "previous attempt")

    def test_symlink_output_cannot_escape_target(self):
        (self.root / "target").mkdir()
        (self.root / "outside").mkdir()
        (self.root / "target/alias").symlink_to(self.root / "outside", target_is_directory=True)
        with self.assertRaises(ValueError):
            probe.Probe(self.root, self.root / "target/alias/new", Runner())

    def test_nonzero_compiler_exit_retains_both_streams(self):
        subject = self.make_probe(Runner(2, b"attempted\n", b"unsupported feature\n"))
        result = subject.step("compiler", ["compiler", "input.java"])
        self.assertEqual((result["status"], result["exitCode"]), ("failed", 2))
        self.assertIn("unsupported feature", subject.text(result))
        self.assertIn("attempted", subject.text(result))
        self.assertEqual(result["stderr"]["size"], len(b"unsupported feature\n"))

    def test_signal_exit_is_not_success(self):
        subject = self.make_probe(Runner(-9))
        self.assertEqual(subject.step("compiler", ["compiler"])["status"], "failed")

    def test_bounded_runner_error_is_infrastructure_failure(self):
        subject = self.make_probe(Runner(error=RuntimeError("capture limit")))
        result = subject.step("compiler", ["compiler"])
        self.assertEqual(result["status"], "infrastructure-error")
        self.assertTrue(result["captureDiscarded"])
        self.assertNotIn("stdout", result)

    def test_launch_error_cannot_be_mistaken_for_feature_failure(self):
        def launch_error(command, *args):
            Path(command[3]).write_text('{"launchError": true}')
            return subprocess.CompletedProcess(command, 0, b"", b"")
        result = self.make_probe(launch_error).step("compiler", ["compiler"])
        self.assertEqual(result["status"], "infrastructure-error")

    def test_boolean_status_is_rejected(self):
        result = self.make_probe(Runner(False)).step("compiler", ["compiler"])
        self.assertEqual(result["status"], "infrastructure-error")

    def test_missing_status_is_rejected(self):
        runner = lambda command, *args: subprocess.CompletedProcess(command, 0, b"", b"")
        self.assertEqual(self.make_probe(runner).step("compiler", ["compiler"])["status"], "infrastructure-error")

    def test_expired_probe_does_not_launch(self):
        runner = Runner()
        subject = self.make_probe(runner)
        subject.deadline = 0
        self.assertEqual(subject.step("compiler", ["compiler"])["status"], "infrastructure-error")
        self.assertFalse(runner.commands)

    def test_invalid_deadline_does_not_create_directory(self):
        with self.assertRaises(ValueError):
            probe.Probe(self.root, self.output, Runner(), timeout=0)
        self.assertFalse(self.output.exists())

    def test_environment_does_not_inherit_tokens_or_java_options(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "private-test-value", "JAVA_TOOL_OPTIONS": "-javaagent:bad.jar"}):
            subject = self.make_probe()
        self.assertNotIn("GITHUB_TOKEN", subject.env)
        self.assertNotIn("JAVA_TOOL_OPTIONS", subject.env)
        self.assertTrue(Path(subject.env["HOME"]).is_relative_to(self.output))

    def test_write_json_refuses_overwrite(self):
        path = self.root / "receipt.json"
        probe.write_json(path, {"first": True})
        with self.assertRaises(FileExistsError):
            probe.write_json(path, {"first": False})
        self.assertTrue(json.loads(path.read_text())["first"])

    def test_content_identity_changes_when_source_changes(self):
        path = self.root / "source.java"
        path.write_text("first")
        before = probe.identity(path)
        path.write_text("second")
        self.assertNotEqual(probe.identity(path), before)

    def test_source_snapshot_reports_missing_authoritative_inputs(self):
        records, missing = probe.source_snapshot(self.root)
        self.assertEqual(records, {})
        self.assertIn("wit/platform", missing)
        self.assertIn("Cargo.lock", missing)

    def test_source_snapshot_rejects_symlink_sources(self):
        project = self.root / probe.PROJECT
        project.mkdir(parents=True)
        source = self.root / "actual.java"
        source.write_text("class Actual {}")
        (project / "Alias.java").symlink_to(source)
        records, missing = probe.source_snapshot(self.root)
        self.assertIn("research/java-capsules/Alias.java", missing)
        self.assertNotIn("research/java-capsules/Alias.java", records)

    def test_source_snapshot_does_not_capture_generated_target_files(self):
        self.output.mkdir(parents=True)
        (self.output / "generated.java").write_text("not an input")
        records, _ = probe.source_snapshot(self.root)
        self.assertNotIn("target/attempt/generated.java", records)

    def test_missing_tool_is_not_compiler_feasibility_failure(self):
        subject = self.make_probe()
        with patch.object(probe.shutil, "which", return_value=None):
            subject.check_tools(CONFIG)
        self.assertEqual(len(subject.report["steps"]), 6)
        self.assertTrue(all(step["status"] == "infrastructure-error" for step in subject.report["steps"]))

    def test_exact_pins_are_accepted(self):
        subject = self.make_probe()
        binary = self.root / "executable"
        binary.write_text("test executable identity")
        outputs = [b"openjdk 25.0.4.1\nOpenJDK Runtime Environment Temurin-25.0.4.1+1 (build 25.0.4.1+1-LTS)\n",
                   b"javac 25.0.4.1\n", b"Gradle 9.1.0\n", b"wasm-tools 1.254.0\n", b"wit-bindgen 0.62.0\n", b"0.16.0\n"]
        def runner(command, *args):
            Path(command[3]).write_text('{"exitCode":0}')
            return subprocess.CompletedProcess(command, 0, outputs.pop(0), b"")
        subject.runner = runner
        with patch.object(probe.shutil, "which", return_value=str(binary)):
            subject.check_tools(CONFIG)
        self.assertEqual(len(subject.tools), 6)

    def test_approximate_or_substring_versions_are_rejected(self):
        subject = self.make_probe(Runner(stdout=b"Gradle 9.1.01\njava 25\njavac 25\nwasm-tools 1.254.01\nwit-bindgen 0.62.01\n0.16.01\n"))
        binary = self.root / "executable"
        binary.write_text("test")
        with patch.object(probe.shutil, "which", return_value=str(binary)):
            subject.check_tools(CONFIG)
        self.assertFalse(subject.tools)

    def test_absent_core_artifact_is_not_componentized(self):
        subject = self.make_probe()
        subject.tools["wasm-tools"] = "wasm-tools"
        subject.componentize("candidate", self.output / "missing.wasm")
        self.assertEqual(subject.report["steps"][0]["reason"], "compiler-output-missing")

    def test_report_survives_missing_configuration(self):
        subject = self.make_probe()
        self.assertEqual(subject.run(), 3)
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["probeStatus"], "infrastructure-error")
        self.assertFalse(report["canCloseIssue"])
        self.assertFalse(report["nodeInvoked"])
        self.assertIsNone(report["runtimeMeasurements"])

    def test_all_passing_subcommands_still_cannot_qualify_an_sdk(self):
        subject = self.make_probe()
        (self.root / "tools").mkdir()
        (self.root / "tools/toolchain.toml").write_text("")
        with patch.object(subject, "check_tools"), patch.object(subject, "compile_candidates"), \
                patch.object(probe, "source_snapshot", return_value=({}, [])):
            self.assertEqual(subject.run(), 2)
        self.assertEqual(subject.report["qualification"], "not-qualified")
        self.assertEqual(subject.report["probeStatus"], "incomplete")
        self.assertGreater(len(subject.report["remaining"]), 0)

    def test_source_mutation_marks_attempt_infrastructure_error(self):
        subject = self.make_probe()
        (self.root / "tools").mkdir()
        (self.root / "tools/toolchain.toml").write_text("")
        with patch.object(subject, "check_tools"), patch.object(subject, "compile_candidates"), \
                patch.object(probe, "source_snapshot", side_effect=[({}, []), ({"changed": {}}, [])]):
            self.assertEqual(subject.run(), 3)
        self.assertEqual(subject.report["steps"][-1]["reason"], "source-inputs-changed")

    def test_cancellation_is_recorded_and_propagated(self):
        subject = self.make_probe()
        (self.root / "tools").mkdir()
        (self.root / "tools/toolchain.toml").write_text("")
        with patch.object(subject, "check_tools", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                subject.run()
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["probeStatus"], "cancelled")
        self.assertFalse(report["canCloseIssue"])

    def test_compiler_pin_drift_is_rejected_before_gradle(self):
        subject = self.make_probe()
        project = self.root / probe.PROJECT
        project.mkdir(parents=True)
        (project / "build.gradle.kts").write_text('val teavmVersion = "unreviewed"')
        with self.assertRaisesRegex(ValueError, "compiler-pin-drift"):
            subject.compile_candidates()
        self.assertFalse(subject.runner.commands)

    def test_java_home_tracks_verified_executable(self):
        subject = self.make_probe(Runner(stdout=b"OpenJDK Runtime Environment (build 25.0.4.1+1-LTS)\n"))
        binary = self.root / "jdk/bin/java"
        binary.parent.mkdir(parents=True)
        binary.write_text("test executable identity")
        subject.env["JAVA_HOME"] = "/wrong/jdk"
        with patch.object(probe.shutil, "which", side_effect=lambda name, **_: str(binary) if name == "java" else None):
            subject.check_tools(CONFIG)
        self.assertEqual(subject.env["JAVA_HOME"], str(self.root / "jdk"))

    def test_direct_compiler_pin_matches_probe_metadata(self):
        build = Path(__file__).with_name("build.gradle.kts").read_text()
        self.assertIn(f'val teavmVersion = "{probe.TEAVM_VERSION}"', build)

    def test_capture_shim_preserves_nonzero_exit_and_diagnostics(self):
        status = self.root / "exit.json"
        result = subprocess.run([probe.sys.executable, str(Path(probe.__file__)), "_capture", str(status),
                                 probe.sys.executable, "-c", "import sys; print('failure-evidence', file=sys.stderr); sys.exit(7)"],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"failure-evidence", result.stderr)
        self.assertEqual(json.loads(status.read_text()), {"exitCode": 7})

    def test_capture_shim_records_launch_failure_separately(self):
        status = self.root / "exit.json"
        self.assertEqual(probe.capture_status([str(status), str(self.root / "nonexistent")]), 0)
        self.assertEqual(json.loads(status.read_text()), {"launchError": True})


if __name__ == "__main__":
    unittest.main()
