#!/usr/bin/env python3
"""Finite real-TLS/Chromium qualification of exact signed native publications."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Client, Process, file_digest, read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import configure_node, connect, stop
from tools.phase3_web_scenario import FOREIGN_TOKEN
from tools.run_security_profile_workflow import replace_config
from tools.run_static_site_workflow import idle

STAGES = ('default', 'allowed', 'removed', 'restored', 'new-ungranted', 'new-opted-in',
          'expiring', 'expired', 'renewed', 'revoked', 'restart-revoked')


def publish_message(path, value):
    """Never expose a partially written IPC request or replace an old one."""
    temporary = path.with_suffix(path.suffix + '.pending')
    write_json(temporary, value)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def script(client, executable, arguments, timeout=120):
    process = Process([str(executable), *map(str, arguments)], ROOT, client.environment,
                      client.cancellation, maximum=262144)
    try:
        result = process.complete(min(client.deadline, time.monotonic() + timeout))
        if result.returncode != 0:
            try:
                failure = json.loads(result.stdout).get('failure', {})
                reason = failure.get('message')
                client.fixture_failure = reason if isinstance(reason, str) and re.fullmatch(r'[a-z][a-z-]{0,95}', reason) else 'unavailable'
            except (ValueError, AttributeError):
                client.fixture_failure = 'unavailable'
            require(False, 'native-cors-fixture-command-failed')
        return json.loads(result.stdout)
    finally:
        process.close()


def wait_file(client, browser, path, timeout=45):
    until = min(client.deadline, time.monotonic() + timeout)
    while not path.exists():
        client.cancellation.check()
        browser.drain()
        if client.node:
            client.node.drain()
        require(not browser.owner.exited(), 'native-cors-browser-exited')
        require(time.monotonic() < until, 'native-cors-browser-stage-deadline')
        time.sleep(0.025)
    return read_json(path)


def apply(client, publication, authority, method):
    name = 'cors-' + method.lower()
    state = client.call('trigger', 'get', name, codes=(0, 6))['data']
    operation = f'{name}-{client.calls}'
    source = client.directory / (operation + '.json')
    write_json(source, {'apiVersion': 'latent.dev/v1alpha1', 'kind': 'HttpTrigger',
        'metadata': {'name': name, 'tenant': 'tests'}, 'spec': {
            'target': {'kind': 'static-web', 'publication': publication},
            'configuration': {'profile': 'static-site-v1', 'scheme': 'https', 'host': authority,
                              'path': '/', 'pathMatch': 'prefix', 'method': method}}})
    result = client.call('trigger', 'apply', source, '--operation-id', operation,
        '--expected-generation', state['trigger']['generation'] if state['trigger'] else '0',
        '--expected-state-version', state['stateVersion'])
    receipt = result['data']['receipt']
    require(result['outcomeKnown'] and receipt['target']['kind'] == 'static-web'
            and receipt['target']['publication'] == {'id': publication, 'tenant': 'tests'},
            'native-cors-exact-static-route')
    return receipt


def run(args, directory, receipt):
    work, node_root, client_root = (directory / name for name in ('fixture', 'node', 'client'))
    for parent in (node_root, client_root):
        parent.mkdir(mode=0o700)
    with owned_cancellation() as cancellation:
        client = Client(args.cli, client_root, cancellation, time.monotonic() + 420)
        node, browser = None, None
        shutdown, phases, lifecycle = [], [], []
        try:
            fixture = script(client, args.node_js, [ROOT / 'tools/cross-origin/native-fixture.mjs',
                'prepare', args.cli, Path('/usr/bin/python3').resolve(strict=True), args.font, work])
            require(fixture['prepared'] and fixture['testIdentityOnly'], 'native-cors-signed-fixtures')
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            authority, foreign = f'assets.lsf.localhost:{port}', f'foreign.lsf.localhost:{port}'
            config = configure_node(node_root, work, 'tests')
            settings = read_json(config)
            settings['shutdownGraceMillis'] = 5000
            settings['limits'] = {'maximumPayloadBytes': 2 * 1024 * 1024}
            settings['audit'].update(records=1024, diskBytes=16 * 1024 * 1024)
            settings['credentials'].append({'token': FOREIGN_TOKEN, 'subject': 'foreign-operator',
                                           'tenant': 'foreign', 'role': 'operator'})
            settings['httpIngress'] = {'formatVersion': 1, 'bind': f'127.0.0.1:{port}',
                'transport': {'mode': 'tls', 'certificateFile': str(work / 'tls/server.pem'),
                              'privateKeyFile': str(work / 'tls/key.pem')},
                'authentication': {'mode': 'public-origins', 'origins': [
                    {'authority': authority, 'subject': 'asset-reader', 'tenant': 'tests'},
                    {'authority': foreign, 'subject': 'foreign-reader', 'tenant': 'foreign'}]},
                'limits': {'maximumConnections': 16, 'maximumExchanges': 8,
                           'maximumBufferBytes': 48 * 1024 * 1024, 'maximumRequestsPerConnection': 16,
                           'idleTimeoutMillis': 1000, 'headerTimeoutMillis': 1000}}
            replace_config(config, settings)
            node = connect(client, args.node, node_root, config, 'tests', 1)
            require(node.startup_record['httpEndpoint'] == f'127.0.0.1:{port}', 'native-cors-tls-endpoint')
            before = idle(client)
            publications = {}
            original = client.config
            foreign_profile = copy.deepcopy(read_json(original))
            foreign_profile['profiles'][0].update(tenant='foreign', token=FOREIGN_TOKEN)
            foreign_config = client_root / 'foreign.json'
            write_json(foreign_config, foreign_profile)
            for name in ('a', 'b', 'anonymous', 'foreign'):
                client.config = foreign_config if name == 'foreign' else original
                result = client.call('web', 'publish', work / name / 'package',
                    '--evidence', work / (name + '-evidence/index.json'), '--operation-id', 'cors-publish-' + name,
                    '--expected-generation', '0')
                operation = result['data']['operation']
                require(result['outcomeKnown'] and result['data']['auditAck'] is not None
                        and operation['publication']['tenant'] == ('foreign' if name == 'foreign' else 'tests'),
                        'native-cors-publication-audit')
                publications[name] = operation['publication']['id']
            client.config = original
            require(len(set(publications.values())) == 4, 'native-cors-distinct-publications')
            for method in ('GET', 'HEAD'):
                apply(client, publications['a'], authority, method)
            write_json(work / 'browser-input.json', {'assets': 'https://' + authority,
                       'foreign': 'https://' + foreign, 'publications': publications})
            browser = Process([str(args.node_js), str(ROOT / 'tools/cross-origin/native-browser.mjs'),
                str(args.toolchain), str(args.chrome), str(work)], ROOT, client.environment, cancellation, maximum=262144)
            callers = wait_file(client, browser, work / 'browser-ready.json')
            require(set(callers) == {'approved', 'crossSite', 'unrelated'}, 'native-cors-caller-origins')

            def grant(name, credentials='include'):
                return {'authority': authority, 'tenant': 'tests', 'publication': publications[name],
                        'origins': [callers['approved'], callers['crossSite']], 'credentials': credentials}

            def restart(grants):
                nonlocal node
                stop(client, node)
                shutdown.append(stopped_record(node))
                node = None
                floor = read_json(node_root / 'data/supply-chain/floor.json')['restartNotBefore']
                require(type(floor) is int and floor <= time.time() + 6, 'native-cors-real-clock-floor')
                while time.time() < floor:
                    cancellation.check()
                    browser.drain()
                    require(time.monotonic() < client.deadline, 'native-cors-restart-deadline')
                    time.sleep(0.025)
                settings['httpIngress']['crossOriginAssets'] = grants
                replace_config(config, settings)
                node = connect(client, args.node, node_root, config, 'tests', len(shutdown) + 1)

            def renew(label, lifetime):
                proof = script(client, args.node_js, [ROOT / 'tools/cross-origin/native-fixture.mjs',
                    'sign', args.cli, work, 'b', label, lifetime], timeout=30)
                old = client.call('web', 'get', '--publication', publications['b'])['data']['record']
                result = client.call('web', 'renew-evidence', '--publication', publications['b'],
                    '--package-digest', fixture['fixtures']['b']['packageDigest'],
                    '--evidence', work / ('b-' + label) / 'index.json', '--operation-id', 'cors-' + label,
                    '--expected-generation', old['generation'])
                operation = result['data']['operation']
                require(result['outcomeKnown'] and operation['publication']['id'] == publications['b']
                        and int(operation['resultingGeneration']) == int(old['generation']) + 1,
                        'native-cors-exact-evidence-renewal')
                lifecycle.append({'kind': label, 'publication': publications['b'],
                                  'generation': operation['resultingGeneration'], **proof})
                for method in ('GET', 'HEAD'):
                    apply(client, publications['b'], authority, method)
                return proof

            expiring = None
            for index, stage in enumerate(STAGES):
                receipt['stage'] = stage
                if stage in ('allowed', 'restored'):
                    restart([grant('a'), grant('anonymous', 'omit')])
                elif stage == 'removed':
                    restart([])
                elif stage == 'new-ungranted':
                    for method in ('GET', 'HEAD'):
                        apply(client, publications['b'], authority, method)
                elif stage == 'new-opted-in':
                    restart([grant('b'), grant('anonymous', 'omit')])
                elif stage == 'expiring':
                    expiring = renew('short-proof', 20)
                elif stage == 'expired':
                    while time.time() <= expiring['expiresAt'] + 1:
                        cancellation.check()
                        browser.drain()
                        node.drain()
                        require(time.monotonic() < client.deadline, 'native-cors-evidence-expiry-deadline')
                        time.sleep(0.05)
                elif stage == 'renewed':
                    renew('renewed-proof', 900)
                elif stage == 'revoked':
                    old = client.call('web', 'get', '--publication', publications['b'])['data']['record']
                    result = client.call('web', 'revoke', '--publication', publications['b'],
                        '--operation-id', 'cors-revoke', '--expected-generation', old['generation'])
                    require(result['outcomeKnown'], 'native-cors-known-revocation')
                    lifecycle.append({'kind': 'revoke', 'operation': result['data']['operation']})
                elif stage == 'restart-revoked':
                    restart([grant('b'), grant('anonymous', 'omit')])
                publish_message(work / f'{index}-request.json', {'stage': stage})
                result = wait_file(client, browser, work / f'{index}-result.json')
                require(result['stage'] == stage and result['passed'] is True, 'native-cors-browser-oracle')
                phases.append(result)
            completed = browser.complete(min(client.deadline, time.monotonic() + 10))
            require(completed.returncode == 0, 'native-cors-browser-final-oracle')
            browser.close()
            browser_receipt = read_json(work / 'browser-result.json', maximum=512 * 1024)
            require(browser_receipt['passed'] and browser_receipt['nativeRuntimeQualified']
                    and browser_receipt['cleanup'] == 'browser-and-caller-listener-closed', 'native-cors-browser-cleanup')
            after = idle(client)
            stop(client, node)
            shutdown.append(stopped_record(node))
            node = None
            receipt.update(passed=True, nativeRuntimeQualified=True, publications=publications,
                packageDigests={name: value['packageDigest'] for name, value in fixture['fixtures'].items()},
                phases=phases, lifecycle=lifecycle, shutdown=shutdown, before=before, after=after,
                browserVersion=browser_receipt['browser'], browserCases=len(browser_receipt['cases']),
                cliProcesses=client.calls, nodeDigest=file_digest(args.node, 256 * 1024 * 1024, cancellation, client.deadline),
                cliDigest=file_digest(args.cli, 256 * 1024 * 1024, cancellation, client.deadline))
            del receipt['stage']
        finally:
            client.node = None
            if browser is not None:
                browser.close()
            if node is not None:
                node.close()
            if client.failed_call is not None:
                receipt['failedCall'] = client.failed_call
            if hasattr(client, 'fixture_failure'):
                receipt['fixtureFailure'] = client.fixture_failure
            network = work / 'browser-result.json'
            if network.is_file():
                content = network.read_bytes()
                require(len(content) <= 512 * 1024, 'native-cors-network-receipt-bound')
                (args.output / 'browser-network.json').write_bytes(content)
                receipt['networkReceiptSha256'] = hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cli', 'node', 'toolchain', 'chrome', 'font', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    require(sys.platform == 'linux' and os.geteuid() != 0, 'native-cors-unprivileged-linux-required')
    for name in ('cli', 'node', 'toolchain', 'chrome', 'font'):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    executable = shutil.which('node')
    require(executable is not None, 'native-cors-node-runtime-required')
    args.node_js = Path(executable).resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='lsf-cross-origin-'))
    receipt = {'schemaVersion': 'latent.cross-origin.native-qualification.v1', 'passed': False,
               'nativeRuntimeQualified': False, 'productionTlsQualified': False, 'testIdentityOnly': True}
    status = 1
    try:
        run(args, directory, receipt)
        status = 0
    except Exception as error:
        receipt['failure'] = {'kind': type(error).__name__, 'message': str(error)[:500]}
    finally:
        require(directory.parent == Path(tempfile.gettempdir()).resolve()
                and directory.name.startswith('lsf-cross-origin-'), 'native-cors-cleanup-root')
        shutil.rmtree(directory)
        (args.output / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': receipt['passed'], 'failure': receipt.get('failure'), 'stage': receipt.get('stage')}))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
