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
