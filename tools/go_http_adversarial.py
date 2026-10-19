"""Finite standard-client lifecycle and redirect oracles, with exact authority."""
from __future__ import annotations

import copy

from tools.phase2_operator_process import require
from tools.rust_capsule_node import selected_revision
from tools.static_api.node import policy

CAPABILITY = 'latent:http/streaming@0.3.0'
SERVICE = 'examples/go-standard-http'
OPERATIONS = ['open', 'write', 'finish', 'read', 'chunk-bytes', 'trailers', 'abort-upload', 'abort-body']
CEILING = {'operations': 64, 'inputBytes': 65536, 'outputBytes': 262144, 'wallTimeMillis': 5000}


def configure(value):
    """Permit Go's ordinary Referer on these two fixture origins only."""
    result = copy.deepcopy(value)
    destinations = result['providers']['httpStreaming']['configuration']['destinations']
    require(len(destinations) == 2, 'adversarial-go-exact-two-origins')
    for destination in destinations:
        require(destination['allowedRequestHeaders'] == ['accept', 'user-agent', 'x-conformance'],
                'adversarial-go-original-header-contract')
        destination['allowedRequestHeaders'].append('referer')
    return result


def authorize_redirect(client, publication, primary, secondary):
    rules = []
    for identity, origin, paths, prefixes, methods in (
            ('ordinary-http', primary, [], ['/conformance/'], ['GET', 'POST']),
            ('exact-redirect-target', secondary, ['/conformance/redirect-target'], [], ['GET'])):
        rules.append({'id': identity, 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [SERVICE], 'publications': [publication], 'capability': CAPABILITY,
            'operations': OPERATIONS,
            'resources': {'kind': 'http', 'origins': [origin], 'methods': methods,
                          'paths': paths, 'pathPrefixes': prefixes}, 'ceiling': dict(CEILING)})
    policy(client, 'policy', 'http-redirect-allow',
           {'formatVersion': 1, 'tenant': 'examples', 'rules': rules})
    return {'capability': CAPABILITY, 'policy': 'http-redirect-allow'}


def cases():
    # The authorised redirect runs last, after a separate explicit policy apply.
    return (
        ('redirect-denied', 27, '/conformance/redirect-denied', 'transport-error', 1),
        ('redirect-stopped', 28, '/conformance/redirect', '302:redirect-stopped', 1),
        ('cookie-jar-denied', 29, '/conformance/json', 'transport-error', 0),
        ('proxy-destination-denied', 30, '/conformance/json', 'proxy-destination-denied', 0),
        ('repeat-requests', 31, '/conformance/json', '200:twice', 2),
        ('root-return-pending', 32, '/conformance/body/partial', 'root-returned-with-pending-body', 1),
        ('root-trap-pending', 33, '/conformance/body/partial', None, 1),
        ('fresh-after-trap', 0, '/conformance/json', '200:domain:7:caf\u00e9:first|\u03bb', 1),
        ('redirect-authorized', 27, '/conformance/redirect', '200:redirected', 2),
    )


def outcome(row, expected, requests, revision, budget):
    response = row['response']
    require(row['processReaped'] and response['outcomeKnown'] is True
            and response['requestDispatched'] is True
            and response['data']['resolvedRevision'] == revision,
            'adversarial-go-known-exact-revision')
    consumption = response['data']['consumption']
    require(consumption['outboundRequests'] == requests and consumption['effectCount'] == 0
            and 0 < int(consumption['cpuFuel']) <= int(budget['cpuFuel'])
            and 0 < int(consumption['peakMemoryBytes']) <= int(budget['memoryBytes']),
            'adversarial-go-effects-or-budget')
    if expected is None:
        require(row['exitCode'] == 4 and response['error']['code'] == 'guest-trap'
                and response['data']['terminalState'] == 'guest_trap' and row['decoded'] is None,
                'adversarial-go-certain-root-trap')
    else:
        require(row['exitCode'] == 0 and row['decoded'] == [expected],
                'adversarial-go-exact-result')


def peer_outcome(value):
    expected = [('primary', name) for name in (
        'redirect-denied', 'redirect', 'domain-json', 'domain-json',
        'partial-body', 'partial-body', 'domain-json', 'redirect')]
    expected.append(('secondary', 'redirect-target'))
    require(value['acceptedConnections'] == value['startedRequests'] == 9
            and value['rejectedRequests'] == value['committedMutations'] == value['openConnections'] == 0
            and [(row['role'], row.get('vector')) for row in value['requests']] == expected,
            'adversarial-go-exact-contacts')
    require(all(row.get('authorizationPresent') is (row['role'] == 'primary')
                and row.get('cookiePresent') is False
                and row.get('proxyAuthorizationPresent') is False
                for row in value['requests']), 'adversarial-go-credential-isolation')
    require(value['requests'][-1].get('closeReason') == 'response-write-complete',
            'adversarial-go-redirect-not-complete')


def run_cases(client, node, source, target, publication, origins, output, probe, result, invoke, retire):
    from tools.rust_capsule_node import deploy
    primary = origins['primary']
    address = f"http://{primary['host']}:{primary['port']}"
    result['adversarialCases'] = []
    for name, which, path, expected, requests in cases():
        if name == 'redirect-authorized':
            grant = authorize_redirect(client, publication, primary, origins['secondary'])
            grants = [item for item in target['grants'] if item['capability'] != CAPABILITY] + [grant]
            target = deploy(client, source / 'deployment.json', publication,
                            generation=str(target['generation']), grants=grants)
        revision = selected_revision(client, target)
        row = invoke(client, target, which, address + path, 'adversarial-' + name)
        outcome(row, expected, requests, revision, target['budget'])
        retire(client, probe, target, output, 'adversarial-' + name)
        result['cases'].append(name)
        result['adversarialCases'].append({'name': name, 'revision': revision,
            'outboundRequests': requests, 'exitCode': row['exitCode'], 'knownAndReaped': True})
    return target
