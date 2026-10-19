"""Fresh entropy build and current host, with explicitly historical companions.

The original normal receipt remains immutable and historical. A new normal
27-call run precedes the new 43-outcome campaign on the freshly built host.
This does not replace the original complete Go qualification workflow.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.go_capsule_build import build
from tools.go_capsule_project import create
from tools.go_entropy_replay_inputs import TESTED, ARTIFACT
from tools.go_standard_entropy_fixture import PROFILE, install
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_go_standard_entropy import PRODUCTS, selected_packages
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, snapshot, write_json


def compiler_inputs(directory):
    """Bind the fixed source-run tools manifest and the reviewed Go archive."""
    pins = read_json(ROOT/'sdk/go-guest/toolchain.lock.json')
    archive = file_identity(directory/'go.tar.gz', 128*1024**2)
    require(archive['sha256'] == 'sha256:'+pins['go']['linuxAmd64']['sha256'],
            'go-entropy-retained-Go-archive-preimage')
    lines = read_file(directory/'tools.sha256', 4096).decode('ascii').splitlines()
    require(len(lines) == 2, 'go-entropy-retained-tool-manifest-count')
    observed = {}
    for line in lines:
        fields = line.split('  ')
        require(len(fields) == 2 and re.fullmatch('[0-9a-f]{64}', fields[0])
                and fields[1].startswith('/') and '\\' not in fields[1],
                'go-entropy-retained-tool-manifest-shape')
        name = Path(fields[1]).name
        require(name in {'componentize-go', 'wasm-tools'} and name not in observed,
                'go-entropy-retained-tool-manifest-selection')
        actual = file_identity(directory/name, 128*1024**2)
        require(actual['sha256'] == 'sha256:'+fields[0], 'go-entropy-retained-tool-bytes')
        observed[name] = actual
        (directory/name).chmod(0o700)
    return {'artifactId': 12215479048, 'runId': 39310234677, 'goArchive': archive, 'tools': observed}


def historical(acquired):
    acquisition = read_json(acquired/'acquisition.json')
    require(acquisition['artifactId'] == ARTIFACT and acquisition['testedSource'] == TESTED
            and acquisition['normalGreetingIncluded'] is True
            and acquisition['completeArchiveDownloaded'] is False
            and acquisition['credentialsRetained'] is False, 'go-entropy-retained-acquisition')
    normal = acquired/'go-capsule-dependencies'
    receipt = read_json(normal/'qualification.json')
    node_path = normal/'node/workflow.json'
    node = read_json(node_path)
    require(receipt['schemaVersion'] == 'latent.go-capsule.qualification.v1' and receipt['status'] == 'passed'
            and receipt['sourceIdentityDigest'] == digest(read_file(normal/'source-inputs.json'))
            and digest(read_file(node_path)) == receipt['node']['receiptDigest']
            and node['status'] == 'passed' and len(node['invocations']) == 27
            and all(row['processReaped'] for row in node['invocations'])
            and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
            'go-entropy-retained-historical-normal-proof')
    binaries = {name: normal/'native-binaries'/name.replace('/', '-') for name in PRODUCTS}
    observed = {name: file_identity(path, 512*1024**2) for name, path in binaries.items()}
    require(all(observed[name] == receipt['binaries'][name] for name in PRODUCTS),
            'go-entropy-retained-historical-binaries')
    builds, bound = {}, {}
    for name in TEMPLATES:
        location = normal/'builds'/name
        marker = read_json(location/'BUILD-COMPLETE.json')
        require(marker == receipt['builds'][name], 'go-entropy-retained-original-marker')
        for filename, field in (('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'),
                                 ('build-observation.json', 'observationDigest')):
            require(digest(read_file(location/filename, 64*1024**2)) == marker[field],
                    'go-entropy-retained-original-build-binding')
        document = read_json(location/'package-source.json')
        names = ['package-source.json', *(row['source'] for row in document['layers'])]
        require(len(names) == len(set(names)) <= 32 and all(type(part) is str and not part.startswith('/')
                and ':' not in part and '\\' not in part
                and all(piece not in {'', '.', '..'} for piece in part.split('/')) for part in names),
                'go-entropy-retained-package-layer-paths')
        require(inventory({part: read_file(location/part, 64*1024**2) for part in names})
                == read_file(location/'package-inputs.json'), 'go-entropy-retained-original-package-inputs')
        builds[name] = location
        bound[name] = marker
    return binaries, builds, {'compiledSource': TESTED, 'qualification': file_identity(normal/'qualification.json'),
        'sourceInputs': file_identity(normal/'source-inputs.json'), 'node': file_identity(node_path),
        'nativeBinaries': observed, 'builds': bound, 'currentNormalReceiptFabricated': False}


def current_host(output, commands):
    before = source_identity(ROOT)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=15).decode().strip()
    require(re.fullmatch('[0-9a-f]{40}', head), 'go-entropy-retained-current-source')
    raw = commands.run('current-ordinary-host-build', 'cargo', 'build', '--locked', '-p', 'latentd',
                       '--bin', 'latentd', '--message-format=json')
    rows = [json.loads(line) for line in raw.splitlines()]
    finished = [row for row in rows if row.get('reason') == 'build-finished']
    selected = [row for row in rows if row.get('reason') == 'compiler-artifact'
                and row['target']['name'] == 'latentd' and 'bin' in row['target']['kind'] and row.get('executable')]
    require(len(finished) == len(selected) == 1 and finished[0]['success'] is True
            and not selected[0]['features'], 'go-entropy-retained-ordinary-host-only')
    source = Path(selected[0]['executable'])
    expected = file_identity(source, 512*1024**2)
    owned = output/'current-latentd';shutil.copyfile(source, owned);owned.chmod(0o700)
    require(file_identity(owned, 512*1024**2) == expected and source_identity(ROOT) == before,
            'go-entropy-retained-current-host-changed')
    proof = {'compiledSource': head, 'sourceIdentity': before, 'binary': expected,
        'features': [], 'ordinaryDefaults': True, 'originalCliAndCompanionsRecompiled': False}
    write_json(output/'current-host.json', proof)
    return owned, proof


def qualify(acquired, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'go-entropy-retained-Linux-Python313')
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1950, command_seconds=1800)
    record = {'schemaVersion': 'latent.go.retained-entropy-qualification.v1', 'status': 'incomplete',
        'fullTicketQualification': False, 'publisherAuthenticated': False, 'releasePublished': False,
        'originalNormalReceiptRewritten': False, 'randomPayloadRetained': False}
    stage = 'historical-normal-proof'
    try:
        binaries, builds, original = historical(acquired)
        record['historicalInputs'] = original
        stage = 'current-ordinary-host'
        host, record['currentHost'] = current_host(output, commands)
        stage = 'unchanged-baseline-repackaging'
        for name, location in builds.items():
            commands.run('original-package-'+name, binaries['examples/package'], 'build',
                         location/'package-source.json', location, location/'package')
        commands.run('original-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', output/'signed-normal',
                     *(builds[name] for name in TEMPLATES))
        stage = 'actual-normal-27-on-current-host'
        normal = run(binaries['latent'], host, output/'signed-normal', output/'node-normal', language='go')
        require(normal['status'] == 'passed' and len(normal['invocations']) == 27
                and all(row['processReaped'] for row in normal['invocations'])
                and normal['nodeShutdown']['reaped'] and normal['nodeShutdown']['record']['clean'],
                'go-entropy-retained-actual-normal-27-required')
        record['currentHostNormal'] = {'outcomes': 27, 'receipt': file_identity(output/'node-normal/workflow.json')}
        stage = 'fresh-outside-library-capture'
        go = Path(shutil.which('go') or 'missing-pinned-go').resolve(strict=True)
        application = create(output/'project', 'greeting', runtime_profile=PROFILE)
        write_json(output/'capture.json', install(application, output/'outside', go))
        before = inventory(snapshot(application))
        stage = 'fresh-offline-entropy-component'
        artifact = build(application, output/'build', binaries['examples/capsule_contracts'],
            binaries['examples/package'], 'https://github.com/KirilsTurkins/latent-service-fabric')
        require((artifact/'source-inputs.json').read_bytes() == before
                and inventory(snapshot(application)) == before
                and read_json(artifact/'compiler-containment.json')['network'] == 'denied',
                'go-entropy-retained-fresh-offline-source-required')
        record['selectedPackages'] = selected_packages(read_json(artifact/'go-module-build-inputs.json'))
        record['freshBuild'] = read_json(artifact/'BUILD-COMPLETE.json')
        stage = 'fresh-signing-and-43-outcomes'
        commands.run('entropy-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', output/'signed-entropy',
                     *(artifact if name == 'greeting' else builds[name] for name in TEMPLATES))
        node = run(binaries['latent'], host, output/'signed-entropy', output/'node-entropy', language='go', go_standard_entropy=True)
        require(node['status'] == 'passed' and len(node['invocations']) == 43
                and len(node['goStandardEntropy']['cases']) == 8 and len(node['goStandardEntropy']['recovery']) == 3
                and all(row['processReaped'] for row in node['invocations'])
                and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
                'go-entropy-retained-actual-43-required')
        require(historical(acquired)[2] == original and file_identity(host, 512*1024**2) == record['currentHost']['binary']
                and source_identity(ROOT) == record['currentHost']['sourceIdentity'],
                'go-entropy-retained-final-inputs-changed')
        record.update(status='passed', outcomes=43, workflow=file_identity(output/'node-entropy/workflow.json'))
        write_json(output/'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquired', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.acquired.resolve(), args.output.resolve())))
