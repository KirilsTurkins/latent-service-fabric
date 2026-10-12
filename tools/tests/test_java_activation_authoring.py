"""Authoring selection and failed capture controls, never guest qualification."""
from pathlib import Path
import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from tools import java_capsule as cli, java_capsule_build as build, java_capsule_project as project
from tools.java_guest.compiler import Compiler
from tools.rust_capsule_project import snapshot, write_json


PROFILE = 'teavm-activation-fibers-v1'


class AuthoringSelection(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = project.create(self.root / 'application', 'greeting')
        self.output = self.root / 'output'
        (self.root / 'contracts').write_bytes(b'controlled source test input; never executed')
        self.before = snapshot(self.app)

    def invoke(self, **selection):
        return build.build(self.app, self.output, self.root / 'contracts', None,
                           'https://example.invalid/reviewed-source', self.root / 'wasi', **selection)

    def inspect_compile_boundary(self, **selection):
        observations = {}

        class ControlledCompiler:
            def __init__(owner, directory, _wasi, **options):
                observations['inputs'] = options
                owner.compiler_inputs = b'{}'
                owner.materials = []
                owner.records = []
                owner.paths = {}
                directory.mkdir()

            def compile(owner, sources, wit, world, destination, **options):
                observations['compile'] = options
                observations['sources'] = snapshot(sources)
                observations['wit'] = snapshot(wit)
                raise ValueError('controlled-before-actual-java-compilation')

        with patch.object(build, 'Compiler', ControlledCompiler):
            with self.assertRaisesRegex(ValueError, 'controlled-before-actual-java-compilation'):
                self.invoke(**selection)
        self.assertFalse((self.output / 'BUILD-COMPLETE.json').exists())
        self.assertEqual(json.loads((self.output / 'BUILD-FAILED.json').read_bytes())['stage'], 'compile')
        self.assertEqual(snapshot(self.app), self.before)
        self.assertEqual(observations['sources'], {
            name.removeprefix('src/'): raw for name, raw in self.before.items() if name.startswith('src/')})
        self.assertEqual(observations['wit'], {
            name.removeprefix('wit/'): raw for name, raw in self.before.items() if name.startswith('wit/')})
        return observations

    def test_default_builder_never_selects_activation_or_rewrites_application(self):
        result = self.inspect_compile_boundary()
        self.assertEqual(result['compile'], {'application_classpath': ()})
        self.assertNotIn('read_only_cache', result['inputs'])

    def test_explicit_selection_reaches_real_compiler_boundary_without_app_adapter(self):
        result = self.inspect_compile_boundary(runtime_profile=PROFILE)
        self.assertEqual(result['compile'], {'application_classpath': (), 'activation_profile': True})
        recipe = json.loads((self.output / 'recipe-inputs.json').read_bytes())
        self.assertIn('tools/java_guest/class_origin.py', recipe)

    def test_read_only_cache_is_selected_without_an_offline_copy(self):
        cache = self.root / 'modules-2'
        result = self.inspect_compile_boundary(runtime_profile=PROFILE, read_only_cache=cache)
        self.assertEqual(result['inputs']['read_only_cache'], cache)
        self.assertIsNone(result['inputs']['offline_cache'])
        self.assertFalse(cache.exists())

    def test_unknown_or_untyped_profile_fails_before_source_or_output(self):
        for value in ('automatic', 'teavm-activation-fibers-v2', True, 1, []):
            with self.subTest(value=value), patch.object(build, 'Compiler') as compiler:
                with self.assertRaisesRegex(ValueError, 'unsupported Java runtime profile'):
                    self.invoke(runtime_profile=value)
                compiler.assert_not_called()
                self.assertFalse(self.output.exists())
        self.assertEqual(snapshot(self.app), self.before)

    def test_mutually_exclusive_cache_modes_fail_before_source_or_output(self):
        with patch.object(build, 'Compiler') as compiler:
            with self.assertRaisesRegex(ValueError, 'mutually exclusive'):
                self.invoke(runtime_profile=PROFILE, offline_cache=self.root, read_only_cache=self.root)
        compiler.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_tampered_captured_sdk_cannot_acquire_a_profile_or_success_marker(self):
        source = self.app / 'vendor/lsf/sdk/java-guest/fibers/dev/latent/guest/runtime/Activation.java'
        source.write_bytes(source.read_bytes() + b'\n// changed after SDK capture\n')
        with patch.object(build, 'Compiler') as compiler:
            with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
                self.invoke(runtime_profile=PROFILE)
        compiler.assert_not_called()
        self.assertFalse((self.output / 'BUILD-COMPLETE.json').exists())
        self.assertEqual(json.loads((self.output / 'BUILD-FAILED.json').read_bytes())['stage'], 'capture')

    def test_source_capture_failure_keeps_original_error_and_no_success_marker(self):
        error = ValueError('source capture refused')
        with patch.object(build.guest_dependency_inputs, 'capture_source', side_effect=error), \
                patch.object(build, 'Compiler') as compiler:
            with self.assertRaises(ValueError) as caught:
                self.invoke(runtime_profile=PROFILE)
        self.assertIs(caught.exception, error)
        compiler.assert_not_called()
        failed = json.loads((self.output / 'BUILD-FAILED.json').read_bytes())
        self.assertEqual((failed['stage'], failed['reason']), ('capture', str(error)))
        self.assertFalse((self.output / 'BUILD-COMPLETE.json').exists())
        self.assertFalse((self.output / 'source-inputs.json').exists())
        self.assertEqual(snapshot(self.app), self.before)

    def test_observed_compiler_profile_must_match_explicit_selection_before_packaging(self):
        class WrongProfile:
            def __init__(owner, directory, _wasi, **options):
                owner.compiler_inputs = b'{}'
                owner.materials = []
                owner.records = []
                owner.paths = {}
                directory.mkdir()

            def compile(owner, sources, wit, world, destination, **options):
                destination.mkdir()
                (destination / 'component.wasm').write_bytes(b'controlled-not-a-real-component')
                (destination / 'bindings').mkdir()
                write_json(destination / 'runtime-profile.json', {'profile': 'unknown-profile'})
                write_json(destination / 'source-origins.json', {'sources': []})
                return destination / 'component.wasm', {}

        with patch.object(build, 'Compiler', WrongProfile), patch.object(build, 'package_inputs') as package:
            with self.assertRaisesRegex(ValueError, 'runtime profile mismatch'):
                self.invoke(runtime_profile=PROFILE)
        package.assert_not_called()
        self.assertFalse((self.output / 'BUILD-COMPLETE.json').exists())
        self.assertEqual(snapshot(self.app), self.before)


class PublicSelection(unittest.TestCase):
    @staticmethod
    def arguments():
        return ['build', 'project', '--output', 'output', '--repository', 'https://example.invalid/source',
                '--wasi-sdk', 'wasi']

    def test_public_default_preserves_existing_builder_selection(self):
        with patch.object(cli, 'build', return_value=Path('output')) as selected, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(self.arguments()), 0)
        self.assertEqual(selected.call_args.kwargs, {'gradle': 'gradle', 'offline_cache': None})

    def test_public_explicit_profile_and_read_only_cache_reach_builder(self):
        with patch.object(cli, 'build', return_value=Path('output')) as selected, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(self.arguments() + ['--runtime-profile', PROFILE, '--read-only-cache', 'modules-2']), 0)
        self.assertEqual(selected.call_args.kwargs, {'gradle': 'gradle', 'offline_cache': None,
            'runtime_profile': PROFILE, 'read_only_cache': Path('modules-2')})

    def test_unknown_public_profile_never_runs_builder(self):
        with patch.object(cli, 'build') as selected, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as rejected:
                cli.main(self.arguments() + ['--runtime-profile', 'automatic'])
        self.assertEqual(rejected.exception.code, 2)
        selected.assert_not_called()


class DeclaredRuntimeImports(unittest.TestCase):
    @staticmethod
    def graph(imports):
        interfaces, packages, selected = [], [{'name': 'tests:caller@1.0.0'}], {}
        for name in imports:
            base, _, version = name.partition('@')
            package, interface = base.split('/')
            packages.append({'name': package + '@' + version})
            interfaces.append({'name': interface, 'package': len(packages)-1, 'types': {}, 'functions': {}})
            selected[name] = {'interface': {'id': len(interfaces)-1}}
        return {'worlds': [{'name': 'service', 'package': 0, 'imports': selected, 'exports': {}}],
                'interfaces': interfaces, 'packages': packages, 'types': []}

    def invoke(self, imports, *, selected=True):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wit = root / 'wit'
            wit.mkdir()
            (wit / 'service.wit').write_bytes(b'package tests:caller@1.0.0; world service {}\n')
            compiler = Compiler.__new__(Compiler)
            compiler.platform = root / 'platform'
            compiler.platform.mkdir()
            compiler.run = lambda *args: json.dumps(self.graph(imports))
            before = snapshot(wit)
            with patch('tools.java_guest.compiler.generate', side_effect=ValueError('controlled-before-bindings')) as generated:
                with self.assertRaisesRegex(ValueError, 'controlled-before-bindings' if selected else 'requires explicit runtime'):
                    compiler.compile(root / 'sources', wit, 'tests:caller/service@1.0.0', root / 'output', activation_profile=True)
                self.assertEqual(generated.call_count, 1 if selected else 0)
            self.assertEqual(snapshot(wit), before)

    def test_declared_runtime_and_clock_reach_bindings_without_added_authority(self):
        self.invoke(('latent:runtime/activation@0.1.0', 'latent:clock/monotonic@0.1.0'))

    def test_missing_runtime_clock_or_wrong_version_never_reaches_bindings(self):
        for imports in ((), ('latent:runtime/activation@0.1.0',), ('latent:clock/monotonic@0.1.0',),
                        ('latent:runtime/activation@0.2.0', 'latent:clock/monotonic@0.1.0'),
                        ('latent:runtime/activation@0.1.0', 'latent:clock/monotonic@0.2.0')):
            with self.subTest(imports=imports):
                self.invoke(imports, selected=False)


if __name__ == '__main__':
    unittest.main()
