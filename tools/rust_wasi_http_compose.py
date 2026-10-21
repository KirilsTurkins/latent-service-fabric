"""Compose one selected backend and an owned root without library rewrites."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from tools import rust_wasi_http_profile as profile
from tools import rust_wasi_http_io as io
from tools import rust_wasi_http_root as root
from tools.dotnet_guest.internal_io import core_modules
from tools.rust_capsule_project import decode_json, digest, inventory, read_file, snapshot, write_json

MAX_COMPONENT = 64*1024*1024
MAX_GRAPH = 4*1024*1024


def graph(commands, wasm, component, stage):
    raw = commands.run(stage, wasm, 'component', 'wit', component, '--json')
    if len(raw) > MAX_GRAPH:
        raise ValueError('rust-http-composition-graph-bound')
    return decode_json(raw)


def unchanged_exports(original: dict, final: dict):
    before, after = profile.names(original, 'exports'), profile.names(final, 'exports')
    if before.keys() != after.keys():
        raise ValueError('rust-http-composition-public-export-set')
    for name in before:
        left, right = before[name], after[name]
        if left['types'].keys() != right['types'].keys() or left['functions'].keys() != right['functions'].keys():
            raise ValueError('rust-http-composition-public-interface-shape')
        for function, row in left['functions'].items():
            candidate = right['functions'][function]
            if row['kind'] != candidate['kind'] or profile.shape(original, row) != profile.shape(final, candidate):
                raise ValueError('rust-http-composition-public-function-changed')
        for member, index in left['types'].items():
            if profile.shape(original, index, type_index=True) != profile.shape(final, right['types'][member], type_index=True):
                raise ValueError('rust-http-composition-public-type-changed')


def compose(commands, tools: dict, component: Path, public_surface: dict, prepared,
            work: Path, *, isolation, environment_guard):
    if isolation is None or environment_guard is None:
        raise ValueError('rust-http-requires-captured-compiler-namespace')
    prepared.check()
    before_component = read_file(component, MAX_COMPONENT)
    original = graph(commands, tools['wasm-tools'], component, 'rust-http-original-graph')
    imported = profile.names(original, 'imports')
    if not profile.select(list(public_surface['imports']), list(imported)):
        raise ValueError('rust-http-selected-runtime-without-ordinary-client')
    canonical = commands.run('rust-http-original-canonical-wit', tools['wasm-tools'],
        'component', 'wit', component, '--no-docs').decode()
    if len(canonical.encode()) > MAX_GRAPH:
        raise ValueError('rust-http-original-canonical-bound')
    output = commands.output
    directory = work.parent/'rust-http-composition'
    directory.mkdir()
    raw = directory/'application-original.wasm'
    raw.write_bytes(before_component)
    projected, io_record = io.prepare(commands, tools['wasm-tools'], raw,
        prepared.adapter, directory/'application-io', original)
    if io_record is None:
        raise ValueError('rust-http-original-blocking-io-missing')
    forward, root_record, root_files = root.prepare_project(directory/'root-source', canonical,
        original, read_file(work/'Cargo.lock', 8*1024*1024))
    # The captured application's feature union can retain dependency edges that
    # this smaller compiler-owned crate does not enable. Let Cargo normalize
    # only metadata in the same offline captured namespace, then reject any
    # package/identity/edge expansion before protecting the final build inputs.
    original_proof = read_file(forward/'source-proof.json')
    for name in root_files:
        if name != 'Cargo.lock':
            isolation.protect_inputs(forward/name)
    environment_guard.check_unchanged(commands.environment)
    metadata = isolation.wrap(tools['cargo'], ['metadata', '--offline', '--format-version', '1',
        '--manifest-path', str(forward/'Cargo.toml')], forward, commands.environment)
    commands.run('rust-http-compiler-root-normalize-lock', *metadata)
    environment_guard.check_unchanged(commands.environment)
    normalized = read_file(forward/'Cargo.lock', 8*1024*1024)
    lock_record = root.normalized_lock(root_files['Cargo.lock'], normalized, root_record['name'])
    if (read_file(forward/'source-proof.json') != original_proof
            or any(read_file(forward/name) != body for name, body in root_files.items() if name != 'Cargo.lock')
            or set(snapshot(forward)) != {*root_files, 'source-proof.json'}):
        raise ValueError('rust-http-compiler-root-normalization-mutated-source')
    write_json(output/'rust-http-root-locks.json', {'originalCapturedLockDigest': root_record['originalCapturedCargoLock'],
        'projected': root_files['Cargo.lock'].decode(), 'normalized': normalized.decode(), 'validation': lock_record})
    root_files['Cargo.lock'] = normalized
    root_record['files'] = decode_json(inventory(root_files))
    root_record['lockNormalization'] = lock_record
    # This fresh owned proof is the only explicitly updated generated document;
    # its preimage was checked above and both lock preimages are retained.
    (forward/'source-proof.json').write_bytes((json.dumps(root_record, indent=2, ensure_ascii=False)+'\n').encode())
    isolation.protect_inputs(forward)
    environment_guard.check_unchanged(commands.environment)
    wrapped = isolation.wrap(tools['cargo'], ['build', '--locked', '--offline', '--release',
        '--lib', '--target', 'wasm32-unknown-unknown', '--manifest-path', str(forward/'Cargo.toml')],
        forward, commands.environment)
    commands.run('rust-http-compiler-root-compile', *wrapped)
    environment_guard.check_unchanged(commands.environment)
    if snapshot(forward) != {**root_files, 'source-proof.json': read_file(forward/'source-proof.json')}:
        raise ValueError('rust-http-compiler-root-source-mutated')
    if decode_json(read_file(forward/'source-proof.json')) != root_record:
        raise ValueError('rust-http-compiler-root-proof-mutated')
    target = Path(commands.environment['CARGO_TARGET_DIR'])
    module = target/'wasm32-unknown-unknown/release'/(root_record['name'].replace('-', '_')+'.wasm')
    raw_root = directory/'root-original.wasm'
    commands.run('rust-http-compiler-root-component', tools['wasm-tools'], 'component', 'new',
        module, '-o', raw_root)
    root_graph = graph(commands, tools['wasm-tools'], raw_root, 'rust-http-compiler-root-graph')
    unchanged_exports(original, root_graph)
    if set(profile.names(root_graph, 'imports')) != set(profile.names(original, 'exports')) | {profile.RETIREMENT}:
        raise ValueError('rust-http-compiler-root-import-set')
    selected_root, root_io_record = io.prepare(commands, tools['wasm-tools'], raw_root,
        prepared.adapter, directory/'root-io', root_graph, root=True)
    # Each nominal interface is wired by its exact name. WAC must validate all
    # actual resource aliases and signatures; no semver plug/rename is used.
    lines = ['package lsf:rust-http-composition;', 'let runtime = new lsf:runtime { ... };',
        'let application = new lsf:application {']
    lines.extend('  '+json.dumps(name)+': runtime['+json.dumps(name)+'],' for name in sorted(profile.EXTERNAL))
    lines.extend(['  ...', '};', 'let root = new lsf:root {'])
    lines.extend('  '+json.dumps(name)+': application['+json.dumps(name)+'],'
        for name in sorted(profile.names(original, 'exports')))
    lines.append('  '+json.dumps(profile.RETIREMENT)+': runtime['+json.dumps(profile.RETIREMENT)+'],')
    lines.extend(['};', 'export root...;'])
    source = ('\n'.join(lines)+'\n').encode()
    if len(source) > 65536:
        raise ValueError('rust-http-composition-source-bound')
    script = directory/'composition.wac'
    script.write_bytes(source)
    dependencies = directory/'dependencies'
    dependencies.mkdir()
    isolation.protect_inputs(script, projected, selected_root)
    selected = directory/'selected.wasm'
    commands.run('rust-http-exact-composition', prepared.composer, 'compose', script,
        '--deps-dir', dependencies, '--dep', 'lsf:runtime='+str(prepared.adapter),
        '--dep', 'lsf:application='+str(projected), '--dep', 'lsf:root='+str(selected_root), '-o', selected)
    commands.run('rust-http-final-validation', tools['wasm-tools'], 'validate', selected,
        '--features', 'cm-async,cm-async-stackful,cm-more-async-builtins')
    final = graph(commands, tools['wasm-tools'], selected, 'rust-http-final-graph')
    final_imports = set(profile.names(final, 'imports'))
    unchanged_exports(original, final)
    if not final_imports <= set(public_surface['imports']) or not profile.AUTHORITY <= final_imports:
        raise ValueError('rust-http-final-undeclared-or-missing-authority')
    if profile.RETIREMENT in final_imports or any(name.startswith('wasi:') for name in final_imports):
        raise ValueError('rust-http-final-private-or-ambient-import')
    selected_bytes = read_file(selected, MAX_COMPONENT)
    original_cores, final_cores = Counter(core_modules(before_component)), Counter(core_modules(selected_bytes))
    if original_cores - final_cores:
        raise ValueError('rust-http-composition-original-core-bytes-changed')
    prepared.check()
    if read_file(component, MAX_COMPONENT) != before_component or read_file(script, 65536) != source:
        raise ValueError('rust-http-composition-original-input-changed')
    record = {'schemaVersion': 'latent.rust.http.exact-composition.v1', 'profile': profile.PROFILE,
        'originalComponentDigest': digest(before_component), 'selectedComponentDigest': digest(selected_bytes),
        'root': root_record, 'internalIo': io_record, 'privateDrain': root_io_record,
        'source': digest(source), 'originalCoreModulesRetained': len(list(original_cores.elements())),
        'publicGraphUnchanged': True, 'imports': sorted(final_imports),
        'exports': sorted(profile.names(final, 'exports')), 'runtimeReceipt': digest(prepared.material()),
        'librarySourceRewritten': False, 'signedExecutionQualification': False}
    (output/'rust-http-composition.wac').write_bytes(source)
    (output/'rust-http-root-source.json').write_bytes(inventory(root_files))
    (output/'rust-http-runtime.json').write_bytes(prepared.material())
    write_json(output/'rust-http-composition.json', record)
    component.write_bytes(selected_bytes)
    return record
