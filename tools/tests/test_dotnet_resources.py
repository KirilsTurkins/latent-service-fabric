"""Captured embedding controls; actual MSBuild/NativeAOT qualification is separate."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from tools import guest_resources
from tools.dev_workflow.common import digest, encode
from tools.dotnet_guest import resources
from tools.dotnet_guest.build import build
from tools.dotnet_guest.project import create
from tools.rust_capsule_project import snapshot


def declaration(path, source="assets/data.bin"):
    return {"path": path, "source": source, "mediaType": "application/octet-stream"}


def inputs(rows, payload=b"\x00\xff\xfe\x80\n"):
    return {guest_resources.MANIFEST: encode({"schemaVersion": guest_resources.PROFILE, "resources": rows}),
            "assets/data.bin": payload, "private.txt": b"unselected confidential data"}


class DotnetResourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-dotnet-resource-control-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def project(self, name="project"):
        project = self.root / name
        project.mkdir()
        (project / "Capsule.csproj").write_bytes(b'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            b'<TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        return project

    def test_compiler_and_package_select_same_binary_bytes_and_deduplicate_payloads(self):
        files = inputs([declaration("data/first.bin"), declaration("data/second.bin")])
        project = self.project()
        embedded = resources.install(files, project)
        packaged = guest_resources.capture(files, b"component", b"source")
        self.assertEqual(embedded.observation["resources"], packaged.index["resources"])
        self.assertEqual(embedded.observation["bytes"], packaged.index["bytes"])
        self.assertEqual(list(snapshot(project / "resources").values()), [files["assets/data.bin"]])
        self.assertNotIn(files["private.txt"], embedded.objects.values())
        items = ET.fromstring(embedded.project_bytes).findall("./ItemGroup/EmbeddedResource")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].attrib["Include"], items[1].attrib["Include"])
        self.assertEqual([item.findtext("LogicalName") for item in items], ["data/first.bin", "data/second.bin"])
        embedded.check_unchanged()

    def test_logical_names_cannot_expand_msbuild_properties_items_or_xml(self):
        names = ["data/$(Injected).txt", "data/@(Injected).txt", "data/a;b.txt",
                 "data/quote'&snowman\u2603.txt", "culture/fr.txt"]
        embedded = resources.install(inputs([declaration(name) for name in names]), self.project())
        root = ET.fromstring(embedded.project_bytes)
        self.assertEqual(len(root.findall("./PropertyGroup")), 2)
        items = root.findall("./ItemGroup/EmbeddedResource")
        self.assertEqual(len(items), len(names))
        self.assertEqual({item.findtext("LogicalName") for item in items}, {
            "data/%24%28Injected%29.txt", "data/%40%28Injected%29.txt", "data/a%3Bb.txt",
            "data/quote%27&snowman\u2603.txt", "culture/fr.txt"})
        self.assertTrue(all(item.findtext("WithCulture") == "false" for item in items))
        self.assertEqual(root.findtext("./PropertyGroup/EnableDefaultEmbeddedResourceItems"), "false")
        self.assertTrue(all(item.attrib["Include"].startswith("resources/") for item in items))

    def test_captured_transitive_owner_is_required_and_is_preserved(self):
        payload = b"transitive owned bytes"
        owner = "nuget:private:2.0"
        files = {"dependencies/private/data.bin": payload, "latent.dependencies.lock.json": encode({
            "artifacts": [{"id": owner, "files": [{"digest": digest(payload), "size": len(payload)}]}]})}
        row = {**declaration("private/data.bin", "dependencies/private/data.bin"), "digest": digest(payload), "owner": owner}
        embedded = resources.install(files, self.project(), additional_resources=[row])
        self.assertEqual(embedded.observation["resources"][0]["owner"], owner)
        self.assertEqual(embedded.observation["resources"][0]["origin"], "dependency")
        for values in ({"owner": "nuget:uncaptured:1.0"}, {"digest": digest(b"tampered")}):
            project = self.project("denied-" + next(iter(values)))
            before = snapshot(project)
            with self.subTest(values=values), self.assertRaises(guest_resources.ResourceError):
                resources.install(files, project, additional_resources=[{**row, **values}])
            self.assertEqual(snapshot(project), before)

    def test_alias_missing_and_limit_rejection_precedes_owned_output_writes(self):
        attempts = [inputs([declaration("data/A.bin"), declaration("data/a.bin")]),
                    inputs([declaration("missing.bin", "assets/missing.bin")]),
                    inputs([declaration("../outside.bin")])]
        for number, files in enumerate(attempts):
            project = self.project("denied-" + str(number))
            before = snapshot(project)
            with self.subTest(number=number), self.assertRaises(guest_resources.ResourceError):
                resources.install(files, project)
            self.assertEqual(snapshot(project), before)
        project = self.project("bounded")
        before = snapshot(project)
        with patch.object(guest_resources, "MAX_TOTAL", 1), self.assertRaisesRegex(guest_resources.ResourceError, "byte-limit"):
            resources.install(inputs([declaration("data.bin")]), project)
        self.assertEqual(snapshot(project), before)

    def test_generated_byte_metadata_and_inventory_mutations_are_detected(self):
        for case in ("bytes", "metadata", "extra"):
            project = self.project(case)
            embedded = resources.install(inputs([declaration("data.bin")]), project)
            if case == "bytes":
                next((project / "resources").iterdir()).write_bytes(b"changed")
            elif case == "metadata":
                (project / "Capsule.csproj").write_bytes(embedded.project_bytes.replace(b"data.bin", b"other.bin"))
            else:
                (project / "resources/unlisted.bin").write_bytes(b"not selected")
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, "changed during compilation"):
                embedded.check_unchanged()

    def test_empty_and_absent_declarations_preserve_closed_source_project(self):
        project = self.project()
        before = snapshot(project)
        self.assertIsNone(resources.install({}, project))
        self.assertEqual(snapshot(project), before)
        embedded = resources.install(inputs([]), project)
        self.assertEqual(embedded.observation["count"], 0)
        self.assertEqual(snapshot(project), before)
        embedded.check_unchanged()

    def test_invalid_selection_is_rejected_before_contract_or_compiler_execution(self):
        project = create(self.root / "invalid-source", "greeting")
        (project / guest_resources.MANIFEST).write_bytes(inputs([declaration("missing.bin", "missing.bin")])[guest_resources.MANIFEST])
        binary = self.root / "never-executed"
        binary.write_bytes(b"synthetic tool identity")
        output = self.root / "failed"
        with patch("tools.dotnet_guest.build.Commands") as commands, patch("tools.dotnet_guest.build.Compiler") as compiler:
            with self.assertRaisesRegex(guest_resources.ResourceError, "source-missing"):
                build(project, output, binary, binary,
                      "https://github.com/KirilsTurkins/latent-service-fabric", tools=self.root / "tools")
            commands.assert_not_called()
            compiler.assert_not_called()
        import json
        receipt = json.loads((output / "BUILD-FAILED.json").read_bytes())
        self.assertEqual(receipt["stage"], "resource-inputs")
        self.assertFalse((output / "BUILD-COMPLETE.json").exists())

    def test_sdk_owned_project_imports_are_bound_before_resource_receipt(self):
        from tools.tests.test_dotnet_application_dependencies import CapturedCompilerSelection
        fixture = CapturedCompilerSelection()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        compiler, work, output = fixture.application(fixture.root)
        files = inputs([declaration("data.bin")])
        for name, payload in files.items():
            destination = work / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)

        def prepare_sdk_port(_compiler, _declared, project, _output):
            document = ET.fromstring((project / "Capsule.csproj").read_bytes())
            ET.SubElement(document, "Import", {"Project": "sdk-owned-port.targets"})
            (project / "Capsule.csproj").write_bytes(ET.tostring(document, encoding="utf-8"))
            return None

        with patch("tools.dotnet_application_dependencies.configure", fixture.configure), patch(
                "tools.dotnet_guest.entropy.prepare", side_effect=prepare_sdk_port):
            component, receipt = compiler.compile(work, "examples:greeting/service@1.0.0", output)
        self.assertTrue(component.is_file())
        generated = (output / "project/Capsule.csproj").read_bytes()
        self.assertEqual(receipt["embeddedResourceInputs"]["projectDigest"], digest(generated))
        self.assertEqual(ET.fromstring(generated).find("Import").attrib, {"Project": "sdk-owned-port.targets"})
        self.assertIn(output / "project/resources", compiler.isolation.read_only_inputs)
        self.assertIn("locked-restore", fixture.stages)
        self.assertIn("closed-runtime-composition", fixture.stages)
        fixture.configure.assert_called_once_with(compiler.application_closure, work, compiler.package_cache)

    def test_real_compiler_boundary_rechecks_resource_bytes_after_native_commands(self):
        from tools.tests.test_dotnet_application_dependencies import CapturedCompilerSelection
        fixture = CapturedCompilerSelection()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        compiler, work, output = fixture.application(fixture.root)
        for name, payload in inputs([declaration("data.bin")]).items():
            destination = work / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        original = compiler.native_aot

        def mutated_native_command(project, compiled, wrapper):
            original(project, compiled, wrapper)
            next((project / "resources").iterdir()).write_bytes(b"changed during build")

        compiler.native_aot = mutated_native_command
        with patch("tools.dotnet_application_dependencies.configure", fixture.configure), self.assertRaisesRegex(
                ValueError, "generated embedded resource bytes changed during compilation"):
            compiler.compile(work, "examples:greeting/service@1.0.0", output)
        self.assertIn("native-aot", fixture.stages)
        self.assertIn("closed-runtime-composition", fixture.stages)


if __name__ == "__main__":
    unittest.main()
