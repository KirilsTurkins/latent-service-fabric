"""One explicit current management lookup for the retained original attempt."""
import base64
from copy import deepcopy
from pathlib import Path
import re
import time

from tools.rust_capsule_project import read_file
from . import configuration as cfg, lifecycle, policies
from .inputs import decode, require

UNCERTAIN = 'EFFECT_DISPOSITION_UNCERTAIN_AFTER_DISPATCH'
ACKNOWLEDGED = 'EFFECT_DISPOSITION_PROVIDER_ACKNOWLEDGED'
ACTION = 'STATE_MUTATION_KIND_RECONCILE_EFFECT'
OPERATION = 'java-original-ambiguous-reconcile'
REASON = 'Inspect the original retained provider acceptance after the owned restart.'
ENVELOPE = {'schemaVersion', 'command', 'category', 'data', 'error', 'requestDispatched', 'outcomeKnown'}
PLAN = {'original', 'planDigest', 'managementSequence', 'ownerEpoch', 'claimGeneration', 'dispatchAttempt',
        'expiresAtUnixMillis', 'preparedAtUnixMillis', 'before', 'safety', 'dedupValidUntilUnixMillis', 'encodedPlan'}
RECEIPT = {'operationId', 'receiptId', 'mutation', 'namespace', 'authenticatedOperator', 'beforeVersion',
           'afterVersion', 'completedAtUnixMillis', 'recordId', 'policyDigest', 'disposition', 'effect'}


def decimal(value, *, positive=True):
    require(isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]*', value)
            and len(value) <= 20 and int(value) < 2**64 and (not positive or int(value) > 0),
            'original-effect-management-decimal')
    return int(value)


def encoded(value, *, size=None, maximum=16384):
    require(isinstance(value, dict) and set(value) == {'encoding', 'data'}
            and value['encoding'] == 'base64' and isinstance(value['data'], str)
            and len(value['data']) <= (maximum + 2) // 3 * 4, 'original-effect-management-byte-shape')
    try:
        raw = base64.b64decode(value['data'], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('original-effect-management-byte-shape') from error
    require(0 < len(raw) <= maximum and (size is None or len(raw) == size)
            and base64.b64encode(raw).decode() == value['data'], 'original-effect-management-byte-shape')
    return raw


def data(value, command, fields):
    require(isinstance(value, dict) and set(value) == ENVELOPE
            and value['schemaVersion'] == 'latent.cli.result.v1' and value['command'] == command
            and value['category'] == 'success' and value['requestDispatched'] is True
            and value['outcomeKnown'] is True and value['error'] is None
            and isinstance(value['data'], dict) and set(value['data']) == fields,
            'original-effect-management-usable-response')
    return value['data']


def audit(value):
    require(isinstance(value, dict) and set(value) == {'status', 'attemptSequence'}
            and value['status'] == 'AUDIT_ACK_STATUS_DURABLE', 'original-effect-management-durable-audit')
    decimal(value['attemptSequence'])


def policy_proposal(proposals, hosts, publication):
    """Data-only proposal, applied by the original authenticated policy API."""
    require(re.fullmatch(r'publication:sha256:[0-9a-f]{64}', publication or '')
            and hosts.alice['ownerKind'] == 'user' and hosts.alice['subject'] == cfg.ALICE
            and hosts.operator['ownerKind'] == 'administrator' and hosts.operator['subject'] == cfg.OPERATOR
            and any(row['publication'] == publication and row['operation'] == 'http' for row in hosts.effects),
            'selected-current-reconciliation-publication')
    result = deepcopy(proposals)
    rules = result['policies'][cfg.STATE_POLICY]['rules']
    require(all(rule['id'] != 'original-effect-reconciliation' for rule in rules),
            'original-effect-reconciliation-rule-once')
    rules.append(policies.rule('original-effect-reconciliation', 'administrator', hosts.operator['subject'],
        [publication], policies.STATE_CONTRACT, ['inspect-effect', 'effect-plan', 'effect-reconcile'],
        {'kind': 'state', 'scopes': [policies.scope(hosts.alice)]}))
    return result


def profile():
    root = Path(__file__).resolve().parents[2]
    value = decode(read_file(root / 'sdk/profile/transaction-requirements-v1.json', 65536), 65536)
    return {'profile': value['wireProfile'], 'hostAbiDigest': value['hostAbiDigest'],
            'preparationProfileDigest': value['preparationProfileDigest']}


def original(publication, key, effect_id, version, policy_digest):
    return {'effect': {'profile': profile(), 'command': {
        'namespace': {'tenant': cfg.TENANT, 'namespace': cfg.NAMESPACE, 'incarnation': '1'},
        'operation': 'update', 'entity': None, 'clientKey': key, 'sharedRecoveryScope': None},
        'effectId': effect_id, 'authorizationPublication': {'tenant': cfg.TENANT, 'id': publication}},
        'operationId': OPERATION, 'mutation': ACTION, 'expectedVersion': version,
        'expectedPolicyDigest': policy_digest, 'reason': REASON, 'retryDelayMillis': '0'}


def _varint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _message(fields):
    """Canonical subset of the existing authoritative plan messages only."""
    result = bytearray()
    for number, value in fields:
        if isinstance(value, str):
            value = value.encode()
        if type(value) is int:
            if value:
                result.extend(_varint(number << 3) + _varint(value))
        elif value:
            result.extend(_varint(number << 3 | 2) + _varint(len(value)) + value)
    return bytes(result)


def plan_bytes(value):
    request = value['original']
    effect = request['effect']
    command = effect['command']
    namespace = command['namespace']
    selected = effect['authorizationPublication']
    current = effect['profile']
    wire_profile = _message([(1, current['profile']), (2, current['hostAbiDigest']), (3, current['preparationProfileDigest'])])
    wire_namespace = _message([(1, namespace['tenant']), (2, namespace['namespace']), (3, namespace['incarnation'])])
    wire_command = _message([(1, wire_namespace), (2, command['operation']), (4, command['clientKey'])])
    wire_publication = _message([(1, selected['id']), (2, selected['tenant'])])
    wire_effect = _message([(1, wire_profile), (2, wire_command), (3, effect['effectId']), (4, wire_publication)])
    wire_request = _message([(1, wire_effect), (2, request['operationId']), (3, 5),
        (4, encoded(request['expectedVersion'], size=32)), (5, request['expectedPolicyDigest']), (6, request['reason'])])
    return _message([(1, wire_request), (2, encoded(value['planDigest'], size=32)),
        (3, value['managementSequence']), (4, decimal(value['ownerEpoch'])), (5, decimal(value['claimGeneration'])),
        (6, value['dispatchAttempt']), (7, decimal(value['expiresAtUnixMillis'])),
        (8, decimal(value['preparedAtUnixMillis'])), (9, 5), (10, 3)])


def plan(value, expected, before):
    result = data(value, 'state plan-effect', {'plan', 'replayed', 'auditAcknowledgement'})
    audit(result['auditAcknowledgement'])
    actual = result['plan']
    require(result['replayed'] is False and isinstance(actual, dict) and set(actual) == PLAN
            and actual['original'] == expected and actual['before'] == UNCERTAIN
            and actual['safety'] == 'EFFECT_PLAN_SAFETY_PROVIDER_RECEIPT_LOOKUP'
            and actual['dedupValidUntilUnixMillis'] is None
            and type(actual['managementSequence']) is int and 1 <= actual['managementSequence'] <= 128
            and type(before['dispatchAttempt']) is int and 1 <= before['dispatchAttempt'] <= 128
            and type(actual['dispatchAttempt']) is int and actual['dispatchAttempt'] == before['dispatchAttempt']
            and actual['ownerEpoch'] == before['ownerEpoch'] and actual['claimGeneration'] == before['claimGeneration'],
            'original-effect-reconciliation-plan-association')
    prepared, expires = decimal(actual['preparedAtUnixMillis']), decimal(actual['expiresAtUnixMillis'])
    require(prepared < expires <= prepared + 30000, 'original-effect-reconciliation-plan-lifetime')
    require(encoded(actual['encodedPlan']) == plan_bytes(actual), 'original-effect-reconciliation-plan-encoding')
    return actual


def receipt(value, command, actual_plan):
    applying = command == 'state apply-effect'
    fields = {'receipt', 'replayed', 'auditAcknowledgement', 'recovery'} if applying else {
        'stateReceipt', 'namespaceReceipt', 'auditAcknowledgement'}
    result = data(value, command, fields)
    audit(result['auditAcknowledgement'])
    actual = result['receipt' if applying else 'stateReceipt']
    expected = actual_plan['original']
    require(isinstance(actual, dict) and set(actual) == RECEIPT
            and actual['operationId'] == OPERATION and actual['mutation'] == ACTION
            and actual['namespace'] == expected['effect']['command']['namespace']
            and actual['authenticatedOperator'] == lifecycle.operator_actor()
            and actual['beforeVersion'] == expected['expectedVersion']
            and actual['policyDigest'] == expected['expectedPolicyDigest']
            and actual['recordId'] == expected['effect']['effectId']
            and re.fullmatch(r'effect-management:sha256:[0-9a-f]{64}', actual['receiptId'] or '')
            and actual['disposition'] == 'STATE_OPERATION_DISPOSITION_COMMITTED',
            'original-effect-reconciliation-receipt-association')
    encoded(actual['afterVersion'], size=32)
    completed = decimal(actual['completedAtUnixMillis'])
    details = actual['effect']
    require(isinstance(details, dict) and set(details) == {
        'originalPlan', 'before', 'after', 'fact', 'providerReceipt', 'providerObservedAtUnixMillis'}
        and details['originalPlan'] == actual_plan and details['before'] == UNCERTAIN
        and details['after'] == ACKNOWLEDGED and details['fact'] == 'EFFECT_MANAGEMENT_FACT_PROVIDER_CONFIRMED'
        and isinstance(details['providerReceipt'], str) and 0 < len(details['providerReceipt'].encode()) <= 256
        and not any(ord(char) < 32 or ord(char) == 127 for char in details['providerReceipt'])
        and decimal(actual_plan['preparedAtUnixMillis']) <= decimal(details['providerObservedAtUnixMillis']) <= completed,
        'original-provider-confirmation-required')
    if applying:
        require(result['replayed'] is False and result['recovery'] == {
            'family': 'state', 'operationId': OPERATION, 'namespace': actual['namespace'],
            'tenant': expected['effect']['command']['namespace']['tenant'],
            'authorizationPublication': expected['effect']['authorizationPublication'], 'recordId': actual['recordId'],
            'expectedVersion': expected['expectedVersion'], 'expectedPolicyDigest': expected['expectedPolicyDigest'],
            'action': ACTION, 'originalEffectPlan': actual_plan, 'automaticRetry': False},
            'original-effect-reconciliation-no-retry')
    else:
        require(result['namespaceReceipt'] is None, 'original-effect-reconciliation-receipt-family')
    return actual


def reconcile(campaign, publication, key, committed, before):
    require(getattr(campaign.peer, 'current_http', False)
            and getattr(campaign.node, 'current_program', None) == 'terminal'
            and getattr(campaign.node, 'current_publication_program', False),
            'explicit-current-terminal-reconciliation')
    until = campaign.client.deadline
    require(time.monotonic() < until, 'original-effect-reconciliation-cutoff')
    observed = lifecycle.effect(campaign.client, publication, key, committed['effect-ids'][0])
    require(observed['disposition'] == UNCERTAIN and before['disposition'] == UNCERTAIN
            and observed['effectId'] == committed['effect-ids'][0] == before['effectId']
            and observed['commandId'] == committed['command-id'] == before['commandId']
            and observed['commandAttemptId'] == committed['attempt-id'] == before['commandAttemptId']
            and type(observed['dispatchAttempt']) is int and observed['dispatchAttempt'] == before['dispatchAttempt']
            and observed['providerReceipt'] is None and observed['managementOperationReceiptId'] is None,
            'original-uncertain-provider-attempt-required')
    encoded(observed['recordVersion'], size=32)
    namespace = lifecycle.inspect_namespace(campaign.client, publication)
    digest = namespace['namespacePolicyDigest']
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', digest or ''), 'actual-namespace-policy-precondition')
    expected = original(publication, key, observed['effectId'], observed['recordVersion'], digest)
    planned = campaign.client.call('state', 'plan-effect', *lifecycle.namespace_arguments(publication),
        '--operation', 'update', '--client-key', key, '--effect-id', observed['effectId'],
        '--operation-id', OPERATION, '--action', 'reconcile', '--expected-version', observed['recordVersion']['data'],
        '--expected-policy-digest', digest, '--reason', REASON, cutoff=until)
    actual_plan = plan(planned, expected, before)
    applied = campaign.client.call('state', 'apply-effect', *lifecycle.namespace_arguments(publication),
                                  '--plan', actual_plan['encodedPlan']['data'], cutoff=until)
    accepted = receipt(applied, 'state apply-effect', actual_plan)
    looked_up = campaign.client.call('state', 'effect-operation', *lifecycle.namespace_arguments(publication),
                                    '--plan', actual_plan['encodedPlan']['data'], cutoff=until)
    require(receipt(looked_up, 'state effect-operation', actual_plan) == accepted,
            'same-original-effect-management-receipt')
    campaign.client.evidence.record('postcrash-original-provider-reconciliation', {
        'effectBefore': observed, 'plan': actual_plan, 'receipt': accepted,
        'automaticRetry': False, 'providerSendAuthorized': False})
    return accepted
