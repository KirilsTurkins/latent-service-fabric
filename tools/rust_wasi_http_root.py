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


def selected_contract(graph: dict) -> list[dict]:
    """The explicit selected public contract must permit real blocking.

    This checks actual component function types. It never upgrades a user's
    synchronous contract merely because its implementation makes HTTP calls.
    """
    exports = profile.names(graph, 'exports')
    if not exports or len(exports) > 32:
        raise ValueError('rust-http-selected-export-count')
    selected = []
    for identity, interface in sorted(exports.items()):
        functions = interface['functions']
        if not functions or len(functions) > 128 or len(selected) + len(functions) > 128:
            raise ValueError('rust-http-selected-function-count')
        for name, function in functions.items():
            if function.get('name') != name or function['kind'] != 'async-freestanding':
                raise ValueError('rust-http-selected-explicit-async-export-required')
            selected.append({'interface': identity, 'function': name, 'kind': function['kind']})
    return selected


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


BINDGEN_OPTIONS = {'0.62.0': 'async: false', '0.63.0': 'sync: true'}


def selected_bindgen(lock: bytes) -> str:
    if len(lock) > 8 * 1024 * 1024:
        raise ValueError('rust-http-root-lock-input')
    versions = [row['version'] for row in tomllib.loads(lock.decode()).get('package', [])
                if row.get('name') == 'wit-bindgen']
    if len(versions) != 1 or versions[0] not in BINDGEN_OPTIONS:
        raise ValueError('rust-http-root-exact-captured-bindgen-required')
    return versions[0]


def forwarding_source(graph: dict, *, bindgen_version: str = '0.63.0') -> tuple[bytes, list[dict]]:
    if bindgen_version not in BINDGEN_OPTIONS:
        raise ValueError('rust-http-root-exact-captured-bindgen-required')
    option = BINDGEN_OPTIONS[bindgen_version]
    exports = profile.names(graph, 'exports')
    if not exports or len(exports) > 32 or profile.RETIREMENT in exports:
        raise ValueError('rust-http-root-export-count')
    lines = [
        '#![cfg(target_arch = "wasm32")]',
        'wit_bindgen::generate!({ path: "wit", world: "root", '+option+' });',
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
            # The pinned generator's normal override selects the sync Core ABI
            # while retaining the explicit async WIT function types. No Rust
            # executor or future is injected into the ordinary call body.
            lines.append('    fn ' + symbol + '(' + ', '.join(declarations) + ') -> ' + result + ' {')
            lines.append('        let result = ' + path + '::' + symbol + '(' + ', '.join(arguments) + ');')
            lines.append('        latent::rust_http_retirement::owner::drain();')
            lines.extend(('        result', '    }'))
            calls.append({'interface': identity, 'function': name, 'asyncPublic': asynchronous,
                'drainBeforeReturningValueOrError': True})
        lines.append('}')
    mappings = ', '.join(json.dumps(name)+': generate'
        for name in sorted({*exports, profile.RETIREMENT}))
    lines[1] = 'wit_bindgen::generate!({ path: "wit", world: "root", '+option+', with: { '+mappings+' } });'
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
    starts = [key for key in rows if key[0] == 'wit-bindgen' and key[1] == selected_bindgen(original)]
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


def normalized_lock(projected: bytes, normalized: bytes, name: str) -> dict:
    """Permit Cargo's feature pruning, with no new package identity or edge."""
    from tools.rust_capsule_project import digest
    if type(name) is not str or re.fullmatch(r'lsf-owned-http-root-[a-f0-9]{16}', name) is None:
        raise ValueError('rust-http-root-normalized-generated-root-name')

    def rows(raw):
        if len(raw) > 8*1024*1024:
            raise ValueError('rust-http-root-normalized-lock-bound')
        value = tomllib.loads(raw.decode())
        if set(value) != {'version', 'package'} or value['version'] != 4 or not isinstance(value['package'], list):
            raise ValueError('rust-http-root-normalized-lock-shape')
        if not 1 <= len(value['package']) <= 4096:
            raise ValueError('rust-http-root-normalized-package-bound')
        result, indexed, edge_count = {}, {}, 0
        for row in value['package']:
            if (not isinstance(row, dict) or not {'name', 'version'} <= set(row)
                    or set(row) - {'name', 'version', 'source', 'checksum', 'dependencies'}
                    or any(type(row.get(k)) is not str or not 1 <= len(row[k]) <= 128
                        for k in ('name', 'version'))
                    or re.fullmatch(r'[A-Za-z0-9_-]+', row['name']) is None
                    or any(type(row[k]) is not str or not 1 <= len(row[k]) <= 4096
                        for k in ('source', 'checksum') if k in row)):
                raise ValueError('rust-http-root-normalized-package-shape')
            key = row['name'], row['version'], row.get('source')
            deps = row.get('dependencies', [])
            if (key in result or not isinstance(deps, list) or len(deps) > 256
                    or any(type(d) is not str or len(d) > 4096 for d in deps)
                    or len(set(deps)) != len(deps)):
                raise ValueError('rust-http-root-normalized-package-duplicate-or-dependencies')
            edge_count += len(deps)
            if edge_count > 65536:
                raise ValueError('rust-http-root-normalized-edge-bound')
            result[key] = row
            indexed.setdefault(row['name'], []).append(key)
        return result, indexed

    remaining_work = [262144]

    def edges(row, indexed):
        result = set()
        for dependency in row.get('dependencies', []):
            match = re.fullmatch(r'([A-Za-z0-9_-]+)(?: ([^ ()]+))?(?: \(([^\n]+)\))?', dependency)
            if match is None:
                raise ValueError('rust-http-root-normalized-dependency-shape')
            candidates = indexed.get(match[1], ())
            remaining_work[0] -= len(candidates) + 1
            if remaining_work[0] < 0:
                raise ValueError('rust-http-root-normalized-resolution-work-bound')
            selected = [key for key in candidates
                if (match[2] is None or key[1] == match[2])
                and (match[3] is None or key[2] == match[3])]
            if len(selected) != 1:
                raise ValueError('rust-http-root-normalized-dependency-ambiguous-or-missing')
            result.add(selected[0])
        return result

    before, before_index = rows(projected)
    after, after_index = rows(normalized)
    own = (name, '0.0.0', None)
    starts = [key for key in before if key[0] == 'wit-bindgen' and key[1] == selected_bindgen(projected)]
    if (len(starts) != 1 or own not in before or own not in after
            or before[own] != {'name': name, 'version': '0.0.0', 'dependencies': ['wit-bindgen']}
            or after[own] != before[own] or not set(after) <= set(before)):
        raise ValueError('rust-http-root-normalized-exact-generated-root-and-captured-packages')
    removed_edges = 0
    old_edges = {key: edges(row, before_index) for key, row in before.items()}
    new_edges = {key: edges(row, after_index) for key, row in after.items()}
    for key, row in after.items():
        original = before[key]
        if {k: v for k, v in row.items() if k != 'dependencies'} != {
                k: v for k, v in original.items() if k != 'dependencies'}:
            raise ValueError('rust-http-root-normalized-package-identity-drift')
        old, new = old_edges[key], new_edges[key]
        if not new <= old:
            raise ValueError('rust-http-root-normalized-new-dependency-edge')
        removed_edges += len(old - new)
    if new_edges[own] != set(starts):
        raise ValueError('rust-http-root-normalized-exact-bindgen-dependency')
    reached, pending = set(), [own]
    while pending:
        key = pending.pop()
        if key not in reached:
            reached.add(key)
            pending.extend(new_edges[key])
    if reached != set(after):
        raise ValueError('rust-http-root-normalized-unreachable-package')
    return {'projectedLockDigest': digest(projected), 'normalizedLockDigest': digest(normalized),
        'originalPackageCount': len(before), 'normalizedPackageCount': len(after),
        'removedDependencyEdges': removed_edges, 'newPackageIdentities': 0,
        'changedPackageSourceOrChecksums': 0, 'newDependencyEdges': 0,
        'networkResolution': False, 'buildScriptsExecuted': False, 'compilation': False}


def prepare_project(output, canonical: str, graph: dict, lock: bytes):
    from tools.rust_capsule_project import digest, fresh, inventory, write_json
    version = selected_bindgen(lock)
    source, calls = forwarding_source(graph, bindgen_version=version)
    name = 'lsf-owned-http-root-' + digest(source)[7:23]
    files = {
        'src/lib.rs': source,
        'wit/world.wit': forwarding_wit(canonical, graph),
        'Cargo.toml': ('[package]\nname="'+name+'"\nversion="0.0.0"\nedition="2021"\nbuild=false\n'
            '[workspace]\n[lib]\ncrate-type=["cdylib"]\n[dependencies]\nwit-bindgen="=' + version + '"\n'
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
        'rustBindingsAsync': False, 'publicContractKindsPreserved': True,
        'privateCallingConvention': 'sync-core-to-async-component-projection',
        'executionQualification': False}
    write_json(output/'source-proof.json', record)
    return output, record, files
