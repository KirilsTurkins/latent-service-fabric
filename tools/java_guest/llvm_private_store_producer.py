"""One hosted source-built LLVM candidate; never a Java consumer/admission path."""
from __future__ import annotations

import json
import os
from pathlib import Path
import posixpath
import platform
import re
import shutil
import sys
import time

from tools import build_process
from tools.build_observation import build_environment, file_identity
from tools.build_process_signals import owned_cancellation
from tools.java_guest import llvm_ssa_io as io
from tools.java_guest import llvm_private_store_patch as patch, llvm_private_store_results as results
from tools.java_guest import llvm_private_store_distribution as distribution

ROOT = patch.ROOT
PROFILE = distribution.PROFILE
SUFFIX = '-wasi-sdk-' + PROFILE
SECONDS = 90 * 60
BUILD_SECONDS = 75 * 60
BUILD_JOBS = 4
LINK_JOBS = 1
LLVM_SONAME = 'libLLVM.so.21.1' + SUFFIX
CLANG_SONAME = 'libclang-cpp.so.21.1' + SUFFIX
HOST_LIBRARIES = {'libc.so.6', 'libgcc_s.so.1', 'libm.so.6', 'libpthread.so.0',
                  'libdl.so.2', 'librt.so.1', 'ld-linux-x86-64.so.2'}
REPOSITORY = 'KirilsTurkins/latent-service-fabric'
WORKFLOW = '.github/workflows/java-llvm-private-stores-producer.yml'
BRANCH = 'feat/java-llvm-private-stores-r6-20261025'
OFFICIAL_VERSION = ['29.0', 'wasi-libc: ac020b86fd44', 'llvm: 222fc11f2b8f',
                    'llvm-version: 21.1.4', 'config: f992bcc08219']
RECIPE = (
    '.github/workflows/java-llvm-ssa-producer.yml', 'NOTICE', 'tools/qualify_java_llvm_ssa.py',
    'tools/java_guest/llvm_ssa_producer.py', 'tools/java_guest/llvm_ssa_io.py',
    'tools/java_guest/llvm_ssa_patch.py', 'tools/java_guest/llvm_ssa_results.py',
    'tools/java_guest/llvm_ssa_distribution.py',
    'tools/data/java-llvm-ssa/patch.json', 'tools/data/java-llvm-ssa/tests.json',
    'tools/data/java-llvm-ssa/requirements.lock',
    'tools/data/java-llvm-ssa/LICENSE.txt', 'tools/tests/test_java_llvm_ssa_producer.py',
    'tools/build_observation.py', 'tools/build_snapshot.py', 'tools/build_process.py',
    'tools/build_process_linux.py', 'tools/build_process_signals.py',
    '.github/workflows/java-llvm-private-stores-producer.yml',
    'tools/qualify_java_llvm_private_stores.py',
    'tools/java_guest/llvm_private_store_producer.py',
    'tools/java_guest/llvm_private_store_patch.py',
    'tools/java_guest/llvm_private_store_results.py',
    'tools/java_guest/llvm_private_store_distribution.py',
    'tools/data/java-llvm-private-stores/supplement.json',
    'tools/tests/test_java_llvm_private_store_producer.py',
)


def lit_timeout_support() -> dict:
    """Fail before acquisition, using the same Python as the actual lit call.

    Pinned LLVM21 lit.util's Linux support predicate imports psutil; its kill
    path uses Process, children(recursive=True), kill and NoSuchProcess. Never
    exercise the destructive operation during preflight.
    """
    try:
        import psutil
    except ImportError as error:
        raise ValueError('llvm-producer-lit-timeout-dependency-missing') from error
    if (psutil.__version__ != '7.1.3' or not callable(psutil.Process)
            or not callable(psutil.Process.children) or not callable(psutil.Process.kill)
            or not isinstance(psutil.NoSuchProcess, type)
            or not issubclass(psutil.NoSuchProcess, Exception)):
        raise ValueError('llvm-producer-lit-timeout-dependency-identity')
    # Exercise the installed Linux extension on this process without sending
    # signals, spawning children or changing the existing process owner.
    if not psutil.Process(os.getpid()).is_running():
        raise ValueError('llvm-producer-lit-timeout-dependency-unavailable')
    return {'name': 'psutil', 'version': psutil.__version__,
            'litTimeoutSeconds': 60, 'support': 'pinned-lit-linux-psutil'}


def write(path: Path, value) -> None:
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    if len(raw) > 8 * 1024 ** 2:
        raise ValueError('llvm-producer-receipt-bound')
    path.write_bytes(raw)


def ninja_progress(root: Path, deadline: float) -> dict:
    """Count a bounded completed log prefix after original owner cleanup.

    Ninja 1.13.2 writes v7 rows as start/end/mtime/output/hash. Counts are
    diagnostics, not a planned-edge total, successful linking or qualification.
    No output path, command text, compiler binary or raw log is retained.
    """
    result = {'status': 'unavailable', 'reason': 'missing', 'diagnosticOnly': True,
              'completedLogRows': 0, 'uniqueOutputs': 0, 'latestEndMilliseconds': 0,
              'clangObjectRows': 0, 'utilsTestObjectRows': 0,
              'loggedTargets': {name: False for name in
                  ('clang', 'llvm-config', 'opt', 'llc', 'FileCheck', 'not', 'count', 'UtilsTests')}}
    if time.monotonic() >= deadline:
        result.update(status='incomplete', reason='deadline')
        return result
    try:
        raw = patch.regular(root, 'build/.ninja_log', 4 * 1024 ** 2)
    except FileNotFoundError:
        return result
    except (OSError, ValueError):
        result.update(status='incomplete', reason='input-refused')
        return result
    if not raw.startswith(b'# ninja log v7\n'):
        result.update(status='incomplete', reason='unsupported-format')
        return result
    complete = raw.endswith(b'\n')
    rows = raw.split(b'\n', 16386)[1:-1]
    outputs = set()
    targets = {b'bin/' + name.encode(): name for name in
               ('llvm-config', 'opt', 'llc', 'FileCheck', 'not', 'count')}
    targets.update({b'bin/clang': 'clang', b'bin/clang-21': 'clang',
                    b'unittests/Transforms/Utils/UtilsTests': 'UtilsTests'})
    result.update(status='observed' if complete else 'incomplete',
                  reason='complete-prefix' if complete else 'partial-tail')
    for ordinal, row in enumerate(rows):
        if ordinal >= 16384 or len(row) > 4096 or time.monotonic() >= deadline:
            result.update(status='incomplete', reason='work-bound')
            break
        fields = row.split(b'\t')
        if (len(fields) != 5 or not re.fullmatch(rb'[0-9]{1,10}', fields[0])
                or not re.fullmatch(rb'[0-9]{1,10}', fields[1])
                or not re.fullmatch(rb'-?[0-9]{1,20}', fields[2])
                or not fields[3] or not re.fullmatch(rb'[0-9a-f]{1,16}', fields[4])):
            result.update(status='incomplete', reason='row-format')
            break
        start, end = int(fields[0]), int(fields[1])
        if start > end or end > SECONDS * 1000:
            result.update(status='incomplete', reason='row-time')
            break
        output = fields[3]
        outputs.add(output)
        result['completedLogRows'] += 1
        result['latestEndMilliseconds'] = max(result['latestEndMilliseconds'], end)
        result['clangObjectRows'] += int(output.startswith(b'tools/clang/') and output.endswith(b'.o'))
        result['utilsTestObjectRows'] += int(output.startswith(
            b'unittests/Transforms/Utils/CMakeFiles/UtilsTests.dir/') and output.endswith(b'.o'))
        if output in targets:
            result['loggedTargets'][targets[output]] = True
    result['uniqueOutputs'] = len(outputs)
    return result


def admission(output: Path, *, artifact_only: bool = False) -> dict:
    """No public/custom source, compiler, CMake arguments or runner selector."""
    head = os.environ.get('GITHUB_SHA', '')
    ref = os.environ.get('GITHUB_REF', '')
    temp = os.environ.get('RUNNER_TEMP', '')
    if (sys.platform != 'linux' or platform.machine() != 'x86_64'
            or sys.version_info[:2] != (3, 13)
            or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY
            or os.environ.get('GITHUB_EVENT_NAME') != 'push'
            or os.environ.get('GITHUB_WORKSPACE') != str(ROOT)
            or not re.fullmatch(r'[0-9a-f]{40}', head)
            or os.environ.get('GITHUB_WORKFLOW_SHA') != head
            or ref != 'refs/heads/' + BRANCH
            or os.environ.get('GITHUB_WORKFLOW_REF') != REPOSITORY + '/' + WORKFLOW + '@' + ref
            or not temp or not Path(temp).is_absolute()
            or output != Path(temp) / 'java-llvm-private-stores-producer'):
        raise ValueError('llvm-producer-hosted-source-context')
    run = os.environ.get('GITHUB_RUN_ID', '')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '')
    started = os.environ.get('LSF_LLVM_PRODUCER_STARTED', '')
    if (not re.fullmatch(r'[1-9][0-9]{0,19}', run)
            or not re.fullmatch(r'[1-9][0-9]{0,5}', attempt)
            or not re.fullmatch(r'[0-9]{10}', started)):
        raise ValueError('llvm-producer-hosted-source-run')
    elapsed = time.time() - int(started)
    if not 0 <= elapsed < (95 * 60 if artifact_only else SECONDS):
        raise ValueError('llvm-producer-workflow-deadline')
    return {'sourceCommit': head, 'repository': REPOSITORY, 'workflowRef': os.environ['GITHUB_WORKFLOW_REF'],
            'event': 'push', 'runId': run, 'runAttempt': attempt,
            'startedEpoch': int(started), 'remainingSeconds': SECONDS - elapsed}


# The unchanged process/disk/reaping owner is shared, not reimplemented.
from tools.java_guest.llvm_ssa_producer import Commands

def recipe() -> dict:
    return {name: {'bytes': len(raw), 'sha256': patch.sha(raw)}
            for name in RECIPE for raw in [patch.regular(ROOT, name)]}


def source_state(run: Commands, source: Path, modified: bool) -> dict:
    identity = patch.check(source, 'modified' if modified else 'original')
    return {'revision': patch.LLVM, 'files': identity, 'originalTests': results.test_inputs(source),
            'wholeTree': io.source_identity(source, run.deadline)}


def configure(build: Path, source: Path, install: Path, tools: dict) -> list[str]:
    """Reviewed SDK29 compiler flags plus test-only tool targets; no guest flags."""
    return [str(tools['cmake']), '-G', 'Ninja', '-S', str(source / 'llvm'), '-B', str(build),
            '-DCMAKE_BUILD_TYPE=MinSizeRel', '-DCMAKE_INSTALL_PREFIX=' + str(install),
            '-DCMAKE_C_COMPILER=' + str(tools['gcc']), '-DCMAKE_CXX_COMPILER=' + str(tools['g++']),
            '-DCMAKE_MAKE_PROGRAM=' + str(tools['ninja']),
            '-DPython3_EXECUTABLE=' + sys.executable,
            '-DLLVM_ENABLE_PROJECTS=clang;lld', '-DLLVM_TARGETS_TO_BUILD=WebAssembly',
            '-DLLVM_DEFAULT_TARGET_TRIPLE=wasm32-wasi', '-DLLVM_ENABLE_ZLIB=OFF',
            '-DLLVM_ENABLE_ZSTD=OFF', '-DLLVM_ENABLE_LIBXML2=OFF', '-DLLVM_ENABLE_LIBEDIT=OFF',
            '-DLLVM_STATIC_LINK_CXX_STDLIB=ON', '-DLLVM_BUILD_LLVM_DYLIB=ON',
            '-DLLVM_LINK_LLVM_DYLIB=ON', '-DLLVM_VERSION_SUFFIX=' + SUFFIX,
            '-DLLVM_PARALLEL_COMPILE_JOBS=' + str(BUILD_JOBS),
            '-DLLVM_PARALLEL_LINK_JOBS=' + str(LINK_JOBS),
            '-DLLVM_INCLUDE_TESTS=ON', '-DLLVM_INCLUDE_UTILS=ON', '-DCLANG_INCLUDE_TESTS=OFF',
            '-DLLVM_INCLUDE_BENCHMARKS=OFF', '-DLLVM_INCLUDE_EXAMPLES=OFF',
            '-DCMAKE_EXE_LINKER_FLAGS=-s']


def build_pool_values(build: Path) -> dict:
    raw = patch.regular(build, 'CMakeCache.txt', 1024 * 1024)
    expected = {b'LLVM_PARALLEL_COMPILE_JOBS:STRING': str(BUILD_JOBS).encode(),
                b'LLVM_PARALLEL_LINK_JOBS:STRING': str(LINK_JOBS).encode(),
                b'CMAKE_GENERATOR:INTERNAL': b'Ninja'}
    for key, value in expected.items():
        matches = re.findall(rb'^' + re.escape(key) + rb'=([^\r\n]*)\r?$', raw, re.MULTILINE)
        if matches != [value]:
            raise ValueError('llvm-producer-build-pool-cache')
    return {'compileJobs': BUILD_JOBS, 'linkJobs': LINK_JOBS,
            'cache': {'bytes': len(raw), 'sha256': patch.sha(raw)}}


def llvm_checks(run: Commands, build: Path, source: Path) -> dict:
    unit_xml = run.root / 'units.xml'
    run.run('ssa-updater-bulk-units', build / 'unittests/Transforms/Utils/UtilsTests',
            '--gtest_filter=SSAUpdaterBulk.*', '--gtest_output=xml:' + str(unit_xml), seconds=300)
    unit_result = results.units(patch.regular(run.root, 'units.xml', 256 * 1024))
    lit_xml = run.root / 'lit.xml'
    tests = [build / 'test' / Path(row['path']).relative_to('llvm/test')
             for row in results.selection()['wasmTests']]
    run.run('sjlj-and-private-scalar-lit', sys.executable, build / 'bin/llvm-lit', '-v', '--no-progress-bar',
            '--timeout=60', '--xunit-xml-output=' + str(lit_xml), *tests, seconds=600)
    lit_result = results.lit(patch.regular(run.root, 'lit.xml', 256 * 1024))
    # The original, hash-bound dedicated PHI regression also crosses the actual
    # target passes and verifier into instruction selection, with finite output.
    projected = run.root / 'sjlj-through-wineh.ll'
    run.run('sjlj-phi-through-wineh', build / 'bin/opt',
            source / results.selection()['crossPass'], '-wasm-lower-em-ehsjlj', '-wasm-enable-sjlj',
            '-win-eh-prepare', '-demote-catchswitch-only', '-verify-each',
            '-wasm-use-legacy-eh=false', '-S', '-o', projected, seconds=60)
    cross = results.cross_pass(patch.regular(run.root, projected.name, 256 * 1024))
    obj = run.root / 'sjlj-through-wineh.o'
    run.run('sjlj-phi-instruction-selection', build / 'bin/llc', projected,
            '-wasm-enable-eh', '-wasm-enable-sjlj', '-exception-model=wasm',
            '-mattr=+exception-handling,+reference-types,+multivalue',
            '-wasm-use-legacy-eh=false', '-filetype=obj', '-o', obj, seconds=60)
    raw = patch.regular(run.root, obj.name)
    if raw[:8] != b'\0asm\x01\0\0\0':
        raise ValueError('llvm-producer-cross-pass-object')
    cross['object'] = {'bytes': len(raw), 'sha256': patch.sha(raw)}
    return {'units': unit_result, 'sjljAndPrivateScalar': lit_result, 'crossPass': cross}


def read_configuration(build: Path) -> tuple[dict, dict[str, bytes]]:
    """Validate available configuration before build cost, without writes."""
    pools = build_pool_values(build)
    rules = patch.regular(build, 'CMakeFiles/rules.ninja', 1024 * 1024)
    for name, depth in [('compile_job_pool', BUILD_JOBS), ('link_job_pool', LINK_JOBS)]:
        matches = re.findall(rb'^pool ' + name.encode() + rb'\r?\n[ ]+depth = ([0-9]+)\r?$',
                             rules, re.MULTILINE)
        if matches != [str(depth).encode()]:
            raise ValueError('llvm-producer-ninja-pools')
    retained, files = {}, {}
    for source, destination in [('CMakeCache.txt', 'retained-CMakeCache.txt'),
                                ('CMakeFiles/rules.ninja', 'retained-rules.ninja')]:
        raw = patch.regular(build, source, 1024 * 1024)
        files[destination] = raw
        retained[destination] = {'bytes': len(raw), 'sha256': patch.sha(raw)}
    return {'pools': pools, 'files': retained}, files


def retain_configuration(root: Path, build: Path) -> dict:
    value, files = read_configuration(build)
    for destination, raw in files.items():
        with (root / destination).open('xb') as stream:
            stream.write(raw)
    return value


def elf_closure(raw: bytes, role: str) -> dict:
    if len(raw) > 4 * 1024 ** 2 or role not in {'driver', 'llvm', 'clang'}:
        raise ValueError('llvm-producer-elf-role')
    text = raw.decode('utf-8')
    needed = re.findall(r'\(NEEDED\)\s+Shared library: \[([^\]\r\n]+)\]', text)
    rpaths = re.findall(r'\((?:RUNPATH|RPATH)\)\s+Library (?:runpath|rpath): \[([^\]\r\n]+)\]', text)
    sonames = re.findall(r'\(SONAME\)\s+Library soname: \[([^\]\r\n]+)\]', text)
    required = {'driver': {LLVM_SONAME, CLANG_SONAME}, 'llvm': set(), 'clang': {LLVM_SONAME}}[role]
    expected_sonames = {'driver': [], 'llvm': [LLVM_SONAME], 'clang': [CLANG_SONAME]}[role]
    if (len(needed) != len(set(needed)) or not required <= set(needed)
            or not set(needed) <= required | HOST_LIBRARIES
            or rpaths != ['$ORIGIN/../lib'] or sonames != expected_sonames):
        raise ValueError('llvm-producer-compiled-library-binding')
    return {'needed': needed, 'rpath': rpaths, 'soname': sonames,
            'raw': {'bytes': len(raw), 'sha256': patch.sha(raw)}}


def install_overlay(before: dict, installed: dict) -> dict:
    """Only two real profile DSOs and bounded aliases may join the drivers."""
    real_libraries = {'lib/' + LLVM_SONAME, 'lib/' + CLANG_SONAME}
    libraries = {name: row for name, row in installed.items() if name.startswith('lib/')
                 and len(Path(name).parts) == 2}
    if ({name for name, row in libraries.items() if 'link' not in row} != real_libraries
            or len(libraries) > 8):
        raise ValueError('llvm-producer-library-set')
    for name, row in libraries.items():
        if not re.fullmatch(r'lib/(?:libLLVM|libclang-cpp)[A-Za-z0-9._+-]*', name):
            raise ValueError('llvm-producer-library-name')
        seen, target = set(), name
        while 'link' in libraries.get(target, {}):
            if target in seen:
                raise ValueError('llvm-producer-library-alias')
            seen.add(target)
            link = libraries[target]['link']
            target = posixpath.normpath(posixpath.join(posixpath.dirname(target), link))
            if posixpath.isabs(link) or target not in libraries:
                raise ValueError('llvm-producer-library-alias')
        expected_target = 'lib/' + (LLVM_SONAME if name.startswith('lib/libLLVM') else CLANG_SONAME)
        if target != expected_target:
            raise ValueError('llvm-producer-library-alias')
    overlay = {}
    for name, row in installed.items():
        path = Path(name)
        compiler = path.parent == Path('bin') and re.fullmatch(r'clang(?:-21|\+\+|-cl|-cpp)?', path.name)
        if name.startswith('lib/clang/21/include/'):
            if before.get(name) != row:
                raise ValueError('llvm-producer-resource-header-drift')
        elif compiler or name in libraries:
            overlay[name] = row
        else:
            raise ValueError('llvm-producer-unexpected-install-member')
    if 'bin/clang-21' not in overlay or 'link' in overlay['bin/clang-21']:
        raise ValueError('llvm-producer-incomplete-compiler-install')
    return overlay


def prepare_install(run: Commands, original: Path, install: Path, readelf: Path) -> dict:
    before = io.inventory(original, io.SDK_BYTES, run.deadline)
    installed = io.inventory(install, io.PRODUCT_BYTES, run.deadline)
    overlay = install_overlay(before, installed)
    allowed = set(installed)
    allowed.update('lib/clang/21/include/' + name for name in
                   io.entry_names(original / 'lib/clang/21/include', run.deadline))
    for name in tuple(allowed):
        allowed.update(parent.as_posix() for parent in Path(name).parents if parent.parts)
    if io.entry_names(install, run.deadline) != allowed:
        raise ValueError('llvm-producer-install-directory-set')
    closure = {}
    for role, stage, member in [
            ('driver', 'compiled-clang-dynamic-dependencies', 'bin/clang-21'),
            ('llvm', 'compiled-llvm-dynamic-dependencies', 'lib/' + LLVM_SONAME),
            ('clang', 'compiled-clang-cpp-dynamic-dependencies', 'lib/' + CLANG_SONAME)]:
        closure[role] = elf_closure(run.run(stage, readelf, '--dynamic', '--wide',
                                           install / member, seconds=30), role)
        closure[role]['member'] = member
        closure[role]['identity'] = installed[member]
    return {'before': before, 'installed': installed, 'overlay': overlay, 'closure': closure}


def package(run: Commands, original: Path, install: Path, prepared: dict) -> dict:
    """Fresh derived SDK; preserve EVERY original runtime/sysroot/lld member."""
    before, installed = prepared['before'], prepared['installed']
    if (io.inventory(original, io.SDK_BYTES, run.deadline) != before
            or io.inventory(install, io.PRODUCT_BYTES, run.deadline) != installed):
        raise ValueError('llvm-producer-prepared-install-mutated')
    existing = io.entry_names(run.root, run.deadline)
    evidence = {name for name in existing if Path(name).parts[0] not in {
        'llvm-source', 'official-sdk', 'fresh-install'}}
    if len(evidence) > 512 or any(Path(name).parts[0] in {'build', 'products'} for name in existing):
        raise ValueError('llvm-producer-evidence-entry-bound')
    proposed = {'products', 'products/toolchain'}
    proposed.update('products/toolchain/' + name for name in io.entry_names(original, run.deadline))
    proposed.update('products/toolchain/' + name for name in prepared['overlay'])
    proposed.update('products/' + name for name in distribution.TOP - {'toolchain'})
    proposed.update({distribution.ARCHIVE, distribution.ARCHIVE + '.part', distribution.MANIFEST,
                     'upload-admission.json', 'result.json'})
    for offset, stage in enumerate(['packaged-derived-clang-version', 'final-repository-head']):
        proposed.update(f'commands/{len(run.records) + offset:02d}-{stage}.{channel}.log'
                        for channel in ['stdout', 'stderr'])
    future_evidence = evidence | {name for name in proposed if Path(name).parts[0] != 'products'}
    if len(future_evidence) > 512:
        raise ValueError('llvm-producer-evidence-entry-bound')
    projection = io.project_entries(existing, proposed)
    products = io.fresh(run.root / 'products')
    target = products / 'toolchain'
    shutil.copytree(original, target, symlinks=True)
    if io.inventory(target, io.PRODUCT_BYTES, run.deadline) != before:
        raise ValueError('llvm-producer-sdk-copy-identity')
    changed, added, omitted = [], [], []
    for name, row in prepared['overlay'].items():
        path = Path(name)
        compiler = path.parent == Path('bin') and re.fullmatch(r'clang(?:-21|\+\+|-cl|-cpp)?', path.name)
        library = path.parent == Path('lib')
        if library and name in before:
            # A build-time unversioned alias may collide. Keep the original
            # alias/libraries for original lld and record the omitted new link.
            # The new compiler must work without it in the subsequent real
            # packaged --version test; no library-path injection is permitted.
            if 'link' not in row or PROFILE not in Path(row['link']).name:
                raise ValueError('llvm-producer-original-library-collision')
            omitted.append(name)
            continue
        destination = target / name
        if destination.parent.is_symlink() or not destination.parent.resolve().is_relative_to(target):
            raise ValueError('llvm-producer-package-parent')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or destination.exists():
            if not compiler:
                raise ValueError('llvm-producer-package-collision')
            destination.unlink()
        if 'link' in row:
            destination.symlink_to(row['link'])
        else:
            shutil.copy2(install / name, destination)
        (changed if name in before else added).append(name)
    if (not any(name.startswith('bin/clang') for name in changed)
            or not {'lib/' + LLVM_SONAME, 'lib/' + CLANG_SONAME} <= set(added)):
        raise ValueError('llvm-producer-incomplete-compiler-install')
    original_version = patch.regular(original, 'VERSION', 1024)
    if original_version.decode().splitlines() != OFFICIAL_VERSION:
        raise ValueError('llvm-producer-official-version')
    (products / 'official-origin-VERSION').write_bytes(original_version)
    retained_sources = {}
    for member, source in [('LLVM-LICENSE.txt', 'tools/data/java-llvm-ssa/LICENSE.txt'),
                           ('LLVM-PATCH.json', 'tools/data/java-llvm-ssa/patch.json'),
                           ('LLVM-PRIVATE-STORES.json', 'tools/data/java-llvm-private-stores/supplement.json'),
                           ('NOTICE', 'NOTICE')]:
        raw = patch.regular(ROOT, source)
        (products / member).write_bytes(raw)
        retained_sources[member] = {'bytes': len(raw), 'sha256': patch.sha(raw)}
    derived_version = [OFFICIAL_VERSION[0] + '-' + PROFILE, *OFFICIAL_VERSION[1:],
                       'lsf-llvm-patch-sha256: ' + patch.PATCH_SHA256]
    (target / 'VERSION').write_bytes(('\n'.join(derived_version) + '\n').encode())
    after = io.inventory(target, io.PRODUCT_BYTES, run.deadline)
    for name, identity in before.items():
        if name not in changed and name != 'VERSION' and after.get(name) != identity:
            raise ValueError('llvm-producer-original-runtime-mutated')
    banner = run.run('packaged-derived-clang-version', target / 'bin/clang', '--version', seconds=30).decode()
    if '21.1.4' + SUFFIX not in banner:
        raise ValueError('llvm-producer-derived-compiler-version')
    if io.inventory(original, io.SDK_BYTES, run.deadline) != before:
        raise ValueError('llvm-producer-original-sdk-mutated')
    return {'baseSdk': before, 'derivedSdk': after, 'changedCompilerMembers': sorted(changed),
            'addedCompilerMembers': sorted(added), 'omittedBuildTimeAliases': sorted(omitted),
            'originalVersion': OFFICIAL_VERSION, 'derivedVersion': derived_version,
            'officialArchive': io.SDK_SOURCE, 'runtimeSysrootLldPreserved': True,
            'compiledElfClosure': prepared['closure'], 'copyEntryProjection': projection,
            'customLlvmLibrary': LLVM_SONAME, 'customClangLibrary': CLANG_SONAME,
            'retainedSourceNotices': retained_sources}


def produce(output: Path) -> dict:
    origin = admission(output)
    root = io.fresh(output)
    deadline = time.monotonic() + origin['remainingSeconds']
    run = Commands(root, deadline)
    frozen = recipe()
    record = {'schemaVersion': 'latent.java.llvm-private-scalar-producer.v1', 'status': 'running',
              'source': origin, 'recipeInputs': frozen, 'llvmCommit': patch.LLVM,
              'sdkSourceCommit': patch.SDK, 'profile': PROFILE, 'buildJobs': BUILD_JOBS,
              'compileJobs': BUILD_JOBS, 'linkJobs': LINK_JOBS,
              'buildCommandSeconds': BUILD_SECONDS,
              'aggregateSeconds': SECONDS, 'productByteLimit': io.PRODUCT_BYTES,
              'disk': {'preflightFreeBytes': shutil.disk_usage(root).free, 'minimumFreeBytes': io.MINIMUM_FREE,
                       'ownedLogicalByteBudget': io.MAX_OWNED_BYTES, 'reserveBytes': io.FREE_RESERVE,
                       'entryLimit': io.MAX_ENTRIES, 'sourceByteLimit': io.SOURCE_BYTES,
                       'sdkExtractionByteLimit': io.SDK_BYTES, 'sampleSeconds': 10,
                       'operationalBudgetNotFilesystemQuota': True},
              'javaComponentQualification': False, 'javaRuntimeQualification': False}
    try:
        # Retain measured space even when refusing before acquisition/build.
        # Only this fresh result directory exists at this point.
        io.preflight(root)
        io.case_sensitive(root)
        record['hostCapacity'] = io.host_capacity()
        if record['hostCapacity']['status'] != 'admitted':
            raise ValueError('llvm-producer-host-capacity')
        record['litTimeoutSupport'] = lit_timeout_support()
        tools = {}
        for name in ('git', 'cmake', 'ninja', 'gcc', 'g++', 'readelf'):
            value = shutil.which(name, path=run.env.get('PATH'))
            if value is None:
                raise ValueError('llvm-producer-host-tool-missing:' + name)
            tools[name] = Path(value).resolve(strict=True)
            run.run('host-' + name.replace('+', 'p') + '-version', tools[name], '--version', seconds=30)
        tools['python'] = Path(sys.executable).resolve(strict=True)
        run.run('host-python-version', tools['python'], '--version', seconds=30)
        record['hostTools'] = {name: file_identity(path, name) for name, path in tools.items()}
        if run.run('repository-head', tools['git'], 'rev-parse', 'HEAD', cwd=ROOT).decode().strip() != origin['sourceCommit']:
            raise ValueError('llvm-producer-repository-head')
        archive = root / 'wasi-sdk-29.tar.gz'
        record['sdkArchive'] = io.acquire('sdk', archive, deadline)
        original = io.extract('sdk', archive, root / 'official-sdk', deadline)
        llvm_archive = root / 'llvm-project-21.1.4.src.tar.xz'
        record['llvmArchive'] = io.acquire('llvm', llvm_archive, deadline)
        source = io.extract('llvm', llvm_archive, root / 'llvm-source', deadline)
        git = tools['git']
        record['sourceDisk'] = io.tree_size(source, io.SOURCE_BYTES, deadline=deadline)
        record['originalSource'] = source_state(run, source, False)
        record['patch'] = patch.apply(source)
        record['patchedSource'] = source_state(run, source, True)
        write(root / 'source.json', {'before': record['originalSource'], 'patch': record['patch'],
                                     'after': record['patchedSource']})
        record['earlyPackageProjection'] = io.early_package_projection(root, original, deadline)
        build, install = root / 'build', root / 'fresh-install'
        run.run('configure-reviewed-llvm', *configure(build, source, install, tools), seconds=600)
        record['initialConfiguration'], _ = read_configuration(build)
        record['buildPools'] = record['initialConfiguration']['pools']
        run.run('build-reviewed-llvm-and-tests', tools['cmake'], '--build', build, '--parallel', str(BUILD_JOBS),
                '--target', 'clang', 'LLVM', 'opt', 'llc', 'FileCheck', 'not', 'count', 'llvm-config',
                'UtilsTests', 'clang-resource-headers', seconds=BUILD_SECONDS)
        record['tests'] = llvm_checks(run, build, source)
        run.run('install-reviewed-compiler', tools['cmake'], '--build', build, '--parallel', '2',
                '--target', 'install-clang', 'install-LLVM', 'install-clang-cpp',
                'install-clang-resource-headers', seconds=300)
        prepared = prepare_install(run, original, install, tools['readelf'])
        record['retainedConfiguration'] = retain_configuration(root, build)
        if record['retainedConfiguration'] != record['initialConfiguration']:
            raise ValueError('llvm-producer-final-configuration-mutated')
        with owned_cancellation() as signals:
            record['buildRetirement'] = io.retire_build(root, deadline, signals)
        record['products'] = package(run, original, install, prepared)
        record['distribution'] = distribution.create(root, origin['sourceCommit'], deadline)
        record['finalSource'] = source_state(run, source, True)
        if (recipe() != frozen or record['finalSource'] != record['patchedSource']
                or io.authenticate_archive('sdk', archive, deadline) != record['sdkArchive']
                or io.authenticate_archive('llvm', llvm_archive, deadline) != record['llvmArchive']
                or run.run('final-repository-head', git, 'rev-parse', 'HEAD', cwd=ROOT).decode().strip() != origin['sourceCommit']):
            raise ValueError('llvm-producer-final-input-identity')
        io.tree_size(root / 'products', io.PRODUCT_BYTES, deadline=deadline)
        record['finalOwnedDisk'] = io.tree_size(root, io.MAX_OWNED_BYTES, deadline=deadline)
        if len({name for name in io.entry_names(root, deadline) if Path(name).parts[0] not in {
                'llvm-source', 'official-sdk', 'fresh-install', 'products'}}) > 512:
            raise ValueError('llvm-producer-evidence-entry-bound')
        if time.monotonic() >= deadline:
            raise ValueError('llvm-producer-deadline')
        record['status'] = 'passed'
    except BaseException as error:
        record['status'] = 'failed'
        reason = error.reason if isinstance(error, build_process.BuildProcessError) else str(error)
        record['failure'] = reason if re.fullmatch(r'[A-Za-z0-9:+.-]{1,160}', reason) else type(error).__name__
        raise
    finally:
        record['commands'] = len(run.records)
        record['maximumObservedOwnedDiskBytes'] = run.maximum_disk
        record['remainingSeconds'] = round(deadline - time.monotonic(), 6)
        write(root / 'result.json', record)
    if time.monotonic() >= deadline:
        record.update(status='failed', failure='llvm-producer-deadline')
        write(root / 'result.json', record)
        raise ValueError('llvm-producer-deadline')
    return record
