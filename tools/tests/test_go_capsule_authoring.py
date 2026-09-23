"""Go project capture is independent; real compiler/node behavior is in CI."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.go_capsule_project import create, snapshot, validate, TEMPLATES, RUNTIME_IMPORTS
from tools.go_capsule_build import build
from tools.build_go_guest_capsules import project as sdk_project, NAMES
from tools.go_guest.sdk import install, CAPABILITIES, explicit_resource_owners


class GoAuthoringTests(unittest.TestCase):
    def test_guide_and_selectable_examples_cover_the_printed_workflow(self):
        import re
        from tools.go_capsule_project import ROOT
        guide = (ROOT / "docs/component-development/go-authoring.md").read_text()
        self.assertEqual(len(re.findall(r"^```bash$", guide, re.M)), 6)
        for operation in ("new", "build", "demo-sign", "serve", "release publish-package",
                          "deployment apply", "invoke", "deployment delete", "stop_go_node"):
            self.assertIn(operation, guide)
        for template in ("greeting", "word-count", "shipping"):
            example = json.loads((ROOT / "examples/guides" / ("tutorial-" + template) / "example.json").read_text())
            variant, = [item for item in example["variants"] if item["language"] == "go"]
            self.assertEqual(variant["source"], f"sdk/go-guest/templates/{template}.go")
            self.assertEqual(variant["validation"]["target"], "tools/qualify_go_capsules.py")

    def test_every_sdk_fixture_is_an_editable_source_project_with_exact_wit(self):
        for name in NAMES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                directory = sdk_project(Path(temporary) / "fixture", name)
                files = snapshot(directory)
                value, _, _ = validate(files)
                self.assertEqual(value["name"], "guest-" + name)
                self.assertEqual(value["limits"]["memoryBytes"], 67108864)
                self.assertEqual(value["tenant"], None if name in {"service", "callee"} else "tests")
                from tools.rust_capsule_build import package_inputs
                from tools.go_capsule_project import ROOT
                from jsonschema import Draft202012Validator
                output = Path(temporary) / "packaged"
                output.mkdir()
                package_inputs(output, value, {"imports": [], "exports": []}, files, b"component")
                metadata = json.loads((output / "capsule.json").read_text())["metadata"]
                schema = json.loads((ROOT / "schemas/capsule-manifest.schema.json").read_text())
                # Exercise the actual closed field schema; semantic WIT checks
                # and component validation are exercised by the real packager.
                Draft202012Validator(schema["properties"]["metadata"]).validate(metadata)
                self.assertEqual("tenant" in metadata, value["tenant"] is not None)
                for identity in RUNTIME_IMPORTS:
                    self.assertEqual(files["wit/world.wit"].count(("import " + identity + ";").encode()), 1)

    def test_sdk_aliases_follow_generated_identity_without_exposing_resource_constructors(self):
        from tools.go_capsule_project import ROOT
        with tempfile.TemporaryDirectory() as temporary:
            module = Path(temporary)
            for name, (identity, excluded) in CAPABILITIES.items():
                directory = module / ("versioned_" + name)
                directory.mkdir()
                text = (f"package {directory.name}\n//go:wasmimport {identity} run\n"
                        "type Error struct {}\n" + "".join(f"type {item} struct {{}}\n" for item in excluded))
                (directory / "wit_bindings.go").write_text(text)
            install(ROOT / "sdk/go-guest", module)
            for name, (_, excluded) in CAPABILITIES.items():
                aliases = (module / "lsf" / name / "types.go").read_text()
                self.assertIn(f'wit_component/versioned_{name}', aliases)
                for item in excluded:
                    self.assertNotIn(f"type {item} =", aliases)
            with self.assertRaises(FileExistsError):
                install(ROOT / "sdk/go-guest", module)

    def test_every_editable_template_has_exact_runtime_imports_and_captured_sdk(self):
        for template in TEMPLATES:
            with self.subTest(template=template), tempfile.TemporaryDirectory() as temporary:
                root = create(Path(temporary) / "project", template)
                files = snapshot(root)
                project, lock, _pins = validate(files)
                self.assertEqual(project["world"], f"examples:{template}/service@1.0.0")
                self.assertEqual(lock["language"], "go")
                for name in ("go.mod", "go.sum"):
                    self.assertEqual(files[name], files["vendor/lsf/sdk/go-guest/runtime-deps/" + name])
                self.assertTrue(files["src/main.go"].startswith(b"// lsf-example-begin:"))
                for capability in RUNTIME_IMPORTS:
                    self.assertIn(("import " + capability + ";").encode(), files["wit/world.wit"])
                self.assertNotIn(b"grants", files["capsule-project.json"])

    def test_generated_resource_owners_have_no_gc_effects_and_reject_shape_drift(self):
        constructor = '''func ChunkFromOwnHandle(handleValue int32) *Chunk {
\thandle := witRuntime.MakeHandle(handleValue)
\tvalue := &Chunk{handle}
\truntime.AddCleanup(value, func(_ int) {
\t\thandleValue := handle.TakeOrNil()
\t\tif handleValue != 0 {
\t\t\tresourceDropChunk(handleValue)
\t\t}
\t}, 0)
\treturn value
}'''
        explicit = '''func (self *Chunk) Drop() {
\thandle := self.handle.TakeOrNil()
\tif handle != 0 {
\t\tresourceDropChunk(handle)
\t}
}'''
        source = 'package blob\nimport (\n\t"runtime"\n)\n' + explicit + "\n" + constructor
        adapted = explicit_resource_owners(source)
        self.assertNotIn("AddCleanup", adapted)
        self.assertNotIn('"runtime"', adapted)
        self.assertIn(explicit, adapted)
        self.assertIn("value := &Chunk{handle}", adapted)
        self.assertIn('"runtime"', explicit_resource_owners(source + "\nfunc keep() { runtime.KeepAlive(nil) }"))
        for changed in (source.replace("func(_ int)", "func(_ uint32)"),
                        source.replace("resourceDropChunk(handleValue)", "otherDrop(handleValue)"),
                        source + "\nfunc unexpected() { runtime.SetFinalizer(nil, nil) }"):
            with self.subTest(changed=changed[-120:]), self.assertRaises(ValueError):
                explicit_resource_owners(changed)

    def test_sdk_mutation_does_not_silently_become_a_reviewed_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            files = snapshot(create(Path(temporary) / "project", "greeting"))
            files["vendor/lsf/sdk/go-guest/runtime/deny-wasi.wat"] += b"\n;; changed\n"
            with self.assertRaisesRegex(ValueError, "vendored SDK changed"):
                validate(files)

    def test_module_template_rejects_unreviewed_application_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            files = snapshot(create(Path(temporary) / "project", "greeting"))
            for name in ("go.mod", "go.sum"):
                changed = dict(files)
                changed[name] += b"\nexample.invalid/unreviewed v1.0.0\n"
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unreviewed Go module inputs"):
                    validate(changed)
                del changed[name]
                with self.subTest(missing=name), self.assertRaisesRegex(ValueError, "incomplete Go capsule project"):
                    validate(changed)

    def test_source_and_wit_remain_editable_but_budget_types_are_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            files = snapshot(create(Path(temporary) / "project", "greeting"))
            files["src/main.go"] += b"\n// developer edit\n"
            files["wit/world.wit"] += b"\n// contract edit\n"
            validate(files)
            for invalid in (True, 1, "", []):
                changed = dict(files)
                value = json.loads(files["capsule-project.json"])
                value["tenant"] = invalid
                changed["capsule-project.json"] = json.dumps(value).encode()
                with self.subTest(tenant=invalid), self.assertRaises(ValueError):
                    validate(changed)
            for invalid in (True, -1, 2**64, None):
                changed = dict(files)
                value = json.loads(files["capsule-project.json"])
                value["limits"]["cpuFuel"] = invalid
                changed["capsule-project.json"] = json.dumps(value).encode()
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    validate(changed)

    def test_existing_source_and_overlapping_build_outputs_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = create(Path(temporary) / "project", "greeting")
            before = snapshot(root)
            with self.assertRaises(ValueError):
                create(root, "shipping")
            for output in (root, root.parent, root / "output"):
                with self.subTest(output=output), self.assertRaisesRegex(ValueError, "build output"):
                    build(root, output, Path("missing"), Path("missing"), "https://example.invalid/source")
            self.assertEqual(snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
