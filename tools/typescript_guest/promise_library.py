"""Bounded normal SpiderMonkey build of exact intrinsic Promise-hook sources.

This produces a source-bound library candidate, never a qualified JS runtime.
"""
from __future__ import annotations

import hashlib
import platform
import shlex
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import time
import urllib.request

from tools.build_observation import build_environment
from tools.build_process import BuildProcessError, run_bounded_result
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json
from tools.phase3_resource_identity import file_identity
from tools.typescript_guest.activation_engine import FIREFOX_COMMIT
from tools.typescript_guest.promise_engine import PREIMAGES, derive_promise_lifecycle

SOURCES = {
    'firefox': {'url': 'https://codeload.github.com/bytecodealliance/firefox/tar.gz/'+FIREFOX_COMMIT,
        'bytes': 945770760, 'sha256': '3e5bfc91042263a68910c92148d9d8c8b296fcd46a487f33d94b9822042c4307'},
    'wasi-sdk': {'url': 'https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-30/wasi-sdk-30.0-x86_64-linux.tar.gz',
        'bytes': 119449290, 'sha256': '0507679dff16814b74516cd969a9b16d2ced1347388024bc7966264648c78bfb'},
    'cbindgen': {'url': 'https://github.com/mozilla/cbindgen/releases/download/0.29.2/cbindgen-ubuntu22.04',
        'bytes': 5652752, 'sha256': 'a513332aff361143077ac3680c424fa9569c4310d3098fe3a1308c201d2ea23b'},
}
MAX_EXTRACTED = 8*1024**3
MAX_MEMBERS = 750000


def acquire(target: Path, source: dict, deadline: float) -> dict:
    """Retain original bytes, enforcing the pin while streaming, before use."""
    remaining = min(600, deadline-time.monotonic())
    if remaining <= 0:
        raise ValueError('promise-library-acquisition-deadline')
    digest, count, expires = hashlib.sha256(), 0, time.monotonic()+remaining
    with urllib.request.urlopen(source['url'], timeout=min(60, remaining)) as response, target.open('xb') as output:
        if not response.geturl().startswith('https://'):
            raise ValueError('promise-library-source-requires-https')
        while chunk := response.read(1024*1024):
            count += len(chunk)
            if count > source['bytes'] or time.monotonic() >= expires:
                raise ValueError('promise-library-acquisition-bound')
            digest.update(chunk); output.write(chunk)
    actual = {'bytes': count, 'sha256': digest.hexdigest()}
    if actual != {key: source[key] for key in actual}:
        raise ValueError('promise-library-upstream-pin-differs')
    return actual


def extract(archive: Path, target: Path, prefix: str, *, deadline: float) -> Path:
    """Validate the entire bounded carrier before extracting its regular data."""
    if not prefix or PurePosixPath(prefix).name != prefix:
        raise ValueError('promise-library-source-prefix')
    target.mkdir()
    total, count, names = 0, 0, set()

    def bounded_filter(member, destination):
        if time.monotonic() >= deadline:
            raise ValueError('promise-library-extraction-deadline')
        return tarfile.data_filter(member, destination)

    with tarfile.open(archive) as carrier:
        for member in carrier:
            path = PurePosixPath(member.name)
            if (time.monotonic() >= deadline or not path.parts or path.is_absolute() or '..' in path.parts
                    or '\\' in member.name or path.as_posix() != member.name.rstrip('/')
                    or path.parts[0] != prefix or member.name.rstrip('/') in names
                    or not (member.isdir() or member.isfile() or member.issym() or member.islnk())):
                raise ValueError('promise-library-invalid-archive-member')
            names.add(member.name.rstrip('/')); count += 1; total += member.size
            if count > MAX_MEMBERS or total > MAX_EXTRACTED or not 0 <= member.size <= 256*1024**2:
                raise ValueError('promise-library-archive-bound')
            # The standard data filter additionally rejects devices, absolute
            # link targets and links outside this owned extraction root.
            tarfile.data_filter(member, str(target))
        carrier.extractall(target, filter=bounded_filter)
    return target/prefix


def mozconfig(output: Path, wasi: Path) -> str:
    flags = ('--enable-project=js', '--disable-js-shell', '--target=wasm32-unknown-wasi',
        '--without-system-zlib', '--without-intl-api', '--disable-jit', '--disable-shared-js',
        '--disable-shared-memory', '--disable-tests', '--disable-clang-plugin', '--enable-jitspew',
        '--enable-optimize=-O3', '--enable-js-streams', '--enable-portable-baseline-interp',
        '--disable-stdcxx-compat', '--disable-debug', '--enable-lto=thin',
        '--with-sysroot='+str(wasi/'share/wasi-sysroot'), '--prefix='+str(output/'obj/dist'))
    return ''.join('ac_add_options '+shlex.quote(flag)+'\n' for flag in flags)+(
        'mk_add_options MOZ_OBJDIR='+shlex.quote(str(output/'obj'))+'\n'
        'mk_add_options MOZ_MAKE_FLAGS=-j1\nmk_add_options AUTOCLOBBER=1\n')


def build(output: Path) -> dict:
    if sys.platform != 'linux' or platform.machine() not in {'x86_64', 'AMD64'}:
        raise ValueError('promise-library-linux-x86-64-builder-required')
    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError('promise-library-output-must-be-outside-checkout')
    output = fresh(output)
    deadline = time.monotonic()+3000
    record = {'schemaVersion': 'latent.typescript.promise-library-source-build.v1', 'status': 'in-progress',
        'qualification': 'unknown', 'apiSupport': 'not-evaluated',
        'scope': 'intrinsic-hook-library-compile-only', 'applicationCompilerDeadlineSeconds': 600,
        'limits': {'overallSeconds': 3000, 'perAcquisitionSeconds': 600, 'machBuildSeconds': 1800, 'jobs': 1},
        'sources': SOURCES}
    recipe_paths = ('tools/build_typescript_promise_library.py', 'tools/typescript_guest/promise_library.py',
                    'tools/typescript_guest/promise_engine.py', 'tools/typescript_guest/activation_engine.py',
                    'sdk/typescript-guest/activation/promise_hooks.h')
    record['recipe'] = {name: file_identity(ROOT/name) for name in recipe_paths}
    stage = 'acquisition'
    try:
        identities = {}
        for name, source in SOURCES.items():
            identities[name] = acquire(output/(name+'.archive'), source, deadline)
            write_json(output/(name+'-acquisition.json'), identities[name])
        stage = 'source-extraction'
        firefox = extract(output/'firefox.archive', output/'firefox-source', 'firefox-'+FIREFOX_COMMIT, deadline=deadline)
        wasi = extract(output/'wasi-sdk.archive', output/'wasi-source', 'wasi-sdk-30.0-x86_64-linux', deadline=deadline)
        cbindgen = output/'cbindgen'
        shutil.copyfile(output/'cbindgen.archive', cbindgen); cbindgen.chmod(0o700)
        original = {name: read_file(firefox/name) for name in PREIMAGES}
        header_path = ROOT/'sdk/typescript-guest/activation/promise_hooks.h'
        header = read_file(header_path)
        derived, derivation = derive_promise_lifecycle(original, header)
        for name, body in derived.items():
            (firefox/name).write_bytes(body)
        write_json(output/'source-derivation.json', derivation)
        licenses = output/'licenses'; licenses.mkdir()
        (licenses/'Firefox-LICENSE.txt').write_bytes(read_file(firefox/'LICENSE'))
        before = {name: file_identity(firefox/name) for name in derived}
        config = output/'mozconfig'; config.write_text(mozconfig(output, wasi), encoding='utf-8')
        environment = build_environment(output)
        environment.update(CC=str(wasi/'bin/clang'), CXX=str(wasi/'bin/clang++'), AR=str(wasi/'bin/llvm-ar'),
            HOST_CC='/usr/bin/clang-18', HOST_CXX='/usr/bin/clang++-18', CBINDGEN=str(cbindgen),
            MOZCONFIG=str(config), MOZBUILD_STATE_PATH=str(output/'mozbuild-state'),
            MACH_BUILD_PYTHON_NATIVE_PACKAGE_SOURCE='system', RUSTUP_TOOLCHAIN='1.97.1', CARGO_BUILD_JOBS='1')
        environment['PATH'] = str(wasi/'bin')+':'+environment['PATH']
        record['buildTools'] = {}
        for tool, expected in (('rustc', b'rustc 1.97.1'), ('cargo', b'cargo 1.97.1'),
                               (str(cbindgen), b'cbindgen 0.29.2'), ('node', b'v24.19.0')):
            probe = run_bounded_result([tool, '--version'], output, environment,
                timeout_seconds=min(10, deadline-time.monotonic()), max_output_bytes=16384)
            if probe.returncode or not probe.stdout.strip().startswith(expected):
                raise ValueError('promise-library-build-tool-version-differs')
            record['buildTools'][Path(tool).name] = probe.stdout.decode('utf-8').strip()
        command = [sys.executable, str(firefox/'mach'), '--no-interactive', 'build']
        write_json(output/'build-command.json', {'command': command, 'maximumSeconds': 1800,
            'configurationIdentity': file_identity(config), 'sdkHeaderIdentity': file_identity(header_path)})
        stage = 'normal-mach-build'
        started = time.monotonic()
        result = run_bounded_result(command, firefox, environment,
            timeout_seconds=min(1800, deadline-time.monotonic()), max_output_bytes=4*1024*1024)
        for name in ('stdout', 'stderr'):
            (output/('mach.'+name+'.log')).write_bytes(getattr(result, name))
        record.update(machSeconds=round(time.monotonic()-started, 6), machReturnCode=result.returncode)
        if result.returncode:
            raise ValueError('promise-library-normal-mach-build-failed')
        stage = 'emitted-product-integrity'
        products = list((output/'obj').rglob('libjs_static.a'))
        if len(products) != 1:
            raise ValueError('promise-library-unique-normal-static-product-required')
        exported = output/'obj/dist/include/js/ActivationPromiseHooks.h'
        if read_file(exported) != header:
            raise ValueError('promise-library-normal-header-export-differs')
        if before != {name: file_identity(firefox/name) for name in derived} or read_file(header_path) != header:
            raise ValueError('promise-library-derived-source-changed')
        if record['recipe'] != {name: file_identity(ROOT/name) for name in recipe_paths}:
            raise ValueError('promise-library-recipe-changed')
        if identities != {name: file_identity(output/(name+'.archive'), source['bytes'])
                          for name, source in SOURCES.items()}:
            raise ValueError('promise-library-original-archive-changed')
        record.update(status='passed', library={'path': products[0].relative_to(output).as_posix(),
            **file_identity(products[0], 512*1024**2)}, derivation=derivation,
            exportedHeader=file_identity(exported), selectedSources=before,
            limitations=['Library compile only; ComponentizeJS engine, splicer and signed runtime cases remain required.',
                        'No API/default-client qualification or physical allocation bound follows from this build.'])
        write_json(output/'library-build.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage,
            reason=str(error)[:4096] if isinstance(error, (BuildProcessError, ValueError)) else type(error).__name__)
        write_json(output/'FAILED.json', record)
        raise
