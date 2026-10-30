#!/usr/bin/env python3
"""Build exact compiler inputs and optional core diagnostic; no guest qualification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import rust_standard_sysroot_build as std
from tools import rust_thread_guard_controls as result_controls
from tools.build_observation import build_environment, file_identity
from tools.captured_compiler_isolation import distribution
from tools.dev_workflow.common import encode, require
from tools.qualify_rust_standard_clocks import source_archive
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import checked_path, decode_json, digest, fresh, read_file, write_json

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = '.github/workflows/rust-owned-thread-inputs.yml'
CRATE = 'crates/latent-component-threading/'
NATIVE_TLS_TEST = 'sdk/rust-standard-runtime/tests/thread_tls_native.rs'
CRATE_SOURCES = tuple(CRATE + 'src/' + name for name in (
    'lib.rs', 'thread_entry.rs', 'root.rs', 'public_root.rs', 'admission.rs', 'component.rs',
    'c_abi.rs', 'c_component.rs', 'c_context.rs', 'c_lifecycle.rs',
    'c_preimage.rs', 'c_root.rs', 'c_template.rs', 'bin/c-context.rs', 'bin/rust-context.rs',
    'rust_objects.rs', 'rust_component.rs', 'rust_catalogue.rs',
    'rust_catalogue/original-body-image.bin', 'rust_catalogue/origin.json',
    'rust_catalogue/normal-component-shell.bin', 'rust_catalogue/original-wit-metadata.bin',
    'rust_catalogue/adapted-wit-metadata.bin',
    'rust_catalogue/original-producers.bin', 'rust_catalogue/encoded-producers.bin',
    'rust_catalogue/reviewed-original-core.wasm', 'rust_catalogue/reviewed-normal-component.wasm'))
RECIPE = tuple(dict.fromkeys((
    'tools/compile_rust_owned_thread_inputs.py', WORKFLOW, '.cargo/config.toml',
    'tools/requirements.lock', 'tools/qualify_rust_standard_clocks.py',
    'tools/qualify_rust_standard_clock.py', CRATE + 'Cargo.toml',
    'tools/rust_capsule_project.py', 'tools/build_snapshot.py',
    'tools/dev_workflow/common.py', 'tools/application_dependency_store.py',
    'tools/rust_standard_logging_inputs.py', 'tools/rust_application_dependencies.py',
    'tools/rust_standard_thread_capture.py', 'tools/rust_owned_thread_component.py',
    *result_controls.RECIPE, *CRATE_SOURCES, *std.recipe(threads=True), NATIVE_TLS_TEST)))


def git(*args, input=None):
    result = subprocess.run(['git', *args], input=input, cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        env=build_environment(ROOT))
    require(result.returncode == 0 and len(result.stdout) <= 16 * 1024 * 1024
            and len(result.stderr) <= 65536, 'rust-thread-inputs-git-read')
    return result.stdout


def sources(expected, application_diagnostic=False):
    require(re.fullmatch('[0-9a-f]{40}', expected) is not None,
            'rust-thread-inputs-expected-head')
    require(git('rev-parse', '--verify', 'HEAD').decode().strip() == expected
            and not git('status', '--porcelain=v1', '--untracked-files=no'),
            'rust-thread-inputs-clean-exact-head')
    require(type(application_diagnostic) is bool, 'rust-thread-inputs-diagnostic-selector')
    selected = RECIPE
    if application_diagnostic:
        from tools import compile_rust_owned_thread_application as application
        selected = tuple(dict.fromkeys((*RECIPE, *application.RECIPE)))
    require(len(selected) <= 256, 'rust-thread-inputs-source-count')
    queries = ''.join(expected + ':' + name + '\n' for name in selected).encode()
    raw = git('cat-file', '--batch', input=queries)
    offset, total, rows = 0, 0, []
    for name in selected:
        end = raw.find(b'\n', offset)
        require(end >= offset, 'rust-thread-inputs-git-header')
        fields = raw[offset:end].split()
        require(len(fields) == 3 and fields[1] == b'blob' and fields[2].isdigit(),
                'rust-thread-inputs-git-blob')
        size = int(fields[2]); offset = end + 1; total += size
        require(size <= 4 * 1024 * 1024 and total <= 16 * 1024 * 1024,
                'rust-thread-inputs-source-byte-bound')
        value = raw[offset:offset + size]; offset += size
        require(raw[offset:offset + 1] == b'\n'
                and value == read_file(ROOT / name, 4 * 1024 * 1024),
                'rust-thread-inputs-source-preimage')
        offset += 1
        rows.append({'path': name, 'gitBlob': fields[0].decode(),
                     'digest': digest(value), 'size': size})
    require(offset == len(raw), 'rust-thread-inputs-git-trailing-data')
    return {'head': expected, 'tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
            'files': rows, 'totalBytes': total}


def emitted_tool(raw, target):
    require(len(raw) <= 4 * 1024 * 1024, 'rust-thread-inputs-cargo-output-bound')
    selected, finished = [], False
    rows = raw.splitlines()
    require(len(rows) <= 8192, 'rust-thread-inputs-cargo-record-bound')
    for line in rows:
        item = decode_json(line)
        require(isinstance(item, dict) and not finished, 'rust-thread-inputs-cargo-terminal')
        if item.get('reason') == 'build-finished':
            require(item.get('success') is True, 'rust-thread-inputs-tool-build-failed')
            finished = True
        if item.get('reason') != 'compiler-artifact' or item.get('target', {}).get('name') != 'rust-context':
            continue
        require(item['target'].get('kind') == ['bin'] and item.get('profile', {}).get('test') is False
                and item.get('manifest_path') == str(ROOT / CRATE / 'Cargo.toml'),
                'rust-thread-inputs-tool-target')
        value = item.get('executable')
        require(isinstance(value, str), 'rust-thread-inputs-tool-path')
        path = checked_path(Path(value))
        require(path.is_relative_to(target), 'rust-thread-inputs-tool-outside-target')
        selected.append(path)
    require(finished and len(selected) == 1, 'rust-thread-inputs-tool-emission-closure')
    return selected[0]


def retained_files(output):
    rows, total = [], 0
    for path in sorted(output.rglob('*')):
        checked_path(path)
        if path.is_dir():
            continue
        size = path.stat().st_size; total += size
        require(size <= std.MAX_ARTIFACT_BYTES and total <= 128 * 1024 * 1024
                and len(rows) < 512, 'rust-thread-inputs-artifact-bound')
        raw = read_file(path, std.MAX_ARTIFACT_BYTES)
        rows.append({'path': path.relative_to(output).as_posix(), 'digest': digest(raw), 'size': len(raw)})
    return rows


def run(output, rust_bin, expected_head, *, application_diagnostic=False):
    started = time.monotonic()
    output = fresh(output); rust_bin = checked_path(rust_bin)
    summary = {'schemaVersion': 'latent.rust.owned-thread-inputs.v1', 'status': 'in-progress',
        'actualGuestExecuted': False, 'ordinaryThreadPoolQualified': False,
        'privateExecutorGraphAuthenticated': False, 'canonicalCreationEnabled': False,
        'installedCompilerChanged': False, 'runtimeHostProductsBuilt': False,
        'kernelBuiltOrBooted': False, 'stage': 'source'}
    commands = None
    try:
        original = sources(expected_head, application_diagnostic)
        write_json(output / 'source-inputs.json', original)
        tools = {name: checked_path(rust_bin / name) for name in ('cargo', 'rustc')}
        identities = {name: file_identity(path, name) for name, path in tools.items()}
        compiler = distribution(rust_bin.parent)
        compiler_raw = encode(compiler)
        require(len(compiler_raw) <= 1024 * 1024, 'rust-thread-inputs-compiler-inventory-bound')
        (output / 'compiler-distribution.json').write_bytes(compiler_raw)
        summary['tools'] = identities
        summary['compilerDistributionDigest'] = digest(compiler_raw)
        summary['stage'] = 'source-archive'
        archive = output / 'rust-src-1.97.1.tar.xz'
        source_archive(archive)
        summary['sourceArchive'] = file_identity(archive, 'rust-src-1.97.1.tar.xz', 32 * 1024 * 1024)
        build_output = fresh(output / 'tool-build')
        environment = build_environment(build_output)
        target = ROOT / 'target'
        environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0',
            CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_DEBUG='0',
            CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true',
            RUSTUP_TOOLCHAIN='1.97.1', RUSTC=str(tools['rustc']))
        commands = Commands(ROOT, build_output, environment, deadline_seconds=600, command_seconds=180)
        summary['stage'] = 'tool-version'
        version = commands.run('rust-version', tools['rustc'], '--version', '--verbose').decode()
        require('release: 1.97.1\n' in version
                and 'commit-hash: 8bab26f4f68e0e26f0bb7960be334d5b520ea452\n' in version,
                'rust-thread-inputs-pinned-compiler')
        summary['stage'] = 'native-tls-controls'
        native_tls = build_output / 'thread-tls-native'
        commands.run('native-tls-build', tools['rustc'], '--edition=2024', '--test',
                     ROOT / NATIVE_TLS_TEST, '-o', native_tls)
        listed = commands.run('native-tls-list', native_tls, '--list')
        require(sum(line.endswith(b': test') for line in listed.splitlines()) == 10,
                'rust-thread-inputs-native-tls-case-closure')
        commands.run('native-tls-run', native_tls, '--test-threads=1')
        summary['nativeTlsControls'] = 10
        summary['stage'] = 'tool-build'
        cargo = commands.run('rust-context-build', tools['cargo'], 'build', '--locked',
            '--package', 'latent-component-threading', '--bin', 'rust-context', '--message-format=json')
        emitted = emitted_tool(cargo, target)
        identity = file_identity(emitted, 'rust-context', 32 * 1024 * 1024)
        (output / 'tool').mkdir()
        copied = output / 'tool/rust-context'
        shutil.copyfile(emitted, copied); copied.chmod(0o755)
        require(file_identity(copied, 'rust-context', 32 * 1024 * 1024) == identity,
                'rust-thread-inputs-tool-copy')
        summary['contextTool'] = identity
        if application_diagnostic:
            summary['stage'] = 'source-mechanism-controls'
            controls = commands.run('owned-core-source-mechanism-controls', tools['cargo'], 'test', '--locked',
                '--package', 'latent-component-threading', '--lib', '--', '--test-threads=1')
            require(b'test result: ok. 76 passed; 0 failed; 0 ignored;' in controls,
                    'rust-thread-inputs-exact-source-mechanism-controls')
            summary['sourceMechanismControlsPassed'] = 76
            summary['stage'] = 'emitted-result-guard-engine-controls'
            summary['emittedResultGuardControls'] = result_controls.run(
                commands, copied, output / 'result-guard-controls')
        summary['stage'] = 'owned-sysroot-build'
        built = std.build(archive, output / 'owned-sysroot', rust_bin, threads=True)
        require(built['profile'] == std.THREAD_PROFILE
                and built['standardThreadSourceSelected'] is True
                and built['standardThreadRuntimeQualified'] is False
                and built['compilerDistributionDigest'] == summary['compilerDistributionDigest'],
                'rust-thread-inputs-sysroot-profile')
        summary['sysrootIdentity'] = built['identity']
        if application_diagnostic:
            from tools import compile_rust_owned_thread_application as application
            summary['stage'] = 'ordinary-application-core-diagnostic'
            summary['applicationDiagnostic'] = application.run(output / 'application-diagnostic',
                rust_bin, output / 'owned-sysroot', copied, deadline=started + 600)
        summary['stage'] = 'recheck'
        require(sources(expected_head, application_diagnostic) == original, 'rust-thread-inputs-source-mutated')
        require(distribution(rust_bin.parent) == compiler
                and {name: file_identity(path, name) for name, path in tools.items()} == identities,
                'rust-thread-inputs-compiler-mutated')
        require(file_identity(archive, 'rust-src-1.97.1.tar.xz', 32 * 1024 * 1024) == summary['sourceArchive']
                and file_identity(copied, 'rust-context', 32 * 1024 * 1024) == identity,
                'rust-thread-inputs-products-mutated')
        write_json(output / 'artifact-files.json', retained_files(output))
        summary.update(status='passed-compiler-inputs-only', stage='complete',
            commands=commands.records, sourceMatchedContextToolBuilt=True,
            ownedThreadSysrootBuilt=True)
        write_json(output / 'report.json', summary)
        retained_files(output)
        return summary
    except Exception as error:
        summary.update(status='failed', commands=[] if commands is None else commands.records,
                       errorType=type(error).__name__, reason=str(error))
        write_json(output / 'FAILED.json', summary)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rust-bin', type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--application-diagnostic', action='store_true')
    args = parser.parse_args(argv)
    try:
        value = run(args.output, args.rust_bin, args.expected_head,
                    application_diagnostic=args.application_diagnostic)
        print(json.dumps({key: value[key] for key in ('status', 'contextTool', 'sysrootIdentity')}))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f'Owned Rust compiler inputs failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
