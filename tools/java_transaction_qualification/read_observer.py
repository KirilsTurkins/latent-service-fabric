"""Closed read-only replies; observing backpressure supplies no command authority."""
import base64
import re
import time

from . import configuration as cfg
from .inputs import require

ENVELOPE = {'schemaVersion', 'command', 'data', 'category', 'requestDispatched', 'outcomeKnown', 'error'}
CLAIM = {'key', 'commandId', 'attemptId', 'fingerprintSha256', 'outcome', 'metadataDurable',
         'applicationStateCommitted', 'source', 'retainedResult', 'commit', 'provenAbort', 'retention', 'cleanupFailure'}
SOURCE = {'publicationId', 'revisionId', 'releaseDigest', 'componentDigest', 'routeGeneration',
          'contractDigest', 'stateSchema', 'inputFormat', 'resultFormat'}
RETENTION = {'recordFormat', 'recordVersion', 'payloadExpiresAtUnixMillis', 'identityExpiresAtUnixMillis',
             'remainingRecoveryMillis', 'requiredRecordIds', 'payloadAvailable'}
# CallerScope::derive(OriginalCaller) for this program's examples/user/Alice identity.
ALICE_SCOPE = 'recovery:sha256:e922e1a2158f9cedafea276b6375fcbf20b96938db3284e48063c26819a19438'


def kind(value, command, *, missing=False):
    require(command in {'transaction lookup', 'dispatcher inspect'}
            and (not missing or command == 'transaction lookup'), 'explicit-original-read-only-operation')
    require(isinstance(value, dict) and set(value) == ENVELOPE
            and value['schemaVersion'] == 'latent.cli.result.v1' and value['command'] == command
            and value['requestDispatched'] is True and type(value['outcomeKnown']) is bool
            and isinstance(value['data'], dict), 'closed-original-read-only-response')
    if value['category'] == 'transport-failure':
        require(value['outcomeKnown'] is False and value['data'] == {} and isinstance(value['error'], dict)
                and value['error'] == {'code': 'rpc-failed', 'grpcCode': 'resource-exhausted',
                    'message': 'The RPC did not return a usable result.'}, 'closed-original-read-only-busy')
        return 'busy'
    if value['category'] == 'not-found' and missing:
        require(value['outcomeKnown'] is True and value['data'] == {} and isinstance(value['error'], dict)
                and value['error'] == {'code': 'not-found', 'message': 'The platform reported a failure.',
                    'retryable': False, 'details': []} and value['error']['retryable'] is False,
                'original-command-lookup-certainty')
        return 'missing'
    require(value['category'] == 'success' and value['error'] is None, 'original-read-only-lookup-refusal')
    return 'success'


def namespace_kind(value):
    require(isinstance(value, dict) and set(value) == ENVELOPE
            and value['schemaVersion'] == 'latent.cli.result.v1' and value['command'] == 'state inspect'
            and value['requestDispatched'] is True and type(value['outcomeKnown']) is bool
            and isinstance(value['data'], dict), 'closed-original-namespace-read-response')
    if value['category'] == 'transport-failure':
        require(value['outcomeKnown'] is False and value['data'] == {} and isinstance(value['error'], dict)
                and value['error'] == {'code': 'rpc-failed', 'grpcCode': 'resource-exhausted',
                    'message': 'The RPC did not return a usable result.'}, 'closed-original-namespace-read-busy')
        return 'busy'
    require(value['category'] == 'success' and value['outcomeKnown'] is True and value['error'] is None,
            'original-namespace-read-refusal')
    return 'success'


def pause(until, reason):
    remaining = until - time.monotonic()
    require(remaining > 0, reason)
    time.sleep(min(.05, remaining))


def decimal(value):
    return (isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}', value) is not None
            and int(value) < 2**64)


def hex_id(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def pending_claim(record, publication, component, original_key):
    require(isinstance(record, dict) and set(record) == CLAIM
            and record['outcome'] == 'COMMAND_OUTCOME_RECOVERY_REQUIRED'
            and record['metadataDurable'] is False and record['applicationStateCommitted'] is False
            and all(record[name] is None for name in ('retainedResult', 'commit', 'provenAbort', 'cleanupFailure'))
            and hex_id(record['commandId']) and record['attemptId'] == '1', 'actual-original-precommit-command-attempt')
    key, source, retained, fingerprint = record['key'], record['source'], record['retention'], record['fingerprintSha256']
    require(isinstance(key, dict) and set(key) == {'namespace', 'recoveryScope', 'operation', 'entity', 'clientKey'}
            and key['namespace'] == {'tenant': cfg.TENANT, 'namespace': cfg.NAMESPACE, 'incarnation': '1'}
            and key['operation'] == 'update' and key['entity'] is None and key['clientKey'] == original_key
            and key['recoveryScope'] == ALICE_SCOPE, 'actual-original-precommit-command-key')
    require(isinstance(source, dict) and set(source) == SOURCE
            and source['publicationId'] == publication and source['componentDigest'] == component
            and all(isinstance(source[name], str) and re.fullmatch(r'sha256:[0-9a-f]{64}', source[name])
                    for name in ('componentDigest', 'releaseDigest', 'contractDigest', 'stateSchema'))
            and decimal(source['routeGeneration']) and isinstance(source['revisionId'], str)
            and 0 < len(source['revisionId']) <= 1024
            and source['inputFormat'] == source['resultFormat'] == 'lsf-wit-values-v1',
            'actual-original-precommit-command-source')
    require(isinstance(fingerprint, dict) and set(fingerprint) == {'encoding', 'data'}
            and fingerprint['encoding'] == 'base64' and isinstance(fingerprint['data'], str)
            and re.fullmatch(r'[A-Za-z0-9+/]{43}=', fingerprint['data']) is not None
            and base64.b64encode(base64.b64decode(fingerprint['data'], validate=True)).decode() == fingerprint['data'],
            'actual-original-precommit-fingerprint')
    require(isinstance(retained, dict) and set(retained) == RETENTION
            and type(retained['recordVersion']) is int and retained['recordVersion'] in {3, 4}
            and retained['recordFormat'] == f"lsf-command-v{retained['recordVersion']}"
            and retained['payloadAvailable'] is False and retained['remainingRecoveryMillis'] is None
            and decimal(retained['payloadExpiresAtUnixMillis']) and decimal(retained['identityExpiresAtUnixMillis'])
            and int(retained['payloadExpiresAtUnixMillis']) <= int(retained['identityExpiresAtUnixMillis'])
            and isinstance(retained['requiredRecordIds'], list) and len(retained['requiredRecordIds']) == 3
            and all(hex_id(value) for value in retained['requiredRecordIds'])
            and len(set(retained['requiredRecordIds'])) == 3
            and retained['requiredRecordIds'][0] == record['commandId'], 'original-descriptive-pending-retention')
    return record
