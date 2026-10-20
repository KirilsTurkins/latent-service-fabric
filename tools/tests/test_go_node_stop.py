"""Live timer/Store and physical shutdown requirements cannot be replaced by idle models."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tools import go_node_stop_fixture as fixture
from tools import go_node_stop_probe as probe
from tools import qualify_go_node_stop as reference
from tools import qualify_sdk_scratch as normal
from tools.go_capsule_project import create
from tools.rust_capsule_project import snapshot


def inventory():
    return {'topology': {'available': True, 'complete': True, 'entries': [
        {'name': name, 'activeCount': '1'} for name in probe.LIVE_ROWS]}, 'queueDepth': 0}


def event(sequence, operation, *, completed=False, activation='pending', provider=probe.PROFILE):
    return {'epoch': '1', 'sequence': str(sequence), 'data': {'observation': {
        'kind': 'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_PROVIDER_OUTCOME' if completed else
                'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_GRANT_ALLOWED',
        'outcome': 'AUDIT_OBSERVATION_OUTCOME_SUCCEEDED',
        'identities': {'capability': {'activation': activation, 'rootActivation': activation,
            'capability': probe.ACTIVATION, 'providerProfile': provider, 'operation': operation,
            'providerOutcome': 'AUDIT_PROVIDER_OUTCOME_HOST_COMPLETED' if completed else None}}}}}


def pages(mode='pending'):
    minimum = 3 if mode == 'pending' else 2
    rows = [event(1, 'timer-next')]
    rows += [event(index + 2, 'timer-start', completed=True) for index in range(minimum)]
    rows += [event(6, 'timer-next')]
    if mode == 'drain': rows += [event(7, 'close')]
    return [{'category': 'success', 'outcomeKnown': True,
        'data': {'coverage': {'droppedObservations': '0'}, 'records': rows, 'page': {'nextPageToken': None}}}]


def stopped():
    return {'reaped': True, 'record': {'event': 'stopped', 'clean': True, 'report': {
        'clean': True, **{name: '0' for name in probe.ZERO_FIELDS},
        'telemetryFlushed': True, 'epochHelperJoined': True}}}


class GoNodeStop(unittest.TestCase):
    def test_configuration_updates_the_actual_already_created_owned_file_with_original_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            signed, node = root / 'signed', root / 'node'
            signed.mkdir()
            node.mkdir()
            (signed / 'policy.json').write_bytes(b'{}')
            path = reference.configuration(node, signed)
            self.assertEqual(path, node / 'node.json')
            value = json.loads(path.read_bytes())
            self.assertEqual(value['providers']['activationRuntime']['limits'], probe.OWNER_LIMITS)
            self.assertEqual(len(value['providers']['bindings']), 4)
            self.assertEqual(value['execution']['maximumWallTimeMillis'], 120000)
            self.assertEqual(value['cells'], [{'class': 'standard', 'capacity': 1, 'queueCapacity': 2,
                                              'maximumMemoryBytes': 67108864}])
            self.assertEqual(value['shutdownGraceMillis'], 5000)
            self.assertEqual(value['dataDirectory'], 'data')
            self.assertEqual((node / 'policy.json').read_bytes(), b'{}')
            self.assertLessEqual(path.stat().st_size, 262144)

    def test_fixture_uses_original_greeting_with_explicit_v5_and_unchanged_sdk_wit_and_budgets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = snapshot(create(root / 'original', 'greeting', runtime_profile=fixture.PROFILE))
            app, record = fixture.project(root / 'candidate')
            actual = snapshot(app)
            self.assertEqual(set(actual), set(original))
            self.assertEqual([name for name in actual if actual[name] != original[name]], ['sdk-lock.json', 'src/main.go'])
            for value in ('time.Sleep(time.Hour)', 'work.Wait()', 'go func()', 'nodeStopCalls != 1',
                          'nodeStopInitialized != 42', '"Please enter a name."', '"Hello, "'):
                self.assertIn(value, actual['src/main.go'].decode())
            self.assertNotIn('Gosched', actual['src/main.go'].decode())
            self.assertNotIn('lsfRegister', actual['src/main.go'].decode())
            self.assertEqual(json.loads(actual['capsule-project.json'])['limits'],
                             json.loads(original['capsule-project.json'])['limits'])
            self.assertFalse(record['compilerExecuted'])
            self.assertEqual(record['signedQualification'], 'pending')

    def test_barrier_requires_actual_live_store_and_host_completed_body_timers_not_just_a_wait(self):
        actual = probe.barrier(inventory(), pages(), 'pending', 'pending')
        self.assertEqual(actual['completedTimerStarts'], 3)
        self.assertEqual(actual['allowedTimerNext'], 2)
        self.assertFalse(actual['actualNodeSignalSent'])
        for name in probe.LIVE_ROWS:
            value = inventory()
            next(row for row in value['topology']['entries'] if row['name'] == name)['activeCount'] = '0'
            self.assertIsNone(probe.barrier(value, pages(), 'pending', 'pending'))
        raw = pages()
        for row in raw[0]['data']['records']:
            if row['data']['observation']['identities']['capability']['operation'] == 'timer-start':
                row['data']['observation']['kind'] = 'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_GRANT_ALLOWED'
        self.assertIsNone(probe.barrier(inventory(), raw, 'pending', 'pending'))

    def test_returned_root_requires_actual_close_and_timer_next_after_checked_start_results(self):
        self.assertTrue(probe.barrier(inventory(), pages('drain'), 'pending', 'drain')['rootCloseObserved'])
        raw = pages('drain')
        raw[0]['data']['records'].pop()
        self.assertIsNone(probe.barrier(inventory(), raw, 'pending', 'drain'))
        raw = pages()
        raw[0]['data']['records'][-1]['sequence'] = '0'
        self.assertIsNone(probe.barrier(inventory(), raw, 'pending', 'pending'))

    def test_initializer_only_or_other_activation_cannot_stand_in_for_accepted_body_work(self):
        raw = pages()
        raw[0]['data']['records'] = [raw[0]['data']['records'][0], raw[0]['data']['records'][1], raw[0]['data']['records'][-1]]
        self.assertIsNone(probe.barrier(inventory(), raw, 'pending', 'pending'))
        self.assertIsNone(probe.barrier(inventory(), pages(), 'foreign', 'pending'))
        for key, value in [('rootActivation', 'foreign'), ('providerProfile', 'other')]:
            raw = pages()
            raw[0]['data']['records'][1]['data']['observation']['identities']['capability'][key] = value
            with self.assertRaisesRegex(RuntimeError, 'exact-activation-provider'):
                probe.barrier(inventory(), raw, 'pending', 'pending')

    def test_missing_dropped_duplicate_or_partial_audit_is_not_a_live_work_barrier(self):
        for update in ('dropped', 'partial', 'duplicate', 'unavailable'):
            raw = pages()
            if update == 'dropped': raw[0]['data']['coverage']['droppedObservations'] = '1'
            if update == 'partial': raw[0]['data']['page']['nextPageToken'] = 'more'
            if update == 'duplicate': raw[0]['data']['records'] += [copy.deepcopy(raw[0]['data']['records'][0])]
            if update == 'unavailable': raw[0]['category'] = 'transport-failure'
            with self.subTest(update=update), self.assertRaisesRegex(RuntimeError, 'Go-node-stop-'):
                probe.barrier(inventory(), raw, 'pending', 'pending')

    def test_original_limits_are_go_limits_and_readiness_does_not_raise_any_capacity(self):
        self.assertEqual(probe.OWNER_LIMITS, {'tasks': 16, 'executors': 2, 'queuedWork': 2, 'waits': 4,
                         'timers': 2, 'results': 2, 'nativeOwners': 2})
        self.assertEqual(len(probe.OPERATIONS), 8)
        for value in (True, -1, str(2**64), 'private', '1.0'):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, 'finite-observation'):
                probe.integer(value)

    def test_shutdown_requires_each_original_physical_owner_zero_and_real_joined_reaped_report(self):
        self.assertTrue(probe.shutdown(stopped())['clean'])
        for name in probe.ZERO_FIELDS:
            row = stopped()
            row['record']['report'][name] = '1'
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'owners-retired'):
                probe.shutdown(row)
        for field in ('telemetryFlushed', 'epochHelperJoined'):
            row = stopped()
            row['record']['report'][field] = False
            with self.assertRaises(RuntimeError): probe.shutdown(row)
        row = stopped()
        row['reaped'] = False
        with self.assertRaises(RuntimeError): probe.shutdown(row)

    def test_uncertain_transport_is_retained_without_inventing_cancellation_or_retirement(self):
        row = {'processReaped': True, 'exitCode': 5, 'decoded': None,
               'response': {'outcomeKnown': False, 'error': {'code': 'rpc-failed'}}}
        result = probe.interrupted(row)
        self.assertFalse(result['outcomeKnown'])
        self.assertFalse(result['cancellationAcknowledgementInferred'])
        self.assertEqual(result['physicalRetirementSource'], 'actual-node-shutdown-report')
        for key, value in [('processReaped', False), ('exitCode', 0), ('decoded', [{'ok': 'early'}])]:
            changed = copy.deepcopy(row)
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'no-fake-success'):
                probe.interrupted(changed)
        row['response']['error']['code'] = 'private-error-text'
        with self.assertRaisesRegex(RuntimeError, 'closed-terminal-outcome'):
            probe.interrupted(row)

    def test_fresh_after_restart_binds_actual_resolved_revision_and_original_consumption(self):
        revision = {'publicationId': 'published', 'routeGeneration': '23',
                    'releaseDigest': 'release', 'revisionId': 'revision'}
        row = {'exitCode': 0, 'decoded': [{'ok': 'node-stop|fresh=1|value=42'}], 'processReaped': True,
            'response': {'outcomeKnown': True, 'data': {'resolvedRevision': revision,
                'consumption': {'cpuFuel': '100', 'peakMemoryBytes': '8192',
                                'outboundRequests': 0, 'childCalls': 0, 'logBytes': 0, 'effectCount': 0}}}}
        target = {'budget': {'cpuFuel': 1000, 'memoryBytes': 65536}}
        with patch.object(reference, 'selected_revision', return_value=revision), \
                patch.object(reference, 'call', return_value=row):
            self.assertEqual(reference.fresh_call(object(), target, 'fresh'), row)
            for field, value in [('resolvedRevision', {**revision, 'routeGeneration': '1'}),
                                 ('consumption', {**row['response']['data']['consumption'], 'effectCount': 1})]:
                changed = copy.deepcopy(row)
                changed['response']['data'][field] = value
                with self.subTest(field=field), patch.object(reference, 'call', return_value=changed), \
                        self.assertRaisesRegex(RuntimeError, 'Go-node-stop-fresh-'):
                    reference.fresh_call(object(), target, 'fresh')

    def test_component_build_failure_cannot_run_a_node_or_write_successful_qualification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = {}
            for name in ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring'):
                path = root / name.replace('/', '-')
                path.write_bytes(b'controlled-test-not-executable')
                binaries[name] = path
            with patch.object(reference.sys, 'platform', 'linux'), \
                    patch.object(reference.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(reference, 'validate_producer', return_value={}), \
                    patch.object(reference, 'prepared', return_value=(binaries, {}, {'originalInvocations': 27}, {})), \
                    patch.object(reference, 'build_component', side_effect=RuntimeError('controlled-build-failure')), \
                    patch.object(reference, 'programme', side_effect=AssertionError('node before successful component')) as run, \
                    self.assertRaisesRegex(RuntimeError, 'controlled-build-failure'):
                producer = root / 'producer.json'
                producer.write_bytes(b'{}')
                reference.qualify(root / 'output', root / 'normal', producer)
            run.assert_not_called()
            record = json.loads((root / 'output/FAILED.json').read_bytes())
            self.assertEqual((record['status'], record['stage']), ('failed', 'fresh-component-build'))
            self.assertFalse((root / 'output/qualification.json').exists())
            self.assertFalse(record['newNativeBuild'])

    def test_live_barrier_read_failure_restores_the_original_deadline_and_never_signals_node(self):
        client = SimpleNamespace(deadline=100.0)
        node = SimpleNamespace(drain=lambda: None)
        pending = SimpleNamespace(owner=SimpleNamespace(exited=lambda: False),
                                  authoring_started_unix_millis=1000, authoring_activation='pending')
        with patch.object(reference.time, 'monotonic', return_value=10.0), \
                patch.object(reference, 'audit_pages', side_effect=RuntimeError('controlled-read-failure')), \
                patch.object(reference, 'stop', side_effect=AssertionError('signal before actual barrier')) as stop, \
                self.assertRaisesRegex(RuntimeError, 'controlled-read-failure'):
            reference.wait_live(client, node, pending, 'pending')
        self.assertEqual(client.deadline, 100.0)
        stop.assert_not_called()

    def test_historical_normal_tuple_allows_only_exact_unused_dotnet_extension_and_keeps_default_strict(self):
        original = {'runtime': {'sha256': 'runtime'}, 'sdk': {'sha256': 'sdk'}, 'wit': {'sha256': 'wit'},
            'schemas': {'sha256': 'schemas'}, 'guide': {'sha256': 'guide'},
            'helpers': {reference.WORKFLOW_HELPER: reference.ORIGINAL_HELPER,
                        'go_guest/compiler.py': {'sha256': 'compiler'}}}
        current = copy.deepcopy(original)
        current['helpers'][reference.WORKFLOW_HELPER] = reference.DOTNET_ONLY_HELPER
        result = reference.compatible_normal_source(original, current)
        self.assertFalse(result['originalNormalProgrammeRelabelledAsCurrent'])
        for field in ('runtime', 'sdk', 'wit', 'schemas', 'guide'):
            changed = copy.deepcopy(current)
            changed[field]['sha256'] = 'drift'
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'must-match'):
                reference.compatible_normal_source(original, changed)
        for name in (reference.WORKFLOW_HELPER, 'go_guest/compiler.py'):
            changed = copy.deepcopy(current)
            changed['helpers'][name]['sha256'] = 'unknown'
            with self.subTest(helper=name), self.assertRaisesRegex(RuntimeError, 'Go-node-stop-'):
                reference.compatible_normal_source(original, changed)
        with patch.object(normal, 'current_inputs', return_value=current), \
                patch.object(normal, '_prepared_with_inputs', return_value='actual') as checked:
            self.assertEqual(normal.prepared(Path('normal'), 'go'), 'actual')
            checked.assert_called_once_with(Path('normal'), 'go', current, None)

    def test_exact_successful_producer_artifact_cannot_be_substituted_with_other_head_job_or_failure(self):
        value = {'run': {'id': reference.PRODUCER_RUN, 'head_sha': reference.PRODUCER_HEAD,
            'event': 'push', 'path': '.github/workflows/go-scratch-reference.yml',
            'head_branch': 'feat/go-standard-scratch-20261020', 'status': 'completed', 'conclusion': 'success'},
            'job': {'id': reference.PRODUCER_JOB, 'run_id': reference.PRODUCER_RUN,
                'head_sha': reference.PRODUCER_HEAD, 'status': 'completed', 'conclusion': 'success',
                'steps': [{'number': n, 'conclusion': 'success'} for n in (11, 12, 13, 14, 15, 16)]},
            'artifact': {'id': reference.PRODUCER_ARTIFACT, 'workflow_run': {'id': reference.PRODUCER_RUN,
                'head_sha': reference.PRODUCER_HEAD}, 'expired': False,
                'name': 'go-scratch-prepared-' + reference.PRODUCER_HEAD, 'size_in_bytes': 68946198,
                'digest': 'sha256:d748d316bec91a06f3856b5f64e18e16ab71dd824d7a16d1fd8f6ec8c39ec4ea'}}
        self.assertEqual(reference.validate_producer(value)['originalNormalSignedInvocations'], 27)
        for member, key, bad in [('run', 'head_sha', 'other'), ('run', 'event', 'pull_request'),
                ('job', 'run_id', reference.PRODUCER_RUN + 1), ('job', 'conclusion', 'failure'),
                ('artifact', 'digest', 'sha256:' + '0' * 64), ('artifact', 'expired', True)]:
            changed = copy.deepcopy(value)
            changed[member][key] = bad
            with self.subTest(member=member, key=key), self.assertRaisesRegex(RuntimeError, 'Go-node-stop-'):
                reference.validate_producer(changed)
        changed = copy.deepcopy(value)
        changed['job']['steps'][3]['conclusion'] = 'skipped'
        with self.assertRaisesRegex(RuntimeError, 'actual-steps'):
            reference.validate_producer(changed)

    def test_failed_tuple_integrity_never_reaches_a_new_component_or_signer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            producer = root / 'producer.json'
            producer.write_bytes(b'{}')
            with patch.object(reference.sys, 'platform', 'linux'), \
                    patch.object(reference.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(reference, 'validate_producer', return_value={}), \
                    patch.object(reference, 'prepared', side_effect=RuntimeError('controlled-tuple-drift')), \
                    patch.object(reference, 'build_component') as compiler, \
                    self.assertRaisesRegex(RuntimeError, 'controlled-tuple-drift'):
                reference.qualify(root / 'output', root / 'normal', producer)
            compiler.assert_not_called()
            record = json.loads((root / 'output/FAILED.json').read_bytes())
            self.assertEqual(record['stage'], 'original-normal-products')
            self.assertFalse((root / 'output/qualification.json').exists())


if __name__ == '__main__':
    unittest.main()
