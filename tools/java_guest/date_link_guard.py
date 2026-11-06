"""Bind the finite Date lowering to inspected, owned Wasm link inputs."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from tools.c_application_dependencies import wasm_object
from tools.java_guest import c_failure_context
from tools.java_guest.compiler import sdk_snapshot
from tools.java_guest.compiler_profile import admit
from tools.java_guest.date_guard import LIBC_SYMBOLS
from tools.java_guest.enum_guard import MAX_INPUT, _bindings_identity
from tools.rust_capsule_project import read_file

MAX_OWNED = 64 * 1024 * 1024
LIBRARIES = (
    ('crt1-reactor.o', 'share/wasi-sysroot/lib/wasm32-wasip1/crt1-reactor.o',
     '6751ae2953a3356d36662ad4758606549afb4de2fc6c7f8026b75f6568df0f99'),
    ('libsetjmp.a', 'share/wasi-sysroot/lib/wasm32-wasip1/libsetjmp.a',
     'd30897d3a3fafa6a7d78cb4995b35ddabfa3831561194e0385d7ab4495938c1a'),
    ('libc.a', 'share/wasi-sysroot/lib/wasm32-wasip1/libc.a',
     '7034a15b1843554fca59ad09e54488692f50704e80911087b334778ebece2f76'),
    ('libclang_rt.builtins.a', 'lib/clang/21/lib/wasm32-unknown-wasip1/libclang_rt.builtins.a',
     '906c2ca1a6254cb584c8c7e9d2a610c5f64e9343017069d00026f84a1034c5da'),
)
OBJECTS = ('main.o', 'bridge.o', 'platform.o', 'probe.o', 'component.o')
PROTECTED = LIBC_SYMBOLS | {'teavm_date_init'}


def need(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError('java-date-link-' + reason)


def identity(data: bytes) -> dict:
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def inspect_objects(objects: dict[str, bytes]) -> dict:
    need(set(objects) == set(OBJECTS), 'object-set')
    result = {}
    for name in OBJECTS:
        data = objects[name]
        need(0 < len(data) <= MAX_INPUT, 'object-bound')
        profile = wasm_object(data, include_all_symbols=True, allow_exception_tags=True)
        defined = set(profile['definedSymbols']) & PROTECTED
        need(defined == ({'teavm_date_init'} if name == 'main.o' else set()), 'object-symbols')
        if name == 'main.o':
            need('teavm_date_init' in profile['strongSymbols'], 'initializer-symbol')
        result[name] = identity(data)
    return result


def _write_new(path: Path, data: bytes) -> None:
    with path.open('xb') as out:
        out.write(data)


def _profile(compiler) -> None:
    expected = getattr(compiler, 'wasi_compiler_profile', None)
    need(type(expected) is bytes and bool(expected), 'promoted-compiler-required')
    current = admit(compiler.wasi_sdk)
    need(current is not None and current[1] == expected, 'compiler-identity')


def run(compiler, generated: Path, selected: tuple[str, ...], destination: Path,
        core: Path, sealed: bytes) -> dict:
    """Compile once, inspect each object, then link exactly those owned bytes."""
    need(time.monotonic() < compiler.deadline, 'deadline')
    _profile(compiler)
    sdk, bindings = compiler.sdk, destination / 'bindings'
    source_snapshot = sdk_snapshot(sdk)
    need(source_snapshot == compiler.original_sdk, 'sdk-before')
    binding_snapshot = _bindings_identity(bindings)
    owned = destination / 'date-link-inputs'
    owned.mkdir(mode=0o700, exist_ok=False)
    libraries = {}
    for name, relative, expected in LIBRARIES:
        data = read_file(compiler.wasi_sdk / relative, MAX_INPUT)
        need(hashlib.sha256(data).hexdigest() == expected, 'library-identity')
        _write_new(owned / name, data)
        libraries[name] = data
    common = ('-target', 'wasm32-wasip1', '-std=c11', '-O2',
              '-DLSF_JAVA_ACTIVATION_PROFILE=1', '-DLSF_TEAVM_WASM=1', '-DTEAVM_CUSTOM_LOG=1',
              '-mllvm', '-wasm-enable-sjlj', '-mllvm', '-wasm-use-legacy-eh=false',
              '-include', sdk / 'runtime/native.h',
              '-I', bindings, '-I', sdk / 'runtime', '-iquote', generated)
    compiler.run('date-main-object', 'clang', *common, '-c', '-x', 'cpp-output', '-',
                 '-o', owned / 'main.o', input_bytes=sealed)
    for name, source in (('bridge.o', bindings / 'bridge.c'),
                         ('platform.o', sdk / 'feasibility/platform.c'),
                         ('probe.o', bindings / 'probe.c')):
        compiler.run('date-' + name.removesuffix('.o') + '-object', 'clang',
                     *common, '-c', '-x', 'c', source, '-o', owned / name)
    _write_new(owned / 'component.o', read_file(bindings / 'probe_component_type.o', MAX_INPUT))
    objects = {name: read_file(owned / name, MAX_INPUT) for name in OBJECTS}
    need(sum(map(len, objects.values())) + sum(map(len, libraries.values())) <= MAX_OWNED,
         'owned-bound')
    observations = inspect_objects(objects)
    need(source_snapshot == sdk_snapshot(sdk) and binding_snapshot == _bindings_identity(bindings),
         'source-drift')

    def recheck() -> None:
        need(time.monotonic() < compiler.deadline, 'deadline')
        for name, data in {**libraries, **objects}.items():
            need(read_file(owned / name, MAX_INPUT) == data, 'owned-drift')

    recheck()
    c_failure_context.run(compiler, generated, selected, '-target', 'wasm32-wasip1', '-nostdlib',
        '-mexec-model=reactor', owned / 'crt1-reactor.o', '-Wl,--entry=_initialize', owned / 'libsetjmp.a',
        '-Wl,--no-entry', '-Wl,--export-memory', '-Wl,-z,stack-size=65536',
        '-Wl,--max-memory=67108864', *(owned / name for name in OBJECTS),
        owned / 'libc.a', owned / 'libclang_rt.builtins.a', '-o', core)
    recheck()
    need(source_snapshot == sdk_snapshot(sdk) and binding_snapshot == _bindings_identity(bindings),
         'source-drift')
    _profile(compiler)
    return {'schemaVersion': 'latent.java.date-guard-link.v1', 'objects': observations,
            'libraries': {name: identity(data) for name, data in libraries.items()},
            'sealedSha256': hashlib.sha256(sealed).hexdigest()}
