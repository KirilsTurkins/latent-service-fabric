"""Exact successful fresh OWN prerequisites; no engine/library build fallback.

The immutable artifact tuple was authenticated by the sole owning acquisition.
These are native prerequisites, never canonical, signed or physical qualification.
"""
from __future__ import annotations
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from tools.java_replay_materials import api, NoRedirect
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, read_file, digest, fresh, write_json
from tools.typescript_guest import activation_engine, native_build, runtime_profile

HEAD = '9d07a6dfa3ebb77aa75eb1b5899cb9360e26728d'
RUN, JOB = 40056035407, 120759116551
ARTIFACT = 12546161304
ARCHIVE_BYTES = 196485292
ARCHIVE_DIGEST = 'sha256:b4f21ecfb457adf9bb206c4c0b3ec36cbfd786f0da9e2ea2d8ca9d9e9a676123'
PREFIX = ''
MAX_ARCHIVE, MAX_TOTAL, MAX_MEMBERS = 512 * 1024**2, 2 * 1024**3, 1024
PRODUCTS = ('engine.wasm', 'engine-input.json', 'engine-build.json',
            'engine-compilation.json', 'source-derivation.json')
RECEIPT = 'OWN-RESULTS.json'
SCOPE = 'fresh-normal-compiler-engine-unit-native-ABI-prerequisites'
FALSE_SCOPE = ('canonicalOwnComponentExecuted', 'tableReuseQualified', 'signedExecution',
               'physicalProviderQualified', 'wholeCostQualification')


def canonical_identity(value):
    require(type(value) is dict and set(value) == {'bytes', 'sha256'}
            and type(value['bytes']) is int and 0 < value['bytes'] <= 64 * 1024**2
            and type(value['sha256']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', value['sha256']) is not None,
            'borrow-signed-canonical-product-identity')
    return value


def pinned():
    require(type(ARTIFACT) is int and ARTIFACT > 0
            and type(ARCHIVE_BYTES) is int and 0 < ARCHIVE_BYTES <= MAX_ARCHIVE
            and type(ARCHIVE_DIGEST) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', ARCHIVE_DIGEST) is not None,
            'borrow-signed-actual-success-artifact-not-yet-pinned')


def metadata(run, job, artifact):
    pinned()
    require(type(run.get('run_attempt')) is int and run['run_attempt'] == 1
            and run['id'] == RUN and run['head_sha'] == HEAD and run['event'] == 'push'
            and run['path'] == '.github/workflows/typescript-owned-results.yml'
            and run['head_branch'] == 'feat/typescript-owned-result-disposal-compose-20261024'
            and run['status'] == 'completed' and run['conclusion'] == 'success',
            'borrow-signed-successful-own-producer')
    require(job['id'] == JOB and job['run_id'] == RUN and job['head_sha'] == HEAD
            and job['name'] == 'Fresh normal OWN compiler engine and actual native controls'
            and job['status'] == 'completed' and job['conclusion'] == 'success'
            and all(step['conclusion'] in ('success', 'skipped') for step in job['steps']),
            'borrow-signed-successful-own-job')
    require(artifact['id'] == ARTIFACT and artifact['expired'] is False
            and artifact['name'] == 'typescript-own-controls-' + HEAD
            and artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == HEAD
            and artifact['size_in_bytes'] == ARCHIVE_BYTES and artifact['digest'] == ARCHIVE_DIGEST,
            'borrow-signed-pinned-own-artifact')


def receipt(value):
    require(type(value) is dict and value.get('schemaVersion') == 'latent.typescript.owned-result-prerequisites.v1'
            and value.get('status') == 'passed' and value.get('scope') == SCOPE
            and value.get('sourceCommit') == HEAD
            and type(value.get('sourceTree')) is str and re.fullmatch(r'[0-9a-f]{40}', value['sourceTree']) is not None
            and all(value.get(name) is False for name in FALSE_SCOPE), 'borrow-signed-own-receipt-scope')
    require(value.get('freshSplicerBuildCount') == 1 and type(value.get('freshSplicerBuildCount')) is int
            and value.get('freshEngineBuildCount') == 1 and type(value.get('freshEngineBuildCount')) is int
            and value.get('machBuildCount') == 0 and type(value.get('machBuildCount')) is int,
            'borrow-signed-original-build-counts')
    require(type(value.get('sourceControls')) is dict
            and value['sourceControls'] == {'testsRun':29,'skipped':0,'failures':0,'errors':0}
            and all(type(item) is int for item in value['sourceControls'].values()),
            'borrow-signed-original-source-counts')
    rust = value.get('actualRustCases')
    require(type(rust) is list and len(rust) == 13 and all(type(name) is str
            and re.fullmatch(r'lsf_async(?:_splice)?::tests::[A-Za-z0-9_]{1,160}',name) is not None for name in rust)
            and len(set(rust)) == 13, 'borrow-signed-original-rust-counts')
    for field,count in (('nativeRows',13),('lifecycleRows',6)):
        rows = value.get(field)
        require(type(rows) is list and len(rows) == count
                and all(type(row) is dict and type(row.get('status')) is int and row['status'] == 0
                    and type(row.get('case')) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',row['case']) is not None
                    for row in rows) and len({row['case'] for row in rows}) == count,
                'borrow-signed-original-native-counts')
    require(type(value.get('engineProducts')) is dict and set(value['engineProducts']) == set(PRODUCTS),
            'borrow-signed-engine-products')
    for identity in value['engineProducts'].values(): canonical_identity(identity)
    require(type(value.get('recipe')) is dict and 1 <= len(value['recipe']) <= 256,
            'borrow-signed-producer-recipe-bound')
    for name, identity in value['recipe'].items():
        require(type(name) is str and 0 < len(name) <= 512 and ':' not in name and '\\' not in name
                and all(part not in ('', '.', '..') for part in name.split('/'))
                and not PurePosixPath(name).is_absolute(), 'borrow-signed-producer-recipe-path')
        canonical_identity(identity)
    return value


def selected(archive):
    entries = archive.infolist()
    index = {row.filename: row for row in entries}
    require(0 < len(index) == len(entries) <= MAX_MEMBERS
            and sum(row.file_size for row in entries) <= MAX_TOTAL, 'borrow-signed-archive-bound')
    for row in entries:
        name = row.filename
        require(not row.is_dir() and 0 <= row.file_size <= MAX_TOTAL
                and str(PurePosixPath(name)) == name and not PurePosixPath(name).is_absolute()
                and ':' not in name and '\\' not in name
                and all(part not in ('', '.', '..') for part in name.split('/'))
                and not row.flag_bits & 1 and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG),
                'borrow-signed-archive-member')
    name = PREFIX + RECEIPT
    require(name in index and 0 < index[name].file_size <= 4 * 1024**2, 'borrow-signed-own-receipt-required')
    own = receipt(json.loads(archive.read(index[name])))
    compilation_name = PREFIX + 'engine/engine-compilation.json'
    require(compilation_name in index and 0 < index[compilation_name].file_size <= 4 * 1024**2,
            'borrow-signed-compilation-receipt-required')
    raw_compilation = archive.read(index[compilation_name])
    require({'bytes': len(raw_compilation), 'sha256': digest(raw_compilation)} == own['engineProducts']['engine-compilation.json'],
            'borrow-signed-original-compilation-identity')
    compilation = json.loads(raw_compilation)
    limits = native_build.combined_archive_limits(compilation['libraryProduct'], compilation['supportingObjects'])
    require(compilation['archiveCompositionLimits'] == limits, 'borrow-signed-original-composition-limits')
    combined = PREFIX + 'engine/spidermonkey/libspidermonkey.a'
    require(combined in index and index[combined].file_size == compilation['combinedLibrary']['bytes']
            and 0 < index[combined].file_size <= limits['maximumCombinedBytes']
            and all(row.file_size <= 64 * 1024**2 for row in entries if row.filename != combined),
            'borrow-signed-all-member-original-bounds')
    names = {name, *(PREFIX + 'engine/' + product for product in PRODUCTS),
             PREFIX + 'actual-rust-units.stdout.log',
             *(PREFIX + row['case'] + '.stdout.log' for field in ('nativeRows','lifecycleRows') for row in own[field])}
    require(names <= index.keys() and all(index[name].file_size <= 1024**2 for name in names
            if name.endswith('.stdout.log')), 'borrow-signed-original-raw-evidence-bound')
    splicer = {name for name in index if name.startswith(PREFIX + 'splicer/') and
               (name[len(PREFIX + 'splicer/'):].startswith('splicer/') or
                name[len(PREFIX + 'splicer/'):] in ('splicer-input.json', 'splicer-build.json',
                    'splicer-compilation.json', 'source-derivation.json', 'transpile-receipt.json'))}
    require(1 <= len(splicer) <= 37 and names <= index.keys()
            and all(index[name].file_size <= 32 * 1024**2 for name in splicer)
            and sum(index[name].file_size for name in splicer) <= 32 * 1024**2,
            'borrow-signed-splicer-closure-bound')
    for product in PRODUCTS:
        identity = own['engineProducts'][product]
        row = index[PREFIX + 'engine/' + product]
        require(row.file_size == identity['bytes'], 'borrow-signed-engine-member-size')
    names |= splicer
    require(sum(index[name].file_size for name in names) <= 128 * 1024**2,
            'borrow-signed-selected-products-bound')
    require(archive.testzip() is None, 'borrow-signed-all-members-crc')
    return [index[name] for name in sorted(names)]


def extract(archive, destination):
    pinned()
    require(not destination.exists() and not destination.is_symlink(), 'borrow-signed-fresh-products')
    require(file_identity(archive, MAX_ARCHIVE) == {'bytes': ARCHIVE_BYTES, 'sha256': ARCHIVE_DIGEST},
            'borrow-signed-whole-archive-identity')
    with zipfile.ZipFile(archive) as carrier:
        rows = selected(carrier)
        for row in rows:
            name = row.filename.removeprefix(PREFIX)
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with carrier.open(row) as source, path.open('xb') as target:
                while block := source.read(1024**2): target.write(block)
    return {row.filename.removeprefix(PREFIX): file_identity(destination / row.filename.removeprefix(PREFIX), 64 * 1024**2)
            for row in rows}


def verify(directory, git):
    pinned()
    archive = directory.parent / 'producer.zip'
    require(file_identity(archive,MAX_ARCHIVE) == {'bytes':ARCHIVE_BYTES,'sha256':ARCHIVE_DIGEST},
            'borrow-signed-original-whole-carrier-changed')
    with zipfile.ZipFile(archive) as carrier:
        row = carrier.getinfo(PREFIX + RECEIPT)
        require(0 < row.file_size <= 4*1024**2
                and carrier.read(row) == read_file(directory/RECEIPT,4*1024**2),
                'borrow-signed-original-receipt-bytes-changed')
    own = receipt(json.loads(read_file(directory / RECEIPT, 4 * 1024**2)))
    require(git('producer-tree', 'git', 'rev-parse', HEAD + '^{tree}').decode().strip() == own['sourceTree'],
            'borrow-signed-immutable-producer-tree')
    for name, identity in own['recipe'].items():
        raw = git('producer-source', 'git', 'show', HEAD + ':' + name)
        require({'bytes': len(raw), 'sha256': digest(raw)} == identity, 'borrow-signed-immutable-producer-recipe')
    rust = read_file(directory/'actual-rust-units.stdout.log',1024**2)
    unit_commands = [row for row in own['commands'] if row.get('label') == 'actual-rust-units']
    require(len(unit_commands) == 1 and unit_commands[0]['returncode'] == 0
            and unit_commands[0]['stdout'] == {'bytes':len(rust),'sha256':digest(rust)},
            'borrow-signed-original-raw-rust-log')
    for field in ('nativeRows','lifecycleRows'):
        for row in own[field]:
            require(json.loads(read_file(directory/(row['case']+'.stdout.log'),1024**2)) == row,
                    'borrow-signed-original-raw-native-row')
    engine = directory / 'engine'
    require({name: file_identity(engine / name, 64 * 1024**2) for name in PRODUCTS} == own['engineProducts'],
            'borrow-signed-original-engine-product-identities')
    profile = runtime_profile.IMPORT_PROFILE
    envelope = json.loads(read_file(engine / 'engine-input.json', 65536))
    sdk = {name: read_file(ROOT / name) for name in activation_engine.engine_input_paths(profile)}
    runtime_profile.validate_engine(envelope, read_file(engine / 'engine.wasm', 64 * 1024**2), sdk,
        read_file(ROOT / 'wit/platform/activation-runtime/package.wit'), profile=profile)
    splicer = native_build.source_splicer(directory / 'splicer')
    require(splicer == own['splicer'] and envelope['compilerSplicerInputDigest'] == splicer['inputDigest']
            and envelope['buildReceiptDigest'] == digest(read_file(engine / 'engine-compilation.json'))
            and envelope['sourceDerivationDigest'] == digest(read_file(engine / 'source-derivation.json')),
            'borrow-signed-normal-engine-splicer-pair')
    return {'producerHead': HEAD, 'producerRun': RUN, 'producerJob': JOB,
            'producerScope': SCOPE, 'originalReceipt': file_identity(directory / RECEIPT, 4 * 1024**2),
            'engineProducts': own['engineProducts'], 'splicer': splicer,
            'engineRebuilt': False, 'libraryRebuilt': False, 'producerCanonicalQualification': False}


def prepare(output):
    pinned()
    output = output.resolve()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'borrow-signed-separated-products')
    output = fresh(output)
    run, job, artifact = api('actions/runs/' + str(RUN)), api('actions/jobs/' + str(JOB)), api('actions/artifacts/' + str(ARTIFACT))
    metadata(run, job, artifact)
    token = os.environ.get('GH_TOKEN')
    require(type(token) is str and 0 < len(token) <= 4096, 'borrow-signed-read-token')
    request = urllib.request.Request('https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/' + str(ARTIFACT) + '/zip',
                                    headers={'Authorization': 'Bearer ' + token})
    try: urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'borrow-signed-artifact-redirect')
        location = error.headers['Location']
    else: raise ValueError('borrow-signed-redirect-required')
    parsed = urllib.parse.urlsplit(location)
    require(parsed.scheme == 'https' and parsed.username is None and parsed.password is None
            and parsed.hostname is not None and parsed.port in (None, 443)
            and (parsed.hostname.endswith('.blob.core.windows.net') or parsed.hostname.endswith('.githubusercontent.com')),
            'borrow-signed-artifact-origin')
    archive = output / 'producer.zip'
    expires, count = time.monotonic() + 180, 0
    # Deliberately no Authorization on the authenticated blob redirect.
    with urllib.request.urlopen(location, timeout=90) as response, archive.open('xb') as target:
        while block := response.read(1024**2):
            count += len(block)
            require(count <= ARCHIVE_BYTES and time.monotonic() < expires, 'borrow-signed-acquisition-bound')
            target.write(block)
    inventory = extract(archive, output / 'products')
    value = {'schemaVersion': 'latent.typescript.borrow-signed-inputs.v1', 'head': HEAD,
             'run': RUN, 'job': JOB, 'artifact': ARTIFACT,
             'archive': file_identity(archive, MAX_ARCHIVE), 'members': inventory,
             'credentialsRetained': False, 'producerScope': SCOPE}
    write_json(output / 'ACQUIRED.json', value)
    require(time.monotonic() < expires, 'borrow-signed-acquisition-final-deadline')
    return value
