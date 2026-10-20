"""Closed, core-preserving metadata derivation for a retained resource component.

This qualification helper never invokes NativeAOT or changes an application
core. Original AOT records remain verbatim and the fresh observation explicitly
names the metadata-only derivation; a normal packager/signer remains required.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import re
import shutil
import time
from tools.build_observation import finish_observation, file_identity as material
from tools.dotnet_guest import closed_io, compatibility, composer, internal_io
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, read_json, snapshot, write_json

COMPILED_SOURCE = 'a1028e1bd854700f27e75017349c58b88b53b0d5'
COMPONENT = {'sha256':'sha256:ae70bb14ba532ab9cfcef0ea342e9929c08586e77d94e03d71f444ef0076fe74','bytes':2985677}
ADAPTER = {'digest':'sha256:07e5a5aa3435a4b8a0b17300c82559cde1e577a1cb42ed975142e1d54e6d77d0','size':109832}
ENTROPY = {'digest':'sha256:2dbf0dacbc5c95439609a6ed8db7ecb935e4a5ce3581d688cfb6c9478fefc7c0','size':28716}

def shape(graph):
    return {direction: {name: {'functions': {symbol: internal_io.shape(graph, function)
            for symbol, function in members.items()}, 'types': {
                symbol: internal_io.shape(graph, index, type_index=True)
                for symbol, index in next(interface['types'] for interface in graph['interfaces']
                    if internal_io.interface_name(graph, graph['interfaces'].index(interface)) == name).items()}}
        for name, members in internal_io.functions(graph, direction).items()}
        for direction in ('imports', 'exports')}


def recover_components(raw, observed):
    require(file_identity_bytes(raw) == COMPONENT, 'dotnet-resource-original-component')
    nested = [payload for kind, payload, _encoded in internal_io.sections(raw) if kind == 4]
    require(len(nested) == 3, 'dotnet-resource-original-component-count')
    result = {}
    for name, expected in (('adapter', ADAPTER), ('entropy', ENTROPY)):
        values = [value for value in nested if digest(value) == expected['digest'] and len(value) == expected['size']]
        require(len(values) == 1, 'dotnet-resource-original-nested-identity')
        source_name = 'closed-logging-runtime' if name == 'adapter' else 'noncrypto-entropy'
        require([row for row in observed['materials'] if row['name'] == source_name] ==
                [{'name': source_name, **expected}], 'dotnet-resource-original-material')
        result[name] = values[0]
    result['application'] = next(value for value in nested if value not in result.values())
    require(len(result['application']) > 2 * 1024**2, 'dotnet-resource-original-application')
    return result


def file_identity_bytes(raw):
    return {'sha256': digest(raw), 'bytes': len(raw)}


def transform(compiler, source: Path, output: Path, prefix: str):
    output.mkdir()
    body = read_file(source, internal_io.MAX_BINARY)
    graph = json.loads(compiler.run(prefix+'-original-wit', compiler.wasm, 'component', 'wit', source, '--json'))
    compiler.run(prefix+'-unbundle', compiler.wasm, 'component', 'unbundle', source,
        '--module-dir', output/'modules', '--threshold', '0', '-o', output/'unbundled.wasm')
    compiler.run(prefix+'-print', compiler.wasm, 'print', '--name-unnamed', output/'unbundled.wasm', '-o', output/'original.wat')
    text = internal_io.named_export_syntax(read_file(output/'original.wat', internal_io.MAX_TEXT).decode())
    selected_text = closed_io.selected_text(text)
    require(selected_text == text.replace('(func async', '(func'), 'dotnet-resource-only-async-type-token-changes')
    (output/'selected.wat').write_bytes(selected_text.encode())
    compiler.run(prefix+'-encode', compiler.wasm, 'parse', output/'selected.wat', '-o', output/'unbundled-selected.wasm')
    modules = {path.stem: read_file(path, internal_io.MAX_BINARY) for path in (output/'modules').iterdir()}
    selected = output/'selected.wasm'
    selected.write_bytes(internal_io.rebundle(read_file(output/'unbundled-selected.wasm', internal_io.MAX_BINARY), modules))
    compiler.run(prefix+'-validate', compiler.wasm, 'validate', '--features', 'all', selected)
    after = json.loads(compiler.run(prefix+'-selected-wit', compiler.wasm, 'component', 'wit', selected, '--json'))
    require(sorted(internal_io.core_modules(body)) == sorted(internal_io.core_modules(read_file(selected, internal_io.MAX_BINARY))),
            'dotnet-resource-core-bytes-changed')
    return selected, graph, after, text.count('(func async')


def derive(component: Path, observed: dict, output: Path, compiler, recipe_source: str):
    output.mkdir()
    before = read_file(component, internal_io.MAX_BINARY)
    children = recover_components(before, observed)
    for name, body in children.items():
        (output/(name+'.wasm')).write_bytes(body)
    reference, public_before, public_reference, count = transform(compiler, component, output/'reference', 'reference')
    require(count == 16 and public_before == public_reference, 'dotnet-resource-reference-public-types')
    selected_adapter, port = closed_io.prepare(compiler, output/'adapter.wasm', output/'adapter-patch', 'closed-logging')
    application, raw_before, raw_after, count = transform(compiler, output/'application.wasm', output/'application-restored', 'application')
    expected = copy.deepcopy(raw_before)
    found = set()
    for interface, functions in internal_io.functions(expected, 'imports').items():
        for name in internal_io.TARGETS.get(interface, set()):
            if name not in functions:
                continue
            kind = functions[name]['kind']
            require(kind == 'async-freestanding' or isinstance(kind, dict) and set(kind) == {'async-method'},
                    'dotnet-resource-original-BCL-async-projection')
            functions[name]['kind'] = 'freestanding' if kind == 'async-freestanding' else {'method': kind['async-method']}
            found.add((interface, name))
    require(count == 4 and len(found) == 4 and raw_after == expected,
            'dotnet-resource-only-original-BCL-io-types-restored')
    compiler.runtime = selected_adapter
    compiler.wac = composer.install(output, ROOT/'sdk/dotnet-guest', compiler.commands)
    additional = [('entropy', output/'entropy.wasm')]
    coverage = compatibility.inspect(compiler, application, additional_adapters=additional)
    final = output/'composed/component.wasm'
    final.parent.mkdir()
    composer.compose_exact(compiler, application, final, coverage, additional_adapters=additional)
    compiler.run('production-final-validate', compiler.wasm, 'validate', '--features', 'all', final)
    graph = json.loads(compiler.run('production-final-wit', compiler.wasm, 'component', 'wit', final, '--json'))
    final_bytes = read_file(final, internal_io.MAX_BINARY)
    require(shape(graph) == shape(public_before)
            and sorted(internal_io.core_modules(before)) == sorted(internal_io.core_modules(final_bytes)),
            'dotnet-resource-production-composition-type-and-core-equivalence')
    skeleton = compiler.run('production-final-skeleton', compiler.wasm, 'print', '--skeleton', final)
    require(b'(func async' not in skeleton, 'dotnet-resource-production-private-async-types-remain')
    return final, {'metadataRecipeSource': recipe_source, 'compiledSource': COMPILED_SOURCE,
        'nativeAotCompilation': False, 'originalComponent': COMPONENT,
        'referenceComponent': file_identity(reference), 'selectedComponent': file_identity(final),
        'publicGraphEquivalent': True, 'allCoreModulesByteIdentical': True,
        'actualProductionClosedAdapterDerivation': port, 'actualProductionComposition': True,
        'originalBCLImportsRestored': sorted([interface+'#'+name for interface, name in found])}


def publish_build(artifact: Path, component: Path, proof: dict, output: Path, commands, recipe_source: str,
                  *, started: int | None = None, elapsed: float = 0.0, current_materials=()):
    """Create a new honest derivation observation; preserve old evidence verbatim."""
    from tools.dotnet_resource_originals import validate_records
    validate_records(artifact)
    require(re.fullmatch('[0-9a-f]{40}', recipe_source) is not None
        and proof.get('nativeAotCompilation') is False
        and proof.get('allCoreModulesByteIdentical') is True
        and proof.get('publicGraphEquivalent') is True
        and proof.get('actualProductionComposition') is True
        and proof.get('originalComponent') == COMPONENT
        and proof.get('selectedComponent') == file_identity(component),
        'dotnet-resource-metadata-derivation-proof')
    output.mkdir()
    for name in ('BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json',
                 'recipe-inputs.json', 'compatibility-report.json'):
        shutil.copyfile(artifact/name, output/('original-'+name))
    source_files = {'original/component.wasm': read_file(artifact/'component.wasm', 16*1024**2),
        'original/build-observation.json': read_file(artifact/'build-observation.json'),
        'original/source-inputs.json': read_file(artifact/'source-inputs.json'),
        'derivation/closed_io.py': read_file(ROOT/'tools/dotnet_guest/closed_io.py'),
        'derivation/recomposition.py': read_file(Path(__file__)),
        'derivation/source-wit.json': inventory(snapshot(ROOT/'sdk/dotnet-guest/runtime/wit'))}
    source_inventory = inventory(source_files)
    shutil.copyfile(component, artifact/'component.wasm')
    selected = file_identity(component)
    manifest = read_json(artifact/'capsule.json');manifest['component']['digest'] = selected['sha256']
    (artifact/'capsule.json').write_bytes((json.dumps(manifest, sort_keys=True, separators=(',', ':'))+'\n').encode())
    deployment = read_json(artifact/'deployment.json');deployment['spec']['release'] = selected['sha256']
    (artifact/'deployment.json').write_bytes((json.dumps(deployment, sort_keys=True, separators=(',', ':'))+'\n').encode())
    from tools.guest_compatibility import report, finding
    compatibility_report = report('dotnet', digest(source_inventory), selected['sha256'], closed_io.PROFILE,
        [{'kind': 'runtime', 'digest': digest(read_file(ROOT/'tools/dotnet_guest/closed_io.py')), 'profile': closed_io.PROFILE}],
        [finding('unresolved-behavior', phase, 'not-evaluated') for phase in ('initialization', 'invocation')]
        + [finding('lifecycle-unproven', 'retirement', 'not-evaluated', owner_issue=736)])
    (artifact/'compatibility-report.json').write_bytes((json.dumps(compatibility_report, indent=2)+'\n').encode())
    recipe_files = {name: read_file(ROOT/name) for name in ('tools/dotnet_guest/closed_io.py',
        'tools/dotnet_guest/internal_io.py', 'tools/dotnet_guest/composer.py', 'tools/dotnet_guest/compatibility.py')}
    recipe_files['tools/dotnet_resource_recomposition.py'] = read_file(Path(__file__))
    recipe = inventory(recipe_files)
    original_observation = read_json(output/'original-build-observation.json')
    proof = {**proof, 'operation': 'component-metadata-derivation', 'nativeAotCompilation': False,
        'metadataRecipeSource': recipe_source, 'inheritedCompilerParametersDescribeAncestry': True,
        'originalObservationDigest': digest(read_file(output/'original-build-observation.json'))}
    write_json(output/'derivation.json', proof)
    document = read_json(artifact/'package-source.json')
    assets = {'dotnet-inherited-aot-observation.json': read_file(output/'original-build-observation.json'),
        'dotnet-metadata-derivation.json': read_file(output/'derivation.json')}
    require(not set(assets) & {row['source'] for row in document['layers']},
        'dotnet-resource-derivation-reserved-asset')
    for name, raw in assets.items():
        (artifact/name).write_bytes(raw)
        document['layers'].append({'path': name, 'source': name, 'role': 'asset', 'mediaType': 'application/json'})
    (artifact/'package-source.json').write_bytes((json.dumps(document, sort_keys=True, separators=(',', ':'))+'\n').encode())
    package_inputs = inventory({name: read_file(artifact/name, 16*1024**2)
        for name in ('package-source.json', *(layer['source'] for layer in document['layers']))})
    inherited = {row['name']: row for row in original_observation['materials']
        if row['name'] not in {'source-snapshot', 'build-recipe', 'package-inputs'}}
    inherited.update({row['name']: row for row in current_materials})
    now = int(time.time())
    observation = finish_observation(repository='https://github.com/KirilsTurkins/latent-service-fabric',
        revision=digest(source_inventory).removeprefix('sha256:'), inventory=source_inventory,
        component=read_file(component, 16*1024**2),
        materials=[*inherited.values(),
                   material(output/'original-build-observation.json', 'original-native-aot-observation'),
                   material(output/'derivation.json', 'metadata-only-no-native-aot-compilation'),
                   {'name': 'build-recipe', 'digest': digest(recipe), 'size': len(recipe)},
                   {'name': 'package-inputs', 'digest': digest(package_inputs), 'size': len(package_inputs)}],
        started=now if started is None else started, finished=now, elapsed=elapsed, reproducible=False)
    observation['buildType'] = 'https://latent.dev/build/dotnet-capsule/v1'
    observation['source']['capture'] = 'explicit-input-files'
    # This closed typed recipe describes the inherited compiler/runtime lineage.
    # The mandatory hashed material above explicitly states that this operation
    # did not execute that compiler. Never add unsupported recipe fields.
    observation['parameters'] = original_observation['parameters']
    observation['dependencyCompleteness'] = 'declared-inputs-incomplete'
    from jsonschema import Draft202012Validator
    Draft202012Validator(read_json(ROOT/'schemas/build-observation.schema.json')).validate(observation)
    require(next(row for row in observation['materials']
                 if row['name'] == 'metadata-only-no-native-aot-compilation')['digest']
            == digest(read_file(output/'derivation.json')) and not proof['nativeAotCompilation'],
            'dotnet-resource-mandatory-metadata-only-material')
    for name, data in (('source-inputs.json', source_inventory), ('recipe-inputs.json', recipe),
                       ('package-inputs.json', package_inputs)):
        (artifact/name).write_bytes(data)
    raw = (json.dumps(observation, indent=2)+'\n').encode();(artifact/'build-observation.json').write_bytes(raw)
    marker = {'formatVersion': 1, 'componentDigest': selected['sha256'],
        'sourceDigest': digest(source_inventory), 'observationDigest': digest(raw),
        'operation': 'component-metadata-derivation', 'nativeAotCompilation': False}
    (artifact/'BUILD-COMPLETE.json').write_bytes((json.dumps(marker, indent=2)+'\n').encode())
    return marker
