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
        'activationId': f'java-scheduled-libraries-{index // 9}-{index % 9}',
        'iteration': index // 9, 'mode': index % 9, 'value': 2_211_210 if index % 9 == 8 else 42,
        'cpuFuel': 123, 'reportedPeakMemoryBytes': 4096,
        'storesBefore': index, 'storesCreated': index + 1} for index in range(18)]


def output(values):
    return ('\n'.join(['test ' + owner.CASE + ' ... ok',
        'teavm-activation-fibers-v1 signed-preparation-setup-micros=1 stores-created=0 guest-activations=0',
        *['LSF_JAVA_RETAINED=' + json.dumps(row) for row in values],
        'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 51 filtered out;']) + '\n').encode()


class ScheduledLibraryOwnership(unittest.TestCase):
    def test_compiler_retention_accepts_observed_command_pairs_and_remains_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = root / 'prepared'
            compiler = prepared / 'compiler'
            compiler.mkdir(parents=True)
            # The scheduled-library failure recorded 178 successful commands;
            # a successful command normally leaves both of these public files.
            for index in range(178):
                (compiler / f'{index}-stage.command.json').write_bytes(b'{}')
                (compiler / f'{index}-stage.log').write_bytes(b'log')
            (compiler / 'private.txt').write_bytes(b'not selected')
            first = owner.retain(prepared, root / 'observed')
            self.assertEqual(len(first), 356)
            self.assertEqual((root / 'observed/compiler/177-stage.log').read_bytes(), b'log')
            self.assertFalse((root / 'observed/compiler/private.txt').exists())

            for index in range(178, 256):
                (compiler / f'{index}-stage.command.json').write_bytes(b'{}')
                (compiler / f'{index}-stage.log').write_bytes(b'log')
            self.assertEqual(len(owner.retain(prepared, root / 'at-limit')), 512)
            (compiler / 'overflow.log').write_bytes(b'overflow')
            with self.assertRaisesRegex(ValueError, 'compiler-log-count'):
                owner.retain(prepared, root / 'over-limit')
            self.assertFalse((root / 'over-limit/compiler').exists())

    def test_all_eight_modes_twice_require_actual_unique_ids_and_fresh_idle_stores(self):
        actual = rows()
        self.assertEqual(owner.observations(output(actual))['calls'], actual)
        for field, value in (('activationId', actual[0]['activationId']), ('mode', 5), ('value', 42),
                ('value', 2_211_211),
                ('storesBefore', 0), ('liveStores', 1), ('cpuFuel', True),
                ('cpuFuel', 10_000_000_001), ('reportedPeakMemoryBytes', 64 * 1024**2 + 1)):
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(actual); bad[-1][field] = value
                with self.assertRaises(ValueError): owner.observations(output(bad))

    def test_short_old_or_skipped_programmes_cannot_be_relabelled_scheduled_pass(self):
        original = output(rows())
        variants = [output(rows()[:-1]), output(rows() + [rows()[0]]),
            output([row for row in rows() if row['mode'] != 8]),
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
            reference = tuple(map(str, calls[1][1]))
            self.assertTrue(any(name.endswith('reference/dev/latent/generated/Bindings.java')
                                or name.endswith('reference\\dev\\latent\\generated\\Bindings.java') for name in reference))
            self.assertTrue(any(name.endswith('reference/dev/latent/guest/runtime/Activation.java')
                                or name.endswith('reference\\dev\\latent\\guest\\runtime\\Activation.java') for name in reference))
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

        # Both routes reach their unchanged owned-output boundary only for the
        # exact push, workflow path and commit; reject mixed or stale identities.
        environment.pop('LSF_JAVA_WORKER_LIBRARIES_FIXTURE')
        for branch, workflow in ((owner.BRANCH, owner.WORKFLOW), (owner.TIMER_BRANCH, owner.WORKFLOW),
                                 (owner.RENDEZVOUS_BRANCH, owner.WORKFLOW), (owner.DEVELOPMENT_BRANCH, owner.DEVELOPMENT_WORKFLOW)):
            selected = {**environment, 'GITHUB_REF_NAME': branch,
                'GITHUB_WORKFLOW_REF': owner.identities.REPOSITORY + '/' + workflow + '@refs/heads/' + branch}
            with self.subTest(branch=branch), patch.dict(os.environ, selected, clear=True), \
                    patch.object(owner.sys, 'platform', 'linux'), \
                    patch.object(owner, 'fresh', side_effect=RuntimeError('identity accepted')) as fresh:
                with self.assertRaisesRegex(RuntimeError, 'identity accepted'):
                    owner.qualify(Path('absent'), revision)
                fresh.assert_called_once()
        development = {**environment, 'GITHUB_REF_NAME': owner.DEVELOPMENT_BRANCH,
            'GITHUB_WORKFLOW_REF': owner.identities.REPOSITORY + '/' + owner.DEVELOPMENT_WORKFLOW
                + '@refs/heads/' + owner.DEVELOPMENT_BRANCH}
        for key, value in (('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_REPOSITORY', 'elsewhere/repo'),
                           ('GITHUB_REF_NAME', 'release'), ('GITHUB_SHA', 'b' * 40),
                           ('GITHUB_WORKFLOW_SHA', 'b' * 40), ('GITHUB_WORKSPACE', 'elsewhere'),
                           ('GITHUB_WORKFLOW_REF', owner.identities.REPOSITORY + '/' + owner.WORKFLOW
                               + '@refs/heads/' + owner.DEVELOPMENT_BRANCH)):
            with self.subTest(key=key), patch.dict(os.environ, {**development, key: value}, clear=True), \
                    patch.object(owner.sys, 'platform', 'linux'), \
                    patch.object(owner, 'fresh', side_effect=AssertionError('output opened')):
                with self.assertRaisesRegex(ValueError, 'fixed-hosted-push'):
                    owner.qualify(Path('absent'), revision)

        from tools import ci_lane_inventory as lanes
        caller = lanes.structural_workflow(lanes.workflow_model(
            (owner.ROOT / owner.DEVELOPMENT_WORKFLOW).read_text(encoding='utf-8')))
        called = lanes.structural_workflow(lanes.workflow_model(
            (owner.ROOT / owner.WORKFLOW).read_text(encoding='utf-8')))
        self.assertEqual(caller['on']['push']['branches'], ['development'])
        self.assertEqual(set(caller['on']['push']['paths']), set(called['on']['push']['paths']) | {
            owner.DEVELOPMENT_WORKFLOW,
            'crates/latent-core/src/activation_runtime.rs', 'crates/latent-core/src/activation_runtime/**',
            'crates/latent-wasmtime/src/**', 'crates/latent-wasmtime/tests/local_service/**',
            'crates/latent-wasmtime/tests/local_service.rs', 'crates/latent-activation/src/**',
            'crates/latent-executor/src/**', 'crates/latent-node/src/**', 'crates/latent-scheduler/src/**',
            'wit/platform/**', 'Cargo.toml', 'Cargo.lock', '.cargo/managed-guest.toml',
            'tools/toolchain.toml', 'tools/data/java-compiler-profile.json'})
        self.assertEqual(caller['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(caller['jobs'], {'scheduled-library': {'uses': '$/' + owner.WORKFLOW}})
        self.assertIn('workflow_call', called['on'])
        self.assertEqual(called['on']['push']['branches'], [owner.BRANCH, owner.SHUTDOWN_BRANCH, owner.FUTURE_BRANCH, owner.TIMER_BRANCH, owner.RENDEZVOUS_BRANCH])
        job = called['jobs']['scheduled-library']
        self.assertIn(owner.DEVELOPMENT_WORKFLOW + '@refs/heads/development', job['if'])
        self.assertEqual(job['timeout-minutes'],
            "${{ (github.ref_name == '" + owner.BRANCH + "' || github.ref_name == '" + owner.TIMER_BRANCH + "' || github.ref_name == '" + owner.RENDEZVOUS_BRANCH + "' || github.ref_name == 'development') && 45 || 25 }}")
        self.assertEqual([step['if'] for step in job['steps'] if step.get('name', '').startswith('Capture and compile')],
            ["github.ref_name == '" + owner.BRANCH + "' || github.ref_name == '" + owner.TIMER_BRANCH + "' || github.ref_name == '" + owner.RENDEZVOUS_BRANCH + "' || github.ref_name == 'development'"])


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


class TaskShutdownNowSourceCapture(unittest.TestCase):
    def test_full_native_snapshot_and_fixed_supplement_keep_limits_and_detect_drift(self):
        from types import SimpleNamespace
        actual_limits = owner.observed.SnapshotLimits()
        self.assertEqual((actual_limits.max_entries, actual_limits.max_file_bytes, actual_limits.max_total_bytes),
                         (16384, 4 * 1024**2, 128 * 1024**2))
        native = [f'tools/capture-{index:04d}.py' for index in range(100)]
        supplemental = set(owner.observed.EXTRA_SOURCES) | {owner.workers.WORKFLOW, owner.WORKFLOW,
            owner.DEVELOPMENT_WORKFLOW, 'sdk/java-guest/fibers/conformance/scheduled-library/Capsule.java'}
        calls, changed = [], {}
        allowed = {*native, *supplemental, owner.observed.WORKFLOW}
        def command(stage, *argv, max_output_bytes):
            self.assertEqual(max_output_bytes, owner.observed.MAX_SOURCE_LISTING_BYTES)
            calls.append((stage, argv))
            self.assertEqual((stage, argv), ('source-paths', ('git', 'ls-files', '-z', '--', *owner.SOURCE_ALLOWLIST)))
            return ('\0'.join(native) + '\0').encode()
        def read(path, maximum):
            self.assertEqual(maximum, 4 * 1024**2)
            name = path.relative_to(owner.ROOT).as_posix()
            self.assertIn(name, allowed)
            value = changed.get(name, b'x')
            if len(value) > maximum: raise ValueError('file-bound')
            return value
        commands = SimpleNamespace(command_seconds=0, deadline=1000, run=command)
        from tools.build_snapshot import SnapshotLimits
        limits = SnapshotLimits(max_entries=100, max_total_bytes=72 * 1024**2 + 100)
        with patch.object(owner.time, 'monotonic', return_value=100), \
                patch.object(owner.observed, 'SnapshotLimits', return_value=limits), \
                patch.object(owner.observed, 'read_file', side_effect=read):
            before = owner.shutdown_sources(commands)
            self.assertEqual(set(before['native']), set(native))
            self.assertEqual(set(before['supplementary']), supplemental)
            self.assertEqual((len(before['native']), len(before['supplementary']), len(calls)), (100, 18, 1))
            self.assertEqual(owner.shutdown_sources(commands, before['native']), before)
            self.assertEqual(len(calls), 1)
            for capture, workflow in ((owner.workers.sources, owner.workers.WORKFLOW),
                    (owner.observed.source_inputs, owner.observed.WORKFLOW), (owner.sources, owner.WORKFLOW)):
                actual = capture(commands)
                self.assertEqual(actual['native'], before['native'])
                expected = supplemental if workflow == owner.WORKFLOW else set(owner.observed.EXTRA_SOURCES) | {workflow}
                self.assertEqual(set(actual['supplementary']), expected)
                self.assertEqual(capture(commands, before['native']), actual)
            changed[native[0]] = b'changed-native'
            after = owner.shutdown_sources(commands, before['native'])
            self.assertNotEqual(after['native'], before['native'])
            self.assertEqual(after['supplementary'], before['supplementary'])
            changed.clear(); changed[min(supplemental)] = b'changed-supplement'
            after = owner.shutdown_sources(commands, before['native'])
            self.assertEqual(after['native'], before['native'])
            self.assertNotEqual(after['supplementary'], before['supplementary'])
            changed.clear()
            # The injected envelope is already at its entry limit.
            native.append('tools/overflow.py')
            with self.assertRaisesRegex(ValueError, 'native-source-count'):
                owner.shutdown_sources(commands)
            native.pop()
            changed[native[0]] = b'x' * (4 * 1024**2 + 1)
            with self.assertRaisesRegex(ValueError, 'file-bound'):
                owner.shutdown_sources(commands, before['native'])
            changed.clear()
            full = b'x' * (4 * 1024**2)
            count, remainder = divmod(limits.max_total_bytes, limits.max_file_bytes)
            changed.update(dict.fromkeys(native[:count], full))
            changed[native[count]] = b'x' * (remainder - (len(native) - count - 1))
            exact = owner.shutdown_sources(commands, before['native'])
            self.assertEqual(sum(row['bytes'] for row in exact['native'].values()), limits.max_total_bytes)
            changed[native[count]] += b'x'
            with self.assertRaisesRegex(ValueError, 'native-source-total'):
                owner.shutdown_sources(commands, before['native'])
            changed.clear()
            overflow_count = limits.max_total_bytes // limits.max_file_bytes + 1
            changed.update(dict.fromkeys(native[:overflow_count], full))
            with self.assertRaisesRegex(ValueError, 'native-source-total'):
                owner.shutdown_sources(commands, before['native'])
            changed.clear(); changed.update(dict.fromkeys(sorted(supplemental)[:5], full))
            with self.assertRaisesRegex(ValueError, 'supplement-total'):
                owner.shutdown_sources(commands, before['native'])
            changed.clear(); commands.deadline = 100
            with self.assertRaisesRegex(ValueError, 'source-deadline'):
                owner.shutdown_sources(commands, before['native'])


class TaskStandardFutureQueueOwnership(unittest.TestCase):
    def test_four_signed_future_modes_refuse_missing_duplicate_old_and_nonidle_rows(self):
        actual = [{**dict.fromkeys(owner.observed.ZERO_FIELDS, 0),
            'activationId': f'java-future-queue-0-{mode}', 'iteration': 0, 'mode': mode, 'value': 42,
            'cpuFuel': 123, 'reportedPeakMemoryBytes': 4096, 'storesBefore': mode,
            'storesCreated': mode + 1} for mode in range(4)]
        def encoded(values):
            return ('\n'.join(['test ' + owner.FUTURE_CASE + ' ... ok',
                'teavm-activation-fibers-v1 signed-preparation-setup-micros=1 stores-created=0 guest-activations=0',
                *['LSF_JAVA_RETAINED=' + json.dumps(row) for row in values],
                'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 59 filtered out;']) + '\n').encode()
        self.assertEqual(owner.future_observations(encoded(actual), 59)['calls'], actual)
        for values in (actual[:-1], actual + [actual[0]], rows()):
            with self.assertRaises(ValueError): owner.future_observations(encoded(values), 59)
        for field, value in (('activationId', actual[0]['activationId']), ('mode', 2), ('value', 41),
                ('brokerResults', 1), ('storesBefore', 0), ('cpuFuel', True),
                ('cpuFuel', 10_000_000_001), ('reportedPeakMemoryBytes', 64 * 1024**2 + 1)):
            bad = copy.deepcopy(actual); bad[-1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): owner.future_observations(encoded(bad), 59)
        with self.assertRaises(ValueError): owner.future_observations(encoded(actual), 58)

    def test_normal_future_preparation_keeps_reference_capacity_distinct_and_source_controls_before_component(self):
        class BeforeComponent(Exception): pass
        calls = []
        class Compiler:
            def __init__(self, directory, sdk, **options):
                self.sdk, self.paths = sdk, {'java': Path('not-executed-java')}; calls.append(('compiler', options))
            def run(self, stage, *argv):
                calls.append((stage, argv)); return '41 42 42 42' if stage == 'reference-jdk-0' else ''
            def compile(self, *args, **kwargs):
                calls.append(('component', kwargs)); raise BeforeComponent()
        def control(*args): calls.append(('future-source', ())); return {'status': 'source-control-fixture'}
        with tempfile.TemporaryDirectory() as temporary, patch('time.monotonic', return_value=100), \
                patch.object(preparation, 'Compiler', Compiler), patch.object(preparation, 'recipe_inputs', return_value={}), \
                patch.object(preparation, 'future_queue_source_control', side_effect=control), \
                patch.object(preparation, 'completable_source_control', side_effect=AssertionError('old campaign repeated')), \
                patch.object(preparation, 'scheduled_model_control', side_effect=AssertionError('after component')):
            path = Path(temporary) / 'prepared'
            with self.assertRaises(BeforeComponent):
                preparation.prepare(path, owner.ROOT / 'sdk/java-guest', fixture='future-queue', _deadline=1000)
            self.assertEqual([stage for stage, _ in calls], ['compiler', 'reference-jdk-compile', 'reference-jdk-0', 'future-source', 'component'])
            self.assertEqual(calls[0][1]['_deadline'], 1000)
            self.assertEqual(calls[-1][1], {'activation_profile': True})
            report = json.loads((path / 'FIBERS-COMPILE.json').read_bytes())
            self.assertEqual(report['reference'][0]['results'], [41, 42, 42, 42])
            self.assertEqual(report['status'], 'failed')
            self.assertEqual((path / 'src/Capsule.java').read_bytes(),
                (owner.ROOT / 'sdk/java-guest/fibers/conformance/future-queue/Capsule.java').read_bytes())

    def test_future_branch_cannot_reuse_shutdown_selector_or_an_ambient_fixture(self):
        revision = 'a' * 40
        environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': owner.identities.REPOSITORY,
            'GITHUB_REF_NAME': owner.FUTURE_BRANCH, 'GITHUB_EVENT_NAME': 'push',
            'GITHUB_SHA': revision, 'GITHUB_WORKFLOW_SHA': revision, 'GITHUB_WORKSPACE': str(owner.ROOT),
            'GITHUB_WORKFLOW_REF': owner.identities.REPOSITORY + '/' + owner.WORKFLOW + '@refs/heads/' + owner.FUTURE_BRANCH}
        with patch.dict(os.environ, environment, clear=True), patch.object(owner.sys, 'platform', 'linux'), \
                patch.object(owner, 'fresh', side_effect=AssertionError('output opened')):
            with self.assertRaisesRegex(ValueError, 'fixed-hosted-push'):
                owner.qualify_shutdown(Path('absent'), revision)
            with patch.dict(os.environ, {'LSF_JAVA_FUTURE_QUEUE_FIXTURE': 'old'}):
                with self.assertRaisesRegex(ValueError, 'exclusive-fixture-selector'):
                    owner.qualify_shutdown(Path('absent'), revision, future_queue=True)
