"""Authenticate the independent-tenant HTTP native producer; never mint guest qualification."""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_replay_materials import api, git_source_identity, NoRedirect, Ranges, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

SOURCE = '6f5f180136d140ac670561695260f71514781015'
RUN = 39443901256
JOB = 118700610031
# Exact successful public producer; these pins never select a moving branch.
ARTIFACT = {'id': 12275691963, 'size_in_bytes': 66080276, 'digest': 'sha256:fa6c846ffcf5f79b1153d60053aeb79f2e3495228f1c7c510159f7a2c072e399'}
RECEIPTS = {'native-products.json': {'sha256': 'sha256:e90056e7b967ad859ac8311ffd5b27d6513473673006f79be15a47636ff1ba0b', 'bytes': 21159}, 'source-inputs.json': {'sha256': 'sha256:8f10be2d3d773b288df3a76c0bcc4e8b799e6fbbc931c767f82028d9094f7ce1', 'bytes': 18936}}
BRANCH = 'fix/http-phase-unused-nominal-type-20261020'
WORKFLOW = '.github/workflows/sdk-native-products.yml'
PRODUCTS = ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')
STAGES = ('rust-version', 'normal-host-build', 'closed-http-refusal-controls', 'neutral-resource-signing-controls', 'positive-timer-observer-controls', 'phase-nominal-type-owner-controls', 'phase-emitted-type-owner-controls', 'independent-http-configuration-controls', 'independent-http-dispatch-controls', 'independent-http-secret-controls')
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
        'guestComponentsCompiled', 'historicalReceiptRewritten'}, 'java-phase-native-record-fields')
    require(record['schemaVersion'] == 'latent.sdk.native-products.v1' and record['status'] == 'built'
        and record['sourceRevision'] == SOURCE and record['source'] == native
        and record['materials'] == materials and snapshot == {'native': native, 'materials': materials},
        'java-phase-native-source-or-materials')
    require(record['profile'] == 'normal-managed-guest-default-features'
        and record['signedQualification'] is False and record['guestComponentsCompiled'] is False
        and record['historicalReceiptRewritten'] is False and type(record['compiler']) is str
        and record['compiler'].startswith('rustc 1.97.1 ('), 'java-phase-native-profile-not-qualification')
    products = record['products']
    require(type(products) is dict and set(products) == set(PRODUCTS)
        and all(_identity(value) for value in products.values()), 'java-phase-native-five-products')
    commands = record['commands']
    require(type(commands) is list and len(commands) == len(STAGES), 'java-phase-native-command-count')
    for row, stage in zip(commands, STAGES):
        require(type(row) is dict and set(row) == {'stage', 'exitCode', 'seconds'}
            and row['stage'] == stage and type(row['exitCode']) is int and row['exitCode'] == 0
            and type(row['seconds']) in (int, float) and math.isfinite(row['seconds'])
            and 0 <= row['seconds'] <= 1320, 'java-phase-native-command-outcome')
    require(sum(row['seconds'] for row in commands) <= 1320.001,
        'java-phase-native-overall-command-bound')


def _git_materials():
    """One bounded Git batch binds all actual auxiliary compile-input trees."""
    trees = {'wit': (2048, 8*1024**2), 'schemas': (256, 4*1024**2),
             'examples/echo-contract/wit': (128, 1024**2)}
    raw = subprocess.check_output(['git', 'ls-tree', '-rz', SOURCE, '--',
        *MATERIALS, *trees], cwd=ROOT, timeout=30)
    require(len(raw) <= 1024**2, 'java-phase-native-material-tree-bound')
    entries, counts, sizes = [], dict.fromkeys(trees, 0), dict.fromkeys(trees, 0)
    for item in raw.rstrip(b'\0').split(b'\0'):
        metadata, name = item.split(b'\t')
        mode, kind, oid = metadata.decode('ascii').split()
        name = name.decode('utf-8')
        require(mode in ('100644', '100755') and kind == 'blob'
            and PurePosixPath(name).as_posix() == name and '..' not in PurePosixPath(name).parts
            and not PurePosixPath(name).is_absolute(), 'java-phase-native-material-regular')
        require(name in MATERIALS or any(name.startswith(tree+'/') for tree in trees),
            'java-phase-native-material-scope')
        entries.append((name, oid))
    names = [name for name, _ in entries]
    require(set(MATERIALS) <= set(names) and len(names) == len(set(names))
        and 0 < len(names) <= len(MATERIALS)+sum(cap[0] for cap in trees.values()),
        'java-phase-native-material-file-bound')
    data = subprocess.run(['git', 'cat-file', '--batch'],
        input=''.join(oid+'\n' for _, oid in entries).encode(), stdout=subprocess.PIPE,
        check=True, cwd=ROOT, timeout=60).stdout
    require(len(data) <= 16*1024**2, 'java-phase-native-material-batch-bound')
    result, position = {}, 0
    for name, oid in entries:
        line = data.index(b'\n', position)
        header = data[position:line].decode('ascii').split()
        require(len(header) == 3 and header[:2] == [oid, 'blob'],
            'java-phase-native-material-Git-header')
        size = int(header[2]);position = line+1
        maximum = 1024**2 if name in MATERIALS else next(
            cap[1] for tree, cap in trees.items() if name.startswith(tree+'/'))
        require(0 < size <= maximum and position+size < len(data),
            'java-phase-native-material-Git-bound')
        payload = data[position:position+size]
        require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+payload).hexdigest() == oid
            and data[position+size:position+size+1] == b'\n',
            'java-phase-native-material-Git-identity')
        result[name] = {'sha256': 'sha256:'+hashlib.sha256(payload).hexdigest(), 'bytes': size}
        for tree, (count_cap, byte_cap) in trees.items():
            if name.startswith(tree+'/'):
                counts[tree] += 1;sizes[tree] += size
                require(counts[tree] <= count_cap and sizes[tree] <= byte_cap,
                    'java-phase-native-material-tree-cap')
        position += size+1
    require(position == len(data) and all(counts.values()), 'java-phase-native-material-complete')
    return dict(sorted(result.items()))


def _pins():
    require(type(ARTIFACT) is dict and set(ARTIFACT) == {'id', 'size_in_bytes', 'digest'}
        and type(ARTIFACT['id']) is int and ARTIFACT['id'] > 0
        and type(ARTIFACT['size_in_bytes']) is int and 0 < ARTIFACT['size_in_bytes'] <= 1024**3
        and type(ARTIFACT['digest']) is str
        and re.fullmatch(r'sha256:[0-9a-f]{64}', ARTIFACT['digest'])
        and type(RECEIPTS) is dict and set(RECEIPTS) == {'native-products.json', 'source-inputs.json'}
        and all(_identity(value) and value['bytes'] <= 1024**2 for value in RECEIPTS.values()),
        'java-phase-native-completed-producer-pins-required')


def preflight(archive):
    names = archive.namelist()
    require(len(names) <= 20000 and len(names) == len(set(names)), 'java-phase-native-archive-index')
    result = {}
    for name, maximum in ALLOWED.items():
        row = archive.getinfo(name)
        require(0 < row.file_size <= maximum and not row.is_dir()
            and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG),
            'java-phase-native-fixed-member-preflight')
        result[name] = {'bytes': row.file_size, 'compressedBytes': row.compress_size}
    return result


def extract(archive, name, destination):
    path = PurePosixPath(name)
    require(name in ALLOWED and str(path) == name and not path.is_absolute()
        and '..' not in path.parts and '\\' not in name, 'java-phase-native-fixed-member-only')
    row = archive.getinfo(name)
    require(0 < row.file_size <= ALLOWED[name] and not row.is_dir()
        and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG), 'java-phase-native-member-type')
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with archive.open(row) as source, destination.open('xb') as target:
        count = 0
        while raw := source.read(1024**2):
            count += len(raw)
            require(count <= ALLOWED[name], 'java-phase-native-expanded-bound')
            target.write(raw)
    require(count == row.file_size, 'java-phase-native-expanded-length')
    destination.chmod(0o600)


def _official_artifact():
    _pins()
    run, job = api(f'actions/runs/{RUN}'), api(f'actions/jobs/{JOB}')
    require(run['id'] == RUN and run['head_sha'] == SOURCE and run['path'] == WORKFLOW
        and run['event'] == 'push' and run['head_branch'] == BRANCH
        and run['status'] == 'completed' and run['conclusion'] == 'success'
        and job['id'] == JOB and job['run_id'] == RUN and job['head_sha'] == SOURCE
        and job['name'] == 'Build and retain five source-bound native products'
        and job['status'] == 'completed' and job['conclusion'] == 'success',
        'java-phase-native-official-producer')
    listing = api(f'actions/runs/{RUN}/artifacts?per_page=100')
    require(listing['total_count'] == len(listing['artifacts']) <= 100, 'java-phase-native-artifact-pages')
    selected = [a for a in listing['artifacts'] if a['name'] == 'sdk-native-products-' + SOURCE]
    require(len(selected) == 1, 'java-phase-native-unique-artifact')
    artifact = selected[0]
    require(type(artifact['id']) is int and artifact['id'] > 0 and not artifact['expired']
        and type(artifact['size_in_bytes']) is int and 0 < artifact['size_in_bytes'] <= 1024**3
        and type(artifact['digest']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', artifact['digest'])
        and artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == SOURCE,
        'java-phase-native-artifact-origin')
    require(all(artifact[key] == value for key, value in ARTIFACT.items()),
        'java-phase-native-fixed-artifact')
    return artifact


def native_products(prepared):
    return {('capsule_authoring' if name == 'examples/capsule_authoring' else name.split('/')[-1]):
            prepared/'native'/name.replace('/', '-') for name in PRODUCTS}


def receipt_preimages(prepared):
    _pins()
    for name, expected in RECEIPTS.items():
        require(file_identity(prepared/name) == expected, 'java-phase-native-receipt-preimage')


def verify_prepared(prepared):
    receipt_preimages(prepared)
    record, snapshot = read_json(prepared/'native-products.json'), read_json(prepared/'source-inputs.json')
    validate_record(record, snapshot, git_source_identity(SOURCE), _git_materials())
    retained = read_json(prepared/'retrieval.json')
    require(retained['schemaVersion'] == 'latent.sdk.phase-native-products.v1'
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
        and retained['origin']['archiveDigest'] == ARTIFACT['digest'], 'java-phase-native-retained-record-drift')
    for name, expected in record['products'].items():
        require(file_identity(prepared/'native'/name.replace('/', '-'), 512*1024**2) == expected,
            'java-phase-native-product-drift')
    return retained


def prepare(output):
    require(sys.platform == 'linux', 'java-phase-native-linux-required')
    artifact = _official_artifact()
    output = fresh(output)
    token = os.environ.get('GH_TOKEN')
    require(bool(token), 'java-phase-native-explicit-actions-token')
    request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip',
        headers={'Authorization': 'Bearer ' + token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'java-phase-native-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('java-phase-native-redirect-required')
    require(url.startswith('https://'), 'java-phase-native-https')
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
                'java-phase-native-original-product')
            target.chmod(0o700)
    result = {'schemaVersion': 'latent.sdk.phase-native-products.v1', 'compiledSource': SOURCE,
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
    require(verify_prepared(output) == result, 'java-phase-native-final-recheck')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.output)
