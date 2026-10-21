"""Exact internal stackful projection, retaining every compiled core byte.

The original .NET projection/parser remains unchanged. Its bounded component
parser, type comparator and lossless module container are reused as primitives;
this separate caller selects only the eight WASI 0.2.12 operations or the one
compiler-private root drain. No public application function is projected.
"""
from __future__ import annotations

import copy
from pathlib import Path
import re
import time

from tools.dotnet_guest import internal_io as binary
from tools import rust_wasi_http_profile as profile
from tools.rust_capsule_project import decode_json, digest, read_file, write_json


def projection(original: dict, adapter: dict, targets: dict) -> tuple[dict, dict]:
    if targets not in (profile.ASYNC, {profile.RETIREMENT: frozenset({'drain'})}):
        raise ValueError('rust-http-private-projection-targets')
    expected = copy.deepcopy(original)
    imports = binary.functions(expected, 'imports')
    supplied = binary.functions(adapter, 'exports')
    selected = {}
    for identity, names in targets.items():
        for name in sorted(names & imports.get(identity, {}).keys()):
            source = imports[identity][name]
            candidate = supplied.get(identity, {}).get(name)
            if candidate is None or profile.shape(expected, source) != profile.shape(adapter, candidate):
                raise ValueError('rust-http-private-projection-function-shape:' + identity + '#' + name)
            kind = source['kind']
            if kind == 'freestanding':
                source['kind'] = 'async-freestanding'
            elif isinstance(kind, dict) and set(kind) == {'method'}:
                source['kind'] = {'async-method': kind['method']}
            else:
                raise ValueError('rust-http-private-projection-preimage-kind')
            actual = candidate['kind']
            if not (actual == 'async-freestanding' or isinstance(actual, dict) and set(actual) == {'async-method'}):
                raise ValueError('rust-http-private-projection-adapter-must-be-async')
            selected.setdefault(identity, []).append(name)
    if targets != profile.ASYNC and selected != {profile.RETIREMENT: ['drain']}:
        raise ValueError('rust-http-private-root-edge-missing')
    return expected, selected


def prepare(commands, wasm: Path, raw: Path, adapter: Path, output: Path, original: dict, *, root=False):
    if type(root) is not bool:
        raise ValueError('rust-http-private-projection-selector')
    raw_graph = commands.run('rust-http-projection-original-wit', wasm, 'component', 'wit', raw, '--json')
    if decode_json(raw_graph) != original:
        raise ValueError('rust-http-private-stale-original-inspection')
    adapter_bytes = read_file(adapter, binary.MAX_BINARY)
    adapter_raw = commands.run('rust-http-projection-adapter-wit', wasm, 'component', 'wit', adapter, '--json')
    if len(adapter_raw) > binary.MAX_TEXT or len(raw_graph) > binary.MAX_TEXT:
        raise ValueError('rust-http-private-projection-graph-bound')
    targets = {profile.RETIREMENT: frozenset({'drain'})} if root else profile.ASYNC
    expected, selected = projection(original, decode_json(adapter_raw), targets)
    if not selected:
        return raw, None
    original_bytes = read_file(raw, binary.MAX_BINARY)
    output.mkdir()
    before = binary.core_modules(original_bytes)
    if not before or len(before) > 64:
        raise ValueError('rust-http-private-projection-core-count')
    commands.run('rust-http-projection-unbundle', wasm, 'component', 'unbundle', raw,
        '--module-dir', output/'modules', '--threshold', '0', '-o', output/'unbundled.wasm')
    modules = {}
    for path in sorted((output/'modules').iterdir()):
        if not re.fullmatch(r'unbundled-module[0-9]+\.wasm', path.name):
            raise ValueError('rust-http-private-projection-module-name')
        modules[path.stem] = read_file(path, binary.MAX_BINARY)
    if sorted(before) != sorted(modules.values()):
        raise ValueError('rust-http-private-projection-unbundle-core-drift')
    commands.run('rust-http-projection-print', wasm, 'print', '--name-unnamed',
        output/'unbundled.wasm', '-o', output/'unbundled.wat')
    if time.monotonic() >= commands.deadline:
        raise ValueError('rust-http-private-projection-original-deadline')
    text = binary.adapted_text(binary.named_export_syntax(
        read_file(output/'unbundled.wat', binary.MAX_TEXT).decode()), selected)
    (output/'selected.wat').write_text(text, encoding='utf8', newline='\n')
    commands.run('rust-http-projection-encode', wasm, 'parse', output/'selected.wat',
        '-o', output/'unbundled-selected.wasm')
    component = output/'selected.wasm'
    component.write_bytes(binary.rebundle(read_file(output/'unbundled-selected.wasm', binary.MAX_BINARY), modules))
    commands.run('rust-http-projection-validate', wasm, 'validate', '--features', 'all', component)
    after = commands.run('rust-http-projection-selected-wit', wasm, 'component', 'wit', component, '--json')
    if len(after) > binary.MAX_TEXT or expected != decode_json(after):
        raise ValueError('rust-http-private-projection-changed-other-types')
    if sorted(before) != sorted(binary.core_modules(read_file(component, binary.MAX_BINARY))):
        raise ValueError('rust-http-private-projection-core-byte-drift')
    if read_file(raw, binary.MAX_BINARY) != original_bytes or read_file(adapter, binary.MAX_BINARY) != adapter_bytes:
        raise ValueError('rust-http-private-projection-original-changed')
    record = {'schemaVersion': 'latent.rust.http.private-projection.v1',
        'root': root, 'functions': selected,
        'originalDigest': digest(original_bytes), 'selectedDigest': digest(read_file(component, binary.MAX_BINARY)),
        'adapterDigest': digest(adapter_bytes), 'coreBytesUnchanged': True,
        'publicApplicationGraphUnchanged': True,
        'cores': [{'sha256': digest(body), 'bytes': len(body)} for body in before],
        'runtimeQualification': False}
    write_json(output/'projection.json', record)
    return component, record
