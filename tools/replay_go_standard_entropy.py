"""Re-sign and replay the unchanged 42a Go entropy component; no compiler."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.go_capsule_project import create
from tools.go_standard_entropy_fixture import PROFILE
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import inputs
from tools.qualify_go_standard_entropy import PRODUCTS
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, snapshot, write_json

TESTED = '42a2dadf1cd77b3dda65ec4720a4ce973c5e4813'
COMPONENT = {'sha256': 'sha256:72fe32bc6769271fe37655a1f86be49d892c86ad1af28932c4e43ab571a53a78', 'bytes': 2877505}
RUNNER = 'run_rust_capsule_workflow.py'
BEFORE = b'entropy_admission(client, fixture, targets, publications, result)'
AFTER = BEFORE + b'\n                        from tools.go_standard_entropy_probe import buffer_authority\n                        buffer_authority(client, fixture, targets, publications, result)'


def historical_source(original: dict, current: dict, original_runner: bytes, current_runner: bytes):
    """Only the reviewed explicit authority selection differs from compiled inputs."""
    require(original_runner.count(BEFORE) == 1 and original_runner.count(AFTER) == 0
            and current_runner == original_runner.replace(BEFORE, AFTER, 1),
            'go-entropy-replay-reviewed-runner-delta')
    def identity(raw): return {'sha256': digest(raw), 'bytes': len(raw)}
    require(original['helpers'][RUNNER] == identity(original_runner)
            and current['helpers'][RUNNER] == identity(current_runner),
            'go-entropy-replay-runner-source-identity')
    selected = copy.deepcopy(current)
    selected['helpers'][RUNNER] = original['helpers'][RUNNER]
    require(selected == original, 'go-entropy-replay-other-production-source-drift')
    return {'compiledSourceCommit': TESTED, 'originalRunner': identity(original_runner),
            'currentRunner': identity(current_runner), 'otherPreparedSourceFieldsUnchanged': True}


def prepared(directory: Path):
    receipt_path = directory / 'qualification.json'
    receipt = read_json(receipt_path)
    require(receipt['schemaVersion'] == 'latent.go-capsule.qualification.v1' and receipt['status'] == 'passed',
            'go-entropy-replay-normal-qualified')
    source = directory / 'source-inputs.json'
    require(digest(read_file(source)) == receipt['sourceIdentityDigest'], 'go-entropy-replay-normal-source-binding')
    original_runner = subprocess.check_output(['git', 'show', TESTED + ':tools/' + RUNNER], cwd=ROOT, timeout=15)
    proof = historical_source(read_json(source), inputs('go'), original_runner, read_file(ROOT / 'tools' / RUNNER))
    node_path = directory / 'node/workflow.json'
    node = read_json(node_path)
    require(digest(read_file(node_path)) == receipt['node']['receiptDigest'] and node['status'] == 'passed'
            and len(node['invocations']) == 27 and all(row['processReaped'] for row in node['invocations'])
            and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
            'go-entropy-replay-original-normal-node-proof')
    binaries = {name: directory / 'native-binaries' / name.replace('/', '-') for name in PRODUCTS}
    identities = {name: file_identity(path, 512 * 1024**2) for name, path in binaries.items()}
    require(all(identity == receipt['binaries'][name] for name, identity in identities.items()),
            'go-entropy-replay-original-native-tuple')
    companions, bound = {}, {}
    for name in TEMPLATES:
        if name == 'greeting': continue
        path = directory / 'builds' / name
        complete = read_json(path / 'BUILD-COMPLETE.json')
        require(complete == receipt['builds'][name], 'go-entropy-replay-original-companion-marker')
        for filename, field in (('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'),
                                 ('build-observation.json', 'observationDigest')):
            identity = file_identity(path / filename, 64 * 1024**2)
            require(identity['sha256'] == complete[field], 'go-entropy-replay-original-companion-bytes')
            bound[name + '/' + filename] = identity
        companions[name] = path
    return binaries, companions, {'qualification': file_identity(receipt_path), 'sourceInputs': file_identity(source),
        'normalNode': file_identity(node_path), 'normalNodeInvocations': 27,
        'historicalSource': proof, 'binaries': identities, 'companions': bound}


def packages(acquired: Path, output: Path, binaries: dict, companions: dict, commands):
    original = acquired / 'go-standard-entropy/build'
    marker = read_json(original / 'BUILD-COMPLETE.json')
    require(file_identity(original / 'component.wasm', 16 * 1024**2) == COMPONENT
            and marker['componentDigest'] == COMPONENT['sha256']
            and marker['sourceDigest'] == digest(read_file(original / 'source-inputs.json'))
            and marker['observationDigest'] == digest(read_file(original / 'build-observation.json')),
            'go-entropy-replay-original-component-and-build')
    source = read_json(original / 'source-inputs.json')
    project = create(output / 'public-project', 'greeting', runtime_profile=PROFILE)
    wit = {name: raw for name, raw in snapshot(project).items() if name.startswith('wit/')}
    require(set(wit) == {name for name in source if name.startswith('wit/')}, 'go-entropy-replay-original-WIT-set')
    for name, raw in wit.items():
        require(source[name] == {'digest': digest(raw), 'size': len(raw)}, 'go-entropy-replay-original-WIT-byte')
        destination = original / name; destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(raw)
    for directory in [original, *companions.values()]:
        document = read_json(directory / 'package-source.json')
        names = ['package-source.json', *(row['source'] for row in document['layers'])]
        require(len(names) == len(set(names)) <= 32 and all(type(name) is str and not name.startswith('/')
            and '\\' not in name and ':' not in name and all(p not in {'', '.', '..'} for p in name.split('/'))
            for name in names), 'go-entropy-replay-public-package-paths')
        files = {name: read_file(directory / name, 64 * 1024**2) for name in names}
        require(inventory(files) == read_file(directory / 'package-inputs.json'),
                'go-entropy-replay-exact-original-package-layers')
        commands.run('package-' + directory.name, binaries['examples/package'], 'build',
                     directory / 'package-source.json', directory, directory / 'package')
    return original, file_identity(original / 'package-inputs.json')


def replay(acquired: Path, output: Path):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'go-entropy-replay-linux-python313')
    output = fresh(output)
    record = {'schemaVersion': 'latent.go.entropy-policy-replay.v1', 'status': 'incomplete',
        'compiledSourceCommit': TESTED, 'component': COMPONENT, 'newCompilation': False,
        'normalReceiptRewritten': False, 'backendChanged': False, 'fullTicketQualification': False,
        'publisherAuthenticated': False, 'releasePublished': False}
    stage = 'historical-normal-inputs'
    try:
        baseline = acquired / 'go-capsule-dependencies'
        binaries, companions, inherited = prepared(baseline)
        record['inherited'] = inherited
        record['replaySource'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=15).decode().strip()
        commands = Commands(ROOT, output, build_environment(output))
        stage = 'unchanged-component-and-public-package-layers'
        original, package_identity = packages(acquired, output, binaries, companions, commands)
        record['originalPackageInputs'] = package_identity
        stage = 'fresh-normal-signing'
        commands.run('entropy-policy-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', output / 'signed',
            *(original if name == 'greeting' else companions[name] for name in TEMPLATES))
        stage = 'corrected-authority-signed-node'
        node = run(binaries['latent'], binaries['latentd'], output / 'signed', output / 'node',
                   language='go', go_standard_entropy=True)
        require(node['status'] == 'passed' and len(node['invocations']) == 43
                and len(node['goStandardEntropy']['cases']) == 8 and len(node['goStandardEntropy']['recovery']) == 3
                and all(row['processReaped'] for row in node['invocations'])
                and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
                'go-entropy-replay-original-and-new-signed-programme')
        stage = 'final-original-identity'
        require(prepared(baseline)[2] == inherited and file_identity(original / 'component.wasm', 16 * 1024**2) == COMPONENT
                and file_identity(original / 'package-inputs.json') == package_identity,
                'go-entropy-replay-original-inputs-changed')
        record.update(status='passed', invocations=43, workflow=file_identity(output / 'node/workflow.json'), commands=commands.records)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquired', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': replay(args.acquired.resolve(), args.output.resolve())['status']}))
