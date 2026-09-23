"""Closed editable inputs; actual pinned compiler and host operations run in CI."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.typescript_guest import project
from tools.typescript_guest.build import build
from tools.build_typescript_guest_capsules import NAMES, project as sdk_project


class TypeScriptAuthoringTests(unittest.TestCase):
    def test_qualification_watchdogs_remain_explicit_and_finite(self):
        from tools.rust_capsule_build import Commands
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for overall, command in [(True, 1), (900, True), (0, 1), (7201, 1), (3600, 1801), (60, 61)]:
                with self.subTest(overall=overall, command=command), self.assertRaisesRegex(ValueError, "finite"):
                    Commands(root, root, {}, deadline_seconds=overall, command_seconds=command)
            self.assertFalse((root / "logs").exists())
            owner = Commands(root, root, {}, deadline_seconds=3600, command_seconds=1800)
            self.assertEqual(owner.command_seconds, 1800)

    def test_import_identity_follows_selected_world_and_never_arena_indexes(self):
        from tools.typescript_guest.compiler import import_identities
        graph = {"packages": [{"name": "latent:http@0.2.0"}, {"name": "tests:app@1.0.0"}],
                 "interfaces": [{"name": "client", "package": 0}],
                 "worlds": [{"name": "service", "package": 1, "imports": {"interface-0": {"interface": {"id": 0}}}},
                            {"name": "other", "package": 1, "imports": {}}]}
        self.assertEqual(import_identities(graph, "tests:app/service@1.0.0"), ["latent:http/client@0.2.0"])
        self.assertEqual(import_identities(graph, "tests:app/other@1.0.0"), [])
        graph["worlds"][0]["imports"] = {"alias": {"interface": {"id": 0}}}
        with self.assertRaisesRegex(ValueError, "unsupported named"):
            import_identities(graph, "tests:app/service@1.0.0")

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="typescript-authoring-tests-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = project.create(Path(cls.temporary.name) / "project", "greeting")
        cls.files = project.snapshot(cls.root)

    def test_every_template_captures_editable_sources_and_exact_sdk(self):
        for template in project.TEMPLATES:
            with self.subTest(template=template), tempfile.TemporaryDirectory() as temporary:
                files = project.snapshot(project.create(Path(temporary) / "project", template))
                value, lock, _pins = project.validate(files)
                self.assertEqual(value["world"], f"examples:{template}/service@1.0.0")
                self.assertEqual(value["limits"]["outboundRequests"], int(template == "http-status"))
                self.assertEqual(lock["template"]["sourceDigest"], project.digest(files["src/main.ts"]))
                self.assertEqual(
                    sorted(path for path in files if path.startswith("vendor/lsf/sdk/typescript-guest/runtime/")),
                    ["vendor/lsf/sdk/typescript-guest/runtime/text.ts"])
                self.assertFalse(any("tests/model" in path for path in files))
                files["src/main.ts"] += b"\n// application edit\n"
                files["wit/world.wit"] += b"\n// contract edit\n"
                project.validate(files)

    def test_sdk_wit_and_compiler_lock_drift_are_rejected(self):
        for name in ("sdk/typescript-guest/capabilities/owner.ts", "tools/toolchain.toml",
                     "wit/platform/http-v2/package.wit", "sdk/typescript-guest/tools/package-lock.json"):
            files = dict(self.files)
            files["vendor/lsf/" + name] += b"\n"
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "vendored SDK changed"):
                project.validate(files)

    def test_fresh_project_and_safe_names_never_overwrite_source(self):
        with self.assertRaisesRegex(ValueError, "fresh"):
            project.create(self.root, "shipping")
        self.assertEqual(project.snapshot(self.root), self.files)
        for name in ("../escape", "Name", "a--b", "x" * 65):
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "project"
                with self.assertRaises(ValueError):
                    project.create(output, "greeting", name)
                self.assertFalse(output.exists())

    def test_source_and_compiler_directory_overlap_is_rejected_before_execution(self):
        for output in (self.root, self.root.parent, self.root / "output"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "build output"):
                build(self.root, output, Path("missing"), Path("missing"),
                      "https://example.invalid/source", tools=Path("missing-tools"))
        for compiler in (self.root, self.root.parent, self.root / "compiler"):
            with self.subTest(compiler=compiler), self.assertRaisesRegex(ValueError, "compiler installation"):
                build(self.root, self.root.parent / "output", Path("missing"), Path("missing"),
                      "https://example.invalid/source", tools=compiler)

    def test_identity_budget_and_lock_formats_are_closed(self):
        for name, mutate in (
            ("capsule-project.json", lambda value: value.update(formatVersion=True)),
            ("capsule-project.json", lambda value: value.update(extra=1)),
            ("capsule-project.json", lambda value: value.update(name="../escape")),
            ("capsule-project.json", lambda value: value.update(tenant=True)),
            ("capsule-project.json", lambda value: value["limits"].update(cpuFuel=True)),
            ("capsule-project.json", lambda value: value["limits"].update(memoryBytes=2**64)),
            ("capsule-project.json", lambda value: value["limits"].update(wallTimeLimitMillis=None)),
            ("sdk-lock.json", lambda value: value.update(language="rust")),
        ):
            files = dict(self.files)
            value = json.loads(files[name])
            mutate(value)
            files[name] = json.dumps(value).encode()
            with self.subTest(name=name), self.assertRaises(ValueError):
                project.validate(files)

    def test_uncaptured_application_dependency_or_config_overrides_fail_closed(self):
        for name in ("package.json", "src/package-lock.json", "tsconfig.json"):
            files = dict(self.files, **{name: b"{}\n"})
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "reviewed dependency capture"):
                project.validate(files)

    def test_all_current_capability_fixtures_are_editable_typed_projects(self):
        from tools.rust_capsule_build import package_inputs
        from jsonschema import Draft202012Validator
        for name in NAMES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = sdk_project(Path(temporary) / "project", name)
                files = project.snapshot(root)
                value, _, _ = project.validate(files)
                self.assertEqual(value["limits"]["memoryBytes"], 134217728)
                self.assertEqual(value["limits"]["wallTimeLimitMillis"], 240000 if name == "service" else 120000)
                self.assertEqual(value["tenant"], None if name in {"service", "callee"} else "tests")
                self.assertIn(b"typeof Contract", files["src/main.ts"])
                output = Path(temporary) / "packaged"
                output.mkdir()
                package_inputs(output, value, {"imports": [], "exports": []}, files, b"component")
                metadata = json.loads((output / "capsule.json").read_text())["metadata"]
                schema = json.loads((project.ROOT / "schemas/capsule-manifest.schema.json").read_text())
                Draft202012Validator(schema["properties"]["metadata"]).validate(metadata)
                self.assertEqual("tenant" in metadata, value["tenant"] is not None)


if __name__ == "__main__":
    unittest.main()
