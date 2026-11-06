"""Assemble a signed-test input from one honestly retained combined compiler event.

The producer failed after successful composition when writing a duplicate
receipt.  This module preserves that failure and publishes a new, explicitly
marked packaging observation; it never claims a completed normal Rust build.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import tarfile
import time

from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import BUILD_TYPE, package_inputs, selected_recipe
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, write_json
from tools import rust_combined_diagnostic_envelope as envelope, rust_original_delta as delta

SOURCE = '7f1a95ef7f2552bb6b0339e3331cf6b25d765127'
RUN, JOB, ARTIFACT = 41926247914, 126911296919, 13371474344
PROFILE = 'rust-context40-combined-http-diagnostic-v1'
PINS = {
    'application-source-and-capture.tar.gz': (27871200, 'bc7438a17b9f61a4e86f473a5d9b8a67ea0bf298c7ff9fd7f1984dbba978048e'),
    'source-inputs.json': (9472, '64496478141f096d8c12032c543b4896aba416908d1bb01221f47aad90e62626'),
    'raw-core.wasm': (1001580, '1fbef671a60b24c5a66b55ecb899d3c3d8e9b45d296a61db22cc69babd1aa96e'),
    'combined-component.wasm': (1281820, '8916f44f9044242b05fe4a438f47082ff7073cfcbf08585b01312c347e338c90'),
    'FAILED.json': (360266, '0f2277e71f3ec0f01e9bd91138ac7809a526a2925691edb80901f6dfe6a26b12'),
    'rust-http-composition.json': (5281, '37458ad7939380789d0f4a51697ba547c567e245aaaf61b62d2c30f83260fcc5'),
}
WRAPPED = {'bytes': 1629518, 'sha256': 'sha256:5634429a97b4a3f0cf8afca2877dbbddbc98f5e4fd7bf59ae6f7f50e780c2e17'}
IMPORTS = ('latent:clock/monotonic@0.1.0', 'latent:http/streaming@0.3.0',
           'latent:runtime-native/threads@0.1.0', 'latent:runtime/activation@0.1.0')
WALL = 'latent:clock/wall@0.1.0'


def original_files(artifact: Path) -> tuple[dict[str, bytes], dict]:
    identities = {}
    for name, (size, sha) in PINS.items():
        actual = file_identity(artifact / name, 32 * 1024 * 1024)
        require(actual == {'bytes': size, 'sha256': 'sha256:' + sha}, 'rust-http-thread-retained-member')
        identities[name] = actual
    expected = read_json(artifact / 'source-inputs.json', 16 * 1024)
    require(type(expected) is dict and len(expected) == 69
            and all(type(name) is str and name and not PurePosixPath(name).is_absolute()
                    and all(part not in ('', '.', '..') for part in PurePosixPath(name).parts)
                    for name in expected), 'rust-http-thread-retained-snapshot-shape')
    files, seen, total = {}, set(), 0
    with tarfile.open(artifact / 'application-source-and-capture.tar.gz', 'r:gz') as archive:
        for ordinal, member in enumerate(archive):
            name = member.name
            require(ordinal < 10215 and member.isfile() and 0 <= member.size <= 4 * 1024 * 1024
                    and name not in seen, 'rust-http-thread-retained-archive-shape')
            seen.add(name)
            total += member.size
            require(total <= 128 * 1024 * 1024, 'rust-http-thread-retained-archive-bound')
            if name in expected:
                payload = archive.extractfile(member).read(member.size + 1)
                require({'size': len(payload), 'digest': digest(payload)} == expected[name],
                        'rust-http-thread-retained-source-identity')
                files[name] = payload
    require(len(seen) == 10215 and total == 133730018 and set(files) == set(expected)
            and inventory(files) == read_file(artifact / 'source-inputs.json', 16 * 1024),
            'rust-http-thread-complete-retained-source')
    return files, identities


def producer(artifact: Path, files: dict[str, bytes]) -> tuple[dict, dict]:
    failure = read_json(artifact / 'FAILED.json', 512 * 1024)
    composition = read_json(artifact / 'rust-http-composition.json', 16 * 1024)
    last = [(item['stage'], item['exitCode']) for item in failure['commands'][-3:]]
    require(failure['schemaVersion'] == 'latent.rust.http-thread-core-observation.v1'
            and failure['status'] == 'failed' and failure['stage'] == 'maintained-http-composition-preview'
            and failure['errorType'] == 'FileExistsError'
            and failure['reason'].endswith('/rust-http-composition.json\'')
            and failure['actualApplicationCoreCompiled'] is True and failure['normalBuildComplete'] is False
            and failure['normalComponentGateRefused'] is True and failure['actualGuestExecuted'] is False
            and failure['capture']['sourceDigest'] == digest(inventory(files))
            and failure['originalCore']['digest'] == 'sha256:' + PINS['raw-core.wasm'][1]
            and last == [('rust-http-exact-composition', 0), ('rust-http-final-validation', 0),
                         ('rust-http-final-graph', 0)], 'rust-http-thread-original-failure-preserved')
    require(composition['selectedComponentDigest'] == 'sha256:' + PINS['combined-component.wasm'][1]
            and composition['publicGraphUnchanged'] is True
            and composition['signedExecutionQualification'] is False
            and set(composition['imports']) == set(IMPORTS)
            and composition['exports'] == ['examples:greeting/api@1.0.0'],
            'rust-http-thread-exact-composed-surface')
    return failure, composition


def projected_source(files: dict[str, bytes]) -> dict[str, bytes]:
    original = files['wit/world.wit']
    line = b'    import latent:clock/wall@0.1.0;\n'
    require(original.count(line) == 1 and b'greet: async func(' in original,
            'rust-http-thread-original-async-wit')
    return {**files, 'wit/world.wit': original.replace(line, b'', 1)}


def framed(artifact: Path, catalogue: Path) -> bytes:
    original = read_file(artifact / 'raw-core.wasm', 1024 * 1024)
    base = read_file(artifact / 'combined-component.wasm', 2 * 1024 * 1024)
    require(base == read_file(catalogue / 'combined-final-component.wasm', 2 * 1024 * 1024)
            and original == read_file(catalogue / 'combined-original-core.wasm', 1024 * 1024),
            'rust-http-thread-merged-graph-origin')
    proof = read_file(catalogue / 'combined-original-delta.bin', 1024 * 1024)
    require(delta.encode(original, base) == proof, 'rust-http-thread-original-delta-origin')
    result = envelope.frame(base, proof)
    require({'bytes': len(result), 'sha256': digest(result)} == WRAPPED,
            'rust-http-thread-exact-wrapped-component')
    return result


def prepare(artifact: Path, native: dict, output: Path, commands) -> dict:
    output = fresh(output)
    started = int(time.time())
    files, identities = original_files(artifact)
    failure, composition = producer(artifact, files)
    source = projected_source(files)
    project = json.loads(files['capsule-project.json'])
    require(project['name'] == 'rust-wasi-http' and project['service'] == 'examples/rust-wasi-http'
            and project['limits']['memoryBytes'] == 16_777_216
            and project['limits']['wallTimeLimitMillis'] == 5000
            and project['limits']['outboundRequests'] == 8
            and project['limits']['cpuFuel'] == 1_000_000_000, 'rust-http-thread-original-project')
    recipe_names = tuple(dict.fromkeys((*selected_recipe(),
        'tools/rust_combined_diagnostic_envelope.py', 'tools/rust_original_delta.py',
        'tools/rust_thread_http_sibling_gate.py', 'tools/rust_thread_http_sibling_node.py',
        'tools/rust_thread_http_combined_package.py', 'tools/rust_thread_http_combined_node.py',
        'tools/rust_combined_http_materials.py', '.github/workflows/rust-combined-signed-witness.yml',
        'tools/qualify_rust_thread_http_combined.py')))
    require(len(recipe_names) <= 256, 'rust-http-thread-assembly-recipe-bound')
    recipe = inventory({name: read_file(ROOT / name, 4 * 1024 * 1024) for name in recipe_names})
    (output / 'recipe-inputs.json').write_bytes(recipe)
    (output / 'source-inputs.json').write_bytes(read_file(artifact / 'source-inputs.json', 16 * 1024))
    (output / 'original-project.json').write_bytes(files['capsule-project.json'])
    (output / 'original-world.wit').write_bytes(files['wit/world.wit'])
    (output / 'retained-compiler-failure.json').write_bytes(read_file(artifact / 'FAILED.json', 512 * 1024))
    (output / 'retained-composition.json').write_bytes(read_file(artifact / 'rust-http-composition.json', 16 * 1024))
    write_json(output / 'wit-inputs.json', {'world': project['world'], 'sources': [
        {'path': name, 'content': data.decode()} for name, data in sorted(source.items())
        if name.startswith('wit/') and name.endswith('.wit')]})
    commands.run('combined-http-contracts', native['capsule_contracts'], output / 'wit-inputs.json', output / 'contracts')
    for name in ('contracts.json', 'wit-lock.json', 'surface.json'):
        (output / name).write_bytes(read_file(output / 'contracts' / name, 4 * 1024 * 1024))
    surface = read_json(output / 'surface.json')
    require(set(surface['imports']) == set(IMPORTS)
            and surface['exports'] == composition['exports'], 'rust-http-thread-projected-surface')
    catalogue = ROOT / 'crates/latent-component-threading/src/rust_catalogue'
    component = framed(artifact, catalogue)
    (output / 'component.wasm').write_bytes(component)
    projection = {'schemaVersion': 'latent.rust.combined-http.diagnostic-projection.v1',
        'compilerSource': SOURCE, 'compilerRun': RUN, 'compilerJob': JOB, 'compilerArtifact': ARTIFACT,
        'compilerRunConclusion': 'failure', 'compilerFailureStage': failure['stage'],
        'compilerFailureReason': failure['reason'], 'compositionAndValidationCommandsSucceeded': True,
        'retainedMembers': identities, 'originalSourceDigest': digest(inventory(files)),
        'originalPublicWitDigest': digest(files['wit/world.wit']),
        'projectedPublicWitDigest': digest(source['wit/world.wit']),
        'omittedSourceImportAbsentFromComposedGraph': WALL, 'finalRequiredImports': list(IMPORTS),
        'componentDigest': digest(component), 'selectedHostProfile': PROFILE,
        'originalLimits': project['limits'], 'applicationRecompiled': False,
        'originalCompilerObservationRewritten': False, 'normalRustBuilderRouteOpened': False,
        'nativeHostMustRecomputeOriginalGraph': True, 'actualGuestExecuted': False,
        'standardRuntimeQualified': False}
    write_json(output / 'qualification-projection.json', projection)
    package_inputs(output, project, surface, source, component, threading_model='cooperative',
        additional_assets=(('qualification-projection.json', 'asset', 'application/vnd.latent.rust-thread-projection.v1+json'),
            ('original-project.json', 'asset', 'application/json'), ('original-world.wit', 'asset', 'application/wasm-wit'),
            ('retained-compiler-failure.json', 'asset', 'application/json'),
            ('retained-composition.json', 'asset', 'application/json')))
    package_files = {'package-source.json': read_file(output / 'package-source.json')}
    for layer in read_json(output / 'package-source.json')['layers']:
        package_files[layer['source']] = read_file(output / layer['source'], 4 * 1024 * 1024)
    package_inventory = inventory(package_files)
    (output / 'package-inputs.json').write_bytes(package_inventory)
    tool_ids = {name: file_identity(native[name]) for name in ('capsule_contracts', 'package')}
    commands.run('combined-http-package', native['package'], 'build', output / 'package-source.json', output, output / 'package')
    commands.run('combined-http-package-inspect', native['package'], 'inspect', output / 'package')
    require(recipe == inventory({name: read_file(ROOT / name, 4 * 1024 * 1024) for name in recipe_names})
            and tool_ids == {name: file_identity(native[name]) for name in tool_ids}
            and package_inventory == inventory({name: read_file(output / name, 4 * 1024 * 1024)
                                                for name in package_files}), 'rust-http-thread-assembly-input-drift')
    materials = [{'name': name, 'digest': digest(data), 'size': len(data)} for name, data in (
        ('source-snapshot', read_file(output / 'source-inputs.json')), ('build-recipe', recipe),
        ('toolchain-config', files['rust-toolchain.toml']), ('dependency-lock', files['Cargo.lock']),
        ('package-inputs', package_inventory), ('retained-compiler-failure', read_file(output / 'retained-compiler-failure.json')),
        ('retained-composition', read_file(output / 'retained-composition.json')),
        ('qualification-projection', read_file(output / 'qualification-projection.json')))]
    materials.append({'name': 'retained-source-and-cas-capture',
        'digest': identities['application-source-and-capture.tar.gz']['sha256'],
        'size': identities['application-source-and-capture.tar.gz']['bytes']})
    retained = [row for row in failure['tools'] if row['name'] in {'cargo', 'rustc', 'wasm-tools', 'wit-bindgen'}]
    require({row['name'] for row in retained} == {'cargo', 'rustc', 'wasm-tools', 'wit-bindgen'} and len(retained) == 4,
            'rust-http-thread-retained-tool-identities')
    materials.extend(retained)
    materials.extend({'name': 'contracts-tool' if name == 'capsule_contracts' else 'packager',
        'digest': item['sha256'], 'size': item['bytes']} for name, item in tool_ids.items())
    finished = int(time.time())
    require(0 <= finished - started <= 600, 'rust-http-thread-assembly-clock-bound')
    observation = {'formatVersion': 1, 'buildType': BUILD_TYPE,
        'source': {'repository': 'https://github.com/KirilsTurkins/latent-service-fabric',
            'revision': digest(inventory(files))[7:], 'snapshotDigest': digest(inventory(files)),
            'repositoryTrust': 'operator-asserted', 'capture': 'explicit-input-files'},
        'componentDigest': digest(component), 'componentSize': len(component),
        'materials': sorted(materials, key=lambda item: item['name']),
        'parameters': {'cargoPackage': project['name'], 'manifestPath': 'Cargo.toml', 'crateType': 'cdylib',
            'target': 'wasm32-unknown-unknown', 'profile': 'release', 'locked': True, 'incremental': False},
        'startedAt': started, 'finishedAt': finished, 'reproducibility': 'not-checked',
        'hermetic': False, 'dependencyCompleteness': 'declared-inputs-incomplete'}
    write_json(output / 'build-observation.json', observation)
    write_json(output / 'BUILD-COMPLETE.json', {'formatVersion': 1,
        'observationDigest': digest(read_file(output / 'build-observation.json')),
        'sourceDigest': digest(inventory(files)), 'componentDigest': digest(component),
        'packageAssembled': True, 'applicationRecompiled': False, 'retainedCompilerSource': SOURCE,
        'originalCompilerRunConclusion': 'failure', 'normalRustBuilderRouteOpened': False,
        'commands': commands.records})
    return projection
