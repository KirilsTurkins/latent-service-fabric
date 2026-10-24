"""Normal captured build and six signed unchanged published CommonJS cases.

No compiler/runtime success is inferred from capture, source controls or a lock.
Strict normal typechecking precedes componentization, signing and invocation.
The original failed compiler-product producer retains that status. Retried
engine/splicer inputs must match the current captured SDK through unchanged
normal validators; producer status alone supplies no CommonJS qualification.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import java_phase_native_products as host
from tools import typescript_buffer_commonjs_fixture as fixture
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_typescript_buffer import PRODUCTS, build_evidence, execute
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.typescript_guest.build import build
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE
from tools.build_snapshot import canonical


def dependency_build_evidence(artifact, original, source):
    require(read_file(artifact/'source-inputs.json') == source, 'cjs-normal-source-snapshot-binding')
    dependencies = read_json(artifact/'application-dependencies.json')
    require(dependencies['inputIdentity'] == original['inputIdentity']
        and dependencies['manifestDigest'] == original['manifestDigest']
        and dependencies['lockDigest'] == original['acceptedLock']
        and dependencies['transformations'] == [] and dependencies['networkResolution'] is False,
        'cjs-normal-offline-build-closure-binding')
    selected = read_json(artifact/'bundle-selected-inputs.json')
    captured = selected['capturedInputs']
    for name in ('buffer-xor/index.js', 'safe-buffer/index.js'):
        rows = [row for row in captured if row['path'] == 'dependencies/npm/node_modules/'+name]
        require(len(rows) == 1 and rows[0]['digest'] == fixture.SOURCE_FILES[name],
                'cjs-actual-unchanged-commonjs-bundle-input')
    require('lsf-owned-node-buffer:node:buffer' in selected['inputs'], 'cjs-actual-owned-buffer-bundle-input')
    require(selected['selection']['inputIdentity'] == original['inputIdentity']
        and selected['selection']['conditions'] == []
        and selected['selection']['commonJs'] == 'static-require-only', 'cjs-normal-module-selection')
    observation = read_json(artifact/'build-observation.json')
    documents = {}
    for name in ('application-dependencies.json', 'npm-inputs.json', 'bundle-selected-inputs.json'):
        identity = file_identity(artifact/name, 32*1024**2)
        matches = [row for row in observation['materials'] if row['name'] == name.removesuffix('.json')]
        require(matches == [{'name': name.removesuffix('.json'), 'digest': identity['sha256'], 'size': identity['bytes']}],
                'cjs-normal-dependency-material-binding')
        documents[name] = identity
    return documents


def typecheck_layout_evidence(artifact, original):
    layout = read_json(artifact/'compiler-containment.json')['typeScriptNodeModulesAlias']
    tree = original['moduleTree']
    expected = {'phase': 'typecheck', 'access': 'read-only', 'source': 'project/'+tree['mount'],
        'destination': 'project/node_modules', 'inputIdentity': original['inputIdentity'],
        'treeDigest': tree['digest'], 'files': tree['files'], 'bytes': tree['bytes']}
    require(canonical(layout) == canonical(expected), 'cjs-original-readonly-typecheck-layout')
    identity = file_identity(artifact/'compiler-containment.json', 32*1024**2)
    matches = [row for row in read_json(artifact/'build-observation.json')['materials']
               if row['name'] == 'compiler-containment']
    require(matches == [{'name': 'compiler-containment', 'digest': identity['sha256'], 'size': identity['bytes']}],
            'cjs-typecheck-layout-material-binding')
    return identity


def standard_type_evidence(artifact, project):
    from tools.application_dependencies import verify_inputs
    from tools.typescript_guest import standard_global_types as types
    provider = types.select(verify_inputs(project, 'typescript'))
    require(provider is not None, 'cjs-original-standard-type-provider')
    _runtime, _clock, expected = types.compose(provider, read_file(ROOT/types.RUNTIME), read_file(ROOT/types.CLOCK))
    require(canonical(read_json(artifact/types.RECEIPT,65536)) == canonical(expected), 'cjs-standard-type-view-source-binding')
    bindings = read_json(artifact/'bindings.json')['files']
    for name, value in expected['derived'].items():
        rows = [row for row in bindings if row['path'] == name]
        require(canonical(rows) == canonical([{'path':name,'sha256':value['digest'],'bytes':value['size']}]),
                'cjs-actual-generated-standard-type-view')
    identity = file_identity(artifact/types.RECEIPT,65536)
    rows = [row for row in read_json(artifact/'build-observation.json')['materials']
            if row['name'] == 'typescript-standard-global-types']
    require(canonical(rows) == canonical([{'name':'typescript-standard-global-types','digest':identity['sha256'],'size':identity['bytes']}]),
            'cjs-standard-type-view-material-binding')
    layers = [row for row in read_json(artifact/'package-source.json')['layers'] if row['source'] == types.RECEIPT]
    require(layers == [{'path':types.RECEIPT,'source':types.RECEIPT,'role':'asset',
        'mediaType':'application/vnd.latent.typescript.standard-global-types.v1+json'}], 'cjs-standard-type-view-signed-asset')
    return identity


def qualify(project, output, tools, engine, splicer, prepared_native):
    project, output, tools, engine, splicer, prepared_native = (
        Path(path).resolve() for path in (project, output, tools, engine, splicer, prepared_native))
    require(output != ROOT and ROOT not in output.parents, 'cjs-output-outside-checkout')
    require(all(output != path and output not in path.parents and path not in output.parents
        for path in (project, tools, engine, splicer, prepared_native)), 'cjs-input-output-separation')
    output = fresh(output)
    stage = 'verify-normal-captured-published-inputs'
    try:
        files = snapshot(project)
        fixture.verify_probe(files)
        source = inventory(files)
        original_dependencies = fixture.provenance(project)
        original_native = host.verify_prepared(prepared_native)
        originals = host.native_products(prepared_native)
        require(set(originals) == set(PRODUCTS), 'cjs-normal-five-host-products')
        write_json(output/'native-inputs.json', original_native)
        write_json(output/'published-inputs.json', original_dependencies)
        selected = fresh(output/'selected-native')
        binaries = {name: selected/name for name in PRODUCTS}
        identities = {name: file_identity(path, 512*1024**2) for name, path in originals.items()}
        for name, original in originals.items():
            shutil.copyfile(original, binaries[name]); binaries[name].chmod(0o700)
        require(identities == {name: file_identity(path, 512*1024**2) for name, path in binaries.items()},
                'cjs-host-copy-byte-identity')
        # This maintained build performs the actual strict tsc check, esbuild,
        # componentization and normal packaging in order. A type failure raises
        # here; it cannot reach signing, admission or any host invocation below.
        stage = 'normal-strict-typecheck-bundle-component-package'
        artifact = build(project, output/'build', binaries['capsule_contracts'], binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools,
            runtime_engine=engine/'engine.wasm', runtime_engine_receipt=engine/'engine-input.json',
            runtime_splicer=splicer/'splicer', runtime_splicer_receipt=splicer/'splicer-input.json')
        require(fixture.provenance(project) == original_dependencies, 'cjs-captured-inputs-before-signing')
        build_evidence(artifact)
        actual_dependencies = dependency_build_evidence(artifact, original_dependencies, source)
        actual_layout = typecheck_layout_evidence(artifact, original_dependencies)
        actual_types = standard_type_evidence(artifact, project)
        stage = 'six-signed-published-commonjs-cases'
        observed = execute(artifact, binaries, output/'node', cases=fixture.CASES, scope=fixture.SCOPE)
        require(host.verify_prepared(prepared_native) == original_native
            and identities == {name: file_identity(path, 512*1024**2) for name, path in binaries.items()}
            and source == inventory(snapshot(project)) and fixture.provenance(project) == original_dependencies,
            'cjs-all-original-inputs-unchanged')
        require(dependency_build_evidence(artifact, original_dependencies, source) == actual_dependencies,
                'cjs-build-dependency-evidence-unchanged')
        require(typecheck_layout_evidence(artifact, original_dependencies) == actual_layout,
                'cjs-typecheck-layout-evidence-unchanged')
        require(standard_type_evidence(artifact, project) == actual_types, 'cjs-standard-type-view-unchanged')
        require([row['case'] for row in observed['cases']] == list(fixture.CASES), 'cjs-six-actual-cases')
        result = {'schemaVersion': 'latent.typescript.published-commonjs-buffer.v1', 'status': 'passed',
            'fullTicketQualification': False, 'runtimeProfile': IMPORT_PROFILE,
            'sourceIdentityDigest': digest(source), 'publishedInputs': original_dependencies,
            'dependencyBuildEvidence': actual_dependencies,
            'typecheckModuleLayout': actual_layout,
            'standardGlobalTypes': actual_types,
            'component': file_identity(artifact/'component.wasm'),
            'build': file_identity(artifact/'BUILD-COMPLETE.json'),
            'execution': file_identity(output/'node/qualification.json'),
            'cases': list(fixture.CASES),
            'remainingAcceptance': ['published-inplace-subpath-types-and-execution', 'two-HTTP-clients',
                'node-net-Socket', 'Duplex-backpressure', 'typed-result-disposal', 'destroy-cancel-unref-root-lifecycle']}
        # Original capture's runtimeQualification=pending is historical capture
        # scope; this separate result binds the actual successful execution.
        write_json(output/'qualification.json', result)
        return result
    except BaseException:
        write_json(output/'FAILED.json', {'status': 'failed', 'stage': stage,
            'fullTicketQualification': False, 'runtimeQualification': 'not-established'})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'output', 'tools', 'engine', 'splicer', 'prepared-native'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.project, args.output, args.tools, args.engine, args.splicer, args.prepared_native)))
