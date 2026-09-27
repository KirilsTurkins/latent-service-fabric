"""Real released static serving and OCI; no Rust, cloud, or generated runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Client, Process, read_json, require, write_json
from tools.phase2_operator_scenario import NODE_ID, configure_node, connect, stop
from tools.phase3_web_scenario import http_response
from tools.run_oci_registry_tests import certificates, ready
from tools.run_phase2_operator_workflow import registry_profile
from tools.run_static_site_workflow import apply, idle


def run(args):
    work = args.work.resolve(strict=True)
    with owned_cancellation() as cancellation:
        registry_root, node_root, client_root = (work / name for name in ('oci', 'node', 'client'))
        for directory in (registry_root, node_root, client_root):
            directory.mkdir(mode=0o700)
        client = Client(args.cli, client_root, cancellation, time.monotonic() + 100)
        certificates(registry_root)
        value = read_json(registry_root / 'config.json')
        value['storage']['rootDirectory'] = str(registry_root / 'data')
        value['http'].update(address='127.0.0.1')
        value['http']['tls'] = {'cert': str(registry_root / 'server.pem'), 'key': str(registry_root / 'server.key')}
        value['http']['auth']['htpasswd']['path'] = str(registry_root / 'htpasswd')
        write_json(registry_root / 'local.json', value)
        registry = Process(['/usr/local/bin/zot', 'serve', str(registry_root / 'local.json')], registry_root,
                           client.environment, cancellation, maximum=262144)
        node = None
        try:
            ready('https://127.0.0.1:5000', registry_root / 'ca.pem', timeout=10)
            profile = registry_profile(client_root, 'https://127.0.0.1:5000', registry_root / 'ca.der')
            records = {}
            for name in ('site', 'documentation'):
                package, evidence = work / name / 'package', work / (name + '-evidence')
                digest = client.call('package', 'inspect', package)['data']['packageDigest']
                client.call('package', 'push', package, '--registry-profile', profile, '--reference', name,
                            '--evidence-index', evidence / 'index.json', '--evidence-root', evidence)
                pulled = work / (name + '-pulled')
                pulled.mkdir(mode=0o700)
                client.call('package', 'pull', '--registry-profile', profile, '--reference', digest,
                            '--output-dir', pulled / 'package', '--evidence-output', pulled / 'evidence')
                inspected = client.call('package', 'inspect', pulled / 'package')['data']
                require(inspected['packageDigest'] == digest, 'frontend-oci-exact-package')
                client.call('--tenant', 'tests', 'package', 'verify', pulled / 'package',
                            '--evidence-index', pulled / 'evidence/index.json', '--evidence-root', pulled / 'evidence',
                            '--policy', work / 'policy.json')
                records[name] = {'digest': digest, 'path': pulled}
            config = configure_node(node_root, work, 'tests')
            settings = read_json(config)
            settings['shutdownGraceMillis'] = 5000
            settings['limits'] = {'maximumPayloadBytes': 2 * 1024 * 1024}
            settings['httpIngress'] = {'formatVersion': 1, 'bind': '127.0.0.1:18080',
                'transport': {'mode': 'loopback'}, 'authentication': {'mode': 'public-origins', 'origins': [
                    {'authority': 'frontend.example.test', 'subject': 'frontend-browser', 'tenant': 'tests'}]},
                'limits': {'maximumConnections': 4, 'maximumExchanges': 2, 'maximumBufferBytes': 24 * 1024 * 1024,
                           'maximumRequestsPerConnection': 8}}
            config = node_root / 'frontend-node.json'
            write_json(config, settings)
            node = connect(client, args.node, node_root, config, 'tests', 1)
            before = idle(client)
            for name, record in records.items():
                result = client.call('web', 'publish', record['path'] / 'package',
                                    '--evidence', record['path'] / 'evidence/index.json',
                                    '--operation-id', 'frontend-' + name, '--expected-generation', '0')
                receipt = result['data']['operation']
                require(result['outcomeKnown'] and result['data']['auditAck'] is not None, 'frontend-publication-known')
                recovered = client.call('web', 'operation', receipt['operationId'])
                require(recovered['outcomeKnown'] and recovered['data']['operation'] == dict(receipt, replayed=True),
                        'frontend-operation-recovered')
                record['publication'] = receipt['publication']['id']
            for method in ('GET', 'HEAD'):
                apply(client, 'frontend-' + method.lower(), records['site']['publication'], 'frontend.example.test', method=method)
            body, _ = http_response(client, node, 'frontend.example.test', '/', headers={'Accept': 'text/html'})
            require(b'Static release example' in body, 'frontend-served-site')
            for method in ('GET', 'HEAD'):
                apply(client, 'docs-' + method.lower(), records['documentation']['publication'], 'frontend.example.test',
                      mount='/docs', method=method)
            body, _ = http_response(client, node, 'frontend.example.test', '/docs/guide/', headers={'Accept': 'text/html'})
            require(b'Release guide' in body, 'frontend-served-documentation')
            renewal = client.call('web', 'renew-evidence', '--publication', records['site']['publication'],
                                 '--package-digest', records['site']['digest'], '--evidence', work / 'site-renewal/index.json',
                                 '--operation-id', 'frontend-renewal', '--expected-generation', '1')
            require(renewal['data']['operation']['resultingGeneration'] == '2', 'frontend-renewal-generation')
            # Explicit new operations change both routes and then roll them back.
            for publication in (records['documentation']['publication'], records['site']['publication']):
                for method in ('GET', 'HEAD'):
                    apply(client, 'frontend-' + method.lower(), publication, 'frontend.example.test', method=method)
            require(b'Static release example' in http_response(client, node, 'frontend.example.test', '/')[0], 'frontend-rollback')
            after = idle(client)
            stop(client, node)
            # Respect the persisted real clock floor; never edit/advance it or
            # use a fixture clock to make a replacement owner start early.
            floor = read_json(node_root / 'data/supply-chain/floor.json')['restartNotBefore']
            require(type(floor) is int and floor <= time.time() + 6, 'frontend-restart-clock-bound')
            while time.time() < floor:
                cancellation.check()
                require(time.monotonic() < client.deadline, 'frontend-restart-deadline')
                time.sleep(0.05)
            node = connect(client, args.node, node_root, config, 'tests', 2)
            require(b'Static release example' in http_response(client, node, 'frontend.example.test', '/')[0], 'frontend-restart')
            require(b'Release guide' in http_response(client, node, 'frontend.example.test', '/docs/guide/')[0], 'frontend-docs-restart')
            stop(client, node)
            node = None
            return {'passed': True, 'actualReleasedNode': True, 'actualTlsOciByDigest': True,
                    'publishedSiteAndDocumentation': True, 'operationReceiptRecovery': True, 'evidenceRenewal': True,
                    'explicitRouteRollback': True, 'restartPreservedBothPublications': True,
                    'dormantExecutionBeforeAndAfter': before['cache']['entries'] == after['cache']['entries'] == '0',
                    'cliProcesses': client.calls}
        finally:
            client.node = None
            if node is not None:
                node.close()
            registry.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work', 'cli', 'node'):
        parser.add_argument('--' + name, type=Path, required=True)
    try:
        result = run(parser.parse_args())
    except Exception as error:
        reason = str(error)
        result = {'passed': False, 'reason': reason if re.fullmatch(r'[a-z0-9-]{1,256}', reason)
                  else type(error).__name__}
    print(json.dumps(result, separators=(',', ':')))
