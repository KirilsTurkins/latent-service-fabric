"""Diagnostic acquisition keeps frozen native ancestry and current BCL source distinct."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools import replay_dotnet_filesystem as replay
from tools.rust_capsule_project import write_json


class DotnetFilesystemReplay(unittest.TestCase):
    def test_historical_acquisition_static_input_closure_is_present_with_its_exact_original_hash(self):
        record = replay.original.expected_original_inputs()
        self.assertEqual(set(record), {'runtime', 'sdk', 'wit', 'schemas', 'guide', 'helpers'})
        self.assertGreater(len(record['helpers']), 40)

    def test_production_source_guard_checks_recipe_sdk_wit_and_all_current_fixture_inputs(self):
        with patch.object(replay.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'')) as checked, \
                patch.object(replay.subprocess, 'check_output', side_effect=[b'', b'fixture-source\n']):
            record = replay.production_inputs()
        self.assertTrue(record['currentProductionInputsEqual'])
        self.assertEqual(record['productionSource'], replay.PRODUCTION)
        self.assertEqual(record['fixtureSource'], 'fixture-source')
        command = checked.call_args.args[0]
        self.assertIn('sdk/dotnet-guest', command)
        self.assertIn('wit', command)
        self.assertIn('tools/dotnet_guest/closed_filesystem.py', command)
        self.assertIn('tools/sdk_scratch_probe.py', command)

    def test_dirty_checkout_or_changed_production_input_denies_before_acquisition(self):
        for changed, status in ((True, b''), (False, b'?? unexpected-source\n')):
            with self.subTest(changed=changed), \
                    patch.object(replay.subprocess, 'run', return_value=SimpleNamespace(returncode=int(changed), stdout=b'changed' if changed else b'')), \
                    patch.object(replay.subprocess, 'check_output', return_value=status), \
                    self.assertRaisesRegex(RuntimeError, 'filesystem-replay-'):
                replay.production_inputs()

    def test_material_adapter_preserves_original30_and_fresh_baseline27_without_native_rebinding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); prepared, host = root / 'prepared', root / 'host'
            prepared.mkdir(); host.mkdir(); (prepared / 'node').mkdir()
            products = {}
            for name in replay.original.PRODUCTS:
                path = prepared / name.replace('/', '-')
                path.write_bytes(('original-' + name).encode()); products[name] = path
            (host / 'latentd').write_bytes(b'original75-host')
            companions = {name: prepared / 'builds' / name for name in replay.original.COMPANIONS}
            for path in companions.values():
                path.mkdir(parents=True); write_json(path / 'BUILD-COMPLETE.json', {'original': True})
            write_json(prepared / 'node/workflow.json', {'invocations': [{} for _ in range(30)]})
            write_json(prepared / 'retrieval.json', {'originalReceiptRewritten': False})
            selected = {'artifact': 100, 'archiveDigest': 'fixed-archive', 'run': replay.acquisition.RUN,
                'job': replay.acquisition.JOB, 'compiledSource': replay.acquisition.SOURCE,
                'binary': {'original': True}, 'sourceIdentity': {'frozen': True}}
            write_json(host / 'host-retrieval.json', selected)
            with patch.object(replay, 'production_inputs', return_value={'productionSource': replay.PRODUCTION}), \
                    patch.object(replay.original, 'verify_prepared', return_value=(None, {'node': {'receiptDigest': 'old-node'}}, products)), \
                    patch.object(replay.acquisition, 'origin', return_value={'id': 100, 'digest': 'fixed-archive'}), \
                    patch.object(replay.acquisition, 'validate', return_value={'binary': {'original': True}}), \
                    patch.object(replay.acquisition.historical, 'git_source_identity', return_value={'frozen': True}):
                binaries, observed_companions, record = replay.observed(prepared, host)
            self.assertEqual(record['historicalOriginalNode']['invocations'], 30)
            self.assertEqual(record['currentProgrammeBaseInvocations'], 27)
            self.assertEqual(binaries['latentd'], host / 'latentd')
            self.assertEqual(observed_companions, companions)
            self.assertFalse(record['currentNormalReceiptFabricated'])
            self.assertFalse(record['nativeHostRebuilt'])
            self.assertEqual(products['latentd'].read_bytes(), b'original-latentd')

    def test_manual_lane_is20_minutes_and_preserves_all_three_original_job_bodies(self):
        from tools.ci_lane_inventory import workflow_model
        model = workflow_model((replay.ROOT / '.github/workflows/dotnet-guest.yml').read_text())
        original = workflow_model(replay.subprocess.check_output(
            ['git', 'show', replay.PRODUCTION + ':.github/workflows/dotnet-guest.yml'],
            cwd=replay.ROOT, timeout=30).decode('utf-8'))
        selector = model['on']['workflow_dispatch']['inputs']['closed_filesystem_replay']
        self.assertEqual((selector['type'], selector['default']), ('boolean', False))
        for name in ('toolchain', 'scratch-refusals', 'published-tasks'):
            self.assertEqual(model['jobs'][name]['if'], "${{ github.event_name != 'workflow_dispatch' || !inputs.closed_filesystem_replay }}")
            self.assertEqual({key: value for key, value in model['jobs'][name].items()
                              if key != 'if'}, original['jobs'][name])
        projected = {**model, 'jobs': original['jobs'], 'on': {
            **model['on'], 'workflow_dispatch': original['on']['workflow_dispatch']}}
        self.assertEqual(projected, original)
        job = model['jobs']['closed-filesystem-reference']
        self.assertEqual(job['timeout-minutes'], 20)
        self.assertNotIn('needs', job)
        self.assertEqual(job['if'], "${{ github.event_name == 'workflow_dispatch' && inputs.closed_filesystem_replay }}")
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        self.assertIn('tools/replay_dotnet_filesystem.py --prepare', commands)
        self.assertIn('git fetch --no-tags --depth=1 origin 75b408ea0184936aa1dc21df2c9dd5e6c44bbc46 ' + replay.PRODUCTION, commands)
        self.assertNotIn('cargo build', commands)
        self.assertNotIn('cargo test', commands)
        self.assertIn('--tools "$RUNNER_TEMP/dotnet-authoring-tools"', commands)


if __name__ == '__main__':
    unittest.main()
