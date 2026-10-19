"""Owned HTTPS Go proxy and ordinary, previously unknown module coordinates."""
from contextlib import contextmanager
import base64
import http.server
import io
import json
from pathlib import Path
import secrets
import socket
import ssl
import threading
import zipfile

from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest, read_file

TOKEN_SLOT = 'LSF_GO_PRIVATE_PROXY_FIXTURE'
VERSIONS = ('v1.0.0', 'v1.1.0')
TAG = 'private_proxy_qualification'
MAX_REQUESTS = 256


def module_sources(nonce, version, role):
    require(isinstance(nonce, str) and len(nonce) == 24
            and all(c in '0123456789abcdef' for c in nonce)
            and version in VERSIONS and role in {'root', 'leaf'}, 'private-Go-module-selection')
    identity = 'private.example.test/' + nonce + '/' + role
    child = 'private.example.test/' + nonce + '/leaf'
    manifest = 'module ' + identity + '\n\ngo 1.27.2\n'
    if role == 'root':
        manifest += '\nrequire ' + child + ' ' + version + '\n'
        files = {'value.go': ('package ordinary\nimport leaf "' + child + '"\n'
            'var prefix = leaf.Prefix()\nvar calls uint32\n'
            'func Describe(value string) string {\n'
            ' calls++; if calls != 1 || prefix != leaf.Prefix() { panic("fresh private state") };\n'
            ' return prefix + "|" + feature + "|" + target + "|" + value\n}\n').encode(),
            'feature_on.go': ('//go:build ' + TAG + '\n\npackage ordinary\nconst feature = "enabled"\n').encode(),
            'feature_off.go': ('//go:build !' + TAG + '\n\npackage ordinary\nconst feature = "disabled"\n').encode(),
            'target_wasip1.go': b'package ordinary\nconst target = "wasip1"\n',
            'target_linux.go': b'package ordinary\nconst target = "linux"\n'}
    else:
        files = {'value.go': b'''package leaf
import (_ "embed"; "encoding/hex")
//go:embed text.txt
var text string
//go:embed data.bin
var data []byte
func Prefix() string { return text + "|" + hex.EncodeToString(data) }
''', 'text.txt': (nonce + ':' + version + '|Gr\u00fc\u00dfe').encode(),
            'data.bin': bytes((0, 255, 65, 128))}
    return identity, {'go.mod': manifest.encode(), **files}


def archive(identity, version, files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as target:
        for name, raw in sorted(files.items()):
            path = identity + '@' + version + '/' + name
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, raw)
    result = output.getvalue()
    require(0 < len(result) <= 4 * 1024 * 1024, 'private-Go-module-archive-bound')
    return result


def assets(nonce):
    result = {}
    for role in ('root', 'leaf'):
        for version in VERSIONS:
            identity, files = module_sources(nonce, version, role)
            base = '/' + identity + '/@v/' + version
            result[base + '.mod'] = ('private-mod', files['go.mod'])
            result[base + '.zip'] = ('private-zip', archive(identity, version, files))
            result[base + '.info'] = ('private-info', json.dumps(
                {'Version': version, 'Time': '2000-01-01T00:00:00Z'}).encode())
        result['/' + identity + '/@v/list'] = ('private-list', ('\n'.join(VERSIONS) + '\n').encode())
    return result


def expected(nonce, version, text, target='wasip1'):
    return nonce + ':' + version + '|Gr\u00fc\u00dfe|00ff4180|enabled|' + target + '|' + text


class Feed:
    def __init__(self, payloads, token):
        self.assets = dict(payloads)
        self.authorization = 'Basic ' + base64.b64encode(('fixture:' + token).encode()).decode()
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
            require(len(self.observations) < MAX_REQUESTS, 'private-Go-peer-request-bound')
            self.observations.append({'asset': kind, 'authorized': authorized, 'status': status})
        return status, raw if authorized else b'authentication-required'


@contextmanager
def server(root, commands, payloads, token):
    key, certificate = root / 'key.pem', root / 'certificate.pem'
    commands.run('private-Go-public-certificate', 'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', key, '-out', certificate, '-days', '1', '-subj', '/CN=LSF private Go proxy fixture',
        '-addext', 'basicConstraints=critical,CA:TRUE',
        '-addext', 'keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign',
        '-addext', 'subjectAltName=IP:127.0.0.1')
    key.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    feed = Feed(payloads, token)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):
            pass

        def do_GET(self):
            status, raw = feed.response(self.path, self.headers.get('Authorization', ''))
            self.send_response(status)
            if status == 401:
                self.send_header('WWW-Authenticate', 'Basic realm="owned-fixture"')
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
                if isinstance(error, OSError):
                    with feed.lock:
                        feed.handshake_failures += 1
                connection.close()
                raise

        def handle_error(self, *_args):
            with feed.lock:
                feed.failures += 1

    peer = Peer(('127.0.0.1', 0), Handler)
    port = peer.server_address[1]
    owner = threading.Thread(target=peer.serve_forever, kwargs={'poll_interval': .05}, name='private-Go-proxy')
    owner.start()
    try:
        yield feed, 'https://127.0.0.1:' + str(port), read_file(certificate), read_file(key)
    finally:
        peer.shutdown()
        peer.server_close()
        owner.join(timeout=5)
        require(not owner.is_alive(), 'private-Go-peer-not-reaped')
        with socket.socket() as check:
            check.settimeout(1)
            require(check.connect_ex(('127.0.0.1', port)) != 0, 'private-Go-peer-listener-retained')


def probe(client, target, probe, result, population, value):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample, selected_revision
    require(isinstance(value, dict) and set(value) == {'nonce', 'version', 'removed'}
            and type(value['removed']) is bool, 'private-Go-probe-schema')
    module_sources(value['nonce'], value['version'], 'root')
    selected = selected_revision(client, target)
    rows = []
    for ordinal, text in enumerate(('alpha', 'Gr\u00fc\u00dfe', 'fresh-state')):
        argument = text if value['removed'] else 'private-go:' + text
        row = call(client, target, 'greeting', 'greet', [argument], 'private-Go-' + str(ordinal))
        wanted = 'Hello, ' + text + '!' if value['removed'] else expected(value['nonce'], value['version'], text)
        assert_value(client, row, [{'ok': wanted}])
        consumption = row['response']['data']['consumption']
        require(row['response']['data'].get('resolvedRevision') == selected and row['processReaped']
                and all(int(consumption[name]) == 0 for name in ('outboundRequests', 'childCalls', 'effectCount')),
                'private-Go-signed-selected-revision')
        result['invocations'].append(row)
        result['samples'].append(sample(client, probe, 'private-Go-' + str(ordinal), population))
        result.setdefault('providerIdle', []).append(provider_idle(client))
        rows.append({'ordinal': ordinal, 'expectedDigest': digest(json.dumps(wanted).encode()),
                     'freshState': True, 'actualSignedTarget': True})
    result['capturedGoPrivate'] = {'status': 'passed', 'cases': rows, **value}
