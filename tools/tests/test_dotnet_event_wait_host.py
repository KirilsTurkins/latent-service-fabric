"""Host probe orchestration doubles; these do not execute CLR or WASI."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import probe_dotnet_event_wait_context as probe


class DotnetEventWaitHost(unittest.TestCase):
    def exercise(self, directory: str, *, reject_receipt=False, marker_missing=False,
                 corrupt_derived=False, mutate_source=False):
        root = Path(directory)
        sdk = root / 'sdk/dotnet-guest'
        for path in ('global.json', 'nuget.config', 'probes/smoke/Smoke.csproj',
                     'probes/smoke/packages.lock.json',
                     'tests/fixtures/task-wait-finite-il-control/Program.cs'):
            target = sdk / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('fixture source: ' + path)
        original = root / 'original.dll'
        original.write_bytes(b'pinned-input-double')
        stages = []
        output = root / 'out'

        class Commands:
            def __init__(self, *args, **kwargs):
                self.records = []

            def run(self, stage, *args):
                stages.append(stage)
                self.records.append({'stage': stage, 'exitCode': 0})
                if stage == 'sdk-version':
                    return b'10.0.100\n'
                if stage.endswith('-rewrite'):
                    name = stage.removesuffix('-rewrite')
                    assembly = b'derived-double-' + name.encode()
                    Path(args[-2]).write_bytes(assembly)
                    receipt = {'outputDigest': probe.digest(assembly),
                               'aggregateTaskWait': {'fixtureOnly': name}}
                    if corrupt_derived and name == 'aggregate':
                        Path(args[-2]).write_bytes(b'changed-derived-double')
                    probe.write_json(Path(args[-1]), receipt)
                if stage == 'emitted-host-projection':
                    if mutate_source:
                        (sdk / 'tests/fixtures/task-wait-finite-il-control/Program.cs').write_text('changed')
                    markers = probe.MARKERS[:-1] if marker_missing else probe.MARKERS
                    return '\n'.join(marker + 'fixture-only' for marker in markers).encode()
                return b''

        def validate(receipt, **kwargs):
            if reject_receipt and kwargs['aggregate']:
                raise ValueError('fixture-receipt-rejection')

        with patch.object(probe, 'ROOT', root), \
                patch.object(probe, 'Commands', Commands), \
                patch.object(probe.shutil, 'which', return_value='/fixture/dotnet'), \
                patch.object(probe.http_errors, 'install'), \
                patch.object(probe.http_errors, 'verify_installed'), \
                patch.object(probe.task_wait, 'source_path', return_value=original), \
                patch.object(probe.task_wait, 'original', return_value={'fixtureOnly': True}), \
                patch.object(probe.task_wait, 'validate_current_receipt', side_effect=validate) as validator:
            try:
                result = probe.probe(output)
            except BaseException:
                self.assertFalse((output / 'HOST-COMPLETE.json').exists())
                failed = json.loads((output / 'HOST-FAILED.json').read_bytes())
                self.assertEqual(failed['status'], 'failed')
                self.assertFalse(failed['signedWasiQualified'])
                self.assertFalse(failed['nativeAotQualified'])
                raise
        return result, output, stages, validator.call_args_list

    def test_each_derivation_executes_before_one_final_receipt_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            result, output, stages, calls = self.exercise(directory)
            self.assertEqual(json.loads((output / 'receipt-validation.json').read_bytes()), {'rejected': []})
            self.assertTrue((output / 'HOST-COMPLETE.json').is_file())
            self.assertFalse((output / 'HOST-FAILED.json').exists())
            self.assertEqual([stage for stage in stages if stage.endswith('-rewrite')],
                             ['infinite-rewrite', 'finite-rewrite', 'aggregate-rewrite'])
            self.assertEqual([call.kwargs['aggregate'] for call in calls], [False, False, True])
            self.assertEqual([call.kwargs['require_finite_observation'] for call in calls], [False, True, True])
            self.assertFalse(result['signedWasiQualified'])
            self.assertFalse(result['nativeAotQualified'])

    def test_receipt_rejection_is_retained_and_cannot_be_overridden_by_host_success(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'current-receipt-rejected'):
                self.exercise(directory, reject_receipt=True)
            output = Path(directory) / 'out'
            self.assertEqual(json.loads((output / 'receipt-validation.json').read_bytes()), {'rejected': ['aggregate']})
            failed = json.loads((output / 'HOST-FAILED.json').read_bytes())
            self.assertEqual(failed['stage'], 'receipt-validation')
            self.assertIn('emitted-host-projection', [row['stage'] for row in failed['commands']])

    def test_success_receipts_do_not_replace_missing_event_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'host-completion-missing'):
                self.exercise(directory, marker_missing=True)

    def test_changed_derived_bytes_are_refused_before_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'derived-digest'):
                self.exercise(directory, corrupt_derived=True)
            failed = json.loads((Path(directory) / 'out/HOST-FAILED.json').read_bytes())
            self.assertNotIn('emitted-host-projection', [row['stage'] for row in failed['commands']])

    def test_input_recheck_prevents_completion_after_fixture_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'inputs-changed'):
                self.exercise(directory, mutate_source=True)


if __name__ == '__main__':
    unittest.main()
