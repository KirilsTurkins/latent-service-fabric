"""Go project capture is independent; real compiler/node behavior is in CI."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.go_capsule_project import create, snapshot, validate, TEMPLATES, RUNTIME_IMPORTS
from tools.go_capsule_build import build
from tools.build_go_guest_capsules import project as sdk_project, NAMES
from tools.go_guest.sdk import install, CAPABILITIES, explicit_resource_owners


class GoAuthoringTests(unittest.TestCase):
    def test_runtime_transformation_material_captures_all_bytes_above_control_document_size(self):
        from tools.go_capsule_build import runtime_transformations_material
        from tools.rust_capsule_project import digest, MAX_FILE
        value = {'formatVersion': 1, 'profile': 'go-component-activation-v4',
                 'automaticTransformations': [
                     {'name': 'compiler-checkpoint/' + str(index),
                      'upstreamDigest': 'sha256:' + 'a' * 64,
                      'adaptedDigest': 'sha256:' + 'b' * 64,
                      'sites': [{'offset': offset, 'suspendable': True} for offset in range(20)]}
                     for index in range(94)]}
        raw = (json.dumps(value, indent=2) + '\n').encode()
        self.assertGreater(len(raw), 65536)
        self.assertLess(len(raw), MAX_FILE)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            path = output / 'go-runtime-transformations.json'
            path.write_bytes(raw)
            self.assertEqual(runtime_transformations_material(output),
                {'name': 'go-runtime-transformations', 'digest': digest(raw), 'size': len(raw)})
            # A change beyond the old control-document ceiling remains bound.
            value['automaticTransformations'][-1]['adaptedDigest'] = 'sha256:' + 'c' * 64
            changed = (json.dumps(value, indent=2) + '\n').encode()
            self.assertEqual(changed[:65536], raw[:65536])
            path.write_bytes(changed)
            self.assertEqual(runtime_transformations_material(output)['digest'], digest(changed))
            self.assertNotEqual(digest(changed), digest(raw))

    def test_runtime_transformation_material_still_rejects_oversize_and_nonregular_inputs(self):
        from tools.go_capsule_build import runtime_transformations_material
        from tools.rust_capsule_project import MAX_FILE
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            path = output / 'go-runtime-transformations.json'
            path.write_bytes(b' ' * (MAX_FILE + 1))
            with self.assertRaisesRegex(ValueError, 'source must be a bounded regular file'):
                runtime_transformations_material(output)
            path.unlink()
            path.mkdir()
            with self.assertRaisesRegex(ValueError, 'source must be a bounded regular file'):
                runtime_transformations_material(output)

    def test_explicit_runtime_templates_capture_async_api_and_owned_runtime_without_source_edits(self):
        from tools.go_capsule_project import AUTHORING_TEMPLATES, ROOT
        from tools.go_guest.activation import PROFILES
        from tools.rust_capsule_project import digest
        for profile in sorted(PROFILES):
            templates = AUTHORING_TEMPLATES if profile == 'go-component-activation-v4' else ('greeting',)
            for template in templates:
                with self.subTest(profile=profile, template=template), tempfile.TemporaryDirectory() as temporary:
                    files = snapshot(create(Path(temporary) / 'app', template, runtime_profile=profile))
                    value, lock, _ = validate(files)
                    self.assertEqual(value['runtimeProfile'], profile)
                    self.assertEqual(files['src/main.go'], (ROOT / 'sdk/go-guest/templates' / (template + '.go')).read_bytes())
                    self.assertIn(b'import latent:runtime/activation@0.1.0;', files['wit/world.wit'])
                    self.assertIn(b'async func(', files['wit/world.wit'])
                    self.assertNotRegex(files['wit/world.wit'].decode(), r':\s*func\s*\(')
                    self.assertEqual(files['wit/deps/activation-runtime/package.wit'],
                        files['vendor/lsf/wit/platform/activation-runtime/package.wit'])
                    self.assertNotIn('grants', value)
                    self.assertEqual(lock['template']['witDigest'], digest(files['wit/world.wit']))

    def test_cli_runtime_selection_preserves_default_and_rejects_unknown_before_creation(self):
        import contextlib
        import io
        from tools import go_capsule
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ordinary = snapshot(create(root / 'ordinary', 'greeting'))
            self.assertNotIn('runtimeProfile', json.loads(ordinary['capsule-project.json']))
            self.assertNotIn(b'latent:runtime/activation', ordinary['wit/world.wit'])
            self.assertIn(b'greet: func(', ordinary['wit/world.wit'])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(go_capsule.main(['new', str(root / 'selected'), '--runtime-profile', 'go-component-activation-v4']), 0)
            self.assertEqual(validate(snapshot(root / 'selected'))[0]['runtimeProfile'], 'go-component-activation-v4')
            for profile in ('native-go', False, 0, '', [], {}):
                with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, 'profile-not-installed'):
                    create(root / 'invalid', 'greeting', runtime_profile=profile)
                self.assertFalse((root / 'invalid').exists())
            for profile in (None, False, 0, '', [], {}, 'native-go'):
                files = dict(ordinary)
                document = json.loads(files['capsule-project.json'])
                document['runtimeProfile'] = profile
                files['capsule-project.json'] = json.dumps(document).encode()
                with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, 'profile-not-installed'):
                    validate(files)

            from tools import go_application_dependencies as dependencies
            self.assertEqual(dependencies.selection(None), dependencies.selection({}))
            for profile in ('go-component-async-v1', 'go-component-activation-v1', 'go-component-activation-v2',
                            'go-component-activation-v3', 'go-component-activation-v4'):
                declared = {'runtimeProfile': profile, 'tags': ['other', 'local_feature', 'other']}
                before = json.loads(json.dumps(declared))
                self.assertEqual(dependencies.selection(declared),
                                 {'target': 'wasip1/wasm', 'runtimeProfile': profile,
                                  'tags': ['local_feature', 'other']})
                self.assertEqual(declared, before)
            candidate = root / 'candidate.json'
            selected_project = root / 'selected'
            sdk_before = (selected_project / 'sdk-lock.json').read_bytes()
            with patch.object(dependencies, 'run_bounded', side_effect=AssertionError('unexpected native command')) as native:
                for selected in (False, 0, 1, '', [], [('runtimeProfile', 'go-component-activation-v4')]):
                    with self.subTest(selected=selected), self.assertRaisesRegex(dependencies.DependencyError, 'selection-fields-invalid'):
                        dependencies.selection(selected)
                    with self.subTest(resolver_selection=selected), self.assertRaisesRegex(dependencies.DependencyError, 'selection-fields-invalid'):
                        dependencies.resolve(selected_project, candidate, selected=selected)
                with self.assertRaisesRegex(dependencies.DependencyError, 'project-and-captured-runtime-profile-disagree'):
                    dependencies.resolve(selected_project, candidate, selected={'runtimeProfile': 'go-component-activation-v1'})
                for profile in (None, False, 0, '', [], {}, 'native-go'):
                    with self.subTest(selection_profile=profile), self.assertRaisesRegex(dependencies.DependencyError, 'profile-not-installed'):
                        dependencies.selection({'runtimeProfile': profile})
                    document = json.loads((selected_project / 'capsule-project.json').read_bytes())
                    document['runtimeProfile'] = profile
                    (selected_project / 'capsule-project.json').write_bytes(json.dumps(document).encode())
                    with self.subTest(resolver_profile=profile), self.assertRaisesRegex(dependencies.DependencyError, 'profile-not-installed'):
                        dependencies.resolve(selected_project, candidate, selected={})
                native.assert_not_called()
            self.assertFalse(candidate.exists())
            self.assertFalse((selected_project / 'go-resolved.lock.json').exists())
            self.assertEqual((selected_project / 'sdk-lock.json').read_bytes(), sdk_before)

    def test_generated_business_record_owners_survive_export_stub_replacement(self):
        from tools.go_guest.sdk import export_declarations
        source = ('package export_examples_aggregate_api\n\nimport (\n'
                  '\twit "go.bytecodealliance.org/pkg/wit/types"\n'
                  '\traw "wit_component/latent_types"\n)\n\n'
                  'type Aggregate struct { Count uint64; Cursor wit.Option[[]byte] }\n'
                  'type BusinessError uint8\nconst BusinessErrorRejected uint8 = 0\n'
                  'func Update(value uint32) wit.Result[Aggregate, BusinessError] {\n'
                  '\tpanic("not implemented")\n}\n')
        result = export_declarations(source)
        self.assertIn('type Aggregate struct', result)
        self.assertIn('Cursor wit.Option[[]byte]', result)
        self.assertIn('type BusinessError uint8', result)
        self.assertIn('const BusinessErrorRejected', result)
        self.assertIn('wit "go.bytecodealliance.org/pkg/wit/types"', result)
        self.assertNotIn('raw "wit_component/latent_types"', result)
        self.assertNotIn('func Update', result)
        self.assertNotIn('panic(', result)
        with self.assertRaisesRegex(ValueError, 'generated-Go-export-stub-drift'):
            export_declarations(source.replace('\tpanic(', '\treturn panic('))

    def test_readme_entrypoints_match_every_typed_capability_facade(self):
        import re
        from tools.go_capsule_project import ROOT
        sdk = ROOT / "sdk/go-guest"
        readme = (sdk / "README.md").read_text()
        rows = re.findall(r"^\| `([a-z]+)` \| (.+) \|$", readme, re.M)
        self.assertEqual({name for name, _ in rows}, set(CAPABILITIES))
        for name, description in rows:
            source = (sdk / "capabilities" / (name + ".go.in")).read_text()
            for entrypoint in re.findall(r"`([A-Z][A-Za-z0-9]+)`", description):
                with self.subTest(capability=name, entrypoint=entrypoint):
                    self.assertRegex(source, r"func (?:\([^\n]+\) )?" + entrypoint + r"\(")

    def test_sdk_builder_reuses_captured_tools_without_rebuilding_and_rejects_mutation(self):
        from tools import build_go_guest_capsules as sdk_builder
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contracts, packager = root / "contracts-tool", root / "packager"
            contracts.write_bytes(b"captured contracts")
            packager.write_bytes(b"captured packager")
            with patch.object(sdk_builder, "NAMES", ("http",)), \
                    patch.object(sdk_builder, "project", side_effect=lambda path, _name: path), \
                    patch.object(sdk_builder, "build") as compiler:
                sdk_builder.compile_all(root / "valid", contracts_tool=contracts, packager=packager)
                compiler.assert_called_once_with(root / "valid/projects/http", root / "valid/go-http",
                    contracts, packager, "https://github.com/KirilsTurkins/latent-service-fabric")
                report = json.loads((root / "valid/SDK-BUILD.json").read_text())
                self.assertEqual(report["status"], "built-execution-required")
                self.assertEqual(report["commands"], [])
                self.assertFalse(report["runtimeQualified"])
                compiler.side_effect = lambda *_args: packager.write_bytes(b"changed executable")
                with self.assertRaisesRegex(ValueError, "packaging executables changed"):
                    sdk_builder.compile_all(root / "changed", contracts_tool=contracts, packager=packager)
                failed = json.loads((root / "changed/SDK-BUILD.json").read_text())
                self.assertEqual(failed["status"], "failed")
            for selected in ({"contracts_tool": contracts}, {"packager": packager}):
                with self.subTest(selected=selected), self.assertRaisesRegex(ValueError, "both captured"):
                    sdk_builder.compile_all(root / "incomplete", **selected)
                self.assertFalse((root / "incomplete").exists())
            commands = Mock()
            selected = sdk_builder.packaging_tools(commands, root / "target", None, None)
            self.assertEqual(selected, (root / "target/debug/examples/capsule_contracts",
                                        root / "target/debug/examples/package"))
            commands.run.assert_called_once()

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
