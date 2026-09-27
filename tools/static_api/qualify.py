"""Real signed TypeScript API, independent static publication, TLS and browser."""
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import re
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Client, read_json, require, write_json
from tools.phase2_operator_scenario import NODE_ID, TOKEN, connect, stop
from tools.run_oci_registry_tests import certificates
from tools.static_api.node import configure, deploy, grants, policy, trigger
from tools.static_api.peer import Peer


def request(host, path='/api/status', method='GET', headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', int(host.rsplit(':', 1)[1]), timeout=125)
    try:
        connection.request(method, path, headers={'Host': host, 'Connection': 'close', **(headers or {})})
        response = connection.getresponse(); body = response.read(65537)
        require(len(body) <= 65536, 'static-api-response-bound')
        return response.status, body, dict(response.getheaders())
    finally:
        connection.close()


def run(args):
    work = args.work.resolve(strict=True)
    result = {'schemaVersion': 'latent.static-api.composition.v1', 'passed': False, 'cloudQualified': False,
              'testKeysOnly': True, 'cleanup': 'unconfirmed'}
    node = peer = None
    began = time.monotonic()
    with owned_cancellation() as cancellation:
        node_root, client_root, tls = (work / name for name in ['node', 'client', 'tls'])
        for directory in (node_root, client_root, tls): directory.mkdir(mode=0o700)
        client = Client(args.bin / 'latent', client_root, cancellation, time.monotonic() + 480)
        try:
            certificates(tls, dns_names=('status.backend.test',))
            peer = Peer(tls)
            secret_root = node_root / 'credentials'; secret_root.mkdir(mode=0o700)
            secret = secret_root / 'upstream'; secret.write_text(peer.secret, encoding='ascii'); secret.chmod(0o600)
            config, host = configure(node_root, work, args.bin / 'latent-aot-compiler', tls, secret)
            node = connect(client, args.bin / 'latentd', node_root, config, 'examples', 1)
            # The installed source/credential identity comes from actual startup.
            startup = node.startup_record
            api = client.call('release', 'publish-package', work / 'api/package',
                '--evidence', work / 'api-evidence/index.json', '--operation-id', 'api-publish', '--expected-generation', 0)
            publication = api['data']['release']['publication']['id']
            site = client.call('web', 'publish', work / 'site/package', '--evidence', work / 'site-evidence/index.json',
                              '--operation-id', 'site-publish', '--expected-generation', 0)
            static = site['data']['operation']['publication']['id']
            require(api['outcomeKnown'] and site['outcomeKnown'] and publication != static, 'static-api-independent-publications')
            document, policy_generation = grants(client, startup, publication)
            deploy(client, work, publication, host)
            for method in ['GET', 'HEAD']:
                trigger(client, host, method, {'kind': 'static-web', 'publication': static}, False)
            status, body, _ = request(host, '/')
            require(status == 200 and b'Service availability' in body, 'static-api-independent-site')
            status, body, _ = request(host)
            if status != 200:
                result['firstApiStatus'] = status
                result['firstApiPeerRequests'] = len(peer.requests)
            require(status == 200 and body == b'{"status":"available"}', 'static-api-https-success')
            require(peer.requests[-1]['credentialMatches'] and peer.requests[-1]['target'] == 'GET /health HTTP/1.1',
                    'static-api-trusted-credential')
            require(request(host, headers={'Cookie': 'session=application-owned-test-marker'})[0] == 200
                    and 'cookie' not in peer.requests[-1]['headerNames'], 'static-api-browser-cookie-forwarded')
            before = len(peer.requests)
            for path, method, expected in [('/api/missing', 'GET', 404), ('/api/status', 'POST', 405),
                ('/api/status?upstream=other-customer', 'GET', 400)]:
                status, body, _ = request(host, path, method, {'Origin': 'http://' + host})
                require(status == expected and b'<html' not in body.lower(), f'static-api-precedence-{method}-{status}-expected-{expected}')
            for headers in [{'X-Customer': 'other'}, {'X-Upstream': 'https://other.invalid/'},
                            {'Authorization': 'Bearer ' + TOKEN}, {'X-Forwarded-Host': 'other.invalid'}]:
                status, body, _ = request(host, headers=headers)
                require(status in (400, 401, 403), 'static-api-spoof-or-platform-credential-accepted')
            require(len(peer.requests) == before, 'static-api-denied-input-dispatched')
            for mode in ['error', 'redirect']:
                peer.mode = mode; before = len(peer.requests)
                status, body, _ = request(host)
                require(status == 502 and body == b'{"error":"upstream-unavailable"}'
                        and len(peer.requests) == before + 1, 'static-api-upstream-error-or-redirect')
            peer.mode = 'stall'; before = len(peer.requests); started = time.monotonic()
            status, body, _ = request(host)
            require(status in (502, 504) and 1 <= time.monotonic() - started < 4 and len(peer.requests) == before + 1,
                    'static-api-original-deadline')
            # A response loss can be uncertain after a request was sent. No replay.
            result['deadlineStatus'] = status
            peer.accepted.clear(); before = len(peer.requests)
            raw = socket.create_connection(('127.0.0.1', int(host.rsplit(':', 1)[1])), timeout=5)
            raw.sendall(f'GET /api/status HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n'.encode())
            require(peer.accepted.wait(3), 'static-api-disconnect-not-dispatched')
            raw.close()
            deadline = time.monotonic() + 4
            while peer.closed_stalls < 2 and time.monotonic() < deadline: time.sleep(0.025)
            require(peer.closed_stalls == 2 and len(peer.requests) == before + 1, 'static-api-disconnect-not-reclaimed')
            peer.mode = 'ok'
            # A current policy denial prevents any outbound transport.
            document['rules'][0]['effect'] = 'deny'
            denied = policy(client, 'policy', 'status-upstream', document, policy_generation)
            before = len(peer.requests)
            require(request(host)[0] in (403, 502) and len(peer.requests) == before, 'static-api-policy-denial')
            document['rules'][0]['effect'] = 'allow'
            policy(client, 'policy', 'status-upstream', document, denied['generation'])
            deploy(client, work, publication, host, outbound=0)
            before = len(peer.requests)
            status, body, _ = request(host)
            require(status == 503 and body == b'{"error":"temporarily-busy"}' and len(peer.requests) == before,
                    'static-api-budget-exhaustion')
            deploy(client, work, publication, host)
            # Browser is a separately bounded process using the real ingress.
            if args.browser_tools:
                from tools.build_process import run_bounded_result
                observed = run_bounded_result(['node', str(ROOT / 'tools/static_api/browser.mjs'),
                    str(args.browser_tools), str(args.chrome), 'http://' + host], cwd=ROOT,
                    env={**client.environment, 'PLAYWRIGHT_BROWSERS_PATH': '/ms-playwright'},
                    timeout_seconds=60, max_output_bytes=65536)
                (work / 'browser.log').write_bytes(observed.stdout + observed.stderr)
                require(observed.returncode == 0, 'static-api-browser-failed')
                result['browser'] = json.loads(observed.stdout)
            else:
                result['browser'] = {'executed': False}
            inventory = client.call('node', 'get', NODE_ID)['data']['inventory']
            require(inventory['quotas']['usage']['activeActivations'] == 0, 'static-api-live-activation-after-tests')
            require(all(row['credentialMatches'] and row['target'] == 'GET /health HTTP/1.1'
                        and not any(name.startswith(('x-', 'cookie', 'forwarded', 'proxy-')) for name in row['headerNames'])
                        for row in peer.requests), 'static-api-upstream-authority-or-header-leak')
            stop(client, node); node = None
            floor = read_json(node_root / 'data/supply-chain/floor.json')['restartNotBefore']
            require(type(floor) is int and floor <= time.time() + 6, 'static-api-restart-clock-bound')
            while time.time() < floor:
                cancellation.check(); time.sleep(0.05)
            node = connect(client, args.bin / 'latentd', node_root, config, 'examples', 2)
            require(request(host, '/')[0] == 200 and request(host)[1] == b'{"status":"available"}',
                    'static-api-independent-publications-after-restart')
            result.update(passed=True, independentPublications=True, securityProfile='external-capsule-v1',
                verifiedTls=True, credentialInjection=True, platformCredentialsNotForwarded=True,
                callerSelectedDestinationsRejected=True, apiPrecedesStaticFallback=True, redirectNotFollowed=True,
                deadlineNoReplay=True, disconnectReclaimed=True, deniedPolicyNoTransport=True, exhaustedBudgetNoTransport=True,
                restartPreservedBothPublications=True, upstreamRequests=len(peer.requests), cliProcesses=client.calls)
            seconds = getattr(args, 'serve_seconds', 0)
            require(type(seconds) is int and 0 <= seconds <= 600, 'static-api-demo-duration-bound')
            if seconds:
                unit = 'second' if seconds == 1 else 'seconds'
                print(f'Open http://{host}/ and click Check status. This disposable example stops in {seconds} {unit}; Ctrl+C stops it sooner.', flush=True)
                until = time.monotonic() + seconds
                try:
                    while time.monotonic() < until:
                        cancellation.check(); time.sleep(0.1)
                except KeyboardInterrupt:
                    pass
        except BaseException as error:
            reason = str(error)
            result['failure'] = reason if re.fullmatch(r'[a-z0-9-]{1,256}', reason) else type(error).__name__
            result['failedCall'] = client.failed_call
            raise
        finally:
            node_closed = peer_closed = False
            try:
                client.node = None
                if node is not None: node.close()
                node_closed = True
            finally:
                try:
                    if peer is not None: peer.close()
                    peer_closed = True
                finally:
                    if node_closed and peer_closed:
                        result['cleanup'] = 'owned-node-and-peer-reaped'
                    else:
                        result['passed'] = False
                    result['seconds'] = round(time.monotonic() - began, 3)
                    write_json(work / 'composition-receipt.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['work', 'bin']: parser.add_argument('--' + name, type=Path, required=True)
    for name in ['browser-tools', 'chrome']: parser.add_argument('--' + name, type=Path)
    print(json.dumps(run(parser.parse_args())))
