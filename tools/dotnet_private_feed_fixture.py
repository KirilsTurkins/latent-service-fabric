"""Owned authenticated NuGet v3 peer and ordinary private managed libraries."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import threading
import zipfile

from tools.build_observation import build_environment
from tools.dotnet_guest.compiler import Compiler
from tools.phase2_operator_process import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import digest, read_file

TOKEN_SLOT = 'LSF_NUGET_PRIVATE_FIXTURE_PASSWORD'
PREFIX = 'private-nuget:'
VERSIONS = ('1.0.0', '2.0.0')
MAX_REQUESTS = 128


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


def package(name, version, assembly, raw, child=None):
    dependency = ('' if child is None else '<dependencies><group targetFramework="net10.0">'
        '<dependency id="' + child + '" version="[' + version + ']" /></group></dependencies>')
    nuspec = ('<?xml version="1.0"?><package><metadata><id>' + name + '</id><version>' + version
        + '</version><authors>SDK qualification</authors><description>Owned private fixture</description>'
        + dependency + '</metadata></package>').encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as target:
        for path, data in ((name + '.nuspec', nuspec), ('lib/net10.0/' + assembly + '.dll', raw)):
            target.writestr(zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0)), data)
    result = output.getvalue()
    require(0 < len(result) <= 4 * 1024 * 1024, 'private-NuGet-package-bound')
    return result


def expected(nonce, version, text):
    return nonce + ':' + version + '|Gr\u00fc\u00dfe|' + text


def libraries(root, project, tools, nonce):
    """Compile ordinary pure managed code; never executes a package build hook."""
    result = {}
    compiler = None
    for version in VERSIONS:
        leaf_dll = None
        for role in ('Leaf', 'Main'):
            library = root / (role.lower() + '-' + version)
            library.mkdir(mode=0o700)
            assembly = 'Private' + role
            if role == 'Leaf':
                (library / 'text.txt').write_text(nonce + ':' + version + '|Gr\u00fc\u00dfe|', encoding='utf-8')
                source = '''public static class PrivateLeaf {
 public static string Prefix() {
  using var input = typeof(PrivateLeaf).Assembly.GetManifestResourceStream("private.text")
   ?? throw new System.Exception("private resource absent");
  using var reader = new System.IO.StreamReader(input, System.Text.Encoding.UTF8);
  return reader.ReadToEnd();
 }
}'''
                extra = '<EmbeddedResource Include="text.txt" LogicalName="private.text" />'
            else:
                source = '''public static class PrivateMain {
 private static readonly string Initialization = PrivateLeaf.Prefix();
 private static int calls;
 public static string Describe(string text) {
  if (++calls != 1 || Initialization != PrivateLeaf.Prefix())
   throw new System.Exception("private initialization or fresh state changed");
  return Initialization + text;
 }
}'''
                (library / 'references').mkdir(mode=0o700)
                (library / 'references/PrivateLeaf.dll').write_bytes(read_file(leaf_dll))
                extra = '<Reference Include="PrivateLeaf"><HintPath>references/PrivateLeaf.dll</HintPath></Reference>'
            (library / 'Library.cs').write_text(source, encoding='utf-8')
            (library / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                '<TargetFramework>net10.0</TargetFramework><OutputType>Library</OutputType><AssemblyName>' + assembly
                + '</AssemblyName><UseSharedCompilation>false</UseSharedCompilation>'
                '<ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>'
                '<ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets></PropertyGroup><ItemGroup>'
                + extra + '</ItemGroup></Project>', encoding='utf-8')
            (library / 'global.json').write_bytes(read_file(project / 'global.json'))
            (library / 'nuget.config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
            if compiler is None:
                evidence = root / 'library-evidence'
                evidence.mkdir(mode=0o700)
                commands = Commands(library, evidence, build_environment(root))
                compiler = Compiler(tools, commands, project / 'vendor/lsf', offline=True, captured=True)
            compiler.run('private-pure-managed-library', compiler.dotnet, 'build', library / 'Library.csproj',
                '-c', 'Release', '-p:RestoreConfigFile=' + str(library / 'nuget.config'), '-p:NuGetAudit=false',
                '-nodeReuse:false', '-p:UseSharedCompilation=false', '-p:ImportDirectoryBuildProps=false',
                '-p:ImportDirectoryBuildTargets=false')
            compiler.check_unchanged()
            dll = library / ('bin/Release/net10.0/' + assembly + '.dll')
            if role == 'Leaf':
                leaf_dll = dll
            identity = 'Outside.Private.' + nonce + '.' + role
            result[(identity.lower(), version)] = package(identity, version, assembly, read_file(dll),
                None if role == 'Leaf' else 'Outside.Private.' + nonce + '.Leaf')
    return result


def edit_source(project, original=None):
    target = project / 'src/Main.cs'
    if original is not None:
        target.write_bytes(original)
        return
    before = read_file(target)
    hook = b'$"Hello, {clean}!"'
    require(before.count(hook) == 1, 'private-NuGet-original-greeting-required')
    changed = before.replace(hook, b'PrivateGreeting(clean)')
    helper = b'''\n    private static string PrivateGreeting(string text) {
        if (text.StartsWith("private-nuget:", System.StringComparison.Ordinal))
            return PrivateMain.Describe(text.Substring(14));
        return $"Hello, {text}!";
    }\n'''
    position = changed.rfind(b'}')
    target.write_bytes(changed[:position] + helper + changed[position:])
    return before


class Feed:
    """Fixed finite assets; no raw paths, headers or credentials in observations."""
    def __init__(self, endpoint, payloads, token):
        self.authorization = 'Basic ' + base64.b64encode(('fixture:' + token).encode()).decode()
        self.assets = {'/index.json': ('index', json.dumps({'version': '3.0.0', 'resources': [
            {'@id': endpoint + '/flat/', '@type': 'PackageBaseAddress/3.0.0'}]}).encode())}
        for name, version in payloads:
            versions = sorted(v for n, v in payloads if n == name)
            self.assets['/flat/' + name + '/index.json'] = ('versions', json.dumps({'versions': versions}).encode())
            base = '/flat/' + name + '/' + version + '/' + name + '.' + version + '.nupkg'
            self.assets[base] = ('package', payloads[(name, version)])
            self.assets[base + '.sha512'] = ('hash', base64.b64encode(hashlib.sha512(payloads[(name, version)]).digest()))
        self.observations, self.lock = [], threading.Lock()

    def response(self, path, authorization):
        authorized = (isinstance(authorization, str) and authorization.isascii()
                      and secrets.compare_digest(authorization, self.authorization))
        kind, raw = self.assets.get(path, ('unknown', b'not-found'))
        status = 401 if not authorized else 404 if kind == 'unknown' else 200
        body = b'authentication-required' if status == 401 else raw
        with self.lock:
            require(len(self.observations) < MAX_REQUESTS, 'private-NuGet-peer-request-bound')
            self.observations.append({'asset': kind, 'authorized': authorized, 'status': status})
        return status, body


class Peer(http.server.ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 8


@contextmanager
def server(root, commands, payloads, token):
    key, certificate = root / 'key.pem', root / 'certificate.pem'
    commands.run('private-NuGet-certificate', 'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', key, '-out', certificate, '-days', '1', '-subj', '/CN=LSF private NuGet fixture',
        '-addext', 'basicConstraints=critical,CA:TRUE',
        '-addext', 'keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign',
        '-addext', 'subjectAltName=IP:127.0.0.1')
    key.chmod(0o600)
    feed = None

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def setup(self):
            super().setup()
            self.connection.settimeout(3)

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

    peer = Peer(('127.0.0.1', 0), Handler)
    port = peer.server_address[1]
    endpoint = 'https://127.0.0.1:' + str(port)
    feed = Feed(endpoint, payloads, token)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    peer.socket = context.wrap_socket(peer.socket, server_side=True)
    peer.socket.settimeout(3)
    owner = threading.Thread(target=peer.serve_forever, kwargs={'poll_interval': .05}, name='private-NuGet-peer')
    owner.start()
    try:
        yield feed, endpoint, read_file(certificate), read_file(key)
    finally:
        peer.shutdown()
        peer.server_close()
        owner.join(timeout=5)
        require(not owner.is_alive(), 'private-NuGet-peer-not-reaped')
        with socket.socket() as check:
            check.settimeout(1)
            require(check.connect_ex(('127.0.0.1', port)) != 0, 'private-NuGet-peer-listener-retained')


def probe(client, target, probe, result, population, value):
    from tools.rust_capsule_node import assert_value, call, sample, selected_revision
    from tools.rust_capsule_project import digest as sha
    require(isinstance(value, dict) and set(value) == {'nonce', 'version', 'removed'} and type(value['removed']) is bool
            and isinstance(value['nonce'], str) and len(value['nonce']) == 24
            and all(c in '0123456789abcdef' for c in value['nonce']) and value['version'] in VERSIONS,
            'private-NuGet-probe-schema')
    selected = selected_revision(client, target)
    cases = []
    for ordinal, text in enumerate(('alpha', 'Gr\u00fc\u00dfe', 'fresh-state')):
        name = text if value['removed'] else PREFIX + text
        actual = call(client, target, 'greeting', 'greet', [name], 'private-nuget-' + str(ordinal))
        expected_value = 'Hello, ' + text + '!' if value['removed'] else expected(value['nonce'], value['version'], text)
        assert_value(client, actual, [{'ok': expected_value}])
        require(actual['response']['data'].get('resolvedRevision') == selected and actual['processReaped'],
                'private-NuGet-signed-target')
        result['invocations'].append(actual)
        result['samples'].append(sample(client, probe, 'private-NuGet-' + str(ordinal), population))
        cases.append({'ordinal': ordinal, 'expectedDigest': sha(json.dumps(expected_value).encode()),
                      'actualSignedTarget': True, 'freshState': True})
    result['capturedDotnetPrivate'] = {'status': 'passed', 'cases': cases, **value}
