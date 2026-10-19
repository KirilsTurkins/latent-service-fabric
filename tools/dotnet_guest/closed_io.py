"""Keep immediately completing closed WASI operations on their synchronous ABI.

Only the two closed primary adapters qualify. The compiler authenticates the
complete public graph against its captured WIT, retains every core module byte,
and records the derived component separately from the installed original.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import time

from tools.dotnet_guest import internal_io as io
from tools.dotnet_guest import runtime
from tools.rust_capsule_project import digest, inventory, read_file, snapshot, write_json

PROFILE = 'dotnet-private-synchronous-closed-io-v1'
PROFILES = frozenset({'closed', 'closed-logging'})
NAMES = frozenset(name for values in io.TARGETS.values() for name in values)
PRIVATE_NAMES = {
    'import-method-pollable-block': '[method]pollable.block',
    'import-func-poll': 'poll',
    'import-method-input-stream-blocking-read': '[method]input-stream.blocking-read',
    'import-method-output-stream-blocking-flush': '[method]output-stream.blocking-flush',
}


def projected_graph(original: dict, reference: dict, profile: str) -> dict:
    if profile not in PROFILES:
        raise ValueError('dotnet-closed-io-profile')
    required = {runtime.CLOCK, *({runtime.LOG} if profile == 'closed-logging' else set())}
    if set(io.functions(original, 'imports')) != required:
        raise ValueError('dotnet-closed-io-original-import-authority')
    for direction in ('imports', 'exports'):
        actual, expected = io.functions(original, direction), io.functions(reference, direction)
        if set(actual) != set(expected):
            raise ValueError('dotnet-closed-io-original-interface-set')
        for interface, functions in actual.items():
            if set(functions) != set(expected[interface]) or any(
                    io.shape(original, function) != io.shape(reference, expected[interface][name])
                    or (set(function['kind']) if isinstance(function['kind'], dict) else function['kind'])
                    != (set(expected[interface][name]['kind']) if isinstance(expected[interface][name]['kind'], dict)
                        else expected[interface][name]['kind'])
                    for name, function in functions.items()):
                raise ValueError('dotnet-closed-io-original-function-shape')
    result = copy.deepcopy(original)
    found = set()
    for interface, functions in io.functions(result, 'exports').items():
        for name, function in functions.items():
            kind = function['kind']
            asynchronous = kind == 'async-freestanding' or isinstance(kind, dict) and set(kind) == {'async-method'}
            if name in io.TARGETS.get(interface, set()):
                if not asynchronous:
                    raise ValueError('dotnet-closed-io-original-function-not-async')
                function['kind'] = 'freestanding' if kind == 'async-freestanding' else {'method': kind['async-method']}
                found.add((interface, name))
            elif asynchronous:
                raise ValueError('dotnet-closed-io-foreign-async-function')
    if found != {(interface, name) for interface, names in io.TARGETS.items() for name in names}:
        raise ValueError('dotnet-closed-io-original-function-set')
    if any(function['kind'] == 'async-freestanding' or isinstance(function['kind'], dict)
            and set(function['kind']) == {'async-method'}
            for functions in io.functions(result, 'imports').values() for function in functions.values()):
        raise ValueError('dotnet-closed-io-async-import')
    return result


def selected_text(text: str) -> str:
    """Remove async only from types referenced exclusively by the four names.

    Named printer references are resolved within their original lexical scope.
    No canonical lift/lower option, resource, core import or body is rewritten.
    """
    edits = []

    def visit(scope):
        rows = [row for row in scope.items if isinstance(row, io.Node)]
        types = {}
        for row in rows:
            if row.head('type') and len(row.items) == 3 and isinstance(row.items[1], str):
                body = row.items[2]
                if isinstance(body, io.Node) and body.head('func') and body.items[1:2] == ['async']:
                    types[row.items[1]] = (body, set())
        for row in rows:
            function, name = None, None
            if row.head('func') and len(row.items) > 1 and isinstance(row.items[1], str):
                function, name = row, row.items[1].removeprefix('$')
            elif row.head('import') or row.head('export'):
                symbols = [item for item in row.items[1:] if isinstance(item, str) and item.startswith('"')]
                functions = [item for item in row.items if isinstance(item, io.Node) and item.head('func')]
                if len(symbols) == 1:
                    name = symbols[0]
                    # The signature follows the optional exported function index.
                    function = next((item for item in functions if any(
                        isinstance(child, io.Node) and child.head('type') for child in item.items)), None)
            if function is not None:
                references = [item for item in function.items if isinstance(item, io.Node) and item.head('type')]
                for reference in references:
                    if len(reference.items) == 2 and reference.items[1] in types:
                        if name.startswith('"'):
                            name = json.loads(name)
                        name = PRIVATE_NAMES.get(name, name)
                        types[reference.items[1]][1].add(name)
        for body, names in types.values():
            if not names or not names <= NAMES:
                raise ValueError('dotnet-closed-io-unknown-async-type-use')
            raw = text[body.start:body.end]
            if not raw.startswith('(func async ') and raw != '(func async)':
                raise ValueError('dotnet-closed-io-async-token-preimage')
            edits.append((body.start, body.end, raw.replace('(func async', '(func', 1)))
        for row in rows:
            visit(row)

    visit(io.tree(text))
    if not 4 <= len(edits) <= 32:
        raise ValueError('dotnet-closed-io-async-type-count')
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def prepare(compiler, adapter: Path, output: Path, profile: str):
    if profile not in PROFILES:
        raise ValueError('dotnet-closed-io-profile')
    original = read_file(adapter, io.MAX_BINARY)
    graph = json.loads(compiler.run('closed-io-original-wit', compiler.wasm, 'component', 'wit', adapter, '--json'))
    output.mkdir()
    source = compiler.sdk / 'runtime/wit'
    source_inputs = inventory(snapshot(source))
    # The pinned decoder has no --world selector. Its finite dummy encoder
    # selects the source world without compiling or executing an implementation.
    compiler.run('closed-io-source-embed', compiler.wasm, 'component', 'embed', source,
        '--world', profile, '--dummy', '-o', output/'reference-core.wasm')
    compiler.run('closed-io-source-component', compiler.wasm, 'component', 'new',
        output/'reference-core.wasm', '-o', output/'reference.wasm')
    reference = json.loads(compiler.run('closed-io-source-wit', compiler.wasm, 'component', 'wit',
        output/'reference.wasm', '--json'))
    expected = projected_graph(graph, reference, profile)
    before = io.core_modules(original)
    if not before or len(before) > 64:
        raise ValueError('dotnet-closed-io-core-module-count')
    compiler.run('closed-io-unbundle', compiler.wasm, 'component', 'unbundle', adapter,
        '--module-dir', output/'modules', '--threshold', '0', '-o', output/'unbundled.wasm')
    modules = {}
    for path in sorted((output/'modules').iterdir()):
        if not re.fullmatch(r'unbundled-module[0-9]+\.wasm', path.name):
            raise ValueError('dotnet-closed-io-module-filename')
        modules[path.stem] = read_file(path, io.MAX_BINARY)
    if sorted(before) != sorted(modules.values()):
        raise ValueError('dotnet-closed-io-unbundle-changed-core')
    compiler.run('closed-io-print', compiler.wasm, 'print', '--name-unnamed', output/'unbundled.wasm', '-o', output/'unbundled.wat')
    if time.monotonic() >= compiler.commands.deadline:
        raise ValueError('dotnet-closed-io-original-deadline')
    text = selected_text(io.named_export_syntax(read_file(output/'unbundled.wat', io.MAX_TEXT).decode()))
    selected = output/'selected.wasm'
    (output/'selected.wat').write_bytes(text.encode())
    compiler.run('closed-io-encode', compiler.wasm, 'parse', output/'selected.wat', '-o', output/'unbundled-selected.wasm')
    selected.write_bytes(io.rebundle(read_file(output/'unbundled-selected.wasm', io.MAX_BINARY), modules))
    compiler.run('closed-io-validate', compiler.wasm, 'validate', '--features', 'all', selected)
    after = json.loads(compiler.run('closed-io-selected-wit', compiler.wasm, 'component', 'wit', selected, '--json'))
    if expected != after or sorted(before) != sorted(io.core_modules(read_file(selected, io.MAX_BINARY))):
        raise ValueError('dotnet-closed-io-changed-other-types-or-core')
    if read_file(adapter, io.MAX_BINARY) != original or inventory(snapshot(source)) != source_inputs:
        raise ValueError('dotnet-closed-io-original-adapter-changed')
    record = {'profile': PROFILE, 'runtimeProfile': profile,
        'originalDigest': digest(original), 'selectedDigest': digest(read_file(selected, io.MAX_BINARY)),
        'referenceGraphDigest': digest(json.dumps(reference, sort_keys=True).encode()),
        'sourceWitInputsDigest': digest(source_inputs),
        'functions': {name: sorted(values) for name, values in io.TARGETS.items()},
        'coreModules': [{'digest': digest(body), 'size': len(body)} for body in before],
        'coreBytesUnchanged': True, 'applicationImportsUnchanged': True, 'signedExecution': 'not-run'}
    write_json(compiler.commands.output/'closed-io-port.json', record)
    return selected, record
