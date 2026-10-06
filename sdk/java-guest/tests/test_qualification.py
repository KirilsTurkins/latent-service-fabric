"""Binary-identity guard tests; mocked builds are not execution evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import build_java_guest_capsules as sdk
from tools import qualify_java_capsules as qualification
from tools import qualify_java_fibers as fibers


class ThrowableModelIntegrity(unittest.TestCase):
    @staticmethod
    def fixture(root):
        compiler = SimpleNamespace(sdk=root / "sdk", directory=root / "compiler", run=Mock())
        names = ("teavm-classlib", "teavm-core", "teavm-extension-spi", "teavm-interop",
                 "teavm-relocated-libs-asm", "teavm-relocated-libs-asm-analysis",
                 "teavm-relocated-libs-asm-commons", "teavm-relocated-libs-asm-tree", "teavm-relocated-libs-hppc")
        artifacts, jars = [], []
        for name in names:
            raw = name.encode()
            jar = compiler.directory / "gradle-home/caches/modules-2/files-2.1/org.teavm" / name / "0.15.0/hash" / (name + "-0.15.0.jar")
            jar.parent.mkdir(parents=True)
            jar.write_bytes(raw)
            jars.append(jar)
            artifacts.append({"path": "org/teavm/" + name + "/0.15.0/" + jar.name,
                              "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
        lock = compiler.sdk / "feasibility/dependencies.lock.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"artifacts": artifacts}))
        return compiler, jars, lock

    def test_changed_locked_jar_cannot_enter_host_model_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiler, jars, _ = self.fixture(root)
            jars[0].write_bytes(b"X" + jars[0].read_bytes()[1:])
            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                fibers.throwable_model_control(compiler, root / "model")
            compiler.run.assert_not_called()
            self.assertFalse((root / "model").exists())

    def test_capsule_digest_prefix_cannot_replace_maven_inventory_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiler, _, lock = self.fixture(root)
            document = json.loads(lock.read_bytes())
            for item in document["artifacts"]: item["sha256"] = "sha256:" + item["sha256"]
            lock.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                fibers.throwable_model_control(compiler, root / "model")
            compiler.run.assert_not_called()

    def test_missing_ambiguous_and_duplicate_tooling_fail_before_compilation(self):
        for defect in ("missing", "ambiguous", "duplicate-lock"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                compiler, jars, lock = self.fixture(root)
                if defect == "missing": jars[0].unlink()
                elif defect == "ambiguous":
                    duplicate = jars[0].parent.parent / "other-hash" / jars[0].name
                    duplicate.parent.mkdir()
                    duplicate.write_bytes(jars[0].read_bytes())
                else:
                    document = json.loads(lock.read_bytes())
                    document["artifacts"][-1] = document["artifacts"][0]
                    lock.write_text(json.dumps(document))
                with self.assertRaises(ValueError): fibers.throwable_model_control(compiler, root / "model")
                compiler.run.assert_not_called()

    def test_model_uses_only_sdk_control_and_verified_tooling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiler, jars, _ = self.fixture(root)
            compiler.run.return_value = ("THROWABLE_INITIALIZATION_CONTROL PASS constructors=5;original-negative;"
                "real-array-initializer;method-owners;layout-and-repeated-port-negatives;application-identity\n")
            report = fibers.throwable_model_control(compiler, root / "model")
            self.assertEqual(len(report["jarDigests"]), 9)
            self.assertEqual(compiler.run.call_count, 2)
            first, second = compiler.run.call_args_list
            self.assertEqual(first.args[:3], ("throwable-model-compile", "javac", "-proc:none"))
            self.assertEqual(first.args[-2:], (
                compiler.sdk / "fibers/compiler/dev/latent/guest/runtime/compiler/ThrowableInitialization.java",
                compiler.sdk / "fibers/conformance/compiler/ThrowableInitializationControl.java"))
            self.assertEqual(second.args[-1], "dev.latent.guest.runtime.compiler.ThrowableInitializationControl")


class TimeUnitModelIntegrity(unittest.TestCase):
    def test_changed_tooling_is_rejected_before_any_host_model_or_reference_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiler, jars, _ = ThrowableModelIntegrity.fixture(root)
            jars[-1].write_bytes(b"modified compiler tooling")
            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                fibers.timeunit_model_control(compiler, root / "model")
            compiler.run.assert_not_called()
            self.assertFalse((root / "model").exists())

    def test_incomplete_model_proof_cannot_proceed_to_reference_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiler, _, _ = ThrowableModelIntegrity.fixture(root)
            compiler.run.side_effect = ["", "TIMEUNIT_MODEL_CONTROL PASS bodies=0"]
            with self.assertRaisesRegex(ValueError, "TimeUnit model control did not complete"):
                fibers.timeunit_model_control(compiler, root / "model")
            self.assertEqual(compiler.run.call_count, 2)

    def test_source_control_requires_both_model_and_real_reference_conversion_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiler, _, _ = ThrowableModelIntegrity.fixture(root)
            compiler.run.side_effect = ["", ("TIMEUNIT_MODEL_CONTROL PASS missing-declarations-negative;"
                "standard-body-and-reference-closure;enum-owners-preserved;layout-negative;"
                "application-identity-preserved bodies=20"), "TIMEUNIT_NATIVE_SOURCE_CONTROL PASS checks=1661"]
            report = fibers.timeunit_model_control(compiler, root / "model")
            self.assertEqual(len(report["jarDigests"]), 9)
            self.assertEqual(report["referenceConversionChecks"], 1661)
            self.assertEqual(compiler.run.call_count, 3)
            first, model, native = compiler.run.call_args_list
            self.assertEqual(first.args[:3], ("timeunit-model-compile", "javac", "-proc:none"))
            self.assertEqual(model.args[-1], "dev.latent.guest.runtime.compiler.TimeUnitModelControl")
            self.assertEqual(native.args[-1], "TimeUnitNativeControl")


class PackagingTools(unittest.TestCase):
    def test_prebuilt_tools_are_reused_without_a_narrower_cargo_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contracts, packager = root / "contracts", root / "package"
            contracts.write_bytes(b"original contracts tool")
            packager.write_bytes(b"original packager")
            with patch.object(sdk.Commands, "run") as command, \
                    patch.object(sdk, "project", side_effect=lambda path, _name: path), \
                    patch.object(sdk, "build") as build:
                sdk.compile_all(root / "output", root / "wasi", contracts_tool=contracts, packager=packager)
            command.assert_not_called()
            self.assertEqual(build.call_count, 9)
            for call in build.call_args_list:
                self.assertEqual(call.args[2:4], (contracts.resolve(), packager.resolve()))
            report = json.loads((root / "output/SDK-BUILD.json").read_bytes())
            self.assertEqual(report["tools"], report["toolsAfter"])
            self.assertEqual(report["status"], "built-execution-required")
            self.assertFalse(report["runtimeQualified"])

    def test_prebuilt_tools_must_be_supplied_as_a_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for options in ({"contracts_tool": root / "contracts"}, {"packager": root / "package"}):
                with self.subTest(options=options), self.assertRaisesRegex(ValueError, "both packaging tools"):
                    sdk.compile_all(root / "output", root / "wasi", **options)
            self.assertFalse((root / "output").exists())

    def test_replacing_a_tool_during_the_matrix_fails_and_retains_both_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contracts, packager = root / "contracts", root / "package"
            contracts.write_bytes(b"original contracts tool")
            packager.write_bytes(b"original packager")
            def replace(*_args, **_kwargs):
                packager.write_bytes(b"replacement packager")
            with patch.object(sdk.Commands, "run"), \
                    patch.object(sdk, "project", side_effect=lambda path, _name: path), \
                    patch.object(sdk, "build", side_effect=replace), \
                    self.assertRaisesRegex(ValueError, "packaging tools changed"):
                sdk.compile_all(root / "output", root / "wasi", contracts_tool=contracts, packager=packager)
            report = json.loads((root / "output/SDK-BUILD.json").read_bytes())
            self.assertNotEqual(report["tools"]["packager"], report["toolsAfter"]["packager"])
            self.assertEqual(report["status"], "failed")


class FinalIntegrity(unittest.TestCase):
    def test_unchanged_sources_and_binary_identities_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "node"
            binary.write_bytes(b"fixed node")
            identity = {"node": qualification.file_identity(binary)}
            with patch.object(qualification, "inputs", return_value={"source": "before"}):
                qualification.verify_inputs(root, {"source": "before"}, {"node": binary}, identity)
            self.assertEqual(json.loads((root / "binaries-after.json").read_bytes()), identity)

    def test_source_and_binary_changes_fail_closed_with_distinct_retained_diagnostics(self):
        for source_change in (True, False):
            with self.subTest(source_change=source_change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                binary = root / "node"
                binary.write_bytes(b"before")
                identity = {"node": qualification.file_identity(binary)}
                if not source_change:
                    binary.write_bytes(b"after")
                after = {"source": "after" if source_change else "before"}
                expected = "source inputs changed" if source_change else "binaries changed: node"
                with patch.object(qualification, "inputs", return_value=after), \
                        self.assertRaisesRegex(ValueError, expected):
                    qualification.verify_inputs(root, {"source": "before"}, {"node": binary}, identity)
                self.assertEqual(json.loads((root / "source-inputs-after.json").read_bytes()), after)
                self.assertTrue((root / "binaries-after.json").is_file())
