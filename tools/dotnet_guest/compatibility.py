"""Observe required NativeAOT members before composing the selected runtime."""
from __future__ import annotations

from pathlib import Path
import re

from tools import guest_compatibility as compatibility
from tools.guest_compatibility_build import interface_names, retain_report
from tools.dev_workflow.common import decode, digest, require
from tools.rust_capsule_project import read_file, write_json

PROFILE = 'dotnet-native-aot-component-v1'
MAX_GRAPH = 4 * 1024 * 1024


def members(graph: dict, direction: str) -> dict:
    names = interface_names(graph)[direction]
    rows = graph['worlds'][0][direction].values()
    result, count = {}, 0
    for row in rows:
        interface = graph['interfaces'][row['interface']['id']]
        package = graph['packages'][interface['package']]['name']
        base, _, version = package.partition('@')
        name = base + '/' + interface['name'] + ('@' + version if version else '')
        functions, types = interface.get('functions'), interface.get('types')
        require(isinstance(functions, dict) and isinstance(types, dict), 'dotnet-runtime-member-tables')
        require(len(functions) <= 1024 and len(types) <= 1024, 'dotnet-runtime-member-limit')
        count += len(functions) + len(types)
        require(count <= 4096, 'dotnet-runtime-member-limit')
        for symbol, value in functions.items():
            compatibility.token(symbol)
            require(isinstance(value, dict) and value.get('name') == symbol, 'dotnet-runtime-function-name')
        for symbol, index in types.items():
            compatibility.token(symbol)
            require(type(index) is int and 0 <= index < len(graph['types']), 'dotnet-runtime-type-index')
        result[name] = {'functions': sorted(functions), 'types': sorted(types)}
    require(set(result) == set(names), 'dotnet-runtime-interface-identity')
    return result


def coverage(raw: dict, adapter: dict, *, additional_adapters=()) -> dict:
    """Member presence is a necessary check; WAC still checks all type signatures."""
    required, supplied = members(raw, 'imports'), members(adapter, 'exports')
    require(len(additional_adapters) <= 4, 'dotnet-runtime-additional-adapter-limit')
    for graph in additional_adapters:
        exports = members(graph, 'exports')
        require(not set(exports) & set(supplied), 'dotnet-runtime-duplicate-adapter-export')
        supplied.update(exports)
    require(len(supplied) <= 256 and sum(len(row['functions']) + len(row['types'])
            for row in supplied.values()) <= 4096, 'dotnet-runtime-member-limit')
    gaps = []
    for name, row in sorted(required.items()):
        if not name.startswith('wasi:'):
            continue  # Declared LSF capabilities are checked on the final graph.
        if name not in supplied:
            gaps.append({'interface': name, 'kind': 'interface'})
            continue
        for kind in ('types', 'functions'):
            for symbol in sorted(set(row[kind]) - set(supplied[name][kind])):
                gaps.append({'interface': name, 'kind': kind, 'symbol': symbol})
    require(len(gaps) <= 4096, 'dotnet-runtime-gap-limit')
    return {'requiredImports': sorted(required), 'adapterExports': sorted(supplied), 'gaps': gaps,
            'analysisCompleteness': 'required-member-names', 'authority': 'none'}


def findings(value: dict) -> list:
    result = []
    for gap in value['gaps']:
        result.append(compatibility.finding('missing-runtime-port', 'link', 'compiler',
            operation=gap['interface'], symbol=gap.get('symbol'),
            owner_issue=693 if gap['interface'].startswith('wasi:http/') else None))
    return result


def inspect(compiler, raw: Path, *, additional_adapters=()) -> dict:
    raw_bytes, adapter_bytes = read_file(raw, 64 * 1024 * 1024), read_file(compiler.runtime, 64 * 1024 * 1024)
    raw_graph = compiler.run('native-aot-raw-wit', compiler.wasm, 'component', 'wit', raw, '--json')
    adapter_graph = compiler.run('closed-runtime-adapter-wit', compiler.wasm, 'component', 'wit', compiler.runtime, '--json')
    require(len(additional_adapters) <= 4, 'dotnet-runtime-additional-adapter-limit')
    graphs, extra, original = [], [], []
    for name, path in additional_adapters:
        require(isinstance(name, str) and re.fullmatch(r'[a-z][a-z0-9-]{0,63}', name)
                and name not in [row['name'] for row in extra], 'dotnet-runtime-additional-adapter-name')
        body = read_file(path, 64 * 1024 * 1024)
        graph = compiler.run('additional-runtime-' + name + '-wit', compiler.wasm, 'component', 'wit', path, '--json')
        graphs.append(decode(graph, MAX_GRAPH))
        source = 'additional-runtime-' + name + '.wit.json'
        extra.append({'name': name, 'componentDigest': digest(body), 'witDigest': digest(graph), 'witSource': source})
        original.append((path, body))
        (compiler.commands.output / source).write_bytes(graph)
    value = coverage(decode(raw_graph, MAX_GRAPH), decode(adapter_graph, MAX_GRAPH), additional_adapters=graphs)
    require(read_file(raw, 64 * 1024 * 1024) == raw_bytes
            and read_file(compiler.runtime, 64 * 1024 * 1024) == adapter_bytes, 'dotnet-runtime-coverage-stale-input')
    require(all(read_file(path, 64 * 1024 * 1024) == body for path, body in original),
            'dotnet-runtime-coverage-stale-input')
    value.update(schemaVersion='lsf.dotnet.runtime.coverage.v1', runtimeProfile=PROFILE,
                 rawComponentDigest=digest(raw_bytes), runtimeAdapterDigest=digest(adapter_bytes),
                 rawWitDigest=digest(raw_graph), runtimeWitDigest=digest(adapter_graph))
    if extra:
        value['additionalAdapters'] = extra
    output = compiler.commands.output
    (output / 'native-aot-raw.wit.json').write_bytes(raw_graph)
    (output / 'closed-runtime-adapter.wit.json').write_bytes(adapter_graph)
    write_json(output / 'closed-runtime-coverage.json', value)
    if value['gaps']:
        # Preserve the actual compiler output, even though it cannot be signed
        # as a compatible LSF component. Never erase imports or install WASI.
        (output / 'native-aot-raw.wasm').write_bytes(raw_bytes)
        raise ValueError('NativeAOT-selected-runtime-members-missing; inspect closed-runtime-coverage.json')
    return value


def retain_failure(output: Path) -> None:
    """Add precise raw-component observations after the shared failure report."""
    path = output / 'closed-runtime-coverage.json'
    if not path.exists() or not (output / 'native-aot-raw.wasm').exists():
        return
    value = decode(read_file(path, MAX_GRAPH), MAX_GRAPH)
    require(value['schemaVersion'] == 'lsf.dotnet.runtime.coverage.v1'
            and value['runtimeProfile'] == PROFILE
            and value['rawComponentDigest'] == digest(read_file(output / 'native-aot-raw.wasm', 64 * 1024 * 1024))
            and value['rawWitDigest'] == digest(read_file(output / 'native-aot-raw.wit.json', MAX_GRAPH))
            and value['runtimeWitDigest'] == digest(read_file(output / 'closed-runtime-adapter.wit.json', MAX_GRAPH)),
            'dotnet-runtime-coverage-stale-receipt')
    graphs, extra = [], value.get('additionalAdapters', [])
    require(isinstance(extra, list) and len(extra) <= 4, 'dotnet-runtime-additional-adapter-limit')
    names = set()
    for row in extra:
        require(isinstance(row, dict) and set(row) == {'name', 'componentDigest', 'witDigest', 'witSource'},
                'dotnet-runtime-additional-adapter-receipt')
        name = row['name']
        require(isinstance(name, str) and re.fullmatch(r'[a-z][a-z0-9-]{0,63}', name)
                and name not in names and row['witSource'] == 'additional-runtime-' + name + '.wit.json',
                'dotnet-runtime-additional-adapter-receipt')
        names.add(name)
        compatibility.sha(row['componentDigest'])
        graph = read_file(output / row['witSource'], MAX_GRAPH)
        require(digest(graph) == row['witDigest'], 'dotnet-runtime-coverage-stale-receipt')
        graphs.append(decode(graph, MAX_GRAPH))
    actual = coverage(decode(read_file(output / 'native-aot-raw.wit.json', MAX_GRAPH), MAX_GRAPH),
                      decode(read_file(output / 'closed-runtime-adapter.wit.json', MAX_GRAPH), MAX_GRAPH),
                      additional_adapters=graphs)
    require(all(actual[key] == value[key] for key in actual), 'dotnet-runtime-coverage-stale-receipt')
    source = output / 'source-inputs.json'
    if not source.exists():
        return  # A source identity is required; do not invent one for a probe.
    report = compatibility.report('dotnet', digest(read_file(source)), value['rawComponentDigest'], PROFILE,
        [{'kind': 'runtime', 'digest': value['runtimeAdapterDigest'], 'profile': PROFILE},
         *({'kind': 'runtime', 'digest': row['componentDigest'], 'profile': PROFILE + '/' + row['name']}
           for row in extra)], findings(value))
    # This report explicitly describes the retained raw compiler component;
    # successful final composition has a separate authoritative inspection.
    retain_report(output, report, kind='raw')
