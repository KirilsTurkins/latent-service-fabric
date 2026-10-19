"""Owned authenticated HTTPS npm registry with unknown ordinary package coordinates."""
from contextlib import contextmanager
import base64
import gzip
import hashlib
import http.server
import io
import json
import secrets
import socket
import ssl
import tarfile
import threading
from urllib.parse import unquote

from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest, read_file

TOKEN_SLOT = 'LSF_PRIVATE_NPM_REGISTRY_FIXTURE'
VERSIONS = ('1.0.0', '1.1.0')
CONDITION = 'latent-private'
MAX_REQUESTS = 256


def packages(nonce, version, role):
    require(isinstance(nonce, str) and len(nonce) == 24
        and all(c in '0123456789abcdef' for c in nonce)
        and version in VERSIONS and role in {'root', 'leaf'}, 'private-npm-package-selection')
    identity = '@private-' + nonce + '/' + role
    manifest = {'name': identity, 'version': version, 'license': 'Apache-2.0',
        'scripts': {'preinstall': 'node forbidden.cjs', 'install': 'node forbidden.cjs',
                    'postinstall': 'node forbidden.cjs', 'prepare': 'node forbidden.cjs'}}
    files = {'forbidden.cjs': b'throw new Error("private package lifecycle must not run");\n'}
    if role == 'root':
        leaf = '@private-' + nonce + '/leaf'
        manifest.update(type='module', dependencies={leaf: version}, exports={
            'types': './index.d.ts', CONDITION: './selected.mjs', 'default': './default.mjs'})
        files['index.d.ts'] = b'export function describe(value: string): string;\n'
        for name, selected in (('selected', 'enabled'), ('default', 'default')):
            files[name + '.mjs'] = ('import leaf from ' + json.dumps(leaf) + ';\n'
                'import text from ' + json.dumps(leaf + '/text') + ';\n'
                'import bytes from ' + json.dumps(leaf + '/bytes') + ';\n'
                'let calls = 0; const prefix = leaf.prefix();\n'
                'export function describe(value) { if (++calls !== 1 || prefix !== leaf.prefix()) '
                'throw new Error("fresh private state"); '
                'if (prefix !== text + "|00ff4180" || bytes.length !== 4 || bytes[0] !== 0 || '
                'bytes[1] !== 255 || bytes[2] !== 65 || bytes[3] !== 128) throw new Error("private resource"); '
                'return prefix + "|' + selected + '|" + value; }\n').encode()
    else:
        manifest.update(main='index.cjs', exports={'.': './index.cjs', './text': './resource.txt', './bytes': './resource.bin'})
        text = nonce + ':' + version + '|Gr\u00fc\u00dfe'
        files.update({'text.json': json.dumps(text, ensure_ascii=False).encode(),
            'resource.txt': text.encode(), 'resource.bin': bytes((0, 255, 65, 128)),
            'index.cjs': b'const text = require("./text.json");\nexports.prefix = () => text + "|00ff4180";\n'})
    files['package.json'] = json.dumps(manifest, sort_keys=True).encode()
    return identity, files


def archive(files):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as target:
            for name, raw in sorted(files.items()):
                info = tarfile.TarInfo('package/' + name)
                info.size, info.mode, info.mtime = len(raw), 0o644, 0
                target.addfile(info, io.BytesIO(raw))
    result = output.getvalue()
    require(0 < len(result) <= 4 * 1024 * 1024, 'private-npm-archive-bound')
    return result


def assets(nonce, base_url):
    result = {}
    for role in ('root', 'leaf'):
        versions = {}
        for version in VERSIONS:
            identity, files = packages(nonce, version, role)
            raw = archive(files)
            path = '/tarballs/' + role + '-' + version + '.tgz'
            result[path] = ('private-tarball', raw)
            versions[version] = {**json.loads(files['package.json']), 'dist': {
                'tarball': base_url + path,
                'integrity': 'sha512-' + base64.b64encode(hashlib.sha512(raw).digest()).decode(),
                'shasum': hashlib.sha1(raw).hexdigest()}}
        result['/' + identity] = ('private-packument', json.dumps({
            'name': identity, 'dist-tags': {'latest': VERSIONS[-1]}, 'versions': versions}).encode())
    return result


def expected(nonce, version, text, condition='enabled'):
    return nonce + ':' + version + '|Gr\u00fc\u00dfe|00ff4180|' + condition + '|' + text


class Feed:
    def __init__(self, payloads, token):
        self.assets = dict(payloads)
        self.authorization = 'Bearer ' + token
        self.observations = []
        self.failures = 0
        self.handshake_failures = 0
        self.lock = threading.Lock()

    def response(self, path, authorization):
        authorized = isinstance(authorization, str) and authorization.isascii() \
            and secrets.compare_digest(authorization, self.authorization)
        with self.lock:
            kind, raw = self.assets.get(path, ('unknown', b'not-found'))
            status = 401 if not authorized else 404 if kind == 'unknown' else 200
            require(len(self.observations) < MAX_REQUESTS, 'private-npm-peer-request-bound')
            self.observations.append({'asset': kind, 'authorized': authorized, 'status': status})
        return status, raw if authorized else b'authentication-required'


@contextmanager
def server(root, commands, nonce, token):
    key, certificate = root / 'key.pem', root / 'certificate.pem'
    commands.run('private-npm-public-certificate', 'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', key, '-out', certificate, '-days', '1', '-subj', '/CN=LSF private npm registry fixture',
        '-addext', 'basicConstraints=critical,CA:TRUE',
        '-addext', 'keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign',
        '-addext', 'subjectAltName=IP:127.0.0.1')
    key.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    feed = Feed({}, token)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):
            pass

        def do_GET(self):
            status, raw = feed.response(unquote(self.path), self.headers.get('Authorization', ''))
            self.send_response(status)
            if status == 401:
                self.send_header('WWW-Authenticate', 'Bearer realm="owned-fixture"')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(raw)

    class Peer(http.server.ThreadingHTTPServer):
        daemon_threads = False
        block_on_close = True
        request_queue_size = 8

        def get_request(self):
            connection, address = self.socket.accept()
            connection.settimeout(3)
            try:
                connection = context.wrap_socket(connection, server_side=True, do_handshake_on_connect=False)
                connection.do_handshake()
                return connection, address
            except BaseException as error:
                if isinstance(error, (ssl.SSLError, OSError)):
                    with feed.lock:
                        feed.handshake_failures += 1
                connection.close()
                raise

        def handle_error(self, *_args):
            with feed.lock:
                feed.failures += 1

    peer = Peer(('127.0.0.1', 0), Handler)
    port = peer.server_address[1]
    feed.assets = assets(nonce, 'https://127.0.0.1:' + str(port))
    owner = threading.Thread(target=peer.serve_forever, kwargs={'poll_interval': .05}, name='private-npm-proxy')
    owner.start()
    try:
        yield feed, 'https://127.0.0.1:' + str(port), read_file(certificate), read_file(key)
    finally:
        peer.shutdown()
        peer.server_close()
        owner.join(timeout=5)
        require(not owner.is_alive(), 'private-npm-peer-not-reaped')
        with socket.socket() as check:
            check.settimeout(1)
            require(check.connect_ex(('127.0.0.1', port)) != 0, 'private-npm-peer-listener-retained')



def probe(client, target, probe, result, population, value):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample, selected_revision
    require(isinstance(value, dict) and set(value) == {'nonce', 'version', 'removed', 'condition'}
            and type(value['removed']) is bool and value['condition'] in {'enabled', 'default'}, 'private-npm-probe-schema')
    packages(value['nonce'], value['version'], 'root')
    selected = selected_revision(client, target)
    rows = []
    for ordinal, text in enumerate(('alpha', 'Gr\u00fc\u00dfe', 'fresh-state')):
        argument = text if value['removed'] else 'private-npm:' + text
        row = call(client, target, 'greeting', 'greet', [argument], 'private-npm-' + str(ordinal))
        wanted = 'Hello, ' + text + '!' if value['removed'] else expected(value['nonce'], value['version'], text, value['condition'])
        assert_value(client, row, [{'ok': wanted}])
        consumption = row['response']['data']['consumption']
        require(row['response']['data'].get('resolvedRevision') == selected and row['processReaped']
                and all(int(consumption[name]) == 0 for name in ('outboundRequests', 'childCalls', 'effectCount')),
                'private-npm-signed-selected-revision')
        result['invocations'].append(row)
        result['samples'].append(sample(client, probe, 'private-npm-' + str(ordinal), population))
        result.setdefault('providerIdle', []).append(provider_idle(client))
        rows.append({'ordinal': ordinal, 'expectedDigest': digest(json.dumps(wanted).encode()),
                     'freshState': True, 'actualSignedTarget': True})
    result['capturedNpmPrivate'] = {'status': 'passed', 'cases': rows, **value}
