"""Original nonzero cleanup exit stays failed; the appendix is narrowly pinned."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.optimization_evidence.common import EvidenceError
from tools.optimization_kubernetes import failure_evidence, failure_full, model
from tools.optimization_kubernetes.failure_full_support import journal, prefix

FIXTURE = Path(__file__).parent / 'fixtures/kubernetes-full01-failed-exec.json'


def original_shape():
    return {'profile': 'full', 'run_id': 'full-01', 'owner': failure_full.OWNER,
        'source': {'commit': failure_full.SOURCE, 'tree': failure_full.TREE, 'clean': True,
                   'cargo_lock_sha256': model.HISTORICAL_LOCK},
        'source_after': None, 'failure': dict(failure_full.FAILURE), 'groups': [{} for _ in range(5)], 'clients': [],
        'plan': model.plan('full', owner=failure_full.OWNER, startup_protocol=model.HISTORICAL_STARTUP_PROTOCOL),
        'preparations': [{} for _ in range(50)], 'transfers': [{} for _ in range(12)],
        'cleanup': {'namespace_absent': True, 'private_tls_removed': True, 'remaining_pods': {},
                    'remote_removed': False, 'failure_diagnostics': [], 'pods': [{} for _ in range(45)],
                    'errors': [{'stage': 'owned-resources', 'type': 'EvidenceError',
                                'reason': 'kubernetes-worker-exec-not-clean'}]}}


class FailedFullTests(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.row = json.loads(self.raw)

    def check_record(self, row):
        return journal.failed_exec(row, self.row['container_id'],
            int(self.row['started_nanos']), int(self.row['finished_nanos']))

    def test_actual_failed_record_bytes_and_nonzero_exit_are_retained(self):
        self.assertEqual(len(self.raw), 3685)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(),
                         'd9206afad4c5b714972726e0f13cf5e74e03a40be3a250a244efd1d2726c2ca0')
        result, _, _ = self.check_record(self.row)
        self.assertEqual(result['original_failure'], 'EvidenceError')
        self.assertEqual(result['final_inspect']['ExitCode'], 1)
        self.assertFalse(result['final_inspect']['Running'])
        self.assertIn(b'code = NotFound', result['stderr'])
        self.assertNotIn('recovered_failure', result)

    def test_failed_record_identity_and_action_cannot_be_generalized(self):
        changes = (lambda row: row.update(ordinal=1870), lambda row: row.update(failure=None),
                   lambda row: row.update(container_id='0' * 64), lambda row: row.update(timeout_seconds=21),
                   lambda row: row['argv'].__setitem__(1, 'rm'),
                   lambda row: row['argv'].__setitem__(2, '0' * 64))
        for mutate in changes:
            row = deepcopy(self.row)
            mutate(row)
            with self.subTest(mutate=mutate), self.assertRaises(EvidenceError):
                self.check_record(row)

    def test_failed_exec_still_requires_complete_closed_http_receipts(self):
        for record in range(3):
            for key, value in (('connection_closed', False), ('response_complete', False),
                               ('response_sha256', 'sha256:' + '0' * 64)):
                row = deepcopy(self.row)
                row['records'][record]['receipt'][key] = value
                with self.subTest(record=record, key=key), self.assertRaises(EvidenceError):
                    self.check_record(row)

    def test_failed_exec_raw_response_hash_and_length_are_mandatory(self):
        for key, value in (('sha256', 'sha256:' + '0' * 64), ('bytes', '1')):
            row = deepcopy(self.row)
            row['records'][1]['response'][key] = value
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                self.check_record(row)

    def test_only_original_failed_full_shape_and_protocol_are_eligible(self):
        suite = original_shape()
        failure_full.original_shape(suite)
        changes = (lambda s: s.update(profile='smoke'), lambda s: s.update(run_id='full-02'),
                   lambda s: s.update(failure=None), lambda s: s.update(source_after=s['source']),
                   lambda s: s['source'].update(tree='0' * 40), lambda s: s['source'].update(clean=False),
                   lambda s: s['groups'].append({}), lambda s: s['clients'].append({}),
                   lambda s: s['cleanup'].update(remote_removed=True),
                   lambda s: s.update(plan=model.plan('full', owner=s['owner'])))
        for mutate in changes:
            changed = deepcopy(suite)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(EvidenceError):
                failure_full.original_shape(changed)

    def test_whole_original_input_is_pinned_not_just_its_claimed_metadata(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'suite.json').write_bytes(b'{}\n')
            with self.assertRaisesRegex(EvidenceError, 'original-byte-identity'):
                failure_full.original_bytes(root, 'suite.json')

    def test_partial_client_record_is_never_treated_as_complete_line(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'events.jsonl'
            path.write_bytes(b'{"event":"ready"}')
            with self.assertRaisesRegex(EvidenceError, 'line-bound'):
                prefix._rows(path)


class FailedFullDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.suite = original_shape()
        self.write_suite()

    def write_suite(self):
        (self.root / 'suite.json').write_text(json.dumps(self.suite), encoding='utf-8')

    def test_exact_full01_dispatch_forwards_dependencies_and_original_receipt(self):
        receipt = {'status': 'owned-cleanup-completed'}
        with patch.object(failure_full, 'validate', return_value=receipt) as delegated:
            actual = failure_evidence.validate(self.root, 'bootstrap', build_root='build', docker_root='docker')
        self.assertIs(actual, receipt)
        delegated.assert_called_once_with(self.root, Path('bootstrap'), Path('build'), Path('docker'))

    def test_full01_dispatch_requires_both_original_dependencies(self):
        for dependencies in ({}, {'build_root': 'build'}, {'docker_root': 'docker'}):
            with self.subTest(dependencies=dependencies), patch.object(failure_full, 'validate') as delegated:
                with self.assertRaisesRegex(EvidenceError, 'full-dependency-required'):
                    failure_evidence.validate(self.root, 'bootstrap', **dependencies)
                delegated.assert_not_called()

    def test_full01_dispatch_rejects_crossed_scope_before_delegation(self):
        changes = (lambda s: s.update(profile='smoke'), lambda s: s.update(run_id='full-02'),
                   lambda s: s.update(owner='lsf-112-000000000000'),
                   lambda s: s['source'].update(commit='0' * 40),
                   lambda s: s['source'].update(tree='0' * 40),
                   lambda s: s.update(plan=model.plan('full', owner=s['owner'])))
        for mutate in changes:
            self.suite = original_shape()
            mutate(self.suite)
            self.write_suite()
            with self.subTest(mutate=mutate), patch.object(failure_full, 'validate') as delegated:
                with self.assertRaises(EvidenceError):
                    failure_evidence.validate(self.root, 'bootstrap', build_root='build', docker_root='docker')
                delegated.assert_not_called()


if __name__ == '__main__':
    unittest.main()
