#!/usr/bin/env python3
"""Actual private Cargo HTTPS capture, offline builds and signed-node execution.

Consumes only exact products from the preceding maintained Rust qualification.
The private registry, key and credentials are synthetic fixture inputs, never
release trust, guest grants or captured application credentials.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import gzip
import http.server
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import sys
import tarfile
import threading
import time
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as dependencies, rust_capsule
from tools.application_dependency_store import DependencyError, Store
from tools.build_observation import build_environment, resolve_tools
from tools.build_process import run_bounded_result
from tools.build_snapshot import canonical, digest
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import inputs
from tools.run_rust_capsule_workflow import run as node_workflow
from tools.rust_capsule_build import Commands, build
from tools.rust_capsule_project import ROOT, create, fresh, inventory, snapshot
from tools.rust_dependency_fixture import direct_libraries

MAIN, CHILD, VERSION = 'outside-private-main', 'outside-private-child', '0.1.0'
TOKEN_SLOT = 'CARGO_REGISTRIES_TEAM_TOKEN'
REPOSITORY = 'https://github.com/KirilsTurkins/latent-service-fabric'


@contextmanager
def credential(value):
    previous = os.environ.get(TOKEN_SLOT)
    try:
        if value is None:
            os.environ.pop(TOKEN_SLOT, None)
        else:
            os.environ[TOKEN_SLOT] = value
        yield
    finally:
        if previous is None:
            os.environ.pop(TOKEN_SLOT, None)
        else:
            os.environ[TOKEN_SLOT] = previous


def author(*arguments):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = rust_capsule.main([str(value) for value in arguments])
    return code, out.getvalue(), err.getvalue()


def archive(name: str, source: str, resource: bytes | None = None, *, registry_index: str | None = None) -> bytes:
    manifest = '[package]\nname="' + name + '"\nversion="' + VERSION + '"\nedition="2021"\nlicense="MIT"\n'
    if name == MAIN:
        # Published Cargo manifests name an alternate transitive registry by
        # index, rather than a developer-local registry alias. The sparse
        # index's same-registry dependency and the vendored manifest must agree.
        manifest += '[dependencies.' + CHILD + ']\nversion="=' + VERSION + '"\n'
        if registry_index is not None:
            manifest += 'registry-index=' + json.dumps(registry_index) + '\n'
    files = {'Cargo.toml': manifest.encode(), 'src/lib.rs': source.encode()}
    if resource is not None:
        files['src/greeting.txt'] = resource
    target = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=target, mtime=0) as compressed:
        with tarfile.open(mode='w', fileobj=compressed) as package:
            for path, raw in files.items():
                info = tarfile.TarInfo(name + '-' + VERSION + '/' + path)
                info.size, info.mode, info.mtime = len(raw), 0o644, 0
                package.addfile(info, io.BytesIO(raw))
    return target.getvalue()


class Peer(http.server.ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 8


def capture(root: Path, commands: Commands, cargo: Path) -> tuple[Path, dict]:
    app = create(root / 'application', 'greeting')
    sdk = (app / 'sdk-lock.json').read_bytes()
    peer_files = fresh(root / 'private-peer')
    key, certificate = peer_files / 'key.pem', peer_files / 'certificate.pem'
    commands.run('synthetic-registry-certificate', 'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', key, '-out', certificate, '-days', '1', '-subj', '/CN=LSF private Cargo fixture',
        '-addext', 'basicConstraints=critical,CA:TRUE',
        '-addext', 'keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign',
        '-addext', 'subjectAltName=IP:127.0.0.1')
    key.chmod(0o600)
    private_key = key.read_bytes()
    certificate_bytes = certificate.read_bytes()
    ca = app / 'registry-trust/public-roots.pem'
    ca.parent.mkdir()
    ca.write_bytes(Path('/etc/ssl/certs/ca-certificates.crt').read_bytes() + b'\n' + certificate_bytes)
    token, wrong = 'Bearer fixture-' + secrets.token_hex(24), 'Bearer incorrect-' + secrets.token_hex(24)
    confidential = (token.encode(), wrong.encode(), private_key)
    payloads, original = {}, {}
    requests, assets, controls = [], {}, []
    lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def log_message(self, *_arguments):
            pass

        def do_GET(self):
            authorized = secrets.compare_digest(self.headers.get('Authorization', ''), token)
            public = self.path == '/index/config.json'
            status, body = (200, assets[self.path]) if (authorized or public) and self.path in assets else (404, b'not-found')
            if not authorized and not public:
                status, body = 401, b'authentication-required'
            with lock:
                require(len(requests) < 128, 'private-Cargo-peer-request-bound')
                requests.append({'path': self.path, 'authorized': authorized, 'publicMetadata': public,
                                 'knownAsset': self.path in assets, 'status': status})
            self.send_response(status)
            if status == 401:
                self.send_header('WWW-Authenticate', 'Cargo login_url="https://example.invalid/fixture-only"')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)

    peer = Peer(('127.0.0.1', 0), Handler)
    port = peer.server_address[1]
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    peer.socket = context.wrap_socket(peer.socket, server_side=True)
    peer.socket.settimeout(3)
    owner = threading.Thread(target=peer.serve_forever, kwargs={'poll_interval': .05}, name='private-Cargo-registry')
    owner_started = False
    index = 'sparse+https://127.0.0.1:' + str(port) + '/index/'
    payloads.update({
        MAIN: archive(MAIN, 'pub fn prefix() -> &\'static str { outside_private_child::prefix() }\n', registry_index=index),
        CHILD: archive(CHILD, 'pub fn prefix() -> &\'static str { include_str!("greeting.txt") }\n', b'Hello, '),
    })
    original.update({name: {'digest': digest(raw), 'size': len(raw)} for name, raw in payloads.items()})
    assets['/index/config.json'] = canonical({'dl': 'https://127.0.0.1:' + str(port) + '/api/v1/crates', 'auth-required': True})
    for name, raw in payloads.items():
        child = [] if name == CHILD else [{'name': CHILD, 'req': '=' + VERSION, 'features': [],
            'optional': False, 'default_features': True, 'target': None, 'kind': 'normal', 'registry': None}]
        assets['/index/' + name[:2] + '/' + name[2:4] + '/' + name] = canonical({
            'name': name, 'vers': VERSION, 'deps': child, 'cksum': digest(raw)[7:],
            'features': {}, 'yanked': False, 'links': None}) + b'\n'
        assets['/api/v1/crates/' + name + '/' + VERSION + '/download'] = raw
    policy = root / 'private-registry-policy.json'
    declaration = {'registries': {'team': {'index': index}}, 'tlsTrust': {'caFile': 'registry-trust/public-roots.pem'}}
    policy.write_bytes(canonical(declaration))
    with (app / 'Cargo.toml').open('a', encoding='utf-8') as target:
        target.write('\n[dependencies]\n' + MAIN + '={version="=' + VERSION + '",registry="team"}\n')
    source = app / 'src/lib.rs'
    before = source.read_bytes()
    after = before.replace(b'Ok(format!("Hello, {name}!"))', b'Ok(format!("{}{}!", outside_private_main::prefix(), name))')
    require(after != before, 'private-Cargo-ordinary-source-hook-drift')
    source.write_bytes(after)
    try:
        owner.start()
        owner_started = True
        # This is the explicitly authorized native lock update, before the
        # maintained locked capture. It never executes application build hooks.
        lock_work = fresh(root / 'native-lock-preparation')
        environment = build_environment(lock_work)
        home = fresh(lock_work / 'cargo-home')
        pins = tomllib.loads((app / 'vendor/lsf/rust-toolchain.toml').read_text())
        environment.update(CARGO_HOME=str(home), HOME=str(lock_work / 'home'),
            USERPROFILE=str(lock_work / 'home'), RUSTUP_TOOLCHAIN=pins['toolchain']['channel'], RUSTUP_AUTO_INSTALL='0',
            RUSTC=str(cargo.parent / 'rustc'), GIT_CONFIG_NOSYSTEM='1',
            GIT_CONFIG_GLOBAL=str(lock_work / 'git-empty.config'), GIT_TERMINAL_PROMPT='0')
        (lock_work / 'git-empty.config').write_bytes(b'')
        (home / 'config.toml').write_text('[http]\nssl-verify=true\ncainfo=' + json.dumps(str(ca)) +
            '\n[registries.team]\nindex=' + json.dumps(index) + '\ncredential-provider="cargo:token"\n', encoding='utf-8')
        environment[TOKEN_SLOT] = token
        prepared = run_bounded_result([str(cargo), 'metadata', '--manifest-path', str(app / 'Cargo.toml'), '--format-version', '1'],
                                      lock_work, environment, 600, 16 * 1024 * 1024)
        redacted = prepared.stderr
        for secret in confidential:
            redacted = redacted.replace(secret, b'[redacted-owned-fixture-secret]')
        (root / 'logs/native-lock-preparation.stderr.txt').write_bytes(redacted[:65536])
        write_json(root / 'native-lock-preparation.json', {'exitCode': prepared.returncode,
            'stderrBytes': len(prepared.stderr), 'retainedStderrBytes': min(len(redacted), 65536),
            'diagnosticScope': 'owned synthetic fixture only; production resolver still discards private failures'})
        require(prepared.returncode == 0, 'private-Cargo-native-lock-preparation-failed')
        candidate = root / 'private-candidate.json'
        with credential(token):
            code, out, err = author('resolve', app, '--candidate', candidate, '--cargo', cargo, '--registry-config', policy)
        require(code == 0 and not err, 'private-Cargo-normal-resolution-failed')
        require(all(secret not in out.encode() for secret in confidential), 'private-Cargo-public-receipt-secret')
        captured = read_json(candidate, dependencies.MAX_LOCK)
        graph = read_json(app / 'cargo-resolved.lock.json', dependencies.MAX_LOCK)
        libraries = direct_libraries(graph, captured['artifacts'], {(MAIN, VERSION): 'prefix'})
        selected = {row['metadata'].get('package'): row for row in captured['artifacts']}
        require(CHILD in selected and selected[CHILD]['id'] in selected[MAIN]['dependencies'],
                'private-Cargo-native-transitive-edge-missing')
        native_lock = tomllib.loads((app / 'Cargo.lock').read_text())
        store = Store(app / 'dependency-inputs/objects', create=False)
        for name in (MAIN, CHILD):
            native = next(row for row in native_lock['package'] if row['name'] == name and row['version'] == VERSION)
            original_files = json.loads(store.get(**selected[name]['original']))
            checksums = next(row for row in original_files if row['path'] == '.cargo-checksum.json')
            package_checksum = json.loads(store.get(checksums['digest'], checksums['size']))['package']
            require(native['checksum'] == package_checksum == original[name]['digest'][7:],
                    'private-Cargo-original-archive-checksum-drift')
        code, _out, err = author('review-lock', app, '--candidate', candidate, '--expect', digest(candidate.read_bytes()))
        require(code == 0 and not err, 'private-Cargo-normal-lock-review-failed')
        accepted = {name: (app / name).read_bytes() for name in (dependencies.MANIFEST, dependencies.LOCK, 'cargo-resolved.lock.json')}
        for name, selected_token, trusted in (('missing-token', None, True), ('wrong-token', wrong, True),
                                              ('untrusted-certificate', token, False)):
            selected_policy = root / (name + '-policy.json')
            selected_policy.write_bytes(canonical(declaration if trusted else {'registries': declaration['registries']}))
            failed = root / (name + '-candidate.json')
            start = len(requests)
            with credential(selected_token):
                code, out, err = author('resolve', app, '--candidate', failed, '--cargo', cargo, '--registry-config', selected_policy)
            require(code == 1 and not failed.exists(), 'private-Cargo-native-negative-accepted')
            failure = read_json(failed.with_name(failed.name + '.failed.json'))
            require(failure['automaticReplay'] is False and failure['compilerExecution'] is False,
                    'private-Cargo-negative-authority-changed')
            require(not any(row['authorized'] and not row['publicMetadata'] for row in requests[start:]),
                    'private-Cargo-negative-authorized-package-request')
            if not trusted:
                require(len(requests) == start, 'private-Cargo-untrusted-certificate-reached-HTTP')
            require(all(secret not in (out + err).encode() for secret in confidential), 'private-Cargo-negative-secret')
            require(all((app / path).read_bytes() == raw for path, raw in accepted.items()), 'private-Cargo-negative-mutated-lock')
            controls.append({'case': name, 'status': 'known-native-resolution-failure', 'failure': failure,
                             'peerRequests': requests[start:]})
    finally:
        if owner_started:
            peer.shutdown()
        peer.server_close()
        if owner_started:
            owner.join(timeout=5)
        require(not owner.is_alive(), 'private-Cargo-peer-not-physically-reaped')
        write_json(root / 'registry-observations.json', {'requests': requests, 'controls': controls,
            'peerPhysicallyReaped': True, 'headerValuesRetained': False})
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.5):
            raise RuntimeError('private-Cargo-registry-listener-retained')
    except OSError:
        pass
    require(all(secret not in raw for raw in snapshot(app).values() for secret in confidential),
            'private-Cargo-credential-or-private-key-captured')
    require((app / 'sdk-lock.json').read_bytes() == sdk, 'private-Cargo-sdk-lock-drift')
    assets.clear()
    payloads.clear()
    shutil.rmtree(peer_files)
    shutil.rmtree(lock_work)
    result = {'status': 'captured', 'privateArchives': original, 'applicationLibraries': libraries,
              'sdkLockDigest': digest(sdk), 'resourceDigest': digest(b'Hello, '), 'negativeControls': controls,
              'peerPhysicallyReaped': True, 'listenerRefused': True, 'originalArchivesUnavailable': True,
              'catalogueRegistration': False, 'libraryStartupOnBuildHost': False}
    write_json(root / 'capture.json', result)
    return app, result


def integrity_controls(app: Path) -> list[dict]:
    verified = dependencies.verify_inputs(app, 'rust')
    child = next(row for row in verified.lock['artifacts'] if row['metadata'].get('package') == CHILD)
    resource = next(row for row in child['files'] if row['path'] == 'src/greeting.txt')
    store = Store(app / 'dependency-inputs/objects', create=False)
    selected = store.path(resource['digest'])
    resource_bytes = selected.read_bytes()
    ca = app / 'registry-trust/public-roots.pem'
    ca_bytes = ca.read_bytes()
    accepted = (app / dependencies.LOCK).read_bytes()
    result = []
    for name, path, replacement, original, expected in (
        ('missing-transitive-resource', selected, None, resource_bytes, 'dependency-artifact-missing-resolve-explicitly'),
        ('tampered-transitive-resource', selected, b'changed same-coordinate bytes', resource_bytes, 'dependency-artifact-integrity'),
        ('certificate-change', ca, ca_bytes + b'\n', ca_bytes, 'dependency-native-lock-drift'),
    ):
        if replacement is None:
            path.unlink()
        else:
            path.write_bytes(replacement)
        try:
            try:
                dependencies.verify_inputs(app, 'rust')
            except DependencyError as error:
                require(str(error) == expected, 'private-Cargo-integrity-control-wrong-failure')
                result.append({'case': name, 'status': 'known-before-compiler-failure', 'reason': expected})
            else:
                raise RuntimeError('private-Cargo-mutated-input-accepted')
        finally:
            path.write_bytes(original)
        require((app / dependencies.LOCK).read_bytes() == accepted, 'private-Cargo-integrity-control-mutated-lock')
    dependencies.verify_inputs(app, 'rust')
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--prepared-qualification', required=True, type=Path)
    args = parser.parse_args(argv)
    require(args.output.absolute() != ROOT and ROOT not in args.output.absolute().parents,
            'private-Cargo-fixture-must-be-outside-runtime')
    root = fresh(args.output)
    prepared = args.prepared_qualification
    qualified = read_json(prepared / 'qualification.json')
    before = inputs('rust')
    require(qualified['status'] == 'passed' and 'applicationDependencies' in qualified
            and read_json(prepared / 'source-inputs.json') == before
            and (prepared / 'source-inputs.json').read_bytes() == (prepared / 'source-inputs-after.json').read_bytes()
            and digest((prepared / 'source-inputs.json').read_bytes()) == qualified['sourceIdentityDigest'],
            'private-Cargo-exact-prepared-source-required')
    products = {}
    for name, identity in qualified['binaries'].items():
        binary = prepared / 'native-binaries' / name.replace('/', '-')
        require(file_identity(binary, 512 * 1024 * 1024) == identity, 'private-Cargo-prepared-native-mismatch')
        products[name] = binary
    require(set(products) == {'latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring'},
            'private-Cargo-exact-five-native-products-required')
    own_source = file_identity(Path(__file__))
    commands = Commands(ROOT, root, build_environment(root), deadline_seconds=1800, command_seconds=600)
    stage = 'private-registry-capture'
    try:
        paths, materials = resolve_tools(tomllib.loads((ROOT / 'tools/toolchain.toml').read_text()), ROOT, commands.environment)
        cargo = paths['cargo']
        require(next(row for row in materials if row['name'] == 'cargo')
                == next(row for row in qualified['tools'] if row['name'] == 'cargo'),
                'private-Cargo-prepared-compiler-mismatch')
        app, captured = capture(root, commands, cargo)
        stage = 'actual-integrity-controls'
        integrity = integrity_controls(app)
        write_json(root / 'integrity-controls.json', {'status': 'passed', 'cases': integrity})
        stage = 'offline-builds'
        source = inventory(snapshot(app))
        built = []
        for name in ('first', 'offline-rebuild'):
            built.append(build(app, root / name, products['examples/capsule_contracts'], products['examples/package'],
                               REPOSITORY, offline=True))
            require(inventory(snapshot(app)) == source, 'private-Cargo-offline-build-mutated-source')
        stage = 'signing'
        remaining = [prepared / 'builds' / name for name in ('word-count', 'shipping', 'http-status', 'recovery')]
        require(all(read_json(path / 'BUILD-COMPLETE.json') == qualified['builds'][path.name]
                    for path in remaining), 'private-Cargo-prepared-companion-build-changed')
        commands.run('sign-private-fixture', products['examples/capsule_authoring'], 'demo-sign', root / 'signed', built[0], *remaining)
        stage = 'signed-node'
        result = node_workflow(products['latent'], products['latentd'], root / 'signed', root / 'node', language='rust')
        require(result['status'] == 'passed', 'private-Cargo-node-not-qualified')
        require(inputs('rust') == before and file_identity(Path(__file__)) == own_source,
                'private-Cargo-qualification-source-changed')
        require(all(file_identity(binary, 512 * 1024 * 1024) == qualified['binaries'][name]
                    for name, binary in products.items()), 'private-Cargo-native-products-changed')
        require(time.monotonic() < commands.deadline, 'private-Cargo-qualification-deadline')
        write_json(root / 'qualification.json', {'schemaVersion': 'lsf.rust.private-dependencies.v1', 'status': 'passed',
            'scope': 'actual authenticated native Cargo HTTPS closure, offline component builds and signed node',
            'sourceIdentityDigest': qualified['sourceIdentityDigest'], 'qualifier': own_source,
            'capture': captured, 'integrityControls': integrity, 'nativeBinaries': qualified['binaries'],
            'builds': [read_json(p / 'BUILD-COMPLETE.json') for p in built],
            'nodeReceipt': file_identity(root / 'node/workflow.json'), 'commands': commands.records,
            'reproducibility': 'not-claimed', 'releasePublication': 'not-performed'})
        print(json.dumps({'status': 'passed', 'receipt': str(root / 'qualification.json')}), flush=True)
    except BaseException as error:
        write_json(root / 'FAILED.json', {'status': 'failed', 'stage': stage, 'commands': commands.records,
            'reason': str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__})
        raise
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
