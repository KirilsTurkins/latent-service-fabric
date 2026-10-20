"""Authenticate one explicit native producer; never mint a normal qualification."""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import PurePosixPath
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

from tools.java_replay_materials import api, git_source_identity, NoRedirect, Ranges, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

SOURCE = 'a4f05f3f243889cc7ba7a0404bdc76afec32d3c2'
RUN = 39400186766
JOB = 118552659402
ARTIFACT = {'id': 12255531553, 'size_in_bytes': 65925279,
    'digest': 'sha256:0b5756327d92f45e59e65da2f9d059d6f7e464e59830e43761931c97c4391e8e'}
RECEIPTS = {'native-products.json': {'sha256': 'sha256:f6022e637a01a4bf8740ae0f66c4cc3728c0bc45cca852d1746cff666ed16ad4',
                          'bytes': 3105},
 'source-inputs.json': {'sha256': 'sha256:cb2d0d7b2a4948669f23461773caf96d9f651107fecb435c13b6ead59e9f3121',
                        'bytes': 1563}}
WORKFLOW = '.github/workflows/sdk-native-products.yml'
PRODUCTS = ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')
STAGES = ('rust-version', 'normal-host-build', 'closed-http-refusal-controls', 'neutral-resource-signing-controls')
MATERIALS = (WORKFLOW, '.cargo/managed-guest.toml', 'tools/qualify_rust_capsules.py',
             'tools/toolchain.toml', 'tools/rust_capsule_build.py', 'tools/build_observation.py',
             'tools/build_process.py', 'tools/build_process_linux.py')
ALLOWED = {'native-products.json': 1024**2, 'source-inputs.json': 1024**2} | {
    'native-binaries/' + name.replace('/', '-'): 512*1024**2 for name in PRODUCTS}


def _identity(value):
    return (type(value) is dict and set(value) == {'sha256', 'bytes'}
            and type(value['sha256']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', value['sha256'])
            and type(value['bytes']) is int and 0 < value['bytes'] <= 512*1024**2)


def validate_record(record, snapshot, native, materials):
    require(type(record) is dict and set(record) == {'schemaVersion', 'status', 'sourceRevision', 'source',
        'materials', 'compiler', 'products', 'commands', 'profile', 'signedQualification',
        'guestComponentsCompiled', 'historicalReceiptRewritten'}, 'java-fiber-native-record-fields')
    require(record['schemaVersion'] == 'latent.sdk.native-products.v1' and record['status'] == 'built'
        and record['sourceRevision'] == SOURCE and record['source'] == native
        and record['materials'] == materials and snapshot == {'native': native, 'materials': materials},
        'java-fiber-native-source-or-materials')
    require(record['profile'] == 'normal-managed-guest-default-features'
        and record['signedQualification'] is False and record['guestComponentsCompiled'] is False
        and record['historicalReceiptRewritten'] is False and type(record['compiler']) is str
        and record['compiler'].startswith('rustc 1.97.1 ('), 'java-fiber-native-profile-not-qualification')
    products = record['products']
    require(type(products) is dict and set(products) == set(PRODUCTS)
        and all(_identity(value) for value in products.values()), 'java-fiber-native-five-products')
    commands = record['commands']
    require(type(commands) is list and len(commands) == len(STAGES), 'java-fiber-native-command-count')
    for row, stage in zip(commands, STAGES):
        require(type(row) is dict and set(row) == {'stage', 'exitCode', 'seconds'}
            and row['stage'] == stage and type(row['exitCode']) is int and row['exitCode'] == 0
            and type(row['seconds']) in (int, float) and math.isfinite(row['seconds'])
            and 0 <= row['seconds'] <= 1320, 'java-fiber-native-command-outcome')


def _git_materials():
    result = {}
    for name in MATERIALS:
        raw = subprocess.check_output(['git', 'show', SOURCE + ':' + name], cwd=ROOT, timeout=30)
        require(0 < len(raw) <= 1024**2, 'java-fiber-native-git-material-bound')
        result[name] = {'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    return result


def preflight(archive):
    names = archive.namelist()
    require(len(names) <= 20000 and len(names) == len(set(names)), 'java-fiber-native-archive-index')
    result = {}
    for name, maximum in ALLOWED.items():
        row = archive.getinfo(name)
        require(0 < row.file_size <= maximum and not row.is_dir()
            and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG),
            'java-fiber-native-fixed-member-preflight')
        result[name] = {'bytes': row.file_size, 'compressedBytes': row.compress_size}
    return result


def extract(archive, name, destination):
    path = PurePosixPath(name)
    require(name in ALLOWED and str(path) == name and not path.is_absolute()
        and '..' not in path.parts and '\\' not in name, 'java-fiber-native-fixed-member-only')
    row = archive.getinfo(name)
    require(0 < row.file_size <= ALLOWED[name] and not row.is_dir()
        and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG), 'java-fiber-native-member-type')
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with archive.open(row) as source, destination.open('xb') as target:
        count = 0
        while raw := source.read(1024**2):
            count += len(raw)
            require(count <= ALLOWED[name], 'java-fiber-native-expanded-bound')
            target.write(raw)
    require(count == row.file_size, 'java-fiber-native-expanded-length')
    destination.chmod(0o600)


def _official_artifact():
    run, job = api(f'actions/runs/{RUN}'), api(f'actions/jobs/{JOB}')
    require(run['id'] == RUN and run['head_sha'] == SOURCE and run['path'] == WORKFLOW
        and run['event'] == 'push' and run['head_branch'] == 'feat/sdk-current-native-products-20261020'
        and run['status'] == 'completed' and run['conclusion'] == 'success'
        and job['id'] == JOB and job['run_id'] == RUN and job['head_sha'] == SOURCE
        and job['name'] == 'Build and retain five source-bound native products'
        and job['status'] == 'completed' and job['conclusion'] == 'success',
        'java-fiber-native-official-producer')
    listing = api(f'actions/runs/{RUN}/artifacts?per_page=100')
    require(listing['total_count'] == len(listing['artifacts']) <= 100, 'java-fiber-native-artifact-pages')
    selected = [a for a in listing['artifacts'] if a['name'] == 'sdk-native-products-' + SOURCE]
    require(len(selected) == 1, 'java-fiber-native-unique-artifact')
    artifact = selected[0]
    require(type(artifact['id']) is int and artifact['id'] > 0 and not artifact['expired']
        and type(artifact['size_in_bytes']) is int and 0 < artifact['size_in_bytes'] <= 1024**3
        and type(artifact['digest']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', artifact['digest'])
        and artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == SOURCE,
        'java-fiber-native-artifact-origin')
    require(all(artifact[key] == value for key, value in ARTIFACT.items()),
        'java-fiber-native-fixed-artifact')
    return artifact


def native_products(prepared):
    return {('capsule_authoring' if name == 'examples/capsule_authoring' else name.split('/')[-1]):
            prepared/'native'/name.replace('/', '-') for name in PRODUCTS}


def receipt_preimages(prepared):
    for name, expected in RECEIPTS.items():
        require(file_identity(prepared/name) == expected, 'java-fiber-native-receipt-preimage')


def verify_prepared(prepared):
    receipt_preimages(prepared)
    record, snapshot = read_json(prepared/'native-products.json'), read_json(prepared/'source-inputs.json')
    validate_record(record, snapshot, git_source_identity(SOURCE), _git_materials())
    retained = read_json(prepared/'retrieval.json')
    require(retained['schemaVersion'] == 'latent.java.http-fiber.native-products.v1'
        and retained['compiledSource'] == SOURCE and retained['producerRun'] == RUN
        and retained['producerJob'] == JOB and retained['signedQualification'] is False
        and retained['guestComponentsCompiledByProducer'] is False
        and retained['historicalNormalReceiptCreated'] is False
        and retained['compiledTree'] == subprocess.check_output(['git', 'rev-parse', SOURCE+'^{tree}'],
            cwd=ROOT, text=True, timeout=30).strip()
        and retained['producerReceipt'] == file_identity(prepared/'native-products.json')
        and retained['sourceSnapshot'] == file_identity(prepared/'source-inputs.json')
        and retained['products'] == record['products']
        and retained['origin']['artifact'] == ARTIFACT['id']
        and retained['origin']['archiveDigest'] == ARTIFACT['digest'], 'java-fiber-native-retained-record-drift')
    for name, expected in record['products'].items():
        require(file_identity(prepared/'native'/name.replace('/', '-'), 512*1024**2) == expected,
            'java-fiber-native-product-drift')
    return retained


def prepare(output):
    require(sys.platform == 'linux', 'java-fiber-native-linux-required')
    artifact = _official_artifact()
    output = fresh(output)
    token = os.environ.get('GH_TOKEN')
    require(bool(token), 'java-fiber-native-explicit-actions-token')
    request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip',
        headers={'Authorization': 'Bearer ' + token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'java-fiber-native-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('java-fiber-native-redirect-required')
    require(url.startswith('https://'), 'java-fiber-native-https')
    remote = Ranges(url, artifact['size_in_bytes'])
    with zipfile.ZipFile(remote) as archive:
        selected = preflight(archive)
        for name in ('native-products.json', 'source-inputs.json'):
            extract(archive, name, output/name)
        receipt_preimages(output)
        record, snapshot = read_json(output/'native-products.json'), read_json(output/'source-inputs.json')
        validate_record(record, snapshot, git_source_identity(SOURCE), _git_materials())
        for name in PRODUCTS:
            target = output/'native'/name.replace('/', '-')
            extract(archive, 'native-binaries/'+name.replace('/', '-'), target)
            require(file_identity(target, 512*1024**2) == record['products'][name],
                'java-fiber-native-original-product')
            target.chmod(0o700)
    result = {'schemaVersion': 'latent.java.http-fiber.native-products.v1', 'compiledSource': SOURCE,
        'compiledTree': subprocess.check_output(['git', 'rev-parse', SOURCE+'^{tree}'], cwd=ROOT,
            text=True, timeout=30).strip(), 'producerRun': RUN, 'producerJob': JOB,
        'producerReceipt': file_identity(output/'native-products.json'),
        'sourceSnapshot': file_identity(output/'source-inputs.json'), 'products': record['products'],
        'signedQualification': False, 'guestComponentsCompiledByProducer': False,
        'historicalNormalReceiptCreated': False, 'wholeArchiveRetained': False,
        'origin': {'artifact': artifact['id'], 'archiveDigest': artifact['digest'],
            'archiveDigestVerification': 'official-metadata-only-selected-members-hash-verified',
            'fixedMembersPreflighted': selected, 'rangeBytes': remote.transferred, 'rangeRequests': remote.requests}}
    write_json(output/'retrieval.json', result)
    require(verify_prepared(output) == result, 'java-fiber-native-final-recheck')
    return result
