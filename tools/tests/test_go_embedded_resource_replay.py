"""Closed historical source reuse controls, without executing native binaries."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import yaml

from tools import replay_go_embedded_resources as replay
from tools.rust_capsule_project import ROOT


class GoEmbeddedReplay(unittest.TestCase):
    def test_only_exact_unused_helper_and_one_reviewed_test_postimage_are_compatible(self):
        original = {'runtime':replay.ORIGINAL_RUNTIME,'sdk':{'exact':'sdk'},'wit':{'exact':'wit'},
            'helpers':{replay.HELPER:replay.producer.ORIGINAL_HELPER,'used-helper':{'exact':'used'}}}
        current = copy.deepcopy(original)
        current['runtime'] = replay.STARTUP_TEST_RUNTIME
        current['helpers'][replay.HELPER] = replay.RESOURCE_HELPER
        observed = replay.compatible_source(original,current)
        self.assertFalse(observed['currentNativeCompilationClaimed'])
        self.assertFalse(observed['normalReceiptRelabelled'])
        for mode in ('sdk','wit','used-helper','unreviewed-helper','runtime'):
            changed = copy.deepcopy(current)
            if mode in {'sdk','wit'}: changed[mode] = {'substituted':'source'}
            elif mode == 'used-helper': changed['helpers'][mode] = {'substituted':'source'}
            elif mode == 'unreviewed-helper': changed['helpers'][replay.HELPER]['bytes'] += 1
            else: changed['runtime']['sha256'] = 'sha256:'+'0'*64
            with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError,'embedded-Go-'):
                replay.compatible_source(original,changed)

    def test_original_source_is_verified_before_any_retained_product_can_be_selected(self):
        original = {'runtime':replay.ORIGINAL_RUNTIME,'helpers':{replay.HELPER:replay.producer.ORIGINAL_HELPER}}
        current = {'runtime':replay.STARTUP_TEST_RUNTIME,'helpers':{replay.HELPER:replay.RESOURCE_HELPER}}
        calls = [{'activation':'normal-'+str(index)} for index in range(27)]
        node = {'invocations':calls,'samples':[{}]*20,'providerIdle':[{}]*6}
        def read(path,*_args):
            return original if path.name == 'source-inputs.json' else node
        with patch.object(replay,'read_json',side_effect=read), patch.object(replay,'current_inputs',return_value=current), \
                patch.object(replay,'_prepared_with_inputs',return_value=({'five':'binaries'},{'four':'companions'},{'original':'ancestry'})) as checked:
            result = replay.selected(Path('never-executed'))
            checked.assert_called_once_with(Path('never-executed'),'go',original)
            self.assertEqual(result[2]['normalActivations'],[row['activation'] for row in calls])
            self.assertEqual(result[2]['physicalSamples'],20)
        current = copy.deepcopy(current); current['runtime']['bytes'] += 1
        with patch.object(replay,'read_json',return_value=original), patch.object(replay,'current_inputs',return_value=current), \
                patch.object(replay,'_prepared_with_inputs') as checked, self.assertRaisesRegex(RuntimeError,'closed-source'):
            replay.selected(Path('never-executed'))
        checked.assert_not_called()

    def test_input_free_twenty_minute_lane_restores_exact_normal_products_without_building_a_host(self):
        document = yaml.safe_load((ROOT/'.github/workflows/go-embedded-resource-reference.yml').read_bytes())
        events = document.get('on',document.get(True))
        self.assertEqual(events['workflow_dispatch'],None)
        self.assertEqual(events['push']['branches'],['diagnostic/go-embedded-resources-20261020'])
        self.assertNotIn('pull_request',events)
        self.assertEqual(document['permissions'],{'contents':'read','actions':'read'})
        self.assertEqual(set(document['jobs']),{'resources'})
        job = document['jobs']['resources']; self.assertEqual(job['timeout-minutes'],20)
        steps = job['steps']
        download = next(step for step in steps if step.get('uses','').startswith('actions/download-artifact@'))
        self.assertEqual(download['with']['run-id'],39373374237)
        self.assertEqual(download['with']['name'],'go-scratch-prepared-'+replay.producer.PRODUCER_HEAD)
        commands = '\n'.join(step.get('run','') for step in steps)
        self.assertNotIn('-p latentd',commands)
        self.assertNotIn('qualify_rust_capsules.py',commands)
        self.assertIn('--record-producer',commands)
        self.assertIn('--producer-receipt',commands)
        self.assertIn('ecbadb99091a3f46e31f5f934b068b1864eafa7995211b39eaddf76996045fe5',commands)
        producer_index = next(index for index,step in enumerate(steps) if '--record-producer' in step.get('run',''))
        self.assertLess(producer_index,steps.index(download))


if __name__ == '__main__': unittest.main()
