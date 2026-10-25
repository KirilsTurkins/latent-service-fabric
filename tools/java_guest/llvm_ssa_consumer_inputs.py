"""One compiler-only producer input; no wildcard, artifact rebuild or SDK fallback."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from tools.java_guest import llvm_ssa_distribution as carrier
from tools.java_guest import llvm_ssa_patch as patch, llvm_ssa_results as observations
from tools.java_guest import llvm_ssa_io as io
from tools.java_guest import llvm_ssa_producer as producer
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

HEAD = '4545bf149d8ea732e78c25509d5f90ffd16e3ad8'
TREE = '0f367a488e02157c411bc15245ce83f6ee88819c'
BRANCH = 'feat/java-llvm-ssa-producer-20261025'
RUN, JOB, ATTEMPT = 40174439697, 121111971805, 1
REPOSITORY = 'KirilsTurkins/latent-service-fabric'
WORKFLOW = '.github/workflows/java-llvm-ssa-producer.yml'
CONSUMER_BRANCH = 'feat/java-llvm-ssa-consumer-20261025'
RECIPE_SHA = '5ee91c2e0a268025e8c2f9c50c64b0732c1098c13ff8bb9be728d7240699e7e8'
# Actual source/test/code-generation-qualified compiler carrier, independently
# authenticated after R7 success. This admits only the explicit public compiler
# qualification; the normal SDK29 default and runtime admission are unchanged.
QUALIFIED = {
    'artifactId': 12593061730, 'archiveBytes': 167405228,
    'archiveSha256': '7dffc969ad2f91ebc61126f5df0b15ba4a410733704a0abee5f60ce83ef7cb48',
    'carrier': {'bytes': 159518361,
                'sha256': '07032a463018271517dd26fde68b99716937fa5e231c3430ace811f610ae0d37'},
    'manifest': {'bytes': 2101975,
                 'sha256': '1128cf1ee945220f2fa48e2891489cac35b153214c1ea05e35ab310fecd49685'},
    'originVersion': {'bytes': 90,
                      'sha256': 'cb9fa6c932384a5f2f90f576936415a7f256eeb1d9a7c38a3c300320bfad6e23'},
}
NOTICES = {
    'NOTICE': {'bytes': 4708, 'sha256': '350313e55ccde2f2cc2aa4db88d3c870071316497f47e31a431fa83850f1456a'},
    'LLVM-LICENSE.txt': {'bytes': 15141, 'sha256': '8d85c1057d742e597985c7d4e6320b015a9139385cff4cbae06ffc0ebe89afee'},
    'LLVM-PATCH.json': {'bytes': 211777, 'sha256': patch.PATCH_SHA256},
}
LIT_LOCK = {'bytes': 174, 'sha256': '97f9e06a7255f789c87d21f91e8ee463f5f9a0cdafd5d1411e9433b092a8a858'}
STAGES = (
    'host-git-version', 'host-cmake-version', 'host-ninja-version', 'host-gcc-version',
    'host-gpp-version', 'host-readelf-version', 'host-python-version', 'repository-head',
    'configure-reviewed-llvm', 'build-reviewed-llvm-and-tests', 'ssa-updater-bulk-units',
    'original-sjlj-lit', 'sjlj-phi-through-wineh', 'sjlj-phi-instruction-selection',
    'install-reviewed-compiler', 'compiled-clang-dynamic-dependencies',
    'compiled-llvm-dynamic-dependencies', 'compiled-clang-cpp-dynamic-dependencies',
    'packaged-derived-clang-version', 'final-repository-head',
)


def need(condition, reason: str) -> None:
    if not condition:
        raise ValueError('java-llvm-input-' + reason)


def identity(raw: bytes) -> dict:
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def pinned() -> dict:
    value = QUALIFIED
    need(type(value) is dict and set(value) == {
        'artifactId', 'archiveBytes', 'archiveSha256', 'carrier', 'manifest', 'originVersion'}, 'qualified-tuple-unfilled')
    need(type(value['artifactId']) is int and value['artifactId'] > 0
         and type(value['archiveBytes']) is int and 0 < value['archiveBytes'] <= carrier.UPLOAD_BYTES
         and type(value['archiveSha256']) is str
         and re.fullmatch(r'[0-9a-f]{64}', value['archiveSha256']), 'qualified-tuple')
    for field, maximum in [('carrier', carrier.CARRIER_BYTES), ('manifest', carrier.MANIFEST_BYTES),
                           ('originVersion', 1024)]:
        row = value[field]
        need(type(row) is dict and set(row) == {'bytes', 'sha256'}
             and type(row['bytes']) is int and 0 < row['bytes'] <= maximum
             and type(row['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', row['sha256']),
             'qualified-tuple')
    return value


def metadata(run: dict, job: dict, artifact: dict) -> None:
    pin = pinned()
    need(run.get('id') == RUN and run.get('run_attempt') == ATTEMPT
         and run.get('head_sha') == HEAD and run.get('head_branch') == BRANCH
         and run.get('path') == WORKFLOW and run.get('event') == 'push'
         and run.get('status') == 'completed' and run.get('conclusion') == 'success'
         and run.get('head_commit', {}).get('tree_id') == TREE, 'successful-producer')
    need(job.get('id') == JOB and job.get('run_id') == RUN and job.get('head_sha') == HEAD
         and job.get('name') == 'Build and test one source-bound LLVM 21 compiler'
         and job.get('status') == 'completed' and job.get('conclusion') == 'success'
         and type(job.get('steps')) is list and job['steps']
         and all(s.get('status') == 'completed' and s.get('conclusion') == 'success'
                 for s in job['steps']), 'successful-job')
    need(artifact.get('id') == pin['artifactId'] and artifact.get('expired') is False
         and artifact.get('name') == 'java-llvm-ssa-producer-' + HEAD
         and artifact.get('workflow_run', {}).get('id') == RUN
         and artifact.get('workflow_run', {}).get('head_sha') == HEAD
         and artifact.get('size_in_bytes') == pin['archiveBytes']
         and artifact.get('digest') == 'sha256:' + pin['archiveSha256'], 'exact-artifact')


def read(archive, index: dict, name: str, maximum: int) -> bytes:
    need(name in index and 0 < index[name].file_size <= maximum, 'fixed-member')
    with archive.open(index[name]) as stream:
        raw = stream.read(maximum + 1)
    need(len(raw) == index[name].file_size and len(raw) <= maximum, 'fixed-member')
    return raw


def producer_settings(own: dict) -> None:
    """Authenticate the reviewed operating profile, without a RAM-fit claim."""
    for field, expected in [('aggregateSeconds', 5400), ('buildCommandSeconds', 4500),
                            ('buildJobs', 4), ('compileJobs', 4), ('linkJobs', 1)]:
        need(type(own.get(field)) is int and own[field] == expected, 'producer-build-settings')
    need(own.get('litTimeoutSupport') == {
        'name': 'psutil', 'version': '7.1.3', 'litTimeoutSeconds': 60,
        'support': 'pinned-lit-linux-psutil'}, 'producer-lit-timeout')
    pools = own.get('buildPools', {})
    cache = pools.get('cache', {}) if type(pools) is dict else {}
    need(type(pools) is dict and set(pools) == {'compileJobs', 'linkJobs', 'cache'}
         and type(pools.get('compileJobs')) is int and pools['compileJobs'] == 4
         and type(pools.get('linkJobs')) is int and pools['linkJobs'] == 1
         and type(cache) is dict and set(cache) == {'bytes', 'sha256'}
         and type(cache.get('bytes')) is int and 0 < cache['bytes'] <= 1024 ** 2
         and type(cache.get('sha256')) is str and re.fullmatch(r'[0-9a-f]{64}', cache['sha256']),
         'producer-build-pools')
    capacity = own.get('hostCapacity', {})
    need(type(capacity) is dict and capacity.get('status') == 'admitted'
         and capacity.get('reason') == 'operational-preconditions-met'
         and capacity.get('hardRssQuota') is False and capacity.get('memoryFitQualified') is False,
         'producer-host-capacity')
    for observed, minimum, expected in [
        ('effectiveCpuMilli', 'minimumCpuMilli', 4000),
        ('effectiveTotalBytes', 'minimumTotalBytes', 12 * io.GIB),
        ('effectiveAvailableBytes', 'minimumAvailableBytes', 10 * io.GIB),
    ]:
        need(type(capacity.get(minimum)) is int and capacity[minimum] == expected
             and type(capacity.get(observed)) is int and capacity[observed] >= expected,
             'producer-host-capacity')
    need(type(own.get('recipeInputs')) is dict and len(own['recipeInputs']) == 18
         and own['recipeInputs'].get('tools/data/java-llvm-ssa/requirements.lock') == LIT_LOCK
         and patch.sha(carrier.encode(own['recipeInputs'])) == RECIPE_SHA, 'immutable-producer-recipe')


def delivery_evidence(archive, index: dict, own: dict) -> None:
    configuration = own.get('initialConfiguration')
    need(type(configuration) is dict and set(configuration) == {'pools', 'files'}
         and own.get('retainedConfiguration') == configuration
         and configuration['pools'] == own.get('buildPools')
         and type(configuration['files']) is dict
         and set(configuration['files']) == {'retained-CMakeCache.txt', 'retained-rules.ninja'},
         'retained-configuration')
    raw_files = {name: read(archive, index, name, 1024 ** 2) for name in configuration['files']}
    need(configuration['files'] == {name: identity(raw) for name, raw in raw_files.items()},
         'retained-configuration-bytes')
    cache, rules = raw_files['retained-CMakeCache.txt'], raw_files['retained-rules.ninja']
    need(configuration['pools']['cache'] == identity(cache), 'retained-cache-identity')
    for key, expected in [(b'CMAKE_GENERATOR:INTERNAL', b'Ninja'),
                          (b'LLVM_PARALLEL_COMPILE_JOBS:STRING', b'4'),
                          (b'LLVM_PARALLEL_LINK_JOBS:STRING', b'1')]:
        need(re.findall(rb'^' + re.escape(key) + rb'=([^\r\n]*)\r?$', cache, re.MULTILINE) == [expected],
             'retained-cache-value')
    for pool, depth in [(b'compile_job_pool', b'4'), (b'link_job_pool', b'1')]:
        need(re.findall(rb'^pool ' + pool + rb'\r?\n[ ]+depth = ([0-9]+)\r?$', rules,
                        re.MULTILINE) == [depth], 'retained-ninja-value')
    def disk_row(value):
        need(type(value) is dict and set(value) == {'entries', 'logicalBytes'}
             and type(value['entries']) is int and 0 <= value['entries'] <= 200000
             and type(value['logicalBytes']) is int and 0 <= value['logicalBytes'] <= 16 * io.GIB,
             'delivery-disk-row')
    retired = own.get('buildRetirement')
    need(type(retired) is dict and set(retired) == {'child', 'before', 'removedDescendants',
         'removedRoot', 'afterOwned', 'liveCompilerChildren', 'childObservationBasis', 'otherOwnedRootsRetired'}
         and retired['child'] == 'build' and retired['removedRoot'] is True
         and type(retired['liveCompilerChildren']) is int and retired['liveCompilerChildren'] == 0
         and retired['childObservationBasis'] == 'completed-original-process-owner'
         and retired['otherOwnedRootsRetired'] is False, 'delivery-retirement')
    disk_row(retired['before'])
    disk_row(retired['afterOwned'])
    disk_row(own.get('finalOwnedDisk'))
    need(type(retired['removedDescendants']) is int
         and retired['removedDescendants'] == retired['before']['entries'] > 0, 'delivery-retired-count')
    early = own.get('earlyPackageProjection')
    need(type(early) is dict and set(early) == {'existingEntries', 'sdkEntries',
         'headerEntriesIncludingRoot', 'fixedInstallAllowance', 'fixedProductAllowance',
         'evidenceEntryAllowance', 'projectedEntries', 'entryLimit', 'buildMustBeRetired'}
         and all(type(early[key]) is int and 0 < early[key] <= 200000
                 for key in early if key != 'buildMustBeRetired')
         and early['buildMustBeRetired'] is True and early['entryLimit'] == 200000
         and early['fixedInstallAllowance'] == 32 and early['fixedProductAllowance'] == 16
         and early['evidenceEntryAllowance'] == 512
         and early['projectedEntries'] == early['existingEntries'] + early['sdkEntries'] + 1
             + early['headerEntriesIncludingRoot'] + 32 + 16 + 512, 'delivery-early-projection')
    projection = own.get('products', {}).get('copyEntryProjection')
    need(type(projection) is dict and set(projection) == {
         'existingEntries', 'additionalEntries', 'projectedEntries', 'entryLimit'}
         and all(type(value) is int and 0 <= value <= 200000 for value in projection.values())
         and projection['entryLimit'] == 200000
         and projection['existingEntries'] == retired['afterOwned']['entries']
         and projection['projectedEntries'] == projection['existingEntries'] + projection['additionalEntries']
         and own['finalOwnedDisk']['entries'] <= projection['projectedEntries'] <= early['projectedEntries'],
         'delivery-copy-projection')
    product = own.get('products', {})
    closure = product.get('compiledElfClosure')
    need(type(closure) is dict and set(closure) == {'driver', 'llvm', 'clang'}
         and type(product.get('derivedSdk')) is dict, 'delivery-two-dso-closure')
    for role, stage, member in [
            ('driver', 'compiled-clang-dynamic-dependencies', 'bin/clang-21'),
            ('llvm', 'compiled-llvm-dynamic-dependencies', 'lib/' + producer.LLVM_SONAME),
            ('clang', 'compiled-clang-cpp-dynamic-dependencies', 'lib/' + producer.CLANG_SONAME)]:
        raw = read(archive, index, f'commands/{STAGES.index(stage):02d}-{stage}.stdout.log', 4 * 1024 ** 2)
        parsed = producer.elf_closure(raw, role)
        parsed.update(member=member, identity=product['derivedSdk'].get(member))
        need(type(parsed['identity']) is dict and 'link' not in parsed['identity']
             and closure[role] == parsed, 'delivery-two-dso-binding')


def selected(archive: zipfile.ZipFile, deadline: float) -> tuple[dict, dict, dict]:
    """Validate the exact uploaded file union before extracting any product."""
    pin = pinned()
    entries = archive.infolist()
    index = {row.filename: row for row in entries}
    need(0 < len(index) == len(entries) <= 512
         and sum(row.file_size for row in entries) <= carrier.UPLOAD_BYTES, 'zip-bound')
    fixed = set(carrier.FIXED_METADATA) | {carrier.ARCHIVE, 'upload-admission.json'}
    for row in entries:
        carrier.check_time(deadline)
        name = row.filename
        carrier.name_check(name)
        need(not row.is_dir() and not row.flag_bits & 1
             and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG)
             and (name in fixed or re.fullmatch(
                 r'commands/[0-9]{2}-[a-z0-9-]{1,80}\.(stdout|stderr)\.log', name)), 'zip-member')
    admission = json.loads(read(archive, index, 'upload-admission.json', 65536))
    need(admission.get('schemaVersion') == 'latent.java.llvm-sjlj-upload.v1'
         and admission.get('sourceCommit') == HEAD and admission.get('qualifiedCompiler') is True
         and admission.get('carrier') == pin['carrier']
         and type(admission.get('metadata')) is dict
         and set(index) == set(admission['metadata']) | {carrier.ARCHIVE, 'upload-admission.json'},
         'uploaded-union')
    need(admission.get('metadataByteLimit') == carrier.METADATA_BYTES
         and admission.get('carrierByteLimit') == carrier.CARRIER_BYTES
         and admission.get('uploadedByteLimit') == carrier.UPLOAD_BYTES
         and sum(index[n].file_size for n in index if n != carrier.ARCHIVE) <= carrier.METADATA_BYTES,
         'evidence-bound')
    for name, expected in {**admission['metadata'], carrier.ARCHIVE: pin['carrier']}.items():
        maximum = (carrier.CARRIER_BYTES if name == carrier.ARCHIVE else
                   carrier.FIXED_METADATA.get(name, 4 * 1024 ** 2))
        need(name in index and type(expected) is dict and set(expected) == {'bytes', 'sha256'}
             and type(expected['bytes']) is int and type(expected['sha256']) is str
             and re.fullmatch(r'[0-9a-f]{64}', expected['sha256'])
             and expected.get('bytes') == index[name].file_size <= maximum, 'uploaded-member')
        hasher, count = hashlib.sha256(), 0
        with archive.open(index[name]) as stream:
            while raw := stream.read(65536):
                carrier.check_time(deadline)
                count += len(raw)
                need(count <= maximum, 'uploaded-member')
                hasher.update(raw)
        need({'bytes': count, 'sha256': hasher.hexdigest()} == expected, 'uploaded-member-hash')
    own = json.loads(read(archive, index, 'result.json', 8 * 1024 ** 2))
    need(own.get('schemaVersion') == 'latent.java.llvm-sjlj-producer.v1'
         and own.get('status') == 'passed' and own.get('profile') == carrier.PROFILE
         and own.get('source', {}).get('sourceCommit') == HEAD
         and own['source'].get('event') == 'push' and own['source'].get('runId') == str(RUN)
         and own['source'].get('runAttempt') == str(ATTEMPT)
         and own['source'].get('workflowRef') == REPOSITORY + '/' + WORKFLOW + '@refs/heads/' + BRANCH
         and own.get('javaComponentQualification') is False and own.get('javaRuntimeQualification') is False
         and own.get('llvmCommit') == patch.LLVM and own.get('sdkSourceCommit') == patch.SDK,
         'producer-receipt')
    producer_settings(own)
    need(own.get('patch') == {
        'schemaVersion': patch.SCHEMA, 'llvmCommit': patch.LLVM, 'wasiSdkCommit': patch.SDK,
        'patchSha256': patch.PATCH_SHA256, 'upstreamCommits': list(patch.UPSTREAM),
        'before': patch.identities('original'), 'after': patch.identities('modified')}, 'four-source-postimages')
    need(own.get('finalSource') == own.get('patchedSource')
         and own['patchedSource']['files'] == patch.identities('modified')
         and own['originalSource']['files'] == patch.identities('original'), 'source-invariance')
    source = json.loads(read(archive, index, 'source.json', 8 * 1024 ** 2))
    need(source == {'before': own['originalSource'], 'patch': own['patch'], 'after': own['patchedSource']},
         'source-receipt')
    tests = own.get('tests', {})
    need(tests.get('units') == observations.units(read(archive, index, 'units.xml', 256 * 1024))
         and tests.get('originalSjLj') == observations.lit(read(archive, index, 'lit.xml', 256 * 1024)),
         'actual-test-xml')
    cross = observations.cross_pass(read(archive, index, 'sjlj-through-wineh.ll', 256 * 1024))
    obj = read(archive, index, 'sjlj-through-wineh.o', 1024 ** 2)
    need(obj.startswith(b'\0asm\x01\0\0\0'), 'actual-codegen-object')
    cross['object'] = identity(obj)
    need(tests.get('crossPass') == cross, 'actual-cross-pass')
    commands = json.loads(read(archive, index, 'commands.json', 8 * 1024 ** 2))
    need(type(commands) is list and [c.get('stage') for c in commands] == list(STAGES)
         and own.get('commands') == len(commands), 'actual-commands')
    for ordinal, command in enumerate(commands):
        need(type(command.get('exitCode')) is int and command['exitCode'] == 0
             and 'failure' not in command and 'postCheckFailure' not in command, 'command-outcome')
        for channel in ('stdout', 'stderr'):
            name = f'commands/{ordinal:02}-{command["stage"]}.{channel}.log'
            need(command.get(channel) == admission['metadata'].get(name), 'raw-command-channel')
    delivery_evidence(archive, index, own)
    value = json.loads(read(archive, index, carrier.MANIFEST, carrier.MANIFEST_BYTES))
    need(identity(read(archive, index, carrier.MANIFEST, carrier.MANIFEST_BYTES)) == pin['manifest'],
         'manifest-identity')
    carrier.validate_manifest(value, deadline)
    need(value['sourceCommit'] == HEAD and own.get('distribution', {}).get('archive') == {
        'path': carrier.ARCHIVE, **pin['carrier']}
        and own['distribution'].get('manifest') == {'path': carrier.MANIFEST, **pin['manifest']},
        'distribution-identity')
    for name, expected in NOTICES.items():
        row = value['members'].get(name, {})
        need(row.get('kind') == 'file' and {k: row.get(k) for k in ('bytes', 'sha256')} == expected,
             'source-notice')
    return index, own, value


def _hash_file(path: Path, maximum: int, deadline: float) -> dict:
    return carrier.file_identity(path.parent, path.name, maximum, deadline)


def extract_payload(directory: Path, manifest: dict, deadline: float) -> Path:
    """All bytes/headers are validated before writes; links are created last."""
    carrier.verify_carrier(directory, carrier.ARCHIVE, manifest, deadline)
    target = io.fresh(directory / 'products')
    rows = manifest['members']
    for name in sorted(rows, key=lambda n: (n.count('/'), n)):
        if rows[name]['kind'] == 'directory':
            (target / name).mkdir(mode=0o700)
    with tarfile.open(directory / carrier.ARCHIVE, 'r|gz') as archive:
        for member in archive:
            carrier.check_time(deadline)
            if member.name == 'MANIFEST.json':
                continue
            row = rows[member.name]
            if row['kind'] != 'file':
                continue
            path = target / member.name
            need(path.parent.resolve(strict=True).is_relative_to(target), 'extract-parent')
            hasher, count = hashlib.sha256(), 0
            with archive.extractfile(member) as source, path.open('xb') as output:
                while block := source.read(65536):
                    carrier.check_time(deadline)
                    count += len(block)
                    need(count <= row['bytes'], 'extract-file-bound')
                    hasher.update(block)
                    output.write(block)
            need({'bytes': count, 'sha256': hasher.hexdigest()} == {
                k: row[k] for k in ('bytes', 'sha256')}, 'extract-file-identity')
            path.chmod(row['mode'])
    for name, row in rows.items():
        if row['kind'] == 'symlink':
            carrier.check_time(deadline)
            (target / name).symlink_to(row['link'])
    for name in sorted(rows, key=lambda n: (-n.count('/'), n)):
        if rows[name]['kind'] == 'directory':
            (target / name).chmod(rows[name]['mode'])
    need(carrier.payload_rows(target, deadline) == rows, 'decoded-closure')
    return target


def verify_runtime_preservation(own: dict, manifest: dict) -> None:
    pin = pinned()
    product = own.get('products', {})
    before, after = product.get('baseSdk'), product.get('derivedSdk')
    changed, added = product.get('changedCompilerMembers'), product.get('addedCompilerMembers')
    need(type(before) is dict and type(after) is dict and type(changed) is list
         and type(added) is list and len(set(changed)) == len(changed)
         and len(set(added)) == len(added) and product.get('runtimeSysrootLldPreserved') is True,
         'original-sdk-inventory')
    for name in changed:
        need(PurePosixPath(name).parent.as_posix() == 'bin'
             and re.fullmatch(r'clang(?:-21|\+\+|-cl|-cpp)?', PurePosixPath(name).name),
             'compiler-change-set')
    for name in added:
        path = PurePosixPath(name)
        need((path.parent.as_posix() == 'lib' and re.fullmatch(r'(?:libLLVM|libclang-cpp)[A-Za-z0-9._+-]*', path.name))
             or (path.parent.as_posix() == 'bin' and re.fullmatch(r'clang(?:-21|\+\+|-cl|-cpp)?', path.name)),
             'compiler-add-set')
    need(set(changed) <= before.keys() and not set(added) & before.keys()
         and set(after) == set(before) | set(added) and changed and added, 'compiler-member-set')
    # Bind the actual preserved bytes from the authenticated original SDK,
    # never a reconstruction of the five semantic VERSION lines.
    origin = manifest['members'].get('official-origin-VERSION', {})
    need(origin.get('kind') == 'file'
         and {k: origin.get(k) for k in ('bytes', 'sha256')} == pin['originVersion']
         and {k: before.get('VERSION', {}).get(k) for k in ('bytes', 'sha256')} == pin['originVersion']
         and product.get('officialArchive') == io.SDK_SOURCE, 'origin-version')
    for name, row in before.items():
        if name not in changed and name != 'VERSION':
            need(after.get(name) == row, 'runtime-member-mutated')
    actual = {}
    for name, row in manifest['members'].items():
        if not name.startswith('toolchain/') or row['kind'] == 'directory':
            continue
        actual[name.removeprefix('toolchain/')] = (
            {'link': row['link']} if row['kind'] == 'symlink' else
            {'bytes': row['bytes'], 'sha256': row['sha256'], 'executable': bool(row['mode'] & 0o111)})
    need(actual == after, 'actual-derived-sdk')
    llvm, clang = product.get('customLlvmLibrary'), product.get('customClangLibrary')
    real = {'lib/' + producer.LLVM_SONAME, 'lib/' + producer.CLANG_SONAME}
    libraries = {name: after[name] for name in added if PurePosixPath(name).parent.as_posix() == 'lib'}
    need(llvm == producer.LLVM_SONAME and clang == producer.CLANG_SONAME
         and {name for name, row in libraries.items() if 'link' not in row} == real
         and len(libraries) <= 8 and product.get('retainedSourceNotices') == NOTICES,
         'loader-and-notices')
    producer.install_overlay({}, {**libraries, 'bin/clang-21': after['bin/clang-21']})


def decode(archive: Path, directory: Path, deadline: float):
    pin = pinned()
    need(_hash_file(archive, carrier.UPLOAD_BYTES, deadline) == {
        'bytes': pin['archiveBytes'], 'sha256': pin['archiveSha256']}, 'archive-before-parse')
    with zipfile.ZipFile(archive) as zipped:
        index, own, manifest = selected(zipped, deadline)
        verify_runtime_preservation(own, manifest)
        for name, member in index.items():
            carrier.check_time(deadline)
            destination = directory / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as source, destination.open('xb') as output:
                count = 0
                while block := source.read(65536):
                    carrier.check_time(deadline)
                    count += len(block)
                    need(count <= member.file_size, 'extract-zip-member')
                    output.write(block)
            need(count == member.file_size, 'extract-zip-member')
    need(_hash_file(archive, carrier.UPLOAD_BYTES, deadline) == {
        'bytes': pin['archiveBytes'], 'sha256': pin['archiveSha256']}, 'archive-after-decode')
    products = extract_payload(directory, manifest, deadline)
    return _Admitted(directory, products, own, manifest, deadline)


def _root() -> Path:
    temp = os.environ.get('RUNNER_TEMP', '')
    need(bool(temp) and Path(temp).is_absolute(), 'owned-output-context')
    return Path(temp) / 'java-llvm-public-inputs'


class _Admitted:
    """Private compiler-input record; no grant, refund or general SDK token."""
    def __init__(self, directory, products, own, manifest, deadline):
        self.directory, self.products = directory, products
        self.sdk = products / 'toolchain'
        self.own, self.manifest, self.deadline = own, manifest, deadline

    def recheck(self, sdk: Path) -> None:
        pin = pinned()
        need(self.directory == _root() and self.products == self.directory / 'products'
             and sdk == self.sdk and sdk == _root() / 'products/toolchain', 'fixed-sdk-root')
        need(carrier.payload_rows(self.products, self.deadline) == self.manifest['members'], 'sdk-changed')
        origin = patch.regular(self.products, 'official-origin-VERSION', 1024)
        from tools.java_guest.llvm_ssa_producer import OFFICIAL_VERSION
        need(identity(origin) == pin['originVersion']
             and origin.decode('utf-8').splitlines() == OFFICIAL_VERSION, 'origin-version')
        need(_hash_file(self.directory / carrier.ARCHIVE, carrier.CARRIER_BYTES, self.deadline) == pin['carrier']
             and identity(patch.regular(self.directory, carrier.MANIFEST, carrier.MANIFEST_BYTES)) == pin['manifest'],
             'carrier-changed')


def _response(request, deadline, *, maximum):
    carrier.check_time(deadline)
    raw = bytearray()
    with urllib.request.build_opener(NoRedirect).open(
            request, timeout=min(30, deadline - time.monotonic())) as response:
        while block := response.read1(min(65536, maximum + 1 - len(raw))):
            carrier.check_time(deadline)
            raw.extend(block)
            need(len(raw) <= maximum, 'api-bound')
    carrier.check_time(deadline)
    return bytes(raw)


def prepare(deadline: float):
    """Only the fixed reviewed successful tuple can reach any IO or HTTP."""
    pin = pinned()
    import sys
    revision = os.environ.get('GITHUB_SHA', '')
    ref = os.environ.get('GITHUB_REF', '')
    need(sys.platform == 'linux' and os.environ.get('GITHUB_REPOSITORY') == REPOSITORY
         and os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
         and os.environ.get('GITHUB_WORKSPACE') == str(patch.ROOT)
         and re.fullmatch(r'[0-9a-f]{40}', revision)
         and os.environ.get('GITHUB_WORKFLOW_SHA') == revision
         and ref == 'refs/heads/' + CONSUMER_BRANCH
         and os.environ.get('GITHUB_WORKFLOW_REF') == REPOSITORY
             + '/.github/workflows/java-guest-feasibility.yml@' + ref, 'hosted-only')
    token = os.environ.get('GH_TOKEN', '')
    need(0 < len(token) <= 4096, 'read-token')
    consumer_deadline = deadline
    deadline = min(deadline, time.monotonic() + 600)
    network_deadline = min(deadline, time.monotonic() + 180)
    output = io.fresh(_root())
    env = build_environment(output)
    git = shutil.which('git', path=env.get('PATH'))
    need(git is not None, 'source-git')
    head = run_bounded_result([git, '--no-lazy-fetch', 'rev-parse', '--verify', 'HEAD'],
        patch.ROOT, env, timeout_seconds=min(5, deadline - time.monotonic()), max_output_bytes=4096)
    need(head.returncode == 0 and head.stdout.strip() == revision.encode(), 'source-head')
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}
    base = 'https://api.github.com/repos/' + REPOSITORY + '/'
    values = []
    for path in ('actions/runs/' + str(RUN), 'actions/jobs/' + str(JOB),
                 'actions/artifacts/' + str(pin['artifactId'])):
        values.append(json.loads(_response(urllib.request.Request(base + path, headers=headers),
                                           network_deadline, maximum=4 * 1024 ** 2)))
    metadata(*values)
    request = urllib.request.Request(base + 'actions/artifacts/' + str(pin['artifactId']) + '/zip',
                                     headers=headers)
    try:
        urllib.request.build_opener(NoRedirect).open(
            request, timeout=min(30, network_deadline - time.monotonic()))
    except urllib.error.HTTPError as error:
        try:
            need(error.code == 302, 'artifact-redirect')
            location = error.headers['Location']
        finally:
            error.close()
    else:
        raise ValueError('java-llvm-input-redirect-required')
    parsed = urllib.parse.urlsplit(location)
    need(parsed.scheme == 'https' and parsed.username is None and parsed.password is None
         and parsed.port in (None, 443) and parsed.hostname is not None
         and (parsed.hostname.endswith('.blob.core.windows.net')
              or parsed.hostname.endswith('.githubusercontent.com')), 'artifact-origin')
    archive = output / 'producer.zip'
    count = 0
    # The signed blob request has NO GitHub Authorization header.
    with urllib.request.urlopen(location, timeout=min(30, network_deadline - time.monotonic())) as response, \
            archive.open('xb') as destination:
        while block := response.read1(65536):
            carrier.check_time(network_deadline)
            count += len(block)
            need(count <= pin['archiveBytes'], 'artifact-transfer')
            destination.write(block)
    need(count == pin['archiveBytes'], 'artifact-transfer')
    admitted = decode(archive, output, deadline)
    admitted.deadline = consumer_deadline
    for name, value in zip(('producer-run.json', 'producer-job.json', 'producer-artifact.json'), values):
        (output / name).write_bytes(carrier.encode(value))
    return admitted
