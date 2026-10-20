"""Closed existing native startup failures; no raw stderr, paths or messages.

The V7 producer emits this report before its terminal latentd code. Capturing it
does not retry startup, change the error decision or certify successful cleanup.
"""
from __future__ import annotations

import json

SCHEMA = 'latent.startup-failure-observation.v1'
STAGES = frozenset(('configuration', 'executionProfile', 'auditCatalog', 'supplyChainCatalog',
    'artifactCatalog', 'policyCatalog', 'deploymentCatalog', 'rolloutCatalog',
    'catalogAuditReconciliation', 'providerCatalog', 'nodeComposition', 'nodeServices',
    'stateClock', 'stateOperations', 'nativeCapacity', 'effectAuthority', 'protectedStoreStartup',
    'effectDispatcher', 'stateManagement', 'nodeStart', 'nodeShutdown', 'stateKernelPrecondition',
    'protectedStoreOpen', 'protectedStoreInitializerAdmission', 'protectedStoreInitializerCompletion',
    'protectedStoreInitializerDeadline', 'namespaceCatalog', 'stateModeAdmission',
    'stateModeCompletion', 'stateModeDeadline', 'adapterClockBinding', 'stateKernelReadiness',
    'namespaceNativeCapacity'))
REASONS = {
    'platform': frozenset(('unavailable', 'deadline-exceeded', 'cancelled', 'resource-exhausted',
        'permission-denied', 'unauthenticated', 'invalid-argument', 'not-found', 'already-exists',
        'incompatible-contract', 'state-conflict', 'dependency-failed', 'guest-trap',
        'corrupt-artifact', 'route-unavailable', 'admission-rejected', 'internal')),
    'dispatcher': frozenset(('invalidConfiguration', 'unsupportedOrdering', 'invalidAdapter',
        'checkpointRequired', 'admissionClosed', 'staleEpoch')),
    'authority': frozenset(('invalid', 'capacity', 'policyBlocked', 'unsupportedFormat', 'expired',
        'clockDiscontinuity', 'stale', 'unavailable')),
    'protected': frozenset(('invalidConfiguration', 'unsupportedPlatform', 'unsupportedFilesystem',
        'unsafeRoot', 'foreignView', 'commitUncertain')),
    'storage': frozenset(('invalid', 'capacity', 'conflict', 'corrupt', 'unsupportedFormat',
        'unavailable', 'commitUncertain', 'snapshotExpired')),
    'worker': frozenset(('invalidLimits', 'admissionClosed', 'recoveryUnavailable', 'custodyBusy',
        'custodyMismatch', 'custodyExpired', 'queueFull', 'acceptedFull', 'byteBudget', 'jobTooLarge',
        'exhausted', 'poisoned', 'workerStartFailed', 'recoveryRequired', 'initializationFailed',
        'notStarted', 'finalizationFailed', 'drainWaiterBusy', 'alreadyDelivered')),
}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate-startup-observation-field')
        result[key] = value
    return result


def _failure(value):
    return (type(value) is dict and set(value) == {'owner', 'reason'}
            and type(value['owner']) is str and value['owner'] in REASONS
            and type(value['reason']) is str and value['reason'] in REASONS[value['owner']])


def observe(raw):
    """Return only a fully validated finite failure report, or a fixed omission.

    Other stderr lines are ignored, never copied. A second report, private/unknown
    fields, unknown enum, duplicate key, incomplete JSON or truncation fails closed.
    """
    absent = {'status': 'unavailable', 'qualification': False}
    if type(raw) is not bytes or len(raw) > 262144:
        return absent
    candidates = [line for line in raw.splitlines() if SCHEMA.encode() in line]
    if len(candidates) != 1 or len(candidates[0]) > 16384:
        return absent
    try:
        value = json.loads(candidates[0], object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError):
        return absent
    if (type(value) is not dict or set(value) != {'schemaVersion', 'startupSucceeded',
            'terminalFailure', 'observations', 'truncated', 'shutdown'}
            or value['schemaVersion'] != SCHEMA or value['startupSucceeded'] is not False
            or value['truncated'] is not False or value['shutdown'] is not None
            or not _failure(value['terminalFailure']) or type(value['observations']) is not list
            or len(value['observations']) > 32):
        return absent
    for row in value['observations']:
        if (type(row) is not dict or set(row) != {'stage', 'failure'}
                or type(row['stage']) is not str or row['stage'] not in STAGES
                or not _failure(row['failure'])):
            return absent
    return {'status': 'observed', 'qualification': False, 'report': value}
