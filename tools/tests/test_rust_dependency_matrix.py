"""Source/receipt controls; these tests never run Cargo or a native guest."""
import copy
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import application_dependencies as dependencies
from tools import qualify_rust_dependency_matrix as campaign
from tools import rust_dependency_matrix as matrix
from tools import run_rust_capsule_workflow as workflow
from tools.application_dependency_store import DependencyError, Store
from tools.build_snapshot import canonical, digest
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import create, inventory, snapshot


class MatrixSources(unittest.TestCase):
    def test_coordinates_versions_resources_and_feature_selections_vary_without_reference_lookup(self):
        a = matrix.specification('abcdef0123456789abcdef01', 0, 0)
        b = matrix.specification('123456789abcdef012345678', 1, 1)
        self.assertFalse(set(a['packages'].values()) & set(b['packages'].values()))
        self.assertNotEqual(a['version'], b['version'])
        self.assertNotEqual(a['marker'], b['marker'])
        self.assertNotEqual(matrix.expected(a, matrix.INPUTS[0]), matrix.expected(b, matrix.INPUTS[0]))
        self.assertEqual(matrix.INPUTS[0], matrix.INPUTS[-1])
        self.assertEqual(a['selection'], {'features': [], 'allFeatures': False, 'noDefaultFeatures': False})
        self.assertEqual(b['selection'], {'features': ['switched'], 'allFeatures': False, 'noDefaultFeatures': True})

    def test_specification_rejects_unknown_fields_bool_ordinals_and_mutated_nested_values(self):
        good = matrix.specification('0' * 24, 0, 0)
        for field, value in (('formatVersion', True), ('phase', True), ('graph', 3), ('nonce', 'credential-secret'),
                             ('version', '9.9.9'), ('packages', {}), ('marker', [True]), ('selection', {})):
            with self.subTest(field=field):
                bad = {**good, field: value}
                with self.assertRaises(WorkflowError):
                    matrix.validate(bad)
        with self.assertRaises(WorkflowError):
            matrix.validate({**good, 'arbitraryCommand': 'never'})

    def test_emitted_crates_use_actual_no_std_alloc_std_resources_and_target_dependencies(self):
        spec = matrix.specification('abcdef0123456789abcdef01', 0, 0)
        files = matrix.sources(spec)
        self.assertIn(b'#![no_std]', files['patch-0/src/lib.rs'])
        self.assertIn(b'include_bytes!("marker.bin")', files['patch-0/src/lib.rs'])
        self.assertNotEqual(files['patch-0/src/marker.bin'], files['patch-1/src/marker.bin'])
        self.assertIn(b'#![no_std]\nextern crate alloc;', files['allocated/src/lib.rs'])
        self.assertIn(b'alloc::format!', files['allocated/src/lib.rs'])
        self.assertIn(b'Vec<u8>', files['allocated/src/lib.rs'])
        self.assertIn(b'use std::sync::atomic', files['facade/src/lib.rs'])
        self.assertIn(b'include_str!("utf8.txt")', files['facade/src/lib.rs'])
        self.assertIn(b'cfg(not(target_arch = "wasm32"))', files['facade/Cargo.toml'])
        self.assertIn(b'cfg(target_arch = "wasm32")', files['facade/Cargo.toml'])
        self.assertIn(b'activation state reused', files['facade/src/lib.rs'])

    def test_real_project_feature_and_patch_edits_preserve_sdk_descriptor_and_normal_greeting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create(root / 'app', 'greeting')
            before = snapshot(project)
            spec = matrix.specification('0' * 24, 0, 0)
            matrix.edit(project, root / 'outside', spec)
            initial = snapshot(project)
            matrix.edit(project, root / 'outside', matrix.specification('0' * 24, 0, 1))
            after = snapshot(project)
            self.assertEqual(before['sdk-lock.json'], after['sdk-lock.json'])
            self.assertEqual(before['capsule-project.json'], after['capsule-project.json'])
            self.assertEqual(initial['src/lib.rs'], after['src/lib.rs'])
            self.assertIn(b'Ok(format!("Hello, {name}!"))', after['src/lib.rs'])
            self.assertIn(b'cfg!(feature="switched")', after['src/lib.rs'])
            self.assertNotEqual(initial['Cargo.toml'], after['Cargo.toml'])
            self.assertIn(b'patch-1', after['Cargo.toml'])
            self.assertEqual(set(name for name in before if before[name] != after[name]), {'Cargo.toml', 'src/lib.rs'})

    def test_originals_can_be_restored_for_explicit_authoring_and_removed_again_before_each_build(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / 'owned-originals'
            for phase in (0, 1):
                spec = matrix.specification('0' * 24, 0, phase)
                recorded = matrix.restore(outside, spec)
                self.assertEqual(recorded['facade/src/lib.rs'], digest(matrix.sources(spec)['facade/src/lib.rs']))
                matrix.remove(outside, spec)
                self.assertFalse(outside.exists())

    def test_modified_or_foreign_original_directory_refuses_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / 'owned-originals'
            spec = matrix.specification('0' * 24, 0, 0)
            matrix.restore(outside, spec)
            (outside / 'facade/src/lib.rs').write_bytes(b'mutated')
            with self.assertRaisesRegex(WorkflowError, 'owner-mismatch'):
                matrix.remove(outside, spec)
            self.assertTrue(outside.is_dir())


class MinimalRecipe(unittest.TestCase):
    def test_real_minimal_recipe_imports_normal_cli_without_optional_qualification_or_catalogues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'minimal'
            recorded = campaign.stage_recipe(root)
            campaign.check_recipe(root, recorded)
            self.assertEqual(set(recorded['files']), {'tools/__init__.py', *campaign.RECIPE, *campaign.SEEDS})
            self.assertFalse(any('qualif' in name or name.startswith('docs/') or name.startswith('target/')
                                 for name in recorded['files']))
            result = subprocess.run([sys.executable, '-I', '-B', str(root / 'tools/rust_capsule.py'), '--help'],
                                    capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b'review-lock', result.stdout)
            campaign.check_recipe(root, recorded)

    def test_added_optional_catalogue_or_modified_recipe_refuses_before_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'minimal'
            recorded = campaign.stage_recipe(root)
            (root / 'catalogue.json').write_bytes(b'{}')
            commands = Mock()
            with self.assertRaisesRegex(WorkflowError, 'minimal-recipe-mutated'):
                campaign.Frontend(root, recorded, commands).call('not-executed', '--help')
            commands.run.assert_not_called()
            (root / 'catalogue.json').unlink()
            (root / 'tools/rust_capsule.py').write_bytes(b'changed')
            with self.assertRaisesRegex(WorkflowError, 'minimal-recipe-mutated'):
                campaign.Frontend(root, recorded, commands).call('not-executed', '--help')
            commands.run.assert_not_called()

    def test_frontend_always_selects_exact_staged_cli_isolated_no_bytecode_and_rechecks_after(self):
        commands = Mock()
        commands.run.return_value = b'normal-result'
        with patch.object(campaign, 'check_recipe') as check:
            result = campaign.Frontend(Path('/minimal'), {'identity': 'bound'}, commands).call('capture', 'resolve', '/app')
        self.assertEqual(result, b'normal-result')
        commands.run.assert_called_once_with('capture', sys.executable, '-I', '-B',
                                             Path('/minimal/tools/rust_capsule.py'), 'resolve', '/app')
        self.assertEqual(check.call_count, 2)


class CapturedMatrix(unittest.TestCase):
    def setUp(self):
        self.value = matrix.specification('abcdef0123456789abcdef01', 0, 0)
        self.lock = {'selection': {**self.value['selection'], 'target': 'wasm32-unknown-unknown',
                     'runtimeProfile': 'wasm32-unknown-unknown-panic-abort-v1'}, 'executableInputs': [], 'artifacts': []}
        self.graph = {'root': 'root', 'nodes': [], 'selectedResolve': {'root': 'root', 'nodes': [
            {'id': 'root', 'features': ['default', 'matrix-default'], 'deps': [{'pkg': 'facade'}]}]}}
        files = matrix.sources(self.value)
        for role, name in self.value['packages'].items():
            directory = 'patch-0' if role == 'core' else role
            dependencies = ['core'] if role == 'allocated' else ['allocated', 'native'] if role == 'facade' else []
            self.lock['artifacts'].append({'id': role, 'role': 'application', 'dependencies': dependencies,
                'treeDigest': digest(role.encode()), 'metadata': {'package': name, 'version': self.value['version']},
                'files': [{'path': path.removeprefix(directory + '/'), 'digest': digest(raw), 'size': len(raw)}
                          for path, raw in files.items() if path.startswith(directory + '/')]})
            self.graph['nodes'].append({'id': role, 'artifact': role})
            if role != 'native':
                self.graph['selectedResolve']['nodes'].append({'id': role,
                    'features': ['default', 'baseline'] if role == 'facade' else [], 'deps': []})

    def test_exact_selected_graph_binds_three_dependency_profiles_target_and_resources(self):
        result = matrix.captured(self.lock, self.graph, self.value)
        self.assertEqual(set(result), {'core', 'allocated', 'facade', 'native'})
        self.assertEqual(result['core']['treeDigest'], digest(b'core'))

    def test_alternate_root_and_dependency_features_require_the_new_captured_patch_bytes(self):
        alternate = matrix.specification(self.value['nonce'], 0, 1)
        self.lock['selection'].update(alternate['selection'])
        for node in self.graph['selectedResolve']['nodes']:
            if node['id'] == 'root':
                node['features'] = ['switched']
            elif node['id'] == 'facade':
                node['features'] = ['alternate']
        with self.assertRaisesRegex(WorkflowError, 'source-or-resource-mismatch'):
            matrix.captured(self.lock, self.graph, alternate)
        row = next(item for item in self.lock['artifacts'] if item['id'] == 'core')
        marker = next(item for item in row['files'] if item['path'] == 'src/marker.bin')
        marker['digest'] = digest(bytes(alternate['marker']))
        result = matrix.captured(self.lock, self.graph, alternate)
        self.assertEqual(result['allocated']['artifact'], 'allocated')

    def test_unpruned_native_dependency_does_not_count_as_wasm_target_evidence(self):
        self.graph['selectedResolve']['nodes'].append({'id': 'native', 'features': [], 'deps': []})
        with self.assertRaisesRegex(WorkflowError, 'target-pruning'):
            matrix.captured(self.lock, self.graph, self.value)

    def test_wrong_dependency_or_root_features_cannot_borrow_an_unrelated_success(self):
        for index in (0, 3):
            with self.subTest(index=index):
                graph = copy.deepcopy(self.graph)
                graph['selectedResolve']['nodes'][index]['features'] = ['unselected']
                with self.assertRaisesRegex(WorkflowError, 'features-not-observed'):
                    matrix.captured(self.lock, graph, self.value)

    def test_resource_or_core_preimage_drift_refuses_actual_capture_claim(self):
        for role, path in (('core', 'src/marker.bin'), ('facade', 'src/utf8.txt'), ('allocated', 'src/lib.rs')):
            with self.subTest(role=role):
                lock = copy.deepcopy(self.lock)
                row = next(item for item in lock['artifacts'] if item['id'] == role)
                next(item for item in row['files'] if item['path'] == path)['digest'] = digest(b'forged')
                with self.assertRaisesRegex(WorkflowError, 'source-or-resource-mismatch'):
                    matrix.captured(lock, self.graph, self.value)

    def test_missing_application_edges_or_executable_inputs_refuse(self):
        self.lock['artifacts'][1]['dependencies'] = []
        with self.assertRaisesRegex(WorkflowError, 'transitive-edges'):
            matrix.captured(self.lock, self.graph, self.value)
        self.lock['executableInputs'] = ['unapproved']
        with self.assertRaisesRegex(WorkflowError, 'selection-not-observed'):
            matrix.captured(self.lock, self.graph, self.value)

    def test_missing_package_or_wrong_version_cannot_be_inferred_from_coordinate_label(self):
        self.lock['artifacts'][0]['metadata']['version'] = '9.9.9'
        with self.assertRaisesRegex(WorkflowError, 'actual-package-required'):
            matrix.captured(self.lock, self.graph, self.value)


class RealIntegrityControls(unittest.TestCase):
    def test_failed_diagnostic_write_preserves_original_exception_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            original = ValueError('original-qualification-failure')
            with patch.object(campaign, 'prepared_inputs', side_effect=original), \
                    patch.object(campaign, 'write_json', side_effect=RuntimeError('observer-failure')):
                with self.assertRaises(ValueError) as caught:
                    campaign.qualify(Path(directory) / 'prepared', Path(directory) / 'failed')
            self.assertIs(caught.exception, original)

    def test_failure_receipt_keeps_only_closed_stage_and_error_class_without_private_text(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'failed'
            with patch.object(campaign, 'prepared_inputs', side_effect=ValueError('private-secret-source-path')):
                with self.assertRaisesRegex(ValueError, 'private-secret-source-path'):
                    campaign.qualify(Path(directory) / 'prepared', output)
            raw = (output / 'FAILED.json').read_bytes()
            self.assertNotIn(b'private-secret-source-path', raw)
            receipt = json.loads(raw)
            self.assertEqual(receipt['stage'], 'prepared-inputs')
            self.assertEqual(receipt['errorCategory'], 'ValueError')
            self.assertEqual(receipt['completedObservations'], 0)

    def test_missing_and_tampered_transitive_objects_refuse_and_valid_original_is_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            value = matrix.specification('0' * 24, 0, 0)
            source = project / 'outside'
            (source / 'src').mkdir(parents=True)
            (source / 'src/marker.bin').write_bytes(bytes(value['marker']))
            manifest = {'formatVersion': 1, 'language': 'rust', 'selection': value['selection'], 'nativeLocks': [],
                'transformations': [], 'artifacts': [{'id': 'core', 'role': 'application', 'format': 'directory',
                'mount': 'dependencies/core', 'source': {'path': str(source)}, 'dependencies': [],
                'metadata': {'package': value['packages']['core'], 'version': value['version']}}]}
            (project / dependencies.MANIFEST).write_bytes(canonical(manifest))
            lock = dependencies.capture(project)
            (project / dependencies.LOCK).write_bytes(canonical(lock))
            before = dependencies.verify_inputs(project, 'rust').identity
            observed = campaign.integrity_controls(project, lock, value)
            self.assertEqual([row['reason'] for row in observed], ['dependency-artifact-missing-resolve-explicitly',
                                                                 'dependency-artifact-integrity'])
            self.assertTrue(all(not row['compilerExecution'] for row in observed))
            self.assertEqual(dependencies.verify_inputs(project, 'rust').identity, before)

    def test_stale_review_is_not_retried_or_promoted_and_unexpected_error_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / 'candidate.json'
            candidate.write_bytes(b'{}')
            with patch.object(campaign.review, 'review', side_effect=DependencyError('dependency-native-lock-drift')) as review:
                self.assertEqual(campaign.refuse_stale(Path('/app'), candidate), 'dependency-native-lock-drift')
                review.assert_called_once_with(Path('/app'), candidate, digest(b'{}'))
            with patch.object(campaign.review, 'review', return_value={}):
                with self.assertRaisesRegex(ValueError, 'was-accepted'):
                    campaign.refuse_stale(Path('/app'), candidate)
            with patch.object(campaign.review, 'review', side_effect=DependencyError('credential-secret')):
                with self.assertRaisesRegex(WorkflowError, 'unexpected-stale-review-error'):
                    campaign.refuse_stale(Path('/app'), candidate)


class SignedProbe(unittest.TestCase):
    def setUp(self):
        self.value = matrix.specification('abcdef0123456789abcdef01', 0, 0)
        self.target = {'publication': 'owned-publication', 'generation': '2', 'name': 'my-greeting'}
        self.client = Mock()
        self.pin = {'publicationId': 'owned-publication', 'routeGeneration': '18',
                    'releaseDigest': 'sha256:component', 'revisionId': 'revision:owned'}
        self.client.call.return_value = {'data': {'snapshot': {'generation': '18', 'services': [
            {'routeId': 'my-greeting', 'revisions': [self.pin]}]}}}
        self.result = {'invocations': [], 'samples': [], 'providerIdle': []}
        self.rows = [{'activation': str(index), 'exitCode': 0, 'decoded': [{'ok': matrix.expected(self.value, text)}],
                      'processReaped': True, 'response': {'category': 'success', 'outcomeKnown': True,
                      'data': {'consumption': {'outboundRequests': 0}, 'resolvedRevision': dict(self.pin)}}}
                     for index, text in enumerate(matrix.INPUTS)]
        self.enterContext(patch.object(matrix, 'sample', return_value={'owned': True}))
        self.enterContext(patch.object(matrix, 'provider_idle', return_value={'owned': True}))

    def test_dynamic_non_ascii_calls_and_fresh_repeat_are_bound_to_actual_selected_publication(self):
        with patch.object(matrix, 'call', side_effect=self.rows) as call:
            matrix.probe(self.client, self.target, Mock(), self.result, 5, self.value)
        self.assertEqual(call.call_count, 3)
        self.assertEqual(self.result['rustDependencyMatrix']['specificationDigest'], digest(canonical(self.value)))
        self.assertEqual(self.result['rustDependencyMatrix']['cases'][0], self.result['rustDependencyMatrix']['cases'][2])
        self.assertEqual(len(self.result['providerIdle']), 3)

    def test_baseline_greeting_or_old_patch_component_cannot_pass_matrix_probe(self):
        for answer in ('Hello, Ada!', matrix.expected(matrix.specification(self.value['nonce'], 0, 1), matrix.INPUTS[0])):
            with self.subTest(answer=answer):
                rows = copy.deepcopy(self.rows)
                rows[0]['decoded'] = [{'ok': answer}]
                with patch.object(matrix, 'call', side_effect=rows):
                    with self.assertRaises(WorkflowError):
                        matrix.probe(self.client, self.target, Mock(), self.result, 5, self.value)

    def test_wrong_revision_unreaped_or_unexpected_outbound_never_count_as_success(self):
        for mutate in (lambda row: row.update(processReaped=False),
                       lambda row: row['response']['data']['resolvedRevision'].update(publicationId='foreign'),
                       lambda row: row['response']['data']['resolvedRevision'].update(routeGeneration='2'),
                       lambda row: row['response']['data']['resolvedRevision'].update(releaseDigest='foreign'),
                       lambda row: row['response']['data']['resolvedRevision'].update(revisionId='foreign'),
                       lambda row: row['response']['data']['consumption'].update(outboundRequests=1)):
            with self.subTest(mutate=mutate):
                rows = copy.deepcopy(self.rows)
                mutate(rows[0])
                with patch.object(matrix, 'call', side_effect=rows):
                    with self.assertRaises(WorkflowError):
                        matrix.probe(self.client, self.target, Mock(), self.result, 5, self.value)

    def test_selector_defaults_off_and_invalid_language_type_or_combination_refuses_before_effects(self):
        self.assertIs(inspect.signature(workflow.run).parameters['captured_rust_matrix'].default, False)
        with patch.object(workflow, 'fresh') as fresh:
            for options in ({'captured_rust_matrix': 1}, {'captured_rust_matrix': True, 'language': 'c'},
                            {'captured_rust_matrix': True, 'rust_compatibility': True},
                            {'captured_rust_matrix': True, 'captured_git_component': True}):
                with self.subTest(options=options), self.assertRaisesRegex(WorkflowError, 'Rust-matrix-language'):
                    workflow.run(Path('cli'), Path('node'), Path('fixture'), Path('evidence'), **options)
            fresh.assert_not_called()


class SignedOrchestration(unittest.TestCase):
    def test_exact_normal_staged_build_and_signed_component_are_required_before_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'app'
            project.mkdir()
            (project / 'source.rs').write_bytes(b'public-source')
            output = root / 'attempt'
            output.mkdir()
            spec = matrix.specification('0' * 24, 0, 0)
            recipe = {'tools/rust_capsule.py': {'digest': digest(b'recipe'), 'size': 6}}
            frontend, commands = Mock(), Mock()
            frontend.observed = {'files': recipe}
            marker = {'componentDigest': digest(b'actual-component')}
            products = {name: root / name.replace('/', '-') for name in
                        ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')}
            def compile_only(*args):
                built = output / 'build'
                built.mkdir()
                for name, value in (('cargo-inputs.json', {'networkResolution': False}),
                                    ('recipe-inputs.json', recipe), ('BUILD-COMPLETE.json', marker)):
                    (built / name).write_bytes(canonical(value))
            frontend.call.side_effect = compile_only
            def sign_only(*args):
                (output / 'signed').mkdir()
            commands.run.side_effect = sign_only
            def node_only(*args, **kwargs):
                self.assertEqual(kwargs, {'language': 'rust', 'captured_rust_matrix': True})
                self.assertEqual(json.loads((output / 'signed/matrix-probe.json').read_bytes()), spec)
                (output / 'node').mkdir()
                (output / 'node/workflow.json').write_bytes(b'{}')
                return {'status': 'passed', 'rustDependencyMatrix': {'status': 'passed',
                    'specificationDigest': digest(canonical(spec)), 'cases': [{}, {}, {}]},
                    'releaseSet': {'releases': [{'name': 'my-greeting', **marker}]}}
            with patch.object(campaign, 'run', side_effect=node_only):
                result = campaign.signed_probe(frontend, project, output, root / 'prepared', products, commands, spec)
            self.assertEqual(result['build'], marker)
            args = frontend.call.call_args.args
            self.assertEqual(args[:4], ('offline-component', 'build', project, '--output'))
            self.assertIn('--offline', args)
            self.assertIn(products['examples/capsule_contracts'], args)
            self.assertIn(products['examples/package'], args)
            self.assertEqual(commands.run.call_args.args[:3],
                             ('sign-matrix-fixture', products['examples/capsule_authoring'], 'demo-sign'))


class NativePatchRelocation(unittest.TestCase):
    def prepared(self, directory, outside_name='owned originals'):
        from tools import rust_application_dependencies as native
        root = Path(directory)
        project = create(root / 'app', 'greeting')
        outside = root / outside_name
        value = matrix.specification('a' * 24, 0, 0)
        matrix.edit(project, outside, value)
        manifest = project / 'Cargo.toml'
        # This is the same maintained relocation function used by native
        # authoring when it brings Cargo's manifest back from the owned mirror.
        path = (outside / 'patch-0').resolve(strict=False)
        raw = native.selected_manifest(manifest.read_bytes(), manifest, manifest, {path: path})
        manifest.write_bytes(raw)
        return project, outside, value, raw

    def test_actual_native_relative_path_can_advance_only_the_owned_core_patch(self):
        import os
        import tomllib
        with tempfile.TemporaryDirectory(prefix='matrix native path ') as directory:
            project, outside, value, raw = self.prepared(directory)
            before = snapshot(project)
            expected = tomllib.loads(raw.decode())
            name = value['packages']['core']
            self.assertFalse(Path(expected['patch']['crates-io'][name]['path']).is_absolute())
            matrix.edit(project, outside, matrix.specification(value['nonce'], 0, 1))
            actual = tomllib.loads((project / 'Cargo.toml').read_text(encoding='utf-8'))
            expected['patch']['crates-io'][name]['path'] = os.path.relpath(outside / 'patch-1', project).replace('\\', '/')
            self.assertEqual(actual, expected)
            self.assertEqual({p for p in before if before[p] != snapshot(project)[p]}, {'Cargo.toml'})

    def test_foreign_relative_patch_refuses_without_changing_source_or_sdk(self):
        import tomllib
        with tempfile.TemporaryDirectory() as directory:
            project, outside, value, raw = self.prepared(directory)
            selected = tomllib.loads(raw.decode())['patch']['crates-io'][value['packages']['core']]['path']
            changed = raw.replace(json.dumps(selected).encode(), b'"../foreign/patch-0"')
            (project / 'Cargo.toml').write_bytes(changed)
            before = snapshot(project)
            with self.assertRaisesRegex(WorkflowError, 'matrix-original-patch-required'):
                matrix.edit(project, outside, matrix.specification(value['nonce'], 0, 1))
            self.assertEqual(snapshot(project), before)

    def test_native_unicode_relative_path_retains_normal_toml_identity(self):
        import tomllib
        with tempfile.TemporaryDirectory(prefix='matrix \u00e4 path ') as directory:
            project, outside, value, raw = self.prepared(directory, 'owned \u00e4 originals')
            before = tomllib.loads(raw.decode())
            name = value['packages']['core']
            self.assertIn('\u00e4', before['patch']['crates-io'][name]['path'])
            matrix.edit(project, outside, matrix.specification(value['nonce'], 0, 1))
            after = tomllib.loads((project / 'Cargo.toml').read_text(encoding='utf-8'))
            actual = (project / after['patch']['crates-io'][name]['path']).resolve(strict=False)
            self.assertEqual(actual, (outside / 'patch-1').resolve(strict=False))
            after['patch']['crates-io'][name]['path'] = before['patch']['crates-io'][name]['path']
            self.assertEqual(after, before)

    def test_ambiguous_duplicate_string_preimage_refuses_instead_of_rewriting_comments(self):
        import tomllib
        with tempfile.TemporaryDirectory() as directory:
            project, outside, value, raw = self.prepared(directory)
            selected = tomllib.loads(raw.decode())['patch']['crates-io'][value['packages']['core']]['path']
            (project / 'Cargo.toml').write_bytes(raw + b'\n# duplicate ' + json.dumps(selected).encode() + b'\n')
            before = snapshot(project)
            with self.assertRaisesRegex(WorkflowError, 'matrix-original-patch-required'):
                matrix.edit(project, outside, matrix.specification(value['nonce'], 0, 1))
            self.assertEqual(snapshot(project), before)

    def test_extra_patch_fields_or_coordinate_refuse_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            project, outside, value, raw = self.prepared(directory)
            for changed in (raw + b'\n[patch.crates-io.foreign]\npath="../foreign"\n',
                            raw.replace(b' = {path = ', b' = {version="1.0.0", path = ')):
                (project / 'Cargo.toml').write_bytes(changed)
                before = snapshot(project)
                with self.subTest(changed=changed[-100:]), self.assertRaisesRegex(WorkflowError, 'matrix-original-patch-required'):
                    matrix.edit(project, outside, matrix.specification(value['nonce'], 0, 1))
                self.assertEqual(snapshot(project), before)


if __name__ == '__main__':
    unittest.main()
