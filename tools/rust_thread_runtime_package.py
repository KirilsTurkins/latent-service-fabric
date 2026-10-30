"""Package one retained original ThreadPool compiler event for signed execution.

No application compiler is invoked. The original 67-file application snapshot
and full source/CAS archive remain bound to event 28059. The finite qualification
policy changes only the public WIT effect and invocation memory/time envelope;
neither change is presented as original compiler input or runtime authority.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import tarfile
import time

from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import BUILD_TYPE, Commands, package_inputs, selected_recipe
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, write_json
from tools.rust_thread_callback_paths import section, unsigned

SOURCE = 'ef841ed1d5691b4bf25db48b9980a776b4b56bc5'
RUN = 41127291312
HISTORICAL_PINS = {
    'application-source-and-capture.tar.gz': (20761985, 'c6d9ef4e2eb48af53b7685065e406dd5ff8403c5b003c45383680c6afb68a085'),
    'source-inputs.json': (9204, '645f05410a943a1383462ce2eef5a30145c1f6953de74154b3e0b5c62174057e'),
    'raw-core.wasm': (262436, '583e2353a8405db569e61cb3269b3643aff39374c1e2d83cc970cc033604edec'),
    'observation.json': (4522, '8bbcc074c19d458230e14681f4be429848e6e156e327d8370f2c452cf00f35a2'),
}
PREVIOUS_PINS = {
    'application-source-and-capture.tar.gz': (20758354, '426379c7f44ebd9bc903ddf7169454cc78c7fd28ca3a4f2ff744564be5f0aba3'),
    'source-inputs.json': (9204, 'c9b24130d4c9f06b10e801f6fe78e6a2db5642164f7b67cb7f1d624431e29232'),
    'raw-core.wasm': HISTORICAL_PINS['raw-core.wasm'],
    'observation.json': (4521, 'fb43d1bcfe2d3d5f31bedcbe3e889f9a4e60389b7bc7bfe9034ecad94923da9d'),
}
PRIOR_PINS = {
    'application-source-and-capture.tar.gz': (20967082, '0fc010b42fa347a494c4f0590a1e75ce46e0d0a181bf07c9f62201e06d9492ca'),
    'source-inputs.json': (9348, '13cf42650a10c4e8659ef9bf4216a39e19a190e27b327f6f8f9b76073272b52c'),
    'raw-core.wasm': (262760, '32d45c689b53d41e6a4797e4a293c3a41ad5a3e7219407632101cf3858a18468'),
    'observation.json': (5427, '86110a34ac5235bb70058f02b9c89c93ef322c209235e86badade5501c863b69'),
}
LATEST_PREVIOUS_PINS = {
    'application-source-and-capture.tar.gz': (20962606, '782a8fd8c59baf0125493d70866b1eda47dfbb7bb32c259f85ca445e9e0956d4'),
    'source-inputs.json': (9348, '414381e4c607ca3acae3fdbe424d20105420a4ca49994cbdfefc126f1f0be3f2'),
    'raw-core.wasm': (262561, '1016bc74d96585be6943d2b1396cf79ebd8f1fa66828a321d2ee251827431bcc'),
    'observation.json': (5426, 'cf773f3995fa25fd43bba4183683dc8202759c805f8ca8b5e971068a9a2da4f9'),
}
HOSTED_PREVIOUS_PINS = {
    'application-source-and-capture.tar.gz': (20966554, 'c1f67326b3cc0e3b1399ba0eeeb4b5ef05741874d9fc4bcacfe03e22dac52203'),
    'source-inputs.json': (9348, 'e7c36ea2ce9deb88b24aae2f797ced711e3a5a3b183a34c4ed2106d0b6de20e0'),
    'raw-core.wasm': (262853, 'ae5b68cec5fa2d68cdd65eb669844e0d2dd75d8a3fc7563d8fc0a272866b9c7b'),
    'observation.json': (5427, 'bd887733bf8360aeb85dfea8163067339a085f7f4fa5e95dac06e5ee3a11676a'),
}
PINS = {
    'application-source-and-capture.tar.gz': (20968654, '1daf63d7e138e68e2f69910de05c07fc98ed23b60bccd4fa3784e3746ebeca2b'),
    'source-inputs.json': (9348, 'd0419a16e563d186d3c2fc323fa81bf26b13f18f068b88d5f36128bd9e7ada69'),
    'raw-core.wasm': (263030, '0cbb66d8e363c47df6b158d50facb7fa04f280bcb2650aa0597385fd63025a24'),
    'observation.json': (5426, '3738b83b3d08a857fe7dd38e73a9ebe415f65c0c8ff2551ac293bf465128a007'),
}
COMPONENT_SHA = 'sha256:1db2b051a515be1bd60974e38335f6bade254d6b016daf9e20b913360e72c00f'
WRAPPED = {'bytes': 514833,
           'sha256': 'sha256:e81881af5494d3d6ab3b071abd8fadca79d2f21b354e2e52dc746d492582f471'}
PROFILE = 'rust-context40-sync-cooperative-v1'
SOURCE_IMPORTS = ('latent:runtime/activation@0.1.0', 'latent:runtime-native/threads@0.1.0',
                  'latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0')
# The actual authenticated normal encoder envelope contains these three imports.
# Its source-declared but unused wall function has no retained Core reference.
IMPORTS = SOURCE_IMPORTS[:3]
ORIGINAL_WIT = b'''package examples:greeting@1.0.0;

interface api {
    greet: func(name: string) -> result<string, string>;
}

world service {
    import latent:runtime/activation@0.1.0;
    import latent:runtime-native/threads@0.1.0;
    import latent:clock/monotonic@0.1.0;
    import latent:clock/wall@0.1.0;
    export api;
}
'''


def original_files(artifact: Path) -> tuple[dict[str, bytes], dict]:
    """Authenticate a finite retained snapshot without materializing its CAS."""
    identities = {}
    for name, (size, sha) in PINS.items():
        actual = file_identity(artifact / name, 32 * 1024 * 1024)
        require(actual == {'bytes': size, 'sha256': 'sha256:' + sha},
                'rust-thread-exact-retained-compiler-material')
        identities[name] = actual
    expected = read_json(artifact / 'source-inputs.json', 16 * 1024)
    require(type(expected) is dict and len(expected) == 68
            and all(type(name) is str and not PurePosixPath(name).is_absolute()
                    and '..' not in PurePosixPath(name).parts for name in expected),
            'rust-thread-original-snapshot-shape')
    files, seen, total = {}, set(), 0
    with tarfile.open(artifact / 'application-source-and-capture.tar.gz', 'r:gz') as archive:
        for ordinal, member in enumerate(archive):
            require(ordinal < 7262 and member.isfile() and 0 <= member.size <= 4 * 1024 * 1024
                    and member.name not in seen, 'rust-thread-original-archive-shape')
            seen.add(member.name)
            total += member.size
            require(total <= 128 * 1024 * 1024, 'rust-thread-original-archive-expanded-bound')
            if member.name in expected:
                payload = archive.extractfile(member).read(member.size + 1)
                require({'size': len(payload), 'digest': digest(payload)} == expected[member.name],
                        'rust-thread-original-snapshot-file')
                files[member.name] = payload
    require(len(seen) == 7262 and total == 103848865 and set(files) == set(expected)
            and inventory(files) == read_file(artifact / 'source-inputs.json', 16 * 1024),
            'rust-thread-complete-original-application-snapshot')
    require(files.get('wit/world.wit') == ORIGINAL_WIT, 'rust-thread-exact-original-public-wit')
    return files, identities


def wrap_original(original: bytes, component: bytes) -> bytes:
    """Untrusted preimage framing only; the selected native host recomputes it."""
    require(digest(original) == 'sha256:' + PINS['raw-core.wasm'][1]
            and digest(component) == COMPONENT_SHA and len(component) == 251758,
            'rust-thread-original-component-pair')
    name = b'latent-rust-original-core-v1'
    payload = unsigned(len(name)) + name + b'LSFRPR01' + len(original).to_bytes(4, 'little') + original
    wrapped = component + section(0, payload)
    require({'bytes': len(wrapped), 'sha256': digest(wrapped)} == WRAPPED,
            'rust-thread-exact-qualified-component-framing')
    return wrapped


def prepare(artifact: Path, native: dict, output: Path, commands: Commands) -> dict:
    output = fresh(output)
    assembly_started = int(time.time())
    files, identities = original_files(artifact)
    prior_raw = read_file(artifact / 'observation.json', 16 * 1024)
    prior = json.loads(prior_raw)
    require(prior['actualApplicationCoreCompiled'] is True and prior['normalBuildComplete'] is False
            and prior['normalComponentGateRefused'] is True
            and prior['capture']['sourceDigest'] == digest(inventory(files))
            and prior['originalCore']['digest'] == 'sha256:' + PINS['raw-core.wasm'][1],
            'rust-thread-retained-original-compiler-observation')
    recipe_names = tuple(dict.fromkeys((*selected_recipe(),
        '.github/workflows/rust-thread-runtime.yml', 'tools/rust_thread_native_products.py',
        'tools/rust_thread_compiler_materials.py', 'tools/rust_thread_runtime_package.py',
        'tools/rust_thread_runtime_node.py', 'tools/qualify_rust_thread_runtime.py',
        'tools/rust_thread_callback_paths.py', 'tools/rust_thread_object_graph.py')))
    require(len(recipe_names) <= 256, 'rust-thread-retained-assembly-recipe-count')
    recipe = inventory({name: read_file(ROOT / name, 4 * 1024 * 1024) for name in recipe_names})
    (output / 'recipe-inputs.json').write_bytes(recipe)
    project = json.loads(files['capsule-project.json'])
    require(project['name'] == 'ordinary-thread-inputs'
            and project['service'] == 'examples/ordinary-thread-inputs'
            and project['limits']['memoryBytes'] == 4194304
            and project['limits']['wallTimeLimitMillis'] == 1000,
            'rust-thread-original-project-budget')
    (output / 'original-project.json').write_bytes(files['capsule-project.json'])
    (output / 'original-world.wit').write_bytes(files['wit/world.wit'])
    (output / 'retained-compiler-observation.json').write_bytes(prior_raw)
    (output / 'source-inputs.json').write_bytes(read_file(artifact / 'source-inputs.json', 16 * 1024))
    projected = ORIGINAL_WIT.replace(b'greet: func(', b'greet: async func(', 1)
    projected = projected.replace(b'    import latent:clock/wall@0.1.0;\n', b'', 1)
    source = {**files, 'wit/world.wit': projected}
    # Code/CAS/compiler capture stays original. This separately signed operator
    # policy pays genuine original linear memory and all native stack mappings.
    project['limits'].update(memoryBytes=32 * 1024 * 1024, wallTimeLimitMillis=5000)
    wit_input = output / 'wit-inputs.json'
    write_json(wit_input, {'world': project['world'], 'sources': [
        {'path': name, 'content': data.decode()} for name, data in sorted(source.items())
        if name.startswith('wit/') and name.endswith('.wit')]})
    contracts = output / 'contracts'
    commands.run('retained-thread-contracts', native['capsule_contracts'], wit_input, contracts)
    for name in ('contracts.json', 'wit-lock.json', 'surface.json'):
        (output / name).write_bytes(read_file(contracts / name, 4 * 1024 * 1024))
    surface = read_json(output / 'surface.json')
    require(set(surface['imports']) == set(IMPORTS)
            and surface['exports'] == ['examples:greeting/api@1.0.0'],
            'rust-thread-exact-projected-contract-surface')
    base = ROOT / 'crates/latent-component-threading/src/rust_catalogue'
    component = wrap_original(read_file(artifact / 'raw-core.wasm', 1024 * 1024),
                              read_file(base / 'catalogue-normal-component.wasm', 2 * 1024 * 1024))
    (output / 'component.wasm').write_bytes(component)
    record = {'schemaVersion': 'latent.rust.thread-runtime.projection.v1',
        'compilerSource': SOURCE, 'compilerRun': str(RUN), 'compilerRunAttempt': 1,
        'retainedCompilerMaterials': identities,
        'historicalCompilerArtifactMembers': {name: {'bytes': size, 'sha256': 'sha256:' + sha}
            for name, (size, sha) in HISTORICAL_PINS.items()},
        'previousCompilerArtifactMembers': {name: {'bytes': size, 'sha256': 'sha256:' + sha}
            for name, (size, sha) in PREVIOUS_PINS.items()},
        'priorCompilerArtifactMembers': {name: {'bytes': size, 'sha256': 'sha256:' + sha}
            for name, (size, sha) in PRIOR_PINS.items()},
        'latestPreviousCompilerArtifactMembers': {name: {'bytes': size, 'sha256': 'sha256:' + sha}
            for name, (size, sha) in LATEST_PREVIOUS_PINS.items()},
        'hostedPreviousCompilerArtifactMembers': {name: {'bytes': size, 'sha256': 'sha256:' + sha}
            for name, (size, sha) in HOSTED_PREVIOUS_PINS.items()},
        'originalSourceDigest': digest(inventory(files)), 'projectedPublicWitDigest': digest(projected),
        'originalPublicWitDigest': digest(ORIGINAL_WIT), 'publicEffect': 'async',
        'originalDeclaredImports': list(SOURCE_IMPORTS), 'finalRequiredImports': list(IMPORTS),
        'sourceDeclaredImportsOmittedBecauseAbsentFromAuthenticatedComponent': [SOURCE_IMPORTS[3]],
        'coreAbi': 'ordinary-synchronous', 'selectedHostProfile': PROFILE,
        'originalLimits': json.loads(files['capsule-project.json'])['limits'],
        'qualificationLimits': project['limits'], 'componentDigest': digest(component),
        'applicationRecompiled': False, 'guestCodeReplaced': False,
        'assemblyMode': 'retained-compiler-and-component-inputs-with-current-contracts-and-package-assembly',
        'retainedToolIdentitiesInvokedByThisAssembly': False,
        'originalCompilerObservationRewritten': False, 'normalRustBuilderRouteOpened': False,
        'nativeHostMustRecomputeOriginalGraph': True, 'actualGuestExecuted': False,
        'ordinaryThreadPoolQualified': False}
    write_json(output / 'qualification-projection.json', record)
    package_inputs(output, project, surface, source, component, threading_model='cooperative',
        additional_assets=(('qualification-projection.json', 'asset', 'application/vnd.latent.rust-thread-projection.v1+json'),
            ('original-project.json', 'asset', 'application/json'), ('original-world.wit', 'asset', 'application/wasm-wit'),
            ('retained-compiler-observation.json', 'asset', 'application/json')))
    package_files = {'package-source.json': read_file(output / 'package-source.json')}
    for layer in read_json(output / 'package-source.json')['layers']:
        package_files[layer['source']] = read_file(output / layer['source'], 4 * 1024 * 1024)
    package_inventory = inventory(package_files)
    (output / 'package-inputs.json').write_bytes(package_inventory)
    tool_identities = {name: file_identity(native[name]) for name in ('capsule_contracts', 'package')}
    commands.run('retained-thread-package-assembly', native['package'], 'build',
                 output / 'package-source.json', output, output / 'package')
    commands.run('retained-thread-package-inspection', native['package'], 'inspect', output / 'package')
    require(recipe == inventory({name: read_file(ROOT / name, 4 * 1024 * 1024) for name in recipe_names})
            and tool_identities == {name: file_identity(native[name]) for name in tool_identities}
            and package_inventory == inventory({name: read_file(output / name, 4 * 1024 * 1024)
                                                for name in package_files}),
            'rust-thread-retained-assembly-inputs-still-exact')
    materials = [{'name': name, 'digest': digest(data), 'size': len(data)} for name, data in (
        ('source-snapshot', read_file(output / 'source-inputs.json')), ('build-recipe', recipe),
        ('toolchain-config', files['rust-toolchain.toml']), ('dependency-lock', files['Cargo.lock']),
        ('package-inputs', package_inventory), ('retained-compiler-observation', prior_raw),
        ('qualification-projection', read_file(output / 'qualification-projection.json')),
        ('normal-component-origin', read_file(base / 'origin.json', 65536)))]
    materials.append({'name': 'retained-source-and-cas-capture',
        'digest': identities['application-source-and-capture.tar.gz']['sha256'],
        'size': identities['application-source-and-capture.tar.gz']['bytes']})
    # These are genuine original compiler-event tool identities, explicitly
    # reused inputs. The projection says none was invoked by this assembly.
    required = {'cargo', 'rustc', 'wasm-tools', 'wit-bindgen'}
    retained_tools = [row for row in prior['tools'] if row['name'] in required]
    require({row['name'] for row in retained_tools} == required and len(retained_tools) == 4,
            'rust-thread-retained-original-tool-identities')
    materials.extend(retained_tools)
    for name, identity in tool_identities.items():
        materials.append({'name': 'contracts-tool' if name == 'capsule_contracts' else 'packager',
                          'digest': identity['sha256'], 'size': identity['bytes']})
    assembly_finished = int(time.time())
    require(0 <= assembly_finished - assembly_started <= 600,
            'rust-thread-retained-assembly-clock-bound')
    # This is a NEW observation of actual retained-input package assembly.
    # Original compile status/commands/timestamps remain in their bound asset.
    observation = {'formatVersion': 1, 'buildType': BUILD_TYPE,
        'source': {'repository': 'https://github.com/KirilsTurkins/latent-service-fabric',
            'revision': digest(inventory(files))[7:], 'snapshotDigest': digest(inventory(files)),
            'repositoryTrust': 'operator-asserted', 'capture': 'explicit-input-files'},
        'componentDigest': digest(component), 'componentSize': len(component),
        'materials': sorted(materials, key=lambda item: item['name']),
        'parameters': {'cargoPackage': project['name'], 'manifestPath': 'Cargo.toml', 'crateType': 'cdylib',
            'target': 'wasm32-unknown-unknown', 'profile': 'release', 'locked': True, 'incremental': False},
        'startedAt': assembly_started, 'finishedAt': assembly_finished, 'reproducibility': 'not-checked',
        'hermetic': False, 'dependencyCompleteness': 'declared-inputs-incomplete'}
    write_json(output / 'build-observation.json', observation)
    write_json(output / 'BUILD-COMPLETE.json', {'formatVersion': 1,
        'observationDigest': digest(read_file(output / 'build-observation.json')),
        'sourceDigest': digest(inventory(files)), 'componentDigest': digest(component),
        'packageAssembled': True, 'applicationRecompiled': False, 'retainedCompilerSource': SOURCE,
        'normalRustBuilderRouteOpened': False, 'commands': commands.records})
    return record
