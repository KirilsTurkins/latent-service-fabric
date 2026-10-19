"""Raw C resource projection, explicit C23 flags and unchanged input authority."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import application_dependencies as dependencies, c_capsule_project as project
from tools import c_compiled_resource_fixture as fixture, c_resource_inputs as resources, guest_resources
from tools.build_snapshot import canonical, digest
from tools.c_guest import language
from tools.c_guest.compiler import Compiler
from tools.rust_capsule_build import package_inputs
from tools.rust_capsule_project import inventory


class CompiledResources(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory(); self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)

    def closure(self, metadata=None, *, format='directory', extra=()):
        app = project.create(self.root / 'project', 'greeting')
        outside = self.root / 'outside'; outside.mkdir()
        for name, payload in fixture.PAYLOADS.items(): (outside / name).write_bytes(payload)
        artifact = {'id': 'outside-owner/raw-resource/1', 'role': 'resource', 'format': format,
            'mount': 'dependencies/raw/data.bin' if format == 'file' else 'dependencies/raw',
            'source': {'path': '../outside/data.bin' if format == 'file' else '../outside'},
            'dependencies': [], 'metadata': {'resources': list(fixture.DECLARATIONS)} if metadata is None else metadata}
        declaration = {'formatVersion': 1, 'language': 'c', 'selection': {'target': 'wasm32-wasi'},
                       'nativeLocks': [], 'artifacts': [artifact, *extra], 'transformations': []}
        (app / dependencies.MANIFEST).write_bytes(canonical(declaration))
        (app / dependencies.LOCK).write_bytes(canonical(dependencies.capture(app)))
        for path in outside.iterdir(): path.unlink()
        outside.rmdir()
        work, output = self.root / 'work', self.root / 'output'
        work.mkdir(); output.mkdir()
        closure = dependencies.prepare(app, work, output, 'c')
        return app, project.snapshot(app), closure, output

    def test_outside_raw_resources_become_exact_content_addressed_dependency_layers(self):
        app, files, closure, output = self.closure()
        selected = resources.selected(closure, files)
        self.assertEqual(len(selected.rows), 4)
        self.assertEqual(len(selected.sources), 3)
        self.assertEqual(selected.directories, (closure.work / 'dependencies/raw',))
        self.assertEqual(selected.observation['runtimeFilesystem'], 'not-installed')
        self.assertEqual(selected.sources['dependencies/raw/message.txt'], 'Gr\u00fc\u00dfe'.encode())
        self.assertEqual(selected.sources['dependencies/raw/data.bin'], bytes((0, 255, 65, 128)))
        self.assertEqual(selected.sources['dependencies/raw/empty.bin'], b'')
        source = inventory(files); (output / 'source-inputs.json').write_bytes(source)
        value, _, _ = project.validate(files)
        package_inputs(output, value, {'imports': [], 'exports': []}, {**files, **selected.sources},
                       b'controlled component identity, not execution', additional_resources=selected.rows)
        index = json.loads((output / guest_resources.INDEX).read_bytes())
        objects = {row['object']: (output / row['object']).read_bytes() for row in index['resources']}
        verified = guest_resources.verify((output / guest_resources.INDEX).read_bytes(), objects,
            source_digest=digest(source), component_digest=digest(b'controlled component identity, not execution'),
            dependency_lock_digest=digest(files[dependencies.LOCK]), dependency_lock=files[dependencies.LOCK])
        self.assertEqual((verified['count'], len(objects)), (4, 3))
        self.assertTrue(all(row['origin'] == 'dependency' for row in verified['resources']))
        self.assertFalse((app.parent / 'outside').exists())
        closure.check_unchanged()

    def test_explicit_file_and_existing_single_fragment_declarations_retain_original_bytes(self):
        app, files, closure, _ = self.closure({'logicalPath': 'data/raw.bin', 'mediaType': 'application/octet-stream'}, format='file')
        selected = resources.selected(closure, files)
        self.assertEqual(selected.rows[0]['path'], 'data/raw.bin')
        self.assertEqual(list(selected.sources.values()), [fixture.PAYLOADS['data.bin']])
        self.assertEqual(selected.directories, ((closure.work / 'dependencies/raw/data.bin').parent,))
        from tools.c_application_dependencies import selected as compiler_inputs
        inputs = compiler_inputs(closure, compiler_digest=digest(b'compiler'), runtime_digest=digest(b'runtime'))
        self.assertEqual((inputs.sources, inputs.archives, inputs.defines), ((), (), ()))
        self.assertEqual(inputs.receipt['artifacts'][0]['resource']['digest'], digest(fixture.PAYLOADS['data.bin']))
        closure.check_unchanged()

    def test_no_declaration_does_not_invent_resource_assets_or_select_other_captured_files(self):
        _, files, closure, _ = self.closure({'includeDirectories': ['.'], 'license': 'MIT'})
        selected = resources.selected(closure, files)
        self.assertEqual((selected.rows, selected.sources, selected.directories), ((), {}, ()))
        self.assertEqual(resources.selected(None, {}).observation, {'formatVersion': 1, 'resources': []})
        self.assertIsNone(guest_resources.select(files))

    def test_malformed_declarations_missing_members_and_path_escapes_fail_closed(self):
        cases = (None, {}, [True], [{'path': 'data/x', 'source': '../data.bin', 'mediaType': 'text/plain'}],
                 [{'path': 'data/x', 'source': 'missing', 'mediaType': 'text/plain'}],
                 [{'path': 'data/x', 'source': 'data.bin', 'mediaType': 'text/plain; private=x'}],
                 [{**fixture.DECLARATIONS[0], 'hostPath': '/etc/passwd'}])
        for index, declarations in enumerate(cases):
            with self.subTest(declarations=declarations), tempfile.TemporaryDirectory() as temporary:
                previous = self.root; self.root = Path(temporary)
                try:
                    _, files, closure, _ = self.closure({'resources': declarations})
                    with self.assertRaises(guest_resources.ResourceError): resources.selected(closure, files)
                finally: self.root = previous

    def test_application_dependency_and_case_alias_collisions_share_the_existing_profile_fence(self):
        _, files, closure, _ = self.closure()
        files[guest_resources.MANIFEST] = canonical({'schemaVersion': guest_resources.PROFILE, 'resources': [
            {'path': 'DATA/utf8.txt', 'source': 'asset.txt', 'mediaType': 'text/plain'}]})
        files['asset.txt'] = b'private application bytes'
        with self.assertRaisesRegex(guest_resources.ResourceError, 'collision'):
            resources.selected(closure, files)

    def test_lock_object_and_materialized_byte_changes_cannot_supply_a_resource(self):
        _, files, closure, _ = self.closure()
        changed = dict(files); changed[dependencies.LOCK] += b'\n'
        with self.assertRaisesRegex(guest_resources.ResourceError, 'source-lock-binding'):
            resources.selected(closure, changed)
        closure.lock['selection']['extra'] = 'not in bytes'
        with self.assertRaisesRegex(guest_resources.ResourceError, 'lock-mutated'):
            resources.selected(closure, files)
        del closure.lock['selection']['extra']
        path = closure.work / 'dependencies/raw/data.bin'; original = path.read_bytes()
        path.write_bytes(b'changed bytes')
        with self.assertRaisesRegex(guest_resources.ResourceError, 'captured-bytes-changed'):
            resources.selected(closure, files)
        path.write_bytes(original)
        closure.check_unchanged()

    def test_resource_bounds_are_checked_before_opening_oversized_captured_payloads(self):
        _, files, closure, _ = self.closure()
        with patch.object(guest_resources, 'MAX_FILE', 3), patch('tools.c_resource_inputs.read_bytes', side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(guest_resources.ResourceError, 'resource-byte-limit'):
                resources.selected(closure, files)
        with patch.object(guest_resources, 'MAX_COUNT', 3):
            with self.assertRaisesRegex(guest_resources.ResourceError, 'resource-count-limit'):
                resources.selected(closure, files)
        with patch.object(guest_resources, 'MAX_TOTAL', 1):
            with self.assertRaisesRegex(guest_resources.ResourceError, 'resource-byte-limit'):
                resources.selected(closure, files)

    def test_c23_is_explicit_and_project_dependency_modes_cannot_disagree(self):
        from tools.c_dependency_authoring import manifest
        from tools.application_dependency_store import DependencyError
        self.assertEqual(language.selected_standard({}), 'c11')
        self.assertEqual(language.selected_standard({'languageStandard': 'c23'}), 'c23')
        for mode in (None, True, [], {}, 'gnu23', '-include=/secret'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'unsupported-c-language-standard'):
                language.selected_standard({'languageStandard': mode})
            with self.assertRaisesRegex(DependencyError, 'language-standard-not-installed'):
                manifest({'formatVersion': 1, 'language': 'c', 'selection': {'languageStandard': mode},
                          'nativeLocks': [], 'artifacts': [], 'transformations': []})
        for mode in ('c11', None, True):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'selection-mismatch'):
                language.selected_standard({'languageStandard': 'c23'}, {'selection': {'languageStandard': mode}})

    def test_c23_flags_and_embed_roots_apply_to_both_compilation_and_dependency_observation(self):
        source = self.root / 'source.c'; source.write_text('int value;')
        compiler = Compiler.__new__(Compiler)
        compiler.sdk, compiler.platform, compiler.commands = project.ROOT / 'sdk/c-guest', None, None
        compiler.isolation = SimpleNamespace(receipt={}, observe_inputs=lambda path: [])
        compiler.validate_static_libraries = lambda *args: None; compiler.check_unchanged = lambda: None
        calls = []; compiler.run = lambda *args: calls.append(args) or ''
        def generate(run, wit, world, destination, platform):
            destination.mkdir(); return destination, {}
        with patch('tools.c_guest.compiler.generate', generate):
            compiler.compile([source], self.root / 'wit', 'service', self.root / 'compiled',
                language_standard='c23', embed_directories=(self.root,))
        commands = [row for row in calls if row[0] == 'zig']
        self.assertGreaterEqual(len(commands), 2)
        for row in commands:
            self.assertIn('-std=c23', row)
            self.assertIn('--embed-dir=' + str(self.root), row)
            self.assertNotIn('--embed-dir', row)
        with self.assertRaisesRegex(ValueError, 'bounded-c23'):
            compiler.compile([source], self.root, 'service', self.root / 'closed', embed_directories=(self.root,))

    def test_outside_transitive_fixture_keeps_standard_embed_and_exact_raw_package_selection(self):
        app = project.create(self.root / 'project', 'greeting')
        before_sdk = (app / 'sdk-lock.json').read_bytes()
        proof = fixture.prepare(app)
        self.assertTrue(proof['originalsRemoved'])
        files = project.snapshot(app); value, _, _ = project.validate(files)
        self.assertEqual(value['languageStandard'], 'c23')
        self.assertEqual((app / 'sdk-lock.json').read_bytes(), before_sdk)
        self.assertNotIn('runtimeProfile', value)
        work, output = self.root / 'work', self.root / 'output'; work.mkdir(); output.mkdir()
        closure = dependencies.prepare(app, work, output, 'c')
        selected = resources.selected(closure, files)
        self.assertEqual(len(selected.rows), 4)
        body = (work / 'dependencies/compiled-library/compiled_resource.c').read_bytes()
        self.assertIn(b'#embed "data.bin"', body)
        self.assertIn(b'#embed "message.txt"', body)
        self.assertIn(b'__has_embed("missing.bin")', body)
        self.assertNotIn(b'latent_', body)
        self.assertNotIn(b'fopen(', body)
        self.assertEqual(closure.lock['artifacts'][0]['dependencies'], ['outside-owner/raw-resource/1'])
        closure.check_unchanged()

    def test_signed_probe_keeps_exact_results_original_fuel_and_physical_sample_boundaries(self):
        def observe(*, reaped=True, fuel=10_000_000):
            success = lambda name, expected: {'activation': name, 'exitCode': 0, 'processReaped': True,
                'decoded': [{'ok': expected}], 'response': {'outcomeKnown': True}}
            failure = lambda name, code: {'activation': name, 'exitCode': 4, 'processReaped': reaped,
                'response': {'outcomeKnown': True, 'error': {'code': code}, 'data': {
                    'terminalState': code.replace('-', '_'), 'consumption': {
                        'peakMemoryBytes': '262144', 'cpuFuel': str(fuel)}}}}
            replies = [success(name, expected) for name, expected in fixture.CASES]
            for mode, code in (('trap', 'guest-trap'), ('fuel', 'resource-exhausted')):
                replies.extend((failure(mode, code), success(mode + '-fresh', fixture.CASES[0][1])))
            result = {'invocations': [], 'providerIdle': [], 'samples': []}
            with patch('tools.rust_capsule_node.call', side_effect=replies) as calls, \
                    patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                    patch('tools.rust_capsule_node.sample', return_value={}) as samples:
                fixture.probe(None, {'budget': {'cpuFuel': 100_000_000, 'memoryBytes': 2 * 1024 * 1024}},
                              None, result, 5)
            return result, calls, samples
        result, calls, samples = observe()
        self.assertEqual(len(result['invocations']), 10)
        self.assertEqual([row['case'] for row in result['cCompiledResourceCases']], [name for name, _ in fixture.CASES])
        self.assertEqual([row['case'] for row in result['cCompiledResourceRecovery']], ['trap', 'fuel'])
        self.assertEqual(samples.call_count, 10)
        self.assertEqual(len(result['providerIdle']), 6)
        for index in (6, 8):
            self.assertEqual(calls.call_args_list[index].args[1]['budget']['cpuFuel'], 10_000_000)
        with self.assertRaisesRegex(RuntimeError, 'failure-shape'): observe(reaped=False)
        with self.assertRaisesRegex(RuntimeError, 'original-fuel-bound'): observe(fuel=9_999_999)

    def test_emitted_c_parameters_match_the_closed_signer_schema_for_both_standards(self):
        import ast
        import inspect
        from jsonschema import Draft202012Validator, ValidationError
        from tools import c_capsule_build
        tree = ast.parse(inspect.getsource(c_capsule_build.build))
        observations = [node.args[1] for node in ast.walk(tree) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == 'write_json' and node.args
            and isinstance(node.args[0], ast.BinOp) and isinstance(node.args[0].right, ast.Constant)
            and node.args[0].right.value == 'build-observation.json']
        self.assertEqual(len(observations), 1)
        fields = {key.value: value for key, value in zip(observations[0].keys, observations[0].values)}
        schema = json.loads((project.ROOT / 'schemas/build-observation.schema.json').read_bytes())
        c_schema = next(row['then']['properties']['parameters'] for row in schema['allOf']
            if row['if']['properties']['buildType']['const'] == c_capsule_build.BUILD_TYPE)
        validator = Draft202012Validator(c_schema)
        for standard in ('c11', 'c23'):
            # Read the actual producer's wire-map without executing compiler code.
            parameters = {key.value: standard if isinstance(value, ast.Name) and value.id == 'language_standard'
                          else ast.literal_eval(value) for key, value in zip(fields['parameters'].keys, fields['parameters'].values)}
            validator.validate(parameters)
            with self.assertRaises(ValidationError):
                validator.validate({**parameters, 'languageStandard': standard})
        config = [node for node in ast.walk(tree) if isinstance(node, ast.keyword) and node.arg == 'configuration']
        self.assertEqual(len(config), 1)
        self.assertIn('languageStandard', [key.value for key in config[0].value.keys])

    def test_compiled_resource_execution_flag_cannot_enable_another_language_or_facility_profile(self):
        from tools.run_rust_capsule_workflow import run
        for language_name, flag, others in (('java', True, {}), ('c', 1, {}), ('c', True, {'c_standard_combined': True})):
            output = self.root / 'must-not-exist'
            with self.subTest(language=language_name, flag=flag, others=others), self.assertRaisesRegex(RuntimeError, 'c-compiled-resources-language'):
                run(Path('missing'), Path('missing'), Path('missing'), output,
                    language=language_name, c_compiled_resources=flag, **others)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
