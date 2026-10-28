"""Pure owner/reader admission; no Java, native or guest execution credit."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import java_fiber_library_inputs as libraries, qualify_java_fibers as preparation
from tools import qualify_java_scheduled_library as owner


def rows():
    return [{**dict.fromkeys(owner.observed.ZERO_FIELDS, 0),
        'activationId': f'java-scheduled-libraries-{index // 8}-{index % 8}',
        'iteration': index // 8, 'mode': index % 8, 'value': 42,
        'cpuFuel': 123, 'reportedPeakMemoryBytes': 4096,
        'storesBefore': index, 'storesCreated': index + 1} for index in range(16)]


def output(values):
    return ('\n'.join(['test ' + owner.CASE + ' ... ok',
        'teavm-activation-fibers-v1 signed-preparation-setup-micros=1 stores-created=0 guest-activations=0',
        *['LSF_JAVA_RETAINED=' + json.dumps(row) for row in values],
        'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 51 filtered out;']) + '\n').encode()


class ScheduledLibraryOwnership(unittest.TestCase):
    def test_all_eight_modes_twice_require_actual_unique_ids_and_fresh_idle_stores(self):
        actual = rows()
        self.assertEqual(owner.observations(output(actual))['calls'], actual)
        for field, value in (('activationId', actual[0]['activationId']), ('mode', 5),
                ('storesBefore', 0), ('liveStores', 1), ('cpuFuel', True),
                ('cpuFuel', 10_000_000_001), ('reportedPeakMemoryBytes', 64 * 1024**2 + 1)):
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(actual); bad[-1][field] = value
                with self.assertRaises(ValueError): owner.observations(output(bad))

    def test_short_old_or_skipped_programmes_cannot_be_relabelled_scheduled_pass(self):
        original = output(rows())
        variants = [output(rows()[:-1]), output(rows() + [rows()[0]]),
            original.replace(b'0 ignored', b'1 ignored'),
            original.replace(b'java-scheduled-libraries-', b'java-worker-libraries-'),
            original.replace(b'teavm-activation-fibers-v1', b'teavm-activation-fibers-io-v1'),
            original.replace(b'51 filtered out', b'50 filtered out')]
        for raw in variants:
            with self.assertRaises(ValueError): owner.observations(raw)

    def test_real_preparation_uses_normal_compiler_and_new_controls_before_component(self):
        class BeforeComponent(Exception): pass
        calls = []
        class Compiler:
            def __init__(self, directory, sdk, **options):
                self.sdk, self.paths = sdk, {'java': Path('not-executed-java')}
                calls.append(('compiler', options))
            def run(self, stage, *argv):
                calls.append((stage, argv))
                return '42 42 42 42 42 42 42 42' if stage == 'reference-jdk-0' else ''
            def compile(self, *args, **kwargs):
                calls.append(('component', kwargs))
                raise BeforeComponent()
        def control(name):
            def selected(*args): calls.append((name, ())); return {'status': 'source-control-fixture'}
            return selected
        with tempfile.TemporaryDirectory() as temporary, patch('time.monotonic', return_value=100), \
                patch.object(preparation, 'Compiler', Compiler), \
                patch.object(preparation, 'recipe_inputs', return_value={}), \
                patch.object(libraries, 'capture', return_value=((), (), {})) as captured, \
                patch.object(preparation, 'scheduled_source_control', side_effect=control('scheduled-source')), \
                patch.object(preparation, 'scheduled_model_control', side_effect=control('scheduled-model')) as model, \
                patch.object(preparation, 'completable_source_control', side_effect=AssertionError('old controls replayed')):
            path = Path(temporary) / 'prepared'
            with self.assertRaises(BeforeComponent):
                preparation.prepare(path, owner.ROOT / 'sdk/java-guest', fixture='scheduled-library', _deadline=1000)
            self.assertEqual([stage for stage, _ in calls], ['compiler', 'reference-jdk-compile', 'reference-jdk-0',
                'scheduled-source', 'component'])
            model.assert_not_called()
            self.assertEqual(captured.call_args.kwargs['_deadline'], 1000)
            self.assertEqual(calls[0][1]['_deadline'], 1000)
            self.assertEqual(calls[-1][1], {'activation_profile': True})
            self.assertEqual((path / 'src/Capsule.java').read_bytes(),
                (owner.ROOT / 'sdk/java-guest/fibers/conformance/scheduled-library/Capsule.java').read_bytes())
            self.assertEqual(json.loads((path / 'FIBERS-COMPILE.json').read_bytes())['status'], 'failed')
        with patch('time.monotonic', return_value=100), patch.object(preparation, 'fresh', side_effect=AssertionError('IO')):
            with self.assertRaisesRegex(ValueError, 'deadline'):
                preparation.prepare(Path('absent'), Path('absent'), fixture='scheduled-library', _deadline=105)

    def test_mutually_exclusive_fixture_selector_is_refused_before_output_or_capture(self):
        revision = 'a' * 40
        environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': owner.identities.REPOSITORY,
            'GITHUB_REF_NAME': owner.BRANCH, 'GITHUB_EVENT_NAME': 'push',
            'GITHUB_SHA': revision, 'GITHUB_WORKFLOW_SHA': revision, 'GITHUB_WORKSPACE': str(owner.ROOT),
            'GITHUB_WORKFLOW_REF': owner.identities.REPOSITORY + '/' + owner.WORKFLOW + '@refs/heads/' + owner.BRANCH,
            'LSF_JAVA_WORKER_LIBRARIES_FIXTURE': 'old-programme'}
        with patch.dict(os.environ, environment, clear=True), patch.object(owner.sys, 'platform', 'linux'), \
                patch.object(owner, 'fresh', side_effect=AssertionError('output opened')):
            with self.assertRaisesRegex(ValueError, 'exclusive-fixture-selector'):
                owner.qualify(Path('absent'), revision)


class TaskShutdownNowOwnership(unittest.TestCase):
    def test_four_actual_calls_require_current_ids_strict_budgets_and_physical_idle(self):
        actual = [{**dict.fromkeys(owner.observed.ZERO_FIELDS, 0),
            'activationId': f'java-shutdown-now-0-{mode}', 'iteration': 0, 'mode': mode, 'value': 42,
            'cpuFuel': 123, 'reportedPeakMemoryBytes': 4096,
            'storesBefore': mode, 'storesCreated': mode + 1} for mode in range(4)]
        def encoded(values):
            return ('\n'.join(['test ' + owner.SHUTDOWN_CASE + ' ... ok',
                'teavm-activation-fibers-v1 signed-preparation-setup-micros=1 stores-created=0 guest-activations=0',
                *['LSF_JAVA_RETAINED=' + json.dumps(row) for row in values],
                'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 58 filtered out;']) + '\n').encode()
        self.assertEqual(owner.shutdown_observations(encoded(actual), 58)['calls'], actual)
        for values in (actual[:-1], actual + [actual[0]], rows()):
            with self.assertRaises(ValueError): owner.shutdown_observations(encoded(values), 58)
        for field, value in (('activationId', actual[0]['activationId']), ('mode', 2),
                ('liveStores', 1), ('brokerResults', 1), ('storesBefore', 0),
                ('cpuFuel', True), ('cpuFuel', 10_000_000_001),
                ('reportedPeakMemoryBytes', 64 * 1024**2 + 1)):
            bad = copy.deepcopy(actual); bad[-1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                owner.shutdown_observations(encoded(bad), 58)
        with self.assertRaises(ValueError): owner.shutdown_observations(encoded(actual), 57)

    def test_normal_reference_and_real_sdk_ownership_controls_precede_single_component(self):
        class BeforeComponent(Exception): pass
        calls = []
        class Compiler:
            def __init__(self, directory, sdk, **options):
                self.sdk, self.paths = sdk, {'java': Path('not-executed-java')}
                calls.append(('compiler', options))
            def run(self, stage, *argv):
                calls.append((stage, argv))
                return '42 42 42 42' if stage == 'reference-jdk-0' else ''
            def compile(self, *args, **kwargs):
                calls.append(('component', kwargs)); raise BeforeComponent()
        def control(name):
            def selected(*args): calls.append((name, ())); return {'status': 'source-control-fixture'}
            return selected
        with tempfile.TemporaryDirectory() as temporary, patch('time.monotonic', return_value=100), \
                patch.object(preparation, 'Compiler', Compiler), \
                patch.object(preparation, 'recipe_inputs', return_value={}), \
                patch.object(preparation, 'completable_source_control', side_effect=control('completable-source')), \
                patch.object(preparation, 'shutdown_now_source_control', side_effect=control('shutdown-source')), \
                patch.object(preparation, 'completable_model_control', side_effect=AssertionError('after component')):
            path = Path(temporary) / 'prepared'
            with self.assertRaises(BeforeComponent):
                preparation.prepare(path, owner.ROOT / 'sdk/java-guest', fixture='shutdown-now', _deadline=1000)
            self.assertEqual([stage for stage, _ in calls], ['compiler', 'reference-jdk-compile',
                'reference-jdk-0', 'completable-source', 'shutdown-source', 'component'])
            self.assertEqual(calls[0][1]['_deadline'], 1000)
            self.assertEqual(calls[-1][1], {'activation_profile': True})
            self.assertEqual((path / 'src/Capsule.java').read_bytes(),
                (owner.ROOT / 'sdk/java-guest/fibers/conformance/shutdown-now/Capsule.java').read_bytes())
            self.assertEqual(json.loads((path / 'FIBERS-COMPILE.json').read_bytes())['status'], 'failed')

    def test_shutdown_mode_has_exclusive_hosted_identity_before_any_io(self):
        revision = 'a' * 40
        environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': owner.identities.REPOSITORY,
            'GITHUB_REF_NAME': owner.SHUTDOWN_BRANCH, 'GITHUB_EVENT_NAME': 'push',
            'GITHUB_SHA': revision, 'GITHUB_WORKFLOW_SHA': revision, 'GITHUB_WORKSPACE': str(owner.ROOT),
            'GITHUB_WORKFLOW_REF': owner.identities.REPOSITORY + '/' + owner.WORKFLOW + '@refs/heads/' + owner.SHUTDOWN_BRANCH,
            'LSF_JAVA_COMPLETABLE_FIXTURE': 'old-programme'}
        with patch.dict(os.environ, environment, clear=True), patch.object(owner.sys, 'platform', 'linux'), \
                patch.object(owner, 'fresh', side_effect=AssertionError('output opened')):
            with self.assertRaisesRegex(ValueError, 'exclusive-fixture-selector'):
                owner.qualify_shutdown(Path('absent'), revision)
