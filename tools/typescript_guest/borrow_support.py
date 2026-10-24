"""Maintained SpiderMonkey link support for the native diagnostic only.

No engine/libJS rebuild and no replacement encoding, panic, or process symbols.
"""
from __future__ import annotations
from pathlib import Path
import re
import time
from tools.rust_capsule_project import read_file, write_json
from tools.phase3_resource_identity import file_identity
from tools.typescript_guest import native_build, promise_library

RUST = '1.97.1'
CRATES = (('rust-encoding', 'rust-encoding', ''), ('rust-hooks', 'rust-hooks', ''),
          ('rust-url', 'rust-url', ''), ('multipart', 'rust-multipart', '"capi", "simd"'))
MAX_LIBRARY = 64 * 1024**2


def require(value, reason):
    if not value: raise ValueError(reason)


def manifest(source: Path, output: Path) -> dict:
    """Mirror the pinned build-crates template, preserving its complete lock."""
    cmake = read_file(source / 'cmake/build-crates.cmake').decode()
    actual = re.findall(r'^add_rust_lib\(([^ ]+) "\$\{CMAKE_CURRENT_SOURCE_DIR\}/crates/([^"\n]+)"(?: (.*))?\)$',
                        cmake, re.MULTILINE)
    expected = [(name, directory, '"' + features.replace('"', '\\"') + '"' if features else '')
                for name, directory, features in CRATES]
    require(actual == expected, 'borrow-support-maintained-crate-graph-changed')
    template = source / 'runtime/crates/staticlib-template'
    toml = read_file(template / 'Cargo.toml.in')
    rust = read_file(template / 'rust-staticlib.rs.in')
    lock = read_file(template / 'Cargo.lock')
    require(b'[dependencies]' in toml and b'crate-type = ["staticlib"]' in toml,
            'borrow-support-maintained-template-changed')
    for name, directory, features in CRATES:
        path = (source / 'crates' / directory).resolve(strict=True)
        require(path.is_relative_to(source.resolve(strict=True)) and path.is_dir()
                and all(char not in path.as_posix() for char in ('"', '\\', '\r', '\n')), 'borrow-support-crate-path')
        toml += (name + ' = { path = "' + path.as_posix() + '", features = [' + features + '] }\n').encode()
        rust += ('pub use ' + name.replace('-', '_') + ';\n').encode()
    require(not output.exists(), 'borrow-support-fresh-manifest')
    output.mkdir()
    (output / 'Cargo.toml').write_bytes(toml)
    (output / 'rust-staticlib.rs').write_bytes(rust)
    (output / 'Cargo.lock').write_bytes(lock)
    return {name: file_identity(output / name) for name in ('Cargo.toml', 'rust-staticlib.rs', 'Cargo.lock')}


def build(output: Path, wasi: Path, engine: Path, run, environment: dict) -> dict:
    output.mkdir()
    deadline = time.monotonic() + 300
    record = {'schemaVersion': 'latent.typescript.borrow-diagnostic-support.v1', 'status': 'in-progress',
              'scope': 'unchanged-maintained-SpiderMonkey-link-support-only', 'qualification': 'unknown',
              'apiSupport': 'not-evaluated', 'engineRebuilt': False, 'libraryJSRebuilt': False,
              'limits': {'overallSeconds': 300, 'cargoSeconds': 180, 'jobs': 2,
                         'staticLibraryBytes': MAX_LIBRARY, 'wrapperBytes': 1024**2}}
    def bounded(label, *arguments, seconds=30, **kwargs):
        remaining = min(seconds, deadline - time.monotonic())
        require(remaining > 0, 'borrow-support-deadline')
        return run(label, *arguments, seconds=remaining, **kwargs)
    stage = 'fixed-maintained-source'
    try:
        archive = output / 'starling.archive'
        record['sourceAcquisition'] = promise_library.acquire(archive, native_build.SOURCES['starling'], deadline)
        source = promise_library.extract(archive, output / 'source',
            'StarlingMonkey-' + native_build.activation.STARLING_COMMIT, deadline=deadline)
        original, links = native_build.sources(source)
        record['sources'] = {name: native_build.file_bytes(raw) for name, raw in original.items()}
        record['links'] = links
        rust_root = output / 'rust-staticlib'
        record['manifest'] = manifest(source, rust_root)
        stage = 'pinned-compiler'
        compilers = {}
        for name in ('rustc', 'cargo'):
            path = Path(bounded('support-' + name + '-path', 'rustup', 'which', '--toolchain', RUST, name).decode().strip()).resolve(strict=True)
            require(path.name == name and path.is_file(), 'borrow-support-actual-compiler-path')
            compilers[name] = path
        record['compilers'] = {name: file_identity(path, 256 * 1024**2) for name, path in compilers.items()}
        versions = {name: bounded('support-' + name + '-version', path, '--version').decode().strip()
                    for name, path in compilers.items()}
        require(all(value.startswith(name + ' ' + RUST + ' ') for name, value in versions.items()),
                'borrow-support-pinned-rust-compiler')
        record['compilerVersions'] = versions
        clang_alias = wasi / 'bin/clang++'
        clang = clang_alias.resolve(strict=True)
        require(clang.is_relative_to(wasi.resolve(strict=True)), 'borrow-support-compiler-target-escaped-sdk')
        record['clangResolvedPath'] = clang.relative_to(wasi.resolve(strict=True)).as_posix()
        record['clang'] = file_identity(clang, 256 * 1024**2)
        stage = 'maintained-staticlib'
        selected_env = dict(environment, RUSTC=str(compilers['rustc']), RUSTUP_TOOLCHAIN=RUST,
                            CARGO_BUILD_JOBS='2')
        bounded('support-cargo', compilers['cargo'], 'build', '--locked', '--manifest-path', rust_root / 'Cargo.toml',
                '--release', '--target', 'wasm32-wasip1', '--jobs', '2', '--target-dir', output / 'target',
                seconds=180, cwd=rust_root, env=selected_env)
        library = output / 'target/wasm32-wasip1/release/librust_staticlib.a'
        record['library'] = file_identity(library, MAX_LIBRARY)
        stage = 'maintained-cxx-wrappers'
        wrapper = output / 'rust-hooks-wrappers.o'
        bounded('support-wrapper', clang, '-std=c++20', '-O0', '-fno-sized-deallocation',
                '-DSTATIC_JS_API', '-DJS_STANDALONE', '-I' + str(engine / 'spidermonkey/include'),
                '-include', engine / 'spidermonkey/include/js-confdefs.h', '-c',
                source / 'crates/rust-hooks/src/wrappers.cpp', '-o', wrapper)
        record['wrapper'] = file_identity(wrapper, 1024**2)
        emulation = {}
        for name in ('signal', 'process-clocks', 'getpid'):
            filename = 'libwasi-emulated-' + name + '.a'
            path = Path(bounded('support-wasi-' + name, clang, '-print-file-name=' + filename).decode().strip()).resolve(strict=True)
            require(path.is_relative_to(wasi.resolve(strict=True)) and path.name == filename,
                    'borrow-support-normal-wasi-archive')
            emulation[name] = path
        record['wasiEmulation'] = {name: file_identity(path, 32 * 1024**2) for name, path in emulation.items()}
        stage = 'final-integrity'
        require(record['manifest'] == {name: file_identity(rust_root / name) for name in record['manifest']},
                'borrow-support-maintained-lock-or-template-changed')
        after, after_links = native_build.sources(source)
        require(original == after and links == after_links, 'borrow-support-original-source-changed')
        require(clang_alias.resolve(strict=True) == clang
                and record['compilers'] == {name: file_identity(path, 256 * 1024**2) for name, path in compilers.items()}
                and record['clang'] == file_identity(clang, 256 * 1024**2), 'borrow-support-compiler-changed')
        require(record['library'] == file_identity(library, MAX_LIBRARY)
                and record['wrapper'] == file_identity(wrapper, 1024**2)
                and record['wasiEmulation'] == {name: file_identity(path, 32 * 1024**2) for name, path in emulation.items()},
                'borrow-support-product-changed')
        promise_library.recheck_archives(output, {'starling': native_build.SOURCES['starling']},
                                       {'starling': record['sourceAcquisition']})
        require(time.monotonic() < deadline, 'borrow-support-final-deadline')
        record.update(status='passed', products={'library': str(library), 'wrapper': str(wrapper),
                                                'emulation': {name: str(path) for name, path in emulation.items()}})
        write_json(output / 'SUPPORT.json', record)
        require(time.monotonic() < deadline, 'borrow-support-final-exit-deadline')
        return record
    except BaseException as error:
        (output / 'SUPPORT.json').unlink(missing_ok=True)
        record.update(status='failed', stage=stage, reason=str(error)[:1024])
        write_json(output / 'FAILED.json', record)
        raise
