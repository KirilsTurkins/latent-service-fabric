"""Evidence parsing and isolated discovery controls; no JVM execution is claimed."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_java_amplifier as probe
from tools.phase2_operator_process import WorkflowError


def marker(mode, generated, files, size):
    return (f'CHECKPOINT_AMPLIFIER_PROBE {mode} PASS generated={str(generated).lower()} '
        f'outputFiles={files} outputBytes={size}\n'
        f'CHECKPOINT_AMPLIFIER_SPLIT PASS {mode}\n').encode('ascii')


class AmplifierEvidence(unittest.TestCase):
    def test_each_selected_case_requires_its_own_complete_verdict(self):
        for mode in probe.MODES:
            positive = mode in probe.POSITIVE
            with self.subTest(mode=mode):
                raw = marker(mode, positive, int(positive), int(positive))
                result = probe.check_result(mode, raw)
                self.assertEqual(result['generatedC'], positive)
                self.assertEqual(result['mode'], mode)
                with self.assertRaises(WorkflowError):
                    probe.check_result(mode, marker(mode, not positive, 0, 0))
                for invalid in (raw.splitlines(keepends=True)[0], raw + b'other output\n',
                        raw.replace(b' PASS ', b' SKIP ', 1), raw.replace(mode.encode(), b'unknown', 1)):
                    with self.assertRaisesRegex(WorkflowError, 'java-amplifier-control-marker'):
                        probe.check_result(mode, invalid)

    def test_refusal_cannot_claim_any_generated_output(self):
        for files, size in ((1, 0), (0, 1), (1, 1)):
            with self.subTest(files=files, size=size), self.assertRaisesRegex(
                    WorkflowError, 'java-amplifier-control-output-bound'):
                probe.check_result('plugin-intrinsic', marker('plugin-intrinsic', False, files, size))

    def test_generated_output_must_remain_inside_both_bounds(self):
        limit = 64 * 1024 * 1024
        result = probe.check_result('inclusive', marker('inclusive', True, 99999, limit))
        self.assertEqual(result['bytes'], limit)
        for files, size in ((0, 1), (1, 0), (100000, 1), (1, limit + 1)):
            with self.subTest(files=files, size=size), self.assertRaisesRegex(
                    WorkflowError, 'java-amplifier-control-output-bound'):
                probe.check_result('inclusive', marker('inclusive', True, files, size))

    def test_unknown_non_ascii_and_oversized_markers_are_refused(self):
        with self.assertRaisesRegex(WorkflowError, 'java-amplifier-control-mode'):
            probe.check_result('unreviewed', marker('unreviewed', False, 0, 0))
        for raw in (b'\xff', b'x' * 513):
            with self.subTest(raw=raw[:8]), self.assertRaisesRegex(
                    WorkflowError, 'java-amplifier-control-marker'):
                probe.check_result('pass', raw)

    def test_service_discovery_is_confined_to_a_fresh_model_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / 'model'
            model.mkdir()
            original = b'compiled fixture placeholder'
            (model / 'Fixture.class').write_bytes(original)
            descriptor = probe.prepare_plugin_model(model, root / 'plugin-model')
            self.assertFalse((model / 'META-INF').exists())
            self.assertEqual((model / 'Fixture.class').read_bytes(), original)
            self.assertEqual((descriptor.parents[2] / 'Fixture.class').read_bytes(), original)
            self.assertEqual(descriptor.read_text(),
                'org.teavm.platform.plugin.AmplifierPluginControl\n')
            with self.assertRaises(FileExistsError):
                probe.prepare_plugin_model(model, root / 'plugin-model')
        self.assertIn(probe.PLUGIN, probe.observed_sources())

    def test_failed_preparation_retains_failed_receipt_without_execution_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'observation'
            with patch.object(probe, 'acquire', side_effect=WorkflowError('test-acquisition-failure')):
                with self.assertRaisesRegex(WorkflowError, 'test-acquisition-failure'):
                    probe.qualify(output)
            report = json.loads((output / 'result.json').read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertFalse(report['componentExecutionPerformed'])
            self.assertFalse(report['guestExecutionPerformed'])
            self.assertEqual(report['controls'], [])


if __name__ == '__main__':
    unittest.main()
