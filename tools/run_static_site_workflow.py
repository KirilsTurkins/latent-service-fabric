#!/usr/bin/env python3
"""Finite signed static-package, OCI, actual CLI/node and browser qualification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Client, Process, bounded_receipt, file_digest, read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import NODE_ID, configure_node, connect, stop
from tools.phase3_web_scenario import FOREIGN_TOKEN, client_profile, foreign_profile, http_response, publish, tree_inventory
from tools.run_phase2_operator_workflow import registry_fixture, registry_profile
from tools.run_security_profile_workflow import replace_config
from tools.test_run import redact

ROOT = Path(__file__).resolve().parents[1]


def configure(directory, fixture):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    # Startup must acquire this endpoint itself. A racing listener causes failure.
    hosts = {'csr': f'localhost:{port}', 'generator': f'127.0.0.1:{port}', 'foreign': f'foreign.static.test:{port}'}
    path = configure_node(directory, fixture, 'tests')
    value = read_json(path)
    value['cells'][0]['queueCapacity'] = 8
    value['limits'] = {'maximumPayloadBytes': 2 * 1024 * 1024}
    value['shutdownGraceMillis'] = 5000
    value['credentials'].append({'token': FOREIGN_TOKEN, 'subject': 'foreign-operator', 'tenant': 'foreign', 'role': 'operator'})
    value['httpIngress'] = {
        'formatVersion': 1, 'bind': f'127.0.0.1:{port}', 'transport': {'mode': 'loopback'},
        'authentication': {'mode': 'public-origins', 'origins': [
            {'authority': host, 'subject': 'static-browser', 'tenant': 'foreign' if name == 'foreign' else 'tests'}
            for name, host in hosts.items()]},
        'limits': {'maximumConnections': 16, 'maximumExchanges': 8, 'maximumBufferBytes': 48 * 1024 * 1024,
                   'maximumRequestsPerConnection': 16, 'idleTimeoutMillis': 1000, 'headerTimeoutMillis': 1000}}
    replace_config(path, value)
    return path, hosts


def apply(client, name, publication, host, mount='/', method='GET', codes=(0,)):
    state = client.call('trigger', 'get', name, codes=(0, 6))['data']
    generation = state['trigger']['generation'] if state['trigger'] else '0'
    operation = f'{name}-{client.calls}'
    source = client.directory / (operation + '.json')
    write_json(source, {'apiVersion': 'latent.dev/v1alpha1', 'kind': 'HttpTrigger',
        'metadata': {'name': name, 'tenant': 'tests'}, 'spec': {
            'target': {'kind': 'static-web', 'publication': publication},
            'configuration': {'profile': 'static-site-v1', 'scheme': 'http', 'host': host,
                              'path': mount, 'pathMatch': 'prefix', 'method': method}}})
    result = client.call('trigger', 'apply', source, '--operation-id', operation,
                         '--expected-generation', generation, '--expected-state-version', state['stateVersion'], codes=codes)
    if codes == (0,):
        receipt = result['data']['receipt']
        require(result['outcomeKnown'] and receipt['formatVersion'] == 2
                and receipt['target']['kind'] == 'static-web'
                and receipt['target']['publication'] == {'id': publication, 'tenant': 'tests'}, 'static-trigger-exact-target')
        lookup = client.call('trigger', 'operation', operation)
        require(lookup['outcomeKnown'] and lookup['data']['receipt'] == receipt, 'static-trigger-operation-recovery')
        return receipt
    return result


def idle(client):
    deadline = min(client.deadline, time.monotonic() + 8)
    while True:
        value = client.call('node', 'get', NODE_ID)['data']['inventory']
        rows = {row['name']: row for row in value['topology']['entries']}
        require(value['topology']['available'] and all(name in rows for name in
                ['http-listener', 'http-owner', 'http-connections', 'http-exchanges', 'http-buffer-reservations', 'guest-stores']),
                'static-owner-observations-missing')
        if all(rows[name]['activeCount'] == '0' for name in ['http-connections', 'http-exchanges', 'http-buffer-reservations']):
            break
        require(time.monotonic() < deadline, 'static-http-owner-not-reclaimed')
        time.sleep(0.025)
    require(value['cacheSummary']['entries'] == '0' and value['cacheSummary']['compiledImageBytes'] == '0'
            and all(cell['granted'] == '0' and cell['active'] == 0 for cell in value['cellCapacity'])
            and value['quotas']['usage']['activeActivations'] == 0, 'static-allocated-execution')
    require(all(row['activeCount'] == '0' for row in rows.values()
                if row['ownership'] in ('activation-scoped', 'service-resident')), 'static-service-resources')
    return {'cells': value['cellCapacity'], 'cache': value['cacheSummary'], 'quotaUsage': value['quotas']['usage'],
            'topology': [row for row in rows.values() if row['name'].startswith(('http-', 'guest-', 'execution-cell'))]}


def audit(client, receipts):
    expected = {receipt['operationId']: receipt for receipt in receipts}
    attempts, committed, tokens = {}, set(), set()
    token, previous, pages = None, 0, 0
    for _ in range(64):
        arguments = ['audit', 'query', '--scope', 'tenant', '--page-size', '2']
        if token:
            arguments += ['--page-token', token]
        data = client.call(*arguments)['data']
        require(data['coverage']['unknownOutcomes'] == '0', 'static-audit-unknown-outcome')
        pages += 1
        for row in data['records']:
            sequence = int(row['sequence'])
            require(sequence > previous, 'static-audit-order')
            previous = sequence
            attempt = row['data'].get('attempt')
            outcome = row['data'].get('outcome')
            if attempt and attempt['operationId'] in expected:
                receipt = expected[attempt['operationId']]
                require(attempt['requestDigest'] == receipt['requestDigest']
                        and isinstance(attempt['previewReceiptDigest'], str)
                        and len(attempt['previewReceiptDigest']) == 71,
                        'static-audit-preview-association')
                attempts[row['sequence']] = (receipt, attempt['previewReceiptDigest'])
                identities = attempt['identities']
            elif outcome and outcome['attemptSequence'] in attempts:
                receipt, preview_digest = attempts[outcome['attemptSequence']]
                require(outcome['result'] == 'AUDIT_OPERATION_RESULT_COMMITTED'
                        and outcome['receiptDigest'] == preview_digest, 'static-audit-commit')
                committed.add(receipt['operationId'])
                identities = outcome['identities']
            else:
                continue
            target = receipt['target']
            require(identities['trigger'] == receipt['triggerId']
                    and identities['triggerGeneration'] == receipt['objectGeneration']
                    and identities['stateVersion'] == receipt['stateVersion']
                    and identities['routeGeneration'] == '0'
                    and identities['publicationId'] == target['publication']['id']
                    and identities['staticWeb'] == {key: target[key] for key in
                        ('webManifestDigest', 'assetsDigest', 'webGeneration')}
                    and all(identities[key] is None for key in
                        ('componentDigest', 'deployment', 'deploymentGeneration', 'revision', 'rollout')),
                    'static-audit-exact-nonexecutable-target')
        token = data['page']['nextPageToken']
        if not token:
            break
        require(token not in tokens and len(token) <= 4096, 'static-audit-page-token')
        tokens.add(token)
    require(not token and pages > 1 and committed == set(expected), 'static-audit-operation-coverage')
    return {'pages': pages, 'committedOperations': len(committed), 'exactStaticIdentities': True}


def packages(client, fixture, directory, records, profile):
    for name, record in records.items():
        source = fixture / name
        summary = client.call('package', 'inspect', source / 'package')['data']
        require(summary['packageDigest'] == record['packageDigest'] and summary['componentDigest'] is None,
                'static-package-identity')
        client.call('--tenant', 'tests', 'package', 'verify', source / 'package',
                    '--evidence-index', source / 'evidence/index.json', '--evidence-root', source / 'evidence',
                    '--policy', fixture / 'policy.json')
        # A registry tag is only an upload label. Retrieval and publication are exact digest operations.
        client.call('package', 'push', source / 'package', '--registry-profile', profile, '--reference', name,
                    '--evidence-index', source / 'evidence/index.json', '--evidence-root', source / 'evidence')
        output = directory / name
        output.mkdir()
        client.call('package', 'pull', '--registry-profile', profile, '--reference', record['packageDigest'],
                    '--output-dir', output / 'package', '--evidence-output', output / 'evidence')
        require(tree_inventory(output / 'package', client) == tree_inventory(source / 'package', client), 'static-oci-package-bytes')
        require(tree_inventory(output / 'evidence', client) == tree_inventory(source / 'evidence', client), 'static-oci-evidence-bytes')


def browser(client, args, hosts, version, mode='navigation', transition=None):
    receipt = client.directory / f'browser-{client.calls}-{mode}.json'
    ready = receipt.with_suffix('.ready.json')
    resume = receipt.with_suffix('.resume.json')
    argv = [str(args.node_js), str(ROOT / 'tools/static-sites/browser.mjs'), str(args.toolchain), str(args.chrome),
            'http://' + hosts['csr'], 'http://' + hosts['generator'], version, str(receipt), mode, str(ready), str(resume)]
    process = Process(argv, ROOT, client.environment, client.cancellation, maximum=262144)
    try:
        if transition:
            deadline = min(client.deadline, time.monotonic() + 25)
            while not ready.exists():
                process.drain()
                require(not process.owner.exited() and time.monotonic() < deadline, 'static-browser-cutover-readiness')
                time.sleep(0.025)
            require(read_json(ready)['stage'] == 'A-document-selected', 'static-browser-selected-document')
            transition()
            write_json(resume, {'stage': 'B-trigger-committed'})
        result = process.complete(min(client.deadline, time.monotonic() + 75))
        require(result.returncode == 0, 'static-browser-qualification-failed: ' +
                redact(result.stderr.decode('utf-8', errors='replace'))[-1600:])
        return read_json(receipt, 65536)
    finally:
        process.close()


def smoke(client, node, hosts, records, publications):
    observations = []
    for label in ('cold', 'warm'):
        started = time.monotonic_ns()
        body, fields = http_response(client, node, hosts['csr'], '/orders/42', headers={'Accept': 'text/html'})
        require(b'lsf-static-app' in body and fields['cache-control'] == 'private, no-cache', 'static-spa-alias')
        observations.append({'cache': label, 'requestNanos': str(time.monotonic_ns() - started), 'etag': fields['etag']})
    http_response(client, node, hosts['csr'], '/orders/42', headers={'Accept': 'text/html', 'If-None-Match': fields['etag']}, expected=304)
    for host, mount in [(hosts['generator'], ''), (hosts['csr'], '/docs')]:
        require(b'Static home' in http_response(client, node, host, mount + '/')[0], 'static-root-document')
        _, redirect = http_response(client, node, host, mount + '/guide?q=1', expected=308)
        require(redirect['location'] == mount + '/guide/?q=1', 'static-mounted-redirect')
        http_response(client, node, host, mount + '/guide/missing', headers={'Accept': 'text/html'}, expected=404)
    record = records['csr-a']
    asset = next(row for row in record['assets'] if row['mediaType'] == 'text/javascript')
    immutable = '/_lsf/assets/' + publications['csr-a'] + asset['path']
    body, immutable_fields = http_response(client, node, hosts['csr'], immutable)
    require('immutable' in immutable_fields['cache-control'] and len(body) == asset['size'], 'static-immutable-profile')
    http_response(client, node, hosts['foreign'], immutable, expected=(403, 404))
    for path in ['/assets/missing.js', '/api/no-such-data']:
        http_response(client, node, hosts['csr'], path, headers={'Accept': 'application/json'}, expected=404)
    for path in ['/orders/%2f42', '/orders//42', '/orders/../42', '/orders\\42']:
        http_response(client, node, hosts['csr'], path, headers={'Accept': 'text/html'}, expected=400)
    return observations, immutable, immutable_fields['etag']


def run(args):
    metadata = read_json(args.fixture / 'fixture.json')
    require(metadata['schemaVersion'] == 'latent.static.reference.fixture.v1' and metadata['actualCsrBuilds'], 'static-build-fixture')
    records = {row['name']: row for row in metadata['fixtures']}
    require(set(records) == {'csr-a', 'csr-b', 'generator', 'generator-docs'}, 'static-fixture-set')
    with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-static-workflow-') as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        node_root, client_root, pulled = (directory / name for name in ('node', 'client', 'pulled'))
        for path in (node_root, client_root, pulled): path.mkdir(mode=0o700)
        client = Client(args.cli, client_root, cancellation, time.monotonic() + 600)
        original = tree_inventory(args.fixture, client)
        identity = {name: file_digest(path, 1024 * 1024 * 1024, cancellation, client.deadline)
                    for name, path in [('cliDigest', args.cli), ('nodeDigest', args.node)]}
        with registry_fixture(args, directory, cancellation) as (origin, ca):
            profile = registry_profile(client_root, origin, ca)
            registry = read_json(profile)
            registry['repository'] = 'lsf/static-workflow-' + uuid.uuid4().hex
            profile = client_root / 'static-registry.json'
            write_json(profile, registry)
            packages(client, args.fixture, pulled, records, profile)
        config, hosts = configure(node_root, args.fixture)
        node = None
        try:
            node = connect(client, args.node, node_root, config, 'tests', 1)
            selected_profile = client_profile(client, 1)
            before = idle(client)
            publications = {name: publish(client, pulled, name)['publication']['id'] for name in records}
            receipts = []
            for name, host, mount in [('csr-a', hosts['csr'], '/'), ('generator', hosts['generator'], '/'), ('generator-docs', hosts['csr'], '/docs')]:
                for method in ('GET', 'HEAD'):
                    receipts.append(apply(client, name + '-' + method.lower(), publications[name], host, mount, method))
            dormant = idle(client)
            timings, immutable, etag = smoke(client, node, hosts, records, publications)
            browser_a = browser(client, args, hosts, 'A')
            handoff = browser(client, args, hosts, 'A', mode='cutover', transition=lambda:
                              receipts.append(apply(client, 'csr-a-get', publications['csr-b'], hosts['csr'])))
            receipts.append(apply(client, 'csr-a-head', publications['csr-b'], hosts['csr'], method='HEAD'))
            browser_b = browser(client, args, hosts, 'B')
            rollback = apply(client, 'csr-a-get', publications['csr-a'], hosts['csr'])
            receipts.append(rollback)
            require(http_response(client, node, hosts['csr'], '/orders/42', headers={'Accept': 'text/html'})[1]['etag'] == timings[0]['etag'],
                    'static-explicit-rollback-identity')
            receipts.append(apply(client, 'csr-a-get', publications['csr-b'], hosts['csr']))
            revoked = client.call('web', 'revoke', '--publication', publications['csr-a'],
                                  '--operation-id', 'revoke-static-a', '--expected-generation', '1')
            require(revoked['outcomeKnown'], 'static-revocation-uncertain')
            http_response(client, node, hosts['csr'], immutable, headers={'If-None-Match': etag}, expected=(403, 404))
            rejected = apply(client, 'csr-a-get', publications['csr-a'], hosts['csr'], codes=(4,))
            require(rejected['category'] == 'platform-failure', 'static-revoked-rollback-admitted')
            original_profile = client.config
            client.config = foreign_profile(client, selected_profile)
            denied = client.call('web', 'get', '--publication', publications['csr-b'], codes=(4, 6))
            require(denied['category'] != 'success', 'static-foreign-publication')
            client.config = original_profile
            audit_receipt = audit(client, receipts)
            # Disconnect a selected immutable read; its shared request owners must retire.
            asset = next(row for row in records['csr-b']['assets'] if row['mediaType'] == 'text/javascript')
            current_immutable = '/_lsf/assets/' + publications['csr-b'] + asset['path']
            http_response(client, node, hosts['csr'], current_immutable)
            peer = socket.create_connection(node.startup_record['httpEndpoint'].rsplit(':', 1), timeout=5)
            peer.sendall(f'GET {current_immutable} HTTP/1.1\r\nHost: {hosts["csr"]}\r\n\r\n'.encode())
            peer.close()
            after = idle(client)
            stop(client, node)
            shutdown = stopped_record(node)
            node = None
            require(tree_inventory(args.fixture, client) == original, 'static-fixture-mutated')
            return bounded_receipt({'schemaVersion': 'latent.static.workflow.v1', 'passed': True,
                'identity': identity, 'publications': publications, 'packageDigests': {n: r['packageDigest'] for n, r in records.items()},
                'ociExactDigestRoundtrip': True, 'browserA': browser_a, 'cutover': handoff, 'browserB': browser_b,
                'rollback': rollback, 'revokedConditionalDenied': True, 'revokedRollbackDenied': True,
                'foreignPublicationDenied': True, 'before': before, 'dormant': dormant, 'after': after,
                'audit': audit_receipt, 'requests': timings, 'shutdown': shutdown, 'cliProcesses': client.calls})
        finally:
            client.node = None
            if node is not None: node.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cli', 'node', 'fixture', 'toolchain', 'chrome'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--registry-origin')
    parser.add_argument('--registry-ca', type=Path)
    args = parser.parse_args()
    for name in ('cli', 'node', 'fixture', 'toolchain', 'chrome'):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    args.node_js = Path(shutil.which('node')).resolve(strict=True)
    require(sys.platform == 'linux', 'static-workflow-linux-required')
    print(run(args))


if __name__ == '__main__':
    main()
