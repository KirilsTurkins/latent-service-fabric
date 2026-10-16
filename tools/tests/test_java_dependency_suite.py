"""Source admission controls; actual compiler/node qualification stays hosted."""
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import qualify_java_dependency_suite as suite
from tools.phase2_operator_process import WorkflowError


class JavaDependencySuite(unittest.TestCase):
    def test_every_tracked_tool_including_non_python_inputs_is_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'tools').mkdir()
            (root / 'tools/owner.py').write_bytes(b'owned Python source')
            asset = root / 'tools/model-input.json'
            asset.write_bytes(b'{"revision":1}')
            commands = SimpleNamespace(run=lambda *args: b'tools/owner.py\0tools/model-input.json\0')
            with patch.object(suite, 'ROOT', root), patch.object(suite, 'inputs', return_value={'sdk': 'fixed'}):
                before = suite.source_inputs(commands)
                asset.write_bytes(b'{"revision":2}')
                after = suite.source_inputs(commands)
            self.assertEqual(set(before['trackedTools']), {'tools/owner.py', 'tools/model-input.json'})
            self.assertNotEqual(before, after)
            self.assertEqual(before['maintainedJavaInputs'], after['maintainedJavaInputs'])

    def test_unsafe_ambiguous_and_unbounded_lists_fail_before_any_file_read(self):
        for raw in (b'', b'outside.py\0', b'tools/../outside.py\0', b'tools/one.py\0tools/one.py\0',
                    b'\0'.join(('tools/f%d' % i).encode() for i in range(8193))):
            commands = SimpleNamespace(run=lambda *args: raw)
            with self.subTest(bytes=len(raw)), patch.object(suite, 'file_identity') as identity:
                with self.assertRaisesRegex(WorkflowError, 'tracked-input-bound'):
                    suite.source_inputs(commands)
                identity.assert_not_called()

    def test_source_inventory_has_its_own_bounded_writer_above_operator_fixture_size(self):
        value = {'trackedTools': {'tools/source-%04d.py' % i: {
            'sha256': 'sha256:' + '1' * 64, 'bytes': 4096} for i in range(3000)}}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'source-inputs.json'
            suite.write_source_inventory(output, value)
            self.assertGreater(output.stat().st_size, 262144)
            self.assertEqual(suite.json.loads(output.read_bytes()), value)
            oversized = Path(temporary) / 'oversized.json'
            with self.assertRaisesRegex(WorkflowError, 'source-inventory-byte-bound'):
                suite.write_source_inventory(oversized, {'unbounded': 'x' * (8 * 1024 * 1024)})
            self.assertFalse(oversized.exists())

    def test_checkout_outputs_fail_before_creating_attempt_or_starting_native(self):
        for output in (suite.ROOT, suite.ROOT / 'new-attempt'):
            with self.subTest(output=output), patch.object(suite, 'fresh') as fresh, patch.object(suite, 'native') as native:
                with self.assertRaisesRegex(WorkflowError, 'output-must-be-outside-checkout'):
                    suite.main(['--output', str(output), '--wasi-sdk', 'unused', '--mode', 'recovery'])
                fresh.assert_not_called()
                native.assert_not_called()

    def test_missing_or_unknown_selected_programme_has_no_fallback_or_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'checkout'
            root.mkdir()
            with patch.object(suite, 'ROOT', root), patch.object(suite, 'fresh') as fresh, patch.object(suite, 'native') as native:
                with self.assertRaisesRegex(WorkflowError, 'selected-programme-missing'):
                    suite.main(['--output', str(Path(temporary) / 'output'), '--wasi-sdk', 'unused', '--mode', 'private'])
                with patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit) as stopped:
                    suite.main(['--output', str(Path(temporary) / 'output'), '--wasi-sdk', 'unused', '--mode', 'other'])
                self.assertEqual(stopped.exception.code, 2)
                fresh.assert_not_called()
                native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
