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


if __name__ == '__main__':
    unittest.main()
