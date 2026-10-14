"""Synthetic closed CLI shapes from the actual pending store/wire projection.

These values model observation only and never qualify a native execution.
"""
import base64
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from tools.java_transaction_qualification import configuration as cfg

PUBLICATION = 'publication:sha256:' + 'a' * 64
COMPONENT = 'sha256:' + 'a' * 64


def pending_claim(key='original-key'):
    return {'commandId': '1' * 64, 'attemptId': '1',
        'fingerprintSha256': {'encoding': 'base64', 'data': base64.b64encode(bytes(32)).decode()},
        'outcome': 'COMMAND_OUTCOME_RECOVERY_REQUIRED', 'metadataDurable': False,
        'applicationStateCommitted': False, 'retainedResult': None, 'commit': None,
        'provenAbort': None, 'cleanupFailure': None, 'retention': {
            'recordFormat': 'lsf-command-v4', 'recordVersion': 4, 'payloadExpiresAtUnixMillis': '200000',
            'identityExpiresAtUnixMillis': '300000', 'remainingRecoveryMillis': None,
            'requiredRecordIds': ['1' * 64, '5' * 64, '4' * 64], 'payloadAvailable': False},
        'key': {'namespace': {'tenant': cfg.TENANT, 'namespace': cfg.NAMESPACE, 'incarnation': '1'},
            'recoveryScope': 'recovery:sha256:e922e1a2158f9cedafea276b6375fcbf20b96938db3284e48063c26819a19438',
            'operation': 'update', 'entity': None, 'clientKey': key},
        'source': {'publicationId': PUBLICATION, 'componentDigest': COMPONENT,
            'releaseDigest': 'sha256:' + 'b' * 64, 'contractDigest': 'sha256:' + 'c' * 64,
            'stateSchema': 'sha256:' + 'd' * 64, 'revisionId': 'revision-1', 'routeGeneration': '1',
            'inputFormat': 'lsf-wit-values-v1', 'resultFormat': 'lsf-wit-values-v1'}}


def reply(command, data, *, outcome=True, category='success', error=None):
    return {'schemaVersion': 'latent.cli.result.v1', 'command': command, 'data': data,
        'category': category, 'requestDispatched': True, 'outcomeKnown': outcome, 'error': error}


def busy(command):
    return reply(command, {}, outcome=False, category='transport-failure', error={
        'code': 'rpc-failed', 'grpcCode': 'resource-exhausted',
        'message': 'The RPC did not return a usable result.'})


class Clock:
    def __init__(self):
        self.now, self.sleeps = 100., []

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay

    @contextmanager
    def installed(self, module):
        with patch.object(module.time, 'monotonic', self.monotonic), \
                patch.object(module.time, 'sleep', self.sleep):
            yield


def collector(module, call, clock):
    value = module.DiagnosticCampaign.__new__(module.DiagnosticCampaign)
    value.client = SimpleNamespace(call=call, deadline=clock.now + 1000)
    value.publication = PUBLICATION
    value.input = SimpleNamespace(item=SimpleNamespace(component_digest=COMPONENT))
    return value


def pending():
    return SimpleNamespace(thread=SimpleNamespace(is_alive=lambda: True))
