"""Compiler-owned value-API forwarding root, independent of library identity.

The application component is never rewritten. Each completed root call retains
its actual value/error until the same adapter's private drain completes. Public
resource forwarding needs a separate ownership implementation and is refused.
"""
from __future__ import annotations

import json
import re
import tomllib

from tools import rust_wasi_http_profile as profile

PRIMITIVES = {
    'bool': 'bool', 'u8': 'u8', 's8': 'i8', 'u16': 'u16', 's16': 'i16',
    'u32': 'u32', 's32': 'i32', 'u64': 'u64', 's64': 'i64',
    'f32': 'f32', 'f64': 'f64', 'char': 'char', 'string': 'String',
}
KEYWORDS = frozenset(('as break const continue crate else enum extern false fn for if impl in let '
    'loop match mod move mut pub ref return self Self static struct super trait true type unsafe '
    'use where while async await dyn abstract become box do final macro override priv typeof '
    'unsized virtual yield try union').split())


def identifier(name: str) -> str:
    if type(name) is not str or not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', name) or len(name) > 128:
        raise ValueError('rust-http-root-identifier')
    value = name.replace('-', '_')
    if value in KEYWORDS:
        raise ValueError('rust-http-root-keyword-identifier-unsupported')
    return value


def rust_type(graph: dict, value, *, depth=0, active=frozenset(), work=None) -> str:
    work = [32768] if work is None else work
    work[0] -= 1
    if depth > 32 or work[0] < 0:
        raise ValueError('rust-http-root-type-depth')
    if value is None:
        return '()'
    if type(value) is str:
        if value not in PRIMITIVES:
            raise ValueError('rust-http-root-unsupported-primitive')
        return PRIMITIVES[value]
    if type(value) is not int or value < 0 or value >= len(graph['types']) or value in active:
        raise ValueError('rust-http-root-type-index-or-cycle')
    row = graph['types'][value]
    # A named aggregate's Rust identity differs across the import/export
    # namespaces. It cannot be forwarded by pretending those types are equal.
    if row.get('name') is not None:
        raise ValueError('rust-http-root-named-or-resource-value-unsupported')
    kind = row['kind']
    if not isinstance(kind, dict) or len(kind) != 1:
        raise ValueError('rust-http-root-resource-value-unsupported')
    def nested(child):
        result = rust_type(graph, child, depth=depth+1, active=active | {value}, work=work)
        if len(result) > 8192:
            raise ValueError('rust-http-root-generated-type-bound')
        return result
    if set(kind) == {'list'}:
        return 'Vec<' + nested(kind['list']) + '>'
    if set(kind) == {'option'}:
        return 'Option<' + nested(kind['option']) + '>'
    if set(kind) == {'result'} and set(kind['result']) == {'ok', 'err'}:
        return 'Result<' + nested(kind['result']['ok']) + ', ' + nested(kind['result']['err']) + '>'
    if set(kind) == {'tuple'} and set(kind['tuple']) == {'types'} and len(kind['tuple']['types']) <= 16:
        return '(' + ''.join(nested(child) + ', ' for child in kind['tuple']['types']) + ')'
    raise ValueError('rust-http-root-value-shape-unsupported')


def argument(graph: dict, name: str, value) -> str:
    """Pinned wit-bindgen borrowed parameter conventions for this finite port."""
    rust_type(graph, value)
    if value == 'string':
        return '&' + name
    if type(value) is int:
        kind = graph['types'][value]['kind']
        if set(kind) == {'list'}:
            child = kind['list']
            # Lists of owned strings/aggregates need a recursively borrowed
            # argument projection; an ABI guess is not an implementation.
            if child not in PRIMITIVES or child == 'string':
                raise ValueError('rust-http-root-borrowed-list-element-unsupported')
            return '&' + name
        raise ValueError('rust-http-root-borrowed-aggregate-unsupported')
    return name


def forwarding_source(graph: dict) -> tuple[bytes, list[dict]]:
    exports = profile.names(graph, 'exports')
    if not exports or len(exports) > 32:
        raise ValueError('rust-http-root-export-count')
    lines = [
        '#![cfg(target_arch = "wasm32")]',
        'wit_bindgen::generate!({ path: "wit", world: "root" });',
        'struct Root;',
    ]
    calls = []
    for identity, interface in sorted(exports.items()):
        match = re.fullmatch(r'([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)/([a-z][a-z0-9-]*)@([0-9]+\.[0-9]+\.[0-9]+)', identity)
        if match is None or interface['types']:
            raise ValueError('rust-http-root-export-interface-or-types-unsupported')
        path = '::'.join(identifier(name) for name in match.groups()[:3])
        functions = interface['functions']
        if not functions or len(functions) > 128 or len(calls) + len(functions) > 128:
            raise ValueError('rust-http-root-function-count')
        lines.append('impl exports::' + path + '::Guest for Root {')
        for name, function in functions.items():
            if function.get('name') != name or function['kind'] not in ('freestanding', 'async-freestanding'):
                raise ValueError('rust-http-root-function-kind-unsupported')
            asynchronous = function['kind'] == 'async-freestanding'
            params = function['params']
            if not isinstance(params, list) or len(params) > 32:
                raise ValueError('rust-http-root-parameter-count')
            declarations, arguments = [], []
            for param in params:
                param_name = identifier(param['name'])
                declarations.append(param_name + ': ' + rust_type(graph, param['type']))
                arguments.append(argument(graph, param_name, param['type']))
            result = rust_type(graph, function.get('result'))
            symbol = identifier(name)
            lines.append('    ' + ('async ' if asynchronous else '') + 'fn ' + symbol + '(' + ', '.join(declarations) + ') -> ' + result + ' {')
            lines.append('        let result = ' + path + '::' + symbol + '(' + ', '.join(arguments) + ')' + ('.await' if asynchronous else '') + ';')
            lines.append('        latent::rust_http_retirement::owner::drain();')
            lines.extend(('        result', '    }'))
            calls.append({'interface': identity, 'function': name, 'asyncPublic': asynchronous,
                'drainBeforeReturningValueOrError': True})
        lines.append('}')
    lines.append('export!(Root);')
    source = ('\n'.join(lines) + '\n').encode()
    if len(source) > 128*1024:
        raise ValueError('rust-http-root-source-bound')
    return source, calls


def forwarding_wit(canonical: str, graph: dict) -> bytes:
    """Replace only the encoder's one root world; retain all nominal packages."""
    if len(canonical.encode()) > 4*1024*1024 or 'latent:rust-http-retirement' in canonical:
        raise ValueError('rust-http-root-reserved-source-or-bound')
    if len(graph['worlds']) != 1:
        raise ValueError('rust-http-root-world-count')
    world = graph['worlds'][0]['name']
    openings = list(re.finditer(r'(?m)^world ' + re.escape(world) + r' \{', canonical))
    if len(openings) != 1:
        raise ValueError('rust-http-root-canonical-world')
    opening = openings[0]
    closing = canonical.find('\n}', opening.end())
    if closing < 0 or '{' in canonical[opening.end():closing] or '}' in canonical[opening.end():closing]:
        raise ValueError('rust-http-root-inline-world-item-unsupported')
    exports = sorted(profile.names(graph, 'exports'))
    for identity in exports:
        if re.fullmatch(r'[a-z][a-z0-9-]*:[a-z][a-z0-9-]*/[a-z][a-z0-9-]*@[0-9]+\.[0-9]+\.[0-9]+', identity) is None:
            raise ValueError('rust-http-root-canonical-interface')
    body = 'world root {\n'
    body += ''.join('  import ' + identity + ';\n' for identity in exports)
    body += '  import ' + profile.RETIREMENT + ';\n'
    body += ''.join('  export ' + identity + ';\n' for identity in exports)
    body += '}'
    private = '\npackage latent:rust-http-retirement@0.1.0 {\n  interface owner {\n    drain: func();\n  }\n}\n'
    return (canonical[:opening.start()] + body + canonical[closing+2:] + private).encode()


def compiler_lock(original: bytes, name: str) -> bytes:
    """Retain the captured wit-bindgen closure and its exact original lock rows.

    The new compiler crate has no application dependency or executable hook.
    Resolution is still offline/locked inside the original compiler namespace;
    retaining a row does not grant execution approval or allow a new download.
    """
    if len(original) > 8*1024*1024 or not re.fullmatch(r'lsf-owned-http-root-[a-f0-9]{16}', name):
        raise ValueError('rust-http-root-lock-input')
    text = original.decode()
    lock = tomllib.loads(text)
    packages = lock.get('package')
    if lock.get('version') != 4 or not isinstance(packages, list) or not 1 <= len(packages) <= 4096:
        raise ValueError('rust-http-root-lock-shape')
    chunks = re.split(r'(?m)^\[\[package\]\]\n', text)
    if len(chunks) != len(packages)+1:
        raise ValueError('rust-http-root-lock-framing')
    rows = {}
    for row, body in zip(packages, chunks[1:]):
        if tomllib.loads('[[package]]\n'+body).get('package') != [row]:
            raise ValueError('rust-http-root-lock-row-framing')
        key = row['name'], row['version'], row.get('source')
        if key in rows or row['name'] == name:
            raise ValueError('rust-http-root-lock-duplicate-or-collision')
        rows[key] = (row, body)
    starts = [key for key in rows if key[:2] == ('wit-bindgen', '0.62.0')]
    if len(starts) != 1:
        raise ValueError('rust-http-root-exact-captured-bindgen-required')
    retained, pending = set(), starts[:]
    while pending:
        key = pending.pop()
        if key in retained:
            continue
        retained.add(key)
        dependencies = rows[key][0].get('dependencies', [])
        if not isinstance(dependencies, list) or len(dependencies) > 256:
            raise ValueError('rust-http-root-lock-dependency-bound')
        for dependency in dependencies:
            if type(dependency) is not str:
                raise ValueError('rust-http-root-lock-dependency')
            match = re.fullmatch(r'([A-Za-z0-9_-]+)(?: ([^ ()]+))?(?: \(([^\n]+)\))?', dependency)
            if match is None:
                raise ValueError('rust-http-root-lock-dependency')
            selected = [candidate for candidate in rows if candidate[0] == match[1]
                and (match[2] is None or candidate[1] == match[2])
                and (match[3] is None or candidate[2] == match[3])]
            if len(selected) != 1:
                raise ValueError('rust-http-root-lock-missing-or-ambiguous-dependency')
            pending.extend(selected)
    output = chunks[0] + ''.join('[[package]]\n'+body for key, (_row, body) in rows.items() if key in retained)
    output += '\n[[package]]\nname = "'+name+'"\nversion = "0.0.0"\ndependencies = ["wit-bindgen"]\n'
    return output.encode()


def prepare_project(output, canonical: str, graph: dict, lock: bytes):
    from tools.rust_capsule_project import digest, fresh, inventory, write_json
    source, calls = forwarding_source(graph)
    name = 'lsf-owned-http-root-' + digest(source)[7:23]
    files = {
        'src/lib.rs': source,
        'wit/world.wit': forwarding_wit(canonical, graph),
        'Cargo.toml': ('[package]\nname="'+name+'"\nversion="0.0.0"\nedition="2021"\nbuild=false\n'
            '[workspace]\n[lib]\ncrate-type=["cdylib"]\n[dependencies]\nwit-bindgen="=0.62.0"\n'
            '[profile.release]\npanic="abort"\nlto=true\ncodegen-units=1\n').encode(),
        'Cargo.lock': compiler_lock(lock, name),
    }
    output = fresh(output)
    for path, body in files.items():
        destination = output/path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
    record = {'schemaVersion': 'latent.rust.http.compiler-root-source.v1',
        'name': name, 'files': json.loads(inventory(files)),
        'originalCapturedCargoLock': digest(lock), 'calls': calls,
        'publicResultPreserved': True, 'applicationSourceRewritten': False,
        'privateCallingConvention': 'sync-core-to-async-component-projection',
        'executionQualification': False}
    write_json(output/'source-proof.json', record)
    return output, record, files
