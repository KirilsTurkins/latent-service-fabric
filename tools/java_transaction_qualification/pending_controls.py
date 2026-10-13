"""Observe exact current dispatcher and restored-close results; never grant access."""
from __future__ import annotations

import re
import time

from . import configuration as cfg, lifecycle, recovery
from .evidence import encoded
from .inputs import require

COUNTERS = {'queued', 'activeJobs', 'retainedAttemptBytes', 'liveWorkers', 'acceptedEffects',
            'physicalOwners', 'quarantinedPhysicalOwners', 'commandOwners', 'claims', 'pendingEffects',
            'uncertainEffects', 'blockedEffects', 'deadLetterEffects', 'countsObservedAtUnixMillis'}
FLAGS = {'paused', 'pendingControl', 'restoreReviewRequired', 'admissionClosed', 'quarantined',
         'clockContinuityProven'}
PHYSICAL = {'queued', 'activeJobs', 'retainedAttemptBytes', 'acceptedEffects', 'physicalOwners',
            'quarantinedPhysicalOwners', 'commandOwners', 'claims'}
RECEIPT_FIELDS = {'operationId', 'receiptId', 'action', 'authenticatedOperator', 'actorTenant',
                  'beforeGeneration', 'afterGeneration', 'observedAtUnixMillis', 'clockContinuityProven',
                  'restoreReviewRequired', 'disposition'}


def decimal(value, *, positive=False):
    require(isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]{0,19}', value)
            and int(value) < 2**64 and (not positive or int(value) > 0), 'original-dispatcher-counter')
    return value


def generation(value):
    require(isinstance(value, dict) and set(value) == {'ownerEpoch', 'revision'},
            'closed-original-dispatcher-generation')
    for field in value:
        decimal(value[field], positive=True)
    return dict(value)


def durable_audit(value):
    require(isinstance(value, dict) and set(value) == {'status', 'attemptSequence'}
            and value['status'] == 'AUDIT_ACK_STATUS_DURABLE', 'actual-durable-dispatcher-audit')
    decimal(value['attemptSequence'], positive=True)
    return value


def recovery_selector(value, action, operation, original):
    require(isinstance(value, dict) and set(value) == {'family', 'scope', 'tenant', 'operationId',
                'action', 'expectedGeneration', 'automaticRetry'}
            and value == {'family': 'dispatcher', 'scope': 'node', 'tenant': cfg.TENANT,
                'operationId': operation, 'action': 'DISPATCHER_ACTION_' + action.upper(),
                'expectedGeneration': original, 'automaticRetry': False}
            and value['automaticRetry'] is False,
            'original-dispatcher-recovery-selector')


def inspect_dispatcher(client):
    result = client.call('dispatcher', 'inspect', '--scope', 'node')
    data = result['data']
    require(result['outcomeKnown'] is True and isinstance(data, dict)
            and set(data) == {'dispatcher', 'auditAcknowledgement'}
            and data['auditAcknowledgement'] is not None, 'actual-audited-dispatcher-inspection')
    value = data['dispatcher']
    require(isinstance(value, dict) and set(value) == COUNTERS | FLAGS | {'generation', 'failure'}
            and all(type(value[field]) is bool for field in FLAGS)
            and value['failure'] == 'DISPATCHER_FAILURE_NONE', 'closed-healthy-dispatcher-observation')
    generation(value['generation'])
    durable_audit(data['auditAcknowledgement'])
    for field in COUNTERS:
        decimal(value[field])
    return value


def control_dispatcher(client, action, operation):
    require(action in {'pause', 'resume'} and re.fullmatch(r'[a-z0-9-]{1,64}', operation),
            'explicit-current-dispatcher-action')
    before = inspect_dispatcher(client)
    original = generation(before['generation'])
    arguments = ('--scope', 'node', '--operation-id', operation,
                 '--expected-owner-epoch', original['ownerEpoch'], '--expected-revision', original['revision'])
    result = client.call('dispatcher', action, *arguments)
    data = result['data']
    require(result['outcomeKnown'] is True and isinstance(data, dict)
            and set(data) == {'receipt', 'replayed', 'published', 'paused', 'auditAcknowledgement', 'recovery'}
            and data['replayed'] is False and data['published'] is True
            and data['paused'] is (action == 'pause') and data['auditAcknowledgement'] is not None,
            'actual-current-dispatcher-control-published')
    recovery_selector(data['recovery'], action, operation, original)
    receipt = data['receipt']
    durable_audit(data['auditAcknowledgement'])
    require(isinstance(receipt, dict) and set(receipt) == RECEIPT_FIELDS
            and receipt['operationId'] == operation and receipt['action'] == 'DISPATCHER_ACTION_' + action.upper()
            and receipt['authenticatedOperator'] == lifecycle.operator_actor() and receipt['actorTenant'] == cfg.TENANT
            and receipt['beforeGeneration'] == original
            and receipt['disposition'] == 'STATE_OPERATION_DISPOSITION_COMMITTED'
            and receipt['clockContinuityProven'] is True and receipt['restoreReviewRequired'] is False,
            'original-current-dispatcher-receipt-attribution')
    recovery.original_digest(receipt['receiptId'])
    decimal(receipt['observedAtUnixMillis'], positive=True)
    after = generation(receipt['afterGeneration'])
    require(after['ownerEpoch'] == original['ownerEpoch'] and int(after['revision']) == int(original['revision']) + 1,
            'actual-dispatcher-generation-advance')
    lookup = client.call('dispatcher', 'operation', *arguments, '--original-action', action)
    recovered = lookup['data']
    require(lookup['outcomeKnown'] is True and set(recovered) == {'receipt', 'auditAcknowledgement'}
            and recovered['auditAcknowledgement'] is not None and recovered['receipt'] == receipt,
            'historical-dispatcher-receipt-is-original')
    durable_audit(recovered['auditAcknowledgement'])
    client.evidence.passed(operation, {'before': before, 'receipt': receipt, 'lookup': recovered})
    return receipt


def drained_dispatcher(client):
    until = min(client.deadline, time.monotonic() + 10)
    for _ in range(24):
        value = inspect_dispatcher(client)
        require(value['paused'] is True and value['pendingControl'] is False
                and value['restoreReviewRequired'] is False and value['admissionClosed'] is False
                and value['quarantined'] is False and value['clockContinuityProven'] is True,
                'original-paused-dispatcher-control')
        if all(value[field] == '0' for field in PHYSICAL):
            return value
        require(time.monotonic() < until, 'actual-paused-dispatcher-drain-watchdog')
        time.sleep(min(.1, until - time.monotonic()))
    raise ValueError('actual-paused-dispatcher-not-drained')


def close_plan(result, operation, effect_id, expected_view, window):
    require(isinstance(result, dict) and set(result) == {'action', 'acknowledgement', 'plan'}
            and result['action'] == 'inspect-close-effects', 'closed-native-effect-close-inspection')
    acknowledgement = recovery.original_digest(result['acknowledgement'])
    plan = result['plan']
    require(isinstance(plan, dict) and set(plan) == {'schemaVersion', 'operatorId', 'operationId', 'scope',
                'expectedView', 'expectedGuard', 'lossWindowDigest', 'reason', 'effects'}
            and plan['schemaVersion'] == 'lsf.effect-recovery-close.v1' and plan['operatorId'] == cfg.OPERATOR
            and plan['operationId'] == operation and plan['scope'] == {
                'tenant': cfg.TENANT, 'namespace': cfg.NAMESPACE, 'incarnation': 1}
            and type(plan['scope']['incarnation']) is int
            and recovery.original_view(plan['expectedView']) == recovery.original_view(expected_view)
            and 0 < len(recovery.byte_array(plan['expectedGuard'], 16384))
            and bytes(recovery.byte_array(plan['lossWindowDigest'], 32)) == bytes.fromhex(recovery.original_digest(window)[7:])
            and plan['reason'] == 'remote-acceptance-observed-explicit-no-redrive'
            and isinstance(plan['effects'], list) and len(plan['effects']) == 1
            and len(encoded(plan)) <= 12288, 'original-restored-pending-close-plan')
    selected = plan['effects'][0]
    require(isinstance(selected, dict) and set(selected) == {'effectId', 'originalDigest', 'payloadDigest',
                'historyDigest', 'originalDisposition', 'originalClockMillis'}
            and selected['effectId'] == effect_id and selected['originalDisposition'] == 'Pending'
            and type(selected['originalClockMillis']) is int and 0 < selected['originalClockMillis'] < 2**64,
            'exact-restored-pending-effect-selection')
    for field in ('originalDigest', 'payloadDigest', 'historyDigest'):
        raw = recovery.byte_array(selected[field], 32)
        require(len(raw) == 32 and raw != bytes(32), 'original-effect-close-digest')
    return plan, acknowledgement


def close_receipt(result, plan, acknowledgement, *, replay):
    require(isinstance(result, dict) and set(result) == {'action', 'receipt', 'replay'}
            and result['action'] == 'close-effects' and type(result['replay']) is bool
            and result['replay'] is replay, 'closed-native-effect-close-result')
    receipt = result['receipt']
    require(isinstance(receipt, dict) and set(receipt) == {'schemaVersion', 'outcome', 'plan',
                'acknowledgement', 'observedAtMillis'}
            and receipt['schemaVersion'] == 'lsf.effect-recovery-close.v1'
            and receipt['outcome'] == 'closed-without-redrive' and receipt['plan'] == plan
            and bytes(recovery.byte_array(receipt['acknowledgement'], 32)) == bytes.fromhex(acknowledgement[7:])
            and type(receipt['observedAtMillis']) is int
            and plan['effects'][0]['originalClockMillis'] <= receipt['observedAtMillis'] < 2**64
            and len(encoded(receipt)) <= 16384, 'original-no-redrive-close-receipt')
    return receipt
