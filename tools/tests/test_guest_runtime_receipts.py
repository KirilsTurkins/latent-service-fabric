"""Current owner inputs and bounded diagnostics, without runtime qualification."""
import ast
import copy
from pathlib import Path
import tempfile
import unittest

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_context as context
from tools import guest_compatibility_context_build as builder
from tools import guest_compatibility_outcomes as outcomes
from tools import guest_runtime_receipts as runtime
from tools.dev_workflow.common import DevError, digest, encode
from tools.rust_capsule_project import ROOT, inventory


COMPONENT = b'controlled component bytes: not a runtime qualification'
BINDINGS = digest(b'controlled actual binding output')


def inputs(language='rust', package=None):
    files = {runtime.PREFIXES[language][0] + 'runtime-source': b'original maintained runtime',
             'vendor/lsf/wit/platform/runtime/runtime.wit': b'package latent:runtime@0.1.0;',
             'wit/app.wit': b'package controlled:app;', 'src/main': b'controlled application',
             'sdk-lock.json': encode({'language': language})}
    graph = None
    if package is not None:
        graph = {'selection': {'runtimeProfile': runtime.PROFILES[language]},
                 'artifacts': [{'name': package, 'digest': digest(b'arbitrary captured package')}],
                 'privateRepository': 'https://credential:secret@private.invalid/path'}
        files['latent.dependencies.lock.json'] = encode(graph)
    return files, graph


def materials():
    return [{'name': 'build-recipe', 'digest': digest(b'actual owner recipe fixture'), 'size': 26},
            {'name': 'compiler', 'digest': digest(b'actual tool fixture'), 'size': 19}]


def rehash(value):
    value['identity'] = digest(encode({key: row for key, row in value.items() if key != 'identity'}))
    return value


class OwnerSelection(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory(); self.addCleanup(owned.cleanup)
        self.output = Path(owned.name)

    def emit(self, language='rust', package=None):
        output = self.output / str(len(list(self.output.iterdir())))
        output.mkdir()
        files, graph = inputs(language, package)
        configuration = {'profile': runtime.PROFILES[language], 'world': 'app', 'target': 'controlled-target',
                         'selection': graph['selection'] if graph is not None else {}}
        material = runtime.emit(output, language, runtime.PROFILES[language], files, inventory(files),
            COMPONENT, materials(), graph=graph, binding_digest=BINDINGS, configuration=configuration)
        value = runtime.read((output / 'standard-runtime-selection.json').read_bytes())
        return output, files, graph, configuration, material, value

    def test_explicit_runtime_owner_contract_and_captured_sdk_scope(self):
        expected = {'rust': 743, 'go': 742, 'c': 744, 'typescript': 745}
        self.assertEqual(runtime.OWNER_ISSUES, expected)
        for language, issue in expected.items():
            with self.subTest(language=language):
                value = self.emit(language)[5]
                self.assertEqual(value['ownerIssue'], issue)
                self.assertEqual(value['originalRuntimeInputsScope'], 'captured-sdk-inputs')
                self.assertIn('compiler', {row['name'] for row in value['toolAndCompilerInputs']})
                value['originalRuntimeInputsScope'] = 'entire-standard-library'; rehash(value)
                with self.assertRaisesRegex(DevError, 'source-scope'): runtime.validate(value)

    def test_actual_rust_sdk_path_is_captured_beside_bindings_and_cannot_borrow_old_preimage(self):
        files = {'vendor/lsf/sdk/rust-guest/src/lib.rs': b'actual Rust guest SDK source',
                 'vendor/lsf/crates/latent-component-bindings/src/lib.rs': b'actual generated binding boundary',
                 'wit/world.wit': b'package controlled:app;'}
        runtime.emit(self.output, 'rust', 'wasm32-unknown-unknown-panic-abort-v1', files, inventory(files),
            COMPONENT, materials(), graph=None, binding_digest=BINDINGS, configuration={})
        value = runtime.read((self.output / 'standard-runtime-selection.json').read_bytes())
        expected = inventory({name: raw for name, raw in files.items() if name != 'wit/world.wit'})
        self.assertEqual(value['originalRuntimeInputCount'], 2)
        self.assertEqual(value['originalRuntimeInputsDigest'], digest(expected))
        files['vendor/lsf/sdk/rust-guest/src/lib.rs'] = b'changed actual Rust SDK source'
        value['sourceDigest'] = digest(inventory(files)); rehash(value)
        with self.assertRaisesRegex(DevError, 'stale-runtime-preimage'):
            runtime.verify_build(value, 'rust', files, inventory(files), COMPONENT, materials())

    def test_large_valid_captured_file_graph_uses_capture_domain_without_widening_controller_limits(self):
        from tools.application_dependencies import MAX_CLOSURE_FILES, MAX_LOCK
        from tools.dev_workflow.common import decode
        files, _ = inputs('rust')
        rows = [{'path': 'src/file' + str(index) + '.rs', 'digest': digest(b'x'), 'size': 1} for index in range(9000)]
        self.assertLess(len(rows), MAX_CLOSURE_FILES)
        graph = {'formatVersion': 1, 'language': 'rust', 'manifestDigest': digest(b'manifest'),
            'selection': {'runtimeProfile': 'wasm32-unknown-unknown-panic-abort-v1'}, 'nativeLocks': [],
            'artifacts': [{'id': 'library', 'role': 'application', 'format': 'directory',
                'mount': 'application-vendor/library', 'dependencies': [], 'metadata': {},
                'source': {'type': 'captured-local'}, 'original': {'digest': digest(b'original'), 'size': 1},
                'files': rows, 'treeDigest': digest(encode(rows))}], 'transformations': [],
            'completeness': 'selected-declared-closure', 'executableInputs': []}
        raw = encode(graph); self.assertLess(len(raw), MAX_LOCK)
        with self.assertRaisesRegex(DevError, 'document-complexity-limit'): decode(raw, MAX_LOCK)
        files['latent.dependencies.lock.json'] = raw
        runtime.emit(self.output, 'rust', 'wasm32-unknown-unknown-panic-abort-v1', files, inventory(files),
            COMPONENT, materials(), graph=graph, binding_digest=BINDINGS, configuration={})
        value = runtime.read((self.output / 'standard-runtime-selection.json').read_bytes())
        self.assertEqual(value['graphDigest'], digest(raw))
        runtime.verify_build(value, 'rust', files, inventory(files), COMPONENT, materials())
        report = compatibility.report('rust', digest(inventory(files)), digest(COMPONENT),
            'lsf-host-abi-phase3-v5', [], [])
        (self.output / 'compatibility-report.json').write_bytes(encode(report))
        sidecar = (self.output / 'standard-runtime-selection.json').read_bytes()
        selected = builder.finish(self.output, files, inventory(files), COMPONENT, materials() +
            [{'name': 'standard-runtime-selection', 'digest': digest(sidecar), 'size': len(sidecar)}])
        self.assertEqual(selected['standardRuntime']['state'], 'selected-unqualified')

    def test_capture_graph_still_rejects_duplicate_fields_nonfinite_nesting_and_original_byte_limit(self):
        from tools.application_dependencies import MAX_LOCK
        files, _ = inputs('rust')
        for raw in (b'{"selection":{},"selection":{}}', b'{"selection":NaN}',
                    b'{"nested":' + b'[' * 65 + b'0' + b']' * 65 + b'}', b' ' * (MAX_LOCK + 1)):
            files['latent.dependencies.lock.json'] = raw
            with self.subTest(bytes=len(raw)), self.assertRaises(ValueError):
                runtime.captured_inputs('rust', files, inventory(files))

    def test_four_owners_capture_actual_sources_profiles_and_binding_transformation(self):
        for language in ('rust', 'go', 'c', 'typescript'):
            with self.subTest(language=language):
                _, files, graph, configuration, material, value = self.emit(language)
                self.assertEqual(value['profile'], runtime.PROFILES[language])
                self.assertEqual(value['ownerIssue'], runtime.OWNER_ISSUES[language])
                self.assertEqual(value['sourceDigest'], digest(inventory(files)))
                self.assertEqual(value['componentDigest'], digest(COMPONENT))
                self.assertEqual(value['transformations'][0]['resultDigest'], BINDINGS)
                self.assertEqual(value['transformations'][0]['configurationDigest'], digest(encode(configuration)))
                self.assertEqual(value['transformations'][0]['inputScope'], 'captured-wit-inventory')
                runtime.verify_build(value, language, files, inventory(files), COMPONENT, materials())
                self.assertEqual(set(material), {'name', 'digest', 'size'})
                self.assertEqual((value['qualification'], value['apiSupport'], value['authority']),
                                 ('unknown', 'not-evaluated', 'none'))

    def test_arbitrary_package_names_change_graph_identity_without_api_approval(self):
        for language in runtime.PROFILES:
            with self.subTest(language=language):
                first = self.emit(language, 'new-unknown-package')[5]
                second = self.emit(language, 'renamed-arbitrary-package')[5]
                self.assertNotEqual(first['graphDigest'], second['graphDigest'])
                self.assertNotEqual(first['sourceDigest'], second['sourceDigest'])
                for field in ('profile', 'apiSupport', 'qualification', 'ownerIssue', 'authority'):
                    self.assertEqual(first[field], second[field])
                self.assertNotIn('secret', encode(first).decode())
                self.assertNotIn('private.invalid', encode(first).decode())
                self.assertNotIn('new-unknown-package', encode(first).decode())

    def test_optional_graph_is_distinct_from_captured_graph(self):
        absent = self.emit()[5]; captured = self.emit(package='unknown')[5]
        self.assertEqual((absent['graphState'], absent['graphDigest']), ('absent', None))
        self.assertEqual(captured['graphState'], 'captured')
        self.assertEqual(absent['profile'], captured['profile'])
        with self.assertRaisesRegex(DevError, 'stale-graph'): runtime.validate(captured, graph=None)

    def test_detached_source_inventory_cannot_be_used_to_emit_selection(self):
        files, graph = inputs()
        with self.assertRaisesRegex(DevError, 'detached-source'):
            runtime.emit(self.output, 'rust', runtime.PROFILES['rust'], files, inventory({'old': b'old'}),
                COMPONENT, materials(), graph=graph, binding_digest=BINDINGS, configuration={})
        self.assertFalse((self.output / 'standard-runtime-selection.json').exists())

    def test_captured_graph_cannot_be_hidden_or_replaced_at_emission(self):
        files, graph = inputs(package='unknown')
        for supplied in (None, {**graph, 'selection': {'runtimeProfile': 'other'}}):
            with self.subTest(supplied=supplied), self.assertRaisesRegex(DevError, 'stale-graph'):
                runtime.emit(self.output, 'rust', runtime.PROFILES['rust'], files, inventory(files),
                    COMPONENT, materials(), graph=supplied, binding_digest=BINDINGS, configuration={})

    def test_changed_application_source_invalidates_original_receipt(self):
        _, files, _, _, _, value = self.emit()
        files['src/main'] = b'changed application'
        with self.assertRaisesRegex(DevError, 'stale-source'):
            runtime.verify_build(value, 'rust', files, inventory(files), COMPONENT, materials())

    def test_rehashed_receipt_cannot_borrow_changed_runtime_preimage(self):
        _, files, _, _, _, value = self.emit()
        files[runtime.PREFIXES['rust'][0] + 'runtime-source'] = b'changed maintained port'
        value['sourceDigest'] = digest(inventory(files)); rehash(value)
        with self.assertRaisesRegex(DevError, 'stale-runtime-preimage'):
            runtime.verify_build(value, 'rust', files, inventory(files), COMPONENT, materials())

    def test_rehashed_receipt_cannot_borrow_changed_wit_preimage(self):
        _, files, _, _, _, value = self.emit()
        files['wit/app.wit'] = b'changed declarations'
        value['sourceDigest'] = digest(inventory(files)); rehash(value)
        with self.assertRaisesRegex(DevError, 'stale-binding-preimage'):
            runtime.verify_build(value, 'rust', files, inventory(files), COMPONENT, materials())

    def test_rehashed_receipt_cannot_borrow_changed_graph_or_profile(self):
        _, files, graph, _, _, value = self.emit(package='unknown')
        graph['artifacts'][0]['digest'] = digest(b'changed dependency')
        files['latent.dependencies.lock.json'] = encode(graph)
        value['sourceDigest'] = digest(inventory(files)); rehash(value)
        with self.assertRaisesRegex(DevError, 'stale-graph'):
            runtime.verify_build(value, 'rust', files, inventory(files), COMPONENT, materials())
        value['graphDigest'] = digest(encode(graph)); value['profile'] = 'planned-uninstalled-profile'; rehash(value)
        with self.assertRaisesRegex(DevError, 'stale-profile'):
            runtime.verify_build(value, 'rust', files, inventory(files), COMPONENT, materials())

    def test_changed_compiler_or_recipe_cannot_reuse_old_transformation(self):
        _, files, _, _, _, value = self.emit()
        for name in ('compiler', 'build-recipe'):
            current = materials()
            next(row for row in current if row['name'] == name)['digest'] = digest(b'changed tool')
            with self.subTest(name=name), self.assertRaisesRegex(DevError, 'stale-tool-or-recipe'):
                runtime.verify_build(value, 'rust', files, inventory(files), COMPONENT, current)

    def test_binding_result_component_and_configuration_are_independent_bindings(self):
        _, _, _, configuration, _, value = self.emit()
        for bindings, reason in (({'result': digest(b'new bindings')}, 'binding-result'),
                                 ({'component': digest(b'new component')}, 'component'),
                                 ({'configuration': {**configuration, 'world': 'other'}}, 'configuration'),
                                 ({'language': 'go'}, 'language')):
            with self.subTest(reason=reason), self.assertRaisesRegex(DevError, 'stale-' + reason):
                runtime.validate(value, **bindings)

    def test_receipt_cannot_claim_runtime_qualification_or_new_authority(self):
        value = self.emit()[5]
        for field, claimed in (('qualification', 'qualified'), ('apiSupport', 'supported'), ('authority', 'automatic-grant')):
            current = copy.deepcopy(value); current[field] = claimed; rehash(current)
            with self.subTest(field=field), self.assertRaisesRegex(DevError, 'cannot-certify-api'):
                runtime.validate(current)

    def test_signed_materials_remain_closed_and_bounded_without_role(self):
        for invalid in ([{**materials()[0], 'role': 'generated'}], materials() * 2,
                        [{'name': 'm' + str(index), 'digest': digest(b'm'), 'size': 1} for index in range(64)]):
            with self.subTest(count=len(invalid)), self.assertRaises(DevError): runtime.material_inputs(invalid)
        value = self.emit()[5]
        value['identity'] = digest(b'other')
        with self.assertRaisesRegex(DevError, 'identity-or-size'): runtime.validate(value)
        with self.assertRaises(DevError): runtime.read(b'x' * (runtime.MAX_BYTES + 1))

    def test_missing_original_runtime_or_wit_inputs_fails_before_emission(self):
        for keep in ('runtime', 'wit'):
            files, graph = inputs()
            files = {name: raw for name, raw in files.items()
                     if not (name.endswith('.wit') if keep == 'runtime' else name.startswith(runtime.PREFIXES['rust']))}
            with self.subTest(keep=keep), self.assertRaisesRegex(DevError, 'required'):
                runtime.emit(self.output, 'rust', runtime.PROFILES['rust'], files, inventory(files), COMPONENT,
                    materials(), graph=graph, binding_digest=BINDINGS, configuration={})

    def context(self, language='rust'):
        output, files, graph, configuration, material, value = self.emit(language, 'unknown')
        report = compatibility.report(language, digest(inventory(files)), digest(COMPONENT),
            'lsf-host-abi-phase3-v5', [], [compatibility.finding('unresolved-behavior', 'initialization', 'not-evaluated')])
        report_raw = encode(report); (output / 'compatibility-report.json').write_bytes(report_raw)
        selected = builder.finish(output, files, inventory(files), COMPONENT, materials() + [material])
        return output, files, material, value, selected, report_raw

    def test_current_owner_selection_context_preserves_immutable_report_and_unqualified_state(self):
        for language in runtime.PROFILES:
            with self.subTest(language=language):
                output, files, material, value, selected, original = self.context(language)
                self.assertEqual((output / 'compatibility-report.json').read_bytes(), original)
                self.assertEqual(selected['standardRuntime']['receiptName'], 'standard-runtime-selection.json')
                self.assertEqual(selected['standardRuntime']['ownerIssue'], runtime.OWNER_ISSUES[language])
                self.assertEqual(selected['standardRuntime']['state'], 'selected-unqualified')
                self.assertEqual((selected['reachability'], selected['initialization'], selected['workerDrain']),
                                 ('unknown', 'unknown', 'unproven'))
                original_runtime = next(row for row in selected['materials'] if row['name'] == 'selected-runtime-original')
                self.assertEqual(original_runtime['digest'], value['originalRuntimeInputsDigest'])
                self.assertIn('#' + str(runtime.OWNER_ISSUES[language]), context.present(selected))

    def test_context_rejects_source_identical_receipt_with_stale_tools(self):
        output, files, material, value, _, _ = self.context()
        current = materials(); current[1]['digest'] = digest(b'new compiler')
        with self.assertRaisesRegex(DevError, 'stale-tool-or-recipe'):
            builder.finish(output, files, inventory(files), COMPONENT, current + [material])

    def test_actual_outcome_context_rejects_mutated_owner_receipt(self):
        output, files, material, value, selected, _ = self.context()
        (output / 'source-inputs.json').write_bytes(inventory(files))
        descriptor = {'artifacts': {'component': output.name + '/component.wasm'}}
        accepted = {'source': digest(b'frontend source'), 'artifacts': {'component': digest(COMPONENT)}}
        capture = outcomes.from_build(self.output, descriptor, accepted)
        self.assertEqual(capture.context_state, 'observed')
        value['profile'] = 'planned-async-profile'; rehash(value)
        (output / 'standard-runtime-selection.json').write_bytes(encode(value))
        failed = outcomes.from_build(self.output, descriptor, accepted)
        self.assertEqual(failed.context_state, 'invalid-present')
        failed.observe('original', {'category': 'platform-failure', 'outcomeKnown': True,
                                  'error': {'code': 'guest-trap'}}, False)
        self.assertEqual(failed.snapshot()['cases'][0]['cause'], 'unknown')

    def test_generator_kind_uses_reviewed_material_name_without_signed_role(self):
        output, files, material, value, _, _ = self.context()
        # Re-emit after an additional actual input is captured, preserving the
        # signed three-field shape; an arbitrary similarly suffixed name is not
        # treated as the maintained generator record.
        for name, expected in (('rust-generator-inputs', 'compiler'), ('java-generator-inputs', 'generated')):
            rows = materials() + [{'name': name, 'digest': digest(b'generated identity'), 'size': 18}]
            (output / 'standard-runtime-selection.json').unlink()
            item = runtime.emit(output, 'rust', runtime.PROFILES['rust'], files, inventory(files), COMPONENT,
                rows, graph=inputs(package='unknown')[1], binding_digest=BINDINGS, configuration={})
            (output / 'compatibility-context.json').unlink()
            selected = builder.finish(output, files, inventory(files), COMPONENT, rows + [item])
            self.assertEqual(next(row for row in selected['materials'] if row['name'] == name)['kind'], expected)


class MaintainedRecipeOwnership(unittest.TestCase):
    def test_runtime_receipt_helper_is_captured_in_all_six_transitive_owner_recipes(self):
        from tools import rust_capsule_build, c_capsule_build, java_capsule_build, go_capsule_build
        from tools.dotnet_guest import build as dotnet
        from tools.typescript_guest import build as typescript
        for owner in (rust_capsule_build, c_capsule_build, java_capsule_build, go_capsule_build, dotnet, typescript):
            with self.subTest(owner=owner.__name__):
                self.assertIn('tools/guest_runtime_receipts.py', owner.RECIPE)
                self.assertIn('tools/dev_workflow/dependencies.py', owner.RECIPE)

    def test_four_owner_hooks_follow_input_rechecks_and_precede_completed_observation(self):
        for name in ('rust_capsule_build.py', 'go_capsule_build.py', 'c_capsule_build.py', 'typescript_guest/build.py'):
            raw = (ROOT / 'tools' / name).read_text(encoding='utf-8')
            tree = ast.parse(raw)
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
            emitted = [node for node in calls if ast.unparse(node.func) == 'guest_runtime_receipts.emit']
            self.assertEqual(len(emitted), 1)
            rechecks = [node.lineno for node in calls if ast.unparse(node.func).endswith('.check_unchanged')]
            self.assertTrue(rechecks and max(rechecks) < emitted[0].lineno)
            completion = [node.lineno for node in calls if ast.unparse(node.func) == 'write_json'
                          and any(isinstance(part, ast.Constant) and part.value == 'BUILD-COMPLETE.json'
                                  for argument in node.args for part in ast.walk(argument))]
            self.assertEqual(len(completion), 1); self.assertLess(emitted[0].lineno, completion[0])
            self.assertIn("'tools/guest_runtime_receipts.py'", raw)

    def test_reviewed_generator_materials_use_closed_signed_shape_in_all_four_builders(self):
        for name in ('go_capsule_build.py', 'c_capsule_build.py', 'java_capsule_build.py', 'typescript_guest/build.py'):
            tree = ast.parse((ROOT / 'tools' / name).read_text(encoding='utf-8'))
            rows = [node for node in ast.walk(tree) if isinstance(node, ast.Dict)
                    and any(isinstance(item, ast.Constant) and item.value in
                            {'go-generator-inputs', 'c-generator-inputs', 'java-generator-inputs', 'typescript-generator-inputs'}
                            for item in node.values)]
            self.assertEqual(len(rows), 1)
            self.assertEqual({key.value for key in rows[0].keys}, {'name', 'digest', 'size'})


if __name__ == '__main__': unittest.main()
