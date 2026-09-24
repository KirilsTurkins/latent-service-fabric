"""Outside-checkout source captures are not NativeAOT execution evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.dotnet_guest.build import build
from tools.dotnet_guest.project import create, validate
from tools.dotnet_guest.compiler import packages
from tools.build_dotnet_guest_capsules import NAMES, project
from tools.rust_capsule_project import TEMPLATES, snapshot


class DotnetAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-dotnet-authoring-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def files(self):
        return snapshot(create(self.root / "project", "greeting"))

    def test_all_templates_capture_actual_source_and_pinned_sdk(self):
        for name in TEMPLATES:
            files = snapshot(create(self.root / name, name))
            config, lock, _pins = validate(files)
            self.assertEqual(config["world"], f"examples:{name}/service@1.0.0")
            self.assertIn(b"class ApiExportsImpl", files["src/Main.cs"])
            self.assertIn(b"latent:clock/monotonic@0.1.0", files["wit/world.wit"])
            self.assertEqual(lock["language"], "dotnet")
            self.assertEqual(json.loads(files["global.json"])["sdk"]["version"], "10.0.100")

    def test_application_source_and_authoritative_wit_remain_editable(self):
        files = self.files()
        files["src/Main.cs"] += b"\n// an application change\n"
        files["wit/world.wit"] += b"\n// a contract change\n"
        validate(files)

    def test_sdk_capture_cannot_drift(self):
        files = self.files()
        files["vendor/lsf/sdk/dotnet-guest/ownership/Owner.cs"] += b"// drift\n"
        with self.assertRaisesRegex(ValueError, "vendored SDK changed"):
            validate(files)

    def test_application_cannot_inject_msbuild_or_package_overrides(self):
        original = self.files()
        for name in ["src/Directory.Build.props", "nuget.config", "packages.lock.json", "src/evil.csproj"]:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "overrides"):
                validate({**original, name: b"<Project/>"})

    def test_compiler_configuration_is_closed(self):
        files = self.files()
        for name in ["Capsule.csproj", "global.json"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate({**files, name: files[name] + b" "})

    def test_names_and_existing_directories_are_rejected(self):
        for name in ["../escape", "", "Upper", "x;cmd", "x" * 65]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                create(self.root / "invalid", "greeting", name)
        create(self.root / "existing", "greeting")
        with self.assertRaises((ValueError, FileExistsError)):
            create(self.root / "existing", "greeting")

    def test_budgets_reject_overflow_boolean_and_zero_required_dimensions(self):
        files = self.files()
        original = json.loads(files["capsule-project.json"])
        for value in [-1, 2**64, True, 0]:
            config = {**original, "limits": {**original["limits"], "cpuFuel": value}}
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate({**files, "capsule-project.json": json.dumps(config).encode()})

    def test_all_real_sdk_sources_use_the_same_capture_path(self):
        for name in NAMES:
            config, _, _ = validate(snapshot(project(self.root / name, name)))
            self.assertEqual(config["tenant"], None if name in {"service", "callee"} else "tests")
            self.assertEqual(config["limits"]["cpuFuel"], 10_000_000_000)
            self.assertEqual(config["limits"]["memoryBytes"], (256 if name == "service" else 128) * 1024 * 1024)

    def test_nuget_uses_verified_content_identity_not_raw_signed_zip_hash(self):
        directory = self.root / "packages/test/1.0.0"
        directory.mkdir(parents=True)
        archive = directory / "test.1.0.0.nupkg"
        archive.write_bytes(b"synthetic archive; no compiler authority")
        lock = {"dependencies": {"net10.0": {"Test": {"resolved": "1.0.0", "contentHash": "verified-content"}}}}
        seen = []
        def verified(path):
            seen.append(path)
            return "verified-content"
        self.assertEqual(packages(lock, self.root / "packages", verified), {"nuget/test/1.0.0": directory})
        self.assertEqual(seen, [archive])
        with self.assertRaisesRegex(ValueError, "content hash differs"):
            packages(lock, self.root / "packages", lambda _: "different")

    def test_public_contract_rejection_precedes_compiler_work(self):
        source = create(self.root / "unsupported", "greeting")
        output = self.root / "output"
        tool = self.root / "contracts-tool"
        tool.write_bytes(b"synthetic tool identity; never executed")
        with patch("tools.dotnet_guest.build.Commands") as commands, \
                patch("tools.dotnet_guest.build.Compiler") as compiler:
            commands.return_value.records = []
            commands.return_value.run.side_effect = ValueError("unsupported-public-resource")
            with self.assertRaisesRegex(ValueError, "unsupported-public-resource"):
                build(source, output, tool, tool,
                      "https://github.com/KirilsTurkins/latent-service-fabric",
                      tools=self.root / "compiler")
            compiler.assert_not_called()
            self.assertEqual(commands.return_value.run.call_args.args[0], "contracts")
        receipt = json.loads((output / "BUILD-FAILED.json").read_text())
        self.assertEqual(receipt["stage"], "contracts")
        self.assertFalse((output / "component.wasm").exists())
        self.assertFalse((output / "BUILD-COMPLETE.json").exists())


if __name__ == "__main__":
    unittest.main()
