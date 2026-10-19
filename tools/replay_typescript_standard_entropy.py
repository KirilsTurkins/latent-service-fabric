"""Re-sign the unchanged 02f components under the corrected explicit policy case."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.go_entropy_replay_inputs import NoRedirect, Remote
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, write_json

TESTED = '02fbe2f9ed5c2cec6f568ebc7cce99216a12631e'
ARTIFACT, RUN = 12222984675, 39319524998
QUALIFICATION = 'sha256:f9aded6b7b0ba702d9ec105d30320a0b2d44c22a2ab090e88e1bc1e813bda778'
NORMAL = '_temp/typescript-capsule-dependencies/'
ENTROPY = '_temp/typescript-standard-entropy/'
PRODUCTS = ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')
PUBLIC = frozenset({'BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json', 'recipe-inputs.json',
    'package-inputs.json', 'package-source.json', 'component.wasm', 'capsule.json', 'contracts.json',
    'wit-lock.json', 'compatibility-report.json', 'deployment.json', 'typescript-entropy-selection.json'})
COMPONENTS = {
    'greeting': 'sha256:6713f6b5dffc511d7f879e816d629e3ffccd2243a5f24ef15249491275b61cc6',
    'word-count': 'sha256:e233e6985c717740c1d222a0de46ad3b6eedc2d6e2d0e5129b497b9dcba6a177',
}


def selected(name):
    if type(name) is not str or '\\' in name or ':' in name or any(p in {'', '.', '..'} for p in name.split('/')):
        return False
    if name in {NORMAL+p for p in ('qualification.json', 'source-inputs.json', 'source-inputs-after.json', 'node/workflow.json')}:
        return True
    if name in {NORMAL+'native-binaries/'+p.replace('/', '-') for p in PRODUCTS}:
        return True
    for label in TEMPLATES:
        prefix = ENTROPY+'build-'+label+'/' if label in COMPONENTS else NORMAL+'builds/'+label+'/'
        if name.startswith(prefix):
            suffix = name.removeprefix(prefix)
            return suffix in PUBLIC or re.fullmatch(r'wit/(?:[a-z0-9-]+/){0,3}[a-z0-9_.-]+\.wit', suffix) is not None
    return False


def acquire(output):
    output = fresh(output)
    credential = os.environ.get('GH_TOKEN')
    require(type(credential) is str and 0 < len(credential) <= 4096, 'typescript-entropy-replay-read-credential')
    endpoint = f'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/{ARTIFACT}'
    headers = {'Authorization': 'Bearer '+credential, 'Accept': 'application/vnd.github+json'}
    with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers), timeout=30) as response:
        require(response.status == 200, 'typescript-entropy-replay-metadata-status')
        raw = response.read(65537)
    require(len(raw) <= 65536, 'typescript-entropy-replay-metadata-bound')
    metadata = json.loads(raw)
    require(metadata['id'] == ARTIFACT and metadata['workflow_run']['head_sha'] == TESTED
            and metadata['workflow_run']['id'] == RUN and not metadata['expired']
            and type(metadata['size_in_bytes']) is int and 0 < metadata['size_in_bytes'] <= 1024**3,
            'typescript-entropy-replay-original-artifact')
    try:
        urllib.request.build_opener(NoRedirect).open(urllib.request.Request(endpoint+'/zip', headers=headers), timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'typescript-entropy-replay-download-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('typescript-entropy-replay-redirect-required')
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname is not None and parsed.username is None
            and (parsed.hostname.endswith('.blob.core.windows.net') or parsed.hostname.endswith('.githubusercontent.com')),
            'typescript-entropy-replay-download-origin')
    del credential, headers
    remote = Remote(url, metadata['size_in_bytes'], maximum_requests=640)
    copied, total = [], 0
    with zipfile.ZipFile(remote) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) <= 65536, 'typescript-entropy-replay-unique-index')
        entries = [archive.getinfo(name) for name in names if selected(name)]
        require(64 <= len(entries) <= 128, 'typescript-entropy-replay-member-count')
        for item in entries:
            require(not item.is_dir() and not stat.S_ISLNK(item.external_attr >> 16) and not item.flag_bits & 1
                    and 0 < item.file_size <= 192*1024**2, 'typescript-entropy-replay-member-bound')
            total += item.file_size
            require(total <= 384*1024**2, 'typescript-entropy-replay-total-bound')
            path = output/item.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, path.open('xb') as target:
                written = 0
                while raw := source.read(1024**2):
                    written += len(raw)
                    require(written <= item.file_size, 'typescript-entropy-replay-decompression-bound')
                    target.write(raw)
            require(written == item.file_size, 'typescript-entropy-replay-exact-member-size')
            path.chmod(0o700 if '/native-binaries/' in item.filename else 0o600)
            copied.append({'path': item.filename, 'bytes': written})
    record = {'artifactId': ARTIFACT, 'runId': RUN, 'testedSource': TESTED, 'selected': copied,
        'rangeRequests': remote.requests, 'networkBytes': remote.network_bytes,
        'completeArchiveDownloaded': False, 'credentialsRetained': False}
    write_json(output/'acquisition.json', record)
    return record


def historical(acquired):
    normal = acquired/NORMAL
    require(digest(read_file(normal/'qualification.json')) == QUALIFICATION, 'typescript-entropy-replay-qualified-receipt-preimage')
    receipt = read_json(normal/'qualification.json')
    source = read_file(normal/'source-inputs.json')
    node_path = normal/'node/workflow.json'
    node = read_json(node_path)
    require(receipt['status'] == 'passed' and source == read_file(normal/'source-inputs-after.json')
            and digest(source) == receipt['sourceIdentityDigest']
            and digest(read_file(node_path)) == receipt['node']['receiptDigest']
            and node['status'] == 'passed' and len(node['invocations']) == 27
            and all(row['processReaped'] for row in node['invocations'])
            and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
            'typescript-entropy-replay-historical-normal-proof')
    binaries = {name: normal/'native-binaries'/name.replace('/', '-') for name in PRODUCTS}
    identities = {name: file_identity(path, 512*1024**2) for name, path in binaries.items()}
    require(identities == receipt['binaries'], 'typescript-entropy-replay-historical-native-five')
    # The host stays explicitly historical. Require the exact reviewed scalar implementation, without rebinding its whole source receipt.
    for name in ('crates/latent-wasmtime/src/host/runtime/fixed_result.rs', 'crates/latent-wasmtime/src/host/random.rs'):
        original = subprocess.check_output(['git', 'show', TESTED+':'+name], cwd=ROOT, timeout=15)
        require(read_file(ROOT/name) == original, 'typescript-entropy-replay-reviewed-scalar-source')
    return binaries, receipt, {'compiledSource': TESTED, 'qualification': file_identity(normal/'qualification.json'),
        'sourceInputs': file_identity(normal/'source-inputs.json'), 'normalNode': file_identity(node_path),
        'nativeBinaries': identities, 'currentNormalReceiptFabricated': False}


def package_inputs(directory):
    document = read_json(directory/'package-source.json')
    names = ['package-source.json', *(row['source'] for row in document['layers'])]
    require(len(names) == len(set(names)) <= 32 and all(type(name) is str and not name.startswith('/')
        and ':' not in name and '\\' not in name and all(p not in {'', '.', '..'} for p in name.split('/')) for name in names),
        'typescript-entropy-replay-package-paths')
    require(inventory({name: read_file(directory/name, 64*1024**2) for name in names}) == read_file(directory/'package-inputs.json'),
            'typescript-entropy-replay-exact-package-inputs')
    return file_identity(directory/'package-inputs.json')


def packages(acquired, output, binaries, receipt, commands):
    from tools.typescript_entropy_probe import prepare
    from tools.typescript_guest.project import create
    builds, proof = {}, {}
    for name in TEMPLATES:
        directory = acquired/(ENTROPY+'build-'+name if name in COMPONENTS else NORMAL+'builds/'+name)
        marker = read_json(directory/'BUILD-COMPLETE.json')
        require(marker['packageAssembled'] is True and (name in COMPONENTS or marker == receipt['builds'][name]),
                'typescript-entropy-replay-original-build-marker')
        for filename, field in (('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'), ('build-observation.json', 'observationDigest')):
            require(digest(read_file(directory/filename, 64*1024**2)) == marker[field], 'typescript-entropy-replay-original-build-bytes')
        if name in COMPONENTS:
            require(marker['componentDigest'] == COMPONENTS[name], 'typescript-entropy-replay-original-entropy-component')
            recipe = read_json(directory/'recipe-inputs.json')
            for path in ('tools/typescript_guest/entropy.mjs', 'tools/typescript_guest/entropy_profile.py', 'tools/typescript_guest/bundle.mjs'):
                raw = read_file(ROOT/path)
                require(recipe[path] == {'digest': digest(raw), 'size': len(raw)}, 'typescript-entropy-replay-current-entropy-backend')
            app = create(output/('public-'+name), name)
            prepare(app, name)
            source = read_json(directory/'source-inputs.json')
            for path in ('src/main.ts', 'src/entropy-library.ts') if name == 'greeting' else ('src/main.ts',):
                raw = read_file(app/path)
                require(source[path] == {'digest': digest(raw), 'size': len(raw)},
                        'typescript-entropy-replay-current-application-source')
            manifest = read_json(directory/'package-inputs.json')
            wit = {path: read_file(app/path) for path in manifest if path.startswith('wit/')}
            for path, raw in wit.items():
                require(source[path] == manifest[path] == {'digest': digest(raw), 'size': len(raw)},
                        'typescript-entropy-replay-authenticated-WIT')
                require(not (directory/path).exists(), 'typescript-entropy-replay-WIT-already-present')
                (directory/path).parent.mkdir(parents=True, exist_ok=True)
                (directory/path).write_bytes(raw)
        before = package_inputs(directory)
        commands.run('package-'+name, binaries['examples/package'], 'build', directory/'package-source.json', directory, directory/'package')
        require(package_inputs(directory) == before, 'typescript-entropy-replay-package-changed')
        builds[name], proof[name] = directory, {'originalBuild': marker, 'packageInputs': before}
    return builds, proof


def replay(acquired, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'typescript-entropy-replay-Linux-Python313')
    output = fresh(output)
    record = {'schemaVersion': 'latent.typescript.entropy-policy-replay.v1', 'status': 'incomplete',
        'compiledSource': TESTED, 'artifactId': ARTIFACT, 'originalRunId': RUN,
        'newCompilation': False, 'providerAggregateExhaustionQualified': False,
        'normalReceiptRewritten': False, 'fullTicketQualification': False, 'randomPayloadRetained': False}
    stage = 'historical-inputs'
    try:
        binaries, receipt, inherited = historical(acquired)
        record['inherited'] = inherited
        record['replaySource'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=15).decode().strip()
        commands = Commands(ROOT, output, build_environment(output))
        stage = 'unchanged-components-and-package-layers'
        builds, original = packages(acquired, output, binaries, receipt, commands)
        record['originalBuilds'] = original
        stage = 'normal-demo-signing'
        commands.run('entropy-policy-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', output/'signed', *(builds[name] for name in TEMPLATES))
        stage = 'signed-original-and-policy-ceiling-programme'
        node = run(binaries['latent'], binaries['latentd'], output/'signed', output/'node', language='typescript', standard_typescript_entropy=True)
        require(node['status'] == 'passed' and len(node['invocations']) == 34
                and len(node['typescriptStandardEntropy']['cases']) == 6
                and node['typescriptStandardEntropy']['providerAggregateExhaustionQualified'] is False
                and node['typescriptStandardEntropy']['originalPolicyRestoredBeforeFresh'] is True
                and all(row['processReaped'] for row in node['invocations'])
                and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
                'typescript-entropy-replay-all-original-and-new-outcomes')
        require(historical(acquired)[2] == inherited and all(package_inputs(builds[name]) == original[name]['packageInputs'] for name in TEMPLATES),
                'typescript-entropy-replay-original-inputs-changed')
        record.update(status='passed', outcomes=34, workflow=file_identity(output/'node/workflow.json'), commands=commands.records)
        write_json(output/'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquire', action='store_true')
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.acquire:
            acquire(args.inputs)
            print(json.dumps({'status': 'acquired'}))
        else:
            require(args.output is not None, 'typescript-entropy-replay-output-required')
            print(json.dumps({'status': replay(args.inputs, args.output)['status']}))
    except Exception as error:
        # Download errors may contain signed URLs; retain only the closed category.
        print(json.dumps({'status': 'failed', 'errorCategory': type(error).__name__}))
        raise SystemExit(1)
