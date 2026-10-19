"""Actual descriptor-selected NativeAOT reflection and signed failure boundaries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as dependencies
from tools.build_observation import build_environment
from tools.dotnet_dependency_authoring import source_files
from tools.dotnet_guest.build import build
from tools.dotnet_guest.project import create
from tools.dotnet_reflection_fixture import DESCRIPTOR, LOAD_INPUT, ROOTS, install
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import inputs
from tools.run_rust_capsule_workflow import run as node_workflow
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, write_json

PRODUCTS = ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')
COMPANIONS = ('word-count', 'shipping', 'http-status', 'recovery')
REPOSITORY = 'https://github.com/KirilsTurkins/latent-service-fabric'
MATERIALS = ('tools/qualify_dotnet_reflection.py', 'tools/dotnet_reflection_fixture.py',
             'tools/run_rust_capsule_workflow.py')


def prepared_inputs(prepared):
    receipt = read_json(prepared / 'qualification.json')
    before = inputs('dotnet')
    require(receipt['status'] == 'passed' and 'applicationDependencies' in receipt
            and read_json(prepared / 'source-inputs.json') == before
            and read_file(prepared / 'source-inputs.json') == read_file(prepared / 'source-inputs-after.json')
            and digest(read_file(prepared / 'source-inputs.json')) == receipt['sourceIdentityDigest'],
            'reflection-exact-prepared-source-required')
    require(set(receipt['binaries']) == set(PRODUCTS), 'reflection-five-native-products-required')
    products = {name: prepared / 'native-binaries' / name.replace('/', '-') for name in PRODUCTS}
    require(all(file_identity(path, 512 * 1024 * 1024) == receipt['binaries'][name]
                for name, path in products.items()), 'reflection-native-products-changed')
    require(all(read_json(prepared / 'builds' / name / 'BUILD-COMPLETE.json') == receipt['builds'][name]
                for name in COMPANIONS), 'reflection-companion-build-changed')
    return before, receipt, products


def descriptor_material(artifact, assembly, *, roots=ROOTS):
    """Require the actual compiler selection, source preimage and signed material."""
    identity = {'digest': digest(roots), 'size': len(roots)}
    selected = read_json(artifact / 'nuget-build-inputs.json')
    expected = [{'attributes': {'Include': DESCRIPTOR}, 'active': True, **identity}]
    resources = [{'attributes': {'Include': LOAD_INPUT, 'LogicalName': 'reflection.dynamic-input'},
                  'active': True, **assembly}]
    raw = read_file(artifact / 'nuget-build-inputs.json')
    material = {'name': 'nuget-build-inputs', 'digest': digest(raw), 'size': len(raw)}
    require(selected['trimmingDescriptors'] == expected
            and selected['resources'] == resources
            and read_json(artifact / 'source-inputs.json')[DESCRIPTOR] == identity
            and read_json(artifact / 'source-inputs.json')[LOAD_INPUT] == assembly
            and material in read_json(artifact / 'build-observation.json')['materials'],
            'reflection-compiler-descriptor-not-bound')
    return {'descriptor': identity, 'dynamicAssembly': assembly,
            'compilerSelection': {'digest': material['digest'], 'size': material['size']}}


def qualify(prepared, output, tools):
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1800, command_seconds=900)
    materials = {name: file_identity(ROOT / name) for name in MATERIALS}
    stage = 'prepared-inputs'
    try:
        before, receipt, products = prepared_inputs(prepared)
        stage = 'ordinary-capture-and-descriptor-selection'
        project = create(output / 'project', 'greeting')
        captured = install(project, output / 'outside', tools)
        write_json(output / 'capture.json', captured)
        accepted = dependencies.verify_inputs(project, 'dotnet').lock
        observed = inventory(source_files(project))
        stage = 'offline-native-aot-build'
        artifact = build(project, output / 'build', products['examples/capsule_contracts'],
            products['examples/package'], REPOSITORY, tools=tools, offline=True)
        require(inventory(source_files(project)) == observed
                and dependencies.verify_inputs(project, 'dotnet').lock == accepted,
                'reflection-offline-source-or-lock-changed')
        containment = read_json(artifact / 'compiler-containment.json', 32 * 1024 * 1024)
        require(containment['network'] == 'denied' and containment['credentials'] == 'not-inherited',
                'reflection-compiler-not-contained')
        binding = descriptor_material(artifact, captured['dynamicAssembly'])
        stage = 'normal-sign-and-enforced-node'
        require(prepared_inputs(prepared)[:2] == (before, receipt), 'reflection-prepared-input-drift')
        signed = output / 'signed'
        commands.run('reflection-sign', products['examples/capsule_authoring'], 'demo-sign', signed, artifact,
                     *(prepared / 'builds' / name for name in COMPANIONS))
        node = node_workflow(products['latent'], products['latentd'], signed, output / 'node',
                            language='dotnet', noncrypto_entropy=True, dotnet_reflection=True)
        require(node['status'] == 'passed' and node['dotnetReflection']['status'] == 'passed'
                and len(node['dotnetReflection']['cases']) == 4, 'reflection-signed-probe-not-qualified')
        require(before == inputs('dotnet') and prepared_inputs(prepared)[:2] == (before, receipt)
                and materials == {name: file_identity(ROOT / name) for name in MATERIALS}
                and time.monotonic() < commands.deadline, 'reflection-qualification-input-drift')
        result = {'formatVersion': 1, 'status': 'passed', 'capture': captured, 'descriptorMaterial': binding,
            'build': read_json(artifact / 'BUILD-COMPLETE.json'), 'materials': materials,
            'preparedSourceIdentityDigest': receipt['sourceIdentityDigest'], 'nativeBinaries': receipt['binaries'],
            'nodeReceipt': file_identity(output / 'node/workflow.json'), 'cases': node['dotnetReflection']['cases'],
            'hermetic': False, 'cleanHost': False, 'publisherAuthenticated': False,
            'trapCause': 'not-inferred-from-generic-node-error', 'releasePublication': 'not-performed',
            'jitOrCompleteReflectionSupport': False, 'fullTicketQualification': False}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException as error:
        try:
            write_json(output / 'FAILED.json', {'status': 'failed', 'stage': stage,
                'errorCategory': type(error).__name__, 'materials': materials, 'fullTicketQualification': False})
        except Exception:
            pass  # The observer must preserve the original qualification failure.
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-qualification', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tools', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps({'status': qualify(args.prepared_qualification.resolve(), args.output.resolve(), args.tools.resolve())['status']}))
