"""Captured ordinary Go entropy, offline compilation and same-product signed node."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.dev_workflow.common import require
from tools.go_capsule_project import create
from tools.go_capsule_build import build
from tools.go_standard_entropy_fixture import CHILD, PROFILE, install
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import inputs
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_json, snapshot, write_json

PRODUCTS = ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')
HELPERS = ('tools/qualify_go_standard_entropy.py', 'tools/go_standard_entropy_fixture.py',
           'tools/go_standard_entropy_probe.py', 'tools/run_rust_capsule_workflow.py',
           'tools/go_native_authoring.py', 'tools/go_application_dependencies.py', 'tools/go_capsule_build.py')


def prepared(directory: Path):
    receipt_path = directory / 'qualification.json'
    receipt = read_json(receipt_path)
    require(receipt.get('schemaVersion') == 'latent.go-capsule.qualification.v1'
            and receipt.get('status') == 'passed', 'go-entropy-normal-qualification-required')
    source = directory / 'source-inputs.json'
    require(digest(source.read_bytes()) == receipt['sourceIdentityDigest']
            and read_json(source) == inputs('go'), 'go-entropy-prepared-source-mismatch')
    binaries = {name: directory / 'native-binaries' / name.replace('/', '-') for name in PRODUCTS}
    observed = {name: file_identity(path, 512 * 1024 * 1024) for name, path in binaries.items()}
    require(all(observed[name] == receipt['binaries'][name] for name in PRODUCTS),
            'go-entropy-prepared-native-mismatch')
    companions, bound = {}, {}
    for name in TEMPLATES:
        if name == 'greeting': continue
        location = directory / 'builds' / name
        marker = read_json(location / 'BUILD-COMPLETE.json')
        require(marker == receipt['builds'][name], 'go-entropy-companion-marker-mismatch')
        for filename, field in (('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'),
                                 ('build-observation.json', 'observationDigest')):
            identity = file_identity(location / filename, 64 * 1024 * 1024)
            require(identity['sha256'] == marker[field], 'go-entropy-companion-bytes-mismatch')
            bound[name + '/' + filename] = identity
        companions[name] = location
    return binaries, companions, {'qualification': file_identity(receipt_path),
        'sourceInputs': file_identity(source), 'binaries': observed, 'companions': bound}


def selected_packages(value: dict):
    rows = value['packages']
    require(isinstance(rows, list) and len(rows) <= 4096, 'go-entropy-compiled-package-bound')
    for name in ('crypto/rand', 'syscall'):
        selected = [row for row in rows if row['importPath'] == name]
        require(len(selected) == 1 and selected[0]['standard'] is True,
                'go-entropy-ordinary-standard-package-required')
    resource = [row for row in rows if row['importPath'] == CHILD]
    require(len(resource) == 1 and resource[0]['standard'] is False
            and resource[0]['embedFiles'] == ['message.txt'], 'go-entropy-compiled-transitive-resource-required')
    return {'standardAPIs': ['crypto/rand', 'syscall'], 'resource': resource[0],
            'packageObservationDigest': digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())}


def qualify(output: Path, native_qualification: Path):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'go-entropy-linux-python313')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'go-entropy-output-outside-checkout')
    output = fresh(output)
    source = {name: file_identity(ROOT / name) for name in HELPERS}
    record = {'schemaVersion': 'latent.go.standard-entropy-qualification.v1', 'status': 'in-progress',
        'helpers': source, 'runtimeProfile': PROFILE, 'backendChanged': False,
        'fullTicketQualification': False, 'publisherAuthenticated': False, 'releasePublished': False,
        'randomPayloadRetained': False, 'fipsCertification': False,
        'limits': {'componentOverallSeconds': 900, 'nodeOverallSeconds': 900,
                   'randomPolicyOperations': 4096, 'randomPolicyOutputBytes': 32768}}
    stage = 'prepared-products'
    try:
        binaries, companions, inherited = prepared(native_qualification)
        record['inherited'] = inherited
        compiler = shutil.which('go')
        require(compiler is not None, 'go-entropy-pinned-compiler-required')
        stage = 'outside-capture-and-exact-review'
        app = create(output / 'project', 'greeting', runtime_profile=PROFILE)
        captured = install(app, output / 'outside', Path(compiler).resolve(strict=True))
        write_json(output / 'capture.json', captured)
        require(captured['originalsRemoved'], 'go-entropy-original-source-still-present')
        original = inventory(snapshot(app))
        stage = 'isolated-offline-component'
        artifact = build(app, output / 'build', binaries['examples/capsule_contracts'],
            binaries['examples/package'], 'https://github.com/KirilsTurkins/latent-service-fabric')
        require((artifact / 'source-inputs.json').read_bytes() == original,
                'go-entropy-application-source-inventory-mismatch')
        record['selectedPackages'] = selected_packages(read_json(artifact / 'go-module-build-inputs.json'))
        containment = read_json(artifact / 'compiler-containment.json')
        require(containment.get('network') == 'denied', 'go-entropy-offline-compiler-network-required')
        record['compilerContainment'] = containment
        record['build'] = read_json(artifact / 'BUILD-COMPLETE.json')
        stage = 'same-products-signing'
        commands = Commands(ROOT, output, build_environment(output))
        commands.run('entropy-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', output / 'signed',
            *(artifact if name == 'greeting' else companions[name] for name in TEMPLATES))
        require(prepared(native_qualification)[2] == inherited, 'go-entropy-prepared-inputs-changed')
        stage = 'ordinary-signed-node'
        node = run(binaries['latent'], binaries['latentd'], output / 'signed', output / 'node',
                   language='go', go_standard_entropy=True)
        require(node['status'] == 'passed' and len(node['invocations']) == 43
                and len(node['goStandardEntropy']['cases']) == 8
                and len(node['goStandardEntropy']['recovery']) == 3
                and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
                'go-entropy-original-and-new-signed-outcomes-required')
        stage = 'final-integrity'
        require(prepared(native_qualification)[2] == inherited and inventory(snapshot(app)) == original
                and {name: file_identity(ROOT / name) for name in HELPERS} == source,
                'go-entropy-input-mutated')
        record.update(status='passed', invocations=len(node['invocations']),
            workflow=file_identity(output / 'node/workflow.json'), component=file_identity(artifact / 'component.wasm'),
            commands=commands.records)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-qualification', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': qualify(args.output, args.native_qualification)['status']}))
