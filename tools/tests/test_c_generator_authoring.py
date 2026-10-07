import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import c_generator_authoring as generators
from tools import c_dependency_authoring as authoring
from tools.application_dependency_store import DependencyError
from tools.c_capsule_project import create, validate
from tools.rust_capsule_project import snapshot
from tools.build_snapshot import digest


class CGeneratorFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = create(self.root / "app", "greeting")
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        (self.inputs / "value.txt").write_bytes(b"17")
        self.tool = self.root / "generator"
        self.tool.write_bytes(b'#!/bin/sh\nprintf "#define GENERATED_VALUE 17\\n" > /outputs/value.h\n')
        self.tool.chmod(0o700)
        self.candidate = self.project / "target/request.json"
        self.candidate.parent.mkdir()

    def plan(self, **options):
        return generators.request(self.project, self.candidate, tool=self.tool, arguments=[],
            inputs=self.inputs, destination="src/generated", tool_version="fixture-header-v1", **options)


class CGeneratorApproval(CGeneratorFixture):
    def test_cli_request_and_wrong_approval_preserve_the_source(self):
        from contextlib import redirect_stdout, redirect_stderr
        import io
        from tools import c_capsule
        before = snapshot(self.project)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = c_capsule.main(["generator-request", str(self.project), "--candidate", str(self.candidate),
                "--tool", str(self.tool), "--tool-version", "fixture-header-v1", "--inputs", str(self.inputs)])
        self.assertEqual((code, stderr.getvalue()), (0, ""))
        self.assertFalse(json.loads(stdout.getvalue())["generatorExecution"])
        with patch.object(generators.generators, "execute", side_effect=AssertionError("unapproved execution")), redirect_stderr(io.StringIO()):
            self.assertEqual(c_capsule.main(["generate", str(self.project), "--candidate", str(self.candidate),
                "--expect", "sha256:" + "0" * 64]), 1)
        self.assertEqual(snapshot(self.project), before)

    def test_request_binds_source_sdk_tool_arguments_inputs_and_finite_limits_without_execution(self):
        with patch("subprocess.Popen", side_effect=AssertionError("request executed")):
            result = self.plan()
        plan = json.loads(self.candidate.read_bytes())
        self.assertEqual(result["requestDigest"], digest(self.candidate.read_bytes()))
        self.assertEqual(plan["language"], "c")
        self.assertEqual(plan["specification"]["executableDigest"], digest(self.tool.read_bytes()))
        self.assertEqual(plan["limits"], {"timeoutSeconds": 60, "maximumOutputBytes": 1048576})
        self.assertFalse(result["generatorExecution"])
        self.assertFalse((self.project / "src/generated").exists())

    def test_wrong_or_modified_approval_never_dispatches(self):
        planned = self.plan()
        before = snapshot(self.project)
        with patch.object(generators.generators, "execute", side_effect=AssertionError("unapproved execution")):
            for value in ("", "sha256:" + "0" * 64):
                with self.assertRaisesRegex(DependencyError, "approval-mismatch"):
                    generators.run(self.project, self.candidate, value)
            self.candidate.write_bytes(self.candidate.read_bytes() + b" ")
            with self.assertRaisesRegex(DependencyError, "approval-mismatch"):
                generators.run(self.project, self.candidate, planned["requestDigest"])
        self.assertEqual(snapshot(self.project), before)

    def test_source_tool_and_input_drift_reject_before_execution(self):
        planned = self.plan()
        for path, reason in ((self.project / "src/main.c", "source-or-sdk-drift"),
                             (self.tool, "tool-or-input-drift"), (self.inputs / "value.txt", "tool-or-input-drift")):
            raw = path.read_bytes()
            path.write_bytes(raw + b"\n")
            try:
                with patch.object(generators.generators, "execute") as execute:
                    with self.assertRaisesRegex(DependencyError, reason):
                        generators.run(self.project, self.candidate, planned["requestDigest"])
                    execute.assert_not_called()
            finally:
                path.write_bytes(raw)

    def test_destination_collisions_and_nonfinite_limits_reject_without_adoption(self):
        (self.project / "src/generated").mkdir()
        with self.assertRaisesRegex(DependencyError, "destination-already-exists"):
            self.plan()
        for timeout in (0, 61, float("nan"), float("inf")):
            with self.assertRaisesRegex(DependencyError, "finite-limits"):
                generators.limits(timeout, 1048576)
        for maximum in (0, 1048577, True):
            with self.assertRaisesRegex(DependencyError, "finite-limits"):
                generators.limits(60, maximum)


class CGeneratorNative(CGeneratorFixture):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "linux" or not shutil.which("bwrap"):
            if os.environ.get("LSF_REQUIRE_COMPILER_ISOLATION") == "1":
                raise RuntimeError("required C generator containment host missing")
            raise unittest.SkipTest("C source generator execution requires Linux Bubblewrap")

    def test_real_header_generation_keeps_sdk_and_reuses_offline_without_original_tool(self):
        original = snapshot(self.project)
        planned = self.plan()
        result = generators.run(self.project, self.candidate, planned["requestDigest"])
        self.assertEqual((result["status"], result["cleanup"]), ("succeeded", "reaped"))
        self.assertEqual((self.project / "src/generated/value.h").read_bytes(), b"#define GENERATED_VALUE 17\n")
        for name, data in original.items():
            self.assertEqual(snapshot(self.project)[name], data)
        self.tool.unlink()
        (self.inputs / "value.txt").unlink()
        with patch("subprocess.Popen", side_effect=AssertionError("offline validation executed")):
            validate(snapshot(self.project))
            authoring.status(self.project)

    def test_generated_header_drift_is_rejected_by_normal_project_and_dependency_validation(self):
        planned = self.plan()
        generators.run(self.project, self.candidate, planned["requestDigest"])
        (self.project / "src/generated/value.h").write_bytes(b"#define GENERATED_VALUE 18\n")
        with self.assertRaisesRegex(DependencyError, "generated-inputs-drift"):
            validate(snapshot(self.project))
        with self.assertRaisesRegex(DependencyError, "generated-inputs-drift"):
            authoring.status(self.project)

    def test_failed_manifest_adoption_rolls_back_only_the_fresh_subtree(self):
        planned = self.plan()
        before = snapshot(self.project)
        original = os.replace
        def failed_manifest(source, target):
            if Path(target) == self.project / generators.MANIFEST:
                raise OSError("fixture manifest replacement failed")
            return original(source, target)
        with patch.object(generators.os, "replace", side_effect=failed_manifest):
            with self.assertRaisesRegex(OSError, "manifest replacement failed"):
                generators.run(self.project, self.candidate, planned["requestDigest"])
        self.assertEqual(snapshot(self.project), before)
        self.assertFalse((self.project / "src/generated").exists())

    def test_binary_outputs_and_failed_tools_never_adopt_generated_inputs(self):
        for script in (b"#!/bin/sh\nprintf binary > /outputs/library.a\n", b"#!/bin/sh\nexit 7\n"):
            self.tool.write_bytes(script)
            if self.candidate.exists():
                self.candidate.unlink()
            planned = self.plan()
            with self.assertRaises(DependencyError):
                generators.run(self.project, self.candidate, planned["requestDigest"])
            self.assertFalse((self.project / "src/generated").exists())
            self.assertFalse((self.project / generators.MANIFEST).exists())
