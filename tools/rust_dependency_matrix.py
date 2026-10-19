"""Unknown Cargo coordinates and ordinary no_std/alloc/std dependency calls.

This module prepares finite test sources and checks observations. It neither
resolves packages nor authorizes executable inputs on behalf of an application.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil

from tools.build_snapshot import canonical, digest
from tools.phase2_operator_process import require
from tools.rust_capsule_node import assert_value, call, provider_idle, sample
from tools.rust_capsule_project import read_file, snapshot

PREFIX = 'dependency-matrix:'
INPUTS = ('A\u03a99', '\u00fc\u0301', 'A\u03a99')


def specification(nonce: str, graph: int, phase: int) -> dict:
    require(isinstance(nonce, str) and re.fullmatch(r'[0-9a-f]{24}', nonce) is not None
            and type(graph) is int and graph in (0, 1) and type(phase) is int and phase in (0, 1),
            'matrix-specification-invalid')
    prefix = f'outside-matrix-{nonce}-{graph}'
    return {'formatVersion': 1, 'nonce': nonce, 'graph': graph, 'phase': phase,
            'packages': {role: prefix + '-' + role for role in ('core', 'allocated', 'facade', 'native')},
            'version': f'0.{1 + int(nonce[:4], 16)}.{graph + 1}',
            'marker': [int(nonce[index:index + 2], 16) for index in (0, 2, 4)] + [graph, phase, 255],
            'selection': {'features': ['switched'] if phase else [], 'allFeatures': False,
                          'noDefaultFeatures': bool(phase)}}


def validate(value: dict) -> dict:
    require(isinstance(value, dict) and set(value) == set(specification('0' * 24, 0, 0)),
            'matrix-specification-invalid')
    require(canonical(value) == canonical(specification(value['nonce'], value['graph'], value['phase'])),
            'matrix-specification-invalid')
    return value


def sources(value: dict) -> dict[str, bytes]:
    value = validate(value)
    names, version = value['packages'], value['version']
    def package(role):
        return f'[package]\nname = "{names[role]}"\nversion = "{version}"\nedition = "2021"\nlicense = "Apache-2.0"\n'
    files = {}
    for phase in (0, 1):
        marker = specification(value['nonce'], value['graph'], phase)['marker']
        files[f'patch-{phase}/Cargo.toml'] = package('core').encode()
        files[f'patch-{phase}/src/lib.rs'] = (b'#![no_std]\n'
            b'pub fn value() -> u32 { include_bytes!("marker.bin").iter().map(|v| u32::from(*v)).sum() }\n')
        files[f'patch-{phase}/src/marker.bin'] = bytes(marker)
    files['allocated/Cargo.toml'] = (package('allocated') + '[dependencies]\n'
        + names['core'] + f' = "={version}"\n').encode()
    core = names['core'].replace('-', '_')
    files['allocated/src/lib.rs'] = ('#![no_std]\nextern crate alloc;\n'
        'use alloc::vec::Vec;\npub fn describe(text: &str) -> alloc::string::String {\n'
        '    let bytes: Vec<u8> = text.bytes().rev().collect();\n'
        f'    alloc::format!("sum={{}};bytes={{}};chars={{}}", {core}::value(), '
        'bytes.iter().map(|v| u32::from(*v)).sum::<u32>(), text.chars().count())\n}\n').encode()
    files['native/Cargo.toml'] = package('native').encode()
    files['native/src/lib.rs'] = b'#![no_std]\npub fn value() -> u32 { 199 }\n'
    files['facade/Cargo.toml'] = (package('facade') + '[features]\ndefault = ["baseline"]\nbaseline = []\nalternate = []\n'
        + '[target.\'cfg(target_arch = "wasm32")\'.dependencies]\n'
        + names['allocated'] + f' = {{path = "../allocated", version = "={version}"}}\n'
        + '[target.\'cfg(not(target_arch = "wasm32"))\'.dependencies]\n'
        + names['native'] + f' = {{path = "../native", version = "={version}"}}\n').encode()
    allocated, native = (names[role].replace('-', '_') for role in ('allocated', 'native'))
    files['facade/src/lib.rs'] = ('use std::sync::atomic::{AtomicU32, Ordering};\n'
        'static CALLS: AtomicU32 = AtomicU32::new(0);\n'
        'pub fn describe(text: &str) -> String {\n'
        '    assert_eq!(CALLS.fetch_add(1, Ordering::SeqCst), 0, "activation state reused");\n'
        '    #[cfg(target_arch = "wasm32")]\n'
        f'    let selected = {allocated}::describe(text);\n'
        '    #[cfg(not(target_arch = "wasm32"))]\n'
        f'    let selected = format!("native={{}}", {native}::value());\n'
        '    format!("{}|{}|{}|default={}|alternate={}", include_str!("label.txt"), selected,\n'
        '            include_str!("utf8.txt"), cfg!(feature = "baseline"), cfg!(feature = "alternate"))\n}\n').encode()
    files['facade/src/label.txt'] = (value['nonce'] + ':' + value['version']).encode()
    files['facade/src/utf8.txt'] = 'Gr\u00fc\u00dfe'.encode()
    return files


def restore(outside: Path, value: dict) -> dict:
    """Explicit native authoring needs manifests; ordinary builds do not."""
    expected = sources(value)
    outside.mkdir(mode=0o700)
    for name, raw in expected.items():
        target = outside / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(raw)
    (outside / 'owner.json').write_bytes(canonical({'nonce': value['nonce'], 'graph': value['graph']}))
    return {name: digest(raw) for name, raw in expected.items()}


def remove(outside: Path, value: dict):
    require(not outside.is_symlink() and outside.resolve(strict=True) == outside.absolute()
            and json.loads(read_file(outside / 'owner.json', 1024)) == {'nonce': value['nonce'], 'graph': value['graph']}
            and snapshot(outside) == {**sources(value), 'owner.json': canonical({'nonce': value['nonce'], 'graph': value['graph']})},
            'matrix-original-source-owner-mismatch')
    shutil.rmtree(outside)
    require(not outside.exists(), 'matrix-original-sources-still-present')


def edit(project: Path, outside: Path, value: dict):
    value = validate(value)
    manifest = read_file(project / 'Cargo.toml')
    name = value['packages']['core']
    patch = ('\n[patch.crates-io]\n' + name + ' = {path = '
             + json.dumps((outside / ('patch-' + str(value['phase']))).as_posix()) + '}\n').encode()
    if value['phase'] == 0:
        require(b'[patch.' not in manifest and b'[features]' not in manifest, 'matrix-original-manifest-required')
        manifest += b'\n[features]\ndefault = ["matrix-default"]\nmatrix-default = []\nswitched = []\n' + patch
        source = read_file(project / 'src/lib.rs')
        hook = b'Ok(format!("Hello, {name}!"))'
        require(source.count(hook) == 1, 'matrix-original-greeting-required')
        facade = value['packages']['facade'].replace('-', '_')
        source = source.replace(hook, ('if let Some(text) = name.strip_prefix("' + PREFIX + '") {\n'
            '        return Ok(format!("{}|root-default={}|root-switched={}", '
            + facade + '::describe(text), cfg!(feature="matrix-default"), cfg!(feature="switched")));\n'
            '    }\n    ').encode() + hook)
        (project / 'src/lib.rs').write_bytes(source)
    else:
        original = ('\n[patch.crates-io]\n' + name + ' = {path = '
                    + json.dumps((outside / 'patch-0').as_posix()) + '}\n').encode()
        require(manifest.count(original) == 1, 'matrix-original-patch-required')
        manifest = manifest.replace(original, patch)
    (project / 'Cargo.toml').write_bytes(manifest)


def expected(value: dict, text: str) -> str:
    value = validate(value)
    phase = bool(value['phase'])
    return (f"{value['nonce']}:{value['version']}|sum={sum(value['marker'])};bytes={sum(text.encode())};chars={len(text)}"
            f"|Gr\u00fc\u00dfe|default={str(not phase).lower()}|alternate={str(phase).lower()}"
            f"|root-default={str(not phase).lower()}|root-switched={str(phase).lower()}")


def captured(lock: dict, graph: dict, value: dict) -> dict:
    """Require actual selected features, target pruning and the replaced leaf."""
    value = validate(value)
    require(not lock['executableInputs'] and all(lock['selection'].get(key) == selected
            for key, selected in value['selection'].items())
            and lock['selection'].get('target') == 'wasm32-unknown-unknown'
            and lock['selection'].get('runtimeProfile') == 'wasm32-unknown-unknown-panic-abort-v1',
            'matrix-selection-not-observed')
    found = {}
    for role, name in value['packages'].items():
        rows = [row for row in lock['artifacts'] if row['role'] == 'application'
                and row.get('metadata', {}).get('package') == name and row['metadata'].get('version') == value['version']]
        require(len(rows) == 1, 'matrix-actual-package-required')
        found[role] = rows[0]
    nodes = {node['id']: node for node in graph['nodes']}
    selected = graph['selectedResolve']['nodes']
    selected_ids = {node['id'] for node in selected}
    ids = {}
    for role, row in found.items():
        matches = [node for node in nodes.values() if node.get('artifact') == row['id']]
        require(len(matches) == 1, 'matrix-package-graph-identity-required')
        ids[role] = matches[0]['id']
        directory = 'patch-' + str(value['phase']) if role == 'core' else role
        for name, raw in sources(value).items():
            if name.startswith(directory + '/src/'):
                relative = name.removeprefix(directory + '/')
                require([item for item in row['files'] if item['path'] == relative]
                        == [{'path': relative, 'digest': digest(raw), 'size': len(raw)}],
                        'matrix-captured-source-or-resource-mismatch')
    require(ids['native'] not in selected_ids and all(ids[role] in selected_ids for role in ('core', 'allocated', 'facade')),
            'matrix-wasm-target-pruning-required')
    facade = next(node for node in selected if node['id'] == ids['facade'])
    require(set(facade['features']) == ({'alternate'} if value['phase'] else {'default', 'baseline'}),
            'matrix-dependency-features-not-observed')
    root = next(node for node in selected if node['id'] == graph['root'])
    require(set(root['features']) == ({'switched'} if value['phase'] else {'default', 'matrix-default'}),
            'matrix-root-features-not-observed')
    require(found['allocated']['id'] in found['facade']['dependencies']
            and found['core']['id'] in found['allocated']['dependencies']
            and ids['facade'] in {edge['pkg'] for edge in root['deps']}, 'matrix-transitive-edges-not-observed')
    return {role: {'artifact': row['id'], 'treeDigest': row['treeDigest']} for role, row in found.items()}


def probe(client, target, ownership_probe, result, population, value):
    value = validate(value)
    cases = []
    for index, text in enumerate(INPUTS):
        row = call(client, target, 'greeting', 'greet', [PREFIX + text], 'rust-matrix-' + str(index))
        result['invocations'].append(row)
        answer = expected(value, text)
        assert_value(client, row, [{'ok': answer}])
        revision = row['response']['data'].get('resolvedRevision')
        require(row['processReaped'] and isinstance(revision, dict)
                and revision.get('publicationId') == target['publication']
                and revision.get('routeGeneration') == str(target['generation'])
                and int(row['response']['data']['consumption']['outboundRequests']) == 0,
                'matrix-invocation-revision-or-ownership-mismatch')
        result['samples'].append(sample(client, ownership_probe, 'after-rust-matrix-' + str(index), population))
        result['providerIdle'].append(provider_idle(client))
        cases.append({'inputDigest': digest(text.encode()), 'resultDigest': digest(answer.encode())})
    result['rustDependencyMatrix'] = {'status': 'passed', 'specificationDigest': digest(canonical(value)),
        'cases': cases, 'scope': 'captured no_std core, alloc transitive, std facade, features and resources; fresh warm repeat'}
