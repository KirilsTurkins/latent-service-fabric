"""Cancellation fixture delivery checks, not Java or signed execution receipts."""
from pathlib import Path
from fnmatch import fnmatchcase
import json
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_lane_inventory as lanes, qualify_java_fibers as owner


class FutureCancelGuestSelection(unittest.TestCase):
    def prepare_to_boundary(self, reference='42 42 42 42'):
        class BoundaryReached(Exception):
            pass

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name) / 'prepared'
        sdk = owner.ROOT / 'sdk/java-guest'
        original = (sdk / 'fibers/conformance/timers/Capsule.java').read_bytes()
        calls = []
        test = self

        class Compiler:
            def __init__(self, directory, wasi_sdk, **options):
                self.sdk = sdk
                self.paths = {'java': Path('not-executed-java')}
                self.records = []
                calls.append(('compiler', options))

            def run(self, stage, *argv):
                calls.append((stage, argv))
                if stage == 'reference-jdk-compile':
                    test.assertIn(output / 'src/Capsule.java', argv)
                    test.assertEqual((output / 'src/Capsule.java').read_bytes(), original)
                return reference if stage.startswith('reference-jdk-') else ''

            def compile(self, source, wit, world, destination, **options):
                calls.append(('component', options))
                test.assertEqual({p.name for p in source.iterdir()}, {'Capsule.java'})
                test.assertEqual((source / 'Capsule.java').read_bytes(), original)
                test.assertEqual(world, 'tests:caller/service@1.0.0')
                test.assertEqual(options, {'activation_profile': True})
                raise BoundaryReached('stopped-before-real-component-compile')

        def control(name):
            def run(*args):
                calls.append((name, ()))
                return {'status': 'controlled-owner-not-executed'}
            return run

        with patch.object(owner, 'Compiler', Compiler), \
                patch.object(owner, 'recipe_inputs', return_value={}), \
                patch.object(owner, 'completable_source_control', side_effect=control('completable-source')), \
                patch.object(owner, 'standard_timer_source_control', side_effect=control('timer-source')), \
                patch.object(owner, 'standard_timer_model_control', side_effect=control('timer-model')):
            if reference == '42 42 42 42':
                with self.assertRaises(BoundaryReached):
                    owner.prepare(output, Path('not-executed-wasi-sdk'), fixture='timers')
            else:
                with self.assertRaisesRegex(ValueError, 'reference-JDK fiber observable mismatch'):
                    owner.prepare(output, Path('not-executed-wasi-sdk'), fixture='timers')

        receipt = json.loads((output / 'FIBERS-COMPILE.json').read_bytes())
        self.assertEqual(receipt['sourceDigest'], owner.digest(original))
        self.assertEqual(receipt['fixture'], 'timers')
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(receipt['nodeExecution'], 'not-run')
        self.assertNotIn('componentDigest', receipt)
        return calls, receipt

    def test_normal_timer_route_delivers_identical_application_to_jdk_and_guest(self):
        calls, receipt = self.prepare_to_boundary()
        stages = [stage for stage, _ in calls]
        self.assertEqual(len(receipt['reference']), 3)
        for iteration, result in enumerate(receipt['reference']):
            self.assertEqual(result, {'iteration': iteration, 'modes': [0, 1, 2, 3],
                                      'results': [42, 42, 42, 42]})
        for control in ('completable-source', 'timer-source', 'timer-model'):
            self.assertLess(stages.index(control), stages.index('component'))
        self.assertEqual(calls[0][1]['timeout'], 1200)

    def test_failed_reference_stops_before_source_controls_and_component(self):
        calls, receipt = self.prepare_to_boundary(reference='42 42 42')
        stages = {stage for stage, _ in calls}
        self.assertFalse(stages & {'completable-source', 'timer-source', 'timer-model', 'component'})
        self.assertEqual(receipt['reference'], [])

    def test_existing_workflow_selects_signed_timer_and_retains_its_actual_sources(self):
        workflow = lanes.workflow_model((owner.ROOT / '.github/workflows/java-guest-feasibility.yml').read_text())
        job = workflow['jobs']['compiler-component']
        steps = job['steps']
        by_id = {step['id']: step for step in steps if 'id' in step}
        prepared = by_id['prepare-java-standard-timers']
        signed = by_id['signed-java-standard-timers']
        self.assertIn('--fixture timers', prepared['run'])
        self.assertIn('--read-only-cache', prepared['run'])
        self.assertLess(steps.index(prepared), steps.index(signed))
        self.assertNotIn('continue-on-error', prepared)
        self.assertNotIn('continue-on-error', signed)
        self.assertEqual(signed['env']['LSF_GUEST_SDK_LANGUAGE'], 'java')
        self.assertEqual(signed['env']['LSF_JAVA_TIMER_FIXTURE'], '${{ runner.temp }}/java-standard-timers')
        self.assertIn('runtime::signed_java_standard_timers_recur_cancel_and_drain_owned_workers', signed['run'])
        self.assertIn('--ignored --exact', signed['run'])
        retained = [step for step in steps if 'java-standard-timers/FIBERS-COMPILE.json'
                    in step.get('with', {}).get('path', '')]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]['if'], 'always()')
        paths = retained[0]['with']['path'].splitlines()
        for path in ('src/Capsule.java', 'build/component.wasm', 'signed-runtime.log'):
            self.assertTrue(any(fnmatchcase('${{ runner.temp }}/java-standard-timers/' + path, pattern)
                                for pattern in paths), path)


if __name__ == '__main__':
    unittest.main()
