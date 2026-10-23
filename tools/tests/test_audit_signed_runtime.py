"""Audit authority/retirement interpretation controls; no signed invocation here."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_audit_signed_runtime as owner
from tools.phase2_operator_process import WorkflowError


def pair_model():
    activation = 'audit-required-random'
    revision = {'publicationId': 'publication:sha256:' + '1' * 64,
        'releaseDigest': 'sha256:' + '2' * 64, 'revisionId': 'revision-1', 'routeGeneration': '7'}
    provider = {'configurationDigest': 'sha256:' + '3' * 64, 'configurationEpoch': '1'}
    identity = {'publicationId': revision['publicationId'], 'componentDigest': revision['releaseDigest'],
        'revision': revision['revisionId'], 'routeGeneration': '7', 'capability': {
            'activation': activation, 'rootActivation': activation, 'service': 'examples/' + owner.SERVICE,
            'capability': owner.RANDOM, 'operation': 'bytes', 'required': True,
            'providerProfile': 'system-random-v1', 'providerConfigurationDigest': provider['configurationDigest'],
            'providerConfigurationEpoch': '1', 'binding': {'id': 'random-installed', 'revision': '1'},
            'policies': [{'id': 'random-allow', 'revision': '2'}]}}
    outcome_identity = copy.deepcopy(identity)
    outcome_identity['capability']['providerOutcome'] = 'AUDIT_PROVIDER_OUTCOME_HOST_COMPLETED'
    rows = [{'epoch': 'a' * 32, 'sequence': '1', 'data': {'attempt': {
        'action': 'AUDIT_CONTROL_ACTION_CAPABILITY_CALL', 'replay': False, 'identities': identity}}},
        {'epoch': 'a' * 32, 'sequence': '2', 'data': {'outcome': {
            'attemptSequence': '1', 'result': 'AUDIT_OPERATION_RESULT_COMMITTED',
            'replay': False, 'identities': outcome_identity}}}]
    pages = [{'category': 'success', 'outcomeKnown': True, 'requestDispatched': True, 'data': {
        'records': rows, 'page': {'nextPageToken': None}, 'coverage': {'epoch': 'a' * 32,
            'retainedFloor': '1', 'highWatermark': '2', 'scanned': '2',
            'droppedObservations': '7', 'unknownOutcomes': '0', 'previousSessionLossUnknown': False,
            'stop': 'AUDIT_PAGE_STOP_END'}}}]
    return pages, activation, revision, provider


class AuditSignedRuntimeTests(unittest.TestCase):
    def test_original_bank_keeps_live_broker_metadata_visible_and_requires_other_transient_zero(self):
        counters = {'audit_node_metadata_' + key: str(value) for key, value in {
            'maximum_bytes': 8 * 1024**2, 'reserved_bytes': 11000, 'fixed_reserved_bytes': 10000,
            'transient_reserved_bytes': 1000, 'quarantined_reserved_bytes': 0}.items()}
        counters['broker_metadata_bytes'] = '1000'
        observed = owner.bank_observation({'nodeUsage': {'counters': counters}})
        self.assertEqual(observed['reserved_bytes'], 11000)
        self.assertEqual(observed['broker_metadata_bytes'], 1000)
        self.assertEqual(observed['non_broker_transient_bytes'], 0)
        for key, value in (('audit_node_metadata_maximum_bytes', 16 * 1024**2),
                ('audit_node_metadata_reserved_bytes', 11001),
                ('audit_node_metadata_quarantined_reserved_bytes', 1), ('broker_metadata_bytes', 999)):
            changed = dict(counters, **{key: str(value)})
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                owner.bank_observation({'nodeUsage': {'counters': changed}})

    def test_stricter_policy_changes_only_original_random_require_audit_and_does_not_alias_input(self):
        original = {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'capability': owner.RANDOM, 'operations': ['bytes'], 'resources': {'kind': 'random'},
            'ceiling': {'inputBytes': 8, 'operations': 4096}}]}
        selected = owner.required_random_policy(original)
        self.assertNotIn('requireAudit', original['rules'][0])
        self.assertIs(selected['rules'][0]['requireAudit'], True)
        selected['rules'][0].pop('requireAudit')
        self.assertEqual(selected, original)
        for key, value in (('capability', 'foreign'), ('operations', ['u64-value']),
                           ('requireAudit', True), ('ceiling', {'inputBytes': 4096})):
            changed = copy.deepcopy(original)
            changed['rules'][0][key] = value
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                owner.required_random_policy(changed)

    def test_required_pair_binds_current_revision_real_provider_and_same_durable_attempt_despite_optional_loss(self):
        pages, activation, revision, provider = pair_model()
        result = owner.critical_pair(pages, activation, revision, provider)
        self.assertTrue(result['requiredAudit'])
        self.assertFalse(result['optionalCaptureLosslessnessClaimed'])
        self.assertTrue(result['coverage']['optionalObservationLossReported'])
        for mutation in ('required', 'provider', 'policy', 'attempt', 'result', 'replay', 'revision'):
            changed = copy.deepcopy(pages)
            attempt = changed[0]['data']['records'][0]['data']['attempt']
            outcome = changed[0]['data']['records'][1]['data']['outcome']
            if mutation == 'required':
                attempt['identities']['capability']['required'] = False
            elif mutation == 'provider':
                attempt['identities']['capability']['providerConfigurationDigest'] = 'sha256:' + '0' * 64
            elif mutation == 'policy':
                attempt['identities']['capability']['policies'][0]['revision'] = '1'
            elif mutation == 'attempt':
                outcome['attemptSequence'] = '2'
            elif mutation == 'result':
                outcome['result'] = 'AUDIT_OPERATION_RESULT_UNKNOWN'
            elif mutation == 'replay':
                outcome['replay'] = True
            else:
                outcome['identities']['revision'] = 'foreign'
            with self.subTest(mutation=mutation), self.assertRaises(WorkflowError):
                owner.critical_pair(changed, activation, revision, provider)

    def test_prebuild_failure_retains_result_without_retrieval_or_rebuild(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(owner.sys, 'platform', 'linux'), \
                patch.object(owner.subprocess, 'check_output', return_value=b'a' * 40 + b'\n'), \
                patch.object(owner, 'inputs', side_effect=ValueError('fixed-test-refusal')), \
                patch.object(owner.hosts, 'prepare') as hosts:
            output = Path(temporary) / 'capture'
            with self.assertRaises(ValueError):
                owner.qualify(output, 'a' * 40)
            result = json.loads((output / 'result.json').read_bytes())
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['failedStage'], 'bind-current-consumer-source-and-recipe')
            self.assertFalse(result['nativeRebuilt'])
            self.assertFalse(result['guestSourceRecompiled'])
            hosts.assert_not_called()


if __name__ == '__main__':
    unittest.main()
