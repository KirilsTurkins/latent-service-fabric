"""Exact publication setup under the original Java tenant campaign deadline."""
from __future__ import annotations

import json
import re
import time

from tools.phase2_operator_process import Client, require, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_node import MAX_CALLS

MAXIMUM_WAIT_MILLIS = 300000
PROCESS_SECONDS = 305


def prepare(client, publication, tenant, component, output):
    require(tenant in ('examples', 'foreign') and type(publication) is str
        and re.fullmatch(r'publication:sha256:[a-f0-9]{64}', publication)
        and type(component) is str and re.fullmatch(r'sha256:[a-f0-9]{64}', component),
        'java-tenant-preparation-exact-selection')
    require(client.invocation_timeout_millis == 120000 and client.control_timeout_millis == 15000,
        'java-tenant-preparation-original-execution-profile')
    lifecycle = client.call('release', 'lifecycle', '--publication', publication)
    status = lifecycle['data'].get('status')
    require(lifecycle['outcomeKnown'] is True and type(status) is dict,
        'java-tenant-preparation-known-lifecycle')
    record = status.get('record')
    require(type(record) is dict and record.get('publication') == {'id': publication, 'tenant': tenant}
        and record.get('tenant') == tenant and record.get('componentDigest') == component
        and record.get('state') == 'RELEASE_LIFECYCLE_STATE_ADMITTED'
        and status.get('eligibility') == 'RELEASE_LIVE_ELIGIBILITY_ELIGIBLE',
        'java-tenant-preparation-current-publication')
    generation = record.get('generation')
    require(type(generation) is str and generation.isascii() and generation.isdecimal()
        and str(int(generation)) == generation and 0 < int(generation) < 2**64,
        'java-tenant-preparation-positive-lifecycle-generation')
    require(client.calls < MAX_CALLS and time.monotonic() < client.deadline,
        'java-tenant-preparation-original-campaign-bound')
    began = time.monotonic_ns()
    # Use the existing Client process owner directly for this one exact setup
    # command. RecordingClient's ordinary 25s control and 120s invocation limits
    # are unchanged. Client.complete clips this process to the original deadline.
    response = Client.call(client, '--rpc-timeout-ms', str(MAXIMUM_WAIT_MILLIS),
        'release', 'prepare', '--publication', publication, '--lifecycle-generation', generation,
        '--maximum-wait-ms', str(MAXIMUM_WAIT_MILLIS), codes=(0, 2, 3, 4, 5, 6, 130),
        timeout=PROCESS_SECONDS)
    value = {'schemaVersion': 'latent.java.http-release-preparation.v1',
        'qualification': False, 'tenant': tenant, 'publication': publication,
        'lifecycleGeneration': generation, 'componentDigest': component,
        'setupRpcTimeoutMillis': MAXIMUM_WAIT_MILLIS, 'setupProcessTimeoutMillis': PROCESS_SECONDS*1000,
        'originalInvocationTimeoutMillis': client.invocation_timeout_millis,
        'originalControlTimeoutMillis': client.control_timeout_millis,
        'elapsedNanos': str(time.monotonic_ns()-began), 'response': response}
    encoded = json.dumps(value).encode()
    require(len(encoded) <= 65536, 'java-tenant-preparation-public-record-bound')
    client.retained += len(encoded)
    require(client.retained <= 4*1024*1024, 'java-tenant-preparation-original-retention-bound')
    path = output/(tenant+'-preparation.json')
    write_json(path, value)
    require(response['category'] == 'success' and response['command'] == 'release prepare'
        and response['outcomeKnown'] is True and response['data'].get('prepared') is True
        and response['data'].get('executionAuthorized') is False and response['data'] == {
            'publication': {'id': publication, 'tenant': tenant}, 'lifecycleGeneration': generation,
            'componentDigest': component, 'prepared': True, 'executionAuthorized': False},
        'java-tenant-preparation-exact-ready-result')
    return {'path': path.name, **file_identity(path, 65536)}
