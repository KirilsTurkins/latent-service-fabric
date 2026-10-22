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
    def test_failed_child_audit_retains_raw_page_and_live_inventory_before_original_refusal(self):
        from unittest.mock import patch
        page = {'category': 'success', 'outcomeKnown': True, 'requestDispatched': True,
            'data': {'page': {'nextPageToken': None}, 'records': [], 'coverage': {
                'epoch': 'a' * 32, 'retainedFloor': '1', 'highWatermark': '0', 'scanned': '0',
                'droppedObservations': '1', 'unknownOutcomes': '1',
                'previousSessionLossUnknown': False, 'stop': 'AUDIT_PAGE_STOP_END'}}}
        inventory = {'topology': {'available': True, 'complete': True,
            'entries': [{'name': name, 'activeCount': '1'} for name in node.LIVE]}}
        client = SimpleNamespace(deadline=10**12, call=lambda *args: page if args[0] == 'audit'
            else {'data': {'inventory': inventory}})
        process = SimpleNamespace(authoring_activation='c-retention', authoring_started_unix_millis=1,
            owner=SimpleNamespace(exited=lambda: False))
        with tempfile.TemporaryDirectory() as directory, patch.object(node, 'selected_revision', return_value={}):
            output = Path(directory)
            with self.assertRaisesRegex(RuntimeError, '^c-thread-positive-audit-known-coverage$'):
                node.wait_child(client, process, None, {}, output)
            self.assertEqual(json.loads((output / 'child-audit-c-retention-0-1.json').read_bytes()), page)
            self.assertEqual(json.loads((output / 'child-inventory-c-retention-0.json').read_bytes()), inventory)

    @staticmethod
    def positive_child_model():
        revision = {'publicationId': 'publication:sha256:' + '1' * 64,
            'releaseDigest': 'sha256:' + '2' * 64, 'revisionId': 'revision-v1:sha256:' + '3' * 64,
            'routeGeneration': '7'}
        inventory = {'topology': {'available': True, 'complete': True,
            'entries': [{'name': name, 'activeCount': '1'} for name in node.LIVE]}}
        records = []
        for sequence, capability, operation in ((1, node.NATIVE, 'start'), (2, node.ACTIVATION, 'observe')):
            records.append({'epoch': 'a' * 32, 'sequence': str(sequence), 'data': {'observation': {
                'kind': 'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_PROVIDER_OUTCOME', 'identities': {
                    'publicationId': revision['publicationId'], 'componentDigest': revision['releaseDigest'],
                    'revision': revision['revisionId'], 'routeGeneration': '7', 'capability': {
                        'activation': 'c-positive', 'rootActivation': 'c-positive',
                        'service': 'examples/' + node.SERVICE, 'capability': capability,
                        'providerProfile': node.PROVIDERS[capability][1], 'operation': operation,
                        'providerOutcome': 'AUDIT_PROVIDER_OUTCOME_HOST_COMPLETED'}}}}})
        pages = [{'category': 'success', 'outcomeKnown': True, 'requestDispatched': True, 'data': {
            'records': records, 'page': {'nextPageToken': None}, 'coverage': {
                'epoch': 'a' * 32, 'retainedFloor': '1', 'highWatermark': '2', 'scanned': '2',
                'droppedObservations': '328', 'unknownOutcomes': '0',
                'previousSessionLossUnknown': False, 'stop': 'AUDIT_PAGE_STOP_END'}}}]
        return inventory, pages, revision

    def test_retained_current_child_pair_is_positive_evidence_with_raw_loss_not_losslessness(self):
        inventory, pages, revision = self.positive_child_model()
        original = copy.deepcopy(pages)
        result = node.child_entry(inventory, pages, 'c-positive', expected_revision=revision, positive_only=True)
        self.assertEqual(result['nativeStartCompletedSequence'], 1)
        self.assertEqual(result['childObserveCompletedSequence'], 2)
        self.assertEqual(result['auditCoverage']['droppedObservationsByPage'], ['328'])
        self.assertTrue(result['auditCoverage']['optionalObservationLossReported'])
        self.assertFalse(result['auditCoverage']['losslessCaptureClaimed'])
        self.assertFalse(result['auditCoverage']['negativeEvidenceClaimed'])
        self.assertEqual(pages, original)
        with self.assertRaisesRegex(RuntimeError, '^c-thread-lossless-current-audit-required$'):
            node.child_entry(inventory, pages, 'c-positive', expected_revision=revision)
        for missing in (0, 1):
            partial = copy.deepcopy(pages)
            del partial[0]['data']['records'][missing]
            self.assertIsNone(node.child_entry(inventory, partial, 'c-positive',
                expected_revision=revision, positive_only=True))

    def test_positive_child_barrier_refuses_unknown_coverage_and_stale_or_fabricated_pairs(self):
        inventory, pages, revision = self.positive_child_model()
        for name in ('epoch', 'session', 'unknown', 'saturated', 'bool-counter', 'noncanonical-counter',
                     'incomplete', 'scan', 'duplicate', 'order', 'high', 'revision', 'provider', 'outcome'):
            bad = copy.deepcopy(pages)
            coverage, records = bad[0]['data']['coverage'], bad[0]['data']['records']
            if name == 'epoch': coverage['epoch'] = 'b' * 32
            elif name == 'session': coverage['previousSessionLossUnknown'] = True
            elif name == 'unknown': coverage['unknownOutcomes'] = '1'
            elif name == 'saturated': coverage['droppedObservations'] = str(2**64 - 1)
            elif name == 'bool-counter': coverage['droppedObservations'] = True
            elif name == 'noncanonical-counter': coverage['droppedObservations'] = '0328'
            elif name == 'incomplete': bad[0]['data']['page']['nextPageToken'] = 'not-complete'
            elif name == 'scan': coverage['scanned'] = '1'
            elif name == 'duplicate': records.append(copy.deepcopy(records[-1])); coverage['scanned'] = '3'
            elif name == 'order': records.reverse()
            elif name == 'high': records[-1]['sequence'] = '3'
            elif name == 'revision': records[-1]['data']['observation']['identities']['revision'] = 'foreign'
            elif name == 'provider': records[-1]['data']['observation']['identities']['capability']['providerProfile'] = 'foreign'
            else: records[-1]['data']['observation']['identities']['capability']['providerOutcome'] = 'AUDIT_PROVIDER_OUTCOME_REJECTED'
            with self.subTest(name=name):
                if name == 'outcome':
                    self.assertIsNone(node.child_entry(inventory, bad, 'c-positive',
                        expected_revision=revision, positive_only=True))
                else:
                    with self.assertRaises(RuntimeError):
                        node.child_entry(inventory, bad, 'c-positive', expected_revision=revision, positive_only=True)
        self.assertIsNone(node.child_entry(inventory, pages, 'stale', expected_revision=revision, positive_only=True))
        with self.assertRaisesRegex(RuntimeError, '^c-thread-closed-audit-evidence-mode$'):
            node.child_entry(inventory, pages, 'c-positive', expected_revision=revision, positive_only='true')

    def test_positive_child_cursor_requires_one_frozen_session_and_retains_each_actual_loss_count(self):
        inventory, pages, revision = self.positive_child_model()
        first, last = copy.deepcopy(pages[0]), copy.deepcopy(pages[0])
        first['data']['records'] = first['data']['records'][:1]
        last['data']['records'] = last['data']['records'][1:]
        first['data']['coverage'].update(scanned='1', droppedObservations='327', stop='AUDIT_PAGE_STOP_RECORD_LIMIT')
        last['data']['coverage']['scanned'] = '1'
        first['data']['page']['nextPageToken'] = 'fixed-cursor'
        pair = [first, last]
        witness = node.child_entry(inventory, pair, 'c-positive', expected_revision=revision, positive_only=True)
        self.assertEqual(witness['auditCoverage']['droppedObservationsByPage'], ['327', '328'])
        for name in ('epoch', 'high', 'decreasing-loss', 'early-end', 'cycle'):
            bad = copy.deepcopy(pair)
            if name == 'epoch': bad[-1]['data']['coverage']['epoch'] = 'b' * 32
            elif name == 'high': bad[-1]['data']['coverage']['highWatermark'] = '3'
            elif name == 'decreasing-loss': bad[-1]['data']['coverage']['droppedObservations'] = '326'
            elif name == 'early-end': bad[0]['data']['page']['nextPageToken'] = None
            else: bad.append(copy.deepcopy(last)); bad[1]['data']['page']['nextPageToken'] = 'fixed-cursor'
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                node.child_entry(inventory, bad, 'c-positive', expected_revision=revision, positive_only=True)

    def test_explicit_fixed_product_source_is_checked_without_falling_back_to_v1(self):
        from unittest.mock import Mock, patch
        from tools.phase2_operator_process import WorkflowError
        from tools import qualify_c_thread_runtime as qualification
        compiled = {'sha256': 'sha256:' + '1' * 64, 'files': 3, 'bytes': 32,
            'scope': 'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
            'hermetic': False, 'implicitCompilerInputs': 'not-attested'}
        identity = {'sha256': 'sha256:' + '2' * 64, 'bytes': 1}
        products = {'latent': identity, 'latentd': identity, 'examples/package': identity,
            'examples/capsule_contracts': identity, 'examples/capsule_authoring': identity}
        selected = SimpleNamespace(SOURCE='a' * 40,
            verify_prepared=Mock(return_value={'compiledSource': 'a' * 40, 'products': products}),
            native_products=Mock(return_value={'controlled': 'source-routing-model'}))
        snapshot = {'native': compiled, 'materials': {'controlled/' + str(i): identity for i in range(148)}}
        def expected_source(source):
            self.assertEqual(source, selected.SOURCE)
            return compiled
        with patch.object(qualification, 'git_source_identity', side_effect=expected_source), \
                patch.object(qualification, 'source_identity', return_value=compiled), \
                patch.object(qualification, 'read_json', return_value=snapshot), \
                patch.object(qualification, 'file_identity', return_value=identity):
            before, proof, tools = qualification.native_evidence(selected, Path('controlled'))
            self.assertEqual(proof['compiledSourceRevision'], selected.SOURCE)
            self.assertEqual(proof['compiledNativeSource'], proof['consumerNativeSource'])
            self.assertEqual(proof['auxiliaryMaterialsByteExact'], 148)
            self.assertEqual(before['compiledSource'], selected.SOURCE)
            self.assertEqual(tools, {'controlled': 'source-routing-model'})
            selected.native_products.reset_mock()
            selected.verify_prepared.return_value['compiledSource'] = 'b' * 40
            with self.assertRaisesRegex(WorkflowError, 'c-thread-all-five-products-from-exact-native-producer'):
                qualification.native_evidence(selected, Path('controlled'))
            selected.native_products.assert_not_called()
            selected.verify_prepared.return_value['compiledSource'] = selected.SOURCE
            with patch.object(qualification, 'source_identity', return_value={**compiled, 'bytes': 33}):
                with self.assertRaisesRegex(WorkflowError, 'c-thread-current-native-source-must-be-byte-exact'):
                    qualification.native_evidence(selected, Path('controlled'))
            selected.native_products.assert_not_called()

    def test_current_native_source_equality_is_required_before_any_product_use(self):
        from unittest.mock import Mock, patch
        from tools import qualify_c_thread_runtime as qualification
        from tools import host_codec_native_products as guard
        compiled = json.loads((qualification.ROOT /
            'docs/testing/evidence/host-codec-native-7b-2026-10-22.json').read_bytes())['compiledNativeSource']
        products = Mock(SOURCE=guard.SOURCE)
        products.verify_prepared.return_value = {'compiledSource': guard.SOURCE, 'products': {
            name: {'sha256': 'sha256:' + '0'*64, 'bytes': 1} for name in
            ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')}}
        products.native_products.return_value = {'latentd': Path('unexecuted')}
        proof = {'compiledSourceRevision': guard.SOURCE,
                 'compiledNativeSource': compiled, 'consumerNativeSource': compiled,
                 'compiledSourceByteExact': True, 'reviewedSourceChanges': []}
        with patch.object(qualification, 'git_source_identity', return_value=compiled), \
                patch.object(qualification, 'source_identity', return_value=compiled):
            self.assertEqual(qualification.assert_current(qualification.ROOT), proof)
        for field in ('sha256', 'files', 'bytes', 'scope', 'hermetic', 'implicitCompilerInputs'):
            with self.subTest(field=field), \
                    patch.object(qualification, 'git_source_identity', return_value=compiled), \
                    patch.object(qualification, 'source_identity', return_value={**compiled, field: 'foreign'}), \
                    self.assertRaisesRegex(RuntimeError, 'must-be-byte-exact'):
                qualification.assert_current(qualification.ROOT)
        auxiliary = {f'controlled-{i}': {'sha256': 'sha256:'+'0'*64, 'bytes': 1} for i in range(148)}
        snapshot = {'native': compiled, 'materials': auxiliary}
        with patch.object(qualification, 'assert_current', return_value=proof), \
                patch.object(qualification, 'read_json', return_value=snapshot), \
                patch.object(qualification, 'file_identity', return_value=next(iter(auxiliary.values()))):
            before, actual, native = qualification.native_evidence(products, Path('prepared'))
        self.assertEqual((before, actual, native),
                         (products.verify_prepared.return_value, proof, products.native_products.return_value))
        self.assertEqual(actual['auxiliaryMaterialsByteExact'], 148)
        self.assertEqual(actual['perProductCompilation'], {name: {'sourceRevision': guard.SOURCE,
            'nativeSource': compiled, 'identity': identity}
            for name, identity in products.verify_prepared.return_value['products'].items()})
        products.native_products.reset_mock()
        for drift in ('missing-product', 'foreign-source', 'old-auxiliary-count'):
            bad_before = copy.deepcopy(products.verify_prepared.return_value)
            bad_snapshot = copy.deepcopy(snapshot)
            if drift == 'missing-product': del bad_before['products']['latentd']
            elif drift == 'foreign-source': bad_before['compiledSource'] = 'f' * 40
            else: bad_snapshot['materials'].pop('controlled-147')
            with self.subTest(drift=drift), \
                    patch.object(products, 'verify_prepared', return_value=bad_before), \
                    patch.object(qualification, 'assert_current', return_value=proof), \
                    patch.object(qualification, 'read_json', return_value=bad_snapshot), \
                    patch.object(qualification, 'file_identity', return_value=next(iter(auxiliary.values()))), \
                    self.assertRaises(RuntimeError):
                qualification.native_evidence(products, Path('prepared'))
            products.native_products.assert_not_called()
        reviewed = json.loads((qualification.ROOT /
            'docs/testing/evidence/c-thread-native-rustfmt-2026-10-21.json').read_text())
        with patch.object(qualification, 'git_source_identity', return_value=copy.deepcopy(compiled)), \
                patch.object(qualification, 'source_identity', return_value=reviewed['formattedConsumerSource']), \
                self.assertRaisesRegex(RuntimeError, 'must-be-byte-exact'):
            qualification.native_evidence(products, Path('prepared'))
        products.native_products.assert_not_called()
        products.SOURCE = 'f' * 40
        with patch.object(qualification, 'assert_current', return_value=proof), \
                self.assertRaisesRegex(RuntimeError, 'exact-native-producer'):
            qualification.native_evidence(products, Path('prepared'))
        products.native_products.assert_not_called()
        products.verify_prepared.side_effect = RuntimeError('original receipt drift')
        with patch.object(qualification, 'assert_current', side_effect=AssertionError('receipt must be first')), \
                self.assertRaisesRegex(RuntimeError, '^original receipt drift$'):
            qualification.native_evidence(products, Path('prepared'))
        products.native_products.assert_not_called()

    def test_formatter_source_exception_is_exact_full_tree_and_digest_bound(self):
        from unittest.mock import patch
        from tools import c_thread_native_source as native_source
        from tools.rust_capsule_project import ROOT
        raw = (ROOT / native_source.REVIEW).read_bytes()
        proof = json.loads(raw)
        result = native_source.compatibility(proof['compiledNativeSource'], proof['formattedConsumerSource'])
        self.assertIs(result['compiledSourceByteExact'], False)
        self.assertEqual(len(result['reviewedFormatting']), 2)
        self.assertEqual(result['otherNativeFilesByteExact'], 3322)
        for field in ('sha256', 'bytes', 'files', 'scope', 'hermetic', 'implicitCompilerInputs'):
            bad = dict(proof['formattedConsumerSource'], **{field: 'foreign'})
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'exact-reviewed-formatting'):
                native_source.compatibility(proof['compiledNativeSource'], bad)
        with self.assertRaisesRegex(RuntimeError, 'exact-reviewed-formatting'):
            native_source.compatibility(proof['formattedConsumerSource'], proof['compiledNativeSource'])
        with patch.object(native_source, 'read_file', return_value=raw + b'\n'), \
                self.assertRaisesRegex(RuntimeError, 'format-review-identity'):
            native_source.compatibility(proof['compiledNativeSource'], proof['formattedConsumerSource'])

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
