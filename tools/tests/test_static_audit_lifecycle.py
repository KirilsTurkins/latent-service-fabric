"""Fault-oriented helper tests; real signed renewal is qualified by the native workflow."""
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.phase2_operator_process import WorkflowError
from tools.static_audit_lifecycle import Campaign, CampaignClient, MAX_COMMANDS, RECORDS, record_inventory


class Cancellation:
    def check(self):
        pass


class AuditLifecycleHelperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.chmod(0o700)
        self.cancellation = Cancellation()

    def record(self, name, value=b'preserved-record'):
        target = self.root / name
        target.write_bytes(value)
        target.chmod(0o600)
        return target

    def test_stopped_record_scan_is_read_only_bounded_and_exact(self):
        target = self.record('one')
        before = target.stat().st_ino, target.read_bytes()
        result = record_inventory(self.root, self.cancellation, time.monotonic() + 10)
        self.assertEqual(list(result), ['one'])
        self.assertEqual(result['one']['bytes'], len(before[1]))
        self.assertEqual((target.stat().st_ino, target.read_bytes()), before)
        with self.assertRaisesRegex(WorkflowError, 'scan-bound'):
            record_inventory(self.root, self.cancellation, time.monotonic() - 1)

    def test_missing_corrupt_oversized_and_linked_records_are_never_repaired(self):
        target = self.record('one', b'x' * 16385)
        with self.assertRaisesRegex(WorkflowError, 'private-record'):
            record_inventory(self.root, self.cancellation, time.monotonic() + 10)
        self.assertEqual(target.stat().st_size, 16385)
        target.write_bytes(b'original')
        alias = self.root / 'alias'
        os.link(target, alias)
        with self.assertRaisesRegex(WorkflowError, 'private-record'):
            record_inventory(self.root, self.cancellation, time.monotonic() + 10)
        self.assertEqual(alias.read_bytes(), b'original')
        alias.unlink()
        target.chmod(0o644)
        with self.assertRaisesRegex(WorkflowError, 'private-record'):
            record_inventory(self.root, self.cancellation, time.monotonic() + 10)
        self.assertEqual(target.read_bytes(), b'original')

    def test_record_count_refuses_one_more_than_the_actual_fixture_capacity(self):
        for number in range(RECORDS + 1):
            self.record(str(number))
        with self.assertRaisesRegex(WorkflowError, 'scan-bound'):
            record_inventory(self.root, self.cancellation, time.monotonic() + 10)
        self.assertEqual(len(list(self.root.iterdir())), RECORDS + 1)

    def test_cancellation_is_observed_without_deleting_stopped_history(self):
        target = self.record('one')
        cancellation = SimpleNamespace(check=lambda: (_ for _ in ()).throw(RuntimeError('cancelled')))
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            record_inventory(self.root, cancellation, time.monotonic() + 10)
        self.assertEqual(target.read_bytes(), b'preserved-record')

    def test_generic_or_unknown_exhaustion_is_not_qualified_as_affirmative_rejection(self):
        valid = {'category': 'platform-failure', 'outcomeKnown': True, 'error': {
            'code': 'resource-exhausted', 'details': [{'kind': 'audit-journal', 'fields': {'reason': 'audit-capacity'}}]}}
        Campaign.affirmative_rejection(valid)
        for change in ({'outcomeKnown': False}, {'error': {'code': 'resource-exhausted'}},
                       {'category': 'transport-failure'}, {'error': {'code': 'unavailable'}}):
            with self.subTest(change=change), self.assertRaises(WorkflowError):
                Campaign.affirmative_rejection({**valid, **change})

    def test_renewal_uses_current_generation_and_native_operation_surface(self):
        campaign = Campaign.__new__(Campaign)
        campaign.publication = 'publication:sha256:' + 'a' * 64
        campaign.package_digest = 'sha256:' + 'b' * 64
        campaign.args = SimpleNamespace(fixture=self.root)
        campaign.sequence, campaign.renewals = 0, []
        calls = []
        def call(*argv, **options):
            calls.append((argv, options))
            if argv[:2] == ('web', 'get'):
                return {'data': {'record': {'generation': '7'}}}
            operation = argv[argv.index('--operation-id') + 1]
            return {'outcomeKnown': True, 'data': {'operation': {'operationId': operation,
                'resultingGeneration': '8'}, 'auditAck': {'status': 'AUDIT_ACK_STATUS_DURABLE'}}}
        campaign.client = SimpleNamespace(call=call)
        receipt = campaign.renewal()
        argv = calls[-1][0]
        self.assertEqual(argv[argv.index('--expected-generation') + 1], '7')
        self.assertEqual(argv[argv.index('--operation-id') + 1], receipt['operationId'])
        self.assertEqual(campaign.renewals, [receipt])
        self.assertEqual(len(calls), 2)

    def test_failed_renewal_observes_original_record_without_replaying(self):
        campaign = Campaign.__new__(Campaign)
        campaign.publication, campaign.package_digest = 'selected-publication', 'selected-package'
        campaign.args = SimpleNamespace(fixture=self.root)
        campaign.sequence, campaign.renewals = 0, []
        calls = []
        def call(*argv, **options):
            calls.append(argv)
            if argv[:2] == ('web', 'get'):
                return {'data': {'record': {'generation': '7'}}}
            return {'category': 'platform-failure', 'outcomeKnown': True, 'data': {'auditAck': None},
                    'error': {'code': 'resource-exhausted', 'details': [
                        {'kind': 'audit-journal', 'fields': {'reason': 'audit-capacity'}}]}}
        campaign.client = SimpleNamespace(call=call)
        result = campaign.renewal(rejected=True)
        self.assertTrue(result['publicationGenerationUnchanged'])
        self.assertEqual([call[:2] for call in calls], [('web', 'get'), ('web', 'renew-evidence'), ('web', 'get')])
        self.assertEqual(campaign.renewals, [])

    def test_command_limit_is_checked_before_spawning_or_dispatch(self):
        parent = SimpleNamespace(executable='/not-invoked', cancellation=self.cancellation,
                                 deadline=time.monotonic() + 1000)
        client = CampaignClient(parent, self.root, self.root / 'fixture')
        client.calls = MAX_COMMANDS
        with patch('tools.static_audit_lifecycle.Client.call') as call:
            with self.assertRaisesRegex(WorkflowError, 'command-bound'):
                client.call('node', 'get', 'node')
            call.assert_not_called()
        self.assertEqual(client.trace, [])

    def test_expiry_requires_exact_native_reason_and_never_replays_or_serves_bytes(self):
        cases = ('valid', 'unknown', 'generic-conflict', 'busy', 'capacity', 'transport',
                 'receipt', 'audit-ack', 'changed-route', 'changed-journal', 'served-content')
        for case in cases:
            with self.subTest(case=case):
                campaign = Campaign.__new__(Campaign)
                campaign.client_root = self.root / case
                campaign.client_root.mkdir(mode=0o700)
                campaign.hosts, campaign.node = {'csr': 'docs.test'}, object()
                campaign.sequence, campaign.last_renewed_at = 0, 0
                current = {'trigger': {'generation': '7', 'manifest': {'identity': 'original'}},
                           'stateVersion': '11', 'durability': 'confirmed'}
                valid = {'category': 'platform-failure', 'outcomeKnown': True, 'requestDispatched': True,
                         'data': {}, 'error': {'code': 'state-conflict', 'details': [
                             {'kind': 'admission.currentness', 'fields': {'reason': 'signature-stale-proof'}}]}}
                if case == 'unknown':
                    valid['outcomeKnown'] = False
                elif case == 'generic-conflict':
                    valid['error']['details'] = []
                elif case == 'busy':
                    valid['error']['details'][0]['fields']['reason'] = 'admission-authority-busy'
                elif case == 'capacity':
                    valid['error']['code'] = 'resource-exhausted'
                elif case == 'transport':
                    valid['category'] = 'transport-failure'
                elif case == 'receipt':
                    valid['data']['receipt'] = {'operationId': 'possibly-committed'}
                elif case == 'audit-ack':
                    valid['data']['auditAck'] = {'status': 'outcome-unknown', 'attemptSequence': '32'}
                calls, samples = [], []

                def call(*argv, **options):
                    calls.append((argv, options))
                    if argv[:2] == ('trigger', 'get'):
                        value = json.loads(json.dumps(current))
                        if case == 'changed-route' and len(calls) > 1:
                            value['trigger']['generation'] = '8'
                        return {'data': value}
                    self.assertEqual(argv[:2], ('trigger', 'apply'))
                    self.assertEqual(options['codes'], (4,))
                    self.assertEqual(argv[argv.index('--expected-generation') + 1], '7')
                    self.assertEqual(argv[argv.index('--expected-state-version') + 1], '11')
                    self.assertEqual(json.loads(Path(argv[2]).read_text()), current['trigger']['manifest'])
                    return valid

                def sample():
                    samples.append(1)
                    return {}, {'audit_next_sequence': '34' if case == 'changed-journal' and len(samples) > 1 else '33',
                                'audit_retained_records': '32', 'audit_retained_bytes': '4096'}

                campaign.sample = sample
                campaign.client = SimpleNamespace(call=call, cancellation=self.cancellation,
                                                   deadline=time.monotonic() + 10)
                output = (b'forbidden-content' if case == 'served-content' else b'', {})
                with patch('tools.static_audit_lifecycle.http_response', return_value=output) as http:
                    if case == 'valid':
                        result = campaign.expire()
                        self.assertEqual((result['GET'], result['HEAD']), (503, 503))
                        self.assertEqual(result['reason'], 'signature-stale-proof')
                        self.assertEqual(result['platformCode'], 'state-conflict')
                        self.assertTrue(result['probe']['routeUnchanged'] and result['probe']['journalUnchanged'])
                        self.assertEqual(result['probe']['expectedGeneration'], '7')
                        self.assertEqual(result['probe']['expectedStateVersion'], '11')
                        self.assertEqual([item.kwargs['method'] for item in http.call_args_list], ['GET', 'HEAD'])
                        self.assertTrue(all(item.kwargs['expected'] == 503 for item in http.call_args_list))
                    else:
                        with self.assertRaises(WorkflowError):
                            campaign.expire()
                        if case != 'served-content':
                            http.assert_not_called()
                dispatched = [argv for argv, _ in calls if argv[:2] == ('trigger', 'apply')]
                self.assertEqual(len(dispatched), 1)
                self.assertEqual(campaign.sequence, 1)
                if case == 'valid':
                    self.assertEqual(result['probe']['operationId'],
                                     dispatched[0][dispatched[0].index('--operation-id') + 1])
                    self.assertEqual(len(calls), 3)
                    self.assertEqual(len(samples), 2)


    def test_separate_receipt_is_lossless_private_and_keeps_parent_within_original_bound(self):
        import hashlib
        import stat
        from tools.phase2_operator_process import bounded_receipt
        from tools.static_audit_lifecycle import retain_receipt

        report = {'schemaVersion': 'latent.static.audit-lifecycle.qualification.v1', 'passed': True,
            'profile': 'linux-signed-static-32-records-30-second-proof-age', 'multiDaySoak': False,
            'epochs': ['first', 'second'], 'shutdowns': [{'reaped': True}] * 3,
            'nextSequence': '71', 'historyComplete': False,
            'commands': [{'argv': ['web', 'renew-evidence'], 'outcomeKnown': False,
                          'auditAck': {'status': 'OutcomeUnknown'}, 'receiptDigest': None}],
            'boundedFixtureEvidence': 'x' * 60000}
        with self.assertRaisesRegex(WorkflowError, 'receipt-byte-bound'):
            bounded_receipt({'existingEvidence': 'y' * 55000, 'auditLifecycle': report})
        path = self.root / 'audit-lifecycle-receipt.json'
        reference = retain_receipt(report, path)
        raw = path.read_bytes()
        self.assertEqual(json.loads(raw), report)
        self.assertEqual(reference['receiptSha256'], 'sha256:' + hashlib.sha256(raw).hexdigest())
        self.assertEqual(reference['receiptBytes'], len(raw))
        self.assertEqual(reference['receiptFile'], path.name)
        self.assertNotIn(str(self.root), json.dumps(reference))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertLessEqual(len(raw), 65536)
        self.assertLessEqual(len(bounded_receipt(reference).encode()), 1024)
        self.assertLessEqual(len(bounded_receipt({'existingEvidence': 'y' * 55000,
                                                'auditLifecycle': reference}).encode()), 65536)
        self.assertIs(json.loads(raw)['commands'][0]['outcomeKnown'], False)

    def test_separate_receipt_refuses_oversize_and_unqualified_reports_before_creation(self):
        from tools.static_audit_lifecycle import retain_receipt

        path = self.root / 'audit-lifecycle-receipt.json'
        for value, reason in (
            ({'schemaVersion': 'latent.static.audit-lifecycle.qualification.v1',
              'passed': True, 'payload': '\u00e9' * 40000}, 'receipt-byte-bound'),
            ({'schemaVersion': 'latent.static.audit-lifecycle.qualification.v1',
              'passed': False}, 'receipt-not-qualified'),
            ({'schemaVersion': 'wrong', 'passed': True}, 'receipt-not-qualified'),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(WorkflowError, reason):
                retain_receipt(value, path)
            self.assertFalse(path.exists())

    def test_separate_receipt_never_overwrites_existing_or_linked_evidence(self):
        from tools.static_audit_lifecycle import retain_receipt

        value = {'schemaVersion': 'latent.static.audit-lifecycle.qualification.v1', 'passed': True,
            'profile': 'controlled-fixture', 'multiDaySoak': False, 'epochs': [], 'shutdowns': [],
            'nextSequence': '1', 'historyComplete': False}
        original = self.record('original.json', b'original-evidence')
        alias = self.root / 'linked.json'
        alias.symlink_to(original)
        dangling = self.root / 'dangling.json'
        dangling.symlink_to(self.root / 'absent.json')
        for path in (original, alias, dangling):
            with self.subTest(path=path.name), self.assertRaises(FileExistsError):
                retain_receipt(value, path)
        self.assertEqual(original.read_bytes(), b'original-evidence')
        self.assertTrue(alias.is_symlink() and dangling.is_symlink())
        self.assertFalse((self.root / 'absent.json').exists())


if __name__ == '__main__':
    unittest.main()
