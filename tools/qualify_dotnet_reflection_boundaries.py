"""Actual unsupported-operation reflection with a catalogue-free compiler closure."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as dependencies, dotnet_catalogue_free_build as staging
from tools.build_observation import build_environment
from tools.dotnet_dependency_authoring import source_files
from tools.dotnet_guest.project import create
from tools.dotnet_reflection_fixture import BOUNDARY_ROOTS, install
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_dotnet_reflection import COMPANIONS, REPOSITORY, descriptor_material, prepared_inputs
from tools.qualify_rust_capsules import inputs
from tools.run_rust_capsule_workflow import run as node_workflow
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, write_json

MATERIALS = ('tools/qualify_dotnet_reflection_boundaries.py', 'tools/dotnet_catalogue_free_build.py',
             'tools/qualify_dotnet_reflection.py', 'tools/dotnet_reflection_fixture.py',
             'tools/run_rust_capsule_workflow.py')


def qualify(prepared, output, tools):
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1800, command_seconds=900)
    materials = {name: file_identity(ROOT / name) for name in MATERIALS}
    phase = 'prepared-inputs'
    try:
        before, receipt, products = prepared_inputs(prepared)
        phase = 'ordinary-capture-and-explicit-descriptor-selection'
        project = create(output / 'project', 'greeting')
        captured = install(project, output / 'outside', tools, boundaries=True)
        write_json(output / 'capture.json', captured)
        accepted = dependencies.verify_inputs(project, 'dotnet').lock
        observed = inventory(source_files(project))
        phase = 'bounded-recipe-and-static-support-staging'
        staged = output / 'staged-recipe'
        staged_sources = staging.stage(ROOT, staged)
        write_json(output / 'catalogue-free-source.json', staged_sources)
        phase = 'offline-native-aot-build-from-staged-source-only'
        artifact = output / 'build'
        commands.run('catalogue-free-native-aot', sys.executable, '-I', '-S', '-B', staged / staging.SELF,
            '--project', project, '--output', artifact, '--tools', tools,
            '--contracts-tool', products['examples/capsule_contracts'], '--packager', products['examples/package'],
            '--repository', REPOSITORY, '--expect-source-digest', staged_sources['inventoryDigest'])
        require(staging.verify(staged) == staged_sources and inventory(source_files(project)) == observed
                and dependencies.verify_inputs(project, 'dotnet').lock == accepted,
                'reflection-boundaries-offline-inputs-changed')
        containment = read_json(artifact / 'compiler-containment.json', 32 * 1024 * 1024)
        require(containment['network'] == 'denied' and containment['credentials'] == 'not-inherited',
                'reflection-boundaries-compiler-not-contained')
        recipe = read_json(artifact / 'recipe-inputs.json')
        require(recipe and all(staged_sources['files'].get(name) == row for name, row in recipe.items()),
                'reflection-boundaries-recipe-not-in-staged-closure')
        binding = descriptor_material(artifact, captured['dynamicAssembly'], roots=BOUNDARY_ROOTS)
        phase = 'normal-sign-and-enforced-node'
        require(prepared_inputs(prepared)[:2] == (before, receipt), 'reflection-boundaries-prepared-drift')
        signed = output / 'signed'
        commands.run('reflection-boundaries-sign', products['examples/capsule_authoring'], 'demo-sign', signed, artifact,
                     *(prepared / 'builds' / name for name in COMPANIONS))
        node = node_workflow(products['latent'], products['latentd'], signed, output / 'node',
                            language='dotnet', noncrypto_entropy=True, dotnet_reflection_boundaries=True)
        probe = node['dotnetReflectionBoundaries']
        require(node['status'] == probe['status'] == 'passed' and len(probe['cases']) == 7
                and len(node['invocations']) == 34 and node['nodeShutdown']['reaped'] is True and node['nodeShutdown']['record']['clean'] is True,
                'reflection-boundaries-signed-probe-not-qualified')
        require(before == inputs('dotnet') and prepared_inputs(prepared)[:2] == (before, receipt)
                and staging.verify(staged) == staged_sources
                and materials == {name: file_identity(ROOT / name) for name in MATERIALS}
                and time.monotonic() < commands.deadline, 'reflection-boundaries-final-input-drift')
        result = {'schemaVersion': 'latent.dotnet.reflection-boundaries.qualification.v1', 'status': 'passed',
            'capture': captured, 'descriptorMaterial': binding, 'stagedBuildSource': staged_sources,
            'actualRecipe': file_identity(artifact / 'recipe-inputs.json'),
            'build': read_json(artifact / 'BUILD-COMPLETE.json'), 'materials': materials,
            'preparedSourceIdentityDigest': receipt['sourceIdentityDigest'], 'nativeBinaries': receipt['binaries'],
            'nodeReceipt': file_identity(output / 'node/workflow.json'), 'cases': probe['cases'],
            'originalReflectionCasesRetained': 4, 'additionalUnsupportedAndFreshCases': 3,
            'optionalReferenceDataPresentDuringBuild': False, 'catalogueEligibilityCheck': False,
            'hermetic': False, 'cleanHost': False, 'publisherAuthenticated': False,
            'trapCause': 'not-inferred-from-generic-node-error', 'jitOrCompleteReflectionSupport': False,
            'fullTicketQualification': False}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException as error:
        try:
            write_json(output / 'FAILED.json', {'status': 'failed', 'phase': phase,
                'errorCategory': type(error).__name__, 'materials': materials, 'fullTicketQualification': False})
        except Exception:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-qualification', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tools', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps({'status': qualify(args.prepared_qualification.resolve(), args.output.resolve(), args.tools.resolve())['status']}))
