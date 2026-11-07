"""Package one source-captured corrected combined compiler observation.

The successful compiler job and workflow are distinct from the historical
failed compiler and signed execution events. Assembly does not recompile
an application, open the normal builder, or substitute unreviewed graph bytes.
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

CATALOGUE = ROOT / 'crates/latent-component-threading/src/rust_catalogue/combined-corrected-v1'
ORIGIN = read_json(CATALOGUE / 'origin.json', 64 * 1024)
SOURCE = ORIGIN['sourceCommit']
RUN, JOB, ARTIFACT = (ORIGIN[key] for key in ('run', 'job', 'artifact'))
PROFILE = 'rust-context40-combined-http-diagnostic-v1'
# Fixed host-owned selection, not filenames or hashes supplied by a caller.
MEMBERS = ('application-source-and-capture.tar.gz', 'source-inputs.json', 'raw-core.wasm',
           'combined-component.wasm', 'observation.json', 'rust-http-composition.json',
           'recipe-origin.json', 'recipe-inputs.json', 'rust-http-runtime.json')
require(set(ORIGIN['compilerMembers']) == set(MEMBERS), 'rust-combined-fixed-compiler-members')
PINS = {name: (ORIGIN['compilerMembers'][name]['bytes'],
               ORIGIN['compilerMembers'][name]['sha256'].removeprefix('sha256:')) for name in MEMBERS}
WRAPPED = ORIGIN['wrapped']
IMPORTS = ('latent:clock/monotonic@0.1.0', 'latent:http/streaming@0.3.0',
           'latent:runtime-native/threads@0.1.0', 'latent:runtime/activation@0.1.0')
WALL = 'latent:clock/wall@0.1.0'


def original_files(artifact: Path) -> tuple[dict[str, bytes], dict]:
    identities = {}
    for name, (size, sha) in PINS.items():
        actual = file_identity(artifact / name, 32 * 1024 * 1024)
        require(actual == {'bytes': size, 'sha256': 'sha256:' + sha}, 'rust-http-thread-retained-member')
        identities[name] = actual
    expected = read_json(artifact / 'source-inputs.json', 64 * 1024)
    require(type(expected) is dict and 0 < len(expected) <= 256,
            'rust-http-thread-retained-snapshot-shape')
    files, seen, total = {}, set(), 0
    with tarfile.open(artifact / 'application-source-and-capture.tar.gz', 'r:gz') as archive:
        for ordinal, member in enumerate(archive):
            name, path = member.name, PurePosixPath(member.name)
            require(ordinal < 16_384 and member.isfile() and 0 <= member.size <= 4 * 1024 * 1024
                    and name and not path.is_absolute() and path.as_posix() == name
                    and all(part not in ('', '.', '..') for part in path.parts)
                    and name.casefold() not in seen, 'rust-http-thread-retained-archive-shape')
            seen.add(name.casefold())
            total += member.size
            require(total <= 128 * 1024 * 1024, 'rust-http-thread-retained-archive-bound')
            if name in expected:
                payload = archive.extractfile(member).read(member.size + 1)
                require({'size': len(payload), 'digest': digest(payload)} == expected[name],
                        'rust-http-thread-retained-source-identity')
                files[name] = payload
    require(set(files) == set(expected)
            and inventory(files) == read_file(artifact / 'source-inputs.json', 64 * 1024),
            'rust-http-thread-complete-retained-source')
    return files, identities


def validate_producer(observation: dict, composition: dict, recipe: dict,
                      recipe_inputs: dict, source_inventory: bytes, runtime: bytes) -> None:
    commands = observation['commands']
    require(observation['schemaVersion'] == 'latent.rust.http-thread-core-observation.v1'
            and observation['status'] == ORIGIN['compilerObservationStatus']
            and observation['stage'] == 'complete'
            and observation['actualApplicationCoreCompiled'] is True
            and observation['normalBuildComplete'] is False
            and observation['normalComponentGateRefused'] is True
            and observation['actualGuestExecuted'] is False
            and observation['httpCompositionIncluded'] is True
            and observation['capture']['sourceDigest'] == digest(source_inventory)
            and observation['originalCore']['digest'] == 'sha256:' + PINS['raw-core.wasm'][1]
            and observation['combinedComponent']['digest'] == 'sha256:' + PINS['combined-component.wasm'][1]
            and observation['retainedOriginalSource']['digest'] == 'sha256:' + PINS['application-source-and-capture.tar.gz'][1]
            and observation['httpPreparedReceiptDigest'] == digest(runtime)
            and type(commands) is list and 0 < len(commands) <= 128
            and all(row['exitCode'] == 0 for row in commands)
            and sum(row['stage'] == 'compile' for row in commands) == 1
            and [(row['stage'], row['exitCode']) for row in commands[-4:]] == [
                ('rust-http-exact-composition', 0), ('rust-http-final-validation', 0),
                ('rust-http-final-graph', 0), ('combined-component-graph', 0)],
            'rust-http-thread-completed-compiler-observation')
    rows = recipe['files']
    require(recipe['head'] == SOURCE and recipe['tree'] == ORIGIN['sourceTree']
            and type(rows) is list and 0 < len(rows) <= 256
            and len({row['path'] for row in rows}) == len(rows)
            and {row['path']: {'size': row['size'], 'digest': row['digest']} for row in rows} == recipe_inputs,
            'rust-http-thread-compiler-source-lineage')
    require(composition['selectedComponentDigest'] == 'sha256:' + PINS['combined-component.wasm'][1]
            and observation['httpComposition'] == {**composition,
                'diagnosticComposer': observation['diagnosticComposer'], 'diagnosticOnly': True,
                'diagnosticValidationFeatures': 'cm-threading,cm-async,cm-async-stackful,cm-more-async-builtins'}
            and composition['publicGraphUnchanged'] is True
            and composition['librarySourceRewritten'] is False
            and composition['signedExecutionQualification'] is False
            and composition['runtimeReceipt'] == digest(runtime)
            and set(composition['imports']) == set(IMPORTS)
            and composition['exports'] == ['examples:greeting/api@1.0.0'],
            'rust-http-thread-exact-composed-surface')


def producer(artifact: Path, files: dict[str, bytes]) -> tuple[dict, dict]:
    observation = read_json(artifact / 'observation.json', 512 * 1024)
    composition = read_json(artifact / 'rust-http-composition.json', 16 * 1024)
    validate_producer(observation, composition, read_json(artifact / 'recipe-origin.json', 128 * 1024),
                     read_json(artifact / 'recipe-inputs.json', 64 * 1024), inventory(files),
                     read_file(artifact / 'rust-http-runtime.json', 64 * 1024))
    return observation, composition


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
    observed, composition = producer(artifact, files)
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
        'tools/rust_combined_http_materials.py',
        'crates/latent-component-threading/src/rust_catalogue/combined-corrected-v1/origin.json',
        '.github/workflows/rust-combined-signed-witness.yml',
        'tools/qualify_rust_thread_http_combined.py')))
    require(len(recipe_names) <= 256, 'rust-http-thread-assembly-recipe-bound')
    recipe = inventory({name: read_file(ROOT / name, 4 * 1024 * 1024) for name in recipe_names})
    (output / 'recipe-inputs.json').write_bytes(recipe)
    (output / 'source-inputs.json').write_bytes(read_file(artifact / 'source-inputs.json', 64 * 1024))
    (output / 'original-project.json').write_bytes(files['capsule-project.json'])
    (output / 'original-world.wit').write_bytes(files['wit/world.wit'])
    (output / 'retained-compiler-observation.json').write_bytes(read_file(artifact / 'observation.json', 512 * 1024))
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
    component = framed(artifact, CATALOGUE)
    (output / 'component.wasm').write_bytes(component)
    projection = {'schemaVersion': 'latent.rust.combined-http.diagnostic-projection.v1',
        'compilerSource': SOURCE, 'compilerRun': RUN, 'compilerJob': JOB, 'compilerArtifact': ARTIFACT,
        'compilerRunConclusion': ORIGIN['workflowConclusion'],
        'compilerJobConclusion': ORIGIN['producerJobConclusion'],
        'compilerWorkflowSource': ORIGIN['workflowSource'],
        'compilerObservationStatus': observed['status'],
        'workflowFailureOutsideCompilerJob': ORIGIN['workflowFailureOutsideCompilerJob'],
        'compositionAndValidationCommandsSucceeded': True,
        'retainedMembers': identities, 'originalSourceDigest': digest(inventory(files)),
        'originalPublicWitDigest': digest(files['wit/world.wit']),
        'projectedPublicWitDigest': digest(source['wit/world.wit']),
        'omittedSourceImportAbsentFromComposedGraph': WALL, 'finalRequiredImports': list(IMPORTS),
        'componentDigest': digest(component), 'selectedHostProfile': PROFILE,
        'originalLimits': project['limits'], 'applicationRecompiled': True, 'applicationRecompiledDuringAssembly': False,
        'originalCompilerObservationRewritten': False, 'normalRustBuilderRouteOpened': False,
        'nativeHostMustRecomputeOriginalGraph': True, 'actualGuestExecuted': False,
        'standardRuntimeQualified': False}
    write_json(output / 'qualification-projection.json', projection)
    package_inputs(output, project, surface, source, component, threading_model='cooperative',
        additional_assets=(('qualification-projection.json', 'asset', 'application/vnd.latent.rust-thread-projection.v1+json'),
            ('original-project.json', 'asset', 'application/json'), ('original-world.wit', 'asset', 'application/wasm-wit'),
            ('retained-compiler-observation.json', 'asset', 'application/json'),
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
        ('package-inputs', package_inventory), ('retained-compiler-observation', read_file(output / 'retained-compiler-observation.json')),
        ('retained-composition', read_file(output / 'retained-composition.json')),
        ('qualification-projection', read_file(output / 'qualification-projection.json')))]
    materials.append({'name': 'retained-source-and-cas-capture',
        'digest': identities['application-source-and-capture.tar.gz']['sha256'],
        'size': identities['application-source-and-capture.tar.gz']['bytes']})
    retained = [row for row in observed['tools'] if row['name'] in {'cargo', 'rustc', 'wasm-tools', 'wit-bindgen'}]
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
        'packageAssembled': True, 'applicationRecompiled': True, 'applicationRecompiledDuringAssembly': False, 'retainedCompilerSource': SOURCE,
        'compilerRunConclusion': ORIGIN['workflowConclusion'],
        'compilerJobConclusion': ORIGIN['producerJobConclusion'], 'normalRustBuilderRouteOpened': False,
        'commands': commands.records})
    return projection
