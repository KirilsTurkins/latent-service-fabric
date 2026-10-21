"""Source/data controls only; no local C link, native build or guest execution."""
import json
import copy
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from tools import c_thread_runtime_fixture as fixture
from tools import c_thread_runtime_node as node
from tools.c_capsule_project import validate
from tools.rust_capsule_project import snapshot


class CThreadRuntime(unittest.TestCase):
    def test_current_native_source_equality_is_required_before_any_product_use(self):
        from unittest.mock import Mock, patch
        from tools import qualify_c_thread_runtime as qualification
        products = Mock(SOURCE='a' * 40)
        products.verify_prepared.return_value = {'verified': 'frozen receipt'}
        products.native_products.return_value = {'latentd': Path('unexecuted')}
        source = {'sha256': 'source', 'files': 1, 'bytes': 1}
        with patch.object(qualification, 'git_source_identity', return_value=source), \
                patch.object(qualification, 'source_identity', return_value=source):
            before, actual, native = qualification.native_evidence(products, Path('prepared'))
        self.assertEqual((before, actual, native), (products.verify_prepared.return_value,
                         source, products.native_products.return_value))
        products.native_products.reset_mock()
        with patch.object(qualification, 'git_source_identity', return_value=source), \
                patch.object(qualification, 'source_identity', return_value={**source, 'sha256': 'foreign'}), \
                self.assertRaisesRegex(RuntimeError, 'current-native-source-must-match-producer'):
            qualification.native_evidence(products, Path('prepared'))
        products.native_products.assert_not_called()
        products.verify_prepared.side_effect = RuntimeError('original receipt drift')
        with self.assertRaisesRegex(RuntimeError, '^original receipt drift$'):
            qualification.native_evidence(products, Path('prepared'))
        products.native_products.assert_not_called()

    def test_fresh_ordinary_project_is_selected_locked_and_uses_standard_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            project = fixture.prepare(Path(directory) / 'ordinary')
            config, lock, _ = validate(snapshot(project))
            self.assertEqual(config['world'], fixture.WORLD)
            self.assertEqual(config['threadingProfile'], 'c-context144-sync-cooperative-v1')
            self.assertEqual(config['limits']['memoryBytes'], 32 * 1024 * 1024)
            self.assertEqual(config['limits']['outboundRequests'], 0)
            source = (project / 'src/main.c').read_text()
            for ordinary in ('pthread_create(', 'pthread_join(', 'pthread_self(', 'pthread_equal(',
                             'thrd_create(', 'thrd_join(', 'thrd_current(', 'thrd_equal(',
                             'pthread_key_create(', '_Thread_local', 'errno ='):
                self.assertIn(ordinary, source)
            for private in ('thread-abi.h', 'lsf_c_', 'import_module', 'thread-new', 'thread_switch'):
                self.assertNotIn(private, source)
            self.assertEqual(lock['language'], 'c')
            self.assertNotIn('grants', config)

    def test_real_child_owner_observation_is_exact_and_cannot_be_relabelled_pending(self):
        row = fixture.observation('joined:2:2:2:1:1:3:2:6:1048576', 2)
        self.assertEqual(row['nativeOwners'], 6)
        self.assertFalse(row['waitForPollPendingClaimed'])
        for value in ('joined:2:1:2:1:1:3:2:6:1048576', 'joined:2:2:2:0:1:3:2:6:1048576',
                      'joined:2:2:2:1:0:3:2:6:1048576', 'joined:2:2:2:1:1:3:2:5:1048576',
                      'joined:2:2:2:1:1:3:2:6:0', 'joined:2:2:2:1:1:3:2:6:33554433',
                      'joined:02:2:2:1:1:3:2:6:1048576', 'joined:2:2:2:1:1:3:2:6:1048576:1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fixture.observation(value, 2)
        with self.assertRaises(ValueError):
            fixture.observation('joined:2:2:2:1:1:3:2:6:1048576', True)

    def test_child_entry_requires_exact_current_native_and_child_events_and_five_owners(self):
        revision = {'publicationId': 'publication:sha256:' + '1' * 64,
                    'releaseDigest': 'sha256:' + '2' * 64,
                    'revisionId': 'revision-v1:sha256:' + '3' * 64, 'routeGeneration': '7'}
        inventory = {'topology': {'available': True, 'complete': True, 'entries': [
            {'name': name, 'activeCount': '1'} for name in node.LIVE]}}
        def event(sequence, capability, operation):
            return {'epoch': 'a' * 32, 'sequence': str(sequence), 'data': {'observation': {
                'kind': 'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_PROVIDER_OUTCOME',
                'identities': {'publicationId': revision['publicationId'], 'componentDigest': revision['releaseDigest'],
                    'revision': revision['revisionId'], 'routeGeneration': '7', 'capability': {
                        'activation': 'c-cancel', 'rootActivation': 'c-cancel',
                        'service': 'examples/' + node.SERVICE, 'capability': capability,
                        'providerProfile': node.PROVIDERS[capability][1], 'operation': operation,
                        'providerOutcome': 'AUDIT_PROVIDER_OUTCOME_HOST_COMPLETED'}}}}}
        pages = [{'category': 'success', 'outcomeKnown': True, 'data': {
            'records': [event(1, node.NATIVE, 'start'), event(2, node.ACTIVATION, 'observe')],
            'page': {'nextPageToken': None}, 'coverage': {'droppedObservations': '0'}}}]
        result = node.child_entry(inventory, pages, 'c-cancel', expected_revision=revision)
        self.assertTrue(result['sourceBoundChildEntry'])
        self.assertFalse(result['typedObserveSuccessClaimed'])
        self.assertFalse(result['waitForPollPendingClaimed'])
        self.assertIsNone(node.child_entry(inventory, pages, 'stale-activation', expected_revision=revision))
        for mutate in ('owner', 'incomplete', 'loss', 'foreign-revision', 'provider', 'duplicate', 'reordered'):
            bad_inventory, bad_pages = copy.deepcopy(inventory), copy.deepcopy(pages)
            if mutate == 'owner':
                bad_inventory['topology']['entries'][0]['activeCount'] = '0'
            elif mutate == 'incomplete':
                bad_inventory['topology']['complete'] = False
            elif mutate == 'loss':
                bad_pages[0]['data']['coverage']['droppedObservations'] = '1'
            elif mutate == 'foreign-revision':
                bad_pages[0]['data']['records'][1]['data']['observation']['identities']['revision'] = 'foreign'
            elif mutate == 'provider':
                bad_pages[0]['data']['records'][1]['data']['observation']['identities']['capability']['providerProfile'] = 'wrong'
            elif mutate == 'duplicate':
                bad_pages[0]['data']['records'].append(copy.deepcopy(bad_pages[0]['data']['records'][1]))
            else:
                bad_pages[0]['data']['records'][0]['sequence'] = '3'
            with self.subTest(mutate=mutate):
                if mutate in ('owner', 'reordered'):
                    self.assertIsNone(node.child_entry(bad_inventory, bad_pages, 'c-cancel', expected_revision=revision))
                else:
                    with self.assertRaises(RuntimeError):
                        node.child_entry(bad_inventory, bad_pages, 'c-cancel', expected_revision=revision)

    def test_cleanup_preserves_original_failure_but_refuses_failed_success_cleanup(self):
        def refused():
            raise ValueError('cleanup')
        record = {}
        with self.assertRaisesRegex(RuntimeError, '^original$'):
            with node.owned_cleanup(record) as cleanup:
                cleanup.callback(refused)
                raise RuntimeError('original')
        self.assertTrue(record['originalFailurePreserved'])
        with self.assertRaisesRegex(ValueError, '^cleanup$'):
            with node.owned_cleanup({}) as cleanup:
                cleanup.callback(refused)

    def test_failed_invocation_completion_cannot_be_hidden_by_failed_close(self):
        class Process:
            def complete(self, _deadline):
                raise RuntimeError('actual-invocation-failure')

            def close(self):
                raise ValueError('secondary-close-failure')

        with self.assertRaisesRegex(RuntimeError, '^actual-invocation-failure$'):
            node.finish_call(SimpleNamespace(deadline=10**12), Process())

    def test_actual_empty_list_usage_schema_is_required(self):
        value = {'nextPageToken': None, 'nodeUsage': {'scope': 'node', 'unavailable': [],
                 'counters': {name: '0' for name in node.ACTIVE_COUNTERS}}}
        client = SimpleNamespace(call=lambda *args: {'data': value})
        self.assertEqual(node.usage(client, {'name': node.SERVICE}, idle=True), value)
        for unavailable in (False, True, ['provider']):
            value['nodeUsage']['unavailable'] = unavailable
            with self.subTest(unavailable=unavailable), self.assertRaises(RuntimeError):
                node.usage(client, {'name': node.SERVICE}, idle=True)


if __name__ == '__main__':
    unittest.main()
