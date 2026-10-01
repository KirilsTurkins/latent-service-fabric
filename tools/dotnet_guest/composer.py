"""Exact SDK-owned component composer with the upstream resource alias fix."""
from __future__ import annotations

import json
from pathlib import Path
import time
import urllib.request

from tools.build_observation import file_identity
from tools.build_snapshot import digest
from tools.rust_capsule_project import read_file


VERSION = '0.10.1'
SIZE = 21726840
DIGEST = 'sha256:250c11762916ba733c7d22b62487580f21270ec9dde4f13460ea69d300e25406'
URL = 'https://github.com/bytecodealliance/wac/releases/download/v0.10.1/wac-cli-x86_64-unknown-linux-musl'


def selection(sdk: Path) -> dict:
    value = json.loads(read_file(sdk / 'component-composer.json'))
    expected = {'formatVersion': 1, 'version': VERSION, 'target': 'x86_64-unknown-linux-musl',
        'size': SIZE, 'digest': DIGEST, 'url': URL, 'upstreamFix': 'https://github.com/bytecodealliance/wac/pull/205'}
    if value != expected:
        raise ValueError('unreviewed .NET component composer profile')
    return value


def observed(directory: Path, sdk: Path) -> Path:
    pin = selection(sdk)
    binary = directory / 'component-composer/wac'
    identity = file_identity(binary, 'component-composer', SIZE)
    if identity['digest'] != pin['digest'] or identity['size'] != pin['size']:
        raise ValueError('component composer differs from the reviewed resource alias fix')
    return binary


def install(directory: Path, sdk: Path, commands) -> Path:
    pin = selection(sdk)
    started, data = time.monotonic(), bytearray()
    request = urllib.request.Request(pin['url'], headers={'User-Agent': 'LSF-SDK-tool-fetch'})
    with urllib.request.urlopen(request, timeout=30) as response:
        while block := response.read(65536):
            data.extend(block)
            if len(data) > SIZE or time.monotonic() - started > 180:
                raise ValueError('component composer fetch bound exceeded')
    if len(data) != SIZE or digest(data) != pin['digest']:
        raise ValueError('component composer download identity mismatch')
    output = directory / 'component-composer'
    output.mkdir()
    binary = output / 'wac'
    with binary.open('xb') as stream:
        stream.write(data)
    binary.chmod(0o755)
    if commands.run('component-composer-version', binary, '--version').strip() != b'wac-cli 0.10.1':
        raise ValueError('component composer version drift')
    return observed(directory, sdk)


def compose_exact(compiler, raw: Path, component: Path, coverage: dict, *, additional_adapters=()) -> dict:
    """Wire each observed WASI import once, using its complete interface name.

    The pinned WAC plug command also semver-matches exports. An adapter which
    supplies both 0.2.0 and 0.2.6 can therefore satisfy one 0.2.6 argument twice.
    Explicit named edges preserve both exports without an inferred substitute.
    WAC still validates the real interface signatures and resource identities.
    """
    from tools.dev_workflow.common import decode, require
    from tools.guest_compatibility_build import interface_names
    from tools.rust_capsule_project import write_json

    maximum_graph = 4 * 1024 * 1024
    require(1 <= len(additional_adapters) <= 4, 'dotnet-composition-adapter-limit')
    output = compiler.commands.output
    inputs, graphs = [], []

    def observe(path, graph_name, component_digest, graph_digest):
        body, graph_bytes = read_file(path, 64 * 1024 * 1024), read_file(output / graph_name, maximum_graph)
        require(digest(body) == component_digest and digest(graph_bytes) == graph_digest,
                'dotnet-composition-stale-inspection')
        inputs.append((path, body, output / graph_name, graph_bytes))
        return interface_names(decode(graph_bytes, maximum_graph))

    raw_names = observe(raw, 'native-aot-raw.wit.json', coverage['rawComponentDigest'], coverage['rawWitDigest'])
    graphs.append(observe(compiler.runtime, 'closed-runtime-adapter.wit.json',
                          coverage['runtimeAdapterDigest'], coverage['runtimeWitDigest']))
    extra = coverage.get('additionalAdapters')
    require(isinstance(extra, list) and len(extra) == len(additional_adapters), 'dotnet-composition-adapter-receipt')
    adapters = [('primary', compiler.runtime)]
    for (name, path), row in zip(additional_adapters, extra):
        require(row['name'] == name and row['witSource'] == 'additional-runtime-' + name + '.wit.json',
                'dotnet-composition-adapter-receipt')
        graphs.append(observe(path, row['witSource'], row['componentDigest'], row['witDigest']))
        adapters.append((name, path))
    supplied = {}
    for ordinal, graph in enumerate(graphs):
        for name in graph['exports']:
            require(name not in supplied, 'dotnet-composition-duplicate-export')
            supplied[name] = ordinal
    require(len(supplied) <= 256, 'dotnet-composition-interface-limit')
    lines = ['package lsf:dotnet-composition;']
    lines.extend('let runtime' + str(index) + ' = new lsf:adapter' + str(index) + ' { ... };'
                 for index in range(len(adapters)))
    lines.append('let application = new lsf:application {')
    edges = []
    for name in raw_names['imports']:
        if not name.startswith('wasi:'):
            continue  # Original application authority stays an explicit host import.
        require(name in supplied, 'dotnet-composition-exact-export-missing')
        ordinal, literal = supplied[name], json.dumps(name)
        lines.append('    ' + literal + ': runtime' + str(ordinal) + '[' + literal + '],')
        edges.append({'interface': name, 'adapter': adapters[ordinal][0]})
    lines.extend(('    ...', '};', 'export application...;'))
    source = ('\n'.join(lines) + '\n').encode('utf-8')
    require(len(source) <= 64 * 1024, 'dotnet-composition-source-limit')
    script = component.parent / 'runtime-composition.wac'
    with script.open('xb') as stream:
        stream.write(source)
    retained = output / 'runtime-composition.wac'
    with retained.open('xb') as stream:
        stream.write(source)
    dependencies = component.parent / 'runtime-composition-deps'
    dependencies.mkdir()
    if compiler.isolation is not None:
        compiler.isolation.protect_inputs(script, raw)
    arguments = ['compose', script, '--deps-dir', dependencies, '--dep', 'lsf:application=' + str(raw)]
    for ordinal, (_name, path) in enumerate(adapters):
        arguments.extend(('--dep', 'lsf:adapter' + str(ordinal) + '=' + str(path)))
    compiler.run('closed-runtime-composition', compiler.wac, *arguments, '-o', component)
    require(all(read_file(path, 64 * 1024 * 1024) == body
                and read_file(graph_path, maximum_graph) == graph_body
                for path, body, graph_path, graph_body in inputs), 'dotnet-composition-input-changed')
    require(read_file(script, 64 * 1024) == source and read_file(retained, 64 * 1024) == source,
            'dotnet-composition-source-changed')
    result = {'schemaVersion': 'lsf.dotnet.runtime.composition.v1', 'matching': 'exact-interface-names',
        'sourceDigest': digest(source), 'sourceSize': len(source), 'rawComponentDigest': coverage['rawComponentDigest'],
        'adapters': [{'name': name, 'componentDigest': digest(body)}
                     for (name, _path), (_original, body, _graph, _graph_body) in zip(adapters, inputs[1:])],
        'edges': edges, 'unmodifiedHostImports': [name for name in raw_names['imports'] if not name.startswith('wasi:')],
        'composer': file_identity(compiler.wac, 'component-composer', SIZE),
        'component': file_identity(component, 'exact-runtime-composition', 64 * 1024 * 1024),
        'ordinaryLibraryExecutionQualified': False}
    write_json(output / 'runtime-composition.json', result)
    compiler.generated_materials.extend((file_identity(retained, 'runtime-composition-source', 64 * 1024),
        file_identity(output / 'runtime-composition.json', 'runtime-composition', maximum_graph)))
    return result
