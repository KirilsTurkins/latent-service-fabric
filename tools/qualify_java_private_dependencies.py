#!/usr/bin/env python3
"""Actual authenticated Maven closure, followed by the ordinary offline node gate."""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import http.server
import io
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import sys
import threading
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as inputs
from tools.application_dependency_store import DependencyError, Store
from tools.build_observation import build_environment
from tools.build_snapshot import canonical, digest
from tools.java_capsule import main as java_cli
from tools.java_dependency_authoring import edit, review, status
from tools.java_dependency_resolution import DECLARATIONS, resolve
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_dependencies import fixture, main as ordinary_gate
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, inventory, snapshot

PREFIX = 'LSF_REGISTRY_PRIVATE_FIXTURE'
GROUP = 'outside.private.owner'
VERSION = '2026.10.15'


@contextmanager
def credentials(username=None, password=None):
    selected = {PREFIX + '_USERNAME': username, PREFIX + '_PASSWORD': password}
    previous = {name: os.environ.get(name) for name in selected}
    try:
        for name, value in selected.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class Peer(http.server.ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 8


def acquire(root: Path, native_directory: Path, native_tuple: Path, gradle: str) -> dict:
    fresh(root)
    logs = fresh(root / 'private-acquisition')
    environment = build_environment(logs)
    if 'JAVA_HOME' in os.environ:
        environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    commands = Commands(ROOT, logs, environment, deadline_seconds=1800, command_seconds=60)
    original = fixture(root, commands, gradle)
    (root / 'capture.json').rename(root / 'local-capture.json')
    app = root / 'application'
    accepted = {name: (app / name).read_bytes() for name in (inputs.MANIFEST, inputs.LOCK)}
    sdk = (app / 'sdk-lock.json').read_bytes()
    local = inputs.verify_inputs(app, 'java')
    require(local is not None, 'private-Maven-local-preimage-required')
    store = Store(app / 'dependency-inputs/objects', create=False)
    rows = {row['id']: row for row in local.lock['artifacts']}
    jars = {}
    for name in ('primary', 'child'):
        row = rows['outside-owner-' + name + '/2026.10.15']
        jars[name] = store.get(row['original']['digest'], row['original']['size'])
    tls_tool = native_directory / 'capsule_authoring'
    native = ordinary_tuple(native_tuple, {'capsule_authoring': tls_tool})
    commands.run('private-synthetic-tls', tls_tool, 'fixture-tls', root / 'private-peer')
    ca = ssl.DER_cert_to_PEM_cert((root / 'private-peer/ca.der').read_bytes()).encode()
    key = (root / 'private-peer/key.pem').read_bytes()
    (app / 'registry').mkdir()
    certificate = app / 'registry/public-ca.pem'
    certificate.write_bytes(ca)
    assets = {}
    for name, payload in jars.items():
        coordinate = GROUP.replace('.', '/') + '/' + name + '-proof/' + VERSION + '/' + name + '-proof-' + VERSION
        transitive = (f'<dependencies><dependency><groupId>{GROUP}</groupId><artifactId>child-proof</artifactId>'
                      f'<version>{VERSION}</version></dependency></dependencies>' if name == 'primary' else '')
        assets['/maven/' + coordinate + '.pom'] = (
            '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>'
            f'<groupId>{GROUP}</groupId><artifactId>{name}-proof</artifactId><version>{VERSION}</version>'
            '<packaging>jar</packaging>' + transitive + '</project>').encode()
        assets['/maven/' + coordinate + '.jar'] = payload
    username, password = 'fixture-' + secrets.token_hex(16), 'fixture-' + secrets.token_hex(32)
    wrong = 'incorrect-' + secrets.token_hex(16)
    authorization = 'Basic ' + base64.b64encode((username + ':' + password).encode()).decode()
    secrets_to_check = (key, username.encode(), password.encode(), wrong.encode(), authorization.encode())
    requests = []
    lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def log_message(self, *_args):
            pass

        def do_HEAD(self):
            self.respond(head=True)

        def do_GET(self):
            self.respond(head=False)

        def respond(self, *, head):
            authorized = secrets.compare_digest(self.headers.get('Authorization', ''), authorization)
            status_code, body = (200, assets[self.path]) if authorized and self.path in assets else (404, b'not-found')
            if not authorized:
                status_code, body = 401, b'authentication-required'
            with lock:
                require(len(requests) < 128, 'private-Maven-peer-request-limit')
                requests.append({'method': self.command, 'authorized': authorized,
                                 'knownAsset': self.path in assets, 'status': status_code})
            self.send_response(status_code)
            if not authorized:
                self.send_header('WWW-Authenticate', 'Basic realm="captured-private-feed"')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            if not head:
                self.wfile.write(body)

    peer = Peer(('127.0.0.1', 0), Handler)
    port = peer.server_address[1]
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(root / 'private-peer/server.pem', root / 'private-peer/key.pem')
    peer.socket = context.wrap_socket(peer.socket, server_side=True)
    peer.socket.settimeout(3)
    owner = threading.Thread(target=peer.serve_forever, kwargs={'poll_interval': .05})
    owner.start()
    controls = []
    try:
        edit(app, 'remove', identity='outside-owner-primary/2026.10.15')
        edit(app, 'remove', identity='outside-owner-child/2026.10.15')
        coordinate = GROUP + ':primary-proof:' + VERSION
        edit(app, 'add', coordinate=coordinate,
             repository=('private-fixture', 'https://localhost:' + str(port) + '/maven/'),
             repository_ca='registry/public-ca.pem')
        declaration = (app / DECLARATIONS).read_bytes()
        for name, selected_user, selected_password, trust in (
            ('missing-credentials', None, None, True),
            ('wrong-credentials', username, wrong, True),
            ('incomplete-pair', username, None, True),
            ('untrusted-CA', username, password, False),
        ):
            require(commands.deadline - time.monotonic() >= 300, 'private-Maven-total-resolution-deadline')
            value = json.loads(declaration)
            value['dependencies'] = [row for row in value['dependencies'] if row['group'] == GROUP]
            value['repositories'] = [row for row in value['repositories'] if row['id'] == 'private-fixture']
            if not trust:
                next(row for row in value['repositories'] if row['id'] == 'private-fixture').pop('tlsTrust')
            (app / DECLARATIONS).write_bytes(canonical(value) + b'\n')
            candidate = root / (name + '-candidate.json')
            out, err = io.StringIO(), io.StringIO()
            request_start = len(requests)
            try:
                with credentials(selected_user, selected_password), redirect_stdout(out), redirect_stderr(err):
                    code = java_cli(['resolve', str(app), '--candidate', str(candidate), '--gradle', gradle])
            finally:
                (app / DECLARATIONS).write_bytes(declaration)
            require(code == 1 and not candidate.exists(), 'private-Maven-authentication-control-accepted')
            failed = read_json(candidate.with_name(candidate.name + '.failed.json'))
            expected = ('java-registry-credential-pair-invalid' if name == 'incomplete-pair'
                        else 'java-maven-resolution-failed-private-diagnostics-discarded')
            require(failed['reason'] == expected and failed['automaticReplay'] is False,
                    'private-Maven-authentication-control-wrong-outcome')
            require(not any(row['authorized'] for row in requests[request_start:]),
                    'private-Maven-negative-request-authorized')
            if name in {'incomplete-pair', 'untrusted-CA'}:
                require(len(requests) == request_start, 'private-Maven-pre-request-denial-contacted-peer')
            else:
                require(len(requests) > request_start, 'private-Maven-authentication-denial-not-observed')
            require(all(value not in (out.getvalue() + err.getvalue()).encode() for value in secrets_to_check),
                    'private-Maven-credential-in-public-diagnostic')
            require(all((app / name).read_bytes() == raw for name, raw in accepted.items()),
                    'private-Maven-failure-changed-accepted-inputs')
            controls.append({'case': name, 'status': 'known-failure', 'reason': expected})
        candidate = root / 'private-candidate.json'
        require(commands.deadline - time.monotonic() >= 300, 'private-Maven-total-resolution-deadline')
        with credentials(username, password):
            captured = resolve(app, candidate, gradle=gradle)
        by_id = {row['id']: row for row in captured['artifacts']}
        child = GROUP + ':child-proof:' + VERSION
        require(coordinate in by_id and child in by_id[coordinate]['dependencies'], 'private-Maven-transitive-edge-missing')
        for name in jars:
            selected = by_id[GROUP + ':' + name + '-proof:' + VERSION]
            require(selected['original']['digest'] == digest(jars[name]), 'private-Maven-original-JAR-drift')
        review(app, candidate, digest(candidate.read_bytes()))
    finally:
        peer.shutdown()
        peer.server_close()
        owner.join(timeout=5)
        require(not owner.is_alive(), 'private-Maven-peer-not-reaped')
        write_json(root / 'private-peer-observations.json', {'requests': requests, 'controls': controls,
                   'peerPhysicallyReaped': True, 'privateHeaderValuesRetained': False})
    require(all(value not in raw for raw in snapshot(app).values() for value in secrets_to_check),
            'private-Maven-credential-or-private-key-captured')
    require((app / 'sdk-lock.json').read_bytes() == sdk, 'private-Maven-sdk-lock-mutated')
    require(ordinary_tuple(native_tuple, {'capsule_authoring': tls_tool}) == native, 'private-Maven-tls-tool-mutated')
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.5):
            raise RuntimeError('private-Maven-peer-listener-retained')
    except OSError:
        pass
    captured_identity = status(app)['capturedInputIdentity']
    for name in ('certificate-drift', 'private-JAR-drift'):
        selected = certificate if name == 'certificate-drift' else store.path(by_id[coordinate]['original']['digest'])
        preimage = selected.read_bytes()
        selected.write_bytes(b'changed captured input')
        try:
            status(app)
        except DependencyError as error:
            expected = 'dependency-native-lock-drift' if name == 'certificate-drift' else 'dependency-artifact-integrity'
            require(str(error) == expected, 'private-Maven-drift-control-wrong-failure')
            controls.append({'case': name, 'status': 'known-failure', 'reason': expected})
        else:
            raise RuntimeError('private-Maven-changed-input-accepted')
        finally:
            selected.write_bytes(preimage)
        require(status(app)['capturedInputIdentity'] == captured_identity, 'private-Maven-restored-identity-mismatch')
    require(time.monotonic() < commands.deadline, 'private-Maven-total-resolution-deadline')
    result = {**original, 'scope': 'real authenticated private-Maven direct/transitive JARs and resource capture',
        'applicationIdentity': digest(inventory(snapshot(app))), 'capturedInputIdentity': captured_identity,
        'privateMaven': {'nativeTuple': native, 'coordinate': coordinate, 'transitive': child, 'controls': controls,
            'requests': len(requests), 'authorizedRequests': sum(row['authorized'] for row in requests),
            'peerReapedBeforeOfflineBuild': True, 'credentialAndPrivateKeyCapture': False,
            'qualifier': file_identity(Path(__file__))}}
    write_json(root / 'capture.json', result)
    write_json(root / 'private-acquisition.json', result['privateMaven'])
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    boundary = parser.add_mutually_exclusive_group(required=True)
    boundary.add_argument('--resolve-only', action='store_true')
    boundary.add_argument('--offline', action='store_true')
    for name in ('output', 'native-directory', 'native-tuple'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--wasi-sdk', type=Path)
    parser.add_argument('--read-only-cache', type=Path)
    parser.add_argument('--gradle', default='gradle')
    args = parser.parse_args(argv)
    root = args.output.absolute()
    require(root != ROOT and ROOT not in root.parents, 'private-Maven-output-must-stay-outside-source')
    if args.resolve_only:
        try:
            acquire(root, args.native_directory, args.native_tuple, args.gradle)
            print(json.dumps({'status': 'captured', 'runtimeQualification': False}))
            return 0
        except BaseException as error:
            failed = root / 'PRIVATE-FAILED.json'
            if root.is_dir() and not failed.exists():
                write_json(failed, {'status': 'failed', 'stage': 'private-acquisition',
                    'reason': str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__,
                    'automaticReplay': False})
            raise
    require(args.wasi_sdk is not None and args.read_only_cache is not None, 'private-Maven-offline-compiler-required')
    captured = read_json(root / 'private-acquisition.json')
    result = ordinary_gate(['--offline', '--output', str(root), '--native-directory', str(args.native_directory),
        '--native-tuple', str(args.native_tuple), '--wasi-sdk', str(args.wasi_sdk), '--read-only-cache',
        str(args.read_only_cache), '--gradle', args.gradle])
    require(result == 0, 'private-Maven-offline-node-control-failed')
    write_json(root / 'private-qualification.json', {'status': 'passed',
        'scope': 'authenticated private-Maven closure, offline actual component and ordinary signed-node execution',
        'capture': captured, 'ordinaryExecution': file_identity(root / 'qualification.json'),
        'remainingAcceptance': ['installed-update-remove-watch', 'trap-memory-fuel-cancellation-recovery'],
        'issue682Complete': False})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
