"""Keep the passed38 normal products historical; execute only a fresh scratch child."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.build_observation import build_environment
from tools.qualify_sdk_scratch import PRODUCTS, HELPERS, build_component, current_inputs, execution_report, locked_dependencies, package_identity
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.sdk_scratch_fixture import project

ORIGINAL_SOURCE = '38fedd53bb8fc366a9078a3182d88cc03cf0835b'
ORIGINAL_RUN, ORIGINAL_ARTIFACT = 39358494292, 12236803645
QUALIFICATION = 'sha256:87b5664bcca6db0622e2407bf047f3ed30c1f406008370a4ac2cf7a0655fdb9d'
SOURCE_INPUTS = 'sha256:3677ec116d9e47ca3b96542f274b995dd202ba5ff959e7d642afc510d52fbab6'
ORIGINAL_NODE = 'sha256:7727e47ee556712a6cc111aca7dc5ad750060294839c42a2dfe4d3890bcd59d9'


def historical(native):
    require(file_identity(native/'qualification.json')['sha256'] == QUALIFICATION
            and file_identity(native/'source-inputs.json')['sha256'] == SOURCE_INPUTS
            and file_identity(native/'node/workflow.json')['sha256'] == ORIGINAL_NODE,
            'rust-scratch-replay-original-normal-preimages')
    receipt, node = read_json(native/'qualification.json'), read_json(native/'node/workflow.json')
    original, current = read_json(native/'source-inputs.json'), current_inputs('rust')
    require(set(original) == set(current) == {'runtime', 'sdk', 'wit', 'schemas', 'guide', 'helpers'}
            and all(original[name] == current[name] for name in original if name != 'runtime'),
            'rust-scratch-replay-current-nonnative-normal-inputs')
    require(receipt['status'] == 'passed' and receipt['schemaVersion'] == 'latent.rust-capsule.qualification.v1'
            and 'applicationDependencies' not in receipt and receipt['sourceIdentityDigest'] == SOURCE_INPUTS
            and receipt['node']['receiptDigest'] == ORIGINAL_NODE and node['status'] == 'passed'
            and node['language'] == 'rust' and type(node['invocations']) is list and len(node['invocations']) == 27
            and node['nodeShutdown']['reaped'] is True and node['nodeShutdown']['record']['clean'] is True,
            'rust-scratch-replay-passed-original27')
    binaries = {name: native/'native-binaries'/name.replace('/', '-') for name in PRODUCTS}
    identities = {name: file_identity(path, 512*1024**2) for name, path in binaries.items()}
    require(identities == receipt['binaries'], 'rust-scratch-replay-original-native-five')
    companions, packages = {}, {}
    for name in TEMPLATES:
        if name == 'greeting': continue
        location = native/'builds'/name
        marker = read_json(location/'BUILD-COMPLETE.json')
        require(marker == receipt['builds'][name], 'rust-scratch-replay-original-companion-marker')
        packages[name] = package_identity(location, marker)
        companions[name] = location
    return binaries, companions, {
        'originalCompiledSource': ORIGINAL_SOURCE, 'originalRun': ORIGINAL_RUN, 'originalArtifact': ORIGINAL_ARTIFACT,
        'qualification': file_identity(native/'qualification.json'), 'sourceInputs': file_identity(native/'source-inputs.json'),
        'node': file_identity(native/'node/workflow.json'), 'binaries': identities, 'companions': packages,
        'nativeProductsRebuilt': False, 'normalReceiptRewritten': False, 'currentNormalReceiptFabricated': False,
        'currentNonNativeNormalInputsEqual': True}


def replay(native, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'rust-scratch-replay-unprivileged-linux-python313')
    output = output.absolute()
    require(not output.exists() and output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'rust-scratch-replay-fresh-outside-checkout')
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    materials = {name: file_identity(ROOT/name) for name in (*HELPERS, 'tools/replay_rust_scratch.py')}
    record = {'schemaVersion': 'latent.rust-scratch-replay.v1', 'status': 'incomplete', 'language': 'rust',
        'materials': materials, 'fullTicketQualification': False, 'nativeProductsRebuilt': False,
        'filesystemGrantsAdded': False, 'scratchStorageImplemented': False}
    stage = 'authenticated-original-normal'
    try:
        binaries, companions, before = historical(native)
        record['historicalNormal'] = before
        for binary in binaries.values(): binary.chmod(0o700)
        stage = 'ordinary-standard-source'
        app, fixture = project('rust', output/'application'); record['fixture'] = fixture
        source = inventory(snapshot(app))
        stage = 'locked-fixture-dependency-download'
        record['dependencyPreparation'] = locked_dependencies('rust', app, commands)
        stage = 'offline-fresh-component'
        artifact = build_component('rust', app, output/'build', binaries)
        require(read_file(artifact/'source-inputs.json') == source, 'rust-scratch-replay-current-source-observed')
        marker = read_json(artifact/'BUILD-COMPLETE.json'); record['build'] = marker
        package_identity(artifact, marker)
        stage = 'normal-fresh-demo-sign'
        commands.run('rust-scratch-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', output/'signed',
            *(artifact if name == 'greeting' else companions[name] for name in TEMPLATES))
        stage = 'actual-signed-standard-api-results'
        node = run(binaries['latent'], binaries['latentd'], output/'signed', output/'node',
                   language='rust', standard_scratch_refusal=True)
        scratch = node.get('standardScratchRefusal', {})
        require(node['status'] == 'passed' and len(node['invocations']) == 33
                and scratch.get('status') == 'passed' and len(scratch['cases']) == 3
                and all(row['observation']['unsupported'] is True for row in scratch['cases'])
                and node['nodeShutdown']['reaped'] is True and node['nodeShutdown']['record']['clean'] is True,
                'rust-scratch-replay-original27-six-new-concrete-unsupported')
        report = execution_report('rust', artifact, node)
        write_json(output/'compatibility-execution-report.json', report)
        stage = 'final-integrity'
        require(historical(native)[2] == before and inventory(snapshot(app)) == source
                and materials == {name: file_identity(ROOT/name) for name in materials},
                'rust-scratch-replay-inputs-changed')
        record.update(status='passed', invocations=33, scratch=scratch, workflow=file_identity(output/'node/workflow.json'),
            component=file_identity(artifact/'component.wasm', 64*1024**2), commands=commands.records)
        write_json(output/'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': replay(args.native, args.output)['status']}))
