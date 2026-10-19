"""Recompose retained Console cores with the actual closed-only compiler fix.

This builds component metadata, packages and demo-signs it. It never recompiles
the BCL, claims a fresh NativeAOT build, or reuses an old build observation.
"""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path.cwd()))
try:
    import console_original_support as original
except ModuleNotFoundError:
    from tools import diagnose_dotnet_console_failure as original
from tools.build_observation import build_environment, finish_observation, file_identity as material
from tools.dotnet_guest import closed_io, compatibility, composer, internal_io
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_dotnet_standard_console import inherited
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, snapshot, write_json

PRODUCTION = '645f912b0ba01d5064167e773c28089e4cd7b248'
CLOSED_SOURCE = 'sha256:c0d65d52ef8e30f2930a1dfafd1479d9ff370ad1a3cd54789ceebf7eaa2b0684'
ADAPTER = {'digest': 'sha256:07e5a5aa3435a4b8a0b17300c82559cde1e577a1cb42ed975142e1d54e6d77d0', 'size': 109832}
ENTROPY = {'digest': 'sha256:2dbf0dacbc5c95439609a6ed8db7ecb935e4a5ce3581d688cfb6c9478fefc7c0', 'size': 28716}


def shape(graph):
    return {direction: {name: {'functions': {symbol: internal_io.shape(graph, function)
            for symbol, function in members.items()}, 'types': {
                symbol: internal_io.shape(graph, index, type_index=True)
                for symbol, index in next(interface['types'] for interface in graph['interfaces']
                    if internal_io.interface_name(graph, graph['interfaces'].index(interface)) == name).items()}}
        for name, members in internal_io.functions(graph, direction).items()}
        for direction in ('imports', 'exports')}


def recover_components(raw, observed):
    require(file_identity_bytes(raw) == original.COMPONENT, 'console-closed-original-component')
    nested = [payload for kind, payload, _encoded in internal_io.sections(raw) if kind == 4]
    require(len(nested) == 3, 'console-closed-original-component-count')
    result = {}
    for name, expected in (('adapter', ADAPTER), ('entropy', ENTROPY)):
        values = [value for value in nested if digest(value) == expected['digest'] and len(value) == expected['size']]
        require(len(values) == 1, 'console-closed-original-nested-identity')
        source_name = 'closed-logging-runtime' if name == 'adapter' else 'noncrypto-entropy'
        require([row for row in observed['materials'] if row['name'] == source_name] ==
                [{'name': source_name, **expected}], 'console-closed-original-material')
        result[name] = values[0]
    result['application'] = next(value for value in nested if value not in result.values())
    require(len(result['application']) > 2 * 1024**2, 'console-closed-original-application')
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
    require(selected_text == text.replace('(func async', '(func'), 'console-closed-only-async-type-token-changes')
    (output/'selected.wat').write_bytes(selected_text.encode())
    compiler.run(prefix+'-encode', compiler.wasm, 'parse', output/'selected.wat', '-o', output/'unbundled-selected.wasm')
    modules = {path.stem: read_file(path, internal_io.MAX_BINARY) for path in (output/'modules').iterdir()}
    selected = output/'selected.wasm'
    selected.write_bytes(internal_io.rebundle(read_file(output/'unbundled-selected.wasm', internal_io.MAX_BINARY), modules))
    compiler.run(prefix+'-validate', compiler.wasm, 'validate', '--features', 'all', selected)
    after = json.loads(compiler.run(prefix+'-selected-wit', compiler.wasm, 'component', 'wit', selected, '--json'))
    require(sorted(internal_io.core_modules(body)) == sorted(internal_io.core_modules(read_file(selected, internal_io.MAX_BINARY))),
            'console-closed-core-bytes-changed')
    return selected, graph, after, text.count('(func async')


def derive(component: Path, observed: dict, output: Path, compiler):
    output.mkdir()
    before = read_file(component, internal_io.MAX_BINARY)
    children = recover_components(before, observed)
    for name, body in children.items():
        (output/(name+'.wasm')).write_bytes(body)
    reference, public_before, public_reference, count = transform(compiler, component, output/'reference', 'reference')
    require(count == 16 and public_before == public_reference, 'console-closed-reference-public-types')
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
                    'console-closed-original-BCL-async-projection')
            functions[name]['kind'] = 'freestanding' if kind == 'async-freestanding' else {'method': kind['async-method']}
            found.add((interface, name))
    require(count == 4 and len(found) == 4 and raw_after == expected,
            'console-closed-only-original-BCL-io-types-restored')
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
            'console-closed-production-composition-type-and-core-equivalence')
    skeleton = compiler.run('production-final-skeleton', compiler.wasm, 'print', '--skeleton', final)
    require(b'(func async' not in skeleton, 'console-closed-production-private-async-types-remain')
    return final, {'productionSource': PRODUCTION, 'compiledSource': original.TESTED,
        'nativeAotCompilation': False, 'originalComponent': original.COMPONENT,
        'referenceComponent': file_identity(reference), 'selectedComponent': file_identity(final),
        'publicGraphEquivalent': True, 'allCoreModulesByteIdentical': True,
        'actualProductionClosedAdapterDerivation': port, 'actualProductionComposition': True,
        'originalBCLImportsRestored': sorted([interface+'#'+name for interface, name in found])}


def publish_build(artifact: Path, component: Path, proof: dict, output: Path, commands, recipe_source: str,
                  *, started: int | None = None, elapsed: float = 0.0, current_materials=()):
    """Create a new honest derivation observation; preserve old evidence verbatim."""
    output.mkdir()
    for name in ('BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json',
                 'recipe-inputs.json', 'compatibility-report.json'):
        shutil.copyfile(artifact/name, output/('original-'+name))
    source_files = {'original/component.wasm': read_file(artifact/'component.wasm', 16*1024**2),
        'original/build-observation.json': read_file(artifact/'build-observation.json'),
        'original/source-inputs.json': read_file(artifact/'source-inputs.json'),
        'derivation/closed_io.py': read_file(ROOT/'tools/dotnet_guest/closed_io.py'),
        'derivation/replay.py': read_file(Path(__file__)),
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
    document = read_json(artifact/'package-source.json')
    package_inputs = inventory({name: read_file(artifact/name, 16*1024**2)
        for name in ('package-source.json', *(layer['source'] for layer in document['layers']))})
    recipe_files = {name: read_file(ROOT/name) for name in ('tools/dotnet_guest/closed_io.py',
        'tools/dotnet_guest/internal_io.py', 'tools/dotnet_guest/composer.py', 'tools/dotnet_guest/compatibility.py')}
    recipe_files['tools/replay_dotnet_console_closed_io.py'] = read_file(Path(__file__))
    recipe = inventory(recipe_files)
    original_observation = read_json(output/'original-build-observation.json')
    proof = {**proof, 'operation': 'component-metadata-derivation', 'nativeAotCompilation': False,
        'metadataRecipeSource': recipe_source, 'inheritedCompilerParametersDescribeAncestry': True,
        'originalObservationDigest': digest(read_file(output/'original-build-observation.json'))}
    write_json(output/'derivation.json', proof)
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
            'console-closed-mandatory-metadata-only-material')
    for name, data in (('source-inputs.json', source_inventory), ('recipe-inputs.json', recipe),
                       ('package-inputs.json', package_inputs)):
        (artifact/name).write_bytes(data)
    raw = (json.dumps(observation, indent=2)+'\n').encode();(artifact/'build-observation.json').write_bytes(raw)
    marker = {'formatVersion': 1, 'componentDigest': selected['sha256'],
        'sourceDigest': digest(source_inventory), 'observationDigest': digest(raw),
        'operation': 'component-metadata-derivation', 'nativeAotCompilation': False}
    (artifact/'BUILD-COMPLETE.json').write_bytes((json.dumps(marker, indent=2)+'\n').encode())
    return marker


def replay(acquired: Path, output: Path, recipe_source: str):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'console-closed-Linux-Python313')
    require(type(recipe_source) is str and re.fullmatch('[0-9a-f]{40}', recipe_source), 'console-closed-recipe-source')
    require(digest(read_file(Path(closed_io.__file__))) == CLOSED_SOURCE, 'console-closed-production-helper-preimage')
    output = fresh(output)
    record = {'schemaVersion': 'latent.dotnet.closed-console-replay.v1', 'status': 'incomplete',
        'nativeAotCompilation': False, 'compiledSource': original.TESTED,
        'productionSource': PRODUCTION, 'recipeSource': recipe_source, 'fullTicketQualification': False,
        'publisherAuthenticated': False, 'releasePublished': False}
    stage = 'original-inputs'
    try:
        require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip() == original.TESTED,
                'console-closed-original-source-checkout')
        normal = acquired/'dotnet-capsule-dependencies'
        binaries, companions, baseline = inherited(normal)
        record['originalNativeInputs'] = baseline
        command_output = fresh(output/'commands')
        commands = Commands(ROOT, command_output, build_environment(output))
        require(shutil.which('wasm-tools') is not None, 'console-closed-pinned-codec-required')
        compiler = SimpleNamespace(wasm=Path(shutil.which('wasm-tools')), commands=commands,
            run=commands.run, generated_materials=[], isolation=None)
        stage = 'original-public-package'
        artifact, proof = original.rebuild_public_package(acquired/'dotnet-standard-console/build', binaries,
            output/'original-public-package', time.monotonic()+600)
        record['originalPublicPackage'] = proof
        stage = 'actual-production-metadata-composition'
        started, started_monotonic = int(time.time()), time.monotonic()
        component, proof = derive(artifact/'component.wasm', read_json(artifact/'build-observation.json'), output/'derivation', compiler)
        record['derivation'] = proof
        stage = 'new-metadata-observation'
        record['newBuild'] = publish_build(artifact, component, proof, output/'build-evidence', commands, recipe_source,
            started=started, elapsed=time.monotonic()-started_monotonic, current_materials=(
                material(compiler.wasm, 'wasm-tools'), material(compiler.wac, 'component-composer'),
                material(binaries['package'], 'packager'), material(binaries['capsule_contracts'], 'contracts-tool')))
        # The original material inventory was checked before any mutation.
        # A fresh package observes the selected component and new observation.
        commands.run('derived-package', binaries['package'], 'build', artifact/'package-source.json', artifact, output/'derived-package')
        shutil.rmtree(artifact/'package')
        shutil.move(str(output/'derived-package'), artifact/'package')
        for name, directory in companions.items():
            commands.run('companion-package-'+name, binaries['package'], 'build', directory/'package-source.json', directory, directory/'package')
        stage = 'fresh-demo-signing'
        builds = [artifact if name == 'greeting' else companions[name] for name in TEMPLATES]
        commands.run('derived-demo-sign', binaries['capsule_authoring'], 'demo-sign', output/'signed', *builds)
        stage = 'signed-original-and-console-programme'
        observed = run(binaries['latent'], binaries['latentd'], output/'signed', output/'node',
            language='dotnet', noncrypto_entropy=True, dotnet_standard_logging=True)
        require(observed['status'] == 'passed' and len(observed['invocations']) == 45
                and len(observed['dotnetStandardConsoleCases']) == 8
                and len(observed['dotnetStandardConsolePhases']) == 3
                and len(observed['dotnetStandardConsoleRecovery']) == 2
                and all(row['processReaped'] for row in observed['invocations'])
                and observed['nodeShutdown']['reaped'] and observed['nodeShutdown']['record']['clean'],
                'console-closed-original-and-console-gates-required')
        require(inherited(normal)[2] == baseline, 'console-closed-original-inputs-changed')
        record.update(status='passed', outcomes=45, workflow=file_identity(output/'node/workflow.json'))
        write_json(output/'qualification.json', record)
        return record
    except BaseException as error:
        guard = error.args[0] if error.args and type(error.args[0]) is str and re.fullmatch(
            r'(?:console-closed|dotnet-closed-io)-[A-Za-z0-9-]{1,120}', error.args[0]) else None
        record.update(status='failed', stage=stage, reason=type(error).__name__, guard=guard)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquired', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--recipe-source', required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.acquired.resolve(), args.output.resolve(), args.recipe_source)))
