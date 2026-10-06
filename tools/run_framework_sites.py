#!/usr/bin/env python3
"""Actual signed publications, native host policy, immutable responses and browser behavior."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Client, Process, read_json, require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_web_scenario import http_response, publish
from tools.run_security_profile_workflow import replace_config
from tools.run_static_site_workflow import configure, apply, idle
from tools.test_run import redact

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    metadata = read_json(args.fixture / 'fixture.json')
    require(metadata.get('frameworkReferences') is True, 'actual-framework-fixtures-required')
    records = {row['name']: row for row in metadata['fixtures']}
    require(set(records) == {'angular-root', 'angular-mounted', 'docs-root', 'docs-mounted'}, 'framework-fixture-set')
    with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-framework-node-') as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        node_root, client_root = directory / 'node', directory / 'client'
        for path in (node_root, client_root): path.mkdir(mode=0o700)
        client = Client(args.cli, client_root, cancellation, time.monotonic() + 480)
        config, hosts = configure(node_root, args.fixture)
        value = read_json(config)
        value['httpIngress']['allowStaticStyleHashes'] = True
        replace_config(config, value)
        node = None
        try:
            node = connect(client, args.node, node_root, config, 'tests', 1)
            publications = {name: publish(client, args.fixture, name)['publication']['id'] for name in records}
            responses = []
            for name, host, mount in [('angular-root', hosts['csr'], '/'), ('angular-mounted', hosts['csr'], '/app'),
                                      ('docs-root', hosts['generator'], '/'), ('docs-mounted', hosts['generator'], '/docs')]:
                for method in ('GET', 'HEAD'):
                    apply(client, name + '-' + method.lower(), publications[name], host, mount, method)
                path = mount.rstrip('/') + '/'
                body, headers = http_response(client, node, host, path)
                expected = next(row for row in records[name]['assets'] if row['path'] == '/index.html')
                require('sha256:' + hashlib.sha256(body).hexdigest() == expected['digest'], 'immutable-framework-html')
                head, head_headers = http_response(client, node, host, path, method='HEAD')
                conditional, conditional_headers = http_response(client, node, host, path,
                    headers={'If-None-Match': headers['etag']}, expected=304)
                require(not head and not conditional and all(fields['content-security-policy'] == headers['content-security-policy']
                        and fields['etag'] == headers['etag'] for fields in (head_headers, conditional_headers)), 'framework-csp-revalidation')
                responses.append({'name': name, 'htmlDigest': expected['digest'], 'immutableBytes': True, 'headAnd304': True})
                if name.startswith('docs-'):
                    missing_path = mount.rstrip('/') + '/unknown/nested/page'
                    missing, missing_fields = http_response(client, node, host, missing_path,
                        headers={'Accept': 'text/html'}, expected=404)
                    error_asset = next(row for row in records[name]['assets'] if row['path'] == '/404.html')
                    require('sha256:' + hashlib.sha256(missing).hexdigest() == error_asset['digest']
                        and missing_fields['cache-control'] == 'private, no-store', 'immutable-framework-404')
                    head, head_fields = http_response(client, node, host, missing_path, method='HEAD',
                        headers={'Accept': 'text/html', 'If-None-Match': missing_fields['etag']}, expected=404)
                    require(not head and head_fields['content-length'] == str(len(missing))
                        and head_fields['etag'] == missing_fields['etag'], 'framework-error-head-404')
            browser_receipt = client_root / 'browser.json'
            process = Process([shutil.which('node'), str(ROOT / 'examples/framework-compatibility/browser.mjs'), str(args.chrome),
                'http://' + hosts['csr'], 'http://' + hosts['generator'], str(browser_receipt)], ROOT,
                client.environment, cancellation, maximum=262144)
            try:
                result = process.complete(min(client.deadline, time.monotonic() + 170))
                require(result.returncode == 0, 'framework-browser-failed: ' +
                        redact(result.stderr.decode('utf-8', errors='replace'))[-2000:])
            finally: process.close()
            browser = read_json(browser_receipt)
            require(browser.get('passed') is True and len(browser['pages']) == 4, 'framework-browser-evidence')
            revoked = client.call('web', 'revoke', '--publication', publications['docs-root'],
                '--operation-id', 'revoke-framework-error-document', '--expected-generation', '1')
            require(revoked['outcomeKnown'], 'framework-error-revocation-uncertain')
            for method in ('GET', 'HEAD'):
                denied, _ = http_response(client, node, hosts['generator'], '/unknown/nested/page', method=method,
                    headers={'Accept': 'text/html'}, expected=403)
                require(not denied, 'revoked-framework-error-body')
            denied_receipt = client_root / 'revoked-error-browser.json'
            process = Process([shutil.which('node'), str(ROOT / 'tools/static-sites/browser.mjs'),
                str(ROOT / 'examples/renderer-profile'), str(args.chrome), 'http://' + hosts['csr'],
                'http://' + hosts['generator'], 'A', str(denied_receipt), 'error-denied'], ROOT,
                client.environment, cancellation, maximum=262144)
            try:
                result = process.complete(min(client.deadline, time.monotonic() + 75))
                require(result.returncode == 0, 'framework-revoked-error-browser-failed')
            finally: process.close()
            revoked_browser = read_json(denied_receipt)
            require(revoked_browser['errorDocument']['status'] == 403, 'framework-revoked-error-browser-evidence')
            dormant = idle(client)
            stop(client, node)
            stopped_record(node)
            node = None
            value['httpIngress']['allowStaticStyleHashes'] = False
            replace_config(config, value)
            floor = read_json(node_root / 'data/supply-chain/floor.json')['restartNotBefore']
            require(isinstance(floor, int) and floor > 0 and floor - int(time.time()) <= 6, 'framework-clock-floor-bound')
            # Honor the actual durable clock lease, bounded by the configured 5s.
            until = time.monotonic() + 6
            while int(time.time()) < floor:
                require(time.monotonic() < until, 'framework-restart-clock-floor')
                time.sleep(0.025)
            node = connect(client, args.node, node_root, config, 'tests', 2)
            http_response(client, node, hosts['csr'], '/', expected=403)
            http_response(client, node, hosts['csr'], '/app/', expected=403)
            http_response(client, node, hosts['generator'], '/', expected=403)
            http_response(client, node, hosts['generator'], '/docs/')
            stop(client, node)
            shutdown = stopped_record(node)
            node = None
            return {'schemaVersion': 'latent.framework.workflow.v1', 'passed': True, 'browser': browser,
                    'revokedErrorDocumentBrowser': revoked_browser,
                    'responses': responses, 'hostOptInRequiredAfterRestart': True, 'dormant': dormant,
                    'shutdown': shutdown, 'publications': publications}
        finally:
            client.node = None
            if node is not None: node.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cli', 'node', 'chrome', 'fixture'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    for name in ('cli', 'node', 'chrome', 'fixture'):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    print(json.dumps(run(args), separators=(',', ':')))
