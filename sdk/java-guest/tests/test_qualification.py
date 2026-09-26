"""Binary-identity guard tests; mocked builds are not execution evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import build_java_guest_capsules as sdk
from tools import qualify_java_capsules as qualification


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
