"""Retained command receipts are diagnostics, never successful build claims."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

from tools.build_process import BuildProcessError
from tools.java_capsule_build import retain_logs
from tools.java_guest.compiler import Compiler, stage_sdk_service, read_only_dependency_cache, tool_inventory
from tools.java_guest.class_origin import checkpoint_index, source_file


class Diagnostics(unittest.TestCase):
    def test_dependency_cache_choices_fail_before_output_or_tool_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for read_only, offline in ((root / "modules-2", root / "offline"), (root / "wrong-name", None)):
                output = root / "compiler"
                with patch("tools.java_guest.compiler.run_bounded_result") as run, self.assertRaises(ValueError):
                    Compiler(output, root, offline_cache=offline, read_only_cache=read_only)
                run.assert_not_called()
                self.assertFalse(output.exists())

    def test_read_only_cache_requires_pinned_metadata_and_a_bound_regular_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "modules-2"
            (root / "files-2.1").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "incomplete pinned"):
                read_only_dependency_cache(root)
            (root / "metadata-2.107").mkdir()
            jar = root / "files-2.1/artifact.jar"
            jar.write_bytes(b"captured artifact")
            self.assertEqual(read_only_dependency_cache(root), root.resolve())
            before = tool_inventory({"gradle-cache": root})
            jar.write_bytes(b"changed artifact")
            self.assertNotEqual(before, tool_inventory({"gradle-cache": root}))

    def test_changed_read_only_cache_invalidates_the_final_compiler_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "modules-2"
            root.mkdir()
            jar = root / "artifact.jar"
            jar.write_bytes(b"captured artifact")
            compiler = Compiler.__new__(Compiler)
            compiler.sdk = root
            compiler.original_sdk = {}
            compiler.tool_roots = {"gradle-cache": root}
            compiler.compiler_inputs = tool_inventory(compiler.tool_roots)
            compiler.materials = []
            jar.write_bytes(b"changed artifact")
            with patch("tools.java_guest.compiler.sdk_snapshot", return_value={}), \
                    self.assertRaisesRegex(ValueError, "distribution changed"):
                compiler.check_unchanged()

    def test_activation_profile_selection_is_explicit_before_output_or_compilation(self):
        compiler = Compiler.__new__(Compiler)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            for selection in (1, "true", None):
                with self.subTest(selection=selection), self.assertRaisesRegex(ValueError, "explicit boolean"):
                    compiler.compile(Path(temporary), Path(temporary), "tests:app/service", output, activation_profile=selection)
                self.assertFalse(output.exists())

    def test_failed_initialization_commands_keep_exit_and_cleanup_receipts(self):
        for outcome in (subprocess.CompletedProcess(["java"], 7, b"", b"compiler failure"),
                        BuildProcessError("command-deadline")):
            with self.subTest(outcome=type(outcome).__name__), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                compiler = Compiler.__new__(Compiler)
                compiler.directory = root / "compiler"
                compiler.directory.mkdir()
                compiler.deadline = time.monotonic() + 30
                compiler.paths, compiler.environment = {}, {}
                compiler.records, compiler.retained_bytes = [], 0
                mocked = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with patch("tools.java_guest.compiler.run_bounded_result", **mocked):
                    with self.assertRaises((ValueError, BuildProcessError)):
                        compiler.run("java-version", "java", "-version")
                output = root / "output"
                output.mkdir()
                retain_logs(compiler.directory, output)
                record = json.loads((output / "compiler-logs/0-java-version.command.json").read_bytes())
                self.assertEqual(record["command"], ["java", "-version"])
                self.assertEqual(record["exitCode"], None if isinstance(outcome, Exception) else 7)
                if isinstance(outcome, Exception):
                    self.assertEqual(record["processFailure"], "command-deadline")
                else:
                    self.assertIn(b"compiler failure", (output / "compiler-logs/0-java-version.log").read_bytes())

    def test_trusted_compiler_services_merge_without_replacing_existing_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            name = "META-INF/services/org.teavm.extension.spi.substitution.SubstitutionPolicy"
            target = Path(temporary) / name
            stage_sdk_service(target, name, b"dev.latent.guest.server.compiler.ServerSubstitution\n")
            stage_sdk_service(target, name, b"dev.latent.guest.runtime.compiler.RuntimeSubstitution\n")
            expected = (b"dev.latent.guest.server.compiler.ServerSubstitution\n"
                        b"dev.latent.guest.runtime.compiler.RuntimeSubstitution\n")
            self.assertEqual(target.read_bytes(), expected)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                stage_sdk_service(target, name, b"dev.latent.guest.runtime.compiler.RuntimeSubstitution\n")
            self.assertEqual(target.read_bytes(), expected)
            with self.assertRaisesRegex(ValueError, "invalid"):
                stage_sdk_service(target, "ordinary-resource.txt", b"app.CompilerExtension\n")
            self.assertEqual(target.read_bytes(), expected)


class ClassOrigin(unittest.TestCase):
    @staticmethod
    def class_bytes(source=b"App.java", unrelated=b"\xc0\x80", duplicate=False):
        def utf8(value): return b"\x01" + len(value).to_bytes(2, "big") + value
        constant_pool = utf8(b"SourceFile") + utf8(source) + utf8(unrelated)
        attribute = b"\x00\x01\x00\x00\x00\x02\x00\x02"
        return (b"\xca\xfe\xba\xbe\x00\x00\x00\x34\x00\x04" + constant_pool
                + b"\x00" * 12 + (2 if duplicate else 1).to_bytes(2, "big")
                + attribute * (2 if duplicate else 1))

    def test_modified_utf8_literals_are_not_decoded_as_file_names(self):
        self.assertEqual(source_file(self.class_bytes()), "App.java")
        # A supplementary character is encoded as two modified UTF-8 surrogate
        # sequences by javac; arbitrary String constants remain uninterpreted.
        self.assertEqual(source_file(self.class_bytes(b"App\xed\xa0\xbd\xed\xb8\x80.java")), "App\U0001f600.java")

    def test_truncation_duplicate_source_and_untrusted_tail_fail(self):
        original = self.class_bytes()
        for data in (original[:-1], original + b"x", self.class_bytes(duplicate=True),
                     self.class_bytes(b"../App.java"), b"\xca\xfe\xba\xbe\0\0\0\x34\0\x02\xff"):
            with self.subTest(data=data), self.assertRaises(ValueError): source_file(data)

    def test_origin_selects_original_inner_classes_and_captured_jars(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            classes = root / "classes"
            for logical, source in (("dev/app/App.class", b"App.java"),
                                    ("dev/app/App$Worker.class", b"App.java"),
                                    ("dev/latent/generated/Bindings.class", b"Bindings.java")):
                path = classes / logical
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self.class_bytes(source))
            jar = root / "dependency.jar"
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr("other/library/Worker.class", self.class_bytes())
                archive.writestr("META-INF/versions/25/other/library/Worker.class", self.class_bytes())
                archive.writestr("ordinary-resource.txt", b"preserved resource")
            expected = [b"dev.app.App", b"dev.app.App$Worker", b"other.library.Worker"]
            for source in ("dev/app/App.java", "App.java", "unrelated/tree/App.java"):
                self.assertEqual(checkpoint_index(classes, {source: "dev.app"}, (jar,)).splitlines(), expected)
            with self.assertRaisesRegex(ValueError, "unresolved-java-class-origin"):
                checkpoint_index(classes, {"App.java": "unknown"}, ())
            with self.assertRaisesRegex(ValueError, "ambiguous-java-class-origin"):
                checkpoint_index(classes, {"one/App.java": "dev.app", "two/App.java": "dev.app"}, ())

    def test_captured_jar_class_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jar = root / "dependency.jar"
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr("../Worker.class", b"opaque captured bytes")
            with self.assertRaisesRegex(ValueError, "invalid-java-class-origin-path"):
                checkpoint_index(root / "classes", {}, (jar,))


if __name__ == "__main__": unittest.main()
