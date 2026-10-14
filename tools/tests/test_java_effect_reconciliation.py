import base64
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest import mock

from tools.java_transaction_qualification import configuration as cfg, effect_reconciliation as flow


def encoded(raw):
    return {'encoding': 'base64', 'data': base64.b64encode(raw).decode()}


def reply(command, data):
    return {'schemaVersion': 'latent.cli.result.v1', 'command': command, 'category': 'success',
            'requestDispatched': True, 'outcomeKnown': True, 'error': None, 'data': data}


def fixture():
    publication = 'publication:sha256:' + '1' * 64
    committed = {'effect-ids': ['e' * 64], 'command-id': 'c' * 64, 'attempt-id': 'a' * 64}
    before = {'effectId': 'e' * 64, 'commandId': 'c' * 64, 'commandAttemptId': 'a' * 64,
        'dispatchAttempt': 2, 'ownerEpoch': '10', 'claimGeneration': '2', 'disposition': flow.UNCERTAIN,
        'providerReceipt': None, 'managementOperationReceiptId': None, 'recordVersion': encoded(b'v' * 32)}
    policy = 'sha256:' + '3' * 64
    original = flow.original(publication, 'java-original-ambiguous', before['effectId'], before['recordVersion'], policy)
    plan = {'original': original, 'planDigest': encoded(b'p' * 32), 'managementSequence': 1,
        'ownerEpoch': '10', 'claimGeneration': '2', 'dispatchAttempt': 2, 'expiresAtUnixMillis': '31000',
        'preparedAtUnixMillis': '1000', 'before': flow.UNCERTAIN,
        'safety': 'EFFECT_PLAN_SAFETY_PROVIDER_RECEIPT_LOOKUP', 'dedupValidUntilUnixMillis': None}
    plan['encodedPlan'] = encoded(flow.plan_bytes(plan))
    receipt = {'operationId': flow.OPERATION, 'receiptId': 'effect-management:sha256:' + '4' * 64,
        'mutation': flow.ACTION, 'namespace': original['effect']['command']['namespace'],
        'authenticatedOperator': flow.lifecycle.operator_actor(), 'beforeVersion': original['expectedVersion'],
        'afterVersion': encoded(b'w' * 32), 'completedAtUnixMillis': '1002', 'recordId': 'e' * 64,
        'policyDigest': policy, 'disposition': 'STATE_OPERATION_DISPOSITION_COMMITTED',
        'effect': {'originalPlan': plan, 'before': flow.UNCERTAIN, 'after': flow.ACKNOWLEDGED,
            'fact': 'EFFECT_MANAGEMENT_FACT_PROVIDER_CONFIRMED', 'providerReceipt': 'actual-provider-receipt',
            'providerObservedAtUnixMillis': '1001'}}
    audit = {'status': 'AUDIT_ACK_STATUS_DURABLE', 'attemptSequence': '13'}
    planning = reply('state plan-effect', {'plan': plan, 'replayed': False, 'auditAcknowledgement': audit})
    recovery = {'family': 'state', 'operationId': flow.OPERATION, 'namespace': receipt['namespace'],
        'authorizationPublication': original['effect']['authorizationPublication'], 'recordId': receipt['recordId'],
        'expectedVersion': original['expectedVersion'], 'expectedPolicyDigest': policy, 'action': flow.ACTION,
        'originalEffectPlan': plan, 'automaticRetry': False}
    applying = reply('state apply-effect', {'receipt': receipt, 'replayed': False, 'auditAcknowledgement': audit,
                                          'recovery': recovery})
    lookup = reply('state effect-operation', {'stateReceipt': receipt, 'namespaceReceipt': None,
                                            'auditAcknowledgement': audit})
    return publication, committed, before, policy, planning, applying, lookup


class EffectReconciliationTests(unittest.TestCase):
    def test_one_actual_plan_apply_and_same_plan_receipt_use_original_cutoff_and_cas(self):
        publication, committed, before, policy, planning, applying, lookup = fixture()
        client = SimpleNamespace(deadline=50, call=mock.Mock(side_effect=[planning, applying, lookup]),
                                 evidence=SimpleNamespace(record=mock.Mock()))
        campaign = SimpleNamespace(client=client, peer=SimpleNamespace(current_http=True),
            node=SimpleNamespace(current_program='terminal', current_publication_program=True))
        with mock.patch.object(flow.time, 'monotonic', return_value=1), \
                mock.patch.object(flow.lifecycle, 'effect', return_value=deepcopy(before)) as effect, \
                mock.patch.object(flow.lifecycle, 'inspect_namespace', return_value={'namespacePolicyDigest': policy}) as namespace:
            self.assertEqual(flow.reconcile(campaign, publication, 'java-original-ambiguous', committed, before),
                             applying['data']['receipt'])
        effect.assert_called_once()
        namespace.assert_called_once()
        self.assertEqual(client.call.call_count, 3)
        self.assertEqual([row.args[:2] for row in client.call.call_args_list],
                         [('state', 'plan-effect'), ('state', 'apply-effect'), ('state', 'effect-operation')])
        self.assertTrue(all(row.kwargs == {'cutoff': 50} for row in client.call.call_args_list))
        self.assertNotIn('--retry-delay-millis', client.call.call_args_list[0].args)
        self.assertIn(before['recordVersion']['data'], client.call.call_args_list[0].args)
        self.assertEqual(client.call.call_args_list[1].args[-1], planning['data']['plan']['encodedPlan']['data'])
        self.assertEqual(client.call.call_args_list[2].args[-1], planning['data']['plan']['encodedPlan']['data'])

    def test_ambiguous_or_foreign_lookup_receipt_is_fatal_after_single_accepted_apply(self):
        publication, committed, before, policy, planning, applying, lookup = fixture()
        for field, value in [('stateReceipt', None), ('namespaceReceipt', {'foreign': True})]:
            changed = deepcopy(lookup)
            changed['data'][field] = value
            client = SimpleNamespace(deadline=50, call=mock.Mock(side_effect=[planning, applying, changed]),
                                     evidence=SimpleNamespace(record=mock.Mock()))
            campaign = SimpleNamespace(client=client, peer=SimpleNamespace(current_http=True),
                node=SimpleNamespace(current_program='terminal', current_publication_program=True))
            with mock.patch.object(flow.time, 'monotonic', return_value=1), \
                    mock.patch.object(flow.lifecycle, 'effect', return_value=before), \
                    mock.patch.object(flow.lifecycle, 'inspect_namespace', return_value={'namespacePolicyDigest': policy}):
                with self.assertRaises(ValueError):
                    flow.reconcile(campaign, publication, 'java-original-ambiguous', committed, before)
            self.assertEqual(client.call.call_count, 3)
            client.evidence.record.assert_not_called()

    def test_current_effect_must_remain_same_original_uncertain_attempt_before_plan(self):
        publication, committed, before, _, _, _, _ = fixture()
        for name, value in [('disposition', 'EFFECT_DISPOSITION_PENDING'), ('dispatchAttempt', 3),
                            ('effectId', 'f' * 64), ('commandId', 'f' * 64),
                            ('providerReceipt', 'unmatched'), ('managementOperationReceiptId', 'unmatched')]:
            client = SimpleNamespace(deadline=50, call=mock.Mock())
            campaign = SimpleNamespace(client=client, peer=SimpleNamespace(current_http=True),
                node=SimpleNamespace(current_program='terminal', current_publication_program=True))
            observed = deepcopy(before)
            observed[name] = value
            with mock.patch.object(flow.time, 'monotonic', return_value=1), \
                    mock.patch.object(flow.lifecycle, 'effect', return_value=observed), \
                    mock.patch.object(flow.lifecycle, 'inspect_namespace') as namespace:
                with self.assertRaises(ValueError):
                    flow.reconcile(campaign, publication, 'java-original-ambiguous', committed, before)
            namespace.assert_not_called()
            client.call.assert_not_called()

    def test_plan_selectors_kind_action_stamp_and_actual_encoded_plan_cannot_be_substituted(self):
        _, _, before, _, planning, _, _ = fixture()
        expected = deepcopy(planning['data']['plan']['original'])
        mutations = [('before', flow.ACKNOWLEDGED), ('safety', 'EFFECT_PLAN_SAFETY_ADMINISTRATOR_DECLARED'),
            ('ownerEpoch', '11'), ('claimGeneration', '3'), ('dispatchAttempt', 3),
            ('managementSequence', 0), ('dedupValidUntilUnixMillis', '30000'),
            ('encodedPlan', encoded(b'foreign-plan')), ('expiresAtUnixMillis', '31001')]
        for name, value in mutations:
            with self.subTest(name=name):
                changed = deepcopy(planning)
                changed['data']['plan'][name] = value
                with self.assertRaises(ValueError):
                    flow.plan(changed, expected, before)
        for name, value in [('operationId', 'different'), ('mutation', 'STATE_MUTATION_KIND_RETRY_KNOWN_FAILED_EFFECT'),
                            ('expectedPolicyDigest', 'sha256:' + '9' * 64), ('expectedVersion', encoded(b'f' * 32))]:
            with self.subTest(original=name):
                changed = deepcopy(planning)
                changed['data']['plan']['original'][name] = value
                with self.assertRaises(ValueError):
                    flow.plan(changed, expected, before)
        for name, value in [('clientKey', 'foreign'), ('entity', 'foreign'), ('sharedRecoveryScope', 'foreign')]:
            changed = deepcopy(planning)
            changed['data']['plan']['original']['effect']['command'][name] = value
            with self.assertRaises(ValueError):
                flow.plan(changed, expected, before)

    def test_receipt_requires_exact_real_operator_original_plan_and_positive_provider_fact(self):
        _, _, _, _, planning, applying, _ = fixture()
        plan = planning['data']['plan']
        mutations = [('authenticatedOperator', 'foreign'), ('recordId', 'f' * 64), ('operationId', 'foreign'),
            ('policyDigest', 'sha256:' + 'f' * 64), ('beforeVersion', encoded(b'f' * 32)),
            ('disposition', 'STATE_OPERATION_DISPOSITION_RECOVERY_REQUIRED')]
        for name, value in mutations:
            changed = deepcopy(applying)
            changed['data']['receipt'][name] = value
            with self.assertRaises(ValueError):
                flow.receipt(changed, 'state apply-effect', plan)
        for name, value in [('fact', 'EFFECT_MANAGEMENT_FACT_ADMINISTRATOR_TERMINATED'),
                            ('providerReceipt', None), ('providerObservedAtUnixMillis', None),
                            ('after', flow.UNCERTAIN), ('originalPlan', {})]:
            changed = deepcopy(applying)
            changed['data']['receipt']['effect'][name] = value
            with self.assertRaises(ValueError):
                flow.receipt(changed, 'state apply-effect', plan)
        changed = deepcopy(applying)
        changed['data']['recovery']['automaticRetry'] = True
        with self.assertRaises(ValueError):
            flow.receipt(changed, 'state apply-effect', plan)

    def test_unknown_transport_replayed_or_missing_durable_audit_is_fatal(self):
        _, _, before, _, planning, applying, _ = fixture()
        for name, value in [('category', 'transport-failure'), ('outcomeKnown', False),
                            ('requestDispatched', False), ('error', {'code': 'rpc-failed'})]:
            changed = deepcopy(planning)
            changed[name] = value
            with self.assertRaises(ValueError):
                flow.plan(changed, planning['data']['plan']['original'], before)
        for value in [None, {'status': 'AUDIT_ACK_STATUS_UNKNOWN', 'attemptSequence': '13'}]:
            changed = deepcopy(planning)
            changed['data']['auditAcknowledgement'] = value
            with self.assertRaises(ValueError):
                flow.plan(changed, planning['data']['plan']['original'], before)
        changed = deepcopy(applying)
        changed['data']['replayed'] = True
        with self.assertRaises(ValueError):
            flow.receipt(changed, 'state apply-effect', planning['data']['plan'])

    def test_failed_apply_is_never_retried_or_replanned(self):
        publication, committed, before, policy, planning, _, _ = fixture()
        client = SimpleNamespace(deadline=50, call=mock.Mock(side_effect=[planning, ValueError('original-failed-apply')]),
                                 evidence=SimpleNamespace(record=mock.Mock()))
        campaign = SimpleNamespace(client=client, peer=SimpleNamespace(current_http=True),
            node=SimpleNamespace(current_program='terminal', current_publication_program=True))
        with mock.patch.object(flow.time, 'monotonic', return_value=1), \
                mock.patch.object(flow.lifecycle, 'effect', return_value=before), \
                mock.patch.object(flow.lifecycle, 'inspect_namespace', return_value={'namespacePolicyDigest': policy}):
            with self.assertRaisesRegex(ValueError, 'original-failed-apply'):
                flow.reconcile(campaign, publication, 'java-original-ambiguous', committed, before)
        self.assertEqual(client.call.call_count, 2)
        client.evidence.record.assert_not_called()

    def test_legacy_pending_early_and_expired_cutoff_cannot_enable_reconciliation(self):
        publication, committed, before, _, _, _, _ = fixture()
        for current, program, peer in [(True, 'early-http', True), (True, 'pending-close', True),
                                       (False, 'terminal', True), (True, 'terminal', False)]:
            client = SimpleNamespace(deadline=50, call=mock.Mock())
            campaign = SimpleNamespace(client=client, peer=SimpleNamespace(current_http=peer),
                node=SimpleNamespace(current_program=program, current_publication_program=current))
            with self.assertRaises(ValueError):
                flow.reconcile(campaign, publication, 'java-original-ambiguous', committed, before)
            client.call.assert_not_called()
        campaign.node.current_program, campaign.node.current_publication_program, campaign.peer.current_http = 'terminal', True, True
        with mock.patch.object(flow.time, 'monotonic', return_value=50), mock.patch.object(flow.lifecycle, 'effect') as effect:
            with self.assertRaises(ValueError):
                flow.reconcile(campaign, publication, 'java-original-ambiguous', committed, before)
            effect.assert_not_called()

    def test_original_byte_and_uint64_contracts_refuse_malformed_or_overflow_values(self):
        for value in [None, -1, 1, '', '-1', '01', '18446744073709551616', '9' * 200, '0']:
            with self.assertRaises(ValueError):
                flow.decimal(value)
        for value in [None, {'encoding': 'hex', 'data': 'ff'}, {'encoding': 'base64', 'data': '!!!!'},
                      encoded(b''), encoded(b'x' * 31), encoded(b'x' * 33)]:
            with self.assertRaises(ValueError):
                flow.encoded(value, size=32)

    def test_target_rule_is_separate_purpose_limited_and_preserves_default_proposal(self):
        publication = 'publication:sha256:' + '1' * 64
        alice = {'ownerKind': 'user', 'subject': cfg.ALICE, 'recoveryKind': 'original-caller',
                 'recoveryScope': 'recovery:sha256:' + 'a' * 64}
        operator = {'ownerKind': 'administrator', 'subject': cfg.OPERATOR}
        hosts = SimpleNamespace(alice=alice, operator=operator, effects=[{'publication': publication, 'operation': 'http'}])
        proposals = {'policies': {cfg.STATE_POLICY: {'rules': [{'id': 'old-user', 'operations': list(range(16))}]}},
                     'bindings': {}, 'deploymentGrants': []}
        original = deepcopy(proposals)
        changed = flow.policy_proposal(proposals, hosts, publication)
        self.assertEqual(proposals, original)
        self.assertEqual(changed['policies'][cfg.STATE_POLICY]['rules'][:-1], original['policies'][cfg.STATE_POLICY]['rules'])
        rule = changed['policies'][cfg.STATE_POLICY]['rules'][-1]
        self.assertEqual(rule['principals'], [{'kind': 'administrator', 'subject': cfg.OPERATOR}])
        self.assertEqual(rule['publications'], [publication])
        self.assertEqual(rule['operations'], ['inspect-effect', 'effect-plan', 'effect-reconcile'])
        self.assertEqual(rule['resources']['scopes'][0]['recoveryScope'], alice['recoveryScope'])
        with self.assertRaises(ValueError):
            flow.policy_proposal(changed, hosts, publication)
        with self.assertRaises(ValueError):
            flow.policy_proposal(proposals, hosts, 'publication:sha256:' + '2' * 64)


if __name__ == '__main__':
    unittest.main()
