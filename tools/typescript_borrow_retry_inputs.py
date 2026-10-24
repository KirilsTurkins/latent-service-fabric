"""Frozen completed source products from the FAILED native-control producer.

The library/engine succeeded; the diagnostic never ran. No failure is promoted
or receipt rewritten, and no library/engine build is permitted by this reader.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.java_replay_materials import api, NoRedirect
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json, digest
from tools.typescript_guest import activation_engine, native_build, runtime_profile

HEAD = 'e2dfcf6d1b48b650fee585e83cd15720bf7f745c'
TREE = '169a2fcdd2910c0f434e98c61e93bdba3d6b4888'
RUN, JOB, ARTIFACT = 40042939576, 120717969106, 12541695434
ARCHIVE_BYTES = 379457196
ARCHIVE_SHA = 'ee36984b8ba08fe33d37da3e65b6c6a55624487d1206029ff4d5dd2d91851b8c'
PREFIX = 'typescript-borrow-controls/'
ENGINE = PREFIX + 'engine/'
SPLICER = 'typescript-borrow-splicer/splicer/'
MAX_MEMBERS, MAX_TOTAL = 1024, 2 * 1024**3
RECEIPTS = {
    PREFIX + 'FAILED.json': (1061273, 'd0531e73e4ce7b6b1a4647749e934576dff1b1160778e36d96b35cf78576d460'),
    PREFIX + 'library/library-build.json': (6144, 'e5c7e5e5181424c1b813215cca7077ece4d1a7ca9beee4704a9fb42cd58aea6a'),
    ENGINE + 'engine-build.json': (70374, '2915a9dce23c2dfcb5281ba7a7e9ddf7a151d3ffeedeaf69b13514b572c36418'),
    ENGINE + 'engine-compilation.json': (70256, 'f19a9fa10845cf8d0ee543a483c5b30283c29afc6683e52f009c6c6f3df679b1'),
    ENGINE + 'engine-input.json': (8954, '18557c70748fd27daefa296d7bcc156533f5f943317489c3a256e16b2c78918b'),
}


def frozen_receipts(reader):
    for name, (size, sha) in RECEIPTS.items():
        raw = reader(name)
        require(len(raw) == size and digest(raw) == 'sha256:' + sha, 'borrow-retry-frozen-receipt')


def metadata(run, job, artifact):
    require(run['id'] == RUN and run['head_sha'] == HEAD and run['event'] == 'push'
            and run['path'] == '.github/workflows/typescript-borrow-release.yml'
            and run['head_branch'] == 'feat/typescript-borrow-release-source-20261024'
            and run['status'] == 'completed' and run['conclusion'] == 'failure', 'borrow-retry-failed-producer')
    require(job['id'] == JOB and job['run_id'] == RUN and job['head_sha'] == HEAD
            and job['name'] == 'One source-built library and engine with native borrow controls'
            and job['status'] == 'completed' and job['conclusion'] == 'failure'
            and [step['number'] for step in job['steps'] if step['conclusion'] == 'failure'] == [13],
            'borrow-retry-owning-diagnostic-failure')
    require(artifact['id'] == ARTIFACT and artifact['size_in_bytes'] == ARCHIVE_BYTES
            and artifact['digest'] == 'sha256:' + ARCHIVE_SHA and artifact['expired'] is False
            and artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == HEAD
            and artifact['name'] == 'typescript-borrow-controls-' + HEAD, 'borrow-retry-exact-artifact')


def selected_members(archive):
    entries = archive.infolist()
    index = {row.filename: row for row in entries}
    require(0 < len(index) == len(entries) <= MAX_MEMBERS
            and sum(row.file_size for row in entries) <= MAX_TOTAL, 'borrow-retry-archive-bound')
    for row in entries:
        path = PurePosixPath(row.filename)
        mode = row.external_attr >> 16
        require(not row.is_dir() and not path.is_absolute() and str(path) == row.filename
                and all(part not in {'', '.', '..'} for part in row.filename.split('/'))
                and ':' not in row.filename and '\\' not in row.filename
                and not row.flag_bits & 1 and stat.S_IFMT(mode) in (0, stat.S_IFREG)
                and 0 <= row.file_size, 'borrow-retry-member-type-or-path')
    def small(name):
        require(name in index and 0 < index[name].file_size <= 4 * 1024**2, 'borrow-retry-required-small-receipt')
        return json.loads(archive.read(index[name]))
    frozen_receipts(lambda name: archive.read(index[name]))
    failed = small(PREFIX + 'FAILED.json')
    engine = small(ENGINE + 'engine-compilation.json')
    built = small(ENGINE + 'engine-build.json')
    library = small(PREFIX + 'library/library-build.json')
    envelope = small(ENGINE + 'engine-input.json')
    require(failed['status'] == 'failed' and failed['stage'] == 'diagnostic-core'
            and failed['reason'] == 'BuildProcessError' and failed['sourceCommit'] == HEAD
            and failed['sourceTree'] == TREE and failed['signedExecution'] == 'not-run', 'borrow-retry-original-failure')
    require(engine['status'] == 'core-compiled' and built['status'] == 'passed'
            and library['status'] == 'passed' and engine['libraryProduct'] == {key: library['library'][key] for key in ('sha256', 'bytes')}
            and engine['libraryInput'] == {'bytes': index[PREFIX + 'library/library-build.json'].file_size,
                'sha256': digest(archive.read(index[PREFIX + 'library/library-build.json']))},
            'borrow-retry-completed-source-products')
    limits = native_build.combined_archive_limits(engine['libraryProduct'], engine['supportingObjects'])
    require(engine['archiveCompositionLimits'] == limits and built['archiveCompositionLimits'] == limits,
            'borrow-retry-original-composition-bounds')
    combined = ENGINE + 'spidermonkey/libspidermonkey.a'
    raw_library = PREFIX + 'library/obj/js/src/build/libjs_static.a'
    require(combined in index and raw_library in index
            and 0 < index[combined].file_size == engine['combinedLibrary']['bytes'] <= limits['maximumCombinedBytes']
            and 0 < index[raw_library].file_size == engine['libraryProduct']['bytes'] <= limits['originalLibraryMaximumBytes'],
            'borrow-retry-source-product-size')
    require(all(row.file_size <= 32 * 1024**2 for row in entries if row.filename not in {combined, raw_library}),
            'borrow-retry-other-member-bound')
    selected = {PREFIX + 'FAILED.json', PREFIX + 'library/library-build.json', combined,
                *(ENGINE + name for name in ('engine-build.json', 'engine-compilation.json',
                    'engine-input.json', 'source-derivation.json', 'engine.wasm')),
                *(ENGINE + 'spidermonkey/include/' + name for name in engine['installedHeaders'])}
    generated = {name for name in index if name.startswith((ENGINE + 'jobs-generated/', ENGINE + 'clocks-generated/'))}
    splicer = {name for name in index if name.startswith(SPLICER)}
    require(0 < len(generated) <= 32 and 0 < len(splicer) <= 37 and len(engine['installedHeaders']) <= 8192
            and sum(index[name].file_size for name in generated | splicer) <= 32 * 1024**2,
            'borrow-retry-generated-splicer-bounds')
    selected |= generated | splicer
    require(selected <= index.keys() and sum(index[name].file_size for name in selected - {combined}) <= 192 * 1024**2,
            'borrow-retry-selected-bounds')
    # The frozen complete carrier, including unselected original library, is CRC checked.
    require(archive.testzip() is None, 'borrow-retry-all-member-crc')
    return [row for row in entries if row.filename in selected], limits


def validate(directory: Path) -> dict:
    directory = directory.resolve(strict=True)
    frozen_receipts(lambda name: read_file(directory / name, 4 * 1024**2))
    engine_root = directory / PREFIX / 'engine'
    failed = json.loads(read_file(directory / PREFIX / 'FAILED.json', 4 * 1024**2))
    compilation = json.loads(read_file(engine_root / 'engine-compilation.json', 1024**2))
    built = json.loads(read_file(engine_root / 'engine-build.json', 1024**2))
    library = json.loads(read_file(directory / PREFIX / 'library/library-build.json', 1024**2))
    require(failed['sourceCommit'] == HEAD and failed['sourceTree'] == TREE
            and failed['status'] == 'failed' and failed['stage'] == 'diagnostic-core'
            and failed['reason'] == 'BuildProcessError' and library['status'] == 'passed'
            and compilation['status'] == 'core-compiled' and built['status'] == 'passed', 'borrow-retry-retained-status')
    profile = runtime_profile.IMPORT_PROFILE
    sdk = {name: read_file(ROOT / name) for name in activation_engine.engine_input_paths(profile)}
    envelope = json.loads(read_file(engine_root / 'engine-input.json', 65536))
    runtime_profile.validate_engine(envelope, read_file(engine_root / 'engine.wasm', 64 * 1024**2), sdk,
        read_file(ROOT / 'wit/platform/activation-runtime/package.wit'), profile=profile)
    require(envelope['buildReceiptDigest'] == digest(read_file(engine_root / 'engine-compilation.json'))
            and envelope['sourceDerivationDigest'] == digest(read_file(engine_root / 'source-derivation.json'))
            and built['input'] == file_identity(engine_root / 'engine-input.json'), 'borrow-retry-engine-receipt-chain')
    require(compilation['recipe'] == {name: file_identity(ROOT / name) for name in compilation['recipe']},
            'borrow-retry-current-source-recipe-mismatch')
    require(failed['recipe']['sdk/typescript-guest/activation/tests/native_imports.cpp'] ==
            file_identity(ROOT / 'sdk/typescript-guest/activation/tests/native_imports.cpp'), 'borrow-retry-native-controls-changed')
    limits = native_build.combined_archive_limits(compilation['libraryProduct'], compilation['supportingObjects'])
    require(compilation['archiveCompositionLimits'] == limits
            and compilation['combinedLibrary'] == file_identity(engine_root / 'spidermonkey/libspidermonkey.a',
                limits['maximumCombinedBytes']), 'borrow-retry-combined-library-differs')
    require(compilation['installedHeaders'] == {name: file_identity(engine_root / 'spidermonkey/include' / name)
            for name in compilation['installedHeaders']}, 'borrow-retry-original-headers-differ')
    generated = {path.relative_to(engine_root).as_posix(): file_identity(path, 8 * 1024**2)
                 for name in ('jobs-generated', 'clocks-generated')
                 for path in sorted((engine_root / name).rglob('*')) if path.is_file()}
    require(0 < len(generated) <= 32 and sum(row['bytes'] for row in generated.values()) <= 32 * 1024**2,
            'borrow-retry-generated-input-bound')
    splicer = native_build.source_splicer(directory / SPLICER)
    require(envelope['compilerSplicerInputDigest'] == splicer['inputDigest']
            and compilation['sourceSplicer'] == splicer, 'borrow-retry-original-splicer-pair')
    return {'producerHead': HEAD, 'producerTree': TREE, 'producerRun': RUN, 'producerJob': JOB,
            'producerConclusion': 'failure', 'diagnosticPreviouslyRun': False,
            'engineInputs': len(sdk), 'generatedInputs': generated, 'engineInput': file_identity(engine_root / 'engine-input.json'),
            'engineCore': file_identity(engine_root / 'engine.wasm', 64 * 1024**2),
            'combinedLibrary': compilation['combinedLibrary'], 'compositionLimits': limits,
            'splicer': splicer, 'qualification': 'unknown', 'libraryRebuilt': False, 'engineRebuilt': False}


def extract(archive: Path, destination: Path) -> dict:
    require(not destination.exists() and not destination.is_symlink(), 'borrow-retry-fresh-extraction')
    require(file_identity(archive, ARCHIVE_BYTES) == {'bytes': ARCHIVE_BYTES, 'sha256': 'sha256:' + ARCHIVE_SHA},
            'borrow-retry-whole-archive')
    inventory = {}
    with zipfile.ZipFile(archive) as carrier:
        selected, _limits = selected_members(carrier)
        for row in selected:
            path = destination / row.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with carrier.open(row) as source, path.open('xb') as output:
                while block := source.read(1024**2): output.write(block)
            maximum = _limits['maximumCombinedBytes'] if row.filename.endswith('/libspidermonkey.a') else 32 * 1024**2
            inventory[row.filename] = file_identity(path, maximum)
    return inventory


def prepare(output: Path) -> dict:
    output = output.resolve()
    require(output != ROOT and ROOT not in output.parents, 'borrow-retry-independent-output')
    output = fresh(output)
    run, job, artifact = api('actions/runs/' + str(RUN)), api('actions/jobs/' + str(JOB)), api('actions/artifacts/' + str(ARTIFACT))
    metadata(run, job, artifact)
    token = os.environ.get('GH_TOKEN')
    require(type(token) is str and 0 < len(token) <= 4096, 'borrow-retry-read-token')
    request = urllib.request.Request('https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/' + str(ARTIFACT) + '/zip',
                                    headers={'Authorization': 'Bearer ' + token})
    try: urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'borrow-retry-artifact-redirect'); location = error.headers['Location']
    else: raise ValueError('borrow-retry-redirect-required')
    parsed = urllib.parse.urlsplit(location)
    require(parsed.scheme == 'https' and parsed.username is None and parsed.hostname is not None
            and (parsed.hostname.endswith('.blob.core.windows.net') or parsed.hostname.endswith('.githubusercontent.com')),
            'borrow-retry-artifact-origin')
    archive = output / 'producer.zip'; count = 0; expires = time.monotonic() + 180
    with urllib.request.urlopen(location, timeout=90) as response, archive.open('xb') as target:
        while block := response.read(1024**2):
            count += len(block)
            require(count <= ARCHIVE_BYTES and time.monotonic() < expires, 'borrow-retry-acquisition-bound')
            target.write(block)
    inventory = extract(archive, output / 'products')
    validated = validate(output / 'products')
    value = {'schemaVersion': 'latent.typescript.borrow-retry-input.v1', 'run': RUN, 'job': JOB, 'head': HEAD,
             'artifact': ARTIFACT, 'archive': file_identity(archive, ARCHIVE_BYTES), 'members': inventory,
             'validated': validated, 'credentialsRetained': False, 'producerConclusion': 'failure'}
    write_json(output / 'acquisition.json', value)
    return value

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', required=True, type=Path)
    print(json.dumps(prepare(parser.parse_args().output)))
