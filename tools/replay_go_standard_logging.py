"""Explicit diagnostic replay; reuse checked native products, build only logging.

This never substitutes a replay for a new normal qualification or changes the
default Go CI programme. Artifact selection is fixed to one retained old run.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.go_capsule_build import RECIPE, build
from tools.go_capsule_project import create
from tools.go_guest.runtime import prepare_compiler
from tools.go_standard_logging_probe import install
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_go_standard_http import NATIVE_NAMES
from tools.qualify_go_standard_logging import reference
from tools.run_rust_capsule_workflow import run
from tools.build_observation import build_environment
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_json, snapshot, write_json

REPOSITORY = 'KirilsTurkins/latent-service-fabric'
ORIGINAL_HEAD = 'a81b23563d094234ff92efe53a714264f065d441'
ORIGINAL_TESTED = '2aaa142bd72461f37cb36aeadf6f1691a8f204c9'
ORIGINAL_RUN = 39276399961
ORIGINAL_JOB = 118141708049
ARTIFACTS = {
    'products': (12199463374, 260457245, 'sha256:d8468028372ea22be185d6e0f39c98b552dd31851073ec93a5aa8b9633c03313'),
    'source': (12197841828, 23866802, 'sha256:375d39dd7953a5d90f7a96776695a0d3c1579274059424f9ba5472c1fb279c3c'),
    'tools': (12198250785, 81715219, 'sha256:dd8deaaaa28f4fda86da564b7747fb5f868abea8cb38122d606e4b1348979c46')}
TEMPLATES = ('greeting', 'http-status', 'recovery', 'shipping', 'word-count')
COMPANIONS = tuple(name for name in TEMPLATES if name != 'greeting')
MAX_DOCUMENT = 4 * 1024 * 1024
BUILD_FILES = ('BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json',
               'recipe-inputs.json', 'package-inputs.json', 'package-source.json', 'deployment.json')
PRODUCTION_PREFIXES = ('apps/', 'crates/', 'sdk/rust/', 'sdk/go-guest/', 'tools/go_guest/',
                       'tools/optimization-workloads/', '.cargo/', 'wit/', 'schemas/')
PRODUCTION_FILES = frozenset((*RECIPE, 'Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', 'tools/toolchain.toml'))


def identity(raw):
    return {'sha256': digest(raw), 'bytes': len(raw)}


def safe_name(name):
    require(isinstance(name, str) and bool(name), 'replay-artifact-member-path')
    path = PurePosixPath(name)
    require(bool(path.parts) and '\\' not in name
            and not path.is_absolute() and '..' not in path.parts
            and str(path) == name and ':' not in name, 'replay-artifact-member-path')
    return path


def production(name):
    return (name in PRODUCTION_FILES or name.startswith(PRODUCTION_PREFIXES)
            or name.endswith('.rs') or PurePosixPath(name).name in {'Cargo.toml', 'Cargo.lock'})


def fixture_ast(raw, omitted=()):
    tree = ast.parse(raw)
    tree.body = [row for row in tree.body if not isinstance(row, (ast.FunctionDef, ast.AsyncFunctionDef))
                 or row.name not in omitted]
    return ast.dump(tree, include_attributes=False)


def source_bytes(root, name):
    path = root / safe_name(name)
    require(path.resolve(strict=True).is_relative_to(root.resolve(strict=True))
            and not any(parent.is_symlink() for parent in (path, *path.parents) if parent.is_relative_to(root))
            and path.is_file() and path.stat().st_nlink == 1, 'replay-current-source-owner')
    return path.read_bytes()


def prove_source(archive_path, source_root, current_names):
    """Compare actual archived bytes, including removals/additions, without extraction."""
    expected = {name for name in current_names if production(name)}
    seen, selected, originals, total = set(), {}, {}, 0
    with tarfile.open(archive_path, mode='r:gz') as archive:
        for number, row in enumerate(archive, 1):
            require(number <= 20000, 'replay-source-entry-bound')
            name = row.name.rstrip('/')
            safe_name(name)
            require(name not in seen, 'replay-source-duplicate')
            seen.add(name)
            if row.isdir():
                continue
            total += row.size
            require(total <= 512 * 1024**2 and row.size <= 32 * 1024**2, 'replay-source-byte-bound')
            if not production(name) and name != 'tools/go_standard_logging_probe.py':
                continue
            require(row.isfile(), 'replay-source-link-or-special-file')
            stream = archive.extractfile(row)
            raw = stream.read(row.size + 1)
            require(len(raw) == row.size, 'replay-source-member-length')
            if name == 'tools/go_standard_logging_probe.py':
                originals[name] = raw
            if production(name):
                require(name in expected and source_bytes(source_root, name) == raw,
                        'replay-production-source-preimage-mismatch')
                selected[name] = identity(raw)
    require(set(selected) == expected and bool(selected), 'replay-production-source-set-mismatch')
    logging = 'tools/go_standard_logging_probe.py'
    require(logging in originals and fixture_ast(originals[logging], ('configure', 'tutorials'))
            == fixture_ast(source_bytes(source_root, logging), ('configure', 'tutorials')),
            'replay-logging-library-or-install-changed')
    return {'runtimeProductionBytesEqualCurrent': True, 'files': len(selected),
            'inventory': selected, 'inventoryIdentity': identity(json.dumps(selected, sort_keys=True).encode()),
            'loggingLibraryInstallAndOtherProbeASTUnchanged': True,
            'fixtureChangesExcludedFromCompileClaim': ['configure', 'tutorials']}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Ranges(io.RawIOBase):
    def __init__(self, url, size):
        self.url, self.size, self.position, self.transferred, self.requests = url, size, 0, 0, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        require(whence in (0, 1, 2), 'replay-zip-seek-kind')
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        require(0 <= self.position <= self.size, 'replay-zip-seek-bound')
        return self.position

    def read(self, count=-1):
        if count == -1:
            count = self.size - self.position
        require(0 <= count <= 8 * 1024**2, 'replay-range-byte-bound')
        count = min(count, self.size - self.position)
        if not count:
            return b''
        self.requests += 1
        self.transferred += count
        require(self.requests <= 4096 and self.transferred <= 256 * 1024**2, 'replay-total-range-bound')
        end = self.position + count - 1
        request = urllib.request.Request(self.url, headers={'Range': f'bytes={self.position}-{end}'})
        with urllib.request.urlopen(request, timeout=30) as response:
            require(response.status == 206 and response.headers['Content-Range']
                    == f'bytes {self.position}-{end}/{self.size}', 'replay-range-response')
            raw = response.read(count + 1)
        require(len(raw) == count, 'replay-range-length')
        self.position += count
        return raw


def api(path):
    raw = subprocess.check_output(['gh', 'api', 'repos/' + REPOSITORY + '/' + path], timeout=30)
    require(len(raw) <= MAX_DOCUMENT, 'replay-api-byte-bound')
    return json.loads(raw)


class Artifact:
    def __init__(self, kind):
        artifact, size, expected_digest = ARTIFACTS[kind]
        self.metadata = api(f'actions/artifacts/{artifact}')
        run = self.metadata['workflow_run']
        require(self.metadata['id'] == artifact and self.metadata['size_in_bytes'] == size
                and self.metadata['digest'] == expected_digest and not self.metadata['expired'] and run['id'] == ORIGINAL_RUN
                and run['head_sha'] == ORIGINAL_HEAD, 'replay-artifact-source-binding')
        token = os.environ.get('GH_TOKEN')
        require(bool(token), 'replay-explicit-actions-read-token-required')
        request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact}/zip',
            headers={'Authorization': 'Bearer ' + token})
        try:
            urllib.request.build_opener(NoRedirect).open(request, timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 302, 'replay-artifact-redirect')
            url = error.headers['Location']
        else:
            raise ValueError('replay-artifact-redirect-required')
        require(url.startswith('https://'), 'replay-artifact-https-required')
        self.remote = Ranges(url, size)
        self.archive = zipfile.ZipFile(self.remote)
        names = self.archive.namelist()
        require(len(names) <= 20000 and len(names) == len(set(names)), 'replay-artifact-entry-bound')
        self.selected = {}

    def extract(self, name, output, maximum=MAX_DOCUMENT):
        safe_name(name)
        row = self.archive.getinfo(name)
        require(0 < row.file_size <= maximum and not row.is_dir()
                and stat.S_IFMT(row.external_attr >> 16) in {0, stat.S_IFREG}, 'replay-member-type-or-byte-bound')
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        hasher, size = hashlib.sha256(), 0
        with self.archive.open(row) as source, output.open('xb') as target:
            while raw := source.read(1024 * 1024):
                size += len(raw)
                require(size <= maximum, 'replay-member-expanded-bound')
                hasher.update(raw)
                target.write(raw)
        require(size == row.file_size, 'replay-member-size-mismatch')
        output.chmod(0o600)
        self.selected[name] = {'sha256': 'sha256:' + hasher.hexdigest(), 'bytes': size}
        return output

    def summary(self):
        return {'id': self.metadata['id'], 'digest': self.metadata['digest'],
                'selected': self.selected, 'networkBytes': self.remote.transferred}


def retrieve_build(artifact, template, output, expected):
    prefix = 'go-capsule-authoring/builds/' + template + '/'
    output.mkdir(mode=0o700)
    for name in BUILD_FILES:
        artifact.extract(prefix + name, output / name)
    require(read_json(output / 'BUILD-COMPLETE.json') == expected, 'replay-original-build-marker')
    package = read_json(output / 'package-source.json')
    layers = package['layers']
    require(1 <= len(layers) <= 32, 'replay-package-layer-count')
    permitted = {'component.wasm', 'capsule.json', 'contracts.json', 'wit-lock.json', 'compatibility-report.json',
                 'wit/world.wit', 'wit/deps/clock/package.wit', 'wit/deps/random/package.wit',
                 'wit/deps/http-v2/package.wit'}
    observed = {'package-source.json': (output / 'package-source.json').read_bytes()}
    for layer in layers:
        name = layer['source']
        require(name in permitted and layer['path'] == name and name not in observed, 'replay-package-layer-allowlist')
        artifact.extract(prefix + name, output / name, 16 * 1024**2 if name == 'component.wasm' else MAX_DOCUMENT)
        observed[name] = (output / name).read_bytes()
    require(inventory(observed) == (output / 'package-inputs.json').read_bytes()
            and digest(observed['component.wasm']) == expected['componentDigest']
            and digest((output / 'build-observation.json').read_bytes()) == expected['observationDigest']
            and digest((output / 'source-inputs.json').read_bytes()) == expected['sourceDigest'],
            'replay-original-build-input-identity')
    return output


def extract_go(archive_path, destination):
    destination.mkdir(mode=0o700)
    total = 0
    with tarfile.open(archive_path, mode='r:gz') as archive:
        for ordinal, row in enumerate(archive, 1):
            name = safe_name(row.name.rstrip('/'))
            require(name.parts[0] == 'go' and ordinal <= 30000, 'replay-go-archive-layout')
            target = destination / name
            require(row.isdir() or row.isfile(), 'replay-go-link-or-special-file')
            total += row.size
            require(total <= 1024**3 and row.size <= 64 * 1024**2, 'replay-go-expanded-bound')
            if row.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with archive.extractfile(row) as source, target.open('xb') as output:
                    while raw := source.read(1024 * 1024):
                        output.write(raw)
                target.chmod(0o700 if row.mode & 0o111 else 0o600)
    return destination / 'go'


def replay(output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'replay-linux-python313-required')
    output = fresh(output)
    require(output != ROOT and ROOT not in output.parents, 'replay-output-outside-runtime-required')
    record = {'schemaVersion': 'latent.go.standard-logging.replay.v1', 'status': 'in-progress',
        'compiledSource': {'head': ORIGINAL_HEAD, 'testedMerge': ORIGINAL_TESTED,
                           'run': ORIGINAL_RUN, 'job': ORIGINAL_JOB},
        'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'nativeCargoProductsCompilationPerformed': False, 'goToolchainBootstrapPerformed': False,
        'normalQualificationRecreated': False, 'cleanHost': False, 'hermetic': False,
        'publisherAuthenticated': False, 'releasePublication': 'not-performed', 'fullTicketQualification': False}
    stage = 'original-source-and-receipts'
    try:
        job = api(f'actions/jobs/{ORIGINAL_JOB}')
        require(job['run_id'] == ORIGINAL_RUN and job['head_sha'] == ORIGINAL_HEAD and job['conclusion'] == 'failure',
                'replay-original-job-binding')
        commit = api('git/commits/' + ORIGINAL_TESTED)
        require(ORIGINAL_HEAD in [p['sha'] for p in commit['parents']], 'replay-tested-parent-binding')
        record['compiledSource']['tree'] = commit['tree']['sha']
        sources, products, tools = Artifact('source'), Artifact('products'), Artifact('tools')
        original = output / 'original'
        original.mkdir(mode=0o700)
        source_archive = sources.extract('_temp/go-guest-source.tar.gz', original / 'source.tar.gz', 128 * 1024**2)
        source_sha = sources.extract('_temp/go-guest-source.sha', original / 'source.sha', 128)
        require(source_sha.read_text().strip() == ORIGINAL_TESTED, 'replay-source-archive-revision')
        names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().rstrip('\0').split('\0')
        proof = prove_source(source_archive, ROOT, names)
        record['sourceProof'] = proof
        record['runtimeProductionBytesEqualCurrent'] = proof['runtimeProductionBytesEqualCurrent']
        native = original / 'native'
        native.mkdir(mode=0o700)
        receipt_path = products.extract('go-capsule-authoring/qualification.json', native / 'qualification.json')
        receipt = read_json(receipt_path)
        source_inputs = products.extract('go-capsule-authoring/source-inputs.json', native / 'source-inputs.json')
        old_normal_node = products.extract('go-capsule-authoring/node/workflow.json', native / 'normal-node-workflow.json')
        normal_node = read_json(old_normal_node)
        require(receipt['schemaVersion'] == 'latent.go-capsule.qualification.v1' and receipt['status'] == 'passed'
                and receipt['node']['status'] == normal_node['status'] == 'passed'
                and digest(old_normal_node.read_bytes()) == receipt['node']['receiptDigest']
                and len(normal_node['invocations']) >= 27
                and digest(source_inputs.read_bytes()) == receipt['sourceIdentityDigest'], 'replay-old-normal-qualification')
        old_failure = products.extract('go-standard-logging/FAILED.json', original / 'logging-FAILED.json')
        old_node = products.extract('go-standard-logging/node/FAILED.json', original / 'logging-node-FAILED.json')
        require(read_json(old_failure)['status'] == read_json(old_node)['status'] == 'failed'
                and read_json(old_failure)['stage'] == 'signed-enforced-node'
                and read_json(old_node)['reason'] == 'node-startup-exit-configuration-invalid-argument'
                and len(read_json(old_node)['configuration']['providers']['bindings']) == 17,
                'replay-original-failure-boundary')
        record['originalFailure'] = {'qualification': file_identity(old_failure), 'node': file_identity(old_node),
            'stage': read_json(old_failure)['stage'], 'reason': read_json(old_node)['reason']}
        binaries = {}
        for alias, name in NATIVE_NAMES.items():
            path = products.extract('go-capsule-authoring/native-binaries/' + name.replace('/', '-'),
                                    native / name.replace('/', '-'), 256 * 1024**2)
            require(file_identity(path, 256 * 1024**2) == receipt['binaries'][name], 'replay-native-product-identity')
            path.chmod(0o700)
            binaries[alias] = path
        builds = {}
        for template in TEMPLATES:
            builds[template] = retrieve_build(products, template, original / template, receipt['builds'][template])
        record['originalNormalQualification'] = file_identity(receipt_path)
        record['originalNativeProducts'] = {name: file_identity(path, 256 * 1024**2) for name, path in binaries.items()}
        tool_root = original / 'tools'
        tool_root.mkdir(mode=0o700)
        for name in ('go.tar.gz', 'componentize-go', 'wasm-tools', 'tools.sha256'):
            tools.extract(name, tool_root / name, 128 * 1024**2)
        pins = read_json(ROOT / 'sdk/go-guest/toolchain.lock.json')
        require(digest((tool_root / 'go.tar.gz').read_bytes())[7:] == pins['go']['linuxAmd64']['sha256'],
                'replay-pinned-go-archive')
        observed = read_json(builds['greeting'] / 'build-observation.json')
        materials = {row['name']: row for row in observed['materials']}
        for name in ('componentize-go', 'wasm-tools'):
            require(identity((tool_root / name).read_bytes()) ==
                    {'sha256': materials[name]['digest'], 'bytes': materials[name]['size']}, 'replay-pinned-tool-identity')
            (tool_root / name).chmod(0o700)
        record['artifacts'] = {name: artifact.summary() for name, artifact in
                               (('source', sources), ('products', products), ('tools', tools))}
        # Drop the Actions credential before any retained native process runs.
        os.environ.pop('GH_TOKEN', None)
        commands = Commands(ROOT, output, build_environment(output), deadline_seconds=2300, command_seconds=600)
        stage = 'fresh-normal-baseline-signing'
        normal_signed = output / 'normal-signed'
        commands.run('replay-normal-demo-sign', binaries['capsule_authoring'], 'demo-sign', normal_signed,
                     *(builds[name] for name in TEMPLATES))
        stage = 'current-default-normal-node-programme'
        normal = run(binaries['latent'], binaries['latentd'], normal_signed, output / 'normal-node', language='go')
        require(normal['status'] == 'passed' and len(normal['invocations']) >= 27, 'replay-current-normal-baseline')
        record['normalBaselineReplay'] = {'status': 'passed', 'invocations': len(normal['invocations']),
            'receipt': file_identity(output / 'normal-node/workflow.json'), 'freshDemoSigning': True}
        stage = 'prepare-retained-pinned-go-tools'
        go_root = extract_go(tool_root / 'go.tar.gz', output / 'upstream-tools')
        prepared_go = prepare_compiler(go_root, output / 'prepared-go') / 'bin/go'
        require(identity(prepared_go.read_bytes()) == {'sha256': materials['go']['digest'], 'bytes': materials['go']['size']},
                'replay-pinned-go-executable')
        os.environ['PATH'] = os.pathsep.join((str(prepared_go.parent), str(tool_root), os.defpath))
        os.environ['GOTOOLCHAIN'] = 'local'
        stage = 'fresh-current-logging-reference-and-capture'
        record['reference'] = reference(output / 'reference', commands, prepared_go)
        app = create(output / 'application', 'greeting')
        record['capture'] = install(app, output / 'outside-library', prepared_go)
        before = inventory(snapshot(app))
        stage = 'fresh-logging-greeting-only-build'
        built = build(app, output / 'logging-build', binaries['capsule_contracts'], binaries['package'],
                      'https://github.com/' + REPOSITORY)
        require(inventory(snapshot(app)) == before and read_json(built / 'application-dependencies.json')['networkResolution'] is False,
                'replay-fresh-logging-offline-source')
        record['freshLoggingBuild'] = read_json(built / 'BUILD-COMPLETE.json')
        stage = 'fresh-logging-demo-signing'
        signed = output / 'logging-signed'
        commands.run('replay-logging-demo-sign', binaries['capsule_authoring'], 'demo-sign', signed, built,
                     *(builds[name] for name in COMPANIONS))
        stage = 'current-fourteen-binding-logging-node'
        node = run(binaries['latent'], binaries['latentd'], signed, output / 'logging-node', language='go', go_standard_logging=True)
        require(node['status'] == 'passed' and node['goStandardLogging']['status'] == 'passed'
                and len(node['configuration']['providers']['bindings']) == 14, 'replay-logging-programme-required')
        stage = 'final-source-and-native-recheck'
        require(prove_source(source_archive, ROOT, names) == proof
                and record['originalNativeProducts'] == {name: file_identity(path, 256 * 1024**2) for name, path in binaries.items()}
                and time.monotonic() < commands.deadline, 'replay-final-input-drift')
        record.update(status='passed', loggingNodeReceipt=file_identity(output / 'logging-node/workflow.json'),
                      commands=commands.records, originalSigningInputs='not-reconstructed',
                      freshLoggingCompilationPerformed=True)
        write_json(output / 'replay.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        try:
            write_json(output / 'FAILED.json', record)
        except Exception:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': replay(args.output.resolve())['status']}))
