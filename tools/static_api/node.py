"""Ordinary operator configuration and exact, receipt-bearing API/site mutations."""
from __future__ import annotations

import hashlib
import socket
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase2_operator_scenario import configure_node
from tools.run_security_profile_workflow import replace_config

TENANT = 'examples'
CAPABILITY = 'latent:http/client@0.2.0'
ORIGIN = {'scheme': 'https', 'host': 'status.backend.test', 'port': 8443}


def configure(directory, fixture, compiler, certificates, credential):
    path = configure_node(directory, fixture, TENANT)
    value = read_json(path)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    value.update(securityProfile='external-capsule-v1',
        limits={'maximumComponentBytes': 32 * 1024 * 1024, 'maximumPayloadBytes': 2 * 1024 * 1024},
        budgetProfile={'mode': 'phase3', 'maximumOutboundRequests': 8,
                       'maximumBlobReadBytes': 65536, 'maximumBlobWriteBytes': 65536},
        capabilityPolicies={'formatVersion': 1, 'maximumControlJobs': 2,
            'store': {'maximumRecords': 64, 'maximumOutcomes': 128, 'maximumCatalogBytes': 4194304,
                      'maximumReadOwners': 64, 'maximumPageRecords': 16}})
    value['cells'][0].update(capacity=2, queueCapacity=4, maximumMemoryBytes=134217728)
    value['execution'].update(maximumWallTimeMillis=120000)
    value['cache'].update(sourceBytes=128 * 1024 * 1024, compiledImageBytes=256 * 1024 * 1024)
    value['audit'].update(records=4096, diskBytes=67108864)
    value['shutdownGraceMillis'] = 5000
    (directory / 'native.key').write_bytes(bytes([83]) * 32)
    (directory / 'native.key').chmod(0o600)
    value['isolatedAot'] = {'compilerExecutable': str(compiler.resolve()),
        'compilerDigest': 'sha256:' + hashlib.sha256(compiler.read_bytes()).hexdigest(),
        'keyFile': 'native.key', 'blobRoot': 'native-blobs', 'receiptRoot': 'native-receipts',
        'process': {'jobTimeoutMillis': 300000, 'maximumOutputBytes': 134217728, 'addressSpaceBytes': 4294967296},
        'cache': {'entries': 8, 'diskBytes': 536870912},
        'images': {'maximumImages': 4, 'maximumImageBytes': 134217728, 'maximumTotalBytes': 536870912}}
    host = f'localhost:{port}'
    value['httpIngress'] = {'formatVersion': 1, 'bind': f'127.0.0.1:{port}', 'transport': {'mode': 'loopback'},
        'authentication': {'mode': 'public-origins', 'origins': [
            {'authority': host, 'subject': 'status-browser', 'tenant': TENANT}]},
        'limits': {'maximumConnections': 16, 'maximumExchanges': 4, 'maximumBufferBytes': 50331648,
                   'maximumRequestsPerConnection': 8, 'idleTimeoutMillis': 1000, 'headerTimeoutMillis': 1000}}
    value['providers'] = {'formatVersion': 1, 'bindings': [{'name': 'status-http', 'tenant': TENANT,
        'consumerService': 'examples/status-api', 'providerService': 'runtime-host',
        'contract': CAPABILITY, 'providerBinding': 'status-http'}], 'http': {
        'identity': {'id': 'http', 'tenant': TENANT, 'service': 'runtime-host', 'epoch': 1},
        'configuration': {'formatVersion': 1, 'publicRoots': False, 'extraRoots': [list((certificates / 'ca.der').read_bytes())],
            'limits': {'maximumRequestBodyBytes': 32768, 'maximumResponseBodyBytes': 32768,
                'maximumEncodedResponseBytes': 32768, 'maximumHeaderBytes': 8192, 'maximumHeaders': 32, 'maximumRedirects': 0},
            'destinations': [{'origin': ORIGIN, 'addresses': {'networks': ['127.0.0.1/32'], 'specialAddresses': ['127.0.0.1']},
                'resolution': {'kind': 'static', 'addresses': ['127.0.0.1']}, 'allowedRequestHeaders': [], 'redirectDestinations': []}]},
        'credentialDirectory': str(credential.parent),
        'credentials': [{'reference': 'status-upstream', 'file': credential.name, 'destination': 0, 'header': 'authorization'}]}}
    replace_config(path, value)
    return path, host


def policy(client, kind, name, document, generation=0):
    source = client.directory / f'{name}-{client.calls}.json'
    write_json(source, document)
    operation = f'{name}-{client.calls}'
    result = client.call('policy', '--kind', kind, 'apply', '--id', name, '--file', source,
                        '--operation-id', operation, '--expected-generation', generation)
    require(result['outcomeKnown'] and result['data']['receipt']['operationId'] == operation, 'static-api-policy-receipt')
    return result['data']['receipt']


def grants(client, startup, publication):
    installed = next(entry for entry in startup['providers'] if entry['id'] == 'http')
    policy(client, 'provider-binding', 'status-http', {'formatVersion': 1, 'tenant': TENANT,
        'capability': CAPABILITY, 'providerProfile': 'bounded-http-v1',
        'configurationDigest': installed['configurationDigest'], 'configurationEpoch': 1, 'restriction': {'operations': ['send']}})
    document = {'formatVersion': 1, 'tenant': TENANT, 'rules': [{'id': 'status', 'effect': 'allow',
        'principals': [{'kind': 'trigger', 'subject': 'status-browser'}], 'services': ['examples/status-api'],
        'publications': [publication], 'capability': CAPABILITY, 'operations': ['send'],
        'resources': {'kind': 'http', 'origins': [ORIGIN], 'paths': ['/health'], 'pathPrefixes': [], 'methods': ['GET']},
        'ceiling': {'operations': 1, 'inputBytes': 32768, 'outputBytes': 65536, 'wallTimeMillis': 2000}}]}
    receipt = policy(client, 'policy', 'status-upstream', document)
    return document, receipt['generation']


def trigger(client, host, method, target, api):
    name = ('api-' if api else 'site-') + method.lower()
    state = client.call('trigger', 'get', name, codes=(0, 6))['data']
    source = client.directory / f'{name}-{client.calls}.json'
    write_json(source, {'apiVersion': 'latent.dev/v1alpha1', 'kind': 'HttpTrigger',
        'metadata': {'name': name, 'tenant': TENANT}, 'spec': {'target': target,
        'configuration': {'profile': 'buffered-v1' if api else 'static-site-v1', 'scheme': 'http',
            'host': host, 'path': '/api' if api else '/', 'pathMatch': 'prefix', 'method': method}}})
    operation = f'{name}-{client.calls}'
    result = client.call('trigger', 'apply', source, '--operation-id', operation,
        '--expected-generation', state['trigger']['generation'] if state['trigger'] else 0,
        '--expected-state-version', state['stateVersion'])
    require(result['outcomeKnown'] and result['data']['receipt']['operationId'] == operation, 'static-api-route-receipt')


def deploy(client, work, publication, host, *, outbound=1):
    value = read_json(work / 'api/deployment.json')
    value['spec']['publication'] = publication
    value['spec']['grants'] = [{'capability': CAPABILITY, 'policy': 'status-upstream'}]
    value['spec']['resources'].update(outboundRequests=outbound, wallTimeLimitMillis=120000)
    state = client.call('deployment', 'get', 'status-api', '--operation-snapshot', codes=(0, 6))['data']
    source = client.directory / f'deploy-{client.calls}.json'; write_json(source, value)
    generation = state['deployment']['generation'] if state.get('deployment') else 0
    client.call('--rpc-timeout-ms', '300000', 'deployment', 'apply', source, '--operation-id', f'deploy-{client.calls}',
        '--expected-generation', generation, '--expected-state-version', state['stateVersion'], timeout=310)
    deployed = client.call('deployment', 'get', 'status-api')['data']['deployment']
    snapshot = client.call('route', 'get')['data']['snapshot']
    selected = [row for row in snapshot['services'] if row['routeId'] == 'status-api']
    require(len(selected) == 1 and len(selected[0]['revisions']) == 1, 'static-api-exact-route-revision')
    revision = selected[0]['revisions'][0]['revisionId']
    target = {'service': value['spec']['service'], 'contract': 'latent:web/application@0.1.0', 'function': 'handle',
        'route': 'status-api', 'publication': publication, 'revision': revision,
        'deploymentGeneration': int(deployed['generation'])}
    for method in ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']:
        trigger(client, host, method, target, True)
    return deployed
