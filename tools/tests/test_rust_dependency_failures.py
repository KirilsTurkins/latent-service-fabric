"""Only actual retained core and exact native import support FFI attribution."""
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools import guest_compatibility as compatibility
from tools import rust_dependency_failures as suite
from tools.rust_capsule_project import write_json


class RustDependencyFailures(unittest.TestCase):
    def fixture(self, root):
        raw = b'\x00asm\x01\x00\x00\x00'
        source = b'{}'
        (root / 'raw-core.wasm').write_bytes(raw)
        (root / 'source-inputs.json').write_bytes(source)
        write_json(root / 'BUILD-FAILED.json', {'stage': 'component'})
        observation = {'formatVersion': 1, 'stage': 'component', 'sourceDigest': suite.digest(source),
            'coreDigest': suite.digest(raw), 'coreBytes': len(raw), 'state': 'retained-original-compiler-output', 'authority': 'none'}
        write_json(root / 'raw-core-observation.json', observation)
        report = compatibility.report('rust', suite.digest(source), None, 'test-profile', [],
            [compatibility.finding('unresolved-behavior', 'link', 'not-evaluated')])
        write_json(root / 'compatibility-report.json', report)
        commands = Mock()
        commands.run.return_value = b'(module (import "env" "outside_native_cpu" (func (result i32))))'
        artifact = {'id': 'outside/1', 'original': {'digest': 'sha256:' + 'a' * 64}}
        return observation, commands, artifact

    def test_attribution_uses_exact_core_and_preserves_generic_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, commands, artifact = self.fixture(root)
            original = (root / 'compatibility-report.json').read_bytes()
            result = suite.inspect_failure(root, commands, root / 'wasm-tools', artifact)
            self.assertEqual(result['classification'], 'target-incompatible')
            self.assertEqual(result['authority'], 'none')
            self.assertEqual(result['originalGenericStatus'], 'incomplete')
            self.assertEqual((root / 'compatibility-report.json').read_bytes(), original)
            observed = compatibility.read((root / 'ffi-compatibility-report.json').read_bytes())
            self.assertIsNone(observed['componentDigest'])
            self.assertEqual(observed['findings'][0]['symbol'], suite.SYMBOL)
            self.assertEqual(observed['findings'][0]['packageDigest'], artifact['original']['digest'])
            commands.run.assert_called_once_with('inspect-actual-native-core', root / 'wasm-tools',
                'print', root / 'raw-core.wasm', '--skeleton')

    def test_stale_wrong_stage_and_missing_native_import_do_not_classify(self):
        for kind in ('source', 'core', 'stage', 'success', 'symbol'):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); observation, commands, artifact = self.fixture(root)
                if kind == 'source': (root / 'source-inputs.json').write_bytes(b'{"changed":true}')
                if kind == 'core': (root / 'raw-core.wasm').write_bytes(b'\x00asm\x01\x00\x00\x00changed')
                if kind == 'stage':
                    (root / 'BUILD-FAILED.json').unlink()
                    write_json(root / 'BUILD-FAILED.json', {'stage': 'compile'})
                if kind == 'success': write_json(root / 'BUILD-COMPLETE.json', {})
                if kind == 'symbol': commands.run.return_value = b'(module (import "other" "outside_native_cpu" (func)))'
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    suite.inspect_failure(root, commands, root / 'wasm-tools', artifact)
                self.assertFalse((root / 'ffi-compatibility-report.json').exists())

    def test_changed_core_during_inspection_cannot_publish_finding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, commands, artifact = self.fixture(root)
            def changed(*args):
                (root / 'raw-core.wasm').write_bytes(b'\x00asm\x01\x00\x00\x00changed')
                return b'(import "env" "outside_native_cpu" (func))'
            commands.run.side_effect = changed
            with self.assertRaisesRegex(ValueError, 'changed during inspection'):
                suite.inspect_failure(root, commands, root / 'wasm-tools', artifact)
            self.assertFalse((root / 'ffi-compatibility-report.json').exists())

    def test_unreviewed_tool_request_stops_before_ffi_compile_and_restores_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); project = root / 'app'; (project / 'src').mkdir(parents=True)
            before = b'outside_qualification_library::exercise(&name);'
            (project / 'src/lib.rs').write_bytes(before)
            verified = SimpleNamespace(identity='original', lock={'artifacts': [{
                'id': 'outside/1', 'metadata': {'package': 'outside-qualification-library'}}],
                'executableInputs': ['reviewed-tool/1']})
            def request(_project, output, *_args, **_kwargs):
                output.mkdir(parents=True)
                write_json(output / 'BUILD-FAILED.json', {'stage': 'executable-input-approval'})
                write_json(output / 'executable-input-approval-request.json', {'identity': 'changed',
                    'specification': {'executableInputs': [{'id': 'unreviewed-tool/1'}]}})
                raise ValueError('exact approval required')
            with patch.object(suite, 'verify_inputs', return_value=verified), \
                    patch.object(suite.compiler, 'build', side_effect=request) as build, \
                    patch.object(suite, 'inspect_failure') as inspect:
                with self.assertRaisesRegex(ValueError, 'executable input selection changed'):
                    suite.qualify(project, root / 'out', root / 'contracts', root / 'package', root / 'wasm-tools', Mock())
            self.assertEqual((project / 'src/lib.rs').read_bytes(), before)
            self.assertEqual(build.call_count, 1)
            inspect.assert_not_called()

    def test_actual_outside_fixture_declares_native_symbol_as_unimplemented_wasm_import(self):
        import json
        from tools import rust_dependency_fixture as fixture

        class NativeBoundaryReached(RuntimeError):
            pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'; (project / 'src').mkdir(parents=True)
            descriptor = {'limits': {'wallTimeLimitMillis': 1000},
                          'capabilities': [], 'unchanged': {'authority': 'none'}}
            (project / 'capsule-project.json').write_text(json.dumps(descriptor), encoding='utf-8')
            (project / 'src/lib.rs').write_bytes(
                b'pub fn greet(name: String) { Ok(format!("Hello, {name}!")) }')
            with patch.object(fixture.cargo_native_authoring, 'author', side_effect=NativeBoundaryReached) as native:
                with self.assertRaises(NativeBoundaryReached):
                    fixture.install(project, root / 'outside', root / 'unavailable-cargo')
            native.assert_called_once()
            self.assertEqual(native.call_args.kwargs['identity'], 'unicode-normalization')
            source = (root / 'outside/developer-owned-library/src/lib.rs').read_text()
            declaration = ('#[cfg_attr(target_arch = "wasm32", link(wasm_import_module = "env"))]\n'
                           'extern "C" { fn outside_native_cpu() -> u32; }')
            self.assertEqual(source.count(declaration), 1)
            self.assertEqual(source.count('outside_native_cpu() -> u32;'), 1)
            self.assertIn('pub fn native_value() -> u32 { unsafe { outside_native_cpu() } }', source)
            self.assertNotIn('fn outside_native_cpu() -> u32 {', source)
            self.assertEqual(json.loads((project / 'capsule-project.json').read_bytes()),
                             {**descriptor, 'limits': {'wallTimeLimitMillis': 5000}})
