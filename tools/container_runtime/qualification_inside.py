"""Finite real-node container drill; inputs are independently signed test packages."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, '/opt/lsf/runtime')
from native_runtime.common import document, encode, execute, require
from native_runtime import files

STATE = Path('/var/cache/lsf/container-qualification.json')
DEADLINE = time.monotonic() + 90
CALLS = 0


def call(*arguments, codes=(0,)):
    global CALLS
    CALLS += 1
    require(CALLS <= 64 and time.monotonic() < DEADLINE, 'container-qualification-operation-bound')
    status, output = execute(['/opt/lsf/release/bin/latent', '--config', '/etc/lsf/client.json',
        '--output', 'json', *(str(value) for value in arguments)], maximum=300000,
        timeout=min(5, DEADLINE - time.monotonic()), stdout_only=True)
    require(status in codes, 'container-qualification-command-failed')
    result = document(output, 300000)
    require(result.get('outcomeKnown') is True, 'container-qualification-unknown-outcome')
    return result


def route(name, publication, mount, method, prefix='initial', scheme='http', authority='frontend.example.test'):
    previous = call('trigger', 'get', name, codes=(0, 6))['data']
    generation = previous['trigger']['generation'] if previous['trigger'] else '0'
    operation = prefix + '-' + name + '-' + str(CALLS)
    path = Path('/var/cache/lsf') / (operation + '.json')
    files.create(path, encode({'apiVersion': 'latent.dev/v1alpha1', 'kind': 'HttpTrigger',
        'metadata': {'name': name, 'tenant': 'tests'}, 'spec': {
            'target': {'kind': 'static-web', 'publication': publication}, 'configuration': {
                'profile': 'static-site-v1', 'scheme': scheme, 'host': authority,
                'path': mount, 'pathMatch': 'prefix', 'method': method}}}))
    result = call('trigger', 'apply', path, '--operation-id', operation,
                 '--expected-generation', generation, '--expected-state-version', previous['stateVersion'])
    receipt = result['data']['receipt']
    require(receipt['target']['publication'] == {'id': publication, 'tenant': 'tests'}, 'container-route-target')
    require(call('trigger', 'operation', operation)['data']['receipt'] == receipt, 'container-route-receipt')


def served(path, expected):
    headers = {'Host': 'frontend.example.test', 'Accept': 'text/html'}
    results = []
    for method in ('GET', 'HEAD'):
        connection = http.client.HTTPConnection('127.0.0.1', 18080, timeout=3)
        try:
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            body = response.read(65537)
            require(response.status == 200 and len(body) <= 65536, 'container-static-response')
            require(response.getheader('X-Content-Type-Options') == 'nosniff'
                    and "script-src 'self'" in response.getheader('Content-Security-Policy', ''),
                    'container-browser-policy')
            require(body == b'' if method == 'HEAD' else hashlib.sha256(body).hexdigest() == expected,
                    'container-static-exact-content')
            results.append(response.getheader('ETag'))
        finally:
            connection.close()
    require(results[0] and results[0] == results[1], 'container-head-identity')
    return results[0]


def inventory():
    value = call('node', 'get', 'container-qualification')['data']['inventory']
    require(value['node']['id'] == 'container-qualification' and value['health']['ready'] is True
            and value['pressure']['loadAvailable'] is True, 'container-authenticated-readiness')
    require(int(value['cacheSummary']['entries']) == 0, 'container-static-only-dormancy')
    return value


def run():
    require(sys.argv[1:] in (['publish'], ['reopen']), 'container-drill-mode')
    require(os.geteuid() == 10001, 'container-drill-nonroot')
    os.umask(0o077)
    inventory()
    if sys.argv[1] == 'publish':
        work = Path(document(files.read(Path('/work/current.json'), 4096))['work'])
        require(work.parent == Path('/work') and work.name.startswith('lsf-frontend-'), 'container-test-input-root')
        records = {}
        for name, mount, relative in [('site', '/', 'index.html'), ('documentation', '/docs', 'guide/index.html')]:
            result = call('web', 'publish', work / name / 'package', '--evidence', work / (name + '-evidence/index.json'),
                          '--operation-id', 'container-' + name, '--expected-generation', '0')
            operation = result['data']['operation']
            require(result['data']['auditAck'] is not None, 'container-publication-audit')
            require(call('web', 'operation', operation['operationId'])['data']['operation'] == dict(operation, replayed=True),
                    'container-publication-recovery')
            publication = operation['publication']['id']
            for method in ('GET', 'HEAD'):
                route(name + '-' + method.lower(), publication, mount, method)
            expected = hashlib.sha256(files.read(work / (name + '-build') / relative, 65536)).hexdigest()
            public_path = '/' if name == 'site' else '/docs/guide/'
            records[name] = {'publication': publication, 'path': public_path, 'sha256': expected,
                             'etag': served(public_path, expected)}
        files.create(STATE, encode({'records': records}))
    else:
        records = document(files.read(STATE, 8192))['records']
        require(set(records) == {'site', 'documentation'}, 'container-retained-site-set')
        for name, record in records.items():
            require(served(record['path'], record['sha256']) == record['etag'], 'container-reopen-identity')
            for method in ('get', 'head'):
                trigger = call('trigger', 'get', name + '-' + method)['data']['trigger']
                require(trigger['manifest']['spec']['target'] == {'kind': 'static-web', 'publication': record['publication']}
                        and trigger['manifest']['metadata']['tenant'] == 'tests',
                        'container-reopen-route-target')
    inventory()
    print(encode({'schemaVersion': 'latent.container-serving.v1', 'passed': True, 'mode': sys.argv[1],
                  'sites': len(records), 'getAndHead': True, 'exactBytes': True, 'zeroPreparedCapsules': True,
                  'cliProcesses': CALLS, 'cloudQualified': False}).decode(), end='')


if __name__ == '__main__':
    run()
