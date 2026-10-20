"""Fresh ordinary C file refusals with explicitly historical normal products."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_sdk_scratch import PRODUCTS, build_component, execution_report, package_identity
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.sdk_scratch_fixture import project

ORIGINAL_SOURCE = '29b3adf828ba17eb02785849a357bac1d785c4dd'
ORIGINAL_RUN = 39354843145
ORIGINAL_ARTIFACT = 12235113319
QUALIFICATION = 'sha256:1fdaf907bd90543d2e98307e032e635dbaefb18f4b15de37cdb58d04ba168d01'
SOURCE_INPUTS = 'sha256:10d1c94122a045f32d9a01a2dd51a3827f8ce01a084a4bc4b4a17f90ab00415b'
ORIGINAL_NODE = 'sha256:7f0a59eedd9da5af3d857189eb4ee16ad8ebf26ecb7fa0895a216f20bdf587f7'
HELPERS = ('tools/qualify_c_closed_filesystem.py', 'tools/c_guest/closed_filesystem.py',
    'tools/c_guest/compiler.py', 'tools/c_capsule_build.py', 'sdk/c-guest/include/stdio.h',
    'tools/qualify_sdk_scratch.py', 'tools/sdk_scratch_fixture.py', 'tools/sdk_scratch_probe.py',
    'tools/run_rust_capsule_workflow.py', 'tools/rust_capsule_node.py')


def historical(directory):
    """No current-input substitution: the old normal receipt keeps its exact identity."""
    receipt_path, source_path, node_path = (directory/name for name in
        ('qualification.json', 'source-inputs.json', 'node/workflow.json'))
    require(file_identity(receipt_path)['sha256'] == QUALIFICATION
            and file_identity(source_path)['sha256'] == SOURCE_INPUTS
            and file_identity(node_path)['sha256'] == ORIGINAL_NODE, 'c-filesystem-original-preimages')
    receipt, node = read_json(receipt_path), read_json(node_path)
    require(receipt['schemaVersion'] == 'latent.c-capsule.qualification.v1'
            and receipt['status'] == 'passed' and 'applicationDependencies' not in receipt
            and receipt['sourceIdentityDigest'] == SOURCE_INPUTS and receipt['node']['receiptDigest'] == ORIGINAL_NODE
            and node['status'] == 'passed' and node['language'] == 'c'
            and type(node['invocations']) is list and len(node['invocations']) == 27
            and node['nodeShutdown']['reaped'] is True and node['nodeShutdown']['record']['clean'] is True,
            'c-filesystem-original-normal-required')
    binaries = {name: directory/'native-binaries'/name.replace('/', '-') for name in PRODUCTS}
    identities = {name: file_identity(path, 512*1024**2) for name, path in binaries.items()}
    require(identities == receipt['binaries'], 'c-filesystem-original-native-five')
    companions, packages = {}, {}
    for name in TEMPLATES:
        if name == 'greeting': continue
        location = directory/'builds'/name
        marker = read_json(location/'BUILD-COMPLETE.json')
        require(marker == receipt['builds'][name], 'c-filesystem-original-companion-marker')
        packages[name] = package_identity(location, marker)
        companions[name] = location
    return binaries, companions, {'source': ORIGINAL_SOURCE, 'run': ORIGINAL_RUN, 'artifact': ORIGINAL_ARTIFACT,
        'qualification': file_identity(receipt_path), 'sourceInputs': file_identity(source_path),
        'node': file_identity(node_path), 'binaries': identities, 'companions': packages,
        'normalInvocations': 27, 'currentNormalReceiptFabricated': False, 'nativeProductsRebuilt': False}


def qualify(native, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'c-filesystem-unprivileged-linux-python313')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'c-filesystem-output-outside-checkout')
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    material = {name: file_identity(ROOT/name) for name in HELPERS}
    record = {'schemaVersion': 'latent.c-closed-filesystem-qualification.v1', 'status': 'incomplete',
        'materials': material, 'filesystemGrantsAdded': False, 'scratchStorageImplemented': False,
        'nativeProductsRebuilt': False, 'fullTicketQualification': False}
    stage = 'authenticated-historical-products'
    try:
        binaries, companions, before = historical(native)
        record['historicalNormal'] = before
        for binary in binaries.values(): binary.chmod(0o700)
        stage = 'fresh-ordinary-c-source'
        app, fixture = project('c', output/'application')
        source = inventory(snapshot(app)); record['fixture'] = fixture
        stage = 'current-closed-libc-component-build'
        artifact = build_component('c', app, output/'build', binaries)
        require(read_file(artifact/'source-inputs.json') == source, 'c-filesystem-current-source-observed')
        marker = read_json(artifact/'BUILD-COMPLETE.json'); record['build'] = marker
        package_identity(artifact, marker)
        stage = 'fresh-normal-signing'
        commands.run('c-filesystem-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', output/'signed',
            *(artifact if name == 'greeting' else companions[name] for name in TEMPLATES))
        stage = 'actual-signed-standard-stdio'
        node = run(binaries['latent'], binaries['latentd'], output/'signed', output/'node',
                   language='c', standard_scratch_refusal=True)
        scratch = node.get('standardScratchRefusal', {})
        require(node['status'] == 'passed' and len(node['invocations']) == 33
                and scratch.get('status') == 'passed' and len(scratch['cases']) == 3
                and all(row['observation']['unsupported'] is True for row in scratch['cases'])
                and node['nodeShutdown']['reaped'] is True and node['nodeShutdown']['record']['clean'] is True,
                'c-filesystem-original27-six-new-and-concrete-unsupported')
        report = execution_report('c', artifact, node)
        write_json(output/'compatibility-execution-report.json', report)
        stage = 'unchanged-source-and-ancestry'
        require(historical(native)[2] == before and inventory(snapshot(app)) == source
                and {name: file_identity(ROOT/name) for name in HELPERS} == material,
                'c-filesystem-inputs-changed')
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
    print(json.dumps({'status': qualify(args.native, args.output)['status']}))
